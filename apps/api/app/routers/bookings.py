"""Booking HTTP surface (M005 / I3 — the money gate + booking workflow).

Advisors re-price a node's held offer, book an approved node against a covering
paid invoice line (the money gate; an explicit override books on a merely issued
line), and record a supplier confirmation # to advance it to ``confirmed``. A
reconciliation read surfaces Σ(paid lines) ⇔ Σ(booked node costs).

Writes are advisor-only; the reconciliation + offer reads admit the advisor,
owning client, or creator (same gate as the invoice reads). The actor +
ownership helpers and the outcome→HTTP mapping are shared with the itinerary /
invoice routers; the service never raises.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.config import Settings, get_settings
from app.db import get_session
from app.inventory.registry import InventoryProviderRegistry
from app.inventory.supplier_booking import (
    PricingCategoryBooking,
    SupplierAvailability,
    SupplierSelection,
)
from app.models import Booking, InvoiceStatus, NodeOffer, NodeStatus, RefundStatus
from app.payments.base import PaymentGateway
from app.routers.inventory import get_inventory_registry
from app.routers.invoices import _assert_itinerary_access, get_payment_gateway
from app.routers.itineraries import _advisor_actor_from_user
from app.services import bookings as bookings_svc
from app.services.bookings import BookingView, ReconciliationReport
from app.services.itineraries import ItineraryError, ItineraryOutcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("ov_black.routers.bookings")

router = APIRouter(tags=["bookings"])


# ── Request / response models ──────────────────────────────────────────────


class PricingCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A supplier pricing-category id (e.g. adult / child) + how many to book.
    category_id: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=1, le=64)


class SupplierSelectionRequest(BaseModel):
    """The specific supplier slot to book, from a ``supplier-availability`` result.

    The activity itself is the node's own ``source_id`` (bound server-side), so it
    isn't repeated here — this is only the date / start-time / rate / participants.
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    rate_id: str | None = Field(default=None, max_length=64)
    start_time_id: str | None = Field(default=None, max_length=64)
    pricing_categories: list[PricingCategoryRequest] = Field(default_factory=list)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    def to_selection(self) -> SupplierSelection:
        # ``source_id`` is authoritative on the node; book_node rebinds it, so ""
        # here is a placeholder that never reaches the supplier.
        return SupplierSelection(
            source_id="",
            date=self.date,
            rate_id=self.rate_id,
            start_time_id=self.start_time_id,
            pricing_categories=tuple(
                PricingCategoryBooking(category_id=pc.category_id, count=pc.count)
                for pc in self.pricing_categories
            ),
            currency=self.currency,
        )


class BookNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # D-PAY override: book against a merely *issued* (not *paid*) invoice line.
    override_unpaid: bool = False
    # The supplier slot to reserve+confirm — required only for a real supplier
    # booking (a Bokun node with bokun_booking_enabled); ignored otherwise.
    supplier_selection: SupplierSelectionRequest | None = None


class RecordConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_ref: str = Field(min_length=1, max_length=256)
    change_cancel_terms: str | None = Field(default=None, max_length=2048)


class CancelBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2048)


class OfferResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    source: str
    source_offer_id: str | None = None
    amount: Decimal
    currency: str
    priced_at: datetime
    expires_at: datetime | None = None
    refreshed_from_offer_id: uuid.UUID | None = None
    created_at: datetime


class BookingResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    node_status: NodeStatus
    amount: Decimal
    currency: str
    offer_id: uuid.UUID | None = None
    invoice_line_item_id: uuid.UUID | None = None
    supplier_ref: str | None = None
    change_cancel_terms: str | None = None
    override_unpaid: bool
    booked_at: datetime
    confirmed_at: datetime | None = None
    # Real supplier booking (0034) — null for a manual / no-supplier booking.
    supplier_source: str | None = None
    supplier_booking_id: str | None = None
    # Surfaced flight re-price: booked amount − the node's B4 cost (D024).
    reprice_delta: Decimal | None = None
    # Cancel + refund (0028) — null until the booking is cancelled.
    cancelled_at: datetime | None = None
    refund_status: RefundStatus | None = None
    refund_amount: Decimal | None = None


class NodeChargesResponse(BaseModel):
    """The per-node money facet (M006/PS4) — this item's charge, invoice status,
    paid/owed split, and its live booking. Read-only; the pay action deep-links
    to ``invoice_id`` and the booking flow lives on the ``/book`` endpoints."""

    node_id: uuid.UUID
    node_status: NodeStatus
    currency: str | None = None
    # The most recent charge line + its invoice (the pay/deep-link target); null
    # when nothing has been billed against this node yet.
    line_item_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    invoice_status: InvoiceStatus | None = None
    billed_amount: Decimal
    paid_amount: Decimal
    owed_amount: Decimal
    booking: BookingResponse | None = None


