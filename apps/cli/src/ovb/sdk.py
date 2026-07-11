"""Typed async SDK over apps/api — the shared core for the CLI and e2e suite.

Each method maps to one route (see the OpenAPI map), builds a plain-dict body
from explicit params, and parses the response into the machine-generated model
in :mod:`ovb._generated`. Requests are dicts (we know the field names);
*responses* carry the generated types — the same "generated types + hand-written
ergonomic wrapper" split as ``packages/api-client`` (generated SDK + index.ts).

The agent turn loop is intentionally absent here; it lives in :mod:`ovb.agent`
because OpenAPI does not model the SSE stream.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from ovb._generated import models as gm
from ovb.auth import mint_jwt
from ovb.config import Profile
from ovb.errors import ApiError, ConfigError
from ovb.transport import QueryValue, Transport

M = TypeVar("M", bound=BaseModel)

_OK = frozenset({200, 201, 202, 204})


def _detail(resp: httpx.Response) -> tuple[str, Any]:
    """Collapse a FastAPI error body to (reason, raw_body)."""
    try:
        body = resp.json()
    except ValueError:
        return (resp.text[:200] or f"http_{resp.status_code}"), None
    if isinstance(body, dict):
        det = body.get("detail")
        if isinstance(det, str):
            return det, body
        if isinstance(det, list):
            return "validation_error", body
    return f"http_{resp.status_code}", body


class Ovb:
    """A typed client bound to one identity (one bearer JWT)."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    # ── construction ─────────────────────────────────────────────────────
    @classmethod
    def for_identity(
        cls,
        profile: Profile,
        *,
        email: str | None = None,
        role: str | None = None,
        token: str | None = None,
        authed: bool = True,
    ) -> Ovb:
        """Mint (or accept) a JWT for an identity and build a bound client.

        ``authed=False`` builds a token-less client for public routes
        (``/health``, ``/auth/*``).
        """
        if not profile.api_url:
            raise ConfigError(
                f"profile {profile.name!r} has no api_url "
                "(set STAGING_API_URL / OVB_API_URL or configure the profile)"
            )
        bearer = token
        if authed and bearer is None:
            bearer = mint_jwt(profile, email=email, role=role)
        return cls(
            Transport(
                profile.api_url,
                token=bearer if authed else None,
                verify_tls=profile.verify_tls,
            )
        )

    @property
    def transport(self) -> Transport:
        return self._t

    async def aclose(self) -> None:
        await self._t.aclose()

    async def __aenter__(self) -> Ovb:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── low-level helpers ────────────────────────────────────────────────
    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, QueryValue] | None = None,
        authed: bool = True,
    ) -> httpx.Response:
        resp = await self._t.request(
            method, path, json_body=json_body, params=params, authed=authed
        )
        if resp.status_code not in _OK:
            reason, body = _detail(resp)
            raise ApiError(resp.status_code, reason, method=method, path=path, body=body)
        return resp

    async def _model(
        self,
        model: type[M],
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, QueryValue] | None = None,
        authed: bool = True,
    ) -> M:
        resp = await self._send(method, path, json_body=json_body, params=params, authed=authed)
        return model.model_validate(resp.json())

    async def _list(
        self,
        model: type[M],
        method: str,
        path: str,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> list[M]:
        resp = await self._send(method, path, params=params)
        return [model.model_validate(row) for row in resp.json()]

    async def _raw(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, QueryValue] | None = None,
        authed: bool = True,
    ) -> Any:
        resp = await self._send(method, path, json_body=json_body, params=params, authed=authed)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ── auth (public) ────────────────────────────────────────────────────
    async def login(self, *, email: str) -> None:
        await self._send("POST", "/auth/login", json_body={"email": email}, authed=False)

    # ── health ───────────────────────────────────────────────────────────
    async def health(self) -> dict[str, Any]:
        body = await self._raw("GET", "/health", authed=False)
        return body if isinstance(body, dict) else {"status": body}

    async def health_authed(self) -> gm.AuthedHealthResponse:
        return await self._model(gm.AuthedHealthResponse, "GET", "/health/authed")

    # ── itineraries ──────────────────────────────────────────────────────
    async def create_itinerary(
        self,
        *,
        title: str = "",
        client_id: str | None = None,
        timing_kind: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        duration_nights: int | None = None,
    ) -> gm.ItineraryResponse:
        body: dict[str, Any] = {"title": title, "client_id": client_id}
        # Timing (0033/Wave E): seed pinned dates up front — booking gates on
        # timing_kind='exact' (ADV-17), so a bookable seed must pin.
        if timing_kind is not None:
            body["timing_kind"] = timing_kind
        if date_start is not None:
            body["date_start"] = date_start
        if date_end is not None:
            body["date_end"] = date_end
        if duration_nights is not None:
            body["duration_nights"] = duration_nights
        return await self._model(gm.ItineraryResponse, "POST", "/itinerary", json_body=body)

    async def update_itinerary(self, itinerary_id: str, **fields: Any) -> gm.ItineraryResponse:
        """PATCH /itinerary/{id} — partial update (title, brief, timing, …)."""
        return await self._model(
            gm.ItineraryResponse, "PATCH", f"/itinerary/{itinerary_id}", json_body=fields
        )

    async def seed_campaign(self, campaign_id: str, *, client_id: str) -> gm.CampaignSeedResponse:
        """POST /demos/campaign/{id} — seed a campaign shell itinerary (self-serve).

        Stamps the itinerary with the campaign's ``campaign_id``, title, and hero
        ``mood``; no spine (length unknown until intake) and no facts.
        """
        return await self._model(
            gm.CampaignSeedResponse,
            "POST",
            f"/demos/campaign/{campaign_id}",
            json_body={"client_id": client_id},
        )

    async def campaign_kickoff(self, itinerary_id: str) -> gm.CampaignKickoffResponse:
        """POST /itinerary/{id}/campaign/kickoff — snap length + land the spine.

        Reads the trip's chosen nights, snaps to the nearest shipped spine
        length, and instantiates it onto this itinerary. Returns the snap
        ``reason`` + node/edge counts.
        """
        return await self._model(
            gm.CampaignKickoffResponse,
            "POST",
            f"/itinerary/{itinerary_id}/campaign/kickoff",
            json_body={},
        )

    async def add_transfer(
        self,
        itinerary_id: str,
        *,
        origin: str,
        destination: str,
        mode: str = "drive",
        party_size: int = 1,
        service_class: str = "chauffeur_black",
    ) -> gm.NodeResponse:
        """POST /itinerary/{id}/nodes/from-route — a real, tier-aware transfer card."""
        return await self._model(
            gm.NodeResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/from-route",
            json_body={
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "party_size": party_size,
                "service_class": service_class,
            },
        )

    async def save_article(
        self, itinerary_id: str, *, url: str, note: str | None = None
    ) -> gm.NodeResponse:
        """POST /itinerary/{id}/nodes/from-link kind=article — a reading-list card."""
        body: dict[str, Any] = {"url": url, "kind": "article"}
        if note is not None:
            body["note"] = note
        return await self._model(
            gm.NodeResponse, "POST", f"/itinerary/{itinerary_id}/nodes/from-link", json_body=body
        )

    async def retime(
        self, itinerary_id: str, *, date_start: str, date_end: str | None = None
    ) -> gm.RetimeItineraryResponse:
        """Pin the trip to real dates (Wave E / ADV-17): 'Day 1 is date_start'.

        Shifts every scheduled card by ``date_start − days_anchor`` days
        (wall-clock preserved) and flips the trip to ``timing_kind=exact``.
        409 ``booked_dates_locked`` when booked/confirmed cards pin the calendar.
        """
        body: dict[str, Any] = {"date_start": date_start}
        if date_end is not None:
            body["date_end"] = date_end
        return await self._model(
            gm.RetimeItineraryResponse, "POST", f"/itinerary/{itinerary_id}/retime", json_body=body
        )

    async def get_graph(self, itinerary_id: str) -> gm.GraphResponse:
        return await self._model(gm.GraphResponse, "GET", f"/itinerary/{itinerary_id}")

    async def list_advisor_itineraries(self) -> gm.AdvisorItinerariesResponse:
        return await self._model(gm.AdvisorItinerariesResponse, "GET", "/itineraries")

    # ── Wave F advisor ops surface ──────────────────────────────────────────

    async def advisor_overview(self) -> gm.AdvisorOverviewResponse:
        """GET /advisor/overview — the Ops dashboard's portfolio stats."""
        return await self._model(gm.AdvisorOverviewResponse, "GET", "/advisor/overview")

    async def advisor_activity(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> gm.ActivityResponse:
        """GET /advisor/activity — the merged roster event feed, newest-first."""
        params: dict[str, QueryValue] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        resp = await self._send("GET", "/advisor/activity", params=params or None)
        return gm.ActivityResponse.model_validate(resp.json())

    async def advisor_money(
        self, *, status: str | None = None, cursor: str | None = None
    ) -> gm.AdvisorMoneyResponse:
        """GET /advisor/money — the cross-client invoice roster + currency band."""
        params: dict[str, QueryValue] = {}
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        resp = await self._send("GET", "/advisor/money", params=params or None)
        return gm.AdvisorMoneyResponse.model_validate(resp.json())

    async def approve_all(self, itinerary_id: str) -> gm.ApproveAllResponse:
        """Approve every pending approvable node on the official trunk."""
        return await self._model(
            gm.ApproveAllResponse, "POST", f"/itinerary/{itinerary_id}/nodes/approve-all"
        )

    async def lock(self, itinerary_id: str) -> gm.ItineraryResponse:
        return await self._model(gm.ItineraryResponse, "POST", f"/itinerary/{itinerary_id}/lock")

    async def release(self, itinerary_id: str) -> gm.ReleaseLockResponse:
        return await self._model(
            gm.ReleaseLockResponse, "POST", f"/itinerary/{itinerary_id}/release"
        )

    async def assemble(
        self, itinerary_id: str, *, day_plan: list[dict[str, Any]] | None = None
    ) -> gm.GraphResponse:
        body = {"day_plan": day_plan or []}
        return await self._model(
            gm.GraphResponse, "POST", f"/itinerary/{itinerary_id}/assemble", json_body=body
        )

    async def fork_itinerary(
        self, itinerary_id: str, *, title: str | None = None
    ) -> gm.GraphResponse:
        """Fork an itinerary into a versioned clone (G2); returns the fork's graph.

        The response's ``itinerary.forked_from_id`` is the baseline and every node
        carries ``forked_from_node_id`` lineage (+ a ``lock_reason`` on carried
        booked nodes).
        """
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        return await self._model(
            gm.GraphResponse, "POST", f"/itinerary/{itinerary_id}/fork", json_body=body
        )

    # ── fork diff / reconcile (G3) ───────────────────────────────────────
    async def fork_diff(self, fork_id: str) -> gm.ForkDiffResponse:
        """Diff a fork against its baseline (added/removed/changed/moved)."""
        return await self._model(gm.ForkDiffResponse, "GET", f"/itinerary/{fork_id}/diff")

    async def reconcile_fork(
        self,
        fork_id: str,
        *,
        decisions: list[dict[str, Any]] | None = None,
        analysis_id: str | None = None,
        override_block: bool = False,
        accept_all: bool = False,
    ) -> gm.ReconcileResponse:
        """Fold accepted fork changes into the live baseline (advisor only).

        ``decisions`` is a list of ``{"change_id": ..., "accept": bool}``.
        ``accept_all=True`` is the publish fast path — the server accepts every
        change in its own fresh diff and ``decisions`` is ignored.
        """
        body: dict[str, Any] = {
            "decisions": decisions or [],
            "override_block": override_block,
            "accept_all": accept_all,
        }
        if analysis_id is not None:
            body["analysis_id"] = analysis_id
        return await self._model(
            gm.ReconcileResponse, "POST", f"/itinerary/{fork_id}/reconcile", json_body=body
        )

    async def request_reconcile(
        self, fork_id: str, *, note: str | None = None
    ) -> gm.ItineraryResponse:
        """Ask staff to merge this fork (traveler/agent; advisor executes)."""
        body: dict[str, Any] = {}
        if note is not None:
            body["note"] = note
        return await self._model(
            gm.ItineraryResponse,
            "POST",
            f"/itinerary/{fork_id}/request-reconcile",
            json_body=body,
        )

    async def abandon_fork(self, fork_id: str) -> gm.ItineraryResponse:
        """Abandon a fork without merging (advisor or owner)."""
        return await self._model(
            gm.ItineraryResponse, "POST", f"/itinerary/{fork_id}/abandon", json_body={}
        )

    # ── invoices (M005/I1) ───────────────────────────────────────────────
    async def create_invoice(
        self,
        itinerary_id: str,
        *,
        label: str = "",
        currency: str,
        due_at: str | None = None,
    ) -> gm.InvoiceResponse:
        """Create a draft invoice over an itinerary (advisor)."""
        body: dict[str, Any] = {"label": label, "currency": currency}
        if due_at is not None:
            body["due_at"] = due_at
        return await self._model(
            gm.InvoiceResponse, "POST", f"/itinerary/{itinerary_id}/invoices", json_body=body
        )

    async def list_invoices(self, itinerary_id: str) -> list[gm.InvoiceResponse]:
        """List an itinerary's invoices (advisor or owning client)."""
        return await self._list(gm.InvoiceResponse, "GET", f"/itinerary/{itinerary_id}/invoices")

    async def get_invoice(self, invoice_id: str) -> gm.InvoiceResponse:
        """Get an invoice with its ledger + total."""
        return await self._model(gm.InvoiceResponse, "GET", f"/invoices/{invoice_id}")

    async def add_invoice_line(
        self,
        invoice_id: str,
        *,
        kind: str = "charge",
        description: str = "",
        amount: str | None = None,
        currency: str | None = None,
        node_id: str | None = None,
    ) -> gm.InvoiceLineItemResponse:
        """Append a line. Omit ``amount`` + pass ``node_id`` to charge a node's cost."""
        body: dict[str, Any] = {"kind": kind, "description": description}
        if amount is not None:
            body["amount"] = amount
        if currency is not None:
            body["currency"] = currency
        if node_id is not None:
            body["node_id"] = node_id
        return await self._model(
            gm.InvoiceLineItemResponse,
            "POST",
            f"/invoices/{invoice_id}/line-items",
            json_body=body,
        )

    async def void_invoice_line(self, invoice_id: str, line_id: str) -> gm.InvoiceLineItemResponse:
        """Void a line by appending a reversal (advisor)."""
        return await self._model(
            gm.InvoiceLineItemResponse,
            "POST",
            f"/invoices/{invoice_id}/line-items/{line_id}/void",
        )

    async def remove_invoice_line(self, invoice_id: str, line_id: str) -> None:
        """Hard-delete a line (draft-only, advisor)."""
        await self._send("DELETE", f"/invoices/{invoice_id}/line-items/{line_id}")

    async def issue_invoice(self, invoice_id: str) -> gm.InvoiceResponse:
        """Issue a draft invoice (advisor)."""
        return await self._model(gm.InvoiceResponse, "POST", f"/invoices/{invoice_id}/issue")

    async def void_invoice(self, invoice_id: str) -> gm.InvoiceResponse:
        """Void (cancel) an invoice (advisor)."""
        return await self._model(gm.InvoiceResponse, "POST", f"/invoices/{invoice_id}/void")

    async def payment_token(self, invoice_id: str) -> gm.PaymentTokenResponse:
        """Mint a gateway client token for the drop-in (owning client or advisor)."""
        return await self._model(
            gm.PaymentTokenResponse, "POST", f"/invoices/{invoice_id}/payment-token"
        )

    async def pay_invoice(
        self, invoice_id: str, *, payment_method_nonce: str
    ) -> gm.InvoiceResponse:
        """Pay an issued invoice with a tokenized card nonce; returns the paid invoice."""
        return await self._model(
            gm.InvoiceResponse,
            "POST",
            f"/invoices/{invoice_id}/pay",
            json_body={"payment_method_nonce": payment_method_nonce},
        )

    # ── bookings + money gate (M005/I3) ──────────────────────────────────
    async def refresh_offer(self, itinerary_id: str, node_id: str) -> gm.OfferResponse:
        """Re-price a node's held offer (advisor) — live provider or snapshot."""
        return await self._model(
            gm.OfferResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/{node_id}/offers/refresh",
        )

    async def list_offers(self, itinerary_id: str, node_id: str) -> list[gm.OfferResponse]:
        """A node's offer history, newest first (advisor or owning client)."""
        return await self._list(
            gm.OfferResponse, "GET", f"/itinerary/{itinerary_id}/nodes/{node_id}/offers"
        )

    async def book_node(
        self, itinerary_id: str, node_id: str, *, override_unpaid: bool = False
    ) -> gm.BookingResponse:
        """Book an approved node (advisor). The money gate requires a covering paid
        invoice line; ``override_unpaid`` books on a merely issued line (logged)."""
        return await self._model(
            gm.BookingResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/{node_id}/book",
            json_body={"override_unpaid": override_unpaid},
        )

    async def record_confirmation(
        self,
        itinerary_id: str,
        node_id: str,
        *,
        supplier_ref: str,
        change_cancel_terms: str | None = None,
    ) -> gm.BookingResponse:
        """Record a supplier confirmation # → booked becomes confirmed (advisor)."""
        body: dict[str, Any] = {"supplier_ref": supplier_ref}
        if change_cancel_terms is not None:
            body["change_cancel_terms"] = change_cancel_terms
        return await self._model(
            gm.BookingResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/{node_id}/confirm",
            json_body=body,
        )

    async def cancel_booking(
        self,
        itinerary_id: str,
        node_id: str,
        *,
        reason: str | None = None,
    ) -> gm.BookingResponse:
        """Cancel a booked/confirmed node + refund its covering payment (advisor).

        Demotes the node to ``approved``; ``refund_status`` reports refunded /
        voided / not_applicable."""
        body: dict[str, Any] = {}
        if reason is not None:
            body["reason"] = reason
        return await self._model(
            gm.BookingResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/{node_id}/cancel",
            json_body=body,
        )

    async def get_billing_state(self, itinerary_id: str) -> gm.BillingStateResponse:
        """Itinerary-wide money truth (AGT-3): trip total vs invoiced/paid +
        the per-node uninvoiced remainder — the same read the agent's
        ``get_billing_state`` tool makes."""
        return await self._model(
            gm.BillingStateResponse, "GET", f"/itinerary/{itinerary_id}/billing"
        )

    async def get_booking_state(self, itinerary_id: str) -> gm.BookingStateResponse:
        """Every bookable node's booking + payment position (AGT-3)."""
        return await self._model(
            gm.BookingStateResponse, "GET", f"/itinerary/{itinerary_id}/booking-state"
        )

    async def get_reconciliation(self, itinerary_id: str) -> gm.ReconciliationResponse:
        """Reconcile Σ(paid invoice lines) ⇔ Σ(booked node costs) for an itinerary."""
        return await self._model(
            gm.ReconciliationResponse, "GET", f"/itinerary/{itinerary_id}/reconciliation"
        )

    async def list_my_invoices(self) -> gm.MyInvoicesResponse:
        """The calling client's invoices across all itineraries (traveler self-service)."""
        return await self._model(gm.MyInvoicesResponse, "GET", "/me/invoices")

    # ── messaging (human threads) ─────────────────────────────────────────
    async def open_thread(
        self, *, client_id: str, itinerary_id: str | None = None
    ) -> gm.ThreadSummary:
        """Get-or-create the human thread for a scope (M006/PS7)."""
        return await self._model(
            gm.ThreadSummary,
            "POST",
            "/threads",
            json_body={"client_id": client_id, "itinerary_id": itinerary_id},
        )

    async def list_thread_messages(self, thread_id: str) -> list[gm.MessageSummary]:
        """A thread's human messages, oldest first."""
        return await self._list(gm.MessageSummary, "GET", f"/threads/{thread_id}/messages")

    # ── nodes ────────────────────────────────────────────────────────────
    async def add_node(
        self,
        itinerary_id: str,
        *,
        type: str,
        title: str = "",
        status: str = "pending",
        source: str | None = None,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        cost_amount: str | None = None,
        cost_currency: str | None = None,
        cost_kind: str | None = None,
        parent_subgraph_id: str | None = None,
        attached_to_node_id: str | None = None,
        starts_at: str | None = None,
        duration_minutes: int | None = None,
    ) -> gm.NodeResponse:
        body: dict[str, Any] = {
            "type": type,
            "title": title,
            "status": status,
            "source": source,
            "source_id": source_id,
            "metadata": metadata or {},
            "cost_amount": cost_amount,
            "cost_currency": cost_currency,
            "cost_kind": cost_kind,
            "parent_subgraph_id": parent_subgraph_id,
            # Note anchoring (0014): attach to a host node, or a free-standing
            # time anchor. Only meaningful for type="note".
            "attached_to_node_id": attached_to_node_id,
            "starts_at": starts_at,
            "duration_minutes": duration_minutes,
        }
        body = {k: v for k, v in body.items() if v is not None}
        return await self._model(
            gm.NodeResponse, "POST", f"/itinerary/{itinerary_id}/nodes", json_body=body
        )

    async def node_from_inventory(
        self,
        itinerary_id: str,
        *,
        source: str,
        source_id: str,
        status: str = "pending",
        parent_subgraph_id: str | None = None,
    ) -> gm.NodeResponse:
        body: dict[str, Any] = {"source": source, "source_id": source_id, "status": status}
        if parent_subgraph_id:
            body["parent_subgraph_id"] = parent_subgraph_id
        return await self._model(
            gm.NodeResponse,
            "POST",
            f"/itinerary/{itinerary_id}/nodes/from-inventory",
            json_body=body,
        )

    async def update_node(
        self, itinerary_id: str, node_id: str, *, fields: dict[str, Any]
    ) -> gm.NodeResponse:
        return await self._model(
            gm.NodeResponse,
            "PATCH",
            f"/itinerary/{itinerary_id}/nodes/{node_id}",
            json_body=fields,
        )

    async def delete_node(self, itinerary_id: str, node_id: str) -> None:
        await self._send("DELETE", f"/itinerary/{itinerary_id}/nodes/{node_id}")

    # ── edges ────────────────────────────────────────────────────────────
    async def add_edge(
        self,
        itinerary_id: str,
        *,
        from_node_id: str,
        to_node_id: str,
        type: str,
        metadata: dict[str, Any] | None = None,
    ) -> gm.EdgeResponse:
        body = {
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "type": type,
            "metadata": metadata or {},
        }
        return await self._model(
            gm.EdgeResponse, "POST", f"/itinerary/{itinerary_id}/edges", json_body=body
        )

    async def delete_edge(self, itinerary_id: str, edge_id: str) -> None:
        await self._send("DELETE", f"/itinerary/{itinerary_id}/edges/{edge_id}")

    # ── inventory ────────────────────────────────────────────────────────
    async def search_inventory(
        self, *, params: dict[str, QueryValue]
    ) -> gm.SearchInventoryResponse:
        return await self._model(
            gm.SearchInventoryResponse, "GET", "/search-inventory", params=params
        )

    async def inventory_detail(self, source: str, source_id: str) -> Any:
        return await self._raw("GET", f"/inventory/{source}/{source_id}")

    # ── analyze ──────────────────────────────────────────────────────────
    async def start_analysis(
        self,
        itinerary_id: str,
        *,
        depth: str = "standard",
        scope: dict[str, Any] | None = None,
        force_rerun: bool = False,
    ) -> gm.AnalysisCreatedResponse:
        body = {"depth": depth, "scope": scope or {}, "force_rerun": force_rerun}
        return await self._model(
            gm.AnalysisCreatedResponse,
            "POST",
            f"/itinerary/{itinerary_id}/analyses",
            json_body=body,
        )

    async def list_analyses(
        self, itinerary_id: str, *, limit: int | None = None
    ) -> list[gm.AnalysisSummaryResponse]:
        params: dict[str, QueryValue] = {"limit": limit} if limit is not None else {}
        return await self._list(
            gm.AnalysisSummaryResponse,
            "GET",
            f"/itinerary/{itinerary_id}/analyses",
            params=params,
        )

    async def get_analysis(self, itinerary_id: str, analysis_id: str) -> gm.AnalysisDetailResponse:
        return await self._model(
            gm.AnalysisDetailResponse,
            "GET",
            f"/itinerary/{itinerary_id}/analyses/{analysis_id}",
        )

    async def cancel_analysis(
        self, itinerary_id: str, analysis_id: str
    ) -> gm.AnalysisDetailResponse:
        return await self._model(
            gm.AnalysisDetailResponse,
            "POST",
            f"/itinerary/{itinerary_id}/analyses/{analysis_id}/cancel",
        )

    # ── fill ─────────────────────────────────────────────────────────────
    async def fill(
        self,
        itinerary_id: str,
        *,
        gap_start: str,
        gap_end: str,
        party_id: str | None = None,
        analysis_id: str | None = None,
        desired_kinds: list[str] | None = None,
        min_score: float | None = None,
        max_proposals: int | None = None,
    ) -> gm.FillResponse:
        body: dict[str, Any] = {"gap": {"start": gap_start, "end": gap_end}}
        if party_id is not None:
            body["party_id"] = party_id
        if analysis_id is not None:
            body["analysis_id"] = analysis_id
        if desired_kinds is not None:
            body["desired_kinds"] = desired_kinds
        if min_score is not None:
            body["min_score"] = min_score
        if max_proposals is not None:
            body["max_proposals"] = max_proposals
        return await self._model(
            gm.FillResponse, "POST", f"/itinerary/{itinerary_id}/fill", json_body=body
        )

    # ── clients ──────────────────────────────────────────────────────────
    async def list_clients(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> gm.ClientsPage:
        """Wave F: /clients returns a searchable, keyset-paged envelope."""
        params: dict[str, QueryValue] = {}
        if q is not None:
            params["q"] = q
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        resp = await self._send("GET", "/clients", params=params or None)
        return gm.ClientsPage.model_validate(resp.json())

    async def create_client(self, payload: dict[str, Any]) -> gm.ClientCreateResponse:
        return await self._model(gm.ClientCreateResponse, "POST", "/clients", json_body=payload)

    async def get_client(
        self, client_id: str, *, include_redacted: bool = False
    ) -> gm.ClientDetail:
        params: dict[str, QueryValue] = {"include_redacted": 1} if include_redacted else {}
        return await self._model(gm.ClientDetail, "GET", f"/clients/{client_id}", params=params)

    async def list_client_sessions(self, client_id: str) -> gm.ClientSessionsResponse:
        return await self._model(gm.ClientSessionsResponse, "GET", f"/clients/{client_id}/sessions")

    async def resend_welcome(self, client_id: str) -> None:
        """Re-send the welcome sign-in link to a pending client (advisor nudge)."""
        await self._send("POST", f"/clients/{client_id}/resend-welcome")

    async def add_fact(
        self, client_id: str, *, tier: str, kind: str, text: str, source_kind: str | None = None
    ) -> Any:
        """Add a fact to one of dossier/profile/osint (advisor-attributed)."""
        if tier not in ("dossier", "profile", "osint"):
            raise ValueError(f"tier must be dossier|profile|osint, got {tier!r}")
        body: dict[str, Any] = {"kind": kind, "text": text}
        if source_kind:
            body["source_kind"] = source_kind
        return await self._raw("POST", f"/clients/{client_id}/{tier}/facts", json_body=body)

    # ── party members (M003/V1) ──────────────────────────────────────────
    async def list_party_members(
        self, client_id: str, *, include_archived: bool = False
    ) -> gm.PartyMemberListResponse:
        params: dict[str, QueryValue] = {"include_archived": 1} if include_archived else {}
        return await self._model(
            gm.PartyMemberListResponse,
            "GET",
            f"/clients/{client_id}/party-members",
            params=params,
        )

    async def create_party_member(
        self, client_id: str, payload: dict[str, Any]
    ) -> gm.PartyMemberDetail:
        return await self._model(
            gm.PartyMemberDetail, "POST", f"/clients/{client_id}/party-members", json_body=payload
        )

    async def update_party_member(
        self, client_id: str, member_id: str, payload: dict[str, Any]
    ) -> gm.PartyMemberDetail:
        return await self._model(
            gm.PartyMemberDetail,
            "PATCH",
            f"/clients/{client_id}/party-members/{member_id}",
            json_body=payload,
        )

    async def archive_party_member(self, client_id: str, member_id: str) -> gm.PartyMemberDetail:
        return await self._model(
            gm.PartyMemberDetail,
            "DELETE",
            f"/clients/{client_id}/party-members/{member_id}",
        )

    async def my_party_members(
        self, *, include_archived: bool = False
    ) -> gm.PartyMemberListResponse:
        params: dict[str, QueryValue] = {"include_archived": 1} if include_archived else {}
        return await self._model(
            gm.PartyMemberListResponse, "GET", "/me/party-members", params=params
        )

    async def create_my_party_member(self, payload: dict[str, Any]) -> gm.PartyMemberDetail:
        return await self._model(
            gm.PartyMemberDetail, "POST", "/me/party-members", json_body=payload
        )

    async def list_itinerary_party(self, itinerary_id: str) -> gm.ItineraryPartyResponse:
        return await self._model(
            gm.ItineraryPartyResponse, "GET", f"/itineraries/{itinerary_id}/party"
        )

    async def attach_party_member(
        self, itinerary_id: str, party_member_id: str
    ) -> gm.ItineraryPartyResponse:
        return await self._model(
            gm.ItineraryPartyResponse,
            "POST",
            f"/itineraries/{itinerary_id}/party/members",
            json_body={"party_member_id": party_member_id},
        )

    async def detach_party_member(
        self, itinerary_id: str, member_id: str
    ) -> gm.ItineraryPartyResponse:
        return await self._model(
            gm.ItineraryPartyResponse,
            "DELETE",
            f"/itineraries/{itinerary_id}/party/members/{member_id}",
        )

    # ── document vault (M003/V3) ─────────────────────────────────────────
    # Upload is a two-step presigned flow: init (→ presigned PUT) then complete.
    # Against `local` the storage is mocked, so the upload_url points nowhere —
    # the e2e drives the API/DB contract, not a real byte PUT.
    async def list_client_documents(
        self, client_id: str, *, include_archived: bool = False
    ) -> gm.DocumentListResponse:
        params: dict[str, QueryValue] = {"include_archived": 1} if include_archived else {}
        return await self._model(
            gm.DocumentListResponse,
            "GET",
            f"/clients/{client_id}/documents",
            params=params,
        )

    async def init_client_document(
        self, client_id: str, payload: dict[str, Any]
    ) -> gm.DocumentInitResponse:
        return await self._model(
            gm.DocumentInitResponse,
            "POST",
            f"/clients/{client_id}/documents",
            json_body=payload,
        )

    async def complete_client_document(
        self, client_id: str, document_id: str, *, size_bytes: int | None = None
    ) -> gm.DocumentDetail:
        return await self._model(
            gm.DocumentDetail,
            "POST",
            f"/clients/{client_id}/documents/{document_id}/complete",
            json_body={"size_bytes": size_bytes},
        )

    async def download_client_document(
        self, client_id: str, document_id: str
    ) -> gm.DocumentDownloadResponse:
        return await self._model(
            gm.DocumentDownloadResponse,
            "GET",
            f"/clients/{client_id}/documents/{document_id}/download",
        )

    async def archive_client_document(self, client_id: str, document_id: str) -> gm.DocumentDetail:
        return await self._model(
            gm.DocumentDetail,
            "DELETE",
            f"/clients/{client_id}/documents/{document_id}",
        )

    async def my_documents(self, *, include_archived: bool = False) -> gm.DocumentListResponse:
        params: dict[str, QueryValue] = {"include_archived": 1} if include_archived else {}
        return await self._model(gm.DocumentListResponse, "GET", "/me/documents", params=params)

    async def init_my_document(self, payload: dict[str, Any]) -> gm.DocumentInitResponse:
        return await self._model(
            gm.DocumentInitResponse, "POST", "/me/documents", json_body=payload
        )

    async def complete_my_document(
        self, document_id: str, *, size_bytes: int | None = None
    ) -> gm.DocumentDetail:
        return await self._model(
            gm.DocumentDetail,
            "POST",
            f"/me/documents/{document_id}/complete",
            json_body={"size_bytes": size_bytes},
        )

    async def download_my_document(self, document_id: str) -> gm.DocumentDownloadResponse:
        return await self._model(
            gm.DocumentDownloadResponse,
            "GET",
            f"/me/documents/{document_id}/download",
        )

    async def itinerary_documents(self, itinerary_id: str) -> gm.DocumentListResponse:
        return await self._model(
            gm.DocumentListResponse,
            "GET",
            f"/itineraries/{itinerary_id}/documents",
        )

    # ── sessions ─────────────────────────────────────────────────────────
    async def open_session(
        self,
        *,
        client_id: str,
        itinerary_id: str | None = None,
        seeded_opener: str | None = None,
        audience: gm.SessionAudience | str | None = None,
    ) -> gm.OpenSessionResponse:
        body: dict[str, Any] = {"client_id": client_id}
        if itinerary_id is not None:
            body["itinerary_id"] = itinerary_id
        if seeded_opener is not None:
            body["seeded_opener"] = seeded_opener
        # 'traveler' (shared client thread) vs 'advisor' (private advisor↔AI
        # workspace the traveler never sees). Omit to take the API default
        # (traveler); reuse is keyed per (client_id, audience). See 0018.
        if audience is not None:
            body["audience"] = str(audience)
        return await self._model(gm.OpenSessionResponse, "POST", "/sessions", json_body=body)

    async def list_turns(self, session_id: str) -> list[gm.AgentTurnSummary]:
        return await self._list(gm.AgentTurnSummary, "GET", f"/sessions/{session_id}/turns")

    # ── me (traveler self-service) ───────────────────────────────────────
    async def my_client(self) -> gm.MyClientResponse:
        return await self._model(gm.MyClientResponse, "GET", "/me/client")

    async def my_itineraries(self) -> gm.MyItinerariesResponse:
        return await self._model(gm.MyItinerariesResponse, "GET", "/me/itineraries")

    # ── onboarding / demos ───────────────────────────────────────────────
    async def random_opener(self) -> gm.OnboardingOpenerResponse:
        return await self._model(gm.OnboardingOpenerResponse, "GET", "/onboarding/openers/random")

    async def demo_japan(
        self, *, client_id: str, trip_start_at: str | None = None, title: str | None = None
    ) -> gm.JapanInstantiateResponse:
        body: dict[str, Any] = {"client_id": client_id}
        if trip_start_at is not None:
            body["trip_start_at"] = trip_start_at
        if title is not None:
            body["title"] = title
        return await self._model(
            gm.JapanInstantiateResponse, "POST", "/demos/japan", json_body=body
        )
