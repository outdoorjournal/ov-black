"""Coverage for the resend-welcome action (replaces the invite reissue/cancel).

Two layers, mirroring the rest of the clients suite:

- Service tests against a fake async session — every outcome of
  ``resend_welcome_email`` is exercised deterministically without Postgres
  or live Supabase.
- Router tests stub the service entry point and assert the HTTP contract
  (status codes, advisor-only enforcement, collapsed 404 for cross-advisor
  reads).

Resend doubles as the invite-later action (ADV-1): the *first* send to a
silently-created (``uninvited``) client stamps ``invited_at`` — one DB write
that flips it to ``pending`` — while a re-send to an already-invited client
does no write. The fakes answer the single advisor-scoped client lookup and
count commits so both facets are distinguishable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Client
from app.routers import clients as clients_router_module
from app.services import clients as clients_service
from app.services.clients import (
    ResendWelcomeOutcome,
    ResendWelcomeResult,
    resend_welcome_email,
)
from app.services.supabase_admin import MagicLinkIssued, SupabaseAdminError
from fastapi import HTTPException
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


# ── Service-level fakes ─────────────────────────────────────────────────────


@dataclass
class _ExecResult:
    rows: list[Any] = field(default_factory=list)

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None


@dataclass
class FakeServiceSession:
    """Answers the single ``select(Client).where(id, owner_id)`` lookup."""

    clients: list[Client] = field(default_factory=list)
    commits: int = 0

    async def execute(self, stmt: Any) -> _ExecResult:
        compiled = stmt.compile()
        params = compiled.params
        uuids = [v for v in params.values() if isinstance(v, uuid.UUID)]
        wanted_id = uuids[0] if uuids else None
        owner_id = uuids[1] if len(uuids) > 1 else None
        for c in self.clients:
            if c.id == wanted_id and (owner_id is None or c.owner_id == owner_id):
                return _ExecResult([c])
        return _ExecResult([])

    async def commit(self) -> None:
        self.commits += 1


def _client_row(
    advisor_id: uuid.UUID,
    *,
    email: str = "client@example.com",
    accepted: bool = False,
    invited: bool = False,
) -> Client:
    row = Client(owner_id=advisor_id, full_name="Jane Traveler", email=email)
    row.id = uuid.uuid4()
    row.created_at = datetime.now(UTC)
    row.updated_at = row.created_at
    # invited_at set == a welcome link was already issued ("pending"); left
    # None models a silently-created ("uninvited") client whose first invite
    # this send is. ``accepted`` implies invited.
    row.invited_at = datetime.now(UTC) if (invited or accepted) else None
    row.auth_user_id = uuid.uuid4() if accepted else None
    row.accepted_at = datetime.now(UTC) if accepted else None
    return row


@pytest.fixture()
def stub_admin_ok(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _fake(email: str, redirect_to: str, **_kwargs: Any) -> MagicLinkIssued:
        calls.append((email, redirect_to))
        return MagicLinkIssued(email=email, action_link="https://stub/welcome-link")

    monkeypatch.setattr(clients_service, "generate_invite_link", _fake)
    return calls


@pytest.fixture()
def stub_admin_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(email: str, redirect_to: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_unreachable")

    monkeypatch.setattr(clients_service, "generate_invite_link", _boom)


# ── Service: resend ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_invite_of_uninvited_client_stamps_invited_at(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    """Invite-later (ADV-1): the first send to a silent client stamps invited_at."""
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="silent@example.com", invited=False)
    assert client.invited_at is None
    session = FakeServiceSession(clients=[client])

    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=client.id)

    assert result.outcome is ResendWelcomeOutcome.OK
    assert result.issued is not None
    assert result.issued.email == client.email
    assert stub_admin_ok == [
        (client.email, "http://localhost:3000/auth/callback?next=/basecamp"),
    ]
    # uninvited → pending: invited_at now stamped, in exactly one commit.
    assert client.invited_at is not None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_resend_to_pending_client_keeps_stamp_and_writes_nothing(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    """A re-send to an already-invited client re-emails but does no DB write."""
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="resend@example.com", invited=True)
    original_invited_at = client.invited_at
    assert original_invited_at is not None
    session = FakeServiceSession(clients=[client])

    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=client.id)

    assert result.outcome is ResendWelcomeOutcome.OK
    assert result.issued is not None
    assert stub_admin_ok == [
        (client.email, "http://localhost:3000/auth/callback?next=/basecamp"),
    ]
    # Re-send preserves the original invite time and touches no rows.
    assert client.invited_at == original_invited_at
    assert session.commits == 0


@pytest.mark.asyncio
async def test_resend_refuses_when_client_already_accepted(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="active@example.com", accepted=True)
    session = FakeServiceSession(clients=[client])

    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=client.id)

    assert result.outcome is ResendWelcomeOutcome.ALREADY_ACCEPTED
    # No upstream call for an already-signed-in client.
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_resend_unknown_client_returns_client_not_found(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    session = FakeServiceSession()  # no clients

    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=uuid.uuid4())

    assert result.outcome is ResendWelcomeOutcome.CLIENT_NOT_FOUND
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_resend_other_advisors_client_returns_client_not_found(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    other_advisor = uuid.uuid4()
    caller = uuid.uuid4()
    other = _client_row(other_advisor)
    session = FakeServiceSession(clients=[other])

    result = await resend_welcome_email(session, advisor_id=caller, client_id=other.id)

    assert result.outcome is ResendWelcomeOutcome.CLIENT_NOT_FOUND
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_resend_upstream_failure_returns_unavailable(
    stub_admin_unreachable: None,
) -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id)
    session = FakeServiceSession(clients=[client])

    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=client.id)

    assert result.outcome is ResendWelcomeOutcome.UPSTREAM_UNAVAILABLE


# ── Router-level tests ─────────────────────────────────────────────────────


@pytest.fixture()
def advisor_sub() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def auth_headers(
    make_token: Callable[..., str],
    advisor_sub: uuid.UUID,
) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_sub))}"}


@pytest.fixture()
def override_require_advisor(advisor_sub: uuid.UUID) -> Iterator[uuid.UUID]:
    async def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            sub=str(advisor_sub),
            email="advisor@example.com",
            role="authenticated",
            claims={"sub": str(advisor_sub)},
        )

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield advisor_sub
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def override_require_advisor_rejects() -> Iterator[None]:
    async def _dep() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def stub_session() -> Iterator[None]:
    async def _dep() -> Iterator[None]:
        yield None

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def stub_resend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "calls": [],
        "outcome": ResendWelcomeOutcome.OK,
    }

    async def _fake(
        _session: Any,
        *,
        advisor_id: uuid.UUID,
        client_id: uuid.UUID,
        settings: Any = None,
    ) -> ResendWelcomeResult:
        state["calls"].append({"advisor_id": advisor_id, "client_id": client_id})
        outcome = state["outcome"]
        issued = (
            MagicLinkIssued(email="x@example.com", action_link="")
            if outcome is ResendWelcomeOutcome.OK
            else None
        )
        return ResendWelcomeResult(outcome=outcome, issued=issued)

    monkeypatch.setattr(clients_router_module, "resend_welcome_email", _fake)
    return state


@pytest.fixture()
def http_client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


def test_resend_route_advisor_returns_204(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_resend: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    client_id = uuid.uuid4()
    resp = http_client.post(f"/clients/{client_id}/resend-welcome", headers=auth_headers)
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_resend["calls"] == [
        {"advisor_id": override_require_advisor, "client_id": client_id}
    ]


def test_resend_route_non_advisor_returns_403(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor_rejects: None,
    stub_resend: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = http_client.post(f"/clients/{uuid.uuid4()}/resend-welcome", headers=auth_headers)
    assert resp.status_code == 403
    assert stub_resend["calls"] == []


def test_resend_route_unknown_client_returns_404(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_resend: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_resend["outcome"] = ResendWelcomeOutcome.CLIENT_NOT_FOUND
    resp = http_client.post(f"/clients/{uuid.uuid4()}/resend-welcome", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"


def test_resend_route_already_accepted_returns_409(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_resend: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_resend["outcome"] = ResendWelcomeOutcome.ALREADY_ACCEPTED
    resp = http_client.post(f"/clients/{uuid.uuid4()}/resend-welcome", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "client_already_accepted"


def test_resend_route_upstream_unavailable_returns_502(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_resend: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_resend["outcome"] = ResendWelcomeOutcome.UPSTREAM_UNAVAILABLE
    resp = http_client.post(f"/clients/{uuid.uuid4()}/resend-welcome", headers=auth_headers)
    assert resp.status_code == 502
    assert resp.json()["detail"] == "auth_upstream_unavailable"
