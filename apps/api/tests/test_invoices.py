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
    mark_invoice_viewed,
    pay_context,
    remove_line_item,
    settlement_display,
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
async def test_add_line_item_from_node_expands_per_person_by_party_size(
    db_session: AsyncSession,
) -> None:
    """A per_person charge line bills the whole party so it matches what the money
    gate later books for the same node."""
    itin = await create_itinerary(db_session, _actor(), title="pp line")
    try:
        party_id = uuid.uuid4()
        await db_session.execute(
            text("insert into public.parties (id, itinerary_id, label) values (:p, :i, 'all')"),
            {"p": party_id, "i": itin.id},
        )
        # Two named companions → a party of three (the account holder is the
        # implicit floor resolve_party_size adds).
        for name in ("a", "b"):
            await db_session.execute(
                text("insert into public.travelers (party_id, name) values (:p, :n)"),
                {"p": party_id, "n": name},
            )
        await db_session.commit()

        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            status=NodeStatus.approved,
            title="Guide",
            cost_amount=Decimal("750.00"),
            cost_currency="USD",
            cost_kind=CostKind.per_person,
        )
        assert isinstance(node, Node)
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Dep", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        charge = await add_line_item_from_node(
            db_session, _actor(), invoice_id=invoice.id, node_id=node.id
        )
        assert not isinstance(charge, ItineraryError)
        assert charge.amount == Decimal("2250.00")  # 750 × 3 (2 companions + account holder)
    finally:
        await _cleanup(itin.id)


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
async def test_manual_line_may_add_a_new_currency(db_session: AsyncSession) -> None:
    # Since 0050 one invoice may hold several NATIVE currencies — a manual EUR line
    # onto a USD-home invoice is accepted and shows up as its own subtotal.
    itin = await create_itinerary(db_session, _actor(), title="cur")
    try:
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Balance", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        usd = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            description="USD fee",
            amount=Decimal("100.00"),
            currency="USD",
            kind=InvoiceLineKind.fee,
        )
        assert isinstance(usd, InvoiceLineItem)
        eur = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            description="EUR fee",
            amount=Decimal("50.00"),
            currency="EUR",
            kind=InvoiceLineKind.fee,
        )
        assert isinstance(eur, InvoiceLineItem)
        view = await get_invoice(db_session, invoice.id)
        assert isinstance(view, InvoiceView)
        assert view.subtotals == {"USD": Decimal("100.00"), "EUR": Decimal("50.00")}
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
            status=NodeStatus.pending,
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
async def test_node_split_across_deposit_and_balance(db_session: AsyncSession) -> None:
    """A node's cost may be split across invoices (a deposit + the balance), but the
    running charge total for that node can't exceed its effective cost."""
    itin = await create_itinerary(db_session, _actor(), title="split")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")

        deposit = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="USD"
        )
        balance = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Balance", currency="USD"
        )
        assert isinstance(deposit, Invoice)
        assert isinstance(balance, Invoice)

        # 30% deposit against the node, then the 70% balance on a second invoice —
        # the SAME node shared across two lines, netting to its full cost.
        dep_line = await add_line_item(
            db_session,
            _actor(),
            invoice_id=deposit.id,
            kind=InvoiceLineKind.charge,
            description="Aman (deposit)",
            amount=Decimal("300.00"),
            currency="USD",
            node_id=node.id,
        )
        assert isinstance(dep_line, InvoiceLineItem)
        assert dep_line.node_id == node.id

        bal_line = await add_line_item(
            db_session,
            _actor(),
            invoice_id=balance.id,
            kind=InvoiceLineKind.charge,
            description="Aman (balance)",
            amount=Decimal("700.00"),
            currency="USD",
            node_id=node.id,
        )
        assert isinstance(bal_line, InvoiceLineItem)

        # A further charge against the now-fully-billed node is refused.
        over = await add_line_item(
            db_session,
            _actor(),
            invoice_id=balance.id,
            kind=InvoiceLineKind.charge,
            description="Aman (again)",
            amount=Decimal("100.00"),
            currency="USD",
            node_id=node.id,
        )
        assert isinstance(over, ItineraryError)
        assert over.detail == "node_overbilled"

        # Voiding the balance line frees the node's coverage again: a fresh 700
        # charge is accepted because the reversed line no longer counts.
        rev = await void_line_item(
            db_session, _actor(), invoice_id=balance.id, line_item_id=bal_line.id
        )
        assert isinstance(rev, InvoiceLineItem)
        reinstated = await add_line_item(
            db_session,
            _actor(),
            invoice_id=balance.id,
            kind=InvoiceLineKind.charge,
            description="Aman (rebilled balance)",
            amount=Decimal("700.00"),
            currency="USD",
            node_id=node.id,
        )
        assert isinstance(reinstated, InvoiceLineItem)
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


