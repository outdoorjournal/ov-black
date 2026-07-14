"""Itinerary graph CRUD with same-transaction history writes.

Every mutation (node or edge insert/update/delete) writes a matching row to
``node_history`` / ``edge_history`` in the SAME session before commit. We
deliberately do NOT use Postgres triggers for this — see S02 research doc
"Decision: history via service-layer writes, NOT triggers": actor attribution
needs the request-scoped ``ActorContext`` which triggers cannot see, and
coupling the audit write to the application code keeps the invariant visible
to reviewers.

Outcomes are enumerated so the HTTP layer can map each to a specific status
without leaking DB internals. The provenance gate (source ⇔ source_id) is
enforced here as a guardrail; the DB ``nodes_provenance_complete`` CHECK
constraint is the belt-and-suspenders.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, NamedTuple, TypedDict

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CostKind,
    Edge,
    EdgeHistory,
    EdgeType,
    Itinerary,
    ItineraryTimingKind,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
)
from app.services.display_status import NON_APPROVABLE_TYPES
from app.services.node_kinds import is_schedulable

logger = logging.getLogger("ov_black.itineraries")


class ItineraryOutcome(str, enum.Enum):
    """All terminal states of an itinerary mutation."""

    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID_PARENT = "invalid_parent"
    INVALID_PROVENANCE = "invalid_provenance"
    VALIDATION_ERROR = "validation_error"
    FORBIDDEN = "forbidden"
    LOCKED = "locked"
    STATUS_LOCKED = "status_locked"
    # Content mutation attempted directly on an official trunk by a non-advisor.
    # The trunk is written only via fork reconcile (publish); travelers and the
    # agent must work in a fork. Maps to HTTP 409 with detail "fork_required".
    TRUNK_LOCKED = "trunk_locked"
    # A precondition on related state failed (e.g. M005's money gate: a node
    # can't go approved → booked without a covering paid invoice line). Maps to
    # HTTP 409 so the caller can tell "not allowed yet" from a 400 bad request.
    CONFLICT = "conflict"


class ActorKind(str, enum.Enum):
    """Who initiated the mutation. Persisted on every history row."""

    USER = "user"
    AGENT = "agent"
    ADVISOR = "advisor"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Request-scoped principal used to attribute history rows.

    ``user_id`` is the Supabase ``auth.users.id`` (UUID) when a human user
    initiated the change. ``actor_id`` is an opaque string for non-user
    actors (agent session id, advisor id, system job name).
    """

    user_id: uuid.UUID | None
    kind: ActorKind
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class ItineraryError:
    """Failure envelope returned by service functions when outcome != OK."""

    outcome: ItineraryOutcome
    detail: str | None = None


class NodeOut(NamedTuple):
    """Flattened node row + CTE ``depth`` for graph assembly responses.

    ``starts_at`` is the ISO-8601 lower bound of the node's ``starts_at``
    tstzrange; ``duration_minutes`` is the whole-minute span. Both are None
    when the node has no schedule (or, for duration, no upper bound).
    """

    id: uuid.UUID
    itinerary_id: uuid.UUID
    parent_subgraph_id: uuid.UUID | None
    type: NodeType
    status: NodeStatus
    title: str
    source: str | None
    source_id: str | None
    metadata: dict[str, Any]
    cost_amount: Decimal | None
    cost_currency: str | None
    cost_kind: CostKind | None
    starts_at: str | None
    duration_minutes: int | None
    depth: int
    # Computed mutation-lock reason (G1). ``status_locked`` when the node's
    # status is firmed (approved/booked/confirmed), else None. Actor-independent
    # so it rides on every graph-read row; the agent pairs it with ``status`` to
    # explain why an edit was refused. Trailing optional so existing NodeOut
    # construction sites (and test stubs) don't need to pass it.
    lock_reason: str | None = None
    # Fork lineage (G2): the baseline node this one was copied from, or None for a
    # hand-built / inventory-sourced node. Lets the G3 diff pair nodes by lineage.
    forked_from_node_id: uuid.UUID | None = None
    # Note attachment (0014): the host node a `note` annotates, or None for a
    # free-standing note / any non-note. Trailing-optional so existing NodeOut
    # construction sites (and test stubs) don't need to pass it.
    attached_to_node_id: uuid.UUID | None = None


class EdgeOut(NamedTuple):
    """Edge row as it appears in a graph assembly response."""

    id: uuid.UUID
    itinerary_id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any]


class GraphView(NamedTuple):
    """Assembled output of :func:`get_itinerary_graph`."""

    itinerary: Itinerary
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class DaySlot(TypedDict):
    """One day's worth of ordered node ids for :func:`assemble_initial_draft`.

    ``day_index`` is preserved only so the caller can provide ordering across
    days; the service itself only emits ``follows`` edges within a single
    slot (consecutive node pairs).
    """

    day_index: int
    node_ids_in_order: list[uuid.UUID]


# ── Snapshot helpers ────────────────────────────────────────────────────────


def _snapshot_node(node: Node) -> dict[str, Any]:
    """JSON-safe snapshot of a node for before/after history columns."""
    return {
        "id": str(node.id),
        "itinerary_id": str(node.itinerary_id),
        "parent_subgraph_id": (str(node.parent_subgraph_id) if node.parent_subgraph_id else None),
        "type": node.type.value if isinstance(node.type, NodeType) else node.type,
        "status": (node.status.value if isinstance(node.status, NodeStatus) else node.status),
        "title": node.title,
        "source": node.source,
        "source_id": node.source_id,
        "metadata": node.metadata_,
        # Money fields are JSON-safe: Decimal → str (lossless), enum → value.
        "cost_amount": str(node.cost_amount) if node.cost_amount is not None else None,
        "cost_currency": node.cost_currency,
        "cost_kind": (
            node.cost_kind.value if isinstance(node.cost_kind, CostKind) else node.cost_kind
        ),
    }


def _snapshot_edge(edge: Edge) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "itinerary_id": str(edge.itinerary_id),
        "from_node_id": str(edge.from_node_id),
        "to_node_id": str(edge.to_node_id),
        "type": edge.type.value if isinstance(edge.type, EdgeType) else edge.type,
        "metadata": edge.metadata_,
    }


