"""AI Fill service (TravelGraph Phase 6 / B6).

Takes a *gap* in an itinerary and proposes physically-feasible candidates from
live inventory, scoped by a party's constraints and anchored on the latest
Analyze run (B5). Read-only: a proposal mutates nothing. Accepting one is the
existing ``POST /itinerary/{id}/nodes/from-inventory`` write (a Fill proposal
carries the ``inventory_source``/``inventory_id`` that route needs), so the
proposed node lands with full provenance through the normal ``add_node`` path.

The feasibility envelope reuses the **same** mode-speed model the standard
Analyze runner uses (``app.services.analyze_runners.common``) so Fill can never
suggest a stop the analyzer would then flag as unreachable. Where the bracketing
geometry is unknown, a candidate is *marked* ``feasibility_unknown`` rather than
silently asserted feasible (handoff §4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

from app.inventory.registry import InventoryCtx
from app.models import (
    Analysis,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
    NodeType,
)
from app.services.analyze_runners.common import (
    GraphNode,
    drive_mode_for_distance,
    haversine_km,
    load_timeline_nodes,
    transit_minutes,
)
from app.services.inventory import search_inventory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.inventory.registry import InventoryProviderRegistry
    from app.inventory.schemas import InventoryItem


# Kinds that make sense to drop into a gap by default — restaurants + activities.
# A caller can override with ``desired_kinds`` (e.g. only meals).
_DEFAULT_KINDS: tuple[NodeType, ...] = (NodeType.meal, NodeType.experience)

# InventoryItem.kind is a 1:1 subset of NodeType; these are the kinds a provider
# can actually return (the rest of NodeType — free_time, subway, … — is graph
# structure, never inventory).
_INVENTORY_NODE_TYPES: frozenset[NodeType] = frozenset(
    {
        NodeType.experience,
        NodeType.destination,
        NodeType.hotel,
        NodeType.flight,
        NodeType.meal,
        NodeType.transit,
        NodeType.note,
    }
)

# Default visit duration per kind (minutes) when the item carries none. Coarse,
# tunable — Fill assigns a candidate a provisional start/end inside the gap.
_DEFAULT_DURATION_MIN: dict[NodeType, int] = {
    NodeType.meal: 90,
    NodeType.experience: 120,
    NodeType.destination: 120,
    NodeType.hotel: 60,
    NodeType.transit: 30,
    NodeType.note: 0,
    NodeType.flight: 0,
}

# Inventory geo-bias radius bounds (metres). The bias is a hint — providers that
# ignore it still get filtered by the drive-time envelope below.
_MIN_RADIUS_M = 2_000
_MAX_RADIUS_M = 150_000
# Urban drive km/h used only to turn a gap into a coarse search radius.
_RADIUS_DRIVE_KMH = 25.0

# Two meals scheduled within this window of each other read as "you just ate" —
# a meal candidate butted up against an adjacent meal is heavily down-ranked
# (below the default min_score) so Fill won't recommend it unless asked.
_MEAL_SPACING_MIN = 180.0
_REDUNDANT_MEAL_FACTOR = 0.35


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True, slots=True)
class GapWindow:
    """The empty window to fill. Bounds are tz-aware."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class FillProposal:
    """One ranked, feasibility-annotated candidate for a gap.

    ``inventory_source``/``inventory_id`` round-trip into the from-inventory
    write so accepting this proposal needs no extra bookkeeping.
    """

    inventory_source: str
    inventory_id: str
    title: str
    type: NodeType
    starts_at: datetime
    ends_at: datetime
    location: GeoPoint | None
    score: float
    fits_in_gap: bool
    feasibility_unknown: bool
    drive_time_in_min: int | None
    drive_time_out_min: int | None
    party_ok: bool
    constraint_warnings: list[str]
    rationale: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FillResult:
    """``fill_gap`` output: ranked proposals + the analysis they were anchored
    on (``None`` when no completed analysis exists — feasibility is still
    computed from graph geometry, it just isn't analysis-anchored)."""

    proposals: list[FillProposal]
    analysis_id: uuid.UUID | None
    analysis_age_seconds: int | None


