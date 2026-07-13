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
from app.payments.base import BillingInfo, PaymentGateway
from app.routers.itineraries import (
    _actor_from_user,
    _advisor_actor_from_user,
    _is_requester_advisor,
    _load_itinerary,
    _resolve_client_auth_user_id,
)
from app.services import billing_summary as billing_summary_svc
from app.services import finance_rules as finance_rules_svc
from app.services import invoices as invoices_svc
from app.services import payments as payments_svc
from app.services.fx import FxService, get_fx_service
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
    # The currency the traveler pays in. Omit to default to the client's
    # preferred_currency (0050); NULL there → pay native.
    settlement_currency: str | None = Field(default=None, min_length=3, max_length=3)


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
    # Required for a settlement (multi-currency / pay-currency) invoice: the locked
    # FX quote to charge against (0050). Omitted for a native-currency invoice.
    quote_id: uuid.UUID | None = None
    # Payer name + billing address (I2 pay form). Pre-filled from the client record
    # and possibly edited by the traveler; forwarded to the gateway's billing block.
    # Optional — an unconfigured billing form simply charges without it.
    billing_name: str | None = Field(default=None, max_length=200)
    billing_address: str | None = Field(default=None, max_length=2000)
    billing_city: str | None = Field(default=None, max_length=200)
    billing_region: str | None = Field(default=None, max_length=200)
    billing_postal_code: str | None = Field(default=None, max_length=32)
    billing_country: str | None = Field(default=None, max_length=2)


class PaymentTokenResponse(BaseModel):
    client_token: str


class InvoicePayContextResponse(BaseModel):
    """Traveler + trip context for the pay page (I2): the trip title to narrate
    *why* this is owed, plus the owning client's billing identity to pre-fill the
    payment form. Reachable by the same viewers as the invoice itself."""

    itinerary_title: str
    full_name: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    preferred_currency: str | None = None


class PaymentQuoteResponse(BaseModel):
    """A short-lived pay-time FX lock (0050) the browser charges against."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    settlement_currency: str
    settlement_amount: Decimal
    rates: dict[str, str]
    expires_at: datetime


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    # Human-facing monotonic number (0050); None only for a not-yet-flushed row.
    number: int | None = None
    itinerary_id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    # The currency the traveler pays in (0050); None → pay native.
    settlement_currency: str | None = None
    due_at: datetime | None = None
    issued_at: datetime | None = None
    first_viewed_at: datetime | None = None
    # Σ of ALL lines regardless of currency — only meaningful single-currency.
    # Multi-currency consumers read ``subtotals``.
    total: Decimal
    # currency → Σ signed native line amounts (the authoritative money shape, 0050).
    subtotals: dict[str, Decimal] = Field(default_factory=dict)
    # Read-side DISPLAY conversion of ``subtotals`` into ``settlement_currency``
    # (0050). None when no settlement currency or FX is unavailable.
    settlement_total: Decimal | None = None
    settlement_rates: dict[str, Decimal] | None = None
    rates_as_of: datetime | None = None
    created_at: datetime
    lines: list[InvoiceLineItemResponse] = Field(default_factory=list)
    payments: list[PaymentResponse] = Field(default_factory=list)


class BillingCurrencyRowResponse(BaseModel):
    """One currency's reconciliation glance (AGT-3 / the cockpit's strip)."""

    currency: str
    trip_total: Decimal
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal
    uninvoiced: Decimal
    uninvoiced_count: int


class UnbilledNodeResponse(BaseModel):
    """A chargeable node whose effective cost isn't fully billed yet."""

    node_id: uuid.UUID
    title: str
    currency: str
    effective: Decimal
    charged: Decimal
    remaining: Decimal


class InvoiceBriefResponse(BaseModel):
    """An invoice headline (no ledger) for narration."""

    id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    total: Decimal
    paid: Decimal


class BillingStateResponse(BaseModel):
    """Response of ``GET /itinerary/{id}/billing`` — the itinerary's money truth."""

    rows: list[BillingCurrencyRowResponse]
    unbilled_nodes: list[UnbilledNodeResponse]
    invoices: list[InvoiceBriefResponse]


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