def _parse_range_bound(raw: str) -> datetime | None:
    """Parse one bound out of a Postgres tstzrange text literal.

    asyncpg normally hands back a ``Range`` object, but a raw recursive-CTE
    column can surface the text form, e.g.
    ``'["2024-06-20 16:10:00+09","2024-06-20 16:40:00+09")'``. Bounds are
    space-separated (not ``T``) and may be quoted; an empty bound (unbounded
    side) yields ``None``.
    """
    bound = raw.strip().strip('"')
    if not bound:
        return None
    # Postgres uses a space between date and time; datetime.fromisoformat in
    # 3.11+ accepts that, but normalise to be safe across the offset forms it
    # emits (e.g. "+09" with no minutes).
    iso = bound.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _serialize_starts_at(
    value: Any, tz_offset_minutes: int | None = None
) -> tuple[str | None, int | None]:
    """(iso_start, duration_minutes) from a tstzrange value, or (None, None).

    Handles three runtime forms defensively:

    - ``None`` → ``(None, None)``.
    - A Range-like object (asyncpg ``Range``) with ``.lower`` / ``.upper``
      tz-aware datetimes → ``(lower.isoformat(), round((upper - lower)
      total minutes))``; ``upper is None`` → ``(lower.isoformat(), None)``.
    - The Postgres text literal form
      ``'["2024-06-20 16:10:00+09","2024-06-20 16:40:00+09")'`` (in case a
      raw CTE column surfaces the string) — parsed via :func:`_parse_range_bound`.

    ``tz_offset_minutes`` is the node's LOCAL UTC offset (minutes), recorded
    at template build time in the node's metadata. A trip spans multiple
    zones (a LAX→Tokyo flight departs PDT, everything after is JST), and the
    tstzrange column stores instants in UTC — so without this the original
    wall-clock offset is lost. When provided, ``iso_start`` is emitted in a
    fixed-offset timezone (e.g. ``"2024-06-20T16:10:00+09:00"``) representing
    the same instant; when None, the lower bound's own offset (UTC for a CTE
    column) is used. ``duration_minutes`` (range width) is unaffected.
    """
    if value is None:
        return (None, None)

    lower: datetime | None
    upper: datetime | None
    if hasattr(value, "lower") and not isinstance(value, str):
        lower = value.lower
        upper = value.upper
    elif isinstance(value, str):
        inner = value.strip().lstrip("[(").rstrip("])")
        # Split on the comma that separates the two bounds, respecting that a
        # quoted timestamp won't itself contain a bare comma.
        parts = inner.split(",", 1)
        lower = _parse_range_bound(parts[0]) if parts else None
        upper = _parse_range_bound(parts[1]) if len(parts) > 1 else None
    else:
        return (None, None)

    if lower is None:
        return (None, None)
    if tz_offset_minutes is not None:
        local_tz = timezone(timedelta(minutes=tz_offset_minutes))
        iso_start = lower.astimezone(local_tz).isoformat()
    else:
        iso_start = lower.isoformat()
    if upper is None:
        return (iso_start, None)
    duration = round((upper - lower).total_seconds() / 60)
    return (iso_start, duration)


def _tz_offset_from_metadata(metadata: Any) -> int | None:
    """Pull the node's local UTC offset (minutes) out of its metadata.

    Returns None if the key is absent or not an int — callers then fall back
    to the lower bound's own (UTC) offset.
    """
    if not isinstance(metadata, dict):
        return None
    offset = metadata.get("tz_offset_minutes")
    return offset if isinstance(offset, int) else None


def _build_starts_at(iso_start: str, duration_minutes: int | None) -> Range[datetime] | None:
    """Construct a ``tstzrange`` value from an ISO-8601 start + optional minutes.

    The inverse of :func:`_serialize_starts_at`: parse the lower bound (the
    offset it carries is preserved as a UTC instant by Postgres) and, when
    ``duration_minutes`` is given, an upper bound ``start + duration``. Returns a
    half-open ``[)`` :class:`Range` ready to assign to ``Node.starts_at``, or
    ``None`` when the start can't be parsed. Free-standing notes need this at
    INSERT time — the ``notes_anchored_or_attached`` CHECK is per-row, so the
    column can't be back-filled after the insert.
    """
    lower = _parse_range_bound(iso_start)
    if lower is None:
        return None
    upper = lower + timedelta(minutes=duration_minutes) if duration_minutes else None
    return Range(lower, upper, bounds="[)")


