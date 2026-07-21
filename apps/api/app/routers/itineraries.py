"""Itinerary graph HTTP surface (M001/S02).

Seven endpoints:

- ``POST   /itinerary``                              create a graph
- ``GET    /itinerary/{id}``                         assembled graph view
- ``POST   /itinerary/{id}/nodes``                   insert a node
- ``PATCH  /itinerary/{id}/nodes/{node_id}``         update a node
- ``DELETE /itinerary/{id}/nodes/{node_id}``         delete a node
- ``POST   /itinerary/{id}/edges``                   insert an edge
- ``DELETE /itinerary/{id}/edges/{edge_id}``         delete an edge

All of them sit behind the JWT middleware; ``AuthenticatedUser`` is pulled via
``require_user`` and mapped into an :class:`ActorContext` with
``kind=USER``. Service outcomes are mapped to HTTP status codes here; the
service never raises.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import date as _date  # the ResolvedStampResponse.date field shadows `date`
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, NoReturn

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.campaigns import get_campaign
from app.config import get_settings
from app.db import get_session, get_sessionmaker
from app.inventory.registry import InventoryCtx, UnknownSourceError
from app.inventory.schemas import ExperienceItem, FlightItem
from app.kernel import (
    ResolvedScheduleView,
    ResolvedStampView,
    analyze,
    nightly_lodging,
    resolve_view,
)
from app.models import (
    CardTemplate,
    Client,
    CostKind,
    EdgeType,
    ForkStatus,
    Itinerary,
    ItineraryTimingKind,
    Node,
    NodeStatus,
    NodeType,
    Profile,
    UserRole,
)
from app.routers.inventory import get_inventory_registry
from app.services.agent import drain_queue
from app.services.campaign_spine import snap_length
from app.services.card_mapping import (
    flight_item_to_card_attrs,
    flight_slice_count,
    inventory_item_to_card_metadata,
    scheduled_start_for_item,
)
from app.services.changes import load_itinerary_changes, next_changes_cursor
from app.services.display_status import DisplayStatus, display_status_expr
from app.services.fork import (
    ForkDiff,
    NodeChange,
    ReconcileDecision,
    ReconcileResult,
    abandon_fork,
    diff_fork,
    fork_itinerary,
    reconcile_fork,
    request_reconcile,
    withdraw_reconcile,
)
from app.services.fx import get_fx_service
from app.services.inventory import get_inventory_detail
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    DaySlot,
    ItineraryError,
    ItineraryOutcome,
    SchedulePlacement,
    _serialize_starts_at,
    _tz_offset_from_metadata,
    acquire_lock,
    add_edge,
    add_node,
    approve_all_nodes,
    assemble_initial_draft,
    compute_lock_reason,
    create_itinerary,
    delete_edge,
    delete_node,
    get_itinerary_graph,
    release_lock,
    retime_itinerary,
    update_itinerary_details,
    update_node,
)
from app.services.kernel_graph import kernel_graph_from_view
from app.services.kernel_sync import decoded_schedule
from app.services.link_preview import fetch_link_preview
from app.services.node_cost import (
    NodeCost,
    cost_from_inventory_item,
    resolve_party_size,
    sum_node_costs,
)
from app.services.node_kinds import is_schedulable
from app.services.olympus_template import build_olympus_template
from app.services.pagination import clamp_limit, require_cursor
from app.services.reading import seed_campaign_reading_list
from app.services.route_plan import RoutePlanError, compute_route
from app.services.subgraph import SubgraphMaterializeError, materialize_day_subgraph
from app.services.templates import instantiate_into
from app.services.transfers import build_transfer_card

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.inventory.registry import InventoryProviderRegistry


logger = logging.getLogger("ov_black.routers.itineraries")

router = APIRouter(prefix="/itinerary", tags=["itinerary"])


# ── Request / response models ──────────────────────────────────────────────


# Trip brief + timing (0033). The goal ("sailing in Greece with my family") and
# WHEN, modelled as a resolvable window + target duration + a discriminator so
# it spans exact dates -> fuzzy-but-bounded -> flexible. ``timing_note`` is
# free-text riding alongside for constraints the dates can't hold ("not August",
# "back by a Sunday"). Shared field defs keep create / update / response aligned.
_BRIEF_MAX = 2000
_NOTE_MAX = 2000


class CreateItineraryRequest(BaseModel):
    title: str = Field(default="", max_length=512)
    client_id: uuid.UUID | None = None
    # Optional at create — the builder's first-run intake usually fills these in
    # via PATCH, but a caller may seed them up front.
    brief: str | None = Field(default=None, max_length=_BRIEF_MAX)
    timing_kind: ItineraryTimingKind | None = None
    date_start: date | None = None
    date_end: date | None = None
    duration_nights: int | None = Field(default=None, ge=1, le=365)
    timing_note: str | None = Field(default=None, max_length=_NOTE_MAX)


class UpdateItineraryRequest(BaseModel):
    """Partial update of an itinerary's title + brief + timing.

    ``extra="forbid"`` so a misspelled field is a 422, not a silent no-op. Only
    fields explicitly present in the payload are applied (``exclude_unset``), so
    sending ``date_start: null`` clears the date while omitting it leaves the
    stored value untouched — the semantics the first-run intake relies on when a
    traveler switches from exact dates to a flexible window.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=512)
    brief: str | None = Field(default=None, max_length=_BRIEF_MAX)
    timing_kind: ItineraryTimingKind | None = None
    date_start: date | None = None
    date_end: date | None = None
    duration_nights: int | None = Field(default=None, ge=1, le=365)
    timing_note: str | None = Field(default=None, max_length=_NOTE_MAX)
    # The trip's hero image URL (0054). Send null to clear back to the default.
    hero_image: str | None = Field(default=None, max_length=2048)


class ItineraryResponse(BaseModel):
    id: uuid.UUID
    title: str
    client_id: uuid.UUID | None
    created_by: uuid.UUID | None
    # Derived trunk lifecycle (never stored): in_studio → with_traveler →
    # approved, bucketed from the nodes at read time. None when the endpoint
    # didn't compute it (write/lock responses); the graph read and the list
    # endpoints always populate it. On a fork it reflects the fork's own
    # nodes and is mostly meaningless — check fork_status instead.
    display_status: DisplayStatus | None = None
    # Fork lineage (G2). ``forked_from_id`` is the baseline this itinerary was
    # cloned from (None on a normal itinerary); ``fork_status`` tracks the
    # reconcile lifecycle and is None unless this row is a fork.
    forked_from_id: uuid.UUID | None = None
    fork_status: ForkStatus | None = None
    # Reconcile request (G3). Set when a traveler/agent asks staff to merge this
    # fork; cleared on reconcile/abandon. None on a fork with no pending request.
    reconcile_requested_at: datetime | None = None
    reconcile_request_note: str | None = None
    # Trip brief + timing (0033). All None until the first-run intake fills them.
    brief: str | None = None
    timing_kind: ItineraryTimingKind | None = None
    date_start: date | None = None
    date_end: date | None = None
    duration_nights: int | None = None
    timing_note: str | None = None
    # Day-1 anchor (0041, ADV-16). The date "Day 1" currently maps to on an
    # unpinned trip, so relative Day-N labels are stable. None until the first
    # card is scheduled; equals date_start once the dates are pinned (retime).
    days_anchor: date | None = None
    # Kernel anchor (0055, doc/itin-time.md): the canonical Day-1 calendar
    # date every relative schedule resolves against. Generalizes
    # ``days_anchor``/``date_start`` (exact trips anchor at date_start,
    # everything else at the stamped days_anchor); the web maps node
    # ``day_index`` labels onto dates with it. None on a never-scheduled,
    # never-dated trip.
    anchor_date: date | None = None
    # Campaign provenance + mood (0047). ``campaign_id`` is the inbound campaign
    # slug a trip was started from (None on ordinary trips); it drives the
    # dashboard auto-kickoff and agent campaign-awareness. ``mood`` is the
    # persisted atmospheric mood id that themes the concierge CHAT frame — not
    # the itinerary hero.
    campaign_id: str | None = None
    mood: str | None = None
    # The trip's hero image URL (0054), rendered directly by the dashboard hero
    # + basecamp tile. None resolves to a default hero client-side.
    hero_image: str | None = None


class RetimeItineraryRequest(BaseModel):
    """Pin the trip to real dates (Wave E / ADV-17): "Day 1 is date_start".

    The server shifts every scheduled node by ``date_start − days_anchor`` days
    (wall-clock preserved) and flips the itinerary to ``timing_kind=exact``.
    ``date_end`` is optional — omitted, it derives from the current span /
    ``duration_nights`` / the last scheduled card.
    """

    model_config = ConfigDict(extra="forbid")

    date_start: date
    date_end: date | None = None


class RetimeItineraryResponse(BaseModel):
    itinerary: ItineraryResponse
    # How far the plan moved and how many scheduled cards moved with it — the
    # UI's "Day 1 → Wed Mar 18 · 6 cards moved" confirmation payload.
    delta_days: int
    shifted_nodes: int
    # The retime affordance (doc/itin-time.md Phase 3): booked/confirmed cards
    # HOLD their calendar dates (world-pinned supplier commitments) instead of
    # blocking the retime; moved cards with date-sensitive snapshots (quoted
    # flights) need re-checking with their provider. The caller decides what to
    # surface — a banner, an advisor task list, an agent explanation.
    held_node_ids: list[uuid.UUID] = Field(default_factory=list)
    stale_node_ids: list[uuid.UUID] = Field(default_factory=list)


class CreateNodeRequest(BaseModel):
    type: NodeType
    status: NodeStatus = NodeStatus.pending
    title: str = ""
    parent_subgraph_id: uuid.UUID | None = None
    source: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # First-class cost (D-COST). amount + currency must be set together.
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None
    # Note anchoring (0014). A `note` is dual-mode: set `attached_to_node_id` to
    # annotate a host node, OR `starts_at` (ISO-8601, + optional
    # `duration_minutes`) for a free-standing note — exactly one. Ignored for
    # non-note types (and `attached_to_node_id` is rejected on them).
    attached_to_node_id: uuid.UUID | None = None
    starts_at: str | None = None
    duration_minutes: int | None = None