@integration
@pytest.mark.asyncio
async def test_list_invoices_groups_lines_and_totals_per_invoice(db_session: AsyncSession) -> None:
    # Guards the batched list_invoices (one query for all lines / payments,
    # grouped in Python): distinct non-zero totals must land on the right view.
    itin = await create_itinerary(db_session, _actor(), title="grouplist")
    try:
        inv_a = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="A", currency="USD"
        )
        inv_b = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="B", currency="USD"
        )
        assert isinstance(inv_a, Invoice)
        assert isinstance(inv_b, Invoice)
        for amt in ("100.00", "25.00"):  # A: two lines totalling 125.00
            ln = await add_line_item(
                db_session,
                _actor(),
                invoice_id=inv_a.id,
                description="a",
                amount=Decimal(amt),
                currency="USD",
            )
            assert isinstance(ln, InvoiceLineItem)
        ln_b = await add_line_item(  # B: one line of 40.00
            db_session,
            _actor(),
            invoice_id=inv_b.id,
            description="b",
            amount=Decimal("40.00"),
            currency="USD",
        )
        assert isinstance(ln_b, InvoiceLineItem)

        views = {v.invoice.label: v for v in await list_invoices(db_session, itin.id)}
        assert views["A"].total == Decimal("125.00")
        assert len(views["A"].lines) == 2
        assert all(line.invoice_id == inv_a.id for line in views["A"].lines)
        assert views["B"].total == Decimal("40.00")
        assert len(views["B"].lines) == 1
        assert all(line.invoice_id == inv_b.id for line in views["B"].lines)
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
        return InvoiceView(invoice=inv, lines=[], total=Decimal("0.00"), payments=[], subtotals={})

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


# ── Settlement display (0050) — pure conversion, no DB ───────────────────────


class _FakeFx:
    """Minimal FxService stand-in for settlement_display unit tests."""

    def __init__(self, rates: dict[tuple[str, str], Decimal], *, enabled: bool = True) -> None:
        self._rates = rates
        self.enabled = enabled
        self._at = datetime(2026, 7, 12, tzinfo=UTC)

    async def get_rate(self, base: str, target: str) -> Decimal | None:
        if base == target:
            return Decimal(1)
        return self._rates.get((base, target))

    def fetched_at(self, base: str) -> datetime | None:
        return self._at


def _bare_invoice(*, settlement_currency: str | None) -> Invoice:
    return Invoice(
        id=uuid.uuid4(),
        itinerary_id=uuid.uuid4(),
        label="Deposit",
        currency="EUR",
        settlement_currency=settlement_currency,
        status=InvoiceStatus.issued,
        created_at=datetime.now(UTC),
    )


def _bare_view(inv: Invoice, subtotals: dict[str, Decimal]) -> InvoiceView:
    return InvoiceView(
        invoice=inv, lines=[], total=Decimal("0.00"), payments=[], subtotals=subtotals
    )


async def test_settlement_display_converts_multi_currency_subtotals() -> None:
    view = _bare_view(
        _bare_invoice(settlement_currency="USD"),
        {"EUR": Decimal("100.00"), "GBP": Decimal("50.00")},
    )
    fx = _FakeFx({("EUR", "USD"): Decimal("1.10"), ("GBP", "USD"): Decimal("1.25")})
    disp = await settlement_display(view, fx)  # type: ignore[arg-type]
    assert disp is not None
    assert disp.currency == "USD"
    # 100 × 1.10 + 50 × 1.25 = 110.00 + 62.50
    assert disp.total == Decimal("172.50")
    assert disp.rates == {"EUR": Decimal("1.10"), "GBP": Decimal("1.25")}
    assert disp.as_of is not None


async def test_settlement_display_none_when_fx_disabled() -> None:
    view = _bare_view(_bare_invoice(settlement_currency="USD"), {"EUR": Decimal("100.00")})
    fx = _FakeFx({}, enabled=False)
    assert await settlement_display(view, fx) is None  # type: ignore[arg-type]


async def test_settlement_display_none_without_settlement_currency() -> None:
    view = _bare_view(_bare_invoice(settlement_currency=None), {"EUR": Decimal("100.00")})
    fx = _FakeFx({("EUR", "USD"): Decimal("1.10")})
    assert await settlement_display(view, fx) is None  # type: ignore[arg-type]


