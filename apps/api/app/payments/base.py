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


class PaymentGatewayError(Exception):
    """A gateway call failed *before a charge outcome was determined* — a network
    error, timeout, or misconfiguration. Distinct from a **decline**, which is a
    settled outcome carried as ``SaleResult(ok=False)``.

    ``retryable`` marks errors where the request provably never reached the
    processor (e.g. a connect timeout) so it is safe to retry; a read timeout on
    a ``sale`` is NOT retryable (the charge may have landed) — safe retries of a
    charge go through the idempotency key instead.
    """

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


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


@dataclass(frozen=True, slots=True)
class BillingInfo:
    """Optional customer + billing identity forwarded to the processor on a sale.

    Sourced from the owning client's record (``full_name`` split on the last
    space; the free-text ``address`` maps to ``street_address``) and possibly
    edited by the traveler on the pay form. Every field is optional — a gateway
    forwards only the parts that are present. Not PII-logged (never goes to a log
    record; only into the processor request + the polymorphic ``raw`` column).
    """

    first_name: str | None = None
    last_name: str | None = None
    street_address: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code_alpha2: str | None = None


@dataclass(frozen=True, slots=True)
class RefundResult:
    """Normalized outcome of returning a settled charge, vendor-independent.

    ``kind`` records how the funds were returned: ``"refund"`` for a settled
    transaction (money already moved) or ``"void"`` for an unsettled one (the
    authorization is cancelled before settlement). ``processor_transaction_id`` is
    the gateway's id for the refund/void transaction. ``raw`` is the full processor
    response (never logged); ``processor_response`` is the decline/response code.
    """

    ok: bool
    status: str
    kind: str = "refund"
    processor_transaction_id: str | None = None
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
        billing: BillingInfo | None = None,
    ) -> SaleResult:
        """Charge ``amount`` against the tokenized ``payment_method_nonce``.

        ``reference`` is OUR generated cross-reference id (also written onto the
        processor-side transaction, e.g. Braintree ``order_id``) so a row in the
        processor dashboard maps back to our invoice; ``metadata`` carries the
        invoice/itinerary/client ids for richer cross-referencing where the
        processor supports it. ``billing`` (optional) carries the payer's name +
        address to the processor's customer/billing fields (AVS, receipts).
        """
        ...

    def refund(
        self,
        *,
        processor_transaction_id: str,
        amount: Decimal,
        reference: str,
    ) -> RefundResult:
        """Return a previously charged transaction's funds.

        The gateway decides refund-vs-void from the transaction's own settlement
        state (callers do not): a settled charge is refunded, an unsettled one is
        voided. ``reference`` is OUR cross-ref key for the refund. Raises
        :class:`PaymentGatewayError` when the outcome is unknown (network/timeout);
        a clean processor refusal comes back as ``RefundResult(ok=False)``.
        """
        ...


def new_gateway_reference(invoice_id: uuid.UUID) -> str:
    """A unique-per-attempt cross-reference key that embeds the invoice id.

    Written to ``payments.gateway_reference`` AND sent to the processor as its
    order id, so the two sides share a key. Includes a short random suffix so a
    retried payment on the same invoice gets a distinct reference.
    """
    return f"{invoice_id}:{uuid.uuid4().hex[:8]}"


def new_refund_reference(booking_id: uuid.UUID) -> str:
    """A unique cross-reference key for a refund that embeds the booking id.

    Written to ``bookings.refund_gateway_ref`` and the refund ``Payment`` row's
    ``gateway_reference``; the ``refund:`` prefix distinguishes it from a sale
    reference in the processor dashboard.
    """
    return f"refund:{booking_id}:{uuid.uuid4().hex[:8]}"