class CreateNodeFromInventoryRequest(BaseModel):
    """Create a graph node from a live inventory item by (source, source_id).

    The server fetches the current item through the provider registry and
    derives the typed card metadata (e.g. a Duffel flight → FlightCardAttrs),
    so callers never hand-shape card attrs. For flights this re-fetch is a
    natural offer refresh (D024). ``status`` defaults to ``pending`` — a
    candidate on the board.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    source_id: str
    status: NodeStatus = NodeStatus.pending
    parent_subgraph_id: uuid.UUID | None = None
    # Multi-day items (OV adventures) carry a day-by-day internal journey;
    # when true (default) it's materialized as an embedded subgraph — one
    # child node per day chained by ``follows`` edges. Ignored when the item
    # has no days or when this node is itself being created inside a
    # subgraph (no nested materialization).
    expand_days: bool = True


class CreateNodeFromLinkRequest(BaseModel):
    """Save a pasted web link into the Collection as an OpenGraph card.

    The server fetches ``url`` and derives a snapshot (title / image /
    description) so the saved card looks intentional rather than a bare link;
    the fetch degrades gracefully to just the URL. ``kind`` files the link under
    a Collection category (a restaurant → ``meal``, a hotel → ``hotel``) and
    defaults to ``note`` — an unfiled idea. ``status`` defaults to ``pending``
    (a candidate on the board). There is no ``starts_at``: a saved link lands in
    the Collection, unscheduled, until it's dragged onto the timeline.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    kind: NodeType = NodeType.note
    status: NodeStatus = NodeStatus.pending
    note: str | None = Field(default=None, max_length=_NOTE_MAX)
    parent_subgraph_id: uuid.UUID | None = None


class SchedulePlacementPayload(BaseModel):
    """Where a card landed, in trip terms (Phase 4, doc/itin-time.md).

    Drag-and-drop sends ``(day_index, minute_of_day)`` and the kernel builds
    the schedule server-side — no client ISO assembly, no offset guessing.
    ``clear=true`` unschedules instead (back to the Collection) and permits no
    other field. ``tz`` (IANA name) and ``duration_minutes`` are optional
    overrides; omitted, the node keeps its current zone (falling back to the
    trip's default) and width.
    """

    model_config = ConfigDict(extra="forbid")

    day_index: int | None = None
    minute_of_day: int | None = Field(default=None, ge=0, le=1439)
    duration_minutes: int | None = Field(default=None, ge=1)
    tz: str | None = None
    clear: bool = False


class UpdateNodeRequest(BaseModel):
    """Partial update. Any field omitted is left unchanged.

    ``model_config`` uses ``extra="forbid"`` so a misspelled field surfaces
    as 422, not a silent no-op.
    """

    model_config = ConfigDict(extra="forbid")

    type: NodeType | None = None
    status: NodeStatus | None = None
    title: str | None = None
    source: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] | None = None
    # First-class cost (D-COST). Advisor edits land here; amount + currency
    # must be set/cleared together (service-layer + DB CHECK enforce it).
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None
    # Phase 4 schedule placement — see SchedulePlacementPayload. Wins over any
    # ``metadata.start_time`` in the same request.
    schedule: SchedulePlacementPayload | None = None


class ResolvedStampResponse(BaseModel):
    """One schedule endpoint, resolved for display (Phase 4).

    ``day_index`` is the human Day N label (None for a pinned stamp on an
    undated trip); ``date`` is the local calendar date (None for a relative
    stamp on an undated trip); ``wall_time`` is "HH:MM" local; ``tz`` is the
    IANA zone (an ``Etc/GMT±N`` pseudo-zone on rows that predate real-zone
    writes); ``instant`` is the resolved ISO-8601 absolute time with the
    zone's offset, when resolvable.
    """

    day_index: int | None = None
    date: _date | None = None
    wall_time: str
    tz: str
    instant: str | None = None


class ResolvedScheduleResponse(BaseModel):
    """A node's schedule projected for display — the Phase 4 read shape.

    Per-endpoint local views (a flight's start and end each carry their own
    airport zone), the day span (calendar days covered — airline-style +1
    badges come from ``day_span > 1`` or differing endpoint dates), and
    whether this is a kernel-computed provisional slot for an unscheduled
    card (``synthesized`` — a layout hint; the card is still in the
    Collection).
    """

    kind: Literal["relative", "pinned"]
    start: ResolvedStampResponse
    end: ResolvedStampResponse | None = None
    day_span: int = 1
    synthesized: bool = False


class NodeResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    parent_subgraph_id: uuid.UUID | None
    type: NodeType
    status: NodeStatus
    title: str
    source: str | None
    source_id: str | None
    metadata: dict[str, Any]
    # First-class node cost (D-COST). ``cost_amount`` is a native-currency
    # decimal (serialized as a JSON string to avoid float precision loss);
    # ``cost_currency`` is ISO 4217; ``cost_kind`` is per_person|total. All
    # None for a node without a cost.
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None
    # Read-time FX conversion (0048) of ``cost_amount`` into the traveler's
    # preferred currency. Populated only by the graph-read endpoint when the
    # client has a ``preferred_currency`` and a rate resolves; None everywhere
    # else, so the card falls back to the native ``cost_amount``/``cost_currency``.
    cost_display_amount: Decimal | None = None
    cost_display_currency: str | None = None
    # Scheduled timing, derived from the node's ``starts_at`` tstzrange.
    # ``starts_at`` is the ISO-8601 lower bound; ``duration_minutes`` is the
    # whole-minute span (upper - lower), or None when there is no upper bound
    # (or no range at all). Both are None for nodes without a schedule.
    starts_at: str | None = None
    duration_minutes: int | None = None
    depth: int | None = None
    # Computed mutation-lock reason (G1). ``"status_locked"`` when the node is
    # firmed (approved/booked/confirmed), else None. Lets the agent/web explain
    # a refused edit without re-deriving the rule client-side.
    lock_reason: str | None = None
    # Fork lineage (G2). The baseline node this one was copied from, or None.
    forked_from_node_id: uuid.UUID | None = None
    # Note attachment (0014). For a `note` riding a host node, the host's id;
    # None for a free-standing note (which carries `starts_at`) or any non-note.
    attached_to_node_id: uuid.UUID | None = None
    # Sibling nodes created by the same write (from-inventory only). A round-trip
    # flight offer is one bookable item but two legs, so it materializes as this
    # node (the outbound) plus one ``additional_nodes`` entry per return/onward
    # leg. Empty for every single-node write; nested entries carry none of their
    # own. The agent turn loop fans these out into one card_proposed frame each.
    additional_nodes: list[NodeResponse] = Field(default_factory=list)
    # Whether this card may be placed on the timeline (derived from ``type``).
    # Non-schedulable cards (articles) live in the Collection only; the web
    # blocks drag-to-timeline for them and the write path refuses a time.
    # Defaulted so existing callers/fixtures stay valid; the serializers set it
    # explicitly from ``is_schedulable(type)``.
    schedulable: bool = True
    # 0055/Phase 3 — the card moved after its date-sensitive snapshot (e.g. a
    # flight quote) was taken; re-check availability with the provider. Set by
    # schedule moves and retimes; cleared by a fresh quote (new source_id).
    needs_revalidation: bool = False
    # 0055/Phase 4 — the resolved schedule view: day_index, per-endpoint local
    # wall time + zone + date, absolute instants, day span. The web renders
    # from this instead of re-deriving time client-side. None only for
    # unscheduled nodes with no synthesized slot (subgraph children, attached
    # notes, non-schedulable types) and legacy rows whose canonical schedule
    # columns don't decode.
    schedule: ResolvedScheduleResponse | None = None


class CreateEdgeRequest(BaseModel):
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any]


class GraphFindingResponse(BaseModel):
    """One kernel feasibility finding (Phase 5, doc/itin-time.md).

    Judgements, never rejections: ``flight_infeasible`` (block) — the traveler
    would still be in transit; ``flight_tight`` / ``overlap`` /
    ``follows_gap`` (warn) — physically possible but deserves an advisor's
    eye; ``stale`` (info) — a date-sensitive snapshot moved after it was
    quoted. ``node_ids`` are the nodes the judgement is about, so the UI can
    badge the exact cards.
    """

    code: str
    severity: Literal["block", "warn", "info"]
    message: str
    node_ids: list[uuid.UUID]


class NightLodgingResponse(BaseModel):
    """Where the traveler sleeps on one trip night — derived from lodging span
    coverage at read time, never stored. ``day_index`` labels the night by its
    evening (the night of Day 2 is Day 2's evening); ``on`` is that evening's
    calendar date, None until the trip is dated. Nights the plan leaves
    roofless simply don't appear. When two stays cover a night (same-day hotel
    change, overnight excursion away from a kept room), the later check-in
    owns it.
    """

    day_index: int
    on: date | None = None
    node_id: uuid.UUID


class GraphResponse(BaseModel):
    itinerary: ItineraryResponse
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    # Kernel feasibility findings over this graph (Phase 5) — flight margins,
    # lodging windows, overlaps, follows-gap constraints, stale snapshots.
    # Populated by the graph-read endpoint; other producers (fork/reconcile)
    # leave it empty.
    findings: list[GraphFindingResponse] = Field(default_factory=list)
    # Night-by-night lodging coverage (derived, read-only): lets any surface —
    # timeline, agent, exports — answer "where do they sleep tonight" without
    # walking spans itself. Populated by the graph-read endpoint only.
    nightly_lodging: list[NightLodgingResponse] = Field(default_factory=list)
    # Per-currency price of the plan (ADV-10): ``{currency: amount}`` summed over
    # the itinerary's priced, non-discarded, selected nodes — ``per_person``
    # amounts expanded by party size, matching the money-gate. Amounts serialize
    # as strings like ``cost_amount``. Empty when nothing is priced. Populated on
    # the graph-read endpoint; other producers (fork/reconcile) leave it empty.
    totals: dict[str, str] = Field(default_factory=dict)
    # Traveler's preferred display currency (0048) and the plan's whole price
    # converted into it — one comfortable number across mixed native currencies
    # (bugs.md: "you keep giving me things in euros"). ``display_currency`` is
    # the client's ``preferred_currency``; ``total_display`` is the summed,
    # converted total as a string. Both None when the client has no preferred
    # currency or the FX service is disabled/can't resolve every currency, in
    # which case the UI falls back to the native ``totals`` map above.
    display_currency: str | None = None
    total_display: str | None = None
    # The itinerary's effective traveler count (floored at 1), matching the party
    # expansion the money-gate applies to ``per_person`` costs. Surfaced so the
    # billing UI can compute a node's EFFECTIVE cost (``per_person`` × party) and
    # thus its per-node remaining balance across a deposit + balance split. Only
    # the graph-read endpoint populates it; other producers leave the default 1.
    party_size: int = 1
    # The calling viewer's own OPEN fork of this itinerary, when it is a baseline
    # (``forked_from_id is None``) — the traveler's "My version". Resolved per
    # request in ``get_itinerary_endpoint`` so the two-version toggle switches to
    # an existing fork instead of spawning a duplicate. Null on a fork itself, or
    # when the viewer has no open fork.
    viewer_open_fork_id: uuid.UUID | None = None