async def test_settlement_display_none_when_a_rate_is_missing() -> None:
    # All-or-nothing: an unresolved leg drops the whole settlement (no misleading partial).
    view = _bare_view(
        _bare_invoice(settlement_currency="USD"),
        {"EUR": Decimal("100.00"), "JPY": Decimal("2000")},
    )
    fx = _FakeFx({("EUR", "USD"): Decimal("1.10")})  # no JPY→USD
    assert await settlement_display(view, fx) is None  # type: ignore[arg-type]


# ── first_viewed_at (0050) ───────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_first_viewed_at_stamped_once(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="viewed")
    try:
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        line = await add_line_item(
            db_session,
            _actor(),
            invoice_id=invoice.id,
            description="fee",
            amount=Decimal("100.00"),
            currency="USD",
            kind=InvoiceLineKind.fee,
        )
        assert isinstance(line, InvoiceLineItem)

        await mark_invoice_viewed(db_session, invoice_id=invoice.id)
        v1 = await get_invoice(db_session, invoice.id)
        assert isinstance(v1, InvoiceView)
        assert v1.invoice.first_viewed_at is not None
        first = v1.invoice.first_viewed_at

        # Idempotent — a second view never re-stamps.
        await mark_invoice_viewed(db_session, invoice_id=invoice.id)
        v2 = await get_invoice(db_session, invoice.id)
        assert isinstance(v2, InvoiceView)
        assert v2.invoice.first_viewed_at == first
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_create_invoice_defaults_settlement_from_client_preference(
    db_session: AsyncSession,
) -> None:
    # The settlement currency defaults to the owning client's preferred_currency.
    owner_id = uuid.uuid4()
    client_id = uuid.uuid4()
    await db_session.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": owner_id, "email": f"pref-{owner_id}@x.com"},
    )
    await db_session.execute(
        text(
            "insert into public.clients (id, owner_id, full_name, email, preferred_currency) "
            "values (:id, :o, 'Pref Traveler', :e, 'USD')"
        ),
        {"id": client_id, "o": owner_id, "e": f"pref-{client_id}@x.com"},
    )
    await db_session.commit()
    itin = await create_itinerary(db_session, _actor(), title="pref", client_id=client_id)
    try:
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Deposit", currency="EUR"
        )
        assert isinstance(invoice, Invoice)
        assert invoice.settlement_currency == "USD"
    finally:
        await _cleanup(itin.id)
        await db_session.execute(text("delete from public.clients where id = :i"), {"i": client_id})
        await db_session.execute(text("delete from auth.users where id = :i"), {"i": owner_id})
        await db_session.commit()


@integration
@pytest.mark.asyncio
async def test_pay_context_returns_trip_and_client_billing(
    db_session: AsyncSession,
) -> None:
    # The pay page's prefill/narration source: trip title + owning client's billing.
    owner_id = uuid.uuid4()
    client_id = uuid.uuid4()
    await db_session.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": owner_id, "email": f"ctx-{owner_id}@x.com"},
    )
    await db_session.execute(
        text(
            "insert into public.clients (id, owner_id, full_name, email, address, "
            "city, region, postal_code, country_code, preferred_currency) "
            "values (:id, :o, 'Ada Lovelace', :e, '1 Analytical Way', 'London', "
            "'LDN', 'EC1A 1AA', 'GB', 'GBP')"
        ),
        {"id": client_id, "o": owner_id, "e": f"ctx-{client_id}@x.com"},
    )
    await db_session.commit()
    itin = await create_itinerary(
        db_session, _actor(), title="Kyoto in autumn", client_id=client_id
    )
    try:
        ctx = await pay_context(db_session, itin.id)
        assert not isinstance(ctx, ItineraryError)
        assert ctx.itinerary_title == "Kyoto in autumn"
        assert ctx.full_name == "Ada Lovelace"
        assert ctx.address == "1 Analytical Way"
        assert ctx.city == "London"
        assert ctx.region == "LDN"
        assert ctx.postal_code == "EC1A 1AA"
        assert ctx.country_code == "GB"
        assert ctx.preferred_currency == "GBP"

        # A missing itinerary collapses to NOT_FOUND.
        missing = await pay_context(db_session, uuid.uuid4())
        assert isinstance(missing, ItineraryError)
    finally:
        await _cleanup(itin.id)
        await db_session.execute(text("delete from public.clients where id = :i"), {"i": client_id})
        await db_session.execute(text("delete from auth.users where id = :i"), {"i": owner_id})
        await db_session.commit()
