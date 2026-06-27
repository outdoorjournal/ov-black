"""Payment gateway abstraction (M005/I2, D025/D-PAY).

Gateway-agnostic by design: the service layer talks to a :class:`PaymentGateway`
protocol and persists a normalized :class:`SaleResult` plus the full processor
payload, so swapping Braintree for another processor later is one new
implementation, not a rewrite. See :mod:`app.payments.base`.
"""

from app.payments.base import PaymentGateway, SaleResult, new_gateway_reference
from app.payments.braintree_gateway import BraintreeGateway, FakeGateway, build_gateway

__all__ = [
    "BraintreeGateway",
    "FakeGateway",
    "PaymentGateway",
    "SaleResult",
    "build_gateway",
    "new_gateway_reference",
]