class CollectionResponse(BaseModel):
    """The itinerary's Collection (wish list): unscheduled, non-discarded nodes.

    A Collection item is just a node with no ``starts_at`` — a maybe the
    traveler/concierge has accumulated but not yet placed on the timeline.
    Discarded items are excluded. The web derives the same set from the graph it
    already loads; this endpoint keeps the agent's read cheap (it doesn't need
    the whole graph to shop the wish list before proposing something new).
    """

    itinerary_id: uuid.UUID
    items: list[NodeResponse]


class ReleaseLockResponse(BaseModel):
    itinerary: ItineraryResponse
    replayed_count: int


class DaySlotPayload(BaseModel):
    """One day's ordered node ids for the assemble_initial_draft route."""

    model_config = ConfigDict(extra="forbid")

    day_index: int
    node_ids_in_order: list[uuid.UUID]


class AssembleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_plan: list[DaySlotPayload] = Field(default_factory=list)


class ForkItineraryRequest(BaseModel):
    """Fork an itinerary into a versioned clone (G2). ``title`` defaults to
    ``"{baseline} (fork)"`` when omitted."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=512)


# ── G3 fork diff / reconcile ────────────────────────────────────────────────


class NodeChangeResponse(BaseModel):
    """One divergence in a fork's diff (added/removed/changed/moved).

    ``change_id`` is the stable handle the reconcile request references in its
    decisions. ``before`` is the baseline snapshot, ``after`` the fork snapshot
    (one is null for added/removed). ``fields`` names the changed content fields
    (plus ``"position"`` when a content change also moved).
    """

    change_id: uuid.UUID
    kind: str
    fork_node_id: uuid.UUID | None = None
    baseline_node_id: uuid.UUID | None = None
    fields: list[str] = Field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class ForkDiffResponse(BaseModel):
    """``timing`` (kind ``"timing"``, change_id = the fork itinerary id) is the
    trip-level divergence — the fork retimed or re-windowed against a trunk
    with its own timing; accepting it adopts the fork's block and re-resolves
    the trunk spine (world-pinned cards hold). Null when timing agrees or the
    trunk has no timing (that case folds unconditionally on reconcile)."""

    fork_id: uuid.UUID
    baseline_id: uuid.UUID
    added: list[NodeChangeResponse]
    removed: list[NodeChangeResponse]
    changed: list[NodeChangeResponse]
    moved: list[NodeChangeResponse]
    timing: NodeChangeResponse | None = None


class ReconcileDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: uuid.UUID
    accept: bool


class ApproveAllResponse(BaseModel):
    """Result of the bulk approve: how many nodes flipped + the fresh graph."""

    approved_count: int
    graph: GraphResponse


class ReconcileRequest(BaseModel):
    """Advisor per-change accept/discard verdicts, with the feasibility gate.

    ``analysis_id`` pins which Analyze run gates the pass (defaults to the fork's
    latest completed run); ``override_block`` is the advisor's explicit, logged
    escape hatch past a ``block`` finding. ``accept_all=True`` is the publish
    fast path: every change in the server-side diff is accepted (``decisions``
    is ignored — send ``[]``), with no staleness window between a fetched diff
    and the verdicts.
    """

    model_config = ConfigDict(extra="forbid")

    decisions: list[ReconcileDecisionPayload] = Field(default_factory=list)
    analysis_id: uuid.UUID | None = None
    override_block: bool = False
    accept_all: bool = False


class ReconcileOutcomeResponse(BaseModel):
    """What happened to one decided change: applied / discarded / refused_booked
    / failed / skipped (see ``services.fork.ReconcileOutcome``)."""

    change_id: uuid.UUID
    kind: str
    result: str
    detail: str | None = None


class ReconcileResponse(BaseModel):
    """The post-reconcile live baseline graph + the fork + per-change outcomes."""

    baseline: GraphResponse
    fork: ItineraryResponse
    outcomes: list[ReconcileOutcomeResponse]


class RequestReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


# ── Actor resolution ────────────────────────────────────────────────────────


def _actor_from_user(user: AuthenticatedUser) -> ActorContext:
    """Map a Supabase-authenticated user to an ActorContext.

    ``user.sub`` is a UUID string from Supabase Auth. We parse it here so a
    malformed sub surfaces as 401 at the middleware layer rather than a 500
    inside the service; if parsing fails the actor is still recorded but
    with ``user_id=None``.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except (ValueError, AttributeError):
        user_uuid = None
    return ActorContext(user_id=user_uuid, kind=ActorKind.USER, actor_id=user.sub)


