"""Derived itinerary display status — the trunk's lifecycle, computed at read.

With the stored itinerary_status gone (0044), where a trip stands is derived
from its nodes' statuses and branch topology:

- ``in_studio`` — no approvable content on the trunk yet (nothing published,
  or only structural/annotation nodes). The traveler-facing teaser state.
- ``with_traveler`` — at least one approvable node is still ``pending``:
  published content awaiting the traveler's disposition.
- ``approved`` — approvable content exists and every approvable node has been
  actioned (approved / booked / confirmed).

"Approvable" scopes the rule to nodes a traveler actually dispositions:
annotation/filler kinds (``note``, ``waiting``, ``free_time``), discarded
nodes, soft-deleted rows, and *deselected alternatives* are all excluded —
a rejected option B must not hold a trip in ``with_traveler`` after the
traveler approved option A.

Only meaningful for trunks (``forked_from_id IS NULL``); a fork is a working
copy and doesn't carry a lifecycle. Exposed in three forms so every consumer
shares one definition: pure counts (:func:`bucket`), loaded ORM rows
(:func:`bucket_from_nodes`), and SQL expressions (:func:`display_status_expr`
and the count subqueries) for roster list filters and grouped dashboard
counts that must stay in the database.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable

from sqlalchemy import ColumnElement, Select, case, func, select

from app.models import Itinerary, Node, NodeStatus, NodeType

NON_APPROVABLE_TYPES: frozenset[NodeType] = frozenset(
    {NodeType.note, NodeType.waiting, NodeType.free_time}
)


class DisplayStatus(str, enum.Enum):
    """Derived trunk lifecycle bucket (never stored)."""

    in_studio = "in_studio"
    with_traveler = "with_traveler"
    approved = "approved"


def is_approvable(node: Node) -> bool:
    """Whether this node participates in approval counts (see module doc)."""
    return (
        node.type not in NON_APPROVABLE_TYPES
        and node.status != NodeStatus.discarded
        and node.deleted_at is None
        and node.is_selected_alt
    )


def bucket(*, pending_count: int, approvable_count: int) -> DisplayStatus:
    """Pure bucketing rule over pre-computed approvable-node counts."""
    if approvable_count == 0:
        return DisplayStatus.in_studio
    if pending_count > 0:
        return DisplayStatus.with_traveler
    return DisplayStatus.approved


def bucket_from_nodes(nodes: Iterable[Node]) -> DisplayStatus:
    """Bucket from already-loaded ORM nodes (detail responses; no extra query)."""
    approvable = 0
    pending = 0
    for node in nodes:
        if not is_approvable(node):
            continue
        approvable += 1
        if node.status == NodeStatus.pending:
            pending += 1
    return bucket(pending_count=pending, approvable_count=approvable)


def _approvable_nodes() -> Select[tuple[int]]:
    """Correlated count of the itinerary's approvable nodes."""
    return (
        select(func.count(Node.id))
        .where(
            Node.itinerary_id == Itinerary.id,
            Node.deleted_at.is_(None),
            Node.status != NodeStatus.discarded,
            Node.type.not_in(NON_APPROVABLE_TYPES),
            Node.is_selected_alt.is_(True),
        )
        .correlate(Itinerary)
    )


def approvable_count_sq() -> ColumnElement[int]:
    """Scalar subquery: total approvable nodes for the correlated itinerary."""
    return _approvable_nodes().scalar_subquery()


def pending_count_sq() -> ColumnElement[int]:
    """Scalar subquery: approvable nodes still pending for the correlated itinerary."""
    return _approvable_nodes().where(Node.status == NodeStatus.pending).scalar_subquery()


def display_status_expr() -> ColumnElement[str]:
    """The bucketing rule as a SQL ``case()`` — usable in SELECT, WHERE, GROUP BY.

    Keep the count subqueries in the SELECT list alongside this when paging a
    roster, so the WHERE filter doesn't re-run them per row.
    """
    return case(
        (approvable_count_sq() == 0, DisplayStatus.in_studio.value),
        (pending_count_sq() > 0, DisplayStatus.with_traveler.value),
        else_=DisplayStatus.approved.value,
    )


__all__ = [
    "NON_APPROVABLE_TYPES",
    "DisplayStatus",
    "approvable_count_sq",
    "bucket",
    "bucket_from_nodes",
    "display_status_expr",
    "is_approvable",
    "pending_count_sq",
]
