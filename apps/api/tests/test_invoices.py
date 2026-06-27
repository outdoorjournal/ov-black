"""Invoices + line-item ledger (M005/I1).

Two layers, mirroring ``test_fork_reconcile.py``:

1. Integration tests against a local Supabase Postgres — an invoice assembled
   over a priced node, signed discount/adjustment lines, the journal-entry void
   (a ``reversal`` that nets the original to zero), the currency-match guard, the
   issue/void lifecycle gates, and the computed ``Σ(lines)`` total.
2. Router tests (service stubbed) — advisor-only writes (403 for a non-advisor),
   401 without a JWT, and the owner/advisor read gate.

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import (
    CostKind,
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Itinerary,
    Node,
    NodeStatus,
    NodeType,
)
from app.services.invoices import (
    InvoiceView,
    add_line_item,
    add_line_item_from_node,
    create_invoice,
    get_invoice,
    issue_invoice,
    list_invoices,
    remove_line_item,
    void_invoice,
    void_line_item,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    add_node,
    create_itinerary,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"inv-{kind.value}")


# ── Integration harness ──────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(*itinerary_ids: uuid.UUID) -> None:
    # invoices / invoice_line_items cascade off the itinerary FK; node/edge
    # history have no FK so they're cleared explicitly (as in test_fork_reconcile).
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(
                    text("delete from public.edge_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
    finally:
        await engine.dispose()


async def _priced_node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    amount: str,
    currency: str = "USD",
    title: str = "Hotel",
) -> Node:
    node = await add_node(
        session,
        _actor(),
        itinerary_id=itinerary_id,
        type=NodeType.hotel,
        status=NodeStatus.approved,
        title=title,
        cost_amount=Decimal(amount),
        cost_currency=currency,
        cost_kind=CostKind.total,
    )
    assert isinstance(node, Node)
    return node


# ── Ledger: assemble, sign, total, void ──────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_signed_ledger_totals_and_void(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="inv")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")

        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="usd"
        )
        assert isinstance(invoice, Invoice)
        assert invoice.currency == "USD"  # normalized

        # charge from the node's B4 cost
        charge = await add_line_item_from_node(
            db_session, _actor(), invoice_id=invoice.id, node_id=node.id
        )
        assert isinstance(charge, InvoiceLineItem)
        assert charge.kind is InvoiceLineKind.charge
        assert charge.amount == Decimal("1000.00")
        assert charge.description == "Aman"

        # an elderly discount and a child adjustment — signed negatives
        discount = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            kind=InvoiceLineKind.discount,
            description="Elderly discount",
            amount=Decimal("-250.00"),
            currency="USD",
        )
        assert isinstance(discount, InvoiceLineItem)
        child = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            kind=InvoiceLineKind.adjustment,
            description="Child adjustment",
            amount=Decimal("-100.00"),
            currency="USD",
        )
        assert isinstance(child, InvoiceLineItem)

        view = await get_invoice(db_session, invoice.id)
        assert isinstance(view, InvoiceView)
        assert view.total == Decimal("650.00")  # 1000 - 250 - 100
        assert len(view.lines) == 3

        # void the discount -> a reversal nets it back; total returns to 900
        reversal = await void_line_item(
            db_session, _actor(), invoice_id=invoice.id, line_item_id=discount.id
        )
        assert isinstance(reversal, InvoiceLineItem)
        assert reversal.kind is InvoiceLineKind.reversal
        assert reversal.amount == Decimal("250.00")
        assert reversal.reverses_line_item_id == discount.id

        view2 = await get_invoice(db_session, invoice.id)
        assert isinstance(view2, InvoiceView)
        assert view2.total == Decimal("900.00")  # 1000 - 100

        # voiding the same line twice is refused
        again = await void_line_item(
            db_session, _actor(), invoice_id=invoice.id, line_item_id=discount.id
        )
        assert isinstance(again, ItineraryError)
        assert again.detail == "already_reversed"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_currency_mismatch_rejected(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cur")
    try:
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Balance", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        bad = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            description="EUR line",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        assert isinstance(bad, ItineraryError)
        assert bad.detail == "currency_mismatch"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_node_without_cost_rejected(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="nocost")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            status=NodeStatus.proposed,
            title="unpriced idea",
        )
        assert isinstance(node, Node)
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="x", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        result = await add_line_item_from_node(
            db_session, _actor(), invoice_id=invoice.id, node_id=node.id
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "node_has_no_cost"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_issue_lifecycle_gates(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="lifecycle")
    try:
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="USD"
        )
        assert isinstance(invoice, Invoice)

        # can't issue an empty invoice
        empty = await issue_invoice(db_session, _actor(), invoice_id=invoice.id)
        assert isinstance(empty, ItineraryError)
        assert empty.detail == "no_line_items"

        line = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            description="Suite",
            amount=Decimal("500.00"),
            currency="USD",
        )
        assert isinstance(line, InvoiceLineItem)

        issued = await issue_invoice(db_session, _actor(), invoice_id=invoice.id)
        assert isinstance(issued, Invoice)
        assert issued.status is InvoiceStatus.issued

        # after issue: a new charge is refused (assembly is draft-gated)...
        new_charge = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            kind=InvoiceLineKind.charge,
            description="late charge",
            amount=Decimal("50.00"),
            currency="USD",
        )
        assert isinstance(new_charge, ItineraryError)
        assert new_charge.detail == "invoice_not_draft"

        # ...but an adjusting discount is allowed (append-only correction)
        adj = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            kind=InvoiceLineKind.discount,
            description="goodwill",
            amount=Decimal("-25.00"),
            currency="USD",
        )
        assert isinstance(adj, InvoiceLineItem)

        # hard delete is draft-only
        del_after_issue = await remove_line_item(
            db_session, _actor(), invoice_id=invoice.id, line_item_id=line.id
        )
        assert isinstance(del_after_issue, ItineraryError)
        assert del_after_issue.detail == "invoice_not_draft"

        # void the invoice -> closed; no further lines
        voided = await void_invoice(db_session, _actor(), invoice_id=invoice.id)
        assert isinstance(voided, Invoice)
        assert voided.status is InvoiceStatus.void
        closed = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            kind=InvoiceLineKind.discount,
            description="too late",
            amount=Decimal("-5.00"),
            currency="USD",
        )
        assert isinstance(closed, ItineraryError)
        assert closed.detail == "invoice_closed"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_draft_delete_and_list(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="list")
    try:
        inv1 = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="USD"
        )
        inv2 = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Balance", currency="USD"
        )
        assert isinstance(inv1, Invoice)
        assert isinstance(inv2, Invoice)
        line = await add_line_item(
            db_session,
            _actor(),
            invoice_id=inv1.id,
            description="x",
            amount=Decimal("10.00"),
            currency="USD",
        )
        assert isinstance(line, InvoiceLineItem)
        # draft hard-delete works
        removed = await remove_line_item(
            db_session, _actor(), invoice_id=inv1.id, line_item_id=line.id
        )
        assert removed is None

        views = await list_invoices(db_session, itin.id)
        assert {v.invoice.label for v in views} == {"Deposit", "Balance"}
        assert all(v.total == Decimal("0.00") for v in views)
    finally:
        await _cleanup(itin.id)


# ── Router (service stubbed) ───────────────────────────────────────────────


@pytest.fixture()
def invoice_routes(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub the invoice endpoints' service + authz collaborators."""
    from app.auth import AuthenticatedUser
    from app.auth_guards import require_advisor
    from app.db import get_session
    from app.main import app as fastapi_app
    from app.routers import invoices as ri

    returns: dict[str, Any] = {"is_advisor": True, "owner_id": None}

    def _invoice() -> Invoice:
        return Invoice(
            id=uuid.uuid4(),
            itinerary_id=uuid.uuid4(),
            label="Deposit",
            status=InvoiceStatus.draft,
            currency="USD",
            created_at=datetime.now(UTC),
        )

    async def _create(_s: Any, _actor: Any, **kw: Any) -> Any:
        return _invoice()

    async def _get(_s: Any, invoice_id: uuid.UUID) -> Any:
        inv = _invoice()
        inv.id = invoice_id
        return InvoiceView(invoice=inv, lines=[], total=Decimal("0.00"), payments=[])

    async def _load_itin(_s: Any, _iid: uuid.UUID) -> Any:
        # a baseline-less itinerary: no owner/creator, so access hinges on advisor
        return Itinerary(id=uuid.uuid4(), client_id=None, created_by=None)

    async def _is_advisor(_s: Any, _uid: Any) -> bool:
        return bool(returns.get("is_advisor", True))

    async def _resolve_owner(_s: Any, _cid: uuid.UUID) -> Any:
        return returns.get("owner_id")

    monkeypatch.setattr(ri.invoices_svc, "create_invoice", _create)
    monkeypatch.setattr(ri.invoices_svc, "get_invoice", _get)
    monkeypatch.setattr(ri, "_load_itinerary", _load_itin)
    monkeypatch.setattr(ri, "_is_requester_advisor", _is_advisor)
    monkeypatch.setattr(ri, "_resolve_client_auth_user_id", _resolve_owner)

    async def _dep() -> Any:
        yield object()

    advisor_user = AuthenticatedUser(
        sub=str(uuid.uuid4()), email="a@x.com", role="authenticated", claims={}
    )

    async def _require_advisor() -> Any:
        if not returns.get("is_advisor", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="advisor_only")
        return advisor_user

    fastapi_app.dependency_overrides[get_session] = _dep
    fastapi_app.dependency_overrides[require_advisor] = _require_advisor
    try:
        yield {"returns": returns}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(require_advisor, None)