def _advisor_actor_from_user(user: AuthenticatedUser) -> ActorContext:
    """Same as :func:`_actor_from_user` but stamps ``kind=ADVISOR``.

    Used from the lock / release / approve / assemble routes, which are
    already gated by ``require_advisor``. Writing AGENT-layer history rows
    from these handlers would be a lie — the caller is an advisor, and the
    service layer uses the actor kind to decide whether to bypass the lock
    gate.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except (ValueError, AttributeError):
        user_uuid = None
    return ActorContext(user_id=user_uuid, kind=ActorKind.ADVISOR, actor_id=user.sub)


async def _load_itinerary(session: AsyncSession, itinerary_id: uuid.UUID) -> Itinerary | None:
    """Load an itinerary row by id (or None). Extracted so the fork endpoint's
    authz pre-load can be monkeypatched by route-level tests that stub the DB."""
    return (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()


async def _resolve_client_auth_user_id(
    session: AsyncSession, client_id: uuid.UUID
) -> uuid.UUID | None:
    """Return the ``auth.users.id`` for the client, or None if missing.

    Extracted as a helper so the owner check on the draft-read gate can
    be monkey-patched by route-level tests that stub the DB session.
    """
    return (
        await session.execute(select(Client.auth_user_id).where(Client.id == client_id))
    ).scalar_one_or_none()


async def _resolve_viewer_open_fork_id(
    session: AsyncSession,
    user: AuthenticatedUser,
    *,
    baseline_id: uuid.UUID,
) -> uuid.UUID | None:
    """The caller's own OPEN fork of ``baseline_id`` (their "My version"), or None.

    A fork is stamped with ``created_by = actor.user_id`` (see ``fork_itinerary``),
    so the traveler's own working copy is the open fork they created off this
    baseline. Picks the most-recent so any pre-existing duplicate forks (from the
    old "Make an alternative" flow) still resolve to one entry; the lazy-fork model
    stops new duplicates being created.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        return None
    return (
        await session.execute(
            select(Itinerary.id)
            .where(
                Itinerary.forked_from_id == baseline_id,
                Itinerary.fork_status == ForkStatus.open,
                Itinerary.created_by == user_uuid,
            )
            .order_by(Itinerary.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _display_status_for(session: AsyncSession, itinerary_id: uuid.UUID) -> DisplayStatus:
    """Compute the derived display bucket for one itinerary (single scalar query)."""
    value = (
        await session.execute(
            select(display_status_expr()).select_from(Itinerary).where(Itinerary.id == itinerary_id)
        )
    ).scalar_one_or_none()
    return DisplayStatus(value) if value is not None else DisplayStatus.in_studio


async def _is_requester_advisor(session: AsyncSession, user_uuid: uuid.UUID | None) -> bool:
    """One-shot profile lookup used by the draft-read gate.

    Returns ``True`` iff ``user_uuid`` is non-null and the profiles row for
    that id carries ``role = 'advisor'``. Low-RPS by design — the itinerary
    read endpoint lives off the hot path, so a single SELECT per call is
    cheap next to the recursive graph CTE.
    """
    if user_uuid is None:
        return False
    row = (
        await session.execute(select(Profile.role).where(Profile.id == user_uuid))
    ).scalar_one_or_none()
    return row is UserRole.advisor


async def _resolve_actor(session: AsyncSession, user: AuthenticatedUser) -> ActorContext:
    """USER actor, promoted to ADVISOR when the caller's profile says so.

    Content mutations must run with the caller's real role: the trunk guard
    admits advisors (their escape hatch, and the reconcile path) while
    USER/AGENT actors are redirected to a fork — and history rows attribute
    the change to the right actor kind.
    """
    actor = _actor_from_user(user)
    try:
        is_advisor = await _is_requester_advisor(session, actor.user_id)
    except (SQLAlchemyError, AttributeError):
        # Fake-factory tests stub the session; a broken role probe degrades to
        # the non-advisor actor rather than failing the request outright.
        return actor
    if is_advisor:
        return _advisor_actor_from_user(user)
    return actor


async def assert_itinerary_readable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Read gate, shared by the graph-read and analyze endpoints.

    Topology-derived rules (the stored lifecycle is gone):

    - **Trunk** (``forked_from_id`` is None): the owning client, the creator,
      or an advisor may read. There is no "public once proposed" state any
      more — a trunk is private to its trip relationship.
    - **Fork**: the creator or an advisor only. A fork is a private working
      copy; the owning traveler does NOT see an advisor's in-flight fork
      (that privacy is what lets the advisor build before publishing), and
      vice versa staff see everything.

    Everyone else gets a 403 with ``detail='forbidden'`` so the SDK can
    discriminate deterministically. The agent acting on the client's behalf
    carries the client's JWT, so the owner branch admits it without a
    separate actor_kind check. ``itinerary`` must expose ``forked_from_id`` /
    ``client_id`` / ``created_by`` / ``id``.
    """
    actor = _actor_from_user(user)
    is_fork = itinerary.forked_from_id is not None
    is_creator = (
        actor.user_id is not None
        and itinerary.created_by is not None
        and actor.user_id == itinerary.created_by
    )
    if is_creator:
        return
    # ``is_owner`` compares the caller's auth.users id against the clients
    # row linked to this itinerary — clients.id and auth.users.id live in
    # different UUID namespaces, so resolve via clients.auth_user_id.
    if not is_fork and actor.user_id is not None and itinerary.client_id is not None:
        owning_auth_user_id = await _resolve_client_auth_user_id(session, itinerary.client_id)
        if owning_auth_user_id is not None and owning_auth_user_id == actor.user_id:
            return
    if await _is_requester_advisor(session, actor.user_id):
        return
    logger.info(
        "itinerary.read_denied",
        extra={
            "sub_hint": (user.sub or "")[:8],
            "itinerary_id": str(itinerary.id),
        },
    )
    raise HTTPException(status_code=403, detail="forbidden")


async def _has_write_relationship(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> bool:
    """True iff the caller may mutate (or fork) this itinerary.

    The write relationship is **owner** (the client's auth user, resolved via
    ``clients.auth_user_id`` since ``clients.id`` and ``auth.users.id`` live in
    different namespaces) **or creator** (``created_by`` — which is what
    readmits the agent to a concierge-created draft whose ``client_id`` is still
    null) **or advisor**. ``itinerary`` must expose ``client_id`` / ``created_by``.
    """
    actor = _actor_from_user(user)
    if actor.user_id is not None and itinerary.client_id is not None:
        owning_auth_user_id = await _resolve_client_auth_user_id(session, itinerary.client_id)
        if owning_auth_user_id is not None and owning_auth_user_id == actor.user_id:
            return True
    if (
        actor.user_id is not None
        and itinerary.created_by is not None
        and actor.user_id == itinerary.created_by
    ):
        return True
    return await _is_requester_advisor(session, actor.user_id)


async def assert_itinerary_forkable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Only the owning client, the creator, or an advisor may fork an itinerary.

    Stricter than the draft-read gate (which admits any authenticated user to an
    *approved* itinerary): a fork writes a brand-new itinerary onto the client, so
    we require a real relationship to the baseline regardless of its status. The
    agent acting for the client carries the client's JWT, so the owner branch
    admits it. 403 ``forbidden`` so the SDK discriminates deterministically.
    """
    if await _has_write_relationship(session, user, itinerary):
        return
    logger.info(
        "itinerary.fork_denied",
        extra={"sub_hint": (user.sub or "")[:8], "itinerary_id": str(itinerary.id)},
    )
    raise HTTPException(status_code=403, detail="forbidden")


async def assert_itinerary_writable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Gate node/edge writes: only the owner, creator, or an advisor may mutate.

    Closes the gap where any authenticated user holding an itinerary id could
    write to any unlocked, non-firmed graph. Shares the fork gate's relationship
    test (:func:`_has_write_relationship`), so the agent — carrying the client's
    JWT — is admitted as owner, or as creator on a concierge-created draft whose
    ``client_id`` is still null. 403 ``forbidden`` so the SDK discriminates
    deterministically.
    """
    if await _has_write_relationship(session, user, itinerary):
        return
    logger.info(
        "itinerary.write_denied",
        extra={"sub_hint": (user.sub or "")[:8], "itinerary_id": str(itinerary.id)},
    )
    raise HTTPException(status_code=403, detail="forbidden")


# ── Outcome mapping ────────────────────────────────────────────────────────


def _raise_for_error(err: ItineraryError) -> NoReturn:
    """Map an ItineraryError to the conventional HTTPException."""
    if err.outcome is ItineraryOutcome.NOT_FOUND:
        raise HTTPException(status_code=404, detail="not_found")
    if err.outcome is ItineraryOutcome.INVALID_PROVENANCE:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "invalid_provenance",
        )
    if err.outcome is ItineraryOutcome.INVALID_PARENT:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "invalid_parent",
        )
    if err.outcome is ItineraryOutcome.VALIDATION_ERROR:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "validation_error",
        )
    if err.outcome is ItineraryOutcome.FORBIDDEN:
        raise HTTPException(status_code=403, detail=err.detail or "forbidden")
    if err.outcome is ItineraryOutcome.LOCKED:
        raise HTTPException(status_code=409, detail=err.detail or "already_locked")
    if err.outcome is ItineraryOutcome.STATUS_LOCKED:
        # The node's lifecycle status forbids this mutation (G1). 409 like the
        # editor lock; the detail token (status_locked / demote_before_edit /
        # demote_before_delete) lets the agent + web craft the human reason.
        raise HTTPException(status_code=409, detail=err.detail or "status_locked")
    if err.outcome is ItineraryOutcome.TRUNK_LOCKED:
        # Content mutation on an official trunk by a non-advisor — the trunk is
        # written only via publish/reconcile. The ``fork_required`` detail tells
        # the client to fork (the web store lazy-forks on this signal).
        raise HTTPException(status_code=409, detail=err.detail or "fork_required")
    if err.outcome is ItineraryOutcome.CONFLICT:
        # A precondition on related state failed — e.g. the M005 money gate: a
        # node can't be flipped straight to booked/confirmed via update_node
        # (that authority is services.bookings). 409 so the caller can tell
        # "not allowed yet" from a 400; the detail token (use_booking_flow, …)
        # lets the agent + web craft the human reason.
        raise HTTPException(status_code=409, detail=err.detail or "conflict")
    # Defensive — every enum value is mapped above.
    logger.error("itinerary.router.unhandled_outcome", extra={"outcome": err.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")


# ── Node response builders ──────────────────────────────────────────────────


def _stamp_response(stamp: ResolvedStampView) -> ResolvedStampResponse:
    return ResolvedStampResponse(
        day_index=stamp.day_index,
        date=stamp.on,
        wall_time=stamp.wall_time.strftime("%H:%M"),
        tz=stamp.tz_name,
        instant=stamp.instant.isoformat() if stamp.instant is not None else None,
    )


def _schedule_response(
    view: ResolvedScheduleView | None, *, synthesized: bool = False
) -> ResolvedScheduleResponse | None:
    if view is None:
        return None
    kind: Literal["relative", "pinned"] = "pinned" if view.kind == "pinned" else "relative"
    return ResolvedScheduleResponse(
        kind=kind,
        start=_stamp_response(view.start),
        end=_stamp_response(view.end) if view.end is not None else None,
        day_span=view.day_span,
        synthesized=synthesized,
    )


def _node_response_from_out(n: Any) -> NodeResponse:
    """Build a NodeResponse from a service ``NodeOut`` (graph-read shape).

    ``NodeOut`` already carries the serialized ``starts_at`` / cost / resolved
    schedule fields, so this is a straight field copy. Used by the graph-read
    + assemble endpoints.
    """
    return NodeResponse(
        id=n.id,
        itinerary_id=n.itinerary_id,
        parent_subgraph_id=n.parent_subgraph_id,
        type=n.type,
        status=n.status,
        title=n.title,
        source=n.source,
        source_id=n.source_id,
        metadata=n.metadata,
        cost_amount=n.cost_amount,
        cost_currency=n.cost_currency,
        cost_kind=n.cost_kind,
        starts_at=n.starts_at,
        duration_minutes=n.duration_minutes,
        depth=n.depth,
        lock_reason=n.lock_reason,
        forked_from_node_id=n.forked_from_node_id,
        attached_to_node_id=n.attached_to_node_id,
        schedulable=is_schedulable(n.type),
        needs_revalidation=bool(getattr(n, "needs_revalidation", False) or False),
        schedule=_schedule_response(
            getattr(n, "schedule", None),
            synthesized=bool(getattr(n, "schedule_synthesized", False)),
        ),
    )


def _node_response_from_node(node: Any, anchor: date | None = None) -> NodeResponse:
    """Build a NodeResponse from a persisted ``Node`` ORM row (write shape).

    The single-node write endpoints (create / update / from-inventory) return
    a ``Node`` whose ``starts_at`` is still a raw tstzrange, so it's serialized
    here with the node's recorded local offset. ``anchor`` (the itinerary's
    Day-1 date) lets the resolved schedule view carry dates/instants for
    relative schedules; callers fetch it via :func:`_anchor_date_of`.
    """
    starts_at, duration_minutes = _serialize_starts_at(
        node.starts_at, _tz_offset_from_metadata(node.metadata_)
    )
    decoded = decoded_schedule(node)
    return NodeResponse(
        id=node.id,
        itinerary_id=node.itinerary_id,
        parent_subgraph_id=node.parent_subgraph_id,
        type=node.type,
        status=node.status,
        title=node.title,
        source=node.source,
        source_id=node.source_id,
        metadata=node.metadata_,
        cost_amount=node.cost_amount,
        cost_currency=node.cost_currency,
        cost_kind=node.cost_kind,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        lock_reason=compute_lock_reason(node.status),
        forked_from_node_id=getattr(node, "forked_from_node_id", None),
        attached_to_node_id=getattr(node, "attached_to_node_id", None),
        schedulable=is_schedulable(node.type),
        needs_revalidation=bool(getattr(node, "needs_revalidation", False) or False),
        schedule=_schedule_response(resolve_view(decoded, anchor) if decoded is not None else None),
    )


def _kernel_read_for_view(
    view: Any,
) -> tuple[list[GraphFindingResponse], list[NightLodgingResponse]]:
    """Run the kernel read surfaces (feasibility findings + nightly lodging)
    over a served graph view.

    Never raises past this boundary: a kernel-read bug must not take down the
    graph read — both surfaces degrade to empty instead.
    """
    try:
        graph = kernel_graph_from_view(view)
        findings = analyze(graph)
        nights = nightly_lodging(graph)
    except Exception:  # noqa: BLE001 — advisory surface, never fatal
        logger.warning("itinerary.kernel_read_failed", exc_info=True)
        return [], []
    out: list[GraphFindingResponse] = []
    for f in findings:
        severity: Literal["block", "warn", "info"] = (
            "block" if f.severity == "block" else "info" if f.severity == "info" else "warn"
        )
        out.append(
            GraphFindingResponse(
                code=f.code,
                severity=severity,
                message=f.message,
                node_ids=[uuid.UUID(nid) for nid in f.node_ids],
            )
        )
    lodging = [
        NightLodgingResponse(day_index=n.day_index, on=n.on, node_id=uuid.UUID(n.node_id))
        for n in nights
    ]
    return out, lodging


async def _anchor_date_of(session: AsyncSession, itinerary_id: uuid.UUID) -> date | None:
    """The itinerary's kernel Day-1 anchor, for write-path serialization.

    Degrades to None on a stubbed session (router tests replace the service
    layer and hand the endpoint an inert session object) — the anchor only
    enriches the resolved schedule view, it never gates the write.
    """
    if not hasattr(session, "scalar"):
        return None
    return await session.scalar(select(Itinerary.anchor_date).where(Itinerary.id == itinerary_id))


def _graph_to_response(
    view: Any, *, totals: dict[str, str] | None = None, party_size: int = 1
) -> GraphResponse:
    """Assemble a GraphResponse from a service GraphView (itinerary + nodes + edges).

    Shared by the graph-read and fork endpoints so fork lineage (on the itinerary
    and every node) serializes identically everywhere. ``totals`` (per-currency
    price) and ``party_size`` are supplied only by the graph-read endpoint;
    fork/reconcile omit them (party_size defaults to 1).
    """
    return GraphResponse(
        itinerary=_itinerary_to_response(view.itinerary),
        nodes=[_node_response_from_out(n) for n in view.nodes],
        edges=[
            EdgeResponse(
                id=e.id,
                itinerary_id=e.itinerary_id,
                from_node_id=e.from_node_id,
                to_node_id=e.to_node_id,
                type=e.type,
                metadata=e.metadata,
            )
            for e in view.edges
        ],
        totals=totals or {},
        party_size=party_size,
    )


def _node_change_response(change: NodeChange) -> NodeChangeResponse:
    return NodeChangeResponse(
        change_id=change.change_id,
        kind=change.kind,
        fork_node_id=change.fork_node_id,
        baseline_node_id=change.baseline_node_id,
        fields=list(change.fields),
        before=change.before,
        after=change.after,
    )


def _fork_diff_response(diff: ForkDiff) -> ForkDiffResponse:
    return ForkDiffResponse(
        fork_id=diff.fork_id,
        baseline_id=diff.baseline_id,
        added=[_node_change_response(c) for c in diff.added],
        removed=[_node_change_response(c) for c in diff.removed],
        changed=[_node_change_response(c) for c in diff.changed],
        moved=[_node_change_response(c) for c in diff.moved],
        timing=_node_change_response(diff.timing) if diff.timing is not None else None,
    )


def _reconcile_response(result: ReconcileResult, baseline_view: Any) -> ReconcileResponse:
    return ReconcileResponse(
        baseline=_graph_to_response(baseline_view),
        fork=_itinerary_to_response(result.fork),
        outcomes=[
            ReconcileOutcomeResponse(
                change_id=o.change_id, kind=o.kind, result=o.result, detail=o.detail
            )
            for o in result.outcomes
        ],
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ItineraryResponse,
    summary="Create a new itinerary graph.",
)
async def create_itinerary_endpoint(
    payload: CreateItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    actor = _actor_from_user(user)
    itinerary = await create_itinerary(
        session,
        actor,
        title=payload.title,
        client_id=payload.client_id,
        brief=payload.brief,
        timing_kind=payload.timing_kind,
        date_start=payload.date_start,
        date_end=payload.date_end,
        duration_nights=payload.duration_nights,
        timing_note=payload.timing_note,
    )
    return _itinerary_to_response(itinerary)


_CENTS = Decimal("0.01")


async def _apply_display_currency(
    session: AsyncSession,
    *,
    client_id: uuid.UUID | None,
    response: GraphResponse,
) -> None:
    """Convert totals + node costs into the client's preferred currency (0048).

    Read-side, best-effort: when the itinerary's client has a
    ``preferred_currency`` and the FX service resolves rates, we fill
    ``display_currency`` + ``total_display`` and each priced node's
    ``cost_display_*``. Anything that can't be resolved is left None so the UI
    falls back to native amounts — the plan's native ``totals`` are untouched.
    """
    if client_id is None:
        return
    # Cheap gate first: with no FX key there's nothing to convert, so skip the
    # extra client query entirely (also spares session-stubbing callers).
    fx = get_fx_service()
    if not fx.enabled:
        return
    target = (
        await session.execute(select(Client.preferred_currency).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not target:
        return
    response.display_currency = target

    # Whole-plan total: convert every native currency bucket and sum. If any
    # bucket can't be converted, leave total_display None rather than under-count.
    grand = Decimal(0)
    ok = bool(response.totals)
    for currency, amount in response.totals.items():
        converted = await fx.convert(Decimal(amount), currency, target)
        if converted is None:
            ok = False
            break
        grand += converted
    if ok:
        response.total_display = str(grand.quantize(_CENTS))

    # Per-node display conversion (including sibling ``additional_nodes``).
    async def _convert_node(node: NodeResponse) -> None:
        if node.cost_amount is not None and node.cost_currency:
            converted = await fx.convert(node.cost_amount, node.cost_currency, target)
            if converted is not None:
                node.cost_display_amount = converted.quantize(_CENTS)
                node.cost_display_currency = target
        for child in node.additional_nodes:
            await _convert_node(child)

    for node in response.nodes:
        await _convert_node(node)


@router.get(
    "/{itinerary_id}",
    response_model=GraphResponse,
    summary="Get the assembled itinerary graph.",
)
async def get_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    result = await get_itinerary_graph(session, itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    # Read gate (shared with the analyze endpoints).
    await assert_itinerary_readable(session, user, result.itinerary)
    # mypy: result is GraphView past this point
    # Surface the plan's per-currency price (ADV-10) so the UI can show a total
    # alongside the one-action approve. Decimal → str to match cost_amount.
    totals = {c: str(a) for c, a in (await sum_node_costs(session, itinerary_id)).items()}
    party_size = await resolve_party_size(session, itinerary_id)
    response = _graph_to_response(result, totals=totals, party_size=party_size)
    # Kernel read surfaces: feasibility findings (never rejections — the UI
    # badges the cards, the advisor decides) and nightly lodging coverage.
    response.findings, response.nightly_lodging = _kernel_read_for_view(result)
    # Convert totals + node costs into the client's preferred currency (0048).
    await _apply_display_currency(session, client_id=result.itinerary.client_id, response=response)
    response.itinerary.display_status = await _display_status_for(session, itinerary_id)
    # On a baseline, surface the caller's own OPEN fork so the traveler's
    # two-version toggle ("My version") resolves to it rather than re-forking.
    if result.itinerary.forked_from_id is None:
        response.viewer_open_fork_id = await _resolve_viewer_open_fork_id(
            session, user, baseline_id=itinerary_id
        )
    return response


@router.get(
    "/{itinerary_id}/collection",
    response_model=CollectionResponse,
    summary="Get the itinerary's Collection (unscheduled, non-discarded nodes).",
)
async def get_collection_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    """The wish list: nodes with no ``starts_at`` that aren't discarded.

    Reuses the same assembled graph read (and its draft-read gate) as
    ``GET /itinerary/{id}`` and filters, so the Collection can never drift from
    the graph it's a view of.
    """
    result = await get_itinerary_graph(session, itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    await assert_itinerary_readable(session, user, result.itinerary)
    items = [
        _node_response_from_out(n)
        for n in result.nodes
        if n.starts_at is None and n.status is not NodeStatus.discarded
    ]
    return CollectionResponse(itinerary_id=itinerary_id, items=items)


@router.patch(
    "/{itinerary_id}",
    response_model=ItineraryResponse,
    summary="Update an itinerary's title, brief, and timing.",
)
async def update_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: UpdateItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Set the first-class trip brief + timing (0033).

    Trip-level metadata edit, gated by the same owner/creator/advisor test as
    node writes — so the owning traveler can articulate the goal on a draft they
    started, while the backend advisor guards stay the authority over the graph
    itself. Partial: only fields present in the payload are applied.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    result = await update_itinerary_details(
        session, actor, itinerary, fields=payload.model_dump(exclude_unset=True)
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/retime",
    response_model=RetimeItineraryResponse,
    summary="Pin the trip to real dates — shifts every scheduled card with Day 1.",
)
async def retime_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: RetimeItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> RetimeItineraryResponse:
    """The Wave E (ADV-17) pinning gesture: "Day 1 is March 18, 2027".

    Shifts every scheduled node by ``date_start − days_anchor`` days (wall-clock
    + tz offset preserved, node_history written) and flips the itinerary to
    ``timing_kind=exact`` with ``days_anchor = date_start``. Symmetric with the
    PATCH loosen path (exact → window/flexible keeps the anchor and moves
    nothing), so fuzzy → pinned → fuzzy → re-pinned round-trips cleanly. Gated
    like the timing PATCH (owner/creator/advisor); 409 ``booked_dates_locked``
    when a non-zero shift would move booked/confirmed cards.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)
    result = await retime_itinerary(
        session,
        actor,
        itinerary,
        date_start=payload.date_start,
        date_end=payload.date_end,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return RetimeItineraryResponse(
        itinerary=_itinerary_to_response(result.itinerary),
        delta_days=result.delta_days,
        shifted_nodes=len(result.shifted_node_ids),
        held_node_ids=list(result.held_node_ids),
        stale_node_ids=list(result.stale_node_ids),
    )


@router.post(
    "/{itinerary_id}/nodes",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Insert a node into an itinerary graph.",
)
async def create_node_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)
    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=payload.type,
        status=payload.status,
        title=payload.title,
        parent_subgraph_id=payload.parent_subgraph_id,
        source=payload.source,
        source_id=payload.source_id,
        metadata=payload.metadata,
        cost_amount=payload.cost_amount,
        cost_currency=payload.cost_currency,
        cost_kind=payload.cost_kind,
        attached_to_node_id=payload.attached_to_node_id,
        starts_at=payload.starts_at,
        duration_minutes=payload.duration_minutes,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result, await _anchor_date_of(session, itinerary_id))


