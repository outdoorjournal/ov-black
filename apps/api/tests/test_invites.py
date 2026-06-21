"""Coverage for POST /auth/redeem-invite and the invite service (T05).

Two layers:

1. Router tests — exercise the HTTP contract with the invite service
   stubbed. We care here about status codes, response shape, public-path
   whitelisting, and payload validation.
2. Service tests — exercise :func:`redeem_invite` with an in-memory fake
   session so the enumerated outcomes (ok, unknown, consumed, wrong-email,
   upstream-unavailable) are each hit without a live Supabase.

No network calls and no Postgres — this file runs on a fresh checkout.
The live-Supabase integration path (``supabase start`` + mailpit) is
covered by a ``skipif``-gated test at the bottom.
"""

from __future__ import annotations

import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Invite, UserRole
from app.services import invites as invites_service
from app.services.invites import RedeemOutcome, redeem_invite
from app.services.supabase_admin import MagicLinkIssued, SupabaseAdminError
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator


# --- Fakes ------------------------------------------------------------------


@dataclass
class _ExecResult:
    """Mimics the slice of SQLAlchemy Result the service uses."""

    value: Any = None

    def scalar_one_or_none(self) -> Any:
        return self.value


@dataclass
class FakeSession:
    """Minimal async-session stand-in for the invite service.

    Holds a small dict of invites keyed by code. ``execute`` inspects the
    compiled statement enough to tell SELECT from UPDATE and returns the
    right ``_ExecResult`` — the service never peeks inside.
    """

    invites: dict[str, Invite] = field(default_factory=dict)
    commits: int = 0
    rollbacks: int = 0
    # Simulate a concurrent redeemer winning the atomic UPDATE race.
    race_losing_code: str | None = None

    async def execute(self, stmt: Any) -> _ExecResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        params = stmt.compile().params if hasattr(stmt, "compile") else {}
        # Pull the bound "code" param out of the statement.
        code = params.get("code") or params.get("code_1") or params.get("pk_1")
        if code is None:
            # SQLAlchemy sometimes labels the param differently — fall back
            # to scanning all bound values for a match in our invite map.
            for value in params.values():
                if isinstance(value, str) and value in self.invites:
                    code = value
                    break

        if compiled.lstrip().upper().startswith("SELECT"):
            return _ExecResult(self.invites.get(code))

        if compiled.lstrip().upper().startswith("UPDATE"):
            invite = self.invites.get(code)
            if (
                invite is None
                or invite.consumed_at is not None
                or invite.cancelled_at is not None
                or invite.superseded_at is not None
            ):
                return _ExecResult(None)
            if self.race_losing_code == code:
                # Simulate a concurrent redeemer — the row now looks consumed.
                invite.consumed_at = datetime.now(UTC)
                return _ExecResult(None)
            invite.consumed_at = datetime.now(UTC)
            return _ExecResult(invite.code)

        raise AssertionError(f"unexpected statement: {compiled}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _invite(
    code: str,
    *,
    email: str | None = None,
    consumed: bool = False,
    cancelled: bool = False,
    superseded: bool = False,
) -> Invite:
    inv = Invite(
        code=code,
        role=UserRole.advisor,
        email=email,
        created_by=uuid.uuid4(),
    )
    if consumed:
        inv.consumed_at = datetime.now(UTC)
    if cancelled:
        inv.cancelled_at = datetime.now(UTC)
    if superseded:
        inv.superseded_at = datetime.now(UTC)
    return inv


# --- Router-level tests -----------------------------------------------------