class SupplierCategoryPriceResponse(BaseModel):
    category_id: str
    amount: Decimal
    currency: str


class SupplierAvailabilityResponse(BaseModel):
    availability_id: str
    date: date
    start_time: str | None = None
    start_time_id: str | None = None
    seats_available: int | None = None
    rate_id: str | None = None
    prices: list[SupplierCategoryPriceResponse] = Field(default_factory=list)


class ReconciliationRowResponse(BaseModel):
    currency: str
    paid_total: Decimal
    booked_total: Decimal
    balanced: bool


class ReconciliationViolationResponse(BaseModel):
    node_id: uuid.UUID
    code: str
    currency: str
    booked_amount: Decimal
    paid_amount: Decimal


class ReconciliationResponse(BaseModel):
    balanced: bool
    rows: list[ReconciliationRowResponse] = Field(default_factory=list)
    violations: list[ReconciliationViolationResponse] = Field(default_factory=list)


# ── Builders + error mapping ───────────────────────────────────────────────


def _offer_response(offer: NodeOffer) -> OfferResponse:
    return OfferResponse(
        id=offer.id,
        node_id=offer.node_id,
        source=offer.source,
        source_offer_id=offer.source_offer_id,
        amount=offer.amount,
        currency=offer.currency,
        priced_at=offer.priced_at,
        expires_at=offer.expires_at,
        refreshed_from_offer_id=offer.refreshed_from_offer_id,
        created_at=offer.created_at,
    )


def _booking_response(view: BookingView) -> BookingResponse:
    b = view.booking
    return BookingResponse(
        id=b.id,
        node_id=b.node_id,
        node_status=view.node_status,
        amount=b.amount,
        currency=b.currency,
        offer_id=b.offer_id,
        invoice_line_item_id=b.invoice_line_item_id,
        supplier_ref=b.supplier_ref,
        change_cancel_terms=b.change_cancel_terms,
        override_unpaid=b.override_unpaid,
        booked_at=b.booked_at,
        confirmed_at=b.confirmed_at,
        supplier_source=b.supplier_source,
        supplier_booking_id=b.supplier_booking_id,
        reprice_delta=view.reprice_delta,
        cancelled_at=b.cancelled_at,
        refund_status=b.refund_status,
        refund_amount=b.refund_amount,
    )


def _booking_response_bare(b: Booking, node_status: NodeStatus) -> BookingResponse:
    """A BookingResponse from a raw Booking (no offer/reprice context) — for the
    money facet read, which doesn't recompute the flight re-price delta."""
    return BookingResponse(
        id=b.id,
        node_id=b.node_id,
        node_status=node_status,
        amount=b.amount,
        currency=b.currency,
        offer_id=b.offer_id,
        invoice_line_item_id=b.invoice_line_item_id,
        supplier_ref=b.supplier_ref,
        change_cancel_terms=b.change_cancel_terms,
        override_unpaid=b.override_unpaid,
        booked_at=b.booked_at,
        confirmed_at=b.confirmed_at,
        supplier_source=b.supplier_source,
        supplier_booking_id=b.supplier_booking_id,
        reprice_delta=None,
        cancelled_at=b.cancelled_at,
        refund_status=b.refund_status,
        refund_amount=b.refund_amount,
    )


def _supplier_availability_response(
    slots: list[SupplierAvailability],
) -> list[SupplierAvailabilityResponse]:
    return [
        SupplierAvailabilityResponse(
            availability_id=s.availability_id,
            date=s.date,
            start_time=s.start_time,
            start_time_id=s.start_time_id,
            seats_available=s.seats_available,
            rate_id=s.rate_id,
            prices=[
                SupplierCategoryPriceResponse(
                    category_id=p.category_id, amount=p.amount, currency=p.currency
                )
                for p in s.prices
            ],
        )
        for s in slots
    ]


def _reconciliation_response(report: ReconciliationReport) -> ReconciliationResponse:
    return ReconciliationResponse(
        balanced=report.balanced,
        rows=[
            ReconciliationRowResponse(
                currency=r.currency,
                paid_total=r.paid_total,
                booked_total=r.booked_total,
                balanced=r.balanced,
            )
            for r in report.rows
        ],
        violations=[
            ReconciliationViolationResponse(
                node_id=v.node_id,
                code=v.code,
                currency=v.currency,
                booked_amount=v.booked_amount,
                paid_amount=v.paid_amount,
            )
            for v in report.violations
        ],
    )