async def _create_flight_leg_nodes(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    item: FlightItem,
    node_type: NodeType,
    status: NodeStatus,
    parent_subgraph_id: uuid.UUID | None,
    cost: NodeCost | None,
) -> list[Any]:
    """Materialize each slice of a multi-slice flight offer as its own node.

    One node per leg (outbound, return, …), each carrying its own leg-scoped
    ``FlightCardAttrs`` (route, cabin, depart/arrive) and schedule. All legs
    share the offer's ``source_id`` — a round-trip is booked as one offer — and
    the whole-ticket fare is attached only to the outbound so summing node costs
    doesn't count the ticket twice. Returns the created nodes in slice order
    (outbound first); the caller promotes the tail into ``additional_nodes``.
    """
    created: list[Any] = []
    for i in range(flight_slice_count(item)):
        attrs = flight_item_to_card_attrs(item, slice_index=i)
        leg_metadata = attrs.model_dump(mode="json", exclude_none=True)
        start_iso, duration_minutes = scheduled_start_for_item(item, leg_metadata)
        leg_title = (
            f"{attrs.iata_from} → {attrs.iata_to}"
            if attrs.iata_from and attrs.iata_to
            else item.title
        )
        leg_cost = cost if i == 0 else None
        leg = await add_node(
            session,
            actor,
            itinerary_id=itinerary_id,
            type=node_type,
            status=status,
            title=leg_title,
            parent_subgraph_id=parent_subgraph_id,
            source=item.source,
            source_id=item.source_id,
            metadata=leg_metadata,
            starts_at=start_iso,
            duration_minutes=duration_minutes,
            cost_amount=leg_cost.amount if leg_cost else None,
            cost_currency=leg_cost.currency if leg_cost else None,
            cost_kind=leg_cost.kind if leg_cost else None,
        )
        if isinstance(leg, ItineraryError):
            _raise_for_error(leg)
        created.append(leg)
    return created


