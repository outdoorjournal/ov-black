"""Braintree implementation of the :class:`PaymentGateway` protocol (M005/I2).

Ported from the ``voyage-site`` reference (the Node ``brainTreeGateway`` +
``/token`` + ``transaction.sale`` flow) to the Python SDK. The rich Braintree
transaction is mapped down to a normalized :class:`SaleResult` (with the full
payload in ``raw``) so callers never see a Braintree type.

A :class:`FakeGateway` stands in for local dev / CI / e2e where no sandbox
credentials are present — it mirrors Braintree's test-nonce behavior
(``fake-valid-nonce`` succeeds; a declined nonce fails) so the whole pay flow is
exercisable without AWS/Braintree. :func:`build_gateway` picks the real gateway
when keys are set, the fake when unconfigured in a non-prod environment, and
``None`` in production-without-keys (so a missing secret refuses rather than
silently faking a charge).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import braintree

from app.payments.base import PaymentGateway, SaleResult

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger("ov_black.payments")

# Braintree test nonces — usable only against the sandbox / FakeGateway.
VALID_NONCE = "fake-valid-nonce"
DECLINED_NONCE = "fake-processor-declined-nonce"


class BraintreeGateway:
    """Real Braintree gateway over the Python SDK."""

    name = "braintree"

    def __init__(self, gateway: braintree.BraintreeGateway) -> None:
        self._gateway = gateway

    def generate_client_token(self) -> str:
        token = self._gateway.client_token.generate({})
        return str(token)

    def sale(
        self,
        *,
        amount: Decimal,
        currency: str,
        payment_method_nonce: str,
        reference: str,
        metadata: dict[str, str],
    ) -> SaleResult:
        # ``order_id`` carries our cross-reference key onto the Braintree side so
        # a dashboard row maps back to our invoice. (Custom fields would add
        # invoice/itinerary ids too but must be pre-registered in the control
        # panel; order_id always works — see D025 / mvp-plan §8.)
        result = self._gateway.transaction.sale(
            {
                "amount": str(amount),
                "payment_method_nonce": payment_method_nonce,
                "order_id": reference,
                "options": {"submit_for_settlement": True},
            }
        )
        return _to_sale_result(result, metadata=metadata)

    def __repr__(self) -> str:  # never leak the gateway's keyed config
        return "BraintreeGateway(braintree)"


def _to_sale_result(result: Any, *, metadata: dict[str, str]) -> SaleResult:
    """Map a Braintree ``transaction.sale`` result to a normalized SaleResult."""
    txn = getattr(result, "transaction", None)
    if getattr(result, "is_success", False) and txn is not None:
        return SaleResult(
            ok=True,
            status=str(getattr(txn, "status", "") or ""),
            processor_transaction_id=str(getattr(txn, "id", "") or "") or None,
            instrument_type=getattr(txn, "payment_instrument_type", None),
            last_four=_last_four(txn),
            processor_response=getattr(txn, "processor_response_text", None),
            raw=_txn_raw(txn),
        )
    # Failure — surface the validation / processor message, no charge taken.
    message = str(getattr(result, "message", "") or "declined")
    return SaleResult(
        ok=False,
        status="failed",
        processor_transaction_id=(str(getattr(txn, "id", "")) or None) if txn else None,
        processor_response=message,
        raw={"message": message},
    )


def _last_four(txn: Any) -> str | None:
    details = getattr(txn, "credit_card_details", None)
    last = getattr(details, "last_4", None) if details is not None else None
    return str(last) if last else None


def _txn_raw(txn: Any) -> dict[str, Any]:
    """A JSON-safe slice of the transaction for the polymorphic ``raw`` column."""
    keys = (
        "id",
        "status",
        "type",
        "currency_iso_code",
        "amount",
        "payment_instrument_type",
        "processor_response_code",
        "processor_response_text",
        "merchant_account_id",
    )
    raw: dict[str, Any] = {}
    for key in keys:
        value = getattr(txn, key, None)
        if value is not None:
            raw[key] = str(value)
    return raw


class FakeGateway:
    """Deterministic stand-in for local/CI/e2e (no Braintree credentials)."""

    name = "fake"

    def generate_client_token(self) -> str:
        return "fake-client-token"

    def sale(
        self,
        *,
        amount: Decimal,
        currency: str,
        payment_method_nonce: str,
        reference: str,
        metadata: dict[str, str],
    ) -> SaleResult:
        if "declin" in payment_method_nonce.lower():
            return SaleResult(
                ok=False,
                status="failed",
                processor_response="2000 Do Not Honor (fake)",
                raw={"fake": True, "reference": reference, "nonce": payment_method_nonce},
            )
        return SaleResult(
            ok=True,
            status="submitted_for_settlement",
            processor_transaction_id=f"fake-{reference}",
            instrument_type="credit_card",
            last_four="1111",
            processor_response="1000 Approved (fake)",
            raw={
                "fake": True,
                "reference": reference,
                "amount": str(amount),
                "currency": currency,
                "metadata": metadata,
            },
        )

    def __repr__(self) -> str:
        return "FakeGateway(fake)"


def build_gateway(settings: Settings) -> PaymentGateway | None:
    """Pick a gateway from config (mirrors the agent-runtime/vault wiring).

    - All three Braintree keys set → a real :class:`BraintreeGateway`.
    - Unconfigured **and** not production → a :class:`FakeGateway` (local/CI/e2e).
    - Production with missing keys → ``None`` (the service refuses with
      ``payments_unconfigured`` rather than silently faking a charge).
    """
    if (
        settings.braintree_merchant_id
        and settings.braintree_public_key
        and settings.braintree_private_key
    ):
        environment = (
            braintree.Environment.Production
            if settings.braintree_environment == "production"
            else braintree.Environment.Sandbox
        )
        gateway = braintree.BraintreeGateway(
            braintree.Configuration(
                environment=environment,
                merchant_id=settings.braintree_merchant_id,
                public_key=settings.braintree_public_key,
                private_key=settings.braintree_private_key,
            )
        )
        return BraintreeGateway(gateway)
    if settings.braintree_environment != "production":
        return FakeGateway()
    return None