async def _invoice_response(view: InvoiceView, fx: FxService) -> InvoiceResponse:
    inv = view.invoice
    settlement = await invoices_svc.settlement_display(view, fx)
    return InvoiceResponse(
        id=inv.id,
        number=inv.number,
        itinerary_id=inv.itinerary_id,
        label=inv.label,
        status=inv.status,
        currency=inv.currency,
        settlement_currency=inv.settlement_currency,
        due_at=inv.due_at,
        issued_at=inv.issued_at,
        first_viewed_at=inv.first_viewed_at,
        total=view.total,
        subtotals=view.subtotals,
        settlement_total=settlement.total if settlement is not None else None,
        settlement_rates=settlement.rates if settlement is not None else None,
        rates_as_of=settlement.as_of if settlement is not None else None,
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


def _billing_from_request(payload: PayInvoiceRequest) -> BillingInfo | None:
    """Build a :class:`BillingInfo` from the pay form's billing fields.

    ``billing_name`` is split on the LAST space so a multi-word first name stays
    intact ("Mary Jane Watson" → first "Mary Jane", last "Watson"); a single token
    is treated as the first name. Returns ``None`` when nothing billing-shaped was
    sent, so a bare pay call charges exactly as before."""
    first = last = None
    if payload.billing_name and payload.billing_name.strip():
        first, _, last = payload.billing_name.strip().rpartition(" ")
        if not first:  # no space → whole string is the first name
            first, last = last, None
    billing = BillingInfo(
        first_name=first or None,
        last_name=last or None,
        street_address=payload.billing_address or None,
        locality=payload.billing_city or None,
        region=payload.billing_region or None,
        postal_code=payload.billing_postal_code or None,
        country_code_alpha2=(payload.billing_country.upper() if payload.billing_country else None),
    )
    # All-empty → don't bother the gateway with an empty billing block.
    if any(
        (
            billing.first_name,
            billing.last_name,
            billing.street_address,
            billing.locality,
            billing.region,
            billing.postal_code,
            billing.country_code_alpha2,
        )
    ):
        return billing
    return None


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
        settlement_currency=payload.settlement_currency,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, result.id)
    assert not isinstance(view, ItineraryError)
    return await _invoice_response(view, get_fx_service())


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
    fx = get_fx_service()
    return [await _invoice_response(v, fx) for v in views]


@router.post(
    "/itinerary/{itinerary_id}/invoices/deposit",
    status_code=status.HTTP_201_CREATED,
    response_model=InvoiceResponse,
    summary="Draft a deposit invoice (100% of flights, 20% of everything else).",
)
async def create_deposit_invoice_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    actor = _advisor_actor_from_user(user)
    result = await finance_rules_svc.seed_deposit_invoice(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, result.id)
    assert not isinstance(view, ItineraryError)
    return await _invoice_response(view, get_fx_service())


