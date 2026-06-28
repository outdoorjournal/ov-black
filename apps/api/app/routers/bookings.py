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
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session
from app.inventory.registry import InventoryProviderRegistry
from app.models import NodeOffer, NodeStatus, RefundStatus
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


class BookNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # D-PAY override: book against a merely *issued* (not *paid*) invoice line.
    override_unpaid: bool = False


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
    # Surfaced flight re-price: booked amount − the node's B4 cost (D024).
    reprice_delta: Decimal | None = None
    # Cancel + refund (0028) — null until the booking is cancelled.
    cancelled_at: datetime | None = None
    refund_status: RefundStatus | None = None
    refund_amount: Decimal | None = None


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
        reprice_delta=view.reprice_delta,
        cancelled_at=b.cancelled_at,
        refund_status=b.refund_status,
        refund_amount=b.refund_amount,
    )


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
) -> BookingResponse:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.book_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        override_unpaid=payload.override_unpaid,
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
) -> BookingResponse:
    actor = _advisor_actor_from_user(user)
    result = await bookings_svc.cancel_booking(
        session,
        actor,
        gateway,
        itinerary_id=itinerary_id,
        node_id=node_id,
        reason=payload.reason,
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