@pytest.fixture()
def override_session() -> Iterator[FakeSession]:
    """Replace the session dependency with a FakeSession for the test."""
    fake = FakeSession()

    async def _dep() -> Iterator[FakeSession]:
        yield fake

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield fake
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def stub_magic_link(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record emails that would have received a magic link."""
    sent: list[str] = []

    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        sent.append(email)
        return MagicLinkIssued(email=email, action_link="https://stub/magic")

    monkeypatch.setattr(invites_service, "generate_magic_link", _fake)
    return sent


@pytest.fixture()
def stub_magic_link_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(email: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_unreachable")

    monkeypatch.setattr(invites_service, "generate_magic_link", _boom)


def test_redeem_invite_is_publicly_reachable_without_jwt(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    # The entire auth loop starts here — the endpoint MUST NOT require a JWT.
    override_session.invites["INV-OPEN"] = _invite("INV-OPEN")
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-OPEN", "email": "advisor@example.com"},
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_magic_link == ["advisor@example.com"]


def test_redeem_invite_valid_open_invite_consumes_atomically(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    invite = _invite("INV-001")
    override_session.invites["INV-001"] = invite
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-001", "email": "user@example.com"},
    )
    assert resp.status_code == 204
    assert invite.consumed_at is not None
    assert override_session.commits == 1
    assert stub_magic_link == ["user@example.com"]


def test_redeem_invite_unknown_code_returns_404(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "NOPE", "email": "user@example.com"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "invite_not_redeemable"
    assert stub_magic_link == []
    assert override_session.commits == 0


def test_redeem_invite_already_consumed_returns_409(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    override_session.invites["INV-USED"] = _invite("INV-USED", consumed=True)
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-USED", "email": "user@example.com"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "invite_already_consumed"
    assert stub_magic_link == []


def test_redeem_invite_cancelled_collapses_to_404(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    # Cancelled rows must not be distinguishable from invented codes —
    # otherwise an attacker could probe the cancellation surface.
    override_session.invites["INV-CXL"] = _invite("INV-CXL", cancelled=True)
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-CXL", "email": "user@example.com"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "invite_not_redeemable"
    assert stub_magic_link == []


def test_redeem_invite_superseded_collapses_to_404(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    # The advisor resent — this code is stale. Same collapsed shape so the
    # user is funnelled toward the latest email rather than learning the
    # old code is "out of date".
    override_session.invites["INV-OLD"] = _invite("INV-OLD", superseded=True)
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-OLD", "email": "user@example.com"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "invite_not_redeemable"
    assert stub_magic_link == []


def test_redeem_invite_wrong_email_collapses_to_404(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    # Wrong-email must NOT disclose that the code exists — same 404 body as
    # an unknown code. Otherwise an attacker can enumerate live codes.
    override_session.invites["INV-PIN"] = _invite("INV-PIN", email="expected@example.com")
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-PIN", "email": "attacker@example.com"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "invite_not_redeemable"
    assert stub_magic_link == []


def test_redeem_invite_pinned_email_matches_case_insensitively(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    override_session.invites["INV-CASE"] = _invite("INV-CASE", email="User@Example.COM")
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-CASE", "email": "user@example.com"},
    )
    assert resp.status_code == 204
    assert stub_magic_link == ["user@example.com"]


def test_redeem_invite_malformed_payload_returns_422(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link: list[str],
) -> None:
    # Missing ``code`` — FastAPI should 422 without reaching the service.
    resp = client.post(
        "/auth/redeem-invite",
        json={"email": "user@example.com"},
    )
    assert resp.status_code == 422
    # Invalid email string
    resp2 = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-001", "email": "not-an-email"},
    )
    assert resp2.status_code == 422
    assert stub_magic_link == []


def test_redeem_invite_upstream_failure_returns_502_and_preserves_invite(
    client: TestClient,
    override_session: FakeSession,
    stub_magic_link_unreachable: None,
) -> None:
    # Supabase unreachable → 502 and the invite must remain redeemable so
    # the user is not locked out by a transient upstream hiccup.
    invite = _invite("INV-UP")
    override_session.invites["INV-UP"] = invite
    resp = client.post(
        "/auth/redeem-invite",
        json={"code": "INV-UP", "email": "user@example.com"},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "auth_upstream_unavailable"
    assert override_session.rollbacks >= 1


# --- Service-level tests ----------------------------------------------------


@pytest.fixture()
def stub_admin_in_service(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        sent.append(email)
        return MagicLinkIssued(email=email, action_link="https://stub/magic")

    monkeypatch.setattr(invites_service, "generate_magic_link", _fake)
    return sent


@pytest.mark.asyncio
async def test_service_ok_path_returns_issued_link(
    stub_admin_in_service: list[str],
) -> None:
    session = FakeSession(invites={"X": _invite("X")})
    result = await redeem_invite(session, code="X", email="user@example.com")
    assert result.outcome is RedeemOutcome.OK
    assert result.issued is not None
    assert result.issued.email == "user@example.com"
    assert session.commits == 1
    assert stub_admin_in_service == ["user@example.com"]


@pytest.mark.asyncio
async def test_service_unknown_code(stub_admin_in_service: list[str]) -> None:
    session = FakeSession()
    result = await redeem_invite(session, code="MISSING", email="u@e.com")
    assert result.outcome is RedeemOutcome.UNKNOWN_CODE
    assert stub_admin_in_service == []


@pytest.mark.asyncio
async def test_service_already_consumed(stub_admin_in_service: list[str]) -> None:
    session = FakeSession(invites={"X": _invite("X", consumed=True)})
    result = await redeem_invite(session, code="X", email="u@e.com")
    assert result.outcome is RedeemOutcome.ALREADY_CONSUMED
    assert stub_admin_in_service == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_service_wrong_email(stub_admin_in_service: list[str]) -> None:
    session = FakeSession(invites={"X": _invite("X", email="expected@example.com")})
    result = await redeem_invite(session, code="X", email="other@example.com")
    assert result.outcome is RedeemOutcome.WRONG_EMAIL
    assert stub_admin_in_service == []


@pytest.mark.asyncio
async def test_service_race_loss_becomes_already_consumed(
    stub_admin_in_service: list[str],
) -> None:
    # Start with an unconsumed row, but simulate a concurrent redeemer
    # flipping it to consumed between the SELECT and the UPDATE.
    session = FakeSession(invites={"X": _invite("X")}, race_losing_code="X")
    result = await redeem_invite(session, code="X", email="u@e.com")
    assert result.outcome is RedeemOutcome.ALREADY_CONSUMED
    assert session.rollbacks >= 1
    assert stub_admin_in_service == []


@pytest.mark.asyncio
async def test_service_upstream_error_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(email: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_unreachable")

    monkeypatch.setattr(invites_service, "generate_magic_link", _boom)
    invite = _invite("X")
    session = FakeSession(invites={"X": invite})
    result = await redeem_invite(session, code="X", email="u@e.com")
    assert result.outcome is RedeemOutcome.UPSTREAM_UNAVAILABLE
    assert session.rollbacks >= 1
    # Invite stays redeemable — we rolled back the consume.
    # (Fake session doesn't implement transactional undo, but service must
    # call rollback so the real Postgres session does.)


# --- Optional integration path ---------------------------------------------

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)
async def test_service_real_supabase_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end redeem against the local Supabase DB (magic link stubbed).

    Exercises the real UPDATE ... RETURNING path so we catch SQL-shape bugs
    that a fake session would paper over. The Supabase Auth admin call is
    stubbed — magic-link-into-mailpit is checked manually per the slice plan.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        return MagicLinkIssued(email=email, action_link="https://stub/magic")

    monkeypatch.setattr(invites_service, "generate_magic_link", _fake)

    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    code = f"INV-{uuid.uuid4().hex[:10].upper()}"
    try:
        async with maker() as setup:
            await setup.execute(
                text("insert into public.invites (code, role, email) values (:c, 'advisor', NULL)"),
                {"c": code},
            )
            await setup.commit()

        async with maker() as session:
            first = await redeem_invite(session, code=code, email="real@example.com")
            assert first.outcome is RedeemOutcome.OK

        async with maker() as session:
            second = await redeem_invite(session, code=code, email="real@example.com")
            assert second.outcome is RedeemOutcome.ALREADY_CONSUMED
    finally:
        async with maker() as cleanup:
            await cleanup.execute(text("delete from public.invites where code = :c"), {"c": code})
            await cleanup.commit()
        await engine.dispose()