@router.post(
    "/{itinerary_id}/nodes/from-inventory",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Create a node from a live inventory item (typed card metadata).",
)
async def create_node_from_inventory_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeFromInventoryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> NodeResponse:
    """Fetch the item, derive its card metadata, and add it as a node.

    The provider lookup is the single source of card semantics: a Duffel
    flight becomes a ``flight`` node carrying ``FlightCardAttrs`` (cabin /
    seat / depart-arrive), a Ratehawk stay a ``hotel`` node, etc. Goes
    through the same ``add_node`` write path as a hand-built node, so the
    lock/queue + history invariants are unchanged.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)
    ctx = InventoryCtx(actor_kind="user", actor_id=user.sub)
    try:
        item = await get_inventory_detail(
            registry, source=payload.source, source_id=payload.source_id, ctx=ctx
        )
    except UnknownSourceError as exc:
        logger.info("itinerary.from_inventory.unknown_source", extra={"source": exc.source})
        raise HTTPException(status_code=400, detail="unknown_source") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="inventory_not_found")

    # ``InventoryItem.kind`` is a 1:1 subset of NodeType (flight, hotel, meal,
    # experience, destination, transit, note); guard so an unmapped kind is a
    # clean 422 rather than a 500 deep in add_node.
    try:
        node_type = NodeType(item.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unmappable_inventory_kind") from exc

    metadata = inventory_item_to_card_metadata(item)
    # Timed inventory (a flight's ``depart_at``) lands ON the timeline rather
    # than the Collection, so a booked-time item is immediately visible in the
    # journal instead of a silent wish-list add. Untimed kinds return
    # ``(None, None)`` and stay unscheduled — the wish-list default.
    start_iso, duration_minutes = scheduled_start_for_item(item, metadata)
    # Promote the provider's price to first-class cost columns (B4 / D-COST):
    # a Duffel flight or Ratehawk hotel lands with a queryable numeric cost,
    # not just a snapshot string. ``None`` for a price-less item (e.g. a
    # Google-Places meal) — the node simply carries no cost.
    cost = cost_from_inventory_item(item)

    # Round-trip (multi-slice) flight offer → one node per leg. A single Duffel
    # offer is atomically bookable but carries an outbound AND a return slice; the
    # graph must show each as its own node (own route/times/schedule), else the
    # card collapses to origin→origin. Legs share the offer's source_id (booking
    # is atomic) and the whole-ticket fare rides only the outbound to avoid
    # double-counting trip totals.
    if isinstance(item, FlightItem) and flight_slice_count(item) > 1:
        legs = await _create_flight_leg_nodes(
            session,
            actor,
            itinerary_id=itinerary_id,
            item=item,
            node_type=node_type,
            status=payload.status,
            parent_subgraph_id=payload.parent_subgraph_id,
            cost=cost,
        )
        primary, *rest = legs
        anchor = await _anchor_date_of(session, itinerary_id)
        response = _node_response_from_node(primary, anchor)
        response.additional_nodes = [_node_response_from_node(n, anchor) for n in rest]
        return response

    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=node_type,
        status=payload.status,
        title=item.title,
        parent_subgraph_id=payload.parent_subgraph_id,
        source=item.source,
        source_id=item.source_id,
        metadata=metadata,
        starts_at=start_iso,
        duration_minutes=duration_minutes,
        cost_amount=cost.amount if cost else None,
        cost_currency=cost.currency if cost else None,
        cost_kind=cost.kind if cost else None,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)

    # PRD "subgraphs for self-contained experiences": a multi-day item's
    # internal journey becomes child nodes under this one. Top-level nodes
    # only — no nested materialization inside an existing subgraph.
    if (
        payload.expand_days
        and payload.parent_subgraph_id is None
        and isinstance(item, ExperienceItem)
        and item.itinerary_days
    ):
        try:
            await materialize_day_subgraph(
                session,
                actor,
                itinerary_id=itinerary_id,
                parent_node_id=result.id,
                days=item.itinerary_days,
                status=payload.status,
            )
        except SubgraphMaterializeError as exc:
            _raise_for_error(exc.error)

    return _node_response_from_node(result, await _anchor_date_of(session, itinerary_id))


@router.post(
    "/{itinerary_id}/nodes/from-link",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Save a pasted web link into the Collection (OpenGraph card).",
)
async def create_node_from_link_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeFromLinkRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    """Fetch the link's OpenGraph preview and add it as an unscheduled node.

    Goes through the same ``add_node`` write path (lock/queue + history
    invariants unchanged) as any other node. ``source="web"`` / ``source_id=url``
    satisfies the provenance CHECK and marks the card as a pasted link; the
    preview lands in ``metadata.snapshot`` so the existing snapshot-reading cards
    render it. The user's optional ``note`` is kept alongside the snapshot.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)

    preview = await fetch_link_preview(payload.url)
    metadata: dict[str, Any] = {"snapshot": preview.to_snapshot()}
    if payload.note:
        metadata["note"] = payload.note
    # An article card is the reading-list case: carry the canonical url + a
    # publication derived from the host so the card reads as a real read, not a
    # bare link. The OpenGraph title/image/description already live in snapshot.
    if payload.kind is NodeType.article:
        metadata["url"] = preview.url
        metadata["publication"] = _publication_from_url(preview.url)

    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=payload.kind,
        status=payload.status,
        title=preview.title,
        parent_subgraph_id=payload.parent_subgraph_id,
        source="web",
        source_id=preview.url,
        metadata=metadata,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result, await _anchor_date_of(session, itinerary_id))


#: Known editorial hosts → display publication name (reading-list cards).
_PUBLICATION_BY_HOST: dict[str, str] = {
    "outsideonline.com": "Outside",
    "climbing.com": "Climbing",
    "backpacker.com": "Backpacker",
}


def _publication_from_url(url: str) -> str | None:
    """Derive a human publication name from a URL's host (``www.`` stripped).

    Known editorial hosts map to a curated name; anything else falls back to the
    bare registrable host so the card still credits a source.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    return _PUBLICATION_BY_HOST.get(host, host)


class CreateNodeFromRouteRequest(BaseModel):
    """Compute a real route (Google Routes) and persist it as a transfer card."""

    model_config = ConfigDict(extra="forbid")

    origin: str
    destination: str
    mode: Literal["drive", "walk", "bicycle", "transit"] = "drive"
    waypoints: list[str] = Field(default_factory=list)
    party_size: int = Field(default=1, ge=1)
    service_class: Literal["chauffeur_black", "first_class", "standard_taxi"] = "chauffeur_black"
    starts_at: str | None = None


@router.post(
    "/{itinerary_id}/nodes/from-route",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Compute a real route and save it as a tier-aware transfer card.",
)
async def create_node_from_route_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeFromRouteRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    """Persist a ground transfer whose geometry comes from a live routing engine.

    Unlike ``present_route`` (a drawer surface, no graph write), this computes
    the route server-side (the Google key stays on the backend) and lands a
    schedulable ``drive`` card in the Collection carrying the real duration /
    distance / polyline plus the chosen service tier + a coarse price estimate.
    Because the numbers are real, the card survives a live "make it a taxi"
    change — only the trim flexes.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)

    client = httpx.AsyncClient(timeout=10.0)
    try:
        route = await compute_route(
            origin=payload.origin,
            destination=payload.destination,
            waypoints=payload.waypoints,
            mode=payload.mode,
            settings=get_settings(),
            client=client,
        )
    except RoutePlanError as exc:
        if exc.reason == "route_not_found":
            raise HTTPException(status_code=404, detail="route_not_found") from exc
        raise HTTPException(status_code=502, detail=exc.reason) from exc
    finally:
        await client.aclose()

    title, attrs, price = build_transfer_card(
        route=route, service_class=payload.service_class, party_size=payload.party_size
    )
    # The route's real drive time spans the card on the timeline; a caller-supplied
    # ``starts_at`` lands it ON the plan (an airport pickup, a driver between two
    # cards) instead of dateless in the Collection. Duration rides even when
    # unscheduled, so the card carries its true length wherever it's placed later.
    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=NodeType.drive,
        title=title,
        source="route",
        source_id=f"{payload.origin}→{payload.destination}:{payload.mode}:{payload.service_class}",
        metadata=attrs.model_dump(mode="json", exclude_none=True),
        starts_at=payload.starts_at,
        duration_minutes=attrs.eta_minutes,
        cost_amount=price,
        cost_currency="EUR",
        cost_kind=CostKind.total,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result, await _anchor_date_of(session, itinerary_id))


def _itinerary_requested_nights(itinerary: Itinerary) -> int | None:
    """The traveler's chosen trip length in nights, or None if not yet settled.

    Prefers an explicit ``duration_nights`` (a window intake), else derives it
    from a pinned ``date_start``/``date_end`` span (an exact intake).
    """
    nights = getattr(itinerary, "duration_nights", None)
    if isinstance(nights, int) and nights > 0:
        return nights
    start = getattr(itinerary, "date_start", None)
    end = getattr(itinerary, "date_end", None)
    if start is not None and end is not None:
        span = (end - start).days
        return span if span > 0 else None
    return None


