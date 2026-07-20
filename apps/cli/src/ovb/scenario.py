"""Stateful scenario tracking for the e2e suite (and CLI scenario runner).

The harness holds the evolving world — identities, the itinerary under test,
graph snapshots over time, and a transcript of operations — so a test asserts
on *what changed* between steps rather than just final state. Snapshots diff
node/edge sets; the analysis poller turns the async Analyze state machine into a
single awaited result. Identities are minted per role, so "as traveler" vs "as
staff" is one method call apart.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from ovb._generated import models as gm
from ovb.config import Profile
from ovb.sdk import Ovb


@dataclass(frozen=True, slots=True)
class GraphDiff:
    added_nodes: list[str]
    removed_nodes: list[str]
    changed_nodes: dict[str, dict[str, tuple[Any, Any]]]
    added_edges: list[str]
    removed_edges: list[str]

    @property
    def empty(self) -> bool:
        return not (
            self.added_nodes
            or self.removed_nodes
            or self.changed_nodes
            or self.added_edges
            or self.removed_edges
        )

    def summary(self) -> str:
        parts = []
        if self.added_nodes:
            parts.append(f"+{len(self.added_nodes)} nodes")
        if self.removed_nodes:
            parts.append(f"-{len(self.removed_nodes)} nodes")
        if self.changed_nodes:
            parts.append(f"~{len(self.changed_nodes)} nodes")
        if self.added_edges:
            parts.append(f"+{len(self.added_edges)} edges")
        if self.removed_edges:
            parts.append(f"-{len(self.removed_edges)} edges")
        return ", ".join(parts) if parts else "no change"


# Node fields whose change is worth tracking in a diff.
_TRACKED = ("type", "status", "title", "cost_amount", "cost_currency", "starts_at")


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """An indexed, diffable point-in-time view of an itinerary graph."""

    graph: gm.GraphResponse
    nodes: dict[str, gm.NodeResponse]
    edges: dict[str, gm.EdgeResponse]

    @classmethod
    def of(cls, graph: gm.GraphResponse) -> GraphSnapshot:
        return cls(
            graph=graph,
            nodes={str(n.id): n for n in graph.nodes},
            edges={str(e.id): e for e in graph.edges},
        )

    @property
    def status(self) -> str:
        """The trunk's derived display bucket ("" when the endpoint omitted it)."""
        value = self.graph.itinerary.display_status
        if value is None:
            return ""
        return str(value.value if hasattr(value, "value") else value)

    def statuses(self) -> dict[str, str]:
        return {nid: str(n.status) for nid, n in self.nodes.items()}

    def by_status(self, status: str) -> list[gm.NodeResponse]:
        return [n for n in self.nodes.values() if str(n.status) == status]

    def diff(self, later: GraphSnapshot) -> GraphDiff:
        before, after = set(self.nodes), set(later.nodes)
        changed: dict[str, dict[str, tuple[Any, Any]]] = {}
        for nid in before & after:
            a, b = self.nodes[nid], later.nodes[nid]
            deltas = {
                f: (getattr(a, f), getattr(b, f))
                for f in _TRACKED
                if getattr(a, f) != getattr(b, f)
            }
            if deltas:
                changed[nid] = deltas
        return GraphDiff(
            added_nodes=sorted(after - before),
            removed_nodes=sorted(before - after),
            changed_nodes=changed,
            added_edges=sorted(set(later.edges) - set(self.edges)),
            removed_edges=sorted(set(self.edges) - set(later.edges)),
        )


@dataclass(slots=True)
class Step:
    label: str
    data: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)


class AnalysisTimeout(TimeoutError):
    """Analyze did not reach a terminal state within the deadline."""


_TERMINAL = {"completed", "failed", "cancelled"}


@dataclass(slots=True)
class Harness:
    """Owns identities, the world-under-test, and a transcript for one scenario."""

    profile: Profile
    itinerary_id: str | None = None
    client_id: str | None = None
    transcript: list[Step] = field(default_factory=list)
    _clients: list[Ovb] = field(default_factory=list)

    def record(self, label: str, **data: Any) -> None:
        self.transcript.append(Step(label=label, data=data))

    # ── identities ───────────────────────────────────────────────────────
    def advisor(self, *, email: str | None = None) -> Ovb:
        ovb = Ovb.for_identity(self.profile, email=email, role="advisor")
        self._clients.append(ovb)
        return ovb

    def traveler(self, *, email: str | None = None) -> Ovb:
        ovb = Ovb.for_identity(self.profile, email=email, role="client")
        self._clients.append(ovb)
        return ovb

    def public(self) -> Ovb:
        ovb = Ovb.for_identity(self.profile, authed=False)
        self._clients.append(ovb)
        return ovb

    # ── state snapshots ──────────────────────────────────────────────────
    async def snapshot(self, ovb: Ovb, itinerary_id: str | None = None) -> GraphSnapshot:
        itin = itinerary_id or self.itinerary_id
        if itin is None:
            raise ValueError("no itinerary_id to snapshot")
        return GraphSnapshot.of(await ovb.get_graph(itin))

    # ── async-state polling ──────────────────────────────────────────────
    async def wait_for_analysis(
        self,
        ovb: Ovb,
        analysis_id: str,
        *,
        itinerary_id: str | None = None,
        timeout: float = 30.0,
        interval: float = 0.5,
    ) -> gm.AnalysisDetailResponse:
        """Poll an analysis until it reaches a terminal state (the UI's spinner)."""
        itin = itinerary_id or self.itinerary_id
        if itin is None:
            raise ValueError("no itinerary_id for analysis polling")
        deadline = time.monotonic() + timeout
        while True:
            detail = await ovb.get_analysis(itin, analysis_id)
            if str(detail.status) in _TERMINAL:
                self.record("analysis_done", analysis_id=analysis_id, status=str(detail.status))
                return detail
            if time.monotonic() >= deadline:
                raise AnalysisTimeout(
                    f"analysis {analysis_id} still {detail.status} after {timeout}s"
                )
            await asyncio.sleep(interval)

    async def aclose(self) -> None:
        for ovb in self._clients:
            await ovb.aclose()
        self._clients.clear()

    async def __aenter__(self) -> Harness:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