def _raise_for_error(err: ItineraryError) -> NoReturn:
    """Map a booking ItineraryError to the conventional HTTPException."""
    if err.outcome is ItineraryOutcome.NOT_FOUND:
        raise HTTPException(status_code=404, detail="not_found")
    if err.outcome is ItineraryOutcome.CONFLICT:
        # Money-gate / lifecycle precondition (node_not_paid, offer_expired, …).
        raise HTTPException(status_code=409, detail=err.detail or "conflict")
    if err.outcome is ItineraryOutcome.VALIDATION_ERROR:
        raise HTTPException(status_code=400, detail=err.detail or "validation_error")
    if err.outcome is ItineraryOutcome.FORBIDDEN:
        raise HTTPException(status_code=403, detail=err.detail or "forbidden")
    logger.error("booking.router.unhandled_outcome", extra={"outcome": err.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post(
    "/itinerary/{itinerary_id}/nodes/{node_id}/offers/refresh",
    response_model=OfferResponse,
    summary="Re-price a node's held offer (live provider or snapshot).",
)
async def refresh_offer_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> OfferResponse:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.refresh_offer(
        session, actor, itinerary_id=itinerary_id, node_id=node_id, registry=registry
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _offer_response(result)


@router.get(
    "/itinerary/{itinerary_id}/nodes/{node_id}/offers",
    response_model=list[OfferResponse],
    summary="List a node's offer history (newest first).",
)
async def list_offers_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[OfferResponse]:
    await _assert_itinerary_access(session, user, itinerary_id)
    offers = await bookings_svc.list_offers(session, node_id)
    return [_offer_response(o) for o in offers]


@router.get(
    "/itinerary/{itinerary_id}/nodes/{node_id}/charges",
    response_model=NodeChargesResponse,
    summary="This node's money facet: charge line, invoice status, paid/owed, and booking.",
)
async def node_charges_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeChargesResponse:
    # Same read gate as offers/reconciliation: advisor, owning client, or creator.
    await _assert_itinerary_access(session, user, itinerary_id)
    result = await bookings_svc.node_charges(session, itinerary_id, node_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return NodeChargesResponse(
        node_id=result.node_id,
        node_status=result.node_status,
        currency=result.currency,
        line_item_id=result.line_item_id,
        invoice_id=result.invoice_id,
        invoice_status=result.invoice_status,
        billed_amount=result.billed_amount,
        paid_amount=result.paid_amount,
        owed_amount=result.owed_amount,
        booking=(
            _booking_response_bare(result.booking, result.node_status)
            if result.booking is not None
            else None
        ),
    )


@router.get(
    "/itinerary/{itinerary_id}/nodes/{node_id}/supplier-availability",
    response_model=list[SupplierAvailabilityResponse],
    summary="List real supplier availability for a bookable node (Bokun).",
)
async def supplier_availability_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    start: date = Query(..., description="First date to check (yyyy-mm-dd)."),
    end: date = Query(..., description="Last date to check (yyyy-mm-dd)."),
    currency: str = Query("USD", min_length=3, max_length=3),
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
    settings: Settings = Depends(get_settings),
) -> list[SupplierAvailabilityResponse]:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.list_supplier_availability(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        start=start,
        end=end,
        currency=currency,
        registry=registry,
        settings=settings,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _supplier_availability_response(result)


@router.post(
    "/itinerary/{itinerary_id}/nodes/{node_id}/book",
    response_model=BookingResponse,
    summary="Book an approved node (money gate: requires a covering paid line).",
)
async def book_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: BookNodeRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
    settings: Settings = Depends(get_settings),
) -> BookingResponse:
    actor = _advisor_actor_from_user(user)
    selection = (
        payload.supplier_selection.to_selection()
        if payload.supplier_selection is not None
        else None
    )
    result = await bookings_svc.book_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        override_unpaid=payload.override_unpaid,
        supplier_selection=selection,
        registry=registry,
        settings=settings,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _booking_response(result)


@router.post(
    "/itinerary/{itinerary_id}/nodes/{node_id}/confirm",
    response_model=BookingResponse,
    summary="Record a supplier confirmation # (booked → confirmed).",
)
async def confirm_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: RecordConfirmationRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> BookingResponse:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.record_confirmation(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        supplier_ref=payload.supplier_ref,
        change_cancel_terms=payload.change_cancel_terms,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _booking_response(result)


@router.post(
    "/itinerary/{itinerary_id}/nodes/{node_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel a booked/confirmed node + refund its covering payment (advisor).",
)
async def cancel_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: CancelBookingRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway | None = Depends(get_payment_gateway),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> BookingResponse:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.cancel_booking(
        session,
        actor,
        gateway,
        itinerary_id=itinerary_id,
        node_id=node_id,
        reason=payload.reason,
        registry=registry,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _booking_response(result)


@router.get(
    "/itinerary/{itinerary_id}/reconciliation",
    response_model=ReconciliationResponse,
    summary="Reconcile Σ(paid invoice lines) ⇔ Σ(booked node costs).",
)
async def reconciliation_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ReconciliationResponse:
    await _assert_itinerary_access(session, user, itinerary_id)
    report = await bookings_svc.reconcile_itinerary(session, itinerary_id)
    return _reconciliation_response(report)