def _template_tz(template: CardTemplate) -> timezone:
    """The zone a template's offsets were authored in, from ``trip_anchor_iso``.

    Template offsets are wall-clock minutes from the fixture's ``TRIP_ANCHOR``
    (midnight in the trip's local zone), so instantiation must anchor at local
    midnight in that SAME zone — a UTC-midnight anchor lands every card late by
    the trip's UTC offset (an Olympus card authored 15:00 EEST persisted as
    15:00 UTC and displayed 18:00). Falls back to UTC for templates that don't
    record an anchor.
    """
    metadata = template.metadata_ if isinstance(template.metadata_, dict) else {}
    raw = metadata.get("trip_anchor_iso")
    if isinstance(raw, str):
        try:
            offset = datetime.fromisoformat(raw).utcoffset()
        except ValueError:
            offset = None
        if offset is not None:
            return timezone(offset)
    return UTC


def _itinerary_trip_start(itinerary: Itinerary, tz: timezone) -> datetime:
    """Anchor datetime the spine offsets from — the itinerary's ``date_start`` at
    midnight in ``tz`` (the template's authoring zone, see :func:`_template_tz`),
    or ~30 days out if the trip has no dates yet. The no-dates fallback is only a
    provisional ``days_anchor`` (the spine instantiates UNPINNED then); it never
    becomes the trip's dates.
    """
    start = getattr(itinerary, "date_start", None)
    if start is not None:
        return datetime(start.year, start.month, start.day, tzinfo=tz)
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=tz) + timedelta(days=30)


class CampaignKickoffResponse(BaseModel):
    """Result of instantiating the length-snapped campaign spine onto a fork."""

    itinerary_id: uuid.UUID
    campaign_id: str
    requested_nights: int | None
    snapped_length: int
    # Human sentence explaining a length snap ("Olympus really wants at least 5
    # days…"), or empty when the chosen dates matched a shipped length. The agent
    # narrates this verbatim-ish to the traveler.
    reason: str
    node_count: int
    edge_count: int
    # The freshly-instantiated spine nodes, placement-ready (each carries a
    # ``metadata.start_time`` so the canvas can lay it out immediately). The
    # agent turn fans these out as ``node_created`` frames so the scaffold
    # streams onto the dashboard live instead of only after a reload. Ordered by
    # start so a staggered reveal reads chronologically. Empty on the idempotent
    # no-op (the spine was already there).
    created_nodes: list[NodeResponse] = Field(default_factory=list)


def _placement_ready_node(node: Any, anchor: date | None = None) -> NodeResponse:
    """Serialize a persisted spine node so it's ready to drop on the canvas.

    ``_node_response_from_node`` gives the row's ``starts_at`` as a top-level
    ISO field, but the client's timeline gates placement on
    ``metadata.start_time`` (``isNodeScheduled``). The initial graph seed runs
    through an adapter that stamps it; a ``node_created`` frame bypasses that
    adapter, so mirror the invariant here — copy ``starts_at`` into
    ``metadata.start_time`` (+ duration) when the node is scheduled.
    """
    resp = _node_response_from_node(node, anchor)
    if resp.starts_at and not resp.metadata.get("start_time"):
        meta = {**resp.metadata, "start_time": resp.starts_at}
        if resp.duration_minutes is not None and meta.get("duration_minutes") is None:
            meta["duration_minutes"] = resp.duration_minutes
        resp.metadata = meta
    return resp


