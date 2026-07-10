"""Derived itinerary display status (0044) — the shared bucketing rule.

Three layers over :mod:`app.services.display_status`:

1. Pure ``bucket`` boundary tests (no DB).
2. ``bucket_from_nodes`` over hand-built ORM rows — the approvability rule:
   annotation kinds (note/waiting/free_time), discarded nodes, soft-deleted
   rows, and deselected alternatives never count.
3. A DB test asserting the SQL form (``display_status_expr()``) agrees with
   the Python form for a seeded itinerary with a mix of statuses/types —
   the "every consumer shares one definition" contract.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.models import Itinerary, Node, NodeStatus, NodeType
from app.services.display_status import (
    DisplayStatus,
    bucket,
    bucket_from_nodes,
    display_status_expr,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration

# ── Pure: bucket boundaries ──────────────────────────────────────────────────


def test_bucket_no_approvable_content_is_in_studio() -> None:
    assert bucket(pending_count=0, approvable_count=0) is DisplayStatus.in_studio


def test_bucket_any_pending_approvable_is_with_traveler() -> None:
    assert bucket(pending_count=1, approvable_count=1) is DisplayStatus.with_traveler
    assert bucket(pending_count=1, approvable_count=5) is DisplayStatus.with_traveler
    assert bucket(pending_count=5, approvable_count=5) is DisplayStatus.with_traveler


def test_bucket_all_actioned_is_approved() -> None:
    assert bucket(pending_count=0, approvable_count=1) is DisplayStatus.approved
    assert bucket(pending_count=0, approvable_count=7) is DisplayStatus.approved


# ── Pure: bucket_from_nodes + the approvability rule ─────────────────────────


def _node(
    *,
    type_: NodeType = NodeType.experience,
    status: NodeStatus = NodeStatus.pending,
    deleted_at: datetime | None = None,
    is_selected_alt: bool = True,
) -> Node:
    return Node(
        id=uuid.uuid4(),
        itinerary_id=uuid.uuid4(),
        type=type_,
        status=status,
        title="",
        metadata_={},
        deleted_at=deleted_at,
        is_selected_alt=is_selected_alt,
    )


def test_bucket_from_nodes_empty_is_in_studio() -> None:
    assert bucket_from_nodes([]) is DisplayStatus.in_studio


def test_bucket_from_nodes_pending_then_approved() -> None:
    pending = _node(status=NodeStatus.pending)
    approved = _node(status=NodeStatus.approved)
    assert bucket_from_nodes([pending, approved]) is DisplayStatus.with_traveler
    assert bucket_from_nodes([approved]) is DisplayStatus.approved
    booked = _node(status=NodeStatus.booked)
    confirmed = _node(status=NodeStatus.confirmed)
    assert bucket_from_nodes([approved, booked, confirmed]) is DisplayStatus.approved


@pytest.mark.parametrize("kind", [NodeType.note, NodeType.waiting, NodeType.free_time])
def test_bucket_from_nodes_excludes_annotation_kinds(kind: NodeType) -> None:
    """A pending note/waiting/free_time never holds a trip out of in_studio…"""
    assert bucket_from_nodes([_node(type_=kind)]) is DisplayStatus.in_studio
    # …nor out of approved once the real content is actioned.
    real = _node(status=NodeStatus.approved)
    assert bucket_from_nodes([real, _node(type_=kind)]) is DisplayStatus.approved


def test_bucket_from_nodes_excludes_discarded() -> None:
    discarded = _node(status=NodeStatus.discarded)
    assert bucket_from_nodes([discarded]) is DisplayStatus.in_studio
    approved = _node(status=NodeStatus.approved)
    assert bucket_from_nodes([approved, discarded]) is DisplayStatus.approved


def test_bucket_from_nodes_excludes_soft_deleted() -> None:
    tombstoned = _node(deleted_at=datetime.now(UTC))
    assert bucket_from_nodes([tombstoned]) is DisplayStatus.in_studio
    approved = _node(status=NodeStatus.approved)
    assert bucket_from_nodes([approved, tombstoned]) is DisplayStatus.approved


def test_bucket_from_nodes_excludes_deselected_alternatives() -> None:
    """A rejected option B must not hold the trip in with_traveler after the
    traveler approved option A."""
    option_a = _node(status=NodeStatus.approved)
    option_b = _node(status=NodeStatus.pending, is_selected_alt=False)
    assert bucket_from_nodes([option_a, option_b]) is DisplayStatus.approved
    assert bucket_from_nodes([option_b]) is DisplayStatus.in_studio


# ── DB: display_status_expr() agrees with bucket_from_nodes ─────────────────


async def _cleanup(itinerary_id: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.itineraries where id = :i"), {"i": itinerary_id}
            )
    finally:
        await engine.dispose()


async def _sql_bucket(session: AsyncSession, itinerary_id: uuid.UUID) -> DisplayStatus:
    value = (
        await session.execute(
            select(display_status_expr()).select_from(Itinerary).where(Itinerary.id == itinerary_id)
        )
    ).scalar_one()
    return DisplayStatus(value)


async def _python_bucket(session: AsyncSession, itinerary_id: uuid.UUID) -> DisplayStatus:
    nodes = (
        (await session.execute(select(Node).where(Node.itinerary_id == itinerary_id)))
        .scalars()
        .all()
    )
    return bucket_from_nodes(nodes)


@integration
async def test_sql_and_python_forms_agree_for_a_mixed_itinerary() -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    iid: uuid.UUID | None = None
    try:
        async with maker() as s:
            iid = await insert_itinerary(s, title="display-status mix")

            # Nothing yet → in_studio, both forms.
            assert await _sql_bucket(s, iid) is DisplayStatus.in_studio
            assert await _python_bucket(s, iid) is DisplayStatus.in_studio

            # Only excluded rows (annotation kind, discarded, deselected alt,
            # soft-deleted) → still in_studio.
            await insert_node(s, itinerary_id=iid, type="note", title="ann")
            await insert_node(s, itinerary_id=iid, type="waiting", title="layover")
            await insert_node(s, itinerary_id=iid, type="free_time", title="gap")
            await insert_node(s, itinerary_id=iid, type="meal", status="discarded", title="no")
            await insert_node(
                s, itinerary_id=iid, type="hotel", title="option-b", is_selected_alt=False
            )
            ghost = await insert_node(s, itinerary_id=iid, type="experience", title="ghost")
            await s.execute(
                text("update public.nodes set deleted_at = now() where id = :n"), {"n": ghost}
            )
            await s.commit()
            assert await _sql_bucket(s, iid) is DisplayStatus.in_studio
            assert await _python_bucket(s, iid) is DisplayStatus.in_studio

            # One pending approvable card → with_traveler.
            pending = await insert_node(s, itinerary_id=iid, type="experience", title="card")
            await insert_node(s, itinerary_id=iid, type="flight", status="booked", title="jl15")
            assert await _sql_bucket(s, iid) is DisplayStatus.with_traveler
            assert await _python_bucket(s, iid) is DisplayStatus.with_traveler

            # Action the last pending card → approved (excluded rows untouched).
            await s.execute(
                text("update public.nodes set status = 'approved' where id = :n"),
                {"n": pending},
            )
            await s.commit()
            assert await _sql_bucket(s, iid) is DisplayStatus.approved
            assert await _python_bucket(s, iid) is DisplayStatus.approved
    finally:
        await engine.dispose()
        if iid is not None:
            await _cleanup(iid)
