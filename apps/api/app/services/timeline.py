"""Server-side linearization service — TravelGraph Phase 3.

Walks a single itinerary's graph and returns an ordered list of cards
the renderer / agent / analyses can fold over without re-deriving the
ordering each time. Today both prototype frontends compute their own
order from `metadata.start_time` strings, which means each surface
drifts. This service is the one place that knows:

- How to skip graph-structural markers (``node_role IS NOT NULL`` —
  destinations and termini are headers / sync points, not cards).
- Which alternatives are "the plan" (``is_selected_alt``). Renderers
  can ask for all branches; analyses default to the selected one.
- How to scope to a single party's timeline (``node_parties``). Nodes
  with no party rows are conventionally "all parties" — Meld and
  Extract both ride that default.
- How to nest dual-mode notes: attached notes ride their host's
  anchor, free-standing notes appear in the main timeline at their
  own ``starts_at``.

The function returns a :class:`TimelineView` with cards in display
order plus a ``position`` index so callers can refer to "card 3 of 12"
without re-counting. Each card carries its parsed
:class:`CardAttributes` so downstream consumers don't re-hit the
schema layer.

Scope discipline: this slice is read-only. Writing back into the
graph (Phase 4 service updates) and the on-demand Analyze pipeline
(Phase 5) come later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NodeRole, NodeStatus, NodeType
from app.schemas.card_attrs import CardAttributes, parse_card_attrs


@dataclass(frozen=True, slots=True)
class Card:
    """One card in a linearized timeline.

    Attributes mirror the storage row plus parsed
    :class:`CardAttributes` and the in-list ``position``. Attached notes
    are nested directly so the renderer can show them inline without a
    second round-trip.
    """

    node_id: uuid.UUID
    type: NodeType
    status: NodeStatus
    title: str
    role: NodeRole | None
    is_selected_alt: bool
    starts_at_lower: datetime | None
    starts_at_upper: datetime | None
    altitude_m: int | None
    attached_to_node_id: uuid.UUID | None
    attrs: CardAttributes
    attached_notes: list[Card] = field(default_factory=list)
    position: int = 0


@dataclass(frozen=True, slots=True)
class TimelineView:
    """The result of linearizing one itinerary.

    ``party_id`` is the filter that produced this view (None = no
    filter, returning every node visible to the caller). ``cards`` is
    the totally-ordered list — render order, analyzer fold order.
    """

    itinerary_id: uuid.UUID
    party_id: uuid.UUID | None
    cards: list[Card]


_MAIN_SQL = text(
    """
    select
        n.id, n.type, n.status, n.title, n.role, n.is_selected_alt,
        n.altitude_m, n.metadata, n.attached_to_node_id,
        lower(n.starts_at) as starts_at_lower,
        upper(n.starts_at) as starts_at_upper
    from public.nodes n
    where n.itinerary_id = :iid
      and n.attached_to_node_id is null
      and (cast(:include_structural as boolean) or n.role is null)
      and (not cast(:selected_only as boolean) or n.is_selected_alt)
      and (
          (cast(:t_from as timestamptz) is null
           and cast(:t_to as timestamptz) is null)
          or n.starts_at && tstzrange(
              cast(:t_from as timestamptz),
              cast(:t_to as timestamptz),
              '[)'
          )
      )
      and (
          cast(:party_id as uuid) is null
          or exists (
              select 1 from public.node_parties np
              where np.node_id = n.id
                and np.party_id = cast(:party_id as uuid)
          )
          or not exists (
              select 1 from public.node_parties np
              where np.node_id = n.id
          )
      )
    order by lower(n.starts_at) asc nulls last, n.created_at asc
    """
)

_ATTACHED_SQL = text(
    """
    select
        n.id, n.type, n.status, n.title, n.role, n.is_selected_alt,
        n.altitude_m, n.metadata, n.attached_to_node_id,
        lower(n.starts_at) as starts_at_lower,
        upper(n.starts_at) as starts_at_upper
    from public.nodes n
    where n.attached_to_node_id = any(:host_ids)
    order by n.attached_to_node_id, n.created_at asc
    """
)


def _build_card(row: Any, *, position: int, attached: list[Card]) -> Card:
    return Card(
        node_id=row["id"],
        type=NodeType(row["type"]),
        status=NodeStatus(row["status"]),
        title=row["title"],
        role=NodeRole(row["role"]) if row["role"] else None,
        is_selected_alt=row["is_selected_alt"],
        starts_at_lower=row["starts_at_lower"],
        starts_at_upper=row["starts_at_upper"],
        altitude_m=row["altitude_m"],
        attached_to_node_id=row["attached_to_node_id"],
        attrs=parse_card_attrs(row["type"], row["metadata"]),
        attached_notes=attached,
        position=position,
    )


async def linearize(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    party_id: uuid.UUID | None = None,
    t_from: datetime | None = None,
    t_to: datetime | None = None,
    selected_branches_only: bool = True,
    include_structural: bool = False,
) -> TimelineView:
    """Return an ordered :class:`TimelineView` for ``itinerary_id``.

    Filters:

    - ``party_id`` — when set, return only nodes that belong to this
      party OR have no party rows at all (the implicit "all" default).
      ``None`` means no party filter.
    - ``t_from`` / ``t_to`` — half-open ``[t_from, t_to)`` window.
      Either bound may be ``None``; the test is a tstzrange overlap so
      a node whose range straddles either edge is included.
    - ``selected_branches_only`` (default ``True``) — drops nodes with
      ``is_selected_alt = false``. Renderers wanting to show every
      branch flip this off.
    - ``include_structural`` (default ``False``) — drops nodes with
      ``role IS NOT NULL`` (destinations + termini). Set true if the
      caller wants header/sync-point markers in the same list.

    Attached notes (``attached_to_node_id IS NOT NULL``) never appear
    in the main list — they're nested under their host card so the
    timeline stays one card per moment.
    """
    rows = (
        (
            await session.execute(
                _MAIN_SQL,
                {
                    "iid": itinerary_id,
                    "party_id": party_id,
                    "t_from": t_from,
                    "t_to": t_to,
                    "selected_only": selected_branches_only,
                    "include_structural": include_structural,
                },
            )
        )
        .mappings()
        .all()
    )

    attached_by_host: dict[uuid.UUID, list[Card]] = {}
    if rows:
        host_ids = [r["id"] for r in rows]
        att_rows = (await session.execute(_ATTACHED_SQL, {"host_ids": host_ids})).mappings().all()
        # Group attached rows by host so each host's notes get a fresh
        # 0-indexed position. Within a host, ordering is by created_at
        # ascending — matches the SQL ORDER BY.
        groups: dict[uuid.UUID, list[Any]] = {}
        for ar in att_rows:
            groups.setdefault(ar["attached_to_node_id"], []).append(ar)
        attached_by_host = {
            host_id: [_build_card(ar, position=i, attached=[]) for i, ar in enumerate(host_rows)]
            for host_id, host_rows in groups.items()
        }

    cards = [
        _build_card(
            row,
            position=i,
            attached=attached_by_host.get(row["id"], []),
        )
        for i, row in enumerate(rows)
    ]

    return TimelineView(
        itinerary_id=itinerary_id,
        party_id=party_id,
        cards=cards,
    )


__all__ = ["Card", "TimelineView", "linearize"]
