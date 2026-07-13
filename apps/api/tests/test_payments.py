"""Payments — pay an issued invoice (M005/I2).

Integration tests against a local Supabase Postgres, with a ``FakeGateway``
injected so no Braintree credentials are needed:

- a settled sale records a ``succeeded`` payment with the normalized SaleResult
  fields + the cross-reference ``gateway_reference`` and flips the invoice to
  ``paid``;
- a declined sale records a ``failed`` payment and returns ``payment_declined``,
  leaving the invoice ``issued``;
- the gateway receives the ``reference`` + ``{invoice,itinerary,client}``
  metadata (the two-way cross-reference);
- only an *issued* invoice is payable; ``payments_unconfigured`` when no gateway
  is wired; and the redaction sweep finds no secret in the logs.

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import UTC
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import Invoice, InvoiceStatus, Payment, PaymentStatus
from app.payments.base import BillingInfo, PaymentGatewayError, SaleResult
from app.payments.braintree_gateway import DECLINED_NONCE, VALID_NONCE, FakeGateway
from app.services.invoices import add_line_item, create_invoice, get_invoice, issue_invoice
from app.services.itineraries import ActorContext, ActorKind, ItineraryError, create_itinerary
from app.services.payments import create_payment_quote, generate_client_token, pay_invoice
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


def _actor(kind: ActorKind = ActorKind.USER) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"pay-{kind.value}")


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
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
    finally:
        await engine.dispose()


async def _issued_invoice(
    session: AsyncSession, *, amount: str = "500.00", currency: str = "USD"
) -> Invoice:
    itin = await create_itinerary(session, _actor(ActorKind.ADVISOR), title="pay")
    invoice = await create_invoice(
        session, _actor(ActorKind.ADVISOR), itinerary_id=itin.id, label="Balance", currency=currency
    )
    assert isinstance(invoice, Invoice)
    line = await add_line_item(
        session,
        _actor(ActorKind.ADVISOR),
        invoice_id=invoice.id,
        description="Suite",
        amount=Decimal(amount),
        currency=currency,
    )
    assert not isinstance(line, ItineraryError)
    issued = await issue_invoice(session, _actor(ActorKind.ADVISOR), invoice_id=invoice.id)
    assert isinstance(issued, Invoice)
    return invoice


class _SpyGateway(FakeGateway):
    """FakeGateway that records the last sale() call for cross-ref assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def sale(self, **kwargs: Any) -> SaleResult:
        self.calls.append(kwargs)
        return super().sale(**kwargs)


