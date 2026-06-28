"""Invoice HTTP surface (M005 / I1 + I2).

Advisors assemble invoices from an itinerary's approved bookable nodes; the
ledger lines are signed (charges/discounts/adjustments/taxes/fees/reversals) and
the total is always Σ(lines). Reads admit the advisor, the owning client, or the
creator (the traveler must read their own invoice to pay it in I2); every write
is advisor-only.

The actor + ownership helpers and the outcome→HTTP mapping are shared with the
itinerary router (one source of truth for authz); the service never raises.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Payment,
    PaymentStatus,
)
from app.payments.base import PaymentGateway
from app.routers.itineraries import (
    _actor_from_user,
    _advisor_actor_from_user,
    _is_requester_advisor,
    _load_itinerary,
    _resolve_client_auth_user_id,
)
from app.services import invoices as invoices_svc
from app.services import payments as payments_svc
from app.services.invoices import InvoiceView
from app.services.itineraries import ItineraryError, ItineraryOutcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def get_payment_gateway(request: Request) -> PaymentGateway | None:
    """Return the process-wide PaymentGateway stashed on app.state by the lifespan.

    Mirrors ``get_agent_runtime`` / ``get_vault_storage``; tests override this to
    inject a ``FakeGateway`` (or a spy). May be ``None`` in production without
    Braintree keys — the service maps that to ``payments_unconfigured``.
    """
    return getattr(request.app.state, "payment_gateway", None)


logger = logging.getLogger("ov_black.routers.invoices")

router = APIRouter(tags=["invoices"])


# ── Request / response models ──────────────────────────────────────────────


class CreateInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=256)
    currency: str = Field(min_length=3, max_length=3)
    due_at: datetime | None = None


class AddLineItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InvoiceLineKind = InvoiceLineKind.charge
    description: str = Field(default="", max_length=512)
    # When ``amount`` is omitted, ``node_id`` is required and the line is a
    # charge derived from the node's B4 cost. When ``amount`` is given it is a
    # manual signed line (a discount/adjustment is negative) and ``currency`` is
    # required.
    amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    node_id: uuid.UUID | None = None


class InvoiceLineItemResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    node_id: uuid.UUID | None = None
    kind: InvoiceLineKind
    description: str
    amount: Decimal
    currency: str
    reverses_line_item_id: uuid.UUID | None = None
    created_at: datetime


class PaymentResponse(BaseModel):
    id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    currency: str
    gateway: str
    gateway_reference: str
    processor_transaction_id: str | None = None
    instrument_type: str | None = None
    last_four: str | None = None
    created_at: datetime


class PayInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_method_nonce: str = Field(min_length=1, max_length=4096)


class PaymentTokenResponse(BaseModel):
    client_token: str


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    due_at: datetime | None = None
    total: Decimal
    created_at: datetime
    lines: list[InvoiceLineItemResponse] = Field(default_factory=list)
    payments: list[PaymentResponse] = Field(default_factory=list)


# ── Builders + helpers ─────────────────────────────────────────────────────


def _line_response(line: InvoiceLineItem) -> InvoiceLineItemResponse:
    return InvoiceLineItemResponse(
        id=line.id,
        invoice_id=line.invoice_id,
        node_id=line.node_id,
        kind=line.kind,
        description=line.description,
        amount=line.amount,
        currency=line.currency,
        reverses_line_item_id=line.reverses_line_item_id,
        created_at=line.created_at,
    )


def _payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        gateway=payment.gateway,
        gateway_reference=payment.gateway_reference,
        processor_transaction_id=payment.processor_transaction_id,
        instrument_type=payment.instrument_type,
        last_four=payment.last_four,
        created_at=payment.created_at,
    )


def _invoice_response(view: InvoiceView) -> InvoiceResponse:
    inv = view.invoice
    return InvoiceResponse(
        id=inv.id,
        itinerary_id=inv.itinerary_id,
        label=inv.label,
        status=inv.status,
        currency=inv.currency,
        due_at=inv.due_at,
        total=view.total,
        created_at=inv.created_at,
        lines=[_line_response(line) for line in view.lines],
        payments=[_payment_response(p) for p in view.payments],
    )


def _raise_for_error(err: ItineraryError) -> NoReturn:
    """Map an invoice ItineraryError to the conventional HTTPException."""
    if err.outcome is ItineraryOutcome.NOT_FOUND:
        raise HTTPException(status_code=404, detail="not_found")
    if err.outcome is ItineraryOutcome.VALIDATION_ERROR:
        raise HTTPException(status_code=400, detail=err.detail or "validation_error")
    if err.outcome is ItineraryOutcome.FORBIDDEN:
        raise HTTPException(status_code=403, detail=err.detail or "forbidden")
    logger.error("invoice.router.unhandled_outcome", extra={"outcome": err.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")


async def _assert_itinerary_access(
    session: AsyncSession, user: AuthenticatedUser, itinerary_id: uuid.UUID
) -> None:
    """Admit the advisor, owning client, or creator regardless of itinerary
    status (financial data — stricter than the approved-itinerary read gate).
    404 when the itinerary doesn't exist; 403 otherwise."""
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    actor = _actor_from_user(user)
    is_owner = False
    if actor.user_id is not None and itinerary.client_id is not None:
        owning = await _resolve_client_auth_user_id(session, itinerary.client_id)
        is_owner = owning is not None and owning == actor.user_id
    is_creator = (
        actor.user_id is not None
        and itinerary.created_by is not None
        and actor.user_id == itinerary.created_by
    )
    if is_owner or is_creator or await _is_requester_advisor(session, actor.user_id):
        return
    logger.info(
        "invoice.access_denied",
        extra={"sub_hint": (user.sub or "")[:8], "itinerary_id": str(itinerary_id)},
    )
    raise HTTPException(status_code=403, detail="forbidden")