def _headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


def test_create_invoice_endpoint_201(client: Any, invoice_routes: Any, make_token: Any) -> None:
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/invoices",
        json={"label": "Deposit", "currency": "USD"},
        headers=_headers(make_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] == "Deposit"
    assert body["status"] == "draft"
    assert body["total"] == "0.00"  # Decimal serializes to string (like cost_amount)


def test_create_invoice_endpoint_advisor_only_403(
    client: Any, invoice_routes: Any, make_token: Any
) -> None:
    invoice_routes["returns"]["is_advisor"] = False
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/invoices",
        json={"label": "Deposit", "currency": "USD"},
        headers=_headers(make_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "advisor_only"


def test_create_invoice_endpoint_requires_jwt(client: Any, invoice_routes: Any) -> None:
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/invoices", json={"label": "x", "currency": "USD"}
    )
    assert resp.status_code == 401


def test_get_invoice_endpoint_200_for_advisor(
    client: Any, invoice_routes: Any, make_token: Any
) -> None:
    # advisor read passes the access gate
    resp = client.get(f"/invoices/{uuid.uuid4()}", headers=_headers(make_token))
    assert resp.status_code == 200, resp.text


def test_get_invoice_endpoint_forbidden_for_stranger(
    client: Any, invoice_routes: Any, make_token: Any
) -> None:
    # not advisor, not owner, not creator -> 403
    invoice_routes["returns"]["is_advisor"] = False
    resp = client.get(f"/invoices/{uuid.uuid4()}", headers=_headers(make_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"