# ── helpers ────────────────────────────────────────────────────────────


def _ensure_aware(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC so comparisons with DB timestamptz work."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _node_types_to_inventory_kinds(types: list[NodeType]) -> list[str]:
    """Map requested NodeTypes to provider ``kind`` strings, dropping any
    NodeType a provider can't return (graph-structure types)."""
    return [t.value for t in types if t in _INVENTORY_NODE_TYPES]


def _item_point(item: InventoryItem) -> GeoPoint | None:
    loc = item.location
    if loc is None or loc.lat is None or loc.lng is None:
        return None
    return GeoPoint(lat=loc.lat, lng=loc.lng)


def _anchors(nodes: list[GraphNode], gap: GapWindow) -> tuple[GraphNode | None, GraphNode | None]:
    """Nearest located + timed nodes bracketing the gap.

    ``prior`` is the located node ending closest before the gap starts;
    ``next`` the located node starting closest after the gap ends. Either may
    be ``None`` (gap at a trip edge, or neighbors have no coordinates).
    """
    located = [
        n
        for n in nodes
        if n.has_point and n.starts_lower is not None and n.starts_upper is not None
    ]
    prior = max(
        (n for n in located if n.starts_upper is not None and n.starts_upper <= gap.start),
        key=lambda n: n.starts_upper,  # type: ignore[arg-type,return-value]
        default=None,
    )
    nxt = min(
        (n for n in located if n.starts_lower is not None and n.starts_lower >= gap.end),
        key=lambda n: n.starts_lower,  # type: ignore[arg-type,return-value]
        default=None,
    )
    return prior, nxt


def _gap_is_occupied(nodes: list[GraphNode], gap: GapWindow) -> bool:
    """True when any timed, duration-bearing node already spans into the gap.

    A "gap" must be genuinely empty: a multi-day card (a several-night hotel, a
    lodge/expedition/cornerstone booked across a block) covers every hour inside
    its span, so a window that lands *inside* one is not a gap at all — filling
    it would double-book. We test half-open overlap
    (``starts_lower < gap.end and starts_upper > gap.start``), so a stop that
    merely butts the gap edge (``starts_upper == gap.start``) is an adjacent
    neighbour, not an overlap. Zero-duration points (a free-standing note
    dropped *in* the gap to request something new) carry ``starts_upper ==
    starts_lower`` and are intentionally not treated as occupancy — that flow
    depends on Fill still returning options.
    """
    return any(
        n.starts_lower is not None
        and n.starts_upper is not None
        and n.starts_upper > n.starts_lower  # real duration, not a point marker
        and n.starts_lower < gap.end
        and n.starts_upper > gap.start
        for n in nodes
    )


def _temporal_neighbors(
    nodes: list[GraphNode], gap: GapWindow
) -> tuple[GraphNode | None, GraphNode | None]:
    """Nearest timed nodes bracketing the gap, ignoring whether they're located.

    These drive the *content*-adjacency check (e.g. "you just ate"), which is
    about what sits next to the gap in time — distinct from :func:`_anchors`,
    which needs coordinates for the drive-time envelope. A meal with no point
    still counts as the meal you just had.
    """
    timed = [n for n in nodes if n.starts_lower is not None and n.starts_upper is not None]
    prior = max(
        (n for n in timed if n.starts_upper is not None and n.starts_upper <= gap.start),
        key=lambda n: n.starts_upper,  # type: ignore[arg-type,return-value]
        default=None,
    )
    nxt = min(
        (n for n in timed if n.starts_lower is not None and n.starts_lower >= gap.end),
        key=lambda n: n.starts_lower,  # type: ignore[arg-type,return-value]
        default=None,
    )
    return prior, nxt


def _search_center(prior: GraphNode | None, nxt: GraphNode | None) -> GeoPoint | None:
    pts = [(n.lat, n.lng) for n in (prior, nxt) if n is not None]
    if not pts:
        return None
    return GeoPoint(
        lat=sum(p[0] for p in pts) / len(pts),  # type: ignore[misc]
        lng=sum(p[1] for p in pts) / len(pts),  # type: ignore[misc]
    )


def _search_radius_m(gap_min: float) -> int:
    """A coarse bias radius: roughly the one-way urban drive a half-gap buys."""
    one_way_km = _RADIUS_DRIVE_KMH * (gap_min / 2.0 / 60.0)
    return int(max(_MIN_RADIUS_M, min(_MAX_RADIUS_M, one_way_km * 1000)))


def _drive_min(a: GeoPoint, b: GeoPoint) -> int:
    d = haversine_km(a.lat, a.lng, b.lat, b.lng)
    return round(transit_minutes(d, drive_mode_for_distance(d)))


def _item_allergens(item: InventoryItem) -> set[str]:
    raw_allergens = item.raw.get("allergens") if isinstance(item.raw, dict) else None
    found: set[str] = set()
    if isinstance(raw_allergens, list):
        found.update(str(a).casefold() for a in raw_allergens)
    found.update(t.casefold() for t in (item.tags or []))
    return found


def _party_eval(
    item: InventoryItem,
    node_type: NodeType,
    *,
    allergens: set[str],
    has_mobility_limit: bool,
) -> tuple[bool, list[str], bool]:
    """Return ``(party_ok, warnings, hard_block)``.

    A meal carrying a party allergen is a *hard* block (dropped). A mobility
    mismatch is a soft warning (kept, score-penalized) — the advisor decides.
    """
    warnings: list[str] = []
    party_ok = True
    hard_block = False

    if node_type is NodeType.meal and allergens:
        hit = allergens & _item_allergens(item)
        if hit:
            return False, [f"contains allergen(s): {', '.join(sorted(hit))}"], True

    if has_mobility_limit:
        tags = {t.casefold() for t in (item.tags or [])}
        if tags & {"strenuous", "difficult", "hiking"}:
            party_ok = False
            warnings.append("may exceed a traveler's mobility")

    return party_ok, warnings, hard_block


def _redundant_meal(
    node_type: NodeType,
    *,
    starts_at: datetime,
    ends_at: datetime,
    prior_neighbor: GraphNode | None,
    next_neighbor: GraphNode | None,
) -> bool:
    """True when this is a meal butted up against an adjacent meal in time.

    Proposing lunch right after the lunch you just finished (or right before
    dinner) is the "you just ate" case — measured against the gap's temporal
    neighbors, not its geometry anchors.
    """
    if node_type is not NodeType.meal:
        return False
    if (
        prior_neighbor is not None
        and prior_neighbor.type is NodeType.meal
        and prior_neighbor.starts_upper is not None
        and (starts_at - prior_neighbor.starts_upper).total_seconds() / 60.0 < _MEAL_SPACING_MIN
    ):
        return True
    return bool(
        next_neighbor is not None
        and next_neighbor.type is NodeType.meal
        and next_neighbor.starts_lower is not None
        and (next_neighbor.starts_lower - ends_at).total_seconds() / 60.0 < _MEAL_SPACING_MIN
    )


def _build_proposal(
    item: InventoryItem,
    node_type: NodeType,
    *,
    gap: GapWindow,
    gap_min: float,
    prior: GraphNode | None,
    nxt: GraphNode | None,
    party_ok: bool,
    warnings: list[str],
    prior_neighbor: GraphNode | None = None,
    next_neighbor: GraphNode | None = None,
) -> FillProposal:
    loc = _item_point(item)
    duration_min = _DEFAULT_DURATION_MIN.get(node_type, 90)

    drive_in: int | None = None
    drive_out: int | None = None
    if loc is not None and prior is not None:
        drive_in = _drive_min(GeoPoint(prior.lat, prior.lng), loc)  # type: ignore[arg-type]
    if loc is not None and nxt is not None:
        drive_out = _drive_min(loc, GeoPoint(nxt.lat, nxt.lng))  # type: ignore[arg-type]

    # Unknown when the candidate has no point, or there's no located neighbor to
    # measure travel against — don't fabricate reachability (handoff §4).
    feasibility_unknown = loc is None or (prior is None and nxt is None)

    in_min = drive_in or 0
    out_min = drive_out or 0
    used_min = in_min + duration_min + out_min
    fits_in_gap = (not feasibility_unknown) and used_min <= gap_min

    starts_at = gap.start if feasibility_unknown else gap.start + timedelta(minutes=in_min)
    ends_at = starts_at + timedelta(minutes=duration_min)

    party_factor = 1.0 if party_ok else 0.6
    if feasibility_unknown:
        score = 0.5 * party_factor
    elif not fits_in_gap:
        score = 0.25 * party_factor
    else:
        proximity = max(0.0, 1.0 - (in_min + out_min) / gap_min) if gap_min else 0.0
        util = min(1.0, used_min / gap_min) if gap_min else 0.0
        score = (0.6 + 0.25 * proximity + 0.15 * util) * party_factor

    # Variety: don't recommend a meal right after (or before) another meal.
    redundant_meal = _redundant_meal(
        node_type,
        starts_at=starts_at,
        ends_at=ends_at,
        prior_neighbor=prior_neighbor,
        next_neighbor=next_neighbor,
    )
    if redundant_meal:
        score *= _REDUNDANT_MEAL_FACTOR

    rationale = _rationale(
        item.title, duration_min, drive_in, drive_out, fits_in_gap, feasibility_unknown
    )
    notes = list(warnings)
    if redundant_meal:
        notes.append("a meal is already scheduled close by")
    if notes:
        rationale = f"{rationale} ({'; '.join(notes)})"

    return FillProposal(
        inventory_source=item.source,
        inventory_id=item.source_id,
        title=item.title,
        type=node_type,
        starts_at=starts_at,
        ends_at=ends_at,
        location=loc,
        score=round(score, 3),
        fits_in_gap=fits_in_gap,
        feasibility_unknown=feasibility_unknown,
        drive_time_in_min=drive_in,
        drive_time_out_min=drive_out,
        party_ok=party_ok,
        constraint_warnings=warnings,
        rationale=rationale,
        raw={"source": item.source, "source_id": item.source_id, "kind": item.kind},
    )


def _rationale(
    title: str,
    duration_min: int,
    drive_in: int | None,
    drive_out: int | None,
    fits_in_gap: bool,
    feasibility_unknown: bool,
) -> str:
    if feasibility_unknown:
        return f"{title}: location/feasibility unknown — verify travel time before scheduling."
    bits: list[str] = []
    if drive_in is not None:
        bits.append(f"~{drive_in} min from the prior stop")
    bits.append(f"~{duration_min} min visit")
    if drive_out is not None:
        bits.append(f"~{drive_out} min on to the next")
    verdict = "fits the window" if fits_in_gap else "tighter than the window allows"
    return f"{title}: {', '.join(bits)} — {verdict}."


async def _resolve_analysis(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    analysis_id: uuid.UUID | None,
) -> Analysis | None:
    """The pinned analysis, or the latest completed run for this itinerary."""
    if analysis_id is not None:
        return (
            await session.execute(
                select(Analysis).where(
                    Analysis.id == analysis_id,
                    Analysis.itinerary_id == itinerary_id,
                )
            )
        ).scalar_one_or_none()
    return (
        await session.execute(
            select(Analysis)
            .where(
                Analysis.itinerary_id == itinerary_id,
                Analysis.status == AnalysisStatus.completed,
            )
            .order_by(Analysis.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _excluded_node_types(session: AsyncSession, analysis: Analysis | None) -> set[NodeType]:
    """NodeTypes a ``block`` finding rules out for this gap.

    A block finding carrying ``evidence.exclude_node_types: ["experience", …]``
    (e.g. a future weather-closure rule) removes those kinds from the candidate
    set — Fill must not re-propose what Analyze just blocked.
    """
    if analysis is None:
        return set()
    findings = (
        (
            await session.execute(
                select(AnalysisFinding).where(
                    AnalysisFinding.analysis_id == analysis.id,
                    AnalysisFinding.severity == FindingSeverity.block,
                )
            )
        )
        .scalars()
        .all()
    )
    excluded: set[NodeType] = set()
    for f in findings:
        for k in (f.evidence or {}).get("exclude_node_types", []):
            try:
                excluded.add(NodeType(k))
            except ValueError:
                continue
    return excluded


_MOBILITY_LIMIT_TERMS = {
    "wheelchair",
    "limited",
    "low",
    "reduced",
    "cane",
    "walker",
    "assisted",
    "scooter",
}


def _dietary_terms(dietary: str | None) -> set[str]:
    """Tokens from a member's free-text dietary field (0019).

    Folded into the allergen set, which is matched against each item's *declared*
    allergen list (not its prose) — so real allergen names ("nuts", "shellfish")
    block a meal, while preferences ("vegetarian") never match a declared
    allergen and are harmlessly inert.
    """
    if not dietary:
        return set()
    norm = dietary.lower()
    for sep in (";", "/", "\n", "\t"):
        norm = norm.replace(sep, ",")
    terms: set[str] = set()
    for phrase in norm.split(","):
        phrase = phrase.strip()
        if not phrase:
            continue
        terms.add(phrase)
        terms.update(w for w in phrase.split() if len(w) >= 4)
    return terms


async def _party_constraints(
    session: AsyncSession, party_id: uuid.UUID | None
) -> tuple[set[str], bool]:
    """Aggregate hard/soft constraints across a party's travelers.

    Returns ``(allergens, has_mobility_limit)`` — empty/false when no party is
    scoped or it has no travelers. Reads both the per-trip ``profile_attrs`` and
    the durable member's structured ``dietary`` / ``mobility`` (0019), so a
    constraint entered once on a saved member flows into Fill on every trip.
    """
    if party_id is None:
        return set(), False
    rows = (
        await session.execute(
            text(
                "select t.profile_attrs, pm.dietary, pm.mobility "
                "from public.travelers t "
                "left join public.party_members pm on pm.id = t.party_member_id "
                "where t.party_id = :pid"
            ),
            {"pid": party_id},
        )
    ).all()
    allergens: set[str] = set()
    has_mobility_limit = False
    for profile_attrs, dietary, mobility in rows:
        attrs = profile_attrs or {}
        for a in attrs.get("allergens", []) or []:
            allergens.add(str(a).casefold())
        if str(attrs.get("mobility", "")).casefold() in {"wheelchair", "limited", "low"}:
            has_mobility_limit = True
        # Durable member fields (0019) — structured identity reused across trips.
        allergens.update(_dietary_terms(dietary))
        if mobility and any(term in mobility.casefold() for term in _MOBILITY_LIMIT_TERMS):
            has_mobility_limit = True
    return allergens, has_mobility_limit


# ── public surface ─────────────────────────────────────────────────────


async def fill_gap(
    session: AsyncSession,
    *,
    registry: InventoryProviderRegistry,
    itinerary_id: uuid.UUID,
    gap: GapWindow,
    party_id: uuid.UUID | None = None,
    analysis_id: uuid.UUID | None = None,
    desired_kinds: list[NodeType] | None = None,
    min_score: float = 0.5,
    max_proposals: int = 8,
    ctx: InventoryCtx | None = None,
) -> FillResult:
    """Rank physically-feasible inventory candidates for ``gap``.

    Anchors on the latest completed analysis (or the pinned ``analysis_id``);
    queries inventory biased to the bracketing geometry; rejects/marks
    candidates that can't fit the drive-time envelope; drops party-allergen
    meals; down-ranks a meal butted up against an adjacent meal ("you just
    ate"); scores and truncates. Never mutates the graph.

    Returns no proposals when the window overlaps an existing duration-bearing
    node (a multi-day card already covers those hours — it's not a gap).
    """
    ctx = ctx or InventoryCtx(actor_kind="system")
    start = _ensure_aware(gap.start)
    end = _ensure_aware(gap.end)
    gap = GapWindow(start=start, end=end)
    gap_min = (end - start).total_seconds() / 60.0

    analysis = await _resolve_analysis(session, itinerary_id=itinerary_id, analysis_id=analysis_id)
    analysis_id_out = analysis.id if analysis is not None else None
    age_seconds: int | None = None
    if analysis is not None and analysis.completed_at is not None:
        age_seconds = max(0, int((datetime.now(UTC) - analysis.completed_at).total_seconds()))

    if gap_min <= 0:  # degenerate / empty gap — nothing to fill
        return FillResult(
            proposals=[], analysis_id=analysis_id_out, analysis_age_seconds=age_seconds
        )

    excluded = await _excluded_node_types(session, analysis)
    requested = list(desired_kinds) if desired_kinds else list(_DEFAULT_KINDS)
    types = [t for t in requested if t not in excluded]
    inv_kinds = _node_types_to_inventory_kinds(types)
    if not inv_kinds:
        return FillResult(
            proposals=[], analysis_id=analysis_id_out, analysis_age_seconds=age_seconds
        )

    scope: dict[str, Any] = {"party_id": str(party_id)} if party_id is not None else {}
    nodes = await load_timeline_nodes(session, itinerary_id=itinerary_id, scope=scope)

    # A gap that overlaps an existing multi-day (or any duration-bearing) node
    # isn't a gap — the window is already covered, so there's nothing to fill.
    # Short-circuit before hitting inventory.
    if _gap_is_occupied(nodes, gap):
        return FillResult(
            proposals=[], analysis_id=analysis_id_out, analysis_age_seconds=age_seconds
        )

    prior, nxt = _anchors(nodes, gap)
    prior_neighbor, next_neighbor = _temporal_neighbors(nodes, gap)

    filters: dict[str, Any] = {"limit": 40}
    center = _search_center(prior, nxt)
    if center is not None:
        filters |= {
            "near_lat": center.lat,
            "near_lng": center.lng,
            "radius_m": _search_radius_m(gap_min),
        }

    items = await search_inventory(
        registry, sources=None, kinds=inv_kinds, keyword=None, filters=filters, ctx=ctx
    )

    allergens, has_mobility_limit = await _party_constraints(session, party_id)

    proposals: list[FillProposal] = []
    for item in items:
        try:
            node_type = NodeType(item.kind)
        except ValueError:
            continue
        if node_type in excluded:
            continue
        party_ok, warnings, hard_block = _party_eval(
            item, node_type, allergens=allergens, has_mobility_limit=has_mobility_limit
        )
        if hard_block:
            continue
        proposals.append(
            _build_proposal(
                item,
                node_type,
                gap=gap,
                gap_min=gap_min,
                prior=prior,
                nxt=nxt,
                party_ok=party_ok,
                warnings=warnings,
                prior_neighbor=prior_neighbor,
                next_neighbor=next_neighbor,
            )
        )

    ranked = sorted(
        (p for p in proposals if p.score >= min_score),
        key=lambda p: p.score,
        reverse=True,
    )
    return FillResult(
        proposals=ranked[: max(1, max_proposals)],
        analysis_id=analysis_id_out,
        analysis_age_seconds=age_seconds,
    )


__all__ = ["FillProposal", "FillResult", "GapWindow", "GeoPoint", "fill_gap"]
