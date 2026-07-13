"""Composable flow steps for the concierge-to-confirmed e2e suite.

Each per-pillar test file (and the full-loop test) is assembled from the small,
reusable *flow steps* defined here, so a stage written once — "advisor seeds a
client + invite", "build a multi-source itinerary", "analyze and wait" — reads
the same way everywhere and a manual ``ovb`` smoke and an automated assertion
stay one expression apart (the README's "one core, three faces" promise).

Two design rules carried from the existing harness:

* **Assert on invariants, not wording.** Steps return typed models; tests assert
  on *what changed* (a node gained provenance, an analysis emitted a finding) —
  never on the agent's exact prose, so a flow is green against the local mock
  agent and real Bedrock alike.
* **Self-skip, never false-green.** Stages that depend on a milestone not yet
  built call :func:`skip_until`, which raises ``pytest.skip`` with the slice that
  will light them up — mirroring the honest ``NotImplementedError`` stubs in
  ``ovb.invariants``. The scaffold is complete; the skip is the only thing
  standing between it and a live assertion.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn

import pytest

from ovb._compat import unwrap_root
from ovb._generated import models as gm
from ovb.errors import ApiError
from ovb.invariants import Violation, assert_no_violations, graph_integrity
from ovb.scenario import Harness
from ovb.sdk import Ovb

# ─────────────────────────────────────────────────────────────────────────────
# Milestone gating — honest skips for flows whose backend hasn't landed yet.
# ─────────────────────────────────────────────────────────────────────────────


def skip_until(slice_id: str, what: str) -> NoReturn:
    """Skip a flow whose backend lands in a future slice.

    ``slice_id`` is the plan coordinate (e.g. ``"M005/I1"``) so a reader knows
    exactly which slice un-skips the test. Used instead of ``xfail`` because the
    endpoints simply do not exist yet — there is nothing to fail against.
    """
    pytest.skip(f"{what} — lands in {slice_id} (mvp-plan.md); scaffold ready, backend not built")


# Agent error reasons that mean "this box can't actually run a turn" (no Bedrock
# creds / model upstream down) — infra, not a product failure. We skip toward F3
# (live-agent UAT), mirroring the API-unreachable + payments-unconfigured skips.
_AGENT_UNAVAILABLE_REASONS = frozenset({"upstream_unavailable", "agent_unavailable"})


def require_live_agent_turn(result: Any) -> None:
    """Self-skip when a turn errored because the agent upstream is unavailable.

    A turn that *ran* but produced no tool call is a product signal the caller
    handles (e.g. the deterministic mock records no fact); this only catches the
    *infrastructure* case — the model backend is unreachable — so a credential-less
    local box self-skips instead of false-failing. Other turn errors fall through
    to the caller's own ``assert result.ok``.
    """
    if result.ok:
        return
    reason = result.error.reason if result.error else ""
    if reason in _AGENT_UNAVAILABLE_REASONS:
        pytest.skip(f"agent upstream unavailable ({reason}) — live-agent turns are verified in F3")


# ─────────────────────────────────────────────────────────────────────────────
# Identity / client setup
# ─────────────────────────────────────────────────────────────────────────────


def unique_email(prefix: str = "e2e") -> str:
    """A collision-free invite target so ``ensure_client`` always creates fresh.

    ``POST /clients`` issues a real Supabase invite that sends a welcome email
    through the project's SMTP (Resend on staging). The recipient domain must be
    genuinely deliverable or GoTrue fails the send with ``500 Error sending
    invite email`` (surfaced as ``502 auth_upstream_unavailable``). We therefore
    plus-address a real mailbox: ``$OVB_E2E_EMAIL_BASE`` (default
    ``chris@outdoorvoyage.com``) with a unique ``+tag`` per client, so every
    address is unique yet lands in one deliverable inbox. A reserved/undeliverable
    TLD (``.dev`` / ``.test``) bounces the send and masks the real flow.
    """
    base = os.environ.get("OVB_E2E_EMAIL_BASE", "chris+ovb@outdoorvoyage.com")
    local, _, domain = base.partition("@")
    tag = f"{prefix}-{uuid.uuid4().hex[:12]}"
    return f"{local}+{tag}@{domain}"


async def ensure_client(
    advisor: Ovb,
    *,
    full_name: str = "E2E Traveler",
    email: str | None = None,
    net_worth: int | None = None,
    party_notes: str = "",
    children_ages: list[int] | None = None,
) -> tuple[str, str]:
    """Advisor creates a client + Dossier and emails a welcome link (atomic).

    Returns (client_id, email). Mirrors ``POST /clients`` — the same call
    ``ovb clients create`` makes. On a 409 (email already on one of the
    advisor's clients) it resolves the existing client by email, so the step is
    idempotent for a fixed email and creating for a unique one.
    """
    target = email or unique_email()
    # contact_preference is required on the typed Dossier core (DossierTyped); the
    # rest are optional. Mirrors what `ovb clients create` sends.
    typed: dict[str, Any] = {"contact_preference": "email", "travel_party_notes": party_notes}
    if net_worth is not None:
        typed["estimated_net_worth_usd"] = net_worth
    if children_ages:
        typed["children_ages"] = children_ages
    payload = {"full_name": full_name, "email": target, "dossier": {"typed": typed}}
    try:
        created = await advisor.create_client(payload)
        return str(created.client_id), target
    except ApiError as exc:
        if exc.status != 409:
            raise
        for summary in (await advisor.list_clients()).clients:
            if str(summary.email).lower() == target.lower():
                return str(summary.id), target
        raise


def facts_of(detail: gm.ClientDetail, tier: str) -> list[Any]:
    """The active fact rows for one tier (``dossier`` | ``profile`` | ``osint``)."""
    return getattr(detail, f"{tier}_facts", None) or []


def fact_texts(detail: gm.ClientDetail, tier: str) -> list[str]:
    """The text of every active fact in a tier — sentinels for a redaction check."""
    return [str(unwrap_root(getattr(f, "text", ""))) for f in facts_of(detail, tier)]


async def seed_dossier(
    advisor: Ovb,
    client_id: str,
    *,
    dossier: list[tuple[str, str]] | None = None,
    profile: list[tuple[str, str]] | None = None,
    osint: list[tuple[str, str]] | None = None,
) -> None:
    """Hand-seed the three context tiers (Dossier / Profile / OSINT).

    Each entry is ``(kind, text)``. This is the advisor "Dossier" authoring
    that grounds the agent's first message (Pillar 1 → Pillar 2 hand-off).
    """
    for tier, rows in (("dossier", dossier), ("profile", profile), ("osint", osint)):
        for kind, text in rows or []:
            await advisor.add_fact(client_id, tier=tier, kind=kind, text=text)


# ─────────────────────────────────────────────────────────────────────────────
# Itinerary construction
# ─────────────────────────────────────────────────────────────────────────────


async def ensure_japan_itinerary(
    advisor: Ovb,
    *,
    client_id: str,
    trip_start_at: str | None = None,
) -> str:
    """Instantiate the seeded Japan itinerary for a client; returns itinerary_id.

    Gives every downstream step (analyze, fill, cost roll-up) a rich, timed,
    geo-located multi-day graph to operate on without depending on a live agent.
    """
    res = await advisor.demo_japan(client_id=client_id, trip_start_at=trip_start_at)
    return str(res.itinerary_id)


def assert_graph_sound(graph: gm.GraphResponse) -> None:
    """Structural invariants must hold after any mutation (no orphans, valid status)."""
    assert_no_violations(graph_integrity(graph))


def assert_provenance(node: gm.NodeResponse) -> list[Violation]:
    """Every inventory-sourced node must carry source + source_id (Pillar 3 acceptance)."""
    out: list[Violation] = []
    if not node.source:
        out.append(Violation("missing_source", f"node {node.id} has no source"))
    if not node.source_id:
        out.append(Violation("missing_source_id", f"node {node.id} has no source_id"))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Inventory search
# ─────────────────────────────────────────────────────────────────────────────


async def search_inventory(advisor: Ovb, **params: Any) -> gm.SearchInventoryResponse:
    """Thin wrapper so tests read ``search_inventory(advisor, kind="hotel", ...)``."""
    clean = {k: v for k, v in params.items() if v is not None}
    return await advisor.search_inventory(params=clean)


def first_item(resp: gm.SearchInventoryResponse) -> Any | None:
    """First inventory item, or None — tests pivot to a skip when a provider is dark."""
    return resp.items[0] if resp.items else None


async def propose_addable(
    advisor: Ovb,
    itinerary_id: str,
    items: list[Any],
    *,
    prefer_source: str = "mock",
) -> gm.NodeResponse | None:
    """Propose the first item whose detail actually resolves; returns the node or None.

    `POST /nodes/from-inventory` re-fetches the item by (source, source_id) and 404s
    if that provider's `get_detail` can't resolve it — a real provider quirk (some OV
    listing IDs are searchable but not detail-addressable). We try items in order,
    preferring a deterministic provider, so the roundtrip is robust to which vendor
    happened to rank first. Returns None when nothing is addable (caller skips).
    """
    ordered = sorted(items, key=lambda i: i.source != prefer_source)
    for item in ordered:
        try:
            return await advisor.node_from_inventory(
                itinerary_id, source=item.source, source_id=item.source_id
            )
        except ApiError as exc:
            if exc.status == 404:
                continue  # not detail-addressable; try the next item
            raise
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Analyze (async state machine)
# ─────────────────────────────────────────────────────────────────────────────


async def analyze_and_wait(
    harness: Harness,
    advisor: Ovb,
    itinerary_id: str,
    *,
    depth: str = "standard",
    force_rerun: bool = True,
    timeout: float = 30.0,
) -> gm.AnalysisDetailResponse:
    """Queue an analysis and poll it to a terminal state (the UI's spinner)."""
    created = await advisor.start_analysis(itinerary_id, depth=depth, force_rerun=force_rerun)
    return await harness.wait_for_analysis(
        advisor, str(created.analysis_id), itinerary_id=itinerary_id, timeout=timeout
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fill (gap-filling) — gap derivation from a built graph
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Gap:
    start: str  # ISO-8601
    end: str


def _parse_iso(value: Any) -> datetime | None:
    raw = unwrap_root(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def find_fill_gap(graph: gm.GraphResponse) -> Gap | None:
    """Find the widest open window between consecutive timed nodes.

    Fill needs a ``{start, end}`` gap to propose into. We derive it from the
    built graph the same way the advisor authoring surface (B7) eventually will:
    sort timed nodes, walk consecutive pairs, return the largest end→start gap.
    Returns ``None`` when the graph has fewer than two timed nodes.
    """
    timed: list[tuple[datetime, datetime]] = []
    for node in graph.nodes:
        start = _parse_iso(node.starts_at)
        if start is None:
            continue
        minutes = node.duration_minutes or 0
        timed.append((start, start + timedelta(minutes=minutes)))
    timed.sort(key=lambda pair: pair[0])
    if len(timed) < 2:
        return None

    widest: tuple[datetime, datetime] | None = None
    widest_span = 0.0
    for (_, prev_end), (next_start, _) in zip(timed, timed[1:], strict=False):
        span = (next_start - prev_end).total_seconds()
        if span > widest_span:
            widest_span = span
            widest = (prev_end, next_start)
    if widest is None or widest_span <= 0:
        return None
    return Gap(start=widest[0].isoformat(), end=widest[1].isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# Booking through the M005 money gate — the only path a node reaches ``booked``
# ─────────────────────────────────────────────────────────────────────────────


async def book_node_via_money_gate(
    advisor: Ovb,
    itinerary_id: str,
    node_id: str,
    *,
    amount: str = "1000.00",
    currency: str = "USD",
) -> None:
    """Drive a node to ``booked`` the way the product does: through a paid invoice.

    Since M005 a node can't be flipped straight to ``booked`` via ``update_node``
    (the gate refuses it with ``use_booking_flow``); booking authority is the money
    gate. This prices + approves the node (demoting first if it's already firmed),
    charges + issues + pays a covering invoice line, then books it — the same
    sequence Pillar 6 proves in detail. Self-skips when no payment gateway is wired
    on the target (the honest skip, mirroring Pillar 6), so a credential-less stack
    doesn't false-fail.
    """
    graph = await advisor.get_graph(itinerary_id)
    node = next((n for n in graph.nodes if str(n.id) == node_id), None)
    # Editing a firmed node needs a demotion first (G1); pre-firmed nodes edit freely.
    if node is not None and str(node.status) in {"approved", "booked", "confirmed"}:
        await advisor.update_node(itinerary_id, node_id, fields={"status": "pending"})
    await advisor.update_node(
        itinerary_id,
        node_id,
        fields={"cost_amount": amount, "cost_currency": currency, "cost_kind": "total"},
    )
    await advisor.update_node(itinerary_id, node_id, fields={"status": "approved"})

    invoice = await advisor.create_invoice(itinerary_id, label="Booking", currency=currency)
    await advisor.add_invoice_line(str(invoice.id), node_id=node_id)
    await advisor.issue_invoice(str(invoice.id))
    try:
        await advisor.pay_invoice(str(invoice.id), payment_method_nonce="fake-valid-nonce")
    except ApiError as exc:
        if exc.detail == "payments_unconfigured":
            pytest.skip("no payment gateway wired on this target (prod without keys)")
        raise
    await advisor.book_node(itinerary_id, node_id)
