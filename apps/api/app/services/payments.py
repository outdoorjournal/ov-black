"""Payment processing for issued invoices (M005/I2, D025/D-PAY).

A traveler pays an *issued* invoice: we total the ledger, charge the tokenized
card through the configured (gateway-agnostic) :class:`PaymentGateway`, record a
:class:`Payment` (a row per attempt — succeeded or failed), and on success flip
the invoice to ``paid``. The charge carries OUR ``gateway_reference`` onto the
processor side and ``{invoice,itinerary,client}`` metadata, so a processor
dashboard row maps back to our invoice and vice-versa.

Redaction discipline: never log the nonce, the processor transaction id, the
card last-four, or the raw payload.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InvoiceStatus, Payment, PaymentStatus
from app.payments.base import PaymentGateway, new_gateway_reference
from app.services.invoices import _invoice_total, _load_invoice, mark_invoice_paid
from app.services.itineraries import ActorContext, ItineraryError, ItineraryOutcome

logger = logging.getLogger("ov_black.payments")

_ZERO = Decimal("0.00")


def _err(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail=detail)


def generate_client_token(gateway: PaymentGateway | None) -> str | ItineraryError:
    """A processor client token for the browser drop-in to tokenize a card."""
    if gateway is None:
        return _err("payments_unconfigured")
    return gateway.generate_client_token()


async def pay_invoice(
    session: AsyncSession,
    actor: ActorContext,
    gateway: PaymentGateway | None,
    *,
    invoice_id: uuid.UUID,
    payment_method_nonce: str,
    client_id: uuid.UUID | None = None,
) -> Payment | ItineraryError:
    """Charge an issued invoice and record the payment.

    On a settled sale the invoice flips to ``paid`` and the ``succeeded`` payment
    is returned. On a decline the ``failed`` payment is still recorded (audit)
    and a ``payment_declined`` error is returned. ``payments_unconfigured`` when
    no gateway is wired (production without keys).
    """
    if gateway is None:
        return _err("payments_unconfigured")

    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if invoice.status is not InvoiceStatus.issued:
        return _err("invoice_not_issued")

    total = await _invoice_total(session, invoice_id)
    if total <= _ZERO:
        return _err("nothing_to_pay")

    reference = new_gateway_reference(invoice_id)
    metadata = {
        "invoice_id": str(invoice_id),
        "itinerary_id": str(invoice.itinerary_id),
    }
    if client_id is not None:
        metadata["client_id"] = str(client_id)

    sale = gateway.sale(
        amount=total,
        currency=invoice.currency,
        payment_method_nonce=payment_method_nonce,
        reference=reference,
        metadata=metadata,
    )

    payment = Payment(
        invoice_id=invoice_id,
        amount=total,
        currency=invoice.currency,
        status=PaymentStatus.succeeded if sale.ok else PaymentStatus.failed,
        gateway=gateway.name,
        gateway_reference=reference,
        processor_transaction_id=sale.processor_transaction_id,
        instrument_type=sale.instrument_type,
        last_four=sale.last_four,
        processor_response=sale.processor_response,
        raw=sale.raw,
    )
    session.add(payment)

    if sale.ok:
        marked = await mark_invoice_paid(session, invoice_id=invoice_id)
        if isinstance(marked, ItineraryError):  # pragma: no cover — status re-checked above
            await session.rollback()
            return marked

    await session.flush()
    await session.commit()

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

    if not sale.ok:
        return _err("payment_declined")
    return payment
