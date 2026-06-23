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
    async def redeem_invite(self, *, code: str, email: str) -> None:
        await self._send(
            "POST",
            "/auth/redeem-invite",
            json_body={"code": code, "email": email},
            authed=False,
        )

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
        self, *, title: str = "", client_id: str | None = None
    ) -> gm.ItineraryResponse:
        body = {"title": title, "client_id": client_id}
        return await self._model(gm.ItineraryResponse, "POST", "/itinerary", json_body=body)

    async def get_graph(self, itinerary_id: str) -> gm.GraphResponse:
        return await self._model(gm.GraphResponse, "GET", f"/itinerary/{itinerary_id}")

    async def list_advisor_itineraries(self) -> gm.AdvisorItinerariesResponse:
        return await self._model(gm.AdvisorItinerariesResponse, "GET", "/itineraries")

    async def approve(self, itinerary_id: str) -> gm.ItineraryResponse:
        return await self._model(gm.ItineraryResponse, "POST", f"/itinerary/{itinerary_id}/approve")

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

    # ── nodes ────────────────────────────────────────────────────────────
    async def add_node(
        self,
        itinerary_id: str,
        *,
        type: str,
        title: str = "",
        status: str = "idea",
        source: str | None = None,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        cost_amount: str | None = None,
        cost_currency: str | None = None,
        cost_kind: str | None = None,
        parent_subgraph_id: str | None = None,
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
        status: str = "proposed",
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
    async def list_clients(self) -> list[gm.ClientSummary]:
        return await self._list(gm.ClientSummary, "GET", "/clients")

    async def create_client(self, payload: dict[str, Any]) -> gm.ClientCreateResponse:
        return await self._model(gm.ClientCreateResponse, "POST", "/clients", json_body=payload)

    async def get_client(
        self, client_id: str, *, include_redacted: bool = False
    ) -> gm.ClientDetail:
        params: dict[str, QueryValue] = {"include_redacted": 1} if include_redacted else {}
        return await self._model(gm.ClientDetail, "GET", f"/clients/{client_id}", params=params)

    async def list_client_sessions(self, client_id: str) -> gm.ClientSessionsResponse:
        return await self._model(gm.ClientSessionsResponse, "GET", f"/clients/{client_id}/sessions")

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

    # ── sessions ─────────────────────────────────────────────────────────
    async def open_session(
        self,
        *,
        client_id: str,
        itinerary_id: str | None = None,
        seeded_opener: str | None = None,
    ) -> gm.OpenSessionResponse:
        body: dict[str, Any] = {"client_id": client_id}
        if itinerary_id is not None:
            body["itinerary_id"] = itinerary_id
        if seeded_opener is not None:
            body["seeded_opener"] = seeded_opener
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
