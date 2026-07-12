"""Payment processing for issued invoices (M005/I2, hardening I2/I3).

A traveler pays an *issued* invoice: we total the ledger, charge the tokenized
card through the configured (gateway-agnostic) :class:`PaymentGateway`, record a
:class:`Payment` (a row per attempt — succeeded or failed), and on success flip
the invoice to ``paid``. The charge carries OUR ``gateway_reference`` onto the
processor side and ``{invoice,itinerary,client}`` metadata, so a processor
dashboard row maps back to our invoice and vice-versa.

Hardening (no double-charge, no event-loop block):

- the synchronous gateway call is offloaded to a worker thread (it does network
  I/O — calling it inline would stall the whole event loop) and is bounded by
  the gateway's configured timeout;
- the invoice row is **locked** (``SELECT … FOR UPDATE``) for the duration of the
  charge, so two concurrent pays serialize — the loser sees ``paid`` and is
  refused instead of charging twice;
- an optional **idempotency key** lets a client safely retry: a second pay with
  the same key replays the prior outcome rather than issuing a new charge;
- a gateway *error* (timeout/network — outcome unknown) records NO payment and
  returns ``payment_gateway_unavailable`` so the client can retry with the same
  key; only a settled *decline* records a ``failed`` row.

Redaction discipline: never log the nonce, the processor transaction id, the
card last-four, or the raw payload.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial

import anyio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, InvoiceStatus, Payment, PaymentQuote, PaymentStatus
from app.observability import emit_metric, span
from app.payments.base import PaymentGateway, PaymentGatewayError, new_gateway_reference
from app.services import invoices as invoices_svc
from app.services.fx import FxService
from app.services.invoices import _invoice_total, mark_invoice_paid
from app.services.itineraries import ActorContext, ItineraryError, ItineraryOutcome

logger = logging.getLogger("ov_black.payments")

_ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")


async def create_payment_quote(
    session: AsyncSession,
    fx: FxService,
    *,
    invoice_id: uuid.UUID,
) -> PaymentQuote | ItineraryError:
    """Freeze a short-lived pay-time FX lock over a settlement invoice (0050).

    Pulls the current native→settlement rate per currency, computes the exact
    charge in the invoice's ``settlement_currency``, and persists it locked for
    ``payment_quote_ttl_seconds``. The pay call references the quote and charges the
    locked amount; an expired/consumed quote forces a re-quote. Only for issued
    invoices with a settlement currency and FX configured — a native invoice pays
    directly (``no_settlement_currency``)."""
    from app.config import get_settings

    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        return view
    invoice = view.invoice
    if invoice.status is not InvoiceStatus.issued:
        return _err("invoice_not_issued")
    target = invoice.settlement_currency
    if target is None:
        return _err("no_settlement_currency")
    if not fx.enabled:
        return _err("fx_unavailable")

    rates: dict[str, str] = {}
    total = _ZERO
    for currency, subtotal in view.subtotals.items():
        if subtotal == _ZERO:
            continue
        rate = await fx.get_rate(currency, target)
        if rate is None:
            return _err("rate_unavailable")
        rates[currency] = str(rate)
        total += subtotal * rate
    total = total.quantize(_CENTS)
    if total <= _ZERO:
        return _err("nothing_to_pay")

    ttl = get_settings().payment_quote_ttl_seconds
    quote = PaymentQuote(
        invoice_id=invoice_id,
        settlement_currency=target,
        settlement_amount=total,
        rates=rates,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    session.add(quote)
    await session.flush()
    await session.commit()
    logger.info(
        "invoice.payment_quote",
        extra={"invoice_id": str(invoice_id), "quote_id": str(quote.id)},
    )
    return quote


async def _load_valid_quote(
    session: AsyncSession, invoice_id: uuid.UUID, quote_id: uuid.UUID
) -> PaymentQuote | None:
    """The quote if it belongs to this invoice and is neither consumed nor expired."""
    quote = (
        await session.execute(
            select(PaymentQuote).where(
                PaymentQuote.id == quote_id,
                PaymentQuote.invoice_id == invoice_id,
            )
        )
    ).scalar_one_or_none()
    if quote is None or quote.consumed_at is not None:
        return None
    if quote.expires_at <= datetime.now(UTC):
        return None
    return quote


def _err(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail=detail)


async def generate_client_token(gateway: PaymentGateway | None) -> str | ItineraryError:
    """A processor client token for the browser drop-in to tokenize a card.

    Read-only, so it is safely retried within a bounded budget on a *retryable*
    gateway error. Offloaded to a thread — the SDK call is blocking network I/O.
    """
    if gateway is None:
        return _err("payments_unconfigured")

    from app.config import get_settings

    attempts = get_settings().payment_token_max_retries + 1
    reason = "gateway_error"
    for attempt in range(attempts):
        try:
            async with span("payment.gateway.client_token", metric=True, gateway=gateway.name):
                return await anyio.to_thread.run_sync(gateway.generate_client_token)
        except PaymentGatewayError as exc:
            reason = exc.reason
            if not exc.retryable or attempt == attempts - 1:
                break
            await anyio.sleep(min(0.2 * (2**attempt), 1.0))
    logger.warning(
        "invoice.payment_token.error",
        extra={"gateway": gateway.name, "reason": reason},
    )
    emit_metric("payment.token_error", 1, dimensions={"Gateway": gateway.name})
    return _err("payment_token_unavailable")


async def _load_invoice_for_update(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice | None:
    """Load + row-lock the invoice so concurrent pays serialize on this row."""
    return (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()


async def _find_payment_by_key(
    session: AsyncSession, invoice_id: uuid.UUID, idempotency_key: str
) -> Payment | None:
    return (
        await session.execute(
            select(Payment).where(
                Payment.invoice_id == invoice_id,
                Payment.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


def _replay(payment: Payment) -> Payment | ItineraryError:
    """The outcome to return for an idempotent replay of a recorded attempt."""
    if payment.status is PaymentStatus.succeeded:
        return payment
    return _err("payment_declined")


async def pay_invoice(
    session: AsyncSession,
    actor: ActorContext,
    gateway: PaymentGateway | None,
    *,
    invoice_id: uuid.UUID,
    payment_method_nonce: str,
    client_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    quote_id: uuid.UUID | None = None,
) -> Payment | ItineraryError:
    """Charge an issued invoice and record the payment.

    An invoice with a ``settlement_currency`` (0050) charges in that currency at a
    **locked** pay-time quote: ``quote_id`` must reference a fresh, unconsumed
    :class:`PaymentQuote` (``quote_required`` / ``quote_expired`` otherwise), and the
    charge is its frozen ``settlement_amount``. A native invoice (no settlement)
    charges Σ(lines) in its own currency as before.

    On a settled sale the invoice flips to ``paid`` and the ``succeeded`` payment
    is returned. On a decline the ``failed`` payment is still recorded (audit)
    and a ``payment_declined`` error is returned. ``payments_unconfigured`` when
    no gateway is wired; ``payment_gateway_unavailable`` when the gateway errored
    (outcome unknown — safe to retry with the same ``idempotency_key``).
    """
    if gateway is None:
        return _err("payments_unconfigured")

    # Fast path: a prior attempt with this key short-circuits without locking.
    if idempotency_key:
        prior = await _find_payment_by_key(session, invoice_id, idempotency_key)
        if prior is not None:
            logger.info(
                "invoice.payment.idempotent_replay",
                extra={"invoice_id": str(invoice_id), "payment_id": str(prior.id)},
            )
            return _replay(prior)

    # Lock the invoice for the whole charge so concurrent pays can't both see
    # ``issued`` and charge twice — the second waits, then re-checks below.
    invoice = await _load_invoice_for_update(session, invoice_id)
    if invoice is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    # Authoritative replay check, now under the lock (covers the concurrent
    # same-key race the fast path above can miss).
    if idempotency_key:
        prior = await _find_payment_by_key(session, invoice_id, idempotency_key)
        if prior is not None:
            await session.rollback()
            return _replay(prior)

    # From here on the invoice row is locked; every non-charging exit must
    # rollback to release it promptly (else it is held until the request-scoped
    # session closes — and a concurrent reader/cleanup would block meanwhile).
    if invoice.status is not InvoiceStatus.issued:
        await session.rollback()
        return _err("invoice_not_issued")

    # Resolve what to charge: a settlement invoice charges the locked quote amount
    # in the pay currency; a native invoice charges Σ(lines) in its own currency.
    quote: PaymentQuote | None = None
    if invoice.settlement_currency is not None:
        if quote_id is None:
            await session.rollback()
            return _err("quote_required")
        quote = await _load_valid_quote(session, invoice_id, quote_id)
        if quote is None:
            await session.rollback()
            return _err("quote_expired")
        charge_amount = quote.settlement_amount
        charge_currency = quote.settlement_currency
    else:
        charge_amount = await _invoice_total(session, invoice_id)
        charge_currency = invoice.currency
    if charge_amount <= _ZERO:
        await session.rollback()
        return _err("nothing_to_pay")

    reference = new_gateway_reference(invoice_id)
    metadata = {
        "invoice_id": str(invoice_id),
        "itinerary_id": str(invoice.itinerary_id),
    }
    if client_id is not None:
        metadata["client_id"] = str(client_id)

    # The gateway is synchronous network I/O — run it off the event loop, timed.
    try:
        async with span("payment.gateway.sale", metric=True, gateway=gateway.name):
            sale = await anyio.to_thread.run_sync(
                partial(
                    gateway.sale,
                    amount=charge_amount,
                    currency=charge_currency,
                    payment_method_nonce=payment_method_nonce,
                    reference=reference,
                    metadata=metadata,
                )
            )
    except PaymentGatewayError as exc:
        # Outcome unknown (timeout/network). Record nothing and release the lock;
        # a client retry with the same idempotency key is the safe recovery.
        await session.rollback()
        logger.warning(
            "invoice.payment.gateway_error",
            extra={
                "invoice_id": str(invoice_id),
                "gateway": gateway.name,
                "reason": exc.reason,
                "actor_kind": actor.kind.value,
            },
        )
        emit_metric("payment.gateway_error", 1, dimensions={"Gateway": gateway.name})
        return _err("payment_gateway_unavailable")

    payment = Payment(
        invoice_id=invoice_id,
        amount=charge_amount,
        currency=charge_currency,
        status=PaymentStatus.succeeded if sale.ok else PaymentStatus.failed,
        gateway=gateway.name,
        gateway_reference=reference,
        idempotency_key=idempotency_key,
        processor_transaction_id=sale.processor_transaction_id,
        instrument_type=sale.instrument_type,
        last_four=sale.last_four,
        processor_response=sale.processor_response,
        raw=sale.raw,
    )
    session.add(payment)

    if sale.ok:
        # Consume the FX lock so it can't be replayed for another charge.
        if quote is not None:
            quote.consumed_at = datetime.now(UTC)
        marked = await mark_invoice_paid(session, invoice_id=invoice_id)
        if isinstance(marked, ItineraryError):  # pragma: no cover — status re-checked above
            await session.rollback()
            return marked

    try:
        await session.flush()
        await session.commit()
    except IntegrityError:
        # Lost the race on the (invoice_id, idempotency_key) unique index — a
        # concurrent request recorded this exact attempt. Replay its outcome.
        await session.rollback()
        if idempotency_key:
            prior = await _find_payment_by_key(session, invoice_id, idempotency_key)
            if prior is not None:
                return _replay(prior)
        raise

    # Never log nonce / txn id / last_four / raw.
    logger.info(
        "invoice.payment",
        extra={
            "invoice_id": str(invoice_id),
            "payment_id": str(payment.id),
            "gateway": gateway.name,
            "status": payment.status.value,
            "actor_kind": actor.kind.value,
        },
    )
    emit_metric(
        "payment.count",
        1,
        dimensions={"Gateway": gateway.name, "Status": payment.status.value},
    )

    if not sale.ok:
        return _err("payment_declined")
    return payment
