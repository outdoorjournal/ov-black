"""Value types + capability protocol for suppliers that can *book*, not just list.

The read-only :class:`~app.inventory.registry.InventoryProvider` seam
(``search`` / ``get_detail``) is separate from the ability to *transact*: only
some upstreams (Bokun today) can hold, confirm, and cancel a real reservation.
That capability is an OPTIONAL, ``runtime_checkable`` protocol so the booking
service can gate on it —

    provider = registry.get(node.source)
    if isinstance(provider, SupplierBookingProvider):
        ...

— without every provider having to implement booking (mock/OV/Duffel don't).

Money model (D-BOOK): OV is merchant-of-record — it collects the traveler's
payment (Braintree) BEFORE booking, then reserves + confirms with the supplier
at the net rate. So the flow here is Bokun's ``RESERVE_FOR_EXTERNAL_PAYMENT``
two-step: ``reserve`` holds inventory (~30 min) → the money gate has already
cleared → ``confirm``. ``abort`` releases a reservation whose confirm never
landed; ``cancel`` reverses a *confirmed* booking (idempotent — an already-gone
booking resolves as cancelled, so a retry after a partial cancel is safe).

These dataclasses are provider-agnostic; each adapter maps its own wire shapes to
them. ``raw`` carries the trimmed upstream payload for audit and MUST never hold
anything sensitive (no card data, no secret).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from app.inventory.registry import InventoryCtx


@dataclass(frozen=True, slots=True)
class PricingCategoryBooking:
    """How many of one supplier pricing category (adult / child / …) to book."""

    category_id: str
    count: int


@dataclass(frozen=True, slots=True)
class SupplierSelection:
    """The specific bookable slot chosen for a supplier experience.

    Identifies an availability of ``source_id`` on ``date`` (+ optional intra-day
    ``start_time_id``) at rate ``rate_id``, for a per-category participant
    breakdown. Assembled from a :meth:`SupplierBookingProvider.check_availability`
    result and passed into ``book_node`` so the money gate books an actual, priced
    slot — not merely an activity id.
    """

    source_id: str
    date: date
    rate_id: str | None = None
    start_time_id: str | None = None
    pricing_categories: tuple[PricingCategoryBooking, ...] = ()
    currency: str = "USD"

    def as_dict(self) -> dict[str, Any]:
        """JSONB-friendly snapshot persisted on the booking (audit + idempotency)."""
        return {
            "source_id": self.source_id,
            "date": self.date.isoformat(),
            "rate_id": self.rate_id,
            "start_time_id": self.start_time_id,
            "pricing_categories": [
                {"category_id": pc.category_id, "count": pc.count} for pc in self.pricing_categories
            ],
            "currency": self.currency,
        }


@dataclass(frozen=True, slots=True)
class SupplierCategoryPrice:
    """Per-participant price for one pricing category within an availability."""

    category_id: str
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class SupplierAvailability:
    """One bookable slot returned by ``check_availability``."""

    availability_id: str
    date: date
    start_time: str | None
    start_time_id: str | None
    seats_available: int | None
    rate_id: str | None
    prices: tuple[SupplierCategoryPrice, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupplierReservation:
    """Result of ``reserve`` — inventory is HELD, not yet paid/confirmed."""

    confirmation_code: str
    booking_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupplierBookingRecord:
    """Result of ``confirm`` — the committed supplier booking."""

    confirmation_code: str
    booking_id: str | None = None
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupplierCancellation:
    """Result of ``cancel`` / ``abort`` — idempotent (already-gone ⇒ cancelled)."""

    cancelled: bool
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SupplierBookingError(Exception):
    """A supplier reserve/confirm/abort/cancel call failed.

    ``retryable`` is False for a definitive decline (the supplier rejected the
    request — a 4xx) and True for an ambiguous transport failure (timeout, 5xx)
    where the outcome is unknown. The booking service is fail-closed either way;
    the flag only steers the logged reason.
    """

    def __init__(
        self, reason: str, *, retryable: bool = False, status_code: int | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


@runtime_checkable
class SupplierBookingProvider(Protocol):
    """Optional capability: an ``InventoryProvider`` that can transact bookings.

    A provider opts in simply by implementing these methods; the booking service
    ``isinstance``-checks for the protocol (method presence) at runtime.
    """

    async def check_availability(
        self,
        *,
        source_id: str,
        start: date,
        end: date,
        currency: str,
        ctx: InventoryCtx,
    ) -> list[SupplierAvailability]: ...

    async def reserve(
        self, *, selection: SupplierSelection, ctx: InventoryCtx
    ) -> SupplierReservation: ...

    async def confirm(
        self, *, confirmation_code: str, ctx: InventoryCtx
    ) -> SupplierBookingRecord: ...

    async def abort(self, *, confirmation_code: str, ctx: InventoryCtx) -> SupplierCancellation: ...

    async def cancel(
        self, *, booking_id: str | None, confirmation_code: str, ctx: InventoryCtx
    ) -> SupplierCancellation: ...
