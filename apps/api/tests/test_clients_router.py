"""Coverage for the advisor-facing /clients surface (M001/S03 T05).

Router-level tests only — the service behaviour is exercised by
``test_clients_service.py``. We stub :func:`create_client_with_voodoo_doll`
and override ``require_advisor`` / ``get_session`` so each case exercises
exactly one router responsibility:

- outcome → status mapping (POST 201/409/502);
- role enforcement (POST 403 for a client-role JWT);
- payload validation (POST 422 on missing fields);
- advisor-scoped reads (GET filters by owner_id);
- collapsed cross-advisor 404 (GET-by-id) — 403 would leak existence.

No Postgres and no live Supabase — the whole file runs on a fresh checkout.
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
from app.models import Client, Invite, UserRole, VoodooDoll
from app.models.client import ContactChannel, GroupType
from app.routers import clients as clients_router_module
from app.services.clients import (
    ClientCreateOutcome,
    ClientCreateResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


# ── Fixtures / helpers ──────────────────────────────────────────────────────


@dataclass
class _ExecResult:
    """Mimics the slice of SQLAlchemy Result the router uses."""

    rows: list[Any] = field(default_factory=list)

    def scalar_one_or_none(self) -> Any:
        # Used for single-row lookups (GET-by-id client/doll/invite).
        if not self.rows:
            return None
        return self.rows[0]

    def all(self) -> list[Any]:
        return list(self.rows)


@dataclass
class FakeSession:
    """Async-session stand-in for the router's reads.

    Holds an advisor-scoped fixture: a dict of clients keyed by (owner_id,
    client_id), plus voodoo_dolls and invites. ``execute`` introspects the
    compiled SQL enough to dispatch to the right helper. The router only
    ever calls ``execute`` — no commit/rollback is expected on the read path.
    """

    clients_by_id: dict[uuid.UUID, Client] = field(default_factory=dict)
    dolls_by_client: dict[uuid.UUID, VoodooDoll] = field(default_factory=dict)
    invites: list[Invite] = field(default_factory=list)

    async def execute(self, stmt: Any) -> _ExecResult:
        compiled = stmt.compile()
        params = compiled.params
        sql = str(compiled).lower()

        # ── LIST /clients — joined SELECT on clients + voodoo_dolls + invites ──
        if "from clients" in sql and "join" in sql:
            advisor_id = next(
                (v for v in params.values() if isinstance(v, uuid.UUID)), None
            )
            rows: list[tuple[Client, uuid.UUID | None, Invite | None]] = []
            owned = [
                c
                for c in self.clients_by_id.values()
                if c.owner_id == advisor_id
            ]
            owned.sort(key=lambda c: c.created_at, reverse=True)
            for client in owned:
                doll = self.dolls_by_client.get(client.id)
                invite = next(
                    (
                        i
                        for i in self.invites
                        if i.email == client.email
                        and i.role is UserRole.client
                        and i.created_by == advisor_id
                    ),
                    None,
                )
                rows.append((client, doll.id if doll else None, invite))
            return _ExecResult(rows)

        # ── GET /clients/{id} — single client scoped to owner ──
        if "from clients" in sql:
            client_id = None
            owner_id = None
            for v in params.values():
                if isinstance(v, uuid.UUID):
                    # First UUID is id, second is owner_id (by binding order)
                    if client_id is None:
                        client_id = v
                    else:
                        owner_id = v
            client = self.clients_by_id.get(client_id)
            if client is None or (owner_id is not None and client.owner_id != owner_id):
                return _ExecResult([])
            return _ExecResult([client])

        # ── VoodooDoll lookup by client_id ──
        if "from voodoo_dolls" in sql:
            client_id = next(
                (v for v in params.values() if isinstance(v, uuid.UUID)), None
            )
            doll = self.dolls_by_client.get(client_id)
            return _ExecResult([doll] if doll is not None else [])

        # ── Invite lookup by (email, role, created_by) ──
        if "from invites" in sql:
            email = next(
                (v for v in params.values() if isinstance(v, str) and "@" in v),
                None,
            )
            created_by = None
            for v in params.values():
                if isinstance(v, uuid.UUID):
                    created_by = v
                    break
            invite = next(
                (
                    i
                    for i in self.invites
                    if i.email == email
                    and i.role is UserRole.client
                    and i.created_by == created_by
                ),
                None,
            )
            return _ExecResult([invite] if invite is not None else [])

        raise AssertionError(f"unexpected statement: {sql}")

    async def commit(self) -> None:  # pragma: no cover — router does not commit
        return None

    async def rollback(self) -> None:  # pragma: no cover — router does not rollback
        return None


@pytest.fixture()
def fake_session() -> "Iterator[FakeSession]":
    """Override ``get_session`` with a FakeSession for the test."""
    fake = FakeSession()

    async def _dep() -> "Iterator[FakeSession]":
        yield fake

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield fake
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def advisor_sub() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def auth_headers(
    make_token: "Callable[..., str]",
    advisor_sub: uuid.UUID,
) -> dict[str, str]:
    """Mint a valid JWT so the middleware lets the request through.

    The dependency overrides below then decide whether to let it pass as
    an advisor, reject it as a non-advisor, etc. — the JWT itself is just
    there to satisfy ``JWTAuthMiddleware``.
    """
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_sub))}"}


@pytest.fixture()
def override_require_advisor(advisor_sub: uuid.UUID) -> "Iterator[uuid.UUID]":
    """Install ``require_advisor`` override that returns an advisor principal."""

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
def override_require_advisor_rejects_client() -> "Iterator[None]":
    """Install ``require_advisor`` override that 403s like a non-advisor JWT."""

    async def _dep() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def stub_service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub ``create_client_with_voodoo_doll`` on the router module."""
    state: dict[str, Any] = {
        "calls": [],
        "return_outcome": ClientCreateOutcome.OK,
        "return_client_id": None,
    }

    async def _fake(
        _session: Any,
        *,
        advisor_id: uuid.UUID,
        payload: Any,
        settings: Any = None,
    ) -> ClientCreateResult:
        state["calls"].append(
            {"advisor_id": advisor_id, "payload": payload}
        )
        outcome = state["return_outcome"]
        client_id = state["return_client_id"] or (
            uuid.uuid4() if outcome is ClientCreateOutcome.OK else None
        )
        return ClientCreateResult(outcome=outcome, client_id=client_id)

    monkeypatch.setattr(
        clients_router_module, "create_client_with_voodoo_doll", _fake
    )
    return state