@integration
@pytest.mark.asyncio
async def test_pay_settles_and_marks_paid(db_session: AsyncSession) -> None:
    invoice = await _issued_invoice(db_session, amount="500.00")
    gateway = _SpyGateway()
    try:
        payment = await pay_invoice(
            db_session,
            _actor(),
            gateway,
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            client_id=None,
        )
        assert isinstance(payment, Payment)
        assert payment.status is PaymentStatus.succeeded
        assert payment.amount == Decimal("500.00")
        assert payment.gateway == "fake"
        assert payment.gateway_reference.startswith(str(invoice.id))
        assert payment.processor_transaction_id == f"fake-{payment.gateway_reference}"
        assert payment.last_four == "1111"

        # cross-reference: our reference + metadata reached the gateway
        call = gateway.calls[-1]
        assert call["reference"] == payment.gateway_reference
        assert call["metadata"]["invoice_id"] == str(invoice.id)
        assert call["metadata"]["itinerary_id"] == str(invoice.itinerary_id)

        view = await get_invoice(db_session, invoice.id)
        assert not isinstance(view, ItineraryError)
        assert view.invoice.status is InvoiceStatus.paid
        assert len(view.payments) == 1
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_pay_forwards_billing_to_gateway(db_session: AsyncSession) -> None:
    """The payer's name + address reach the gateway's billing block (and, via the
    FakeGateway echo, land in the recorded payment's ``raw``)."""
    invoice = await _issued_invoice(db_session, amount="500.00")
    gateway = _SpyGateway()
    billing = BillingInfo(
        first_name="Ada",
        last_name="Lovelace",
        street_address="1 Analytical Way",
        locality="London",
        region="LDN",
        postal_code="EC1A 1AA",
        country_code_alpha2="GB",
    )
    try:
        payment = await pay_invoice(
            db_session,
            _actor(),
            gateway,
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            client_id=None,
            billing=billing,
        )
        assert isinstance(payment, Payment)
        assert gateway.calls[-1]["billing"] is billing
        # FakeGateway echoes the mapped billing block into ``raw`` for assertion.
        assert payment.raw["billing"]["first_name"] == "Ada"
        assert payment.raw["billing"]["street_address"] == "1 Analytical Way"
        assert payment.raw["billing"]["country_code_alpha2"] == "GB"
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_declined_records_failed_and_keeps_issued(db_session: AsyncSession) -> None:
    invoice = await _issued_invoice(db_session, amount="500.00")
    try:
        result = await pay_invoice(
            db_session,
            _actor(),
            FakeGateway(),
            invoice_id=invoice.id,
            payment_method_nonce=DECLINED_NONCE,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "payment_declined"

        view = await get_invoice(db_session, invoice.id)
        assert not isinstance(view, ItineraryError)
        assert view.invoice.status is InvoiceStatus.issued  # not flipped
        assert len(view.payments) == 1
        assert view.payments[0].status is PaymentStatus.failed
        assert view.payments[0].processor_response is not None
    finally:
        await _cleanup(invoice.itinerary_id)


class _ErroringGateway(FakeGateway):
    """Gateway whose charge raises an infra error (timeout) — outcome unknown."""

    def sale(self, **kwargs: Any) -> SaleResult:
        raise PaymentGatewayError("ReadTimeoutError", retryable=False)


@integration
@pytest.mark.asyncio
async def test_gateway_error_records_nothing_and_keeps_issued(db_session: AsyncSession) -> None:
    invoice = await _issued_invoice(db_session, amount="250.00")
    # Capture ids: the gateway-error path rolls back (releasing the lock), which
    # expires the shared-session ORM objects.
    invoice_id = invoice.id
    itinerary_id = invoice.itinerary_id
    try:
        result = await pay_invoice(
            db_session,
            _actor(),
            _ErroringGateway(),
            invoice_id=invoice_id,
            payment_method_nonce=VALID_NONCE,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "payment_gateway_unavailable"

        view = await get_invoice(db_session, invoice_id)
        assert not isinstance(view, ItineraryError)
        # Outcome unknown → record NOTHING, leave the invoice payable for retry.
        assert view.invoice.status is InvoiceStatus.issued
        assert len(view.payments) == 0
    finally:
        await _cleanup(itinerary_id)


@integration
@pytest.mark.asyncio
async def test_idempotency_key_replays_and_does_not_double_charge(
    db_session: AsyncSession,
) -> None:
    invoice = await _issued_invoice(db_session, amount="999.00")
    gateway = _SpyGateway()
    try:
        first = await pay_invoice(
            db_session,
            _actor(),
            gateway,
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            idempotency_key="idem-1",
        )
        assert isinstance(first, Payment)

        # Same key again: replays the recorded outcome, charges nothing more.
        second = await pay_invoice(
            db_session,
            _actor(),
            gateway,
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            idempotency_key="idem-1",
        )
        assert isinstance(second, Payment)
        assert second.id == first.id
        assert len(gateway.calls) == 1  # the gateway was hit exactly once

        view = await get_invoice(db_session, invoice.id)
        assert not isinstance(view, ItineraryError)
        assert view.invoice.status is InvoiceStatus.paid
        assert len(view.payments) == 1
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_pay_requires_issued(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="draftpay")
    # Capture ids as plain values: pay_invoice rolls back (releasing the row
    # lock) on the not-issued path, which expires shared-session ORM objects.
    itin_id = itin.id
    try:
        invoice = await create_invoice(
            db_session, _actor(ActorKind.ADVISOR), itinerary_id=itin_id, label="x", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        result = await pay_invoice(
            db_session,
            _actor(),
            FakeGateway(),
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "invoice_not_issued"
    finally:
        await _cleanup(itin_id)


@integration
@pytest.mark.asyncio
async def test_unconfigured_gateway_refuses(db_session: AsyncSession) -> None:
    invoice = await _issued_invoice(db_session)
    try:
        result = await pay_invoice(
            db_session,
            _actor(),
            None,  # production-without-keys
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "payments_unconfigured"
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_pay_does_not_leak_secrets_to_logs(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    invoice = await _issued_invoice(db_session)
    try:
        with caplog.at_level(logging.INFO):
            payment = await pay_invoice(
                db_session,
                _actor(),
                FakeGateway(),
                invoice_id=invoice.id,
                payment_method_nonce=VALID_NONCE,
            )
        assert isinstance(payment, Payment)
        blob = "\n".join(r.getMessage() + str(getattr(r, "__dict__", {})) for r in caplog.records)
        assert VALID_NONCE not in blob
        assert (payment.processor_transaction_id or "ZZZ") not in blob
        assert "1111" not in blob  # last_four
    finally:
        await _cleanup(invoice.itinerary_id)


async def test_generate_client_token_unconfigured() -> None:
    result = await generate_client_token(None)
    assert isinstance(result, ItineraryError)
    assert result.detail == "payments_unconfigured"


async def test_fake_gateway_token() -> None:
    assert await generate_client_token(FakeGateway()) == "fake-client-token"


# ── FakeGateway.refund dispatch (settled → refund, unsettled → void, decline) ──


def test_fake_gateway_refund_settled_charge() -> None:
    res = FakeGateway().refund(
        processor_transaction_id="fake-abc", amount=Decimal("100.00"), reference="refund:1:aa"
    )
    assert res.ok is True
    assert res.kind == "refund"
    assert res.status == "refunded"


def test_fake_gateway_voids_unsettled_charge() -> None:
    res = FakeGateway().refund(
        processor_transaction_id="fake-unsettled-abc",
        amount=Decimal("100.00"),
        reference="refund:1:bb",
    )
    assert res.ok is True
    assert res.kind == "void"
    assert res.status == "voided"


def test_fake_gateway_refund_declines() -> None:
    res = FakeGateway().refund(
        processor_transaction_id="fake-declined-abc",
        amount=Decimal("100.00"),
        reference="refund:1:cc",
    )
    assert res.ok is False
    assert res.status == "failed"


# ── Router (service stubbed) ───────────────────────────────────────────────


@pytest.fixture()
def pay_routes(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.auth import AuthenticatedUser
    from app.db import get_session
    from app.main import app as fastapi_app
    from app.models import Itinerary
    from app.routers import invoices as ri
    from app.services.invoices import InvoiceView

    def _invoice() -> Invoice:
        return Invoice(
            id=uuid.uuid4(),
            itinerary_id=uuid.uuid4(),
            label="Balance",
            status=InvoiceStatus.issued,
            currency="USD",
            created_at=_now(),
        )

    async def _get(_s: Any, invoice_id: uuid.UUID) -> Any:
        inv = _invoice()
        inv.id = invoice_id
        return InvoiceView(
            invoice=inv,
            lines=[],
            total=Decimal("500.00"),
            payments=[],
            subtotals={"USD": Decimal("500.00")},
        )

    async def _load_itin(_s: Any, _iid: uuid.UUID) -> Any:
        return Itinerary(id=uuid.uuid4(), client_id=None, created_by=None)

    async def _is_advisor(_s: Any, _uid: Any) -> bool:
        return True

    async def _pay(_s: Any, _actor: Any, _gateway: Any, **kw: Any) -> Any:
        return Payment(
            id=uuid.uuid4(),
            invoice_id=kw["invoice_id"],
            amount=Decimal("500.00"),
            currency="USD",
            status=PaymentStatus.succeeded,
            gateway="fake",
            gateway_reference="ref-1",
            created_at=_now(),
        )

    monkeypatch.setattr(ri.invoices_svc, "get_invoice", _get)
    monkeypatch.setattr(ri.payments_svc, "pay_invoice", _pay)
    monkeypatch.setattr(ri, "_load_itinerary", _load_itin)
    monkeypatch.setattr(ri, "_is_requester_advisor", _is_advisor)

    async def _dep() -> Any:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _dep
    fastapi_app.dependency_overrides[ri.get_payment_gateway] = lambda: FakeGateway()
    try:
        yield {}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(ri.get_payment_gateway, None)
    _ = AuthenticatedUser  # imported for symmetry with other router fixtures


def _now() -> Any:
    from datetime import datetime

    return datetime.now(UTC)


def _headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


def test_pay_endpoint_200(client: Any, pay_routes: Any, make_token: Any) -> None:
    invoice_id = uuid.uuid4()
    resp = client.post(
        f"/invoices/{invoice_id}/pay",
        json={"payment_method_nonce": VALID_NONCE},
        headers=_headers(make_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(invoice_id)


def test_pay_endpoint_requires_jwt(client: Any, pay_routes: Any) -> None:
    resp = client.post(f"/invoices/{uuid.uuid4()}/pay", json={"payment_method_nonce": VALID_NONCE})
    assert resp.status_code == 401


def test_payment_token_endpoint_200(client: Any, pay_routes: Any, make_token: Any) -> None:
    resp = client.post(f"/invoices/{uuid.uuid4()}/payment-token", headers=_headers(make_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_token"] == "fake-client-token"


# ── Settlement (pay-currency) quotes + charging (0050) ───────────────────────


class _FakeFx:
    """Minimal FxService stand-in for payment-quote tests."""

    def __init__(self, rates: dict[tuple[str, str], Decimal], *, enabled: bool = True) -> None:
        self._rates = rates
        self.enabled = enabled

    async def get_rate(self, base: str, target: str) -> Decimal | None:
        if base == target:
            return Decimal(1)
        return self._rates.get((base, target))

    def fetched_at(self, base: str) -> None:
        return None


async def _issued_settlement_invoice(
    session: AsyncSession, *, native: str = "EUR", amount: str = "1000.00", settlement: str = "USD"
) -> Invoice:
    itin = await create_itinerary(session, _actor(ActorKind.ADVISOR), title="settle")
    invoice = await create_invoice(
        session,
        _actor(ActorKind.ADVISOR),
        itinerary_id=itin.id,
        label="Deposit",
        currency=native,
        settlement_currency=settlement,
    )
    assert isinstance(invoice, Invoice)
    line = await add_line_item(
        session,
        _actor(ActorKind.ADVISOR),
        invoice_id=invoice.id,
        description="Suite",
        amount=Decimal(amount),
        currency=native,
    )
    assert not isinstance(line, ItineraryError)
    issued = await issue_invoice(session, _actor(ActorKind.ADVISOR), invoice_id=invoice.id)
    assert isinstance(issued, Invoice)
    return invoice


@integration
@pytest.mark.asyncio
async def test_payment_quote_locks_the_settlement_amount(db_session: AsyncSession) -> None:
    invoice = await _issued_settlement_invoice(db_session, native="EUR", amount="1000.00")
    try:
        fx = _FakeFx({("EUR", "USD"): Decimal("1.10")})
        quote = await create_payment_quote(db_session, fx, invoice_id=invoice.id)  # type: ignore[arg-type]
        assert not isinstance(quote, ItineraryError)
        assert quote.settlement_currency == "USD"
        assert quote.settlement_amount == Decimal("1100.00")  # 1000 EUR × 1.10
        assert quote.rates == {"EUR": "1.10"}
        assert quote.consumed_at is None
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_settlement_pay_charges_the_locked_quote(db_session: AsyncSession) -> None:
    invoice = await _issued_settlement_invoice(db_session, native="EUR", amount="1000.00")
    try:
        fx = _FakeFx({("EUR", "USD"): Decimal("1.10")})
        quote = await create_payment_quote(db_session, fx, invoice_id=invoice.id)  # type: ignore[arg-type]
        assert not isinstance(quote, ItineraryError)
        gateway = _SpyGateway()
        payment = await pay_invoice(
            db_session,
            _actor(),
            gateway,
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            quote_id=quote.id,
        )
        assert isinstance(payment, Payment)
        # Charged the LOCKED settlement figure in the pay currency — not native EUR.
        assert payment.amount == Decimal("1100.00")
        assert payment.currency == "USD"
        call = gateway.calls[-1]
        assert call["amount"] == Decimal("1100.00")
        assert call["currency"] == "USD"
        view = await get_invoice(db_session, invoice.id)
        assert not isinstance(view, ItineraryError)
        assert view.invoice.status is InvoiceStatus.paid
    finally:
        await _cleanup(invoice.itinerary_id)


@integration
@pytest.mark.asyncio
async def test_settlement_pay_requires_a_quote(db_session: AsyncSession) -> None:
    invoice = await _issued_settlement_invoice(db_session)
    # Capture up front: the no-quote path rolls back, which expires the ORM object,
    # so a later attribute read would trigger a lazy load outside the async context.
    itinerary_id = invoice.itinerary_id
    try:
        result = await pay_invoice(
            db_session,
            _actor(),
            _SpyGateway(),
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "quote_required"
    finally:
        await _cleanup(itinerary_id)


@integration
@pytest.mark.asyncio
async def test_settlement_pay_rejects_an_expired_quote(db_session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    invoice = await _issued_settlement_invoice(db_session)
    itinerary_id = invoice.itinerary_id
    try:
        fx = _FakeFx({("EUR", "USD"): Decimal("1.10")})
        quote = await create_payment_quote(db_session, fx, invoice_id=invoice.id)  # type: ignore[arg-type]
        assert not isinstance(quote, ItineraryError)
        quote.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        result = await pay_invoice(
            db_session,
            _actor(),
            _SpyGateway(),
            invoice_id=invoice.id,
            payment_method_nonce=VALID_NONCE,
            quote_id=quote.id,
        )
        assert isinstance(result, ItineraryError)
        assert result.detail == "quote_expired"
    finally:
        await _cleanup(itinerary_id)
