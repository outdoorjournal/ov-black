"""Service-level coverage for ``create_client_with_dossier`` (T04).

FakeSession + stubbed-admin pattern. No Postgres, no live Supabase — every
outcome enum (OK / DUPLICATE_EMAIL / UPSTREAM_UNAVAILABLE) is exercised
deterministically against the service's control flow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from app.models import Client, Dossier, DossierFact, DossierFactKind, FactSourceKind
from app.schemas.clients import ClientCreatePayload
from app.schemas.dossier import DossierPayload, DossierTyped
from app.schemas.facts import DossierFactCreate
from app.services import clients as clients_service
from app.services.clients import (
    ClientCreateOutcome,
    create_client_with_dossier,
)
from app.services.supabase_admin import MagicLinkIssued, SupabaseAdminError
from sqlalchemy.exc import IntegrityError

# --- Fakes ------------------------------------------------------------------


@dataclass
class FakeSession:
    """Minimal async-session stand-in for the clients service.

    Tracks everything ``session.add``-ed so each test can inspect the
    rows the service tried to persist (client, dossier, dossier_facts).
    Optional ``flush_raises`` lets a test simulate the unique-index
    violation from ``clients_owner_email_idx``.
    """

    added: list[Any] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    flushes: int = 0
    flush_raises: IntegrityError | None = None
    raise_on_nth_flush: int = 1

    def add(self, obj: Any) -> None:
        # Emulate the server-side default on clients.id so the service can
        # hand the generated UUID to the dossier row in the same txn.
        if isinstance(obj, Client) and obj.id is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_raises is not None and self.flushes == self.raise_on_nth_flush:
            raise self.flush_raises

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _payload(*, email: str = "new@example.com") -> ClientCreatePayload:
    return ClientCreatePayload(
        full_name="Jane Doe",
        email=email,
        dossier=DossierPayload(
            typed=DossierTyped(
                contact_preference="email",
                children_ages=[7, 10],
                travel_party_notes="prefers late checkouts",
                estimated_net_worth_usd=5_000_000,
            ),
        ),
        dossier_facts=[
            DossierFactCreate(
                kind=DossierFactKind.passion,
                text="skiing",
                source_kind=FactSourceKind.advisor,
            ),
            DossierFactCreate(
                kind=DossierFactKind.travel_history,
                text="Aspen · 2024",
                source_kind=FactSourceKind.advisor,
            ),
        ],
    )


def _integrity_error() -> IntegrityError:
    return IntegrityError(
        statement="INSERT INTO public.clients ...",
        params={},
        orig=Exception("duplicate key value violates unique constraint 'clients_owner_email_idx'"),
    )


# --- Tests ------------------------------------------------------------------


@pytest.fixture()
def stub_admin_ok(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Stub generate_invite_link to succeed. Captures (email, redirect_to)."""
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


@pytest.fixture()
def stub_admin_email_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub generate_invite_link to reject with GoTrue's 422 ``email_exists`` —
    the address is already a registered auth user (so the invite can't create
    it), even though it isn't one of *this* advisor's clients."""

    async def _rejected(email: str, redirect_to: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError(
            "supabase_admin_rejected", status_code=422, error_code="email_exists"
        )

    monkeypatch.setattr(clients_service, "generate_invite_link", _rejected)


@pytest.mark.asyncio
async def test_ok_path_inserts_client_dossier_facts_with_one_commit(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    session = FakeSession()

    result = await create_client_with_dossier(
        session,
        advisor_id=advisor_id,
        payload=_payload(email="fresh@example.com"),
    )

    assert result.outcome is ClientCreateOutcome.OK
    assert result.client_id is not None
    assert result.issued is not None
    assert result.issued.email == "fresh@example.com"

    assert session.commits == 1
    assert session.rollbacks == 0

    client_rows = [o for o in session.added if isinstance(o, Client)]
    dossier_rows = [o for o in session.added if isinstance(o, Dossier)]
    fact_rows = [o for o in session.added if isinstance(o, DossierFact)]

    assert len(client_rows) == 1
    assert len(dossier_rows) == 1
    assert len(fact_rows) == 2  # the two seeded dossier_facts

    assert client_rows[0].owner_id == advisor_id
    assert client_rows[0].email == "fresh@example.com"
    assert dossier_rows[0].client_id == client_rows[0].id
    assert dossier_rows[0].authored_by == advisor_id
    assert dossier_rows[0].children_ages == [7, 10]
    for fact in fact_rows:
        assert fact.client_id == client_rows[0].id
        assert fact.recorded_by == advisor_id
        assert fact.source_kind is FactSourceKind.advisor

    # The welcome email is sent code-free — no `data` kwarg.
    assert stub_admin_ok == [
        ("fresh@example.com", "http://localhost:3000/auth/callback?next=/basecamp"),
    ]


@pytest.mark.asyncio
async def test_duplicate_email_rolls_back_and_does_not_call_admin(
    stub_admin_ok: list[tuple[str, str]],
) -> None:
    advisor_id = uuid.uuid4()
    session = FakeSession(flush_raises=_integrity_error(), raise_on_nth_flush=1)

    result = await create_client_with_dossier(
        session,
        advisor_id=advisor_id,
        payload=_payload(email="dup@example.com"),
    )

    assert result.outcome is ClientCreateOutcome.DUPLICATE_EMAIL
    assert result.client_id is None
    assert result.issued is None
    assert session.commits == 0
    assert session.rollbacks == 1
    assert stub_admin_ok == []


@pytest.mark.asyncio
async def test_upstream_failure_rolls_back_and_returns_unavailable(
    stub_admin_unreachable: None,
) -> None:
    advisor_id = uuid.uuid4()
    session = FakeSession()

    result = await create_client_with_dossier(
        session,
        advisor_id=advisor_id,
        payload=_payload(email="lost@example.com"),
    )

    assert result.outcome is ClientCreateOutcome.UPSTREAM_UNAVAILABLE
    assert result.client_id is None
    assert result.issued is None
    assert session.commits == 0
    # Service MUST rollback so the client + dossier + facts rows do not
    # persist when the welcome email could not be issued.
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_already_registered_email_is_duplicate_not_outage(
    stub_admin_email_exists: None,
) -> None:
    # Regression: an email that isn't THIS advisor's client (so the per-advisor
    # unique index doesn't fire and the flush succeeds) but IS an already-
    # registered auth user — another advisor's client, or any account. GoTrue
    # rejects the invite with 422 ``email_exists``; that is a DUPLICATE, and it
    # must surface on the 409 path, not as a 502 "auth unreachable" outage.
    advisor_id = uuid.uuid4()
    session = FakeSession()

    result = await create_client_with_dossier(
        session,
        advisor_id=advisor_id,
        payload=_payload(email="taken@example.com"),
    )

    assert result.outcome is ClientCreateOutcome.DUPLICATE_EMAIL
    assert result.client_id is None
    assert result.issued is None
    assert session.commits == 0
    # The client + dossier inserts must roll back — no orphan row for an email
    # we could never have invited.
    assert session.rollbacks == 1