def _valid_payload(email: str = "client@example.com") -> dict[str, Any]:
    return {
        "full_name": "Jane Traveler",
        "email": email,
        "voodoo_doll": {
            "typed": {
                "contact_preference": "email",
                "group_type": "couple",
                "children_ages": [],
                "travel_party_notes": "",
                "estimated_net_worth_usd": None,
            },
            "jsonb": {},
        },
    }


def _client_row(
    *,
    owner_id: uuid.UUID,
    email: str = "client@example.com",
    full_name: str = "Jane Traveler",
    client_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Client:
    row = Client(
        owner_id=owner_id,
        full_name=full_name,
        email=email,
    )
    row.id = client_id or uuid.uuid4()
    row.created_at = created_at or datetime.now(timezone.utc)
    row.updated_at = row.created_at
    row.auth_user_id = None
    return row


def _doll_for(client_id: uuid.UUID, authored_by: uuid.UUID) -> VoodooDoll:
    doll = VoodooDoll(
        client_id=client_id,
        authored_by=authored_by,
        contact_preference=ContactChannel.email,
        group_type=GroupType.couple,
        children_ages=[],
        travel_party_notes="notes",
        estimated_net_worth_usd=None,
        passions=[],
        motivations={},
        travel_history=[],
        triggers=[],
        constraints=[],
        deal_breakers=[],
        dream_trip_signals={},
        osint_notes={},
    )
    doll.id = uuid.uuid4()
    doll.created_at = datetime.now(timezone.utc)
    doll.updated_at = doll.created_at
    return doll


def _invite_for(email: str, created_by: uuid.UUID, *, consumed: bool = False) -> Invite:
    inv = Invite(
        code=f"INV-{uuid.uuid4().hex[:8]}",
        role=UserRole.client,
        email=email,
        created_by=created_by,
    )
    if consumed:
        inv.consumed_at = datetime.now(timezone.utc)
    return inv


# ── POST /clients ──────────────────────────────────────────────────────────


def test_post_clients_advisor_returns_201_with_client_id(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    new_id = uuid.uuid4()
    stub_service["return_outcome"] = ClientCreateOutcome.OK
    stub_service["return_client_id"] = new_id

    resp = client.post("/clients", json=_valid_payload(), headers=auth_headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"] == str(new_id)
    assert body["invite_email"] == "client@example.com"
    # Service received the advisor UUID from user.sub.
    assert stub_service["calls"][0]["advisor_id"] == override_require_advisor


def test_post_clients_client_role_jwt_returns_403(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor_rejects_client: None,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    # Guard 403s before the router body runs — service must not be called.
    resp = client.post("/clients", json=_valid_payload(), headers=auth_headers)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "advisor_only"
    assert stub_service["calls"] == []


def test_post_clients_duplicate_email_returns_409(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["return_outcome"] = ClientCreateOutcome.DUPLICATE_EMAIL

    resp = client.post("/clients", json=_valid_payload(), headers=auth_headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "client_email_already_invited"


def test_post_clients_upstream_unavailable_returns_502(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["return_outcome"] = ClientCreateOutcome.UPSTREAM_UNAVAILABLE

    resp = client.post("/clients", json=_valid_payload(), headers=auth_headers)

    assert resp.status_code == 502
    # Same detail string S01's redeem path uses — ops dashboards collapse on this.
    assert resp.json()["detail"] == "auth_upstream_unavailable"


def test_post_clients_missing_required_fields_returns_422(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    # No voodoo_doll — Pydantic rejects with 422 before the handler runs.
    bad_payload = {"full_name": "Jane", "email": "jane@example.com"}

    resp = client.post("/clients", json=bad_payload, headers=auth_headers)

    assert resp.status_code == 422
    assert stub_service["calls"] == []


# ── GET /clients ───────────────────────────────────────────────────────────


def test_get_clients_returns_only_own_clients(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    auth_headers: dict[str, str],
) -> None:
    advisor_a = override_require_advisor
    advisor_b = uuid.uuid4()

    a_client = _client_row(
        owner_id=advisor_a,
        email="a@example.com",
        full_name="Alice A",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    b_client = _client_row(
        owner_id=advisor_b,
        email="b@example.com",
        full_name="Bob B",
        created_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
    )
    a_client_2 = _client_row(
        owner_id=advisor_a,
        email="c@example.com",
        full_name="Carol A",
        created_at=datetime(2026, 4, 3, tzinfo=timezone.utc),
    )

    fake_session.clients_by_id[a_client.id] = a_client
    fake_session.clients_by_id[b_client.id] = b_client
    fake_session.clients_by_id[a_client_2.id] = a_client_2

    # advisor_a has a doll for a_client only, and a consumed invite for a_client
    fake_session.dolls_by_client[a_client.id] = _doll_for(a_client.id, advisor_a)
    fake_session.invites.append(
        _invite_for(a_client.email, advisor_a, consumed=True)
    )
    fake_session.invites.append(_invite_for(a_client_2.email, advisor_a))

    resp = client.get("/clients", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 2
    emails = {row["email"] for row in body}
    assert emails == {"a@example.com", "c@example.com"}
    # Newest first.
    assert body[0]["email"] == "c@example.com"
    assert body[1]["email"] == "a@example.com"

    a_row = next(r for r in body if r["email"] == "a@example.com")
    assert a_row["has_voodoo_doll"] is True
    assert a_row["invite_status"] == "consumed"
    assert a_row["full_name"] == "Alice A"

    c_row = next(r for r in body if r["email"] == "c@example.com")
    assert c_row["has_voodoo_doll"] is False
    assert c_row["invite_status"] == "pending"


# ── GET /clients/{id} ───────────────────────────────────────────────────────


def test_get_client_by_id_returns_joined_payload_for_own_client(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    auth_headers: dict[str, str],
) -> None:
    advisor_a = override_require_advisor
    own = _client_row(owner_id=advisor_a, email="own@example.com")
    doll = _doll_for(own.id, advisor_a)
    invite = _invite_for(own.email, advisor_a)

    fake_session.clients_by_id[own.id] = own
    fake_session.dolls_by_client[own.id] = doll
    fake_session.invites.append(invite)

    resp = client.get(f"/clients/{own.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(own.id)
    assert body["email"] == "own@example.com"
    assert body["invite_status"] == "pending"
    assert body["voodoo_doll"] is not None
    assert body["voodoo_doll"]["id"] == str(doll.id)
    assert body["voodoo_doll"]["contact_preference"] == "email"
    assert body["voodoo_doll"]["group_type"] == "couple"


def test_get_client_by_id_other_advisors_client_returns_404_not_403(
    client: TestClient,
    fake_session: FakeSession,
    override_require_advisor: uuid.UUID,
    auth_headers: dict[str, str],
) -> None:
    # Advisor B owns the client; the caller is advisor A. The handler MUST
    # return 404 (not 403) — S01 D015 collapsed shape so advisor A cannot
    # probe whether the client_id exists.
    advisor_b = uuid.uuid4()
    other = _client_row(owner_id=advisor_b, email="other@example.com")
    fake_session.clients_by_id[other.id] = other
    fake_session.dolls_by_client[other.id] = _doll_for(other.id, advisor_b)

    resp = client.get(f"/clients/{other.id}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"
