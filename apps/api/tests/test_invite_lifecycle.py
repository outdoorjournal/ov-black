"""Coverage for the invite re-issue + cancel lifecycle (M001, 0007).

Two layers, mirroring ``test_invites.py`` / ``test_clients_*``:

- Service tests against a fake async session — every outcome of
  ``reissue_client_invite`` and ``cancel_client_invite`` is exercised
  deterministically without Postgres or live Supabase.
- Router tests stub the service entry points and assert the HTTP contract
  (status codes, advisor-only enforcement, collapsed 404 for cross-advisor
  reads).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Client, Invite, UserRole
from app.routers import clients as clients_router_module
from app.services import clients as clients_service
from app.services.clients import (
    InviteCancelOutcome,
    InviteCancelResult,
    InviteReissueOutcome,
    InviteReissueResult,
    cancel_client_invite,
    reissue_client_invite,
)
from app.services.supabase_admin import MagicLinkIssued, SupabaseAdminError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


# ── Service-level fakes ─────────────────────────────────────────────────────


@dataclass
class _ExecResult:
    """SQLAlchemy Result slice the service uses."""

    rows: list[Any] = field(default_factory=list)

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalars(self) -> list[Any]:
        return list(self.rows)


@dataclass
class FakeServiceSession:
    """Async-session stand-in that backs the service's CRUD ops.

    Tracks ``add``-ed Invite rows, ``commit``/``rollback`` counts, and
    introspects compiled SQL enough to dispatch on whether the statement
    is a Client lookup, a consumed-exists probe, a supersede UPDATE, or
    a cancel UPDATE.
    """

    clients: list[Client] = field(default_factory=list)
    invites: list[Invite] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    flushes: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, stmt: Any) -> _ExecResult:
        compiled = stmt.compile()
        params = compiled.params
        sql = str(compiled).lower()

        if sql.lstrip().startswith("update"):
            return self._handle_update(sql, params)
        return self._handle_select(sql, params)

    # ── helpers ────────────────────────────────────────────────────────────

    def _handle_select(self, sql: str, params: dict[str, Any]) -> _ExecResult:
        if "from clients" in sql:
            wanted_id = next(
                (v for v in params.values() if isinstance(v, uuid.UUID)), None
            )
            owners = [v for v in params.values() if isinstance(v, uuid.UUID)]
            owner_id = owners[1] if len(owners) > 1 else None
            for c in self.clients:
                if c.id == wanted_id and (owner_id is None or c.owner_id == owner_id):
                    return _ExecResult([c])
            return _ExecResult([])

        if "from invites" in sql:
            email = next(
                (v for v in params.values() if isinstance(v, str) and "@" in v),
                None,
            )
            created_by = next(
                (v for v in params.values() if isinstance(v, uuid.UUID)), None
            )
            consumed_only = "consumed_at is not null" in sql
            matches = [
                i
                for i in self.invites
                if i.role is UserRole.client
                and i.created_by == created_by
                and (email is None or i.email == email)
                and (not consumed_only or i.consumed_at is not None)
            ]
            if consumed_only:
                # Service uses .scalar_one_or_none() against `select(Invite.code)`.
                return _ExecResult([m.code for m in matches[:1]])
            return _ExecResult(matches)

        raise AssertionError(f"unexpected SELECT: {sql}")

    def _handle_update(self, sql: str, params: dict[str, Any]) -> _ExecResult:
        if "invites" not in sql:
            raise AssertionError(f"unexpected UPDATE: {sql}")

        email = next(
            (v for v in params.values() if isinstance(v, str) and "@" in v),
            None,
        )
        created_by = next(
            (v for v in params.values() if isinstance(v, uuid.UUID)), None
        )
        # Setting which lifecycle column? Inspect the SET clause.
        is_supersede = "set superseded_at" in sql
        is_cancel = "set cancelled_at" in sql
        now = datetime.now(timezone.utc)

        targets = [
            i
            for i in self.invites
            if i.role is UserRole.client
            and i.created_by == created_by
            and i.email == email
            and i.consumed_at is None
            and i.cancelled_at is None
            and i.superseded_at is None
        ]
        for inv in targets:
            if is_supersede:
                inv.superseded_at = now
            elif is_cancel:
                inv.cancelled_at = now

        return _ExecResult([t.code for t in targets])


def _client_row(advisor_id: uuid.UUID, *, email: str = "client@example.com") -> Client:
    row = Client(
        owner_id=advisor_id,
        full_name="Jane Traveler",
        email=email,
    )
    row.id = uuid.uuid4()
    row.created_at = datetime.now(timezone.utc)
    row.updated_at = row.created_at
    row.auth_user_id = None
    return row


def _invite_row(
    *,
    email: str,
    advisor_id: uuid.UUID,
    consumed: bool = False,
    cancelled: bool = False,
    superseded: bool = False,
) -> Invite:
    inv = Invite(
        code=f"INV-{uuid.uuid4().hex[:10]}",
        role=UserRole.client,
        email=email,
        created_by=advisor_id,
    )
    inv.created_at = datetime.now(timezone.utc)
    if consumed:
        inv.consumed_at = inv.created_at
    if cancelled:
        inv.cancelled_at = inv.created_at
    if superseded:
        inv.superseded_at = inv.created_at
    return inv


@pytest.fixture()
def stub_admin_ok(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _fake(email: str, redirect_to: str, **_kwargs: Any) -> MagicLinkIssued:
        calls.append((email, redirect_to))
        return MagicLinkIssued(email=email, action_link="https://stub/invite-link")

    monkeypatch.setattr(clients_service, "generate_invite_link", _fake)
    return calls


@pytest.fixture()
def stub_admin_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(email: str, redirect_to: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_unreachable")

    monkeypatch.setattr(clients_service, "generate_invite_link", _boom)


# ── Service: reissue ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reissue_supersedes_active_and_inserts_fresh_row(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="resend@example.com")
    active = _invite_row(email=client.email, advisor_id=advisor_id)
    session = FakeServiceSession(clients=[client], invites=[active])

    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteReissueOutcome.OK
    assert result.issued is not None
    assert result.issued.email == client.email
    assert active.superseded_at is not None
    new_invites = [o for o in session.added if isinstance(o, Invite)]
    assert len(new_invites) == 1
    assert new_invites[0].email == client.email
    assert new_invites[0].created_by == advisor_id
    assert new_invites[0].code != active.code
    assert session.commits == 1
    assert session.rollbacks == 0
    assert stub_admin_ok == [
        (client.email, "http://localhost:3000/auth/callback?next=/basecamp"),
    ]


@pytest.mark.asyncio
async def test_reissue_when_no_active_row_just_inserts_a_fresh_row(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    # Advisor cancelled the prior invite, then changed their mind.
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="rebound@example.com")
    cancelled = _invite_row(
        email=client.email, advisor_id=advisor_id, cancelled=True
    )
    session = FakeServiceSession(clients=[client], invites=[cancelled])

    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteReissueOutcome.OK
    new_invites = [o for o in session.added if isinstance(o, Invite)]
    assert len(new_invites) == 1
    # Existing cancelled row stays cancelled — supersede is a no-op for it.
    assert cancelled.cancelled_at is not None
    assert cancelled.superseded_at is None


@pytest.mark.asyncio
async def test_reissue_refuses_when_invite_already_consumed(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id, email="redeemed@example.com")
    consumed = _invite_row(email=client.email, advisor_id=advisor_id, consumed=True)
    session = FakeServiceSession(clients=[client], invites=[consumed])

    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteReissueOutcome.ALREADY_REDEEMED
    # No new invite was added, no upstream call.
    assert [o for o in session.added if isinstance(o, Invite)] == []
    assert stub_admin_ok == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_reissue_unknown_client_returns_client_not_found(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    session = FakeServiceSession()  # no clients

    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=uuid.uuid4()
    )

    assert result.outcome is InviteReissueOutcome.CLIENT_NOT_FOUND
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_reissue_other_advisors_client_returns_client_not_found(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    # Cross-advisor scoping: the row exists but the caller doesn't own it.
    other_advisor = uuid.uuid4()
    caller = uuid.uuid4()
    other = _client_row(other_advisor)
    session = FakeServiceSession(clients=[other])

    result = await reissue_client_invite(
        session, advisor_id=caller, client_id=other.id
    )

    assert result.outcome is InviteReissueOutcome.CLIENT_NOT_FOUND
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_reissue_upstream_failure_rolls_back(
    stub_admin_unreachable: None,
) -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id)
    active = _invite_row(email=client.email, advisor_id=advisor_id)
    session = FakeServiceSession(clients=[client], invites=[active])

    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteReissueOutcome.UPSTREAM_UNAVAILABLE
    assert session.commits == 0
    assert session.rollbacks == 1


# ── Service: cancel ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_marks_active_invite_cancelled() -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id)
    active = _invite_row(email=client.email, advisor_id=advisor_id)
    session = FakeServiceSession(clients=[client], invites=[active])

    result = await cancel_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteCancelOutcome.OK
    assert active.cancelled_at is not None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_cancel_when_no_active_returns_no_active_invite() -> None:
    advisor_id = uuid.uuid4()
    client = _client_row(advisor_id)
    consumed = _invite_row(email=client.email, advisor_id=advisor_id, consumed=True)
    session = FakeServiceSession(clients=[client], invites=[consumed])

    result = await cancel_client_invite(
        session, advisor_id=advisor_id, client_id=client.id
    )

    assert result.outcome is InviteCancelOutcome.NO_ACTIVE_INVITE
    assert session.commits == 0


@pytest.mark.asyncio
async def test_cancel_other_advisors_client_returns_client_not_found() -> None:
    other_advisor = uuid.uuid4()
    caller = uuid.uuid4()
    other = _client_row(other_advisor)
    session = FakeServiceSession(clients=[other])

    result = await cancel_client_invite(
        session, advisor_id=caller, client_id=other.id
    )

    assert result.outcome is InviteCancelOutcome.CLIENT_NOT_FOUND


# ── Router-level tests ─────────────────────────────────────────────────────


@pytest.fixture()
def advisor_sub() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def auth_headers(
    make_token: "Callable[..., str]",
    advisor_sub: uuid.UUID,
) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_sub))}"}


@pytest.fixture()
def override_require_advisor(advisor_sub: uuid.UUID) -> "Iterator[uuid.UUID]":
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
def override_require_advisor_rejects() -> "Iterator[None]":
    async def _dep() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def stub_session() -> "Iterator[None]":
    """Provide a no-op session; the service layer is stubbed below."""

    async def _dep() -> "Iterator[None]":
        yield None

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def stub_reissue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "calls": [],
        "outcome": InviteReissueOutcome.OK,
    }

    async def _fake(
        _session: Any,
        *,
        advisor_id: uuid.UUID,
        client_id: uuid.UUID,
        settings: Any = None,
    ) -> InviteReissueResult:
        state["calls"].append({"advisor_id": advisor_id, "client_id": client_id})
        outcome = state["outcome"]
        issued = (
            MagicLinkIssued(email="x@example.com", action_link="")
            if outcome is InviteReissueOutcome.OK
            else None
        )
        return InviteReissueResult(outcome=outcome, issued=issued)

    monkeypatch.setattr(clients_router_module, "reissue_client_invite", _fake)
    return state


@pytest.fixture()
def stub_cancel(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "calls": [],
        "outcome": InviteCancelOutcome.OK,
    }

    async def _fake(
        _session: Any,
        *,
        advisor_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> InviteCancelResult:
        state["calls"].append({"advisor_id": advisor_id, "client_id": client_id})
        return InviteCancelResult(outcome=state["outcome"])

    monkeypatch.setattr(clients_router_module, "cancel_client_invite", _fake)
    return state


@pytest.fixture()
def http_client() -> "Iterator[TestClient]":
    with TestClient(fastapi_app) as c:
        yield c


# ── Router: reissue ────────────────────────────────────────────────────────


def test_reissue_route_advisor_returns_204(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_reissue: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    client_id = uuid.uuid4()
    resp = http_client.post(
        f"/clients/{client_id}/invite/reissue", headers=auth_headers
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_reissue["calls"] == [
        {"advisor_id": override_require_advisor, "client_id": client_id}
    ]


def test_reissue_route_non_advisor_returns_403(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor_rejects: None,
    stub_reissue: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/reissue", headers=auth_headers
    )
    assert resp.status_code == 403
    assert stub_reissue["calls"] == []


def test_reissue_route_unknown_client_returns_404(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_reissue: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_reissue["outcome"] = InviteReissueOutcome.CLIENT_NOT_FOUND
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/reissue", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"


def test_reissue_route_already_redeemed_returns_409(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_reissue: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_reissue["outcome"] = InviteReissueOutcome.ALREADY_REDEEMED
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/reissue", headers=auth_headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "invite_already_redeemed"


def test_reissue_route_upstream_unavailable_returns_502(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_reissue: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_reissue["outcome"] = InviteReissueOutcome.UPSTREAM_UNAVAILABLE
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/reissue", headers=auth_headers
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "auth_upstream_unavailable"


# ── Router: cancel ────────────────────────────────────────────────────────


def test_cancel_route_advisor_returns_204(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_cancel: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    client_id = uuid.uuid4()
    resp = http_client.post(
        f"/clients/{client_id}/invite/cancel", headers=auth_headers
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_cancel["calls"] == [
        {"advisor_id": override_require_advisor, "client_id": client_id}
    ]


def test_cancel_route_non_advisor_returns_403(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor_rejects: None,
    stub_cancel: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/cancel", headers=auth_headers
    )
    assert resp.status_code == 403
    assert stub_cancel["calls"] == []


def test_cancel_route_no_active_returns_409(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_cancel: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_cancel["outcome"] = InviteCancelOutcome.NO_ACTIVE_INVITE
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/cancel", headers=auth_headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_active_invite"


def test_cancel_route_unknown_client_returns_404(
    http_client: TestClient,
    stub_session: None,
    override_require_advisor: uuid.UUID,
    stub_cancel: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_cancel["outcome"] = InviteCancelOutcome.CLIENT_NOT_FOUND
    resp = http_client.post(
        f"/clients/{uuid.uuid4()}/invite/cancel", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"
