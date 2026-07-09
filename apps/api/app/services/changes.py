"""Itinerary change replay — the graph's audit trail, projected (Wave F).

``GET /itinerary/{id}/changes`` walks ``node_history`` + ``edge_history``
newest-first with a keyset cursor (served by 0042's itinerary-scoped indexes).
The response is a *projection*: op, actor attribution, title, the status
transition, and which keys changed — never the raw before/after JSONB (node
metadata can carry free text; replay needs the shape of the change, not its
payload).

Total order ``(occurred_at DESC, entity ASC, id DESC)`` — entity breaks the
cross-table tie ("edge" < "node" alphabetically), the BigInt id breaks
same-instant ties within a table, newest-id-first to match occurred_at's
direction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgeHistory, NodeHistory
from app.services.pagination import encode_cursor

Entity = Literal["node", "edge"]


@dataclass(frozen=True, slots=True)
class Change:
    """One projected history row."""

    id: str  # "node:123" / "edge:45" — BigInt ids collide across tables
    entity: Entity
    entity_id: uuid.UUID
    op: str
    actor_kind: str
    actor_user_id: uuid.UUID | None
    occurred_at: datetime
    title: str | None
    status_before: str | None
    status_after: str | None
    changed_keys: list[str]


def diff_changed_keys(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    """Keys whose value differs between the two snapshots (either side missing
    counts), sorted for a stable response. Pure — the replay affordance."""
    before = before or {}
    after = after or {}
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def _row_key(change: Change) -> tuple[float, str, int]:
    raw_id = int(change.id.split(":", 1)[1])
    return (-change.occurred_at.timestamp(), change.entity, -raw_id)


def next_changes_cursor(changes: list[Change], limit: int) -> str | None:
    if len(changes) < limit or not changes:
        return None
    last = changes[-1]
    return encode_cursor(
        {
            "at": last.occurred_at.isoformat(),
            "entity": last.entity,
            "id": int(last.id.split(":", 1)[1]),
        }
    )


async def load_itinerary_changes(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    limit: int,
    cursor: dict[str, object] | None = None,
    entity: Entity | None = None,
) -> list[Change]:
    """One merged page of node+edge history for an itinerary, newest-first."""
    changes: list[Change] = []

    def _windowed(stmt: Select[Any], ent: Entity, at_col: Any, id_col: Any) -> Select[Any]:
        if cursor is not None:
            cur_at = datetime.fromisoformat(str(cursor["at"]))
            cur_entity = str(cursor["entity"])
            cur_id = int(str(cursor["id"]))
            if ent == cur_entity:
                stmt = stmt.where(or_(at_col < cur_at, and_(at_col == cur_at, id_col < cur_id)))
            elif ent > cur_entity:  # "node" > "edge": ties at cur_at come after
                stmt = stmt.where(at_col <= cur_at)
            else:
                stmt = stmt.where(at_col < cur_at)
        return stmt.order_by(at_col.desc(), id_col.desc()).limit(limit)

    if entity in (None, "node"):
        stmt = select(
            NodeHistory.id,
            NodeHistory.node_id,
            NodeHistory.op,
            NodeHistory.actor_kind,
            NodeHistory.actor_user_id,
            NodeHistory.before,
            NodeHistory.after,
            NodeHistory.occurred_at,
        ).where(NodeHistory.itinerary_id == itinerary_id)
        rows = (
            await session.execute(_windowed(stmt, "node", NodeHistory.occurred_at, NodeHistory.id))
        ).all()
        for hid, nid, op, actor_kind, actor_uid, before, after, at in rows:
            before = before or {}
            after = after or {}
            changes.append(
                Change(
                    id=f"node:{hid}",
                    entity="node",
                    entity_id=nid,
                    op=op,
                    actor_kind=actor_kind,
                    actor_user_id=actor_uid,
                    occurred_at=at,
                    title=after.get("title") or before.get("title"),
                    status_before=before.get("status"),
                    status_after=after.get("status"),
                    changed_keys=diff_changed_keys(before, after),
                )
            )

    if entity in (None, "edge"):
        stmt = select(
            EdgeHistory.id,
            EdgeHistory.edge_id,
            EdgeHistory.op,
            EdgeHistory.actor_kind,
            EdgeHistory.actor_user_id,
            EdgeHistory.before,
            EdgeHistory.after,
            EdgeHistory.occurred_at,
        ).where(EdgeHistory.itinerary_id == itinerary_id)
        rows = (
            await session.execute(_windowed(stmt, "edge", EdgeHistory.occurred_at, EdgeHistory.id))
        ).all()
        for hid, eid, op, actor_kind, actor_uid, before, after, at in rows:
            before = before or {}
            after = after or {}
            changes.append(
                Change(
                    id=f"edge:{hid}",
                    entity="edge",
                    entity_id=eid,
                    op=op,
                    actor_kind=actor_kind,
                    actor_user_id=actor_uid,
                    occurred_at=at,
                    title=None,
                    status_before=None,
                    status_after=None,
                    changed_keys=diff_changed_keys(before, after),
                )
            )

    changes.sort(key=_row_key)
    return changes[:limit]