def _resolve_note_anchor(
    *,
    metadata: dict[str, Any],
    attached_to_node_id: uuid.UUID | None,
    starts_at: str | None,
    duration_minutes: int | None,
) -> tuple[ItineraryError | None, Range[datetime] | None, dict[str, Any]]:
    """Validate a note's anchor and, for a free-standing note, build its range.

    Returns ``(error, starts_at_range, metadata)``. An *attached* note returns
    ``(None, None, metadata)`` — it rides its host and carries no range (the
    caller validates that ``attached_to_node_id`` lives in the same itinerary).
    A *free-standing* note takes its time from ``starts_at`` or, failing that,
    ``metadata['start_time']``; the chosen start is mirrored back into the
    returned metadata (with ``tz_offset_minutes`` / ``duration_minutes``) so the
    web timeline, which reads ``metadata.start_time``, renders it.
    """
    if attached_to_node_id is not None:
        if starts_at is not None:
            return (
                ItineraryError(
                    outcome=ItineraryOutcome.VALIDATION_ERROR,
                    detail="a note is either attached to a node or has its own time, not both",
                ),
                None,
                metadata,
            )
        return (None, None, metadata)

    iso = starts_at or metadata.get("start_time")
    if not isinstance(iso, str) or not iso:
        # A timeless, unattached note is a Collection note (0035): it lives in
        # the wish list with no schedule, exactly like any other unscheduled
        # node. The relaxed `notes_anchored_or_attached` CHECK permits it.
        return (None, None, metadata)
    rng = _build_starts_at(iso, duration_minutes)
    if rng is None or rng.lower is None:
        return (
            ItineraryError(
                outcome=ItineraryOutcome.VALIDATION_ERROR,
                detail="starts_at must be an ISO-8601 datetime",
            ),
            None,
            metadata,
        )
    mirrored = {**metadata, "start_time": iso}
    offset = rng.lower.utcoffset()
    if offset is not None:
        mirrored["tz_offset_minutes"] = int(offset.total_seconds() // 60)
    if duration_minutes:
        mirrored["duration_minutes"] = duration_minutes
    return (None, rng, mirrored)


def _resolve_scheduled_anchor(
    *,
    metadata: dict[str, Any],
    starts_at: str | None,
    duration_minutes: int | None,
) -> tuple[ItineraryError | None, Range[datetime] | None, dict[str, Any]]:
    """Build a NON-note node's ``starts_at`` range from an ISO start + duration.

    Flights, meals, experiences, … also live on the timeline by ``starts_at``;
    the ``tstzrange`` column is their schedule. This mirrors the note anchor's
    contract for them: parse the ISO start (plus optional ``duration_minutes``)
    into a half-open range, and write the chosen wall-clock back into
    ``metadata`` (``start_time`` / ``tz_offset_minutes`` / ``duration_minutes``)
    so the read serializer and web timeline reconstruct the exact local time
    the caller sent — the column stores UTC instants, so the offset would
    otherwise be lost. ``starts_at is None`` leaves the node unscheduled and
    returns ``(None, None, metadata)`` unchanged.
    """
    if starts_at is None:
        return (None, None, metadata)
    rng = _build_starts_at(starts_at, duration_minutes)
    if rng is None or rng.lower is None:
        return (
            ItineraryError(
                outcome=ItineraryOutcome.VALIDATION_ERROR,
                detail="starts_at must be an ISO-8601 datetime",
            ),
            None,
            metadata,
        )
    mirrored = {**metadata, "start_time": starts_at}
    offset = rng.lower.utcoffset()
    if offset is not None:
        mirrored["tz_offset_minutes"] = int(offset.total_seconds() // 60)
    if duration_minutes:
        mirrored["duration_minutes"] = duration_minutes
    return (None, rng, mirrored)


async def _write_node_history(
    session: AsyncSession,
    *,
    node_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    op: str,
    actor: ActorContext,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append a row to node_history in the same session as the mutation."""
    session.add(
        NodeHistory(
            node_id=node_id,
            itinerary_id=itinerary_id,
            op=op,
            actor_user_id=actor.user_id,
            actor_kind=actor.kind.value,
            actor_id=actor.actor_id,
            before=before,
            after=after,
        )
    )
    logger.info(
        "itinerary.history.write",
        extra={"table": "node_history", "op": op, "node_id": str(node_id)},
    )


async def _write_edge_history(
    session: AsyncSession,
    *,
    edge_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    op: str,
    actor: ActorContext,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        EdgeHistory(
            edge_id=edge_id,
            itinerary_id=itinerary_id,
            op=op,
            actor_user_id=actor.user_id,
            actor_kind=actor.kind.value,
            actor_id=actor.actor_id,
            before=before,
            after=after,
        )
    )
    logger.info(
        "itinerary.history.write",
        extra={"table": "edge_history", "op": op, "edge_id": str(edge_id)},
    )


# ── Provenance gate ─────────────────────────────────────────────────────────


def _check_provenance(source: str | None, source_id: str | None) -> ItineraryError | None:
    if (source is None) != (source_id is None):
        return ItineraryError(
            outcome=ItineraryOutcome.INVALID_PROVENANCE,
            detail="source and source_id must be provided together",
        )
    return None


def _check_cost(cost_amount: Decimal | None, cost_currency: str | None) -> ItineraryError | None:
    """Amount and currency must travel together (mirrors provenance).

    A guardrail in front of the ``nodes_cost_amount_currency_together`` DB
    CHECK so a half-specified cost surfaces as a deterministic 400 instead of
    an integrity error. ``cost_kind`` is independent and not checked here.
    """
    if (cost_amount is None) != (cost_currency is None):
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail="cost_amount and cost_currency must be provided together",
        )
    return None


_COST_FIELDS: tuple[str, ...] = ("cost_amount", "cost_currency", "cost_kind")


def _check_cost_authority(
    updates: dict[str, Any], node: Node, actor: ActorContext
) -> ItineraryError | None:
    """Price is advisor-authored — a traveler/agent can't (re-)quote it.

    A traveler may reshape and annotate their own fork (title, schedule, notes,
    description), but the *price* is the advisor's authority alone, even on that
    fork: the itinerary graph is the billing spine, so a self-set cost must never
    slip in. SYSTEM passes so fork reconcile (publish, advisor-executed) can
    carry an advisor's price onto the trunk. Mirrors the trunk guard's actor
    split (see ``_check_write_gates``).

    Only a mutation that actually CHANGES a cost field is refused; echoing the
    current value alongside a legitimate non-price edit stays allowed.
    """
    if actor.kind in (ActorKind.ADVISOR, ActorKind.SYSTEM):
        return None
    for field in _COST_FIELDS:
        if field in updates and updates[field] != getattr(node, field):
            return ItineraryError(
                outcome=ItineraryOutcome.FORBIDDEN,
                detail="advisor_only_price",
            )
    return None


# ── Write gates (editor lock + trunk guard) ─────────────────────────────────


async def _check_write_gates(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    actor: ActorContext,
    *,
    pure_status_change: bool = False,
    trunk_exempt: bool = False,
) -> ItineraryError | None:
    """Reject writes the itinerary-level gates forbid. One SELECT, two rules.

    **Trunk guard.** An official trunk (``forked_from_id IS NULL``) receives
    content only via fork reconcile (publish). A USER/AGENT content mutation on
    a trunk returns ``TRUNK_LOCKED`` / ``fork_required`` — fork first. Pure
    node-status changes are exempt (traveler approval/discard happens directly
    on the trunk), as are ADVISOR (reconcile applies through this path, plus
    the deliberate escape hatch) and SYSTEM (seeds/demos) actors. **Non-plan
    Collection writes are exempt too** (``trunk_exempt``): a note is feedback
    and a reading-list ``article`` is a non-schedulable saved read — neither is
    a plan commitment (the Journal lets a traveler annotate the trunk directly,
    and reading is Collection-only), so — like a status change and like the
    delete path's note carve-out — they land on the trunk without a fork. The
    editor lock below still applies.

    **Editor lock.** Non-advisor writes to an itinerary locked by a different
    user are rejected. Advisors always bypass — they hold the lock during
    their editing session and the advisor guard at the router layer is the
    authoritative gate. A null ``locked_by`` means unlocked; a ``locked_by``
    matching ``actor.user_id`` means the caller owns the lock.
    """
    row = (
        await session.execute(
            select(Itinerary.locked_by, Itinerary.forked_from_id).where(
                Itinerary.id == itinerary_id
            )
        )
    ).one_or_none()
    if row is None:
        return None  # Existence is the caller's NOT_FOUND concern.
    locked_by, forked_from_id = row

    if (
        forked_from_id is None
        and not pure_status_change
        and not trunk_exempt
        and actor.kind not in (ActorKind.ADVISOR, ActorKind.SYSTEM)
    ):
        return ItineraryError(
            outcome=ItineraryOutcome.TRUNK_LOCKED,
            detail="fork_required",
        )

    if actor.kind is ActorKind.ADVISOR:
        return None
    if locked_by is None:
        return None
    if actor.user_id is not None and locked_by == actor.user_id:
        return None
    return ItineraryError(
        outcome=ItineraryOutcome.LOCKED,
        detail="locked_by_advisor",
    )


# ── Status gate (G1 — TravelGraph_Analysis §11) ─────────────────────────────

# "Firmed" statuses are commitments: a node that's approved, booked, or
# confirmed is immutable except through an explicit advisor-initiated status
# change (demotion / cancellation / advance). The pre-firmed statuses are
# freely editable — pending is still being shaped, and discarded is a
# reversible side-state that restores to a prior status.
_FIRMED_STATUSES: frozenset[NodeStatus] = frozenset(
    {NodeStatus.approved, NodeStatus.booked, NodeStatus.confirmed}
)

# Statuses a node may enter ONLY through the M005/I3 money gate
# (``services.bookings``), never via a direct ``update_node`` status flip.
_GATED_PROMOTION_STATUSES: frozenset[NodeStatus] = frozenset(
    {NodeStatus.booked, NodeStatus.confirmed}
)


def compute_lock_reason(status: NodeStatus) -> str | None:
    """The agent-readable reason a node is mutation-locked, or None.

    Computed from status alone (actor-independent) so it can ride on every
    graph-read row: a firmed node carries ``"status_locked"`` and the agent
    pairs it with the node's ``status`` to explain conversationally ("that
    hotel is already booked; an advisor would need to move it"). Editor-session
    locks are itinerary-level and surface via the ``LOCKED`` outcome on write,
    not here.
    """
    if status in _FIRMED_STATUSES:
        return "status_locked"
    return None


def _check_status_gate(
    *,
    current_status: NodeStatus,
    actor: ActorContext,
    mutates_other_fields: bool,
) -> ItineraryError | None:
    """Reject mutations that a node's lifecycle status forbids (§11).

    Only firmed statuses (approved/booked/confirmed) are constrained:

    - **Advisor** may perform a *pure status change* — the demotion /
      cancellation / advance escape hatch, which is recorded in node_history
      with ``actor_kind=advisor`` (the visible note the Style Guide requires).
      Editing any other field on a firmed node is refused: the advisor must
      demote it to a pre-firmed status first, then edit.
    - **Non-advisor** (traveler / agent / system) cannot touch a firmed node at
      all.

    Pre-firmed statuses (pending/discarded) are unconstrained here.
    Promotion *into* a firmed status from a pre-firmed one is intentionally NOT
    gated in G1 — booked-promotion authority is M005's money gate (a node may
    move ``approved → booked`` only when a paid invoice line covers it).
    """
    if current_status not in _FIRMED_STATUSES:
        return None
    if actor.kind is ActorKind.ADVISOR:
        if mutates_other_fields:
            # Advisor edit of a firmed node without demoting first.
            return ItineraryError(
                outcome=ItineraryOutcome.STATUS_LOCKED,
                detail="demote_before_edit",
            )
        # Pure status change — the logged demotion / cancellation / advance.
        return None
    return ItineraryError(
        outcome=ItineraryOutcome.STATUS_LOCKED,
        detail="status_locked",
    )


# ── Public service surface ──────────────────────────────────────────────────


async def create_itinerary(
    session: AsyncSession,
    actor: ActorContext,
    *,
    title: str,
    client_id: uuid.UUID | None = None,
    brief: str | None = None,
    timing_kind: ItineraryTimingKind | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
    duration_nights: int | None = None,
    timing_note: str | None = None,
    campaign_id: str | None = None,
    mood: str | None = None,
) -> Itinerary:
    """Create a new itinerary container.

    Optional ``brief`` + timing fields (0033) let a caller seed the trip goal /
    when at creation; they usually arrive later via ``update_itinerary_details``
    from the builder's first-run intake, so all default to None. ``campaign_id``
    + ``mood`` (0047) let a campaign seed stamp provenance + the hero mood up
    front; None for ordinary trips.

    Itineraries themselves are not audited in node_history / edge_history —
    those tables only track graph mutations. Auditing of itinerary-level
    changes can land in a follow-up slice if needed.
    """
    itinerary = Itinerary(
        title=title,
        client_id=client_id,
        created_by=actor.user_id,
        brief=brief,
        timing_kind=timing_kind,
        date_start=date_start,
        date_end=date_end,
        duration_nights=duration_nights,
        timing_note=timing_note,
        campaign_id=campaign_id,
        mood=mood,
    )
    session.add(itinerary)
    await session.flush()
    await session.commit()
    logger.info(
        "itinerary.create",
        extra={
            "itinerary_id": str(itinerary.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return itinerary


# Trip-level fields the builder's intake may write. Title is included but treated
# specially (NOT NULL — an explicit null is ignored, not applied).
_UPDATABLE_ITINERARY_FIELDS = frozenset(
    {
        "title",
        "brief",
        "timing_kind",
        "date_start",
        "date_end",
        "duration_nights",
        "timing_note",
    }
)


async def update_itinerary_details(
    session: AsyncSession,
    actor: ActorContext,
    itinerary: Itinerary,
    *,
    fields: dict[str, Any],
) -> Itinerary | ItineraryError:
    """Apply a partial update to an itinerary's title + brief + timing (0033).

    Only keys present in ``fields`` are written (the router passes
    ``model_dump(exclude_unset=True)``), so a caller clears a date by sending an
    explicit ``None`` while omitted fields are left untouched — the semantics the
    first-run intake relies on when switching from exact dates to a flexible
    window. ``title`` is NOT NULL, so an explicit ``None`` there is ignored.

    Date ordering is validated here (against the post-update values) so a bad
    range returns a clean VALIDATION_ERROR instead of surfacing the DB CHECK as
    a 500.
    """
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE_ITINERARY_FIELDS}

    # Validate the resulting range: a provided key overrides the stored value
    # (including to None); an absent key keeps the stored value.
    new_start = updates.get("date_start", itinerary.date_start)
    new_end = updates.get("date_end", itinerary.date_end)
    if new_start is not None and new_end is not None and new_end < new_start:
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail="date_end_before_start",
        )

    # Booking invariant, reverse direction (Wave E / ADV-17): booking is only
    # possible on pinned (exact) dates, so loosening exact → window/flexible is
    # refused while booked/confirmed cards exist — their dates are commitments
    # to suppliers. Cancel the bookings first, then loosen.
    new_kind = updates.get("timing_kind", itinerary.timing_kind)
    if (
        itinerary.timing_kind is ItineraryTimingKind.exact
        and new_kind is not ItineraryTimingKind.exact
        and await _has_booked_nodes(session, itinerary.id)
    ):
        return ItineraryError(
            outcome=ItineraryOutcome.CONFLICT,
            detail="booked_dates_locked",
        )

    changed: list[str] = []
    for key, value in updates.items():
        if key == "title" and value is None:
            continue  # NOT NULL column — ignore an explicit clear.
        if getattr(itinerary, key) != value:
            setattr(itinerary, key, value)
            changed.append(key)

    # On a pinned (exact) trip `date_start` IS Day 1, so the stamped anchor must
    # follow it — otherwise a `days_anchor` stamped earlier (e.g. against a
    # scratch note added before dates were set) leaves Day-N numbering counting
    # from a phantom start and mis-shifts a later retime. `retime_itinerary`
    # re-stamps on its own path; this is the raw window-edit path's equivalent.
    if (
        itinerary.timing_kind is ItineraryTimingKind.exact
        and itinerary.date_start is not None
        and itinerary.days_anchor != itinerary.date_start
    ):
        itinerary.days_anchor = itinerary.date_start
        if "days_anchor" not in changed:
            changed.append("days_anchor")

    if changed:
        await session.commit()
        await session.refresh(itinerary)
    logger.info(
        "itinerary.update_details",
        extra={
            "itinerary_id": str(itinerary.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
            # Field NAMES only — never the free-text brief / note values.
            "fields": ",".join(sorted(changed)),
        },
    )
    return itinerary


async def _has_booked_nodes(session: AsyncSession, itinerary_id: uuid.UUID) -> bool:
    """True when any live (non-deleted) node is booked or confirmed.

    The Wave E booking invariant's other half: booked cards pin the calendar,
    so retime / loosening must refuse while any exist.
    """
    row = (
        await session.execute(
            select(Node.id)
            .where(
                Node.itinerary_id == itinerary_id,
                Node.status.in_([NodeStatus.booked, NodeStatus.confirmed]),
                Node.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _maybe_stamp_days_anchor(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    """Give "Day 1" a stable identity the first time anything is scheduled (ADV-16).

    On an unpinned trip the cards' absolute dates are provisional coordinates;
    what matters is their *relative* structure, rendered as Day-N ordinals from
    this anchor: Day N ≡ days_anchor + (N−1). Without it the anchor was derived
    from the earliest scheduled card, so deleting the Day-1 card renumbered
    every day. Stamped once — the window's ``date_start`` when one exists, else
    the current UTC date (matching the web adapter's ``todayKey`` fallback the
    first card was laid out against). No commit: rides the caller's transaction.
    """
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None or itinerary.days_anchor is not None:
        return
    itinerary.days_anchor = itinerary.date_start or datetime.now(UTC).date()
    logger.info(
        "itinerary.days_anchor.stamp",
        extra={"itinerary_id": str(itinerary_id), "days_anchor": itinerary.days_anchor.isoformat()},
    )


def _node_local_start_date(node: Node) -> date | None:
    """The node's scheduled LOCAL calendar date, or None when unscheduled.

    Prefers the mirrored ``metadata.start_time`` wall-clock (the same value the
    web timeline places the card by); falls back to the ``starts_at`` lower
    bound re-expressed in the recorded ``tz_offset_minutes``.
    """
    meta = node.metadata_ if isinstance(node.metadata_, dict) else {}
    iso = meta.get("start_time")
    if isinstance(iso, str) and iso:
        try:
            return datetime.fromisoformat(iso).date()
        except ValueError:
            pass
    lower = getattr(node.starts_at, "lower", None)
    if isinstance(lower, datetime):
        offset = _tz_offset_from_metadata(meta)
        if offset is not None:
            return lower.astimezone(timezone(timedelta(minutes=offset))).date()
        return lower.date()
    return None


@dataclass(frozen=True, slots=True)
class RetimeResult:
    """Outcome of :func:`retime_itinerary` — the pinned itinerary + what moved."""

    itinerary: Itinerary
    delta_days: int
    shifted_node_ids: tuple[uuid.UUID, ...]


async def retime_itinerary(
    session: AsyncSession,
    actor: ActorContext,
    itinerary: Itinerary,
    *,
    date_start: date,
    date_end: date | None = None,
) -> RetimeResult | ItineraryError:
    """Pin the trip to real dates — the Wave E (ADV-17) retime gesture.

    "Day 1 is March 18, 2027": computes ``delta = date_start − days_anchor``
    and shifts every scheduled node's ``starts_at`` / ``metadata.start_time``
    by that many whole days, preserving the wall-clock time and tz offset (a
    09:00 breakfast stays a 09:00 breakfast). Then flips the itinerary to
    ``timing_kind=exact`` and re-stamps ``days_anchor = date_start``, so a
    later re-pin is just another uniform shift. Each moved node gets a
    node_history row.

    Deliberately trip-level: approved (but unbooked) cards move with the trip —
    the G1 per-node edit gate does not apply here. What DOES refuse is a shift
    while booked/confirmed cards exist (``booked_dates_locked``): booking gates
    on pinned dates, so a booked card's date is a supplier commitment.

    ``date_end`` resolution when omitted: an already-exact trip keeps its span;
    else ``duration_nights`` counts forward from ``date_start``; else the last
    scheduled card's (shifted) date; else the trip is a single pinned day.
    """
    if date_end is not None and date_end < date_start:
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail="date_end_before_start",
        )

    lock_err = await _check_write_gates(session, itinerary.id, actor)
    if lock_err is not None:
        return lock_err

    nodes = (
        (
            await session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary.id,
                    Node.starts_at.isnot(None),
                    Node.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    # Day 1's current identity. The stamped anchor is authoritative; legacy
    # trips that predate 0041 fall back to the declared start, then the earliest
    # scheduled card (the web adapter's old derivation), then the target itself
    # (nothing scheduled — the "shift" is a pure timing write).
    anchor = itinerary.days_anchor or itinerary.date_start
    if anchor is None:
        scheduled_dates = [d for d in (_node_local_start_date(n) for n in nodes) if d is not None]
        anchor = min(scheduled_dates) if scheduled_dates else date_start

    delta_days = (date_start - anchor).days
    if delta_days != 0 and any(
        n.status in (NodeStatus.booked, NodeStatus.confirmed) for n in nodes
    ):
        return ItineraryError(
            outcome=ItineraryOutcome.CONFLICT,
            detail="booked_dates_locked",
        )

    shifted: list[uuid.UUID] = []
    if delta_days != 0:
        delta = timedelta(days=delta_days)
        for node in nodes:
            before = _snapshot_node(node)
            meta = node.metadata_ if isinstance(node.metadata_, dict) else {}
            iso = meta.get("start_time")
            new_range: Range[datetime] | None = None
            if isinstance(iso, str) and iso:
                # Shift the mirrored wall-clock and rebuild the column from it —
                # the same metadata-first contract as update_node's schedule
                # sync. A fixed-offset datetime + N days keeps the wall-clock.
                try:
                    new_local = datetime.fromisoformat(iso) + delta
                except ValueError:
                    new_local = None
                if new_local is not None:
                    lower = getattr(node.starts_at, "lower", None)
                    upper = getattr(node.starts_at, "upper", None)
                    dur = (
                        round((upper - lower).total_seconds() / 60)
                        if isinstance(lower, datetime) and isinstance(upper, datetime)
                        else None
                    )
                    new_iso = new_local.isoformat()
                    new_range = _build_starts_at(new_iso, dur)
                    if new_range is not None:
                        node.metadata_ = {**meta, "start_time": new_iso}
            if new_range is None:
                # No (parseable) mirror — shift the raw UTC bounds; whole-day
                # deltas preserve the wall-clock in any fixed-offset zone.
                lower = getattr(node.starts_at, "lower", None)
                upper = getattr(node.starts_at, "upper", None)
                if not isinstance(lower, datetime):
                    continue
                new_range = Range(
                    lower + delta,
                    upper + delta if isinstance(upper, datetime) else None,
                    bounds="[)",
                )
            node.starts_at = new_range
            await _write_node_history(
                session,
                node_id=node.id,
                itinerary_id=itinerary.id,
                op="update",
                actor=actor,
                before=before,
                after=_snapshot_node(node),
            )
            shifted.append(node.id)

    old_start, old_end = itinerary.date_start, itinerary.date_end
    resolved_end = date_end
    if resolved_end is None:
        if itinerary.timing_kind is ItineraryTimingKind.exact and old_start and old_end:
            resolved_end = date_start + (old_end - old_start)
        elif itinerary.duration_nights:
            resolved_end = date_start + timedelta(days=itinerary.duration_nights)
        else:
            shifted_dates = [d for d in (_node_local_start_date(n) for n in nodes) if d is not None]
            resolved_end = max([*shifted_dates, date_start])

    itinerary.timing_kind = ItineraryTimingKind.exact
    itinerary.date_start = date_start
    itinerary.date_end = resolved_end
    itinerary.days_anchor = date_start

    await session.commit()
    await session.refresh(itinerary)
    logger.info(
        "itinerary.retime",
        extra={
            "itinerary_id": str(itinerary.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
            "delta_days": delta_days,
            "shifted_nodes": len(shifted),
        },
    )
    return RetimeResult(
        itinerary=itinerary,
        delta_days=delta_days,
        shifted_node_ids=tuple(shifted),
    )


async def get_itinerary_graph(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
) -> GraphView | ItineraryError:
    """Assemble (itinerary, nodes-with-depth, edges) with one recursive CTE.

    Depth 0 = root nodes (parent_subgraph_id IS NULL). Each deeper level
    follows the self-FK. The CTE is a single round-trip; edges come back in
    a second SELECT. No N+1.
    """
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    cte_sql = text(
        """
        with recursive subgraph(
            id, itinerary_id, parent_subgraph_id, type, status, title,
            source, source_id, metadata, cost_amount, cost_currency, cost_kind,
            starts_at, forked_from_node_id, attached_to_node_id, depth
        ) as (
            select n.id, n.itinerary_id, n.parent_subgraph_id, n.type, n.status,
                   n.title, n.source, n.source_id, n.metadata, n.cost_amount,
                   n.cost_currency, n.cost_kind, n.starts_at,
                   n.forked_from_node_id, n.attached_to_node_id, 0
              from public.nodes n
             where n.itinerary_id = :iid
               and n.parent_subgraph_id is null
               and n.deleted_at is null
            union all
            select c.id, c.itinerary_id, c.parent_subgraph_id, c.type, c.status,
                   c.title, c.source, c.source_id, c.metadata, c.cost_amount,
                   c.cost_currency, c.cost_kind, c.starts_at,
                   c.forked_from_node_id, c.attached_to_node_id, s.depth + 1
              from public.nodes c
              join subgraph s on c.parent_subgraph_id = s.id
             where c.itinerary_id = :iid
               and c.deleted_at is null
        )
        select id, itinerary_id, parent_subgraph_id, type, status, title,
               source, source_id, metadata, cost_amount, cost_currency,
               cost_kind, starts_at, forked_from_node_id, attached_to_node_id, depth
          from subgraph
         order by depth, id
        """
    )
    node_rows = (await session.execute(cte_sql, {"iid": itinerary_id})).all()
    nodes: list[NodeOut] = []
    for row in node_rows:
        row_metadata = row.metadata or {}
        iso_start, duration_minutes = _serialize_starts_at(
            row.starts_at, _tz_offset_from_metadata(row_metadata)
        )
        nodes.append(
            NodeOut(
                id=row.id,
                itinerary_id=row.itinerary_id,
                parent_subgraph_id=row.parent_subgraph_id,
                type=NodeType(row.type),
                status=NodeStatus(row.status),
                title=row.title,
                source=row.source,
                source_id=row.source_id,
                metadata=row_metadata,
                cost_amount=row.cost_amount,
                cost_currency=row.cost_currency,
                cost_kind=CostKind(row.cost_kind) if row.cost_kind else None,
                starts_at=iso_start,
                duration_minutes=duration_minutes,
                depth=row.depth,
                lock_reason=compute_lock_reason(NodeStatus(row.status)),
                forked_from_node_id=row.forked_from_node_id,
                attached_to_node_id=row.attached_to_node_id,
            )
        )

    edge_rows = (
        (
            await session.execute(
                select(Edge).where(Edge.itinerary_id == itinerary_id).order_by(Edge.created_at)
            )
        )
        .scalars()
        .all()
    )
    # Drop edges whose endpoint was soft-deleted (or pruned as a hidden node's
    # descendant): the CTE above already omits those nodes, so a surviving edge
    # would dangle. This mirrors the old ON DELETE CASCADE on the edge FKs.
    visible_node_ids = {node.id for node in nodes}
    edges: list[EdgeOut] = [
        EdgeOut(
            id=edge.id,
            itinerary_id=edge.itinerary_id,
            from_node_id=edge.from_node_id,
            to_node_id=edge.to_node_id,
            type=edge.type,
            metadata=edge.metadata_,
        )
        for edge in edge_rows
        if edge.from_node_id in visible_node_ids and edge.to_node_id in visible_node_ids
    ]

    return GraphView(itinerary=itinerary, nodes=nodes, edges=edges)


async def add_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    type: NodeType,
    status: NodeStatus = NodeStatus.pending,
    title: str = "",
    parent_subgraph_id: uuid.UUID | None = None,
    source: str | None = None,
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    cost_amount: Decimal | None = None,
    cost_currency: str | None = None,
    cost_kind: CostKind | None = None,
    attached_to_node_id: uuid.UUID | None = None,
    starts_at: str | None = None,
    duration_minutes: int | None = None,
) -> Node | ItineraryError:
    """Insert a node + its history row in the same transaction.

    ``note`` nodes are dual-mode (0014 ``notes_anchored_or_attached``): exactly
    one of ``attached_to_node_id`` (an annotation riding a host node) or a time
    anchor (a free-standing item) must be set. The time anchor comes from
    ``starts_at`` (ISO-8601, plus optional ``duration_minutes``) or falls back to
    ``metadata['start_time']``; it's mirrored back into ``metadata`` so the web
    timeline (which reads ``metadata.start_time``) renders it.
    """
    prov_err = _check_provenance(source, source_id)
    if prov_err is not None:
        return prov_err

    cost_err = _check_cost(cost_amount, cost_currency)
    if cost_err is not None:
        return cost_err

    # Non-schedulable cards (articles) are Collection-only reads — they never
    # carry a time. Reject an explicit anchor rather than silently placing them
    # on the timeline (mirrors the write-path guard in move/retime).
    if not is_schedulable(type) and (
        starts_at is not None or (metadata or {}).get("start_time") is not None
    ):
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=f"{type.value} nodes are not schedulable",
        )

    # Confirm parent itinerary exists up front so we return NOT_FOUND
    # instead of an FK violation.
    itinerary_exists = (
        await session.execute(select(Itinerary.id).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary_exists is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_write_gates(
        session,
        itinerary_id,
        actor,
        # Notes and non-schedulable reads (articles) are Collection-only, not
        # plan commitments — they land on a trunk without forking (see gate).
        trunk_exempt=type is NodeType.note or not is_schedulable(type),
    )
    if lock_err is not None:
        return lock_err

    if parent_subgraph_id is not None:
        parent = (
            await session.execute(select(Node).where(Node.id == parent_subgraph_id))
        ).scalar_one_or_none()
        if parent is None or parent.itinerary_id != itinerary_id:
            return ItineraryError(
                outcome=ItineraryOutcome.INVALID_PARENT,
                detail="parent_subgraph_id does not belong to this itinerary",
            )

    # Note anchoring (0014). Resolve the XOR — attached vs. free-standing — and
    # build the starts_at range up front so the per-row CHECK is satisfied at
    # INSERT. ``metadata`` may be replaced with a mirrored copy below.
    node_metadata = dict(metadata or {})
    node_starts_at: Range[datetime] | None = None
    if type is NodeType.note:
        anchor_err, node_starts_at, node_metadata = _resolve_note_anchor(
            metadata=node_metadata,
            attached_to_node_id=attached_to_node_id,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
        )
        if anchor_err is not None:
            return anchor_err
        if attached_to_node_id is not None:
            host = (
                await session.execute(
                    select(Node.id).where(
                        Node.id == attached_to_node_id,
                        Node.itinerary_id == itinerary_id,
                    )
                )
            ).scalar_one_or_none()
            if host is None:
                return ItineraryError(
                    outcome=ItineraryOutcome.INVALID_PARENT,
                    detail="attached_to_node_id does not belong to this itinerary",
                )
    elif attached_to_node_id is not None:
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail="attached_to_node_id is only valid for note nodes",
        )
    else:
        # Non-note nodes carry their schedule on the same column. Persist an
        # explicit starts_at (+ duration) instead of silently dropping it —
        # otherwise the timeline has to synthesize placement (see the web
        # adapter's SYNTH_START_HOUR fallback).
        sched_err, node_starts_at, node_metadata = _resolve_scheduled_anchor(
            metadata=node_metadata,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
        )
        if sched_err is not None:
            return sched_err

    node = Node(
        itinerary_id=itinerary_id,
        parent_subgraph_id=parent_subgraph_id,
        type=type,
        status=status,
        title=title,
        source=source,
        source_id=source_id,
        metadata_=node_metadata,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        cost_kind=cost_kind,
        attached_to_node_id=attached_to_node_id,
        starts_at=node_starts_at,
    )
    session.add(node)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "insert_node", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="insert",
        actor=actor,
        before=None,
        after=_snapshot_node(node),
    )
    # First thing on the timeline pins Day 1's identity (ADV-16).
    if node.starts_at is not None:
        await _maybe_stamp_days_anchor(session, itinerary_id)
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "insert_node",
            "node_id": str(node.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return node


async def update_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    **fields: Any,
) -> Node | ItineraryError:
    """Update a node + capture before/after snapshots in history.

    Only a small whitelist of fields can be changed through this path — the
    primary key, itinerary_id, and timestamps are never mutable.
    """
    node = (
        await session.execute(
            select(Node).where(
                Node.id == node_id,
                Node.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if node is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    allowed = {
        "type",
        "status",
        "title",
        "source",
        "source_id",
        "metadata",
        "cost_amount",
        "cost_currency",
        "cost_kind",
    }
    updates: dict[str, Any] = {k: v for k, v in fields.items() if k in allowed}
    mutates_other_fields = any(key != "status" for key in updates)

    # Pure status flips (traveler approval / discard, advisor demotion) are the
    # one write a trunk accepts directly — everything else must go via a fork.
    lock_err = await _check_write_gates(
        session,
        itinerary_id,
        actor,
        pure_status_change=bool(updates) and not mutates_other_fields,
        trunk_exempt=node.type is NodeType.note or not is_schedulable(node.type),
    )
    if lock_err is not None:
        return lock_err

    if not updates:
        return node  # No-op update is idempotent — don't write history.

    # Status gate (G1): a firmed node is immutable except for an advisor's pure
    # status change. ``node.status`` here is the CURRENT (pre-update) status.
    status_err = _check_status_gate(
        current_status=node.status,
        actor=actor,
        mutates_other_fields=mutates_other_fields,
    )
    if status_err is not None:
        return status_err

    # Money gate (M005/I3): promotion INTO booked/confirmed is not a free graph
    # edit — it must go through ``services.bookings`` (a covering paid invoice
    # line, a fresh flight offer, a recorded booking). Refuse a direct flip here
    # so the gate can't be bypassed via update_node. Demotions OUT of those
    # statuses stay on this path (the advisor cancellation escape hatch).
    if "status" in updates:
        target = NodeStatus(updates["status"])
        if target in _GATED_PROMOTION_STATUSES and node.status != target:
            return ItineraryError(
                outcome=ItineraryOutcome.CONFLICT,
                detail="use_booking_flow",
            )

    new_source = updates.get("source", node.source)
    new_source_id = updates.get("source_id", node.source_id)
    prov_err = _check_provenance(new_source, new_source_id)
    if prov_err is not None:
        return prov_err

    # Price is advisor-authored (M005) — refuse a non-advisor cost mutation even
    # on their own fork, before the together-ness check below.
    cost_auth_err = _check_cost_authority(updates, node, actor)
    if cost_auth_err is not None:
        return cost_auth_err

    new_cost_amount = updates.get("cost_amount", node.cost_amount)
    new_cost_currency = updates.get("cost_currency", node.cost_currency)
    cost_err = _check_cost(new_cost_amount, new_cost_currency)
    if cost_err is not None:
        return cost_err

    before = _snapshot_node(node)
    for key, value in updates.items():
        if key == "metadata":
            node.metadata_ = value
        else:
            setattr(node, key, value)

    # Keep the starts_at column in sync with metadata.start_time on a metadata
    # patch (the web `moveNode` / agent `move_node` schedule by writing the full
    # merged metadata, start_time included). Applies to EVERY node type: a
    # present start schedules the node (mirrored into the tstzrange column); an
    # absent/blank start un-schedules it — clearing the column so the card
    # returns to the Collection instead of a stale starts_at keeping it pinned to
    # the timeline (the read serializer + web adapter fall back to the column).
    # Attached notes ride a host and carry no own time, so they're left alone.
    if (
        "metadata" in updates
        and isinstance(node.metadata_, dict)
        and not (node.type is NodeType.note and node.attached_to_node_id is not None)
    ):
        iso = node.metadata_.get("start_time")
        # A non-schedulable card (article) can never take a time — reject the
        # drag-to-timeline gesture instead of pinning a reading-list item.
        if isinstance(iso, str) and iso and not is_schedulable(node.type):
            return ItineraryError(
                outcome=ItineraryOutcome.VALIDATION_ERROR,
                detail=f"{node.type.value} nodes are not schedulable",
            )
        if isinstance(iso, str) and iso:
            dur = node.metadata_.get("duration_minutes")
            rng = _build_starts_at(iso, dur if isinstance(dur, int) else None)
            if rng is not None:
                node.starts_at = rng
                # Refresh the mirrored offset so the read serializer reconstructs
                # the wall-clock the caller sent, even on a partial metadata patch
                # that dropped tz_offset_minutes.
                offset = rng.lower.utcoffset() if rng.lower is not None else None
                if offset is not None:
                    node.metadata_ = {
                        **node.metadata_,
                        "tz_offset_minutes": int(offset.total_seconds() // 60),
                    }
        else:
            node.starts_at = None

    # A metadata patch is the drag-to-timeline path — the first card scheduled
    # pins Day 1's identity (ADV-16). No-op once the anchor is stamped.
    if "metadata" in updates and node.starts_at is not None:
        await _maybe_stamp_days_anchor(session, itinerary_id)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "update_node", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="update",
        actor=actor,
        before=before,
        after=_snapshot_node(node),
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "update_node",
            "node_id": str(node.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return node


async def delete_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
) -> ItineraryError | None:
    """Delete a node + write a history row with the pre-delete snapshot."""
    node = (
        await session.execute(
            select(Node).where(
                Node.id == node_id,
                Node.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if node is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_write_gates(
        session,
        itinerary_id,
        actor,
        trunk_exempt=node.type is NodeType.note or not is_schedulable(node.type),
    )
    if lock_err is not None:
        return lock_err

    # Status gate (G1): a firmed node is a commitment (approved/booked/confirmed)
    # and can't be deleted by anyone — even an advisor demotes it to a pre-firmed
    # status (cancellation → discarded) first so a booking's history lineage is
    # never silently destroyed. Notes are the exception: a note is feedback, not
    # a plan commitment, so a user may remove ANY of their notes whatever its
    # status. Everything else (regular cards, collection items) is deletable only
    # while pre-firmed — exactly the "delete things that aren't approved/booked".
    if node.type is not NodeType.note and node.status in _FIRMED_STATUSES:
        return ItineraryError(
            outcome=ItineraryOutcome.STATUS_LOCKED,
            detail="demote_before_delete",
        )

    # Soft delete: stamp ``deleted_at`` on the node AND its whole dependent
    # subtree — subgraph descendants (parent_subgraph_id) and attached notes
    # (attached_to_node_id), recursively — the same set the old ON DELETE CASCADE
    # removed. The row + its node_history lineage survive, but every graph read
    # (all of which filter ``deleted_at is null``) drops exactly this subtree, so
    # nothing dangles. ``union`` (distinct) guards against any FK cycle; the
    # ``deleted_at is null`` guard makes a repeat delete affect zero rows.
    before = _snapshot_node(node)
    stamped = (
        (
            await session.execute(
                text(
                    """
                    with recursive doomed(id) as (
                        select cast(:nid as uuid)
                      union
                        select n.id
                          from public.nodes n
                          join doomed d
                            on n.parent_subgraph_id = d.id
                            or n.attached_to_node_id = d.id
                         where n.itinerary_id = :iid
                    )
                    update public.nodes
                       set deleted_at = now()
                     where id in (select id from doomed)
                       and deleted_at is null
                    returning id
                    """
                ),
                {"nid": node_id, "iid": itinerary_id},
            )
        )
        .scalars()
        .all()
    )
    # Nothing stamped → the node (and its subtree) were already tombstoned. Skip
    # the history row so a repeat delete is a true idempotent no-op. (We trust the
    # UPDATE's RETURNING, not the ORM's ``node.deleted_at``, which a prior raw
    # UPDATE in this same session would have left stale.)
    if not stamped:
        return None
    await session.flush()
    await _write_node_history(
        session,
        node_id=node_id,
        itinerary_id=itinerary_id,
        op="delete",
        actor=actor,
        before=before,
        after=None,
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "delete_node",
            "node_id": str(node_id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return None


async def add_edge(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    from_node_id: uuid.UUID,
    to_node_id: uuid.UUID,
    type: EdgeType,
    metadata: dict[str, Any] | None = None,
) -> Edge | ItineraryError:
    """Insert an edge + its history row. The DB enforces no self-loops."""
    itinerary_exists = (
        await session.execute(select(Itinerary.id).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary_exists is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_write_gates(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    edge = Edge(
        itinerary_id=itinerary_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        type=type,
        metadata_=metadata or {},
    )
    session.add(edge)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "insert_edge", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_edge_history(
        session,
        edge_id=edge.id,
        itinerary_id=itinerary_id,
        op="insert",
        actor=actor,
        before=None,
        after=_snapshot_edge(edge),
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "insert_edge",
            "edge_id": str(edge.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return edge


async def delete_edge(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    edge_id: uuid.UUID,
) -> ItineraryError | None:
    edge = (
        await session.execute(
            select(Edge).where(
                Edge.id == edge_id,
                Edge.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if edge is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_write_gates(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    before = _snapshot_edge(edge)
    # Use a Core delete so we don't need to load relationships.
    await session.execute(delete(Edge).where(Edge.id == edge_id))
    await session.flush()
    await _write_edge_history(
        session,
        edge_id=edge_id,
        itinerary_id=itinerary_id,
        op="delete",
        actor=actor,
        before=before,
        after=None,
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "delete_edge",
            "edge_id": str(edge_id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return None


async def acquire_lock(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Take the editor-session lock for ``itinerary_id``.

    Succeeds if the itinerary is either unlocked or already locked by the
    same user (same-user re-acquire is idempotent). Advisor-only — the
    router layer enforces that guard before calling here.
    """
    stmt = (
        update(Itinerary)
        .where(
            Itinerary.id == itinerary_id,
            or_(
                Itinerary.locked_by.is_(None),
                Itinerary.locked_by == actor.user_id,
            ),
        )
        .values(locked_by=actor.user_id, locked_at=func.now())
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        await session.rollback()
        logger.info(
            "itinerary.lock.rejected",
            extra={
                "itinerary_id": str(itinerary_id),
                "sub_hint": (actor.actor_id or "")[:8],
            },
        )
        return ItineraryError(
            outcome=ItineraryOutcome.LOCKED,
            detail="already_locked",
        )
    await session.commit()
    await session.refresh(row)
    logger.info(
        "itinerary.lock.acquired",
        extra={
            "itinerary_id": str(itinerary_id),
            "user_id": str(actor.user_id) if actor.user_id else None,
        },
    )
    return row


async def release_lock(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Release the editor-session lock held by ``actor``.

    Idempotent: if the caller doesn't hold the lock (including the already-
    unlocked case), returns the current row unchanged — not an error.
    """
    stmt = (
        update(Itinerary)
        .where(
            Itinerary.id == itinerary_id,
            Itinerary.locked_by == actor.user_id,
        )
        .values(locked_by=None, locked_at=None)
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        current = (
            await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
        ).scalar_one_or_none()
        if current is None:
            return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
        return current
    await session.commit()
    await session.refresh(row)
    logger.info(
        "itinerary.lock.released",
        extra={
            "itinerary_id": str(itinerary_id),
            "queue_depth_drained": 0,
        },
    )
    return row


async def assemble_initial_draft(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    day_plan: list[DaySlot],
) -> GraphView | ItineraryError:
    """Wire the ordered ``follows`` edges between proposed nodes of an itinerary.

    Pre-conditions enforced here:
      1. The itinerary row exists (NOT_FOUND otherwise).
      2. Every ``node_id`` referenced across the day_plan belongs to
         ``itinerary_id`` AND currently has ``status='pending'``. A stray
         ``status='discarded'`` or cross-itinerary id collapses the whole
         call to VALIDATION_ERROR — we do not partially assemble.

    Effect: within each ``DaySlot`` we append a ``follows`` edge between each
    consecutive pair of node ids. Slots of length 0 or 1 are a no-op.
    Nodes keep their ``pending`` status; approval is the traveler's separate
    per-node (or approve-all) gesture on the trunk.

    Returns a fresh :class:`GraphView` assembled via
    :func:`get_itinerary_graph` so the caller can hand it straight to the
    router layer.
    """
    itinerary_exists = (
        await session.execute(select(Itinerary.id).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary_exists is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_write_gates(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    referenced_ids: list[uuid.UUID] = []
    for slot in day_plan:
        referenced_ids.extend(slot["node_ids_in_order"])

    if referenced_ids:
        rows = (
            await session.execute(
                select(Node.id, Node.itinerary_id, Node.status).where(Node.id.in_(referenced_ids))
            )
        ).all()
        by_id = {row.id: row for row in rows}
        for nid in referenced_ids:
            row = by_id.get(nid)
            if row is None or row.itinerary_id != itinerary_id:
                return ItineraryError(
                    outcome=ItineraryOutcome.VALIDATION_ERROR,
                    detail="node_not_in_itinerary",
                )
            if row.status != NodeStatus.pending:
                return ItineraryError(
                    outcome=ItineraryOutcome.VALIDATION_ERROR,
                    detail="node_not_pending",
                )

    edge_count = 0
    for slot in day_plan:
        ordered = slot["node_ids_in_order"]
        for left, right in zip(ordered, ordered[1:], strict=False):
            edge = Edge(
                itinerary_id=itinerary_id,
                from_node_id=left,
                to_node_id=right,
                type=EdgeType.follows,
                metadata_={},
            )
            session.add(edge)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                logger.info(
                    "itinerary.mutate.integrity_error",
                    extra={"op": "assemble_edge", "reason": str(exc.orig)},
                )
                return ItineraryError(
                    outcome=ItineraryOutcome.VALIDATION_ERROR,
                    detail=_integrity_detail(exc),
                )
            await _write_edge_history(
                session,
                edge_id=edge.id,
                itinerary_id=itinerary_id,
                op="insert",
                actor=actor,
                before=None,
                after=_snapshot_edge(edge),
            )
            edge_count += 1

    await session.commit()

    view = await get_itinerary_graph(session, itinerary_id)
    if isinstance(view, ItineraryError):
        return view

    logger.info(
        "itinerary.assemble_initial_draft",
        extra={
            "itinerary_id": str(itinerary_id),
            "node_count": len(view.nodes),
            "edge_count": edge_count,
        },
    )
    return view


@dataclass(frozen=True, slots=True)
class ApproveAllResult:
    """Outcome of the approve-all gesture: how many flipped + the fresh graph."""

    approved_count: int
    view: GraphView


async def approve_all_nodes(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> ApproveAllResult | ItineraryError:
    """Approve every pending approvable node on a trunk — the "Approve all" gesture.

    The traveler's (or advisor-on-behalf) bulk action replacing the old
    itinerary-level approve: flips each approvable ``pending`` node to
    ``approved``, writing a per-node history row (the audit contract — no
    blind bulk UPDATE). Annotation kinds (note/waiting/free_time), discarded
    nodes, and deselected alternatives are untouched — see
    :mod:`app.services.display_status` for the shared approvability rule.

    Only meaningful on an official trunk: a fork is a working copy with
    nothing to approve (CONFLICT / ``not_a_trunk``). Idempotent — zero
    pending approvable nodes is a successful no-op. The caller's entitlement
    to the itinerary is enforced by the route's writability gate.
    """
    trunk_row = (
        await session.execute(select(Itinerary.forked_from_id).where(Itinerary.id == itinerary_id))
    ).one_or_none()
    if trunk_row is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if trunk_row[0] is not None:
        return ItineraryError(outcome=ItineraryOutcome.CONFLICT, detail="not_a_trunk")

    # Approval is a pure status change, so the trunk guard admits it; the
    # editor lock still applies to non-advisors.
    lock_err = await _check_write_gates(session, itinerary_id, actor, pure_status_change=True)
    if lock_err is not None:
        return lock_err

    nodes = (
        (
            await session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary_id,
                    Node.deleted_at.is_(None),
                    Node.status == NodeStatus.pending,
                    Node.type.not_in(NON_APPROVABLE_TYPES),
                    Node.is_selected_alt.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for node in nodes:
        before = _snapshot_node(node)
        node.status = NodeStatus.approved
        await session.flush()
        await _write_node_history(
            session,
            node_id=node.id,
            itinerary_id=itinerary_id,
            op="update",
            actor=actor,
            before=before,
            after=_snapshot_node(node),
        )
    await session.commit()

    view = await get_itinerary_graph(session, itinerary_id)
    if isinstance(view, ItineraryError):
        return view

    logger.info(
        "itinerary.approve_all",
        extra={
            "itinerary_id": str(itinerary_id),
            "user_id": str(actor.user_id) if actor.user_id else None,
            "approved_count": len(nodes),
        },
    )
    return ApproveAllResult(approved_count=len(nodes), view=view)


def _integrity_detail(exc: IntegrityError) -> str:
    """Extract a stable, caller-useful reason string from a DB error.

    We surface the constraint name when we can see it (nodes_provenance_complete,
    edges_no_self_loop, …) because the slice plan's failure-visibility note
    says the constraint name must be visible in the error.
    """
    msg = str(getattr(exc, "orig", exc))
    for name in (
        "nodes_provenance_complete",
        "nodes_cost_amount_currency_together",
        "edges_no_self_loop",
    ):
        if name in msg:
            return name
    return "integrity_error"