@router.post(
    "/itinerary/{itinerary_id}/invoices/final",
    status_code=status.HTTP_201_CREATED,
    response_model=InvoiceResponse,
    summary="Draft a balance invoice for every chargeable node's remaining balance.",
)
async def create_final_invoice_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> InvoiceResponse:
    actor = _advisor_actor_from_user(user)
    result = await finance_rules_svc.seed_final_invoice(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await invoices_svc.get_invoice(session, result.id)
    assert not isinstance(view, ItineraryError)
    return await _invoice_response(view, get_fx_service())


@router.get(
    "/itinerary/{itinerary_id}/billing",
    response_model=BillingStateResponse,
    summary="Itinerary-wide billing state: trip total vs invoiced/paid + uninvoiced remainder.",
)
async def billing_state_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> BillingStateResponse:
    """The server-side reconciliation glance (AGT-3): the same money truth the
    advisor cockpit derives client-side, readable by the advisor, the owning
    client, or the creator — the agent calls it with the user's own JWT."""
    await _assert_itinerary_access(session, user, itinerary_id)
    state = await billing_summary_svc.billing_state(session, itinerary_id)
    return BillingStateResponse(
        rows=[
            BillingCurrencyRowResponse(
                currency=row.currency,
                trip_total=row.trip_total,
                invoiced=row.invoiced,
                paid=row.paid,
                outstanding=row.outstanding,
                uninvoiced=row.uninvoiced,
                uninvoiced_count=row.uninvoiced_count,
            )
            for row in state.rows
        ],
        unbilled_nodes=[
            UnbilledNodeResponse(
                node_id=n.node_id,
                title=n.title,
                currency=n.currency,
                effective=n.effective,
                charged=n.charged,
                remaining=n.remaining,
            )
            for n in state.unbilled_nodes
        ],
        invoices=[
            InvoiceBriefResponse(
                id=b.invoice_id,
                label=b.label,
                status=b.status,
                currency=b.currency,
                total=b.total,
                paid=b.paid,
            )
            for b in state.invoices
        ],
    )


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
    # Stamp "viewed" when the owning TRAVELER (not an advisor) opens an issued
    # invoice — the advisor's signal that the traveler has seen it (0050).
    actor = _actor_from_user(user)
    if view.invoice.status is InvoiceStatus.issued and not await _is_requester_advisor(
        session, actor.user_id
    ):
        # Same session → same Invoice instance, so ``view.invoice.first_viewed_at``
        # reflects the stamp without a re-read.
        await invoices_svc.mark_invoice_viewed(session, invoice_id=invoice_id)
    return await _invoice_response(view, get_fx_service())


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
    return await _invoice_response(view, get_fx_service())


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
    return await _invoice_response(view, get_fx_service())


# ── Payments (M005/I2) ──────────────────────────────────────────────────────


@router.get(
    "/invoices/{invoice_id}/pay-context",
    response_model=InvoicePayContextResponse,
    summary="Trip title + traveler billing identity for the pay page (prefill).",
)
async def invoice_pay_context_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> InvoicePayContextResponse:
    """Read-side context for the pay surface: the trip title (to narrate *why*
    this is owed) plus the owning client's billing identity (to pre-fill the
    form). Gated exactly like ``GET /invoices/{id}`` — advisor, owning client, or
    creator — because it returns client PII."""
    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    await _assert_itinerary_access(session, user, view.invoice.itinerary_id)
    ctx = await invoices_svc.pay_context(session, view.invoice.itinerary_id)
    if isinstance(ctx, ItineraryError):
        _raise_for_error(ctx)
    return InvoicePayContextResponse(
        itinerary_title=ctx.itinerary_title,
        full_name=ctx.full_name,
        address=ctx.address,
        city=ctx.city,
        region=ctx.region,
        postal_code=ctx.postal_code,
        country_code=ctx.country_code,
        preferred_currency=ctx.preferred_currency,
    )


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
        quote_id=payload.quote_id,
        billing=_billing_from_request(payload),
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    paid = await invoices_svc.get_invoice(session, invoice_id)
    assert not isinstance(paid, ItineraryError)
    return await _invoice_response(paid, get_fx_service())


@router.post(
    "/invoices/{invoice_id}/payment-quote",
    response_model=PaymentQuoteResponse,
    summary="Freeze a short-lived FX lock to pay a settlement invoice.",
)
async def payment_quote_endpoint(
    invoice_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> PaymentQuoteResponse:
    """Lock the native→settlement rate for a few minutes so the traveler pays a
    stable pay-currency amount (0050). The pay call passes the returned ``id``."""
    view = await invoices_svc.get_invoice(session, invoice_id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    await _assert_itinerary_access(session, user, view.invoice.itinerary_id)
    quote = await payments_svc.create_payment_quote(
        session, get_fx_service(), invoice_id=invoice_id
    )
    if isinstance(quote, ItineraryError):
        _raise_for_error(quote)
    return PaymentQuoteResponse(
        id=quote.id,
        invoice_id=quote.invoice_id,
        settlement_currency=quote.settlement_currency,
        settlement_amount=quote.settlement_amount,
        rates={k: str(v) for k, v in quote.rates.items()},
        expires_at=quote.expires_at,
    )