@router.post(
    "/{itinerary_id}/campaign/kickoff",
    response_model=CampaignKickoffResponse,
    summary="Instantiate the length-snapped campaign spine onto the traveler's fork.",
)
async def campaign_kickoff_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CampaignKickoffResponse:
    """Drop the right-sized campaign spine onto a campaign itinerary.

    Called once, from the dashboard auto-kickoff, after intake has settled the
    dates. Reads the itinerary's ``campaign_id``, snaps the chosen nights to the
    nearest shipped spine length, and clones that template onto THIS itinerary
    (the traveler's fork) via ``instantiate_into``. Deterministic — the LLM
    narrates the returned ``reason``, it doesn't pick the number.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)

    campaign_id = getattr(itinerary, "campaign_id", None)
    if not campaign_id:
        raise HTTPException(status_code=409, detail="not_a_campaign_itinerary")
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=409, detail="unknown_campaign")

    requested_nights = _itinerary_requested_nights(itinerary)
    snapped, reason = snap_length(requested_nights, campaign.supported_lengths)

    # Idempotent: the spine is laid down once. If this itinerary already has any
    # nodes, a re-fire (double dashboard mount, retry) must NOT stack a second
    # skeleton — return the no-op shape so the agent narrates without rebuilding.
    existing = (
        await session.execute(select(Node.id).where(Node.itinerary_id == itinerary_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return CampaignKickoffResponse(
            itinerary_id=itinerary.id,
            campaign_id=campaign.id,
            requested_nights=requested_nights,
            snapped_length=snapped,
            reason="",
            node_count=0,
            edge_count=0,
        )

    # Build (idempotent) + resolve the length-matched spine template. Only the
    # Olympus campaign ships spines today; dispatch by id keeps the seam clean.
    if campaign.id == "olympus":
        template = await build_olympus_template(session, nights=snapped)
    else:  # pragma: no cover - guarded by the registry today
        raise HTTPException(status_code=409, detail="campaign_has_no_spine")

    # Intake settled no length at all → we're laying down the length-snapped
    # DEFAULT spine (Olympus: the full 14 nights). Persist that length onto the
    # itinerary so the trip brief carries it and the agent stops re-asking "how
    # many days?" on the next turn. Guarded on ``requested_nights is None``: an
    # explicit duration or pinned exact dates already imply the length via
    # ``_itinerary_requested_nights``, so we don't clobber a real choice (nor a
    # date span, which could disagree with the snapped length).
    if requested_nights is None:
        itinerary.duration_nights = snapped

    trip_start_at = _itinerary_trip_start(itinerary, _template_tz(template))
    # Pin the trip only when the traveler actually chose exact dates. A
    # flexible/window intake (or no intake) lays the spine out as stable
    # "Day N" slots off a provisional days_anchor — the kickoff must not
    # invent calendar dates the traveler never gave.
    pin = itinerary.timing_kind == ItineraryTimingKind.exact and itinerary.date_start is not None
    # Only the edge count is taken from the spine clone; the node total is
    # recomputed below to include the reading-list reads seeded next.
    _, edge_count = await instantiate_into(
        session, template=template, itinerary=itinerary, trip_start_at=trip_start_at, pin=pin
    )

    # Stock the reading list in the same deterministic breath as the spine: the
    # campaign's curated reads land as unscheduled ``article`` nodes on this
    # itinerary, so the concierge's opener can greet them as chips (and the
    # Reading destination shows a stocked rack) without gating on the model
    # calling ``suggest_reading``. They ride the ``created_nodes`` reveal below.
    if campaign.reading_list:
        actor = await _resolve_actor(session, user)
        await seed_campaign_reading_list(
            session, actor, itinerary_id=itinerary.id, seeds=campaign.reading_list
        )

    # Return the freshly-created nodes so the agent turn can stream them onto the
    # canvas live (as ``node_created`` frames). The itinerary was empty before
    # this call (guarded above), so every node here was created by this kickoff —
    # the scheduled spine plus the unscheduled reading-list reads. Order by start
    # so the staggered reveal reads front-to-back (the unscheduled reads last).
    created_rows = (
        (await session.execute(select(Node).where(Node.itinerary_id == itinerary_id)))
        .scalars()
        .all()
    )
    kickoff_anchor = await _anchor_date_of(session, itinerary_id)
    created_nodes = sorted(
        (_placement_ready_node(n, kickoff_anchor) for n in created_rows),
        key=lambda n: (n.starts_at is None, n.starts_at or ""),
    )

    return CampaignKickoffResponse(
        itinerary_id=itinerary.id,
        campaign_id=campaign.id,
        requested_nights=requested_nights,
        snapped_length=snapped,
        reason=reason,
        # Everything the kickoff laid down — spine + reading list — so callers
        # can reconcile against ``created_nodes`` (``instantiate_into`` alone
        # counts only the spine it cloned).
        node_count=len(created_nodes),
        edge_count=edge_count,
        created_nodes=created_nodes,
    )


@router.patch(
    "/{itinerary_id}/nodes/{node_id}",
    response_model=NodeResponse,
    summary="Update a node (partial).",
)
async def update_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: UpdateNodeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    # Resolve actor kind so the status gate (G1) can tell an advisor (who may
    # demote/cancel a firmed node) from a traveler/agent (who cannot). The
    # agent carries the client's JWT, so it resolves to USER like a traveler.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    # Only forward fields the client actually set so "omitted" ≠ "set to None".
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("schedule", None)  # forwarded as a typed placement below, not a raw dict
    placement: SchedulePlacement | None = None
    clear_schedule = False
    if payload.schedule is not None:
        sched = payload.schedule
        if sched.clear:
            if sched.day_index is not None or sched.minute_of_day is not None:
                raise HTTPException(
                    status_code=422, detail="schedule.clear permits no other placement field"
                )
            clear_schedule = True
        else:
            if sched.day_index is None or sched.minute_of_day is None:
                raise HTTPException(
                    status_code=422,
                    detail="schedule placement needs day_index and minute_of_day",
                )
            placement = SchedulePlacement(
                day_index=sched.day_index,
                minute_of_day=sched.minute_of_day,
                duration_minutes=sched.duration_minutes,
                tz_name=sched.tz,
            )
    result = await update_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        placement=placement,
        clear_schedule=clear_schedule,
        **fields,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result, await _anchor_date_of(session, itinerary_id))


@router.delete(
    "/{itinerary_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a node.",
)
async def delete_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    # See update_node_endpoint: advisor resolution drives the G1 status gate.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    err = await delete_node(session, actor, itinerary_id=itinerary_id, node_id=node_id)
    if err is not None:
        _raise_for_error(err)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _itinerary_to_response(
    itinerary: Any, *, display_status: DisplayStatus | None = None
) -> ItineraryResponse:
    return ItineraryResponse(
        id=itinerary.id,
        title=itinerary.title,
        client_id=itinerary.client_id,
        created_by=itinerary.created_by,
        display_status=display_status,
        forked_from_id=getattr(itinerary, "forked_from_id", None),
        fork_status=getattr(itinerary, "fork_status", None),
        reconcile_requested_at=getattr(itinerary, "reconcile_requested_at", None),
        reconcile_request_note=getattr(itinerary, "reconcile_request_note", None),
        brief=getattr(itinerary, "brief", None),
        timing_kind=getattr(itinerary, "timing_kind", None),
        date_start=getattr(itinerary, "date_start", None),
        date_end=getattr(itinerary, "date_end", None),
        duration_nights=getattr(itinerary, "duration_nights", None),
        timing_note=getattr(itinerary, "timing_note", None),
        days_anchor=getattr(itinerary, "days_anchor", None),
        anchor_date=getattr(itinerary, "anchor_date", None),
        campaign_id=getattr(itinerary, "campaign_id", None),
        mood=getattr(itinerary, "mood", None),
        hero_image=getattr(itinerary, "hero_image", None),
    )


@router.post(
    "/{itinerary_id}/lock",
    response_model=ItineraryResponse,
    summary="Acquire the advisor editor lock on an itinerary.",
)
async def lock_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    actor = _advisor_actor_from_user(user)
    result = await acquire_lock(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/release",
    response_model=ReleaseLockResponse,
    summary="Release the advisor editor lock and drain the agent write queue.",
)
async def release_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ReleaseLockResponse:
    actor = _advisor_actor_from_user(user)
    result = await release_lock(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    # Drain happens after the lock row has been cleared. The agent queue
    # lives in-process (D008), so we grab the same sessionmaker the request
    # uses; each queued entry opens a fresh session for its replay.
    replayed = await drain_queue(get_sessionmaker(), itinerary_id)
    return ReleaseLockResponse(
        itinerary=_itinerary_to_response(result),
        replayed_count=replayed,
    )


@router.post(
    "/{itinerary_id}/nodes/approve-all",
    response_model=ApproveAllResponse,
    summary="Approve every pending approvable node on the official trunk.",
)
async def approve_all_nodes_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ApproveAllResponse:
    """The traveler's "Approve all" — bulk per-node approval on the trunk.

    Replaces the retired itinerary-level approve: flips every approvable
    ``pending`` node to ``approved`` (annotation kinds, discarded nodes, and
    deselected alternatives are untouched), one history row per node.
    Approval is the *traveler's* gesture but is gated by the same writability
    relationship as node writes (owner / creator / advisor), so an advisor can
    still approve on behalf of a not-yet-signed-in client. Idempotent — zero
    pending nodes returns ``approved_count=0``. 409 ``not_a_trunk`` on a fork.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await approve_all_nodes(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    graph = _graph_to_response(result.view)
    graph.itinerary.display_status = await _display_status_for(session, itinerary_id)
    return ApproveAllResponse(approved_count=result.approved_count, graph=graph)


@router.post(
    "/{itinerary_id}/fork",
    response_model=GraphResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork an itinerary into an independently-editable versioned clone (G2).",
)
async def fork_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: ForkItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Deep-copy ``itinerary_id`` into a new fork and return the fork's graph.

    Traveler-initiated (and the agent, via the client's JWT). Pre-booked nodes
    copy in editable; booked/confirmed nodes copy in carried-locked (the G1 gate
    keeps them immutable in the fork). Every node carries ``forked_from_node_id``
    lineage; the itinerary carries ``forked_from_id``.

    Idempotent per caller: if the caller already holds an OPEN fork of this
    baseline, that fork's graph is returned instead of a duplicate being minted
    (still 201 — the caller can't distinguish, matching session-open semantics).
    """
    baseline = await _load_itinerary(session, itinerary_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, baseline)
    # Stamp the actor kind so the fork's history rows attribute correctly and a
    # later advisor edit on the fork resolves to ADVISOR (G1 gate).
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await fork_itinerary(session, actor, itinerary_id=itinerary_id, title=payload.title)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await get_itinerary_graph(session, result.id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    return _graph_to_response(view)


@router.get(
    "/{fork_id}/diff",
    response_model=ForkDiffResponse,
    summary="Diff a fork against its baseline (added/removed/changed/moved).",
)
async def diff_fork_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ForkDiffResponse:
    """Pair a fork's nodes to their baseline origins by lineage and bucket the
    divergence. Owner / creator / advisor only (``assert_itinerary_forkable``)."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    result = await diff_fork(session, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _fork_diff_response(result)


@router.post(
    "/{fork_id}/reconcile",
    response_model=ReconcileResponse,
    summary="Fold accepted fork changes into the live baseline (advisor only).",
)
async def reconcile_fork_endpoint(
    fork_id: uuid.UUID,
    payload: ReconcileRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ReconcileResponse:
    """Apply each accepted change to the baseline through the lock/queue +
    status-gate path; booked nodes are refused per-change, not applied. Refuses
    the whole pass on a ``block`` Analyze finding unless ``override_block``.
    Advisor-only (``require_advisor`` + stamps ADVISOR)."""
    actor = _advisor_actor_from_user(user)
    decisions = [
        ReconcileDecision(change_id=d.change_id, accept=d.accept) for d in payload.decisions
    ]
    result = await reconcile_fork(
        session,
        actor,
        fork_id=fork_id,
        decisions=decisions,
        analysis_id=payload.analysis_id,
        override_block=payload.override_block,
        accept_all=payload.accept_all,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    baseline_view = await get_itinerary_graph(session, result.itinerary.id)
    if isinstance(baseline_view, ItineraryError):
        _raise_for_error(baseline_view)
    return _reconcile_response(result, baseline_view)


@router.post(
    "/{fork_id}/request-reconcile",
    response_model=ItineraryResponse,
    summary="Ask staff to merge this fork (traveler/agent; advisor executes).",
)
async def request_reconcile_endpoint(
    fork_id: uuid.UUID,
    payload: RequestReconcileRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Stamp a pending reconcile request on the fork. Owner / creator / advisor;
    the traveler can request but only an advisor executes the merge."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await request_reconcile(session, actor, fork_id=fork_id, note=payload.note)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{fork_id}/cancel-reconcile",
    response_model=ItineraryResponse,
    summary="Withdraw a pending merge request (traveler/agent); the fork stays open.",
)
async def cancel_reconcile_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Clear the pending reconcile request on the fork without abandoning it.

    The inverse of ``request-reconcile``: the traveler asked staff to merge, then
    changed their mind. Owner / creator / advisor; the fork stays ``open`` so they
    keep editing."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await withdraw_reconcile(session, actor, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{fork_id}/abandon",
    response_model=ItineraryResponse,
    summary="Abandon a fork without merging (advisor or owner).",
)
async def abandon_fork_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Mark the fork ``abandoned`` and clear any pending reconcile request."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await abandon_fork(session, actor, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/assemble",
    response_model=GraphResponse,
    summary="Assemble the initial draft by wiring follows edges across days.",
)
async def assemble_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: AssembleDraftRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    # Gate by role: advisors stamp ADVISOR, anyone else stamps USER. The
    # service layer's lock gate admits both ADVISOR (always) and the lock
    # holder (same user_id), so an advisor-assembled draft during their own
    # lock still goes through without queueing.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    day_plan: list[DaySlot] = [
        DaySlot(
            day_index=slot.day_index,
            node_ids_in_order=slot.node_ids_in_order,
        )
        for slot in payload.day_plan
    ]
    result = await assemble_initial_draft(
        session,
        actor,
        itinerary_id=itinerary_id,
        day_plan=day_plan,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return GraphResponse(
        itinerary=_itinerary_to_response(result.itinerary),
        nodes=[_node_response_from_out(n) for n in result.nodes],
        edges=[
            EdgeResponse(
                id=e.id,
                itinerary_id=e.itinerary_id,
                from_node_id=e.from_node_id,
                to_node_id=e.to_node_id,
                type=e.type,
                metadata=e.metadata,
            )
            for e in result.edges
        ],
    )


@router.post(
    "/{itinerary_id}/edges",
    status_code=status.HTTP_201_CREATED,
    response_model=EdgeResponse,
    summary="Insert an edge into an itinerary graph.",
)
async def create_edge_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateEdgeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> EdgeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)
    result = await add_edge(
        session,
        actor,
        itinerary_id=itinerary_id,
        from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id,
        type=payload.type,
        metadata=payload.metadata,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return EdgeResponse(
        id=result.id,
        itinerary_id=result.itinerary_id,
        from_node_id=result.from_node_id,
        to_node_id=result.to_node_id,
        type=result.type,
        metadata=result.metadata_,
    )


@router.delete(
    "/{itinerary_id}/edges/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an edge.",
)
async def delete_edge_endpoint(
    itinerary_id: uuid.UUID,
    edge_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = await _resolve_actor(session, user)
    err = await delete_edge(session, actor, itinerary_id=itinerary_id, edge_id=edge_id)
    if err is not None:
        _raise_for_error(err)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── change replay (Wave F) ────────────────────────────────────────────────────


class ChangeOut(BaseModel):
    """One projected history row — shape of the change, never its payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity: Literal["node", "edge"]
    entity_id: uuid.UUID
    op: str
    actor_kind: str
    actor_user_id: uuid.UUID | None
    occurred_at: datetime
    title: str | None
    status_before: str | None
    status_after: str | None
    changed_keys: list[str]


class ChangesResponse(BaseModel):
    """Envelope for ``GET /itinerary/{id}/changes`` — newest-first replay."""

    model_config = ConfigDict(extra="forbid")

    changes: list[ChangeOut]
    next_cursor: str | None


@router.get(
    "/{itinerary_id}/changes",
    response_model=ChangesResponse,
    summary="Replay the itinerary's node/edge history, newest-first.",
)
async def get_itinerary_changes_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    cursor: str | None = None,
    entity: Literal["node", "edge"] | None = None,
) -> ChangesResponse:
    """History of a graph the caller can read is not a new exposure — the gate
    is exactly the graph read's (``assert_itinerary_readable``)."""
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_readable(session, user, itinerary)
    page_limit = clamp_limit(limit)
    changes = await load_itinerary_changes(
        session,
        itinerary_id=itinerary_id,
        limit=page_limit,
        cursor=require_cursor(cursor),
        entity=entity,
    )
    return ChangesResponse(
        changes=[
            ChangeOut(
                id=c.id,
                entity=c.entity,
                entity_id=c.entity_id,
                op=c.op,
                actor_kind=c.actor_kind,
                actor_user_id=c.actor_user_id,
                occurred_at=c.occurred_at,
                title=c.title,
                status_before=c.status_before,
                status_after=c.status_after,
                changed_keys=c.changed_keys,
            )
            for c in changes
        ],
        next_cursor=next_changes_cursor(changes, page_limit),
    )