async def _load_invoice_or_404(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    view_or_err = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view_or_err, ItineraryError):
        _raise_for_error(view_or_err)
    return view_or_err.invoice


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post(
    "/itinerary/{itinerary_id}/invoices",
    status_code=status.HTTP_201_CREATED,
    response_model=InvoiceResponse,
    summary="Create a draft invoice over an itinerary.",
)
async def create_invoice_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateInvoiceRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    actor = _advisor_actor_from_user(user)
    result = await invoices_svc.create_invoice(
        session,
        actor,
        itinerary_id=itinerary_id,
        label=payload.label,
        currency=payload.currency,
        due_at=payload.due_at,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, result.id)
    assert not isinstance(view, ItineraryError)
    return _invoice_response(view)


@router.get(
    "/itinerary/{itinerary_id}/invoices",
    response_model=list[InvoiceResponse],
    summary="List an itinerary's invoices.",
)
async def list_invoices_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[InvoiceResponse]:
    await _assert_itinerary_access(session, user, itinerary_id)
    views = await invoices_svc.list_invoices(session, itinerary_id)
    return [_invoice_response(v) for v in views]


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get an invoice with its ledger and total.",
)
async def get_invoice_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    await _assert_itinerary_access(session, user, view.invoice.itinerary_id)
    return _invoice_response(view)


@router.post(
    "/invoices/{invoice_id}/line-items",
    response_model=InvoiceLineItemResponse,
    summary="Append a line (manual signed line, or charge from a node's cost).",
)
async def add_line_item_endpoint(
    invoice_id: uuid.UUID,
    payload: AddLineItemRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceLineItemResponse:
    actor = _advisor_actor_from_user(user)
    if payload.amount is None:
        if payload.node_id is None:
            raise HTTPException(status_code=400, detail="amount_or_node_required")
        result = await invoices_svc.add_line_item_from_node(
            session, actor, invoice_id=invoice_id, node_id=payload.node_id
        )
    else:
        if payload.currency is None:
            raise HTTPException(status_code=400, detail="currency_required")
        result = await invoices_svc.add_line_item(
            session,
            actor,
            invoice_id=invoice_id,
            description=payload.description,
            amount=payload.amount,
            currency=payload.currency,
            kind=payload.kind,
            node_id=payload.node_id,
        )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _line_response(result)


@router.post(
    "/invoices/{invoice_id}/line-items/{line_id}/void",
    response_model=InvoiceLineItemResponse,
    summary="Void a line by appending a reversal entry.",
)
async def void_line_item_endpoint(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceLineItemResponse:
    actor = _advisor_actor_from_user(user)
    result = await invoices_svc.void_line_item(
        session, actor, invoice_id=invoice_id, line_item_id=line_id
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _line_response(result)


@router.delete(
    "/invoices/{invoice_id}/line-items/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a line (draft-only).",
)
async def delete_line_item_endpoint(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    actor = _advisor_actor_from_user(user)
    result = await invoices_svc.remove_line_item(
        session, actor, invoice_id=invoice_id, line_item_id=line_id
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invoices/{invoice_id}/issue",
    response_model=InvoiceResponse,
    summary="Issue a draft invoice (makes it payable).",
)
async def issue_invoice_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    actor = _advisor_actor_from_user(user)
    result = await invoices_svc.issue_invoice(session, actor, invoice_id=invoice_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, invoice_id)
    assert not isinstance(view, ItineraryError)
    return _invoice_response(view)


@router.post(
    "/invoices/{invoice_id}/void",
    response_model=InvoiceResponse,
    summary="Void (cancel) an invoice.",
)
async def void_invoice_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    actor = _advisor_actor_from_user(user)
    result = await invoices_svc.void_invoice(session, actor, invoice_id=invoice_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, invoice_id)
    assert not isinstance(view, ItineraryError)
    return _invoice_response(view)


# ── Payments (M005/I2) ──────────────────────────────────────────────────────


@router.post(
    "/invoices/{invoice_id}/payment-token",
    response_model=PaymentTokenResponse,
    summary="Mint a gateway client token for the browser drop-in.",
)
async def payment_token_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway | None = Depends(get_payment_gateway),
) -> PaymentTokenResponse:
    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    await _assert_itinerary_access(session, user, view.invoice.itinerary_id)
    token = await payments_svc.generate_client_token(gateway)
    if isinstance(token, ItineraryError):
        _raise_for_error(token)
    return PaymentTokenResponse(client_token=token)


@router.post(
    "/invoices/{invoice_id}/pay",
    response_model=InvoiceResponse,
    summary="Pay an issued invoice (owning client or advisor).",
)
async def pay_invoice_endpoint(
    invoice_id: uuid.UUID,
    payload: PayInvoiceRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway | None = Depends(get_payment_gateway),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    await _assert_itinerary_access(session, user, view.invoice.itinerary_id)
    itinerary = await _load_itinerary(session, view.invoice.itinerary_id)
    client_id = itinerary.client_id if itinerary is not None else None
    actor = _actor_from_user(user)
    result = await payments_svc.pay_invoice(
        session,
        actor,
        gateway,
        invoice_id=invoice_id,
        payment_method_nonce=payload.payment_method_nonce,
        client_id=client_id,
        idempotency_key=idempotency_key,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    paid = await invoices_svc.get_invoice(session, invoice_id)
    assert not isinstance(paid, ItineraryError)
    return _invoice_response(paid)
