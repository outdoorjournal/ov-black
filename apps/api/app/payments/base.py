"""Gateway-agnostic payment contract (M005/I2).

The service layer never touches a Braintree (or any vendor) type — it depends on
:class:`PaymentGateway` and receives a normalized :class:`SaleResult`. A
:class:`SaleResult` carries the portable, queryable fields we store in normalized
columns (status, processor txn id, instrument, last four, response code) plus a
``raw`` catch-all holding the entire processor payload, so nothing vendor-specific
is lost and a future ``StripeGateway`` slots in behind the same protocol.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SaleResult:
    """Normalized outcome of a charge, vendor-independent.

    ``raw`` is the full processor response (shape varies per gateway) — the
    polymorphic catch-all so we never drop processor state. ``processor_response``
    is the decline / response code on failure.
    """

    ok: bool
    status: str
    processor_transaction_id: str | None = None
    instrument_type: str | None = None
    last_four: str | None = None
    processor_response: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PaymentGateway(Protocol):
    """A payment processor. Braintree today; Stripe-shaped tomorrow."""

    name: str

    def generate_client_token(self) -> str:
        """A client token the browser drop-in uses to tokenize a card."""
        ...

    def sale(
        self,
        *,
        amount: Decimal,
        currency: str,
        payment_method_nonce: str,
        reference: str,
        metadata: dict[str, str],
    ) -> SaleResult:
        """Charge ``amount`` against the tokenized ``payment_method_nonce``.

        ``reference`` is OUR generated cross-reference id (also written onto the
        processor-side transaction, e.g. Braintree ``order_id``) so a row in the
        processor dashboard maps back to our invoice; ``metadata`` carries the
        invoice/itinerary/client ids for richer cross-referencing where the
        processor supports it.
        """
        ...


def new_gateway_reference(invoice_id: uuid.UUID) -> str:
    """A unique-per-attempt cross-reference key that embeds the invoice id.

    Written to ``payments.gateway_reference`` AND sent to the processor as its
    order id, so the two sides share a key. Includes a short random suffix so a
    retried payment on the same invoice gets a distinct reference.
    """
    return f"{invoice_id}:{uuid.uuid4().hex[:8]}"
