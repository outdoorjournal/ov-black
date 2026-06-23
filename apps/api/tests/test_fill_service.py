"""AI Fill service (TravelGraph Phase 6 / B6).

Pure-Python guards for the feasibility helpers + scoring, then integration
(gated on local Supabase) for the full ``fill_gap`` flow: bracketing-node
resolution, the drive-time envelope rejecting an out-of-reach candidate, party
allergen filtering, latest-analysis ``block`` exclusion, the no-analysis and
no-located-anchors (feasibility-unknown) paths, and the degenerate empty gap.

Inventory is served by an in-test ``_FakeProvider`` so candidate coordinates +
allergen tags are fully controlled offline (mirrors the mock-provider posture).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest_asyncio
from app.inventory.registry import (
    InventoryCtx,
    InventoryProvider,
    InventoryProviderRegistry,
)
from app.inventory.schemas import ExperienceItem, InventoryItem, Location, MealItem
from app.models import (
    Analysis,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
    NodeStatus,
    NodeType,
)
from app.services.analyze_runners.common import GraphNode
from app.services.fill import (
    GapWindow,
    _build_proposal,
    _node_types_to_inventory_kinds,
    _party_eval,
    _search_radius_m,
    fill_gap,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import (
    LOCAL_DB_URL,
    insert_itinerary,
    insert_node,
    integration,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# Tokyo anchors: a morning stop ending at 12:00 and an evening stop starting at
# 18:00, leaving a 6h (360 min) gap. Coordinates are real (Tokyo Tower area /
# Shibuya) so haversine distances are realistic.
_PRIOR = (35.6586, 139.7454)
_NEXT = (35.6595, 139.7004)


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, 12, h, m, tzinfo=UTC)


_GAP = GapWindow(start=_at(12), end=_at(18))


# ── in-test inventory provider ──────────────────────────────────────────


class _FakeProvider(InventoryProvider):
    """Returns a fixed item list filtered by ``kinds`` — ignores geo bias, so
    the drive-time envelope (not the provider) is what rejects far candidates."""

    source = "fake"

    def __init__(self, items: list[InventoryItem]) -> None:
        self._items = items

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        ks = set(kinds) if kinds else None
        return [i for i in self._items if ks is None or i.kind in ks]

    async def get_detail(self, *, source_id: str, ctx: InventoryCtx) -> InventoryItem | None:
        return next((i for i in self._items if i.source_id == source_id), None)


def _registry(items: list[InventoryItem]) -> InventoryProviderRegistry:
    reg = InventoryProviderRegistry()
    reg.register(_FakeProvider(items))
    return reg


def _meal(source_id: str, lat: float, lng: float, *, tags: list[str] | None = None) -> MealItem:
    return MealItem(
        source="fake",
        source_id=source_id,
        title=f"Restaurant {source_id}",
        location=Location(lat=lat, lng=lng),
        tags=tags or [],
    )


def _exp(
    source_id: str, lat: float, lng: float, *, tags: list[str] | None = None
) -> ExperienceItem:
    return ExperienceItem(
        source="fake",
        source_id=source_id,
        title=f"Activity {source_id}",
        location=Location(lat=lat, lng=lng),
        tags=tags or [],
    )


# ── pure ─────────────────────────────────────────────────────────────────


def test_node_types_to_inventory_kinds_drops_graph_structure() -> None:
    kinds = _node_types_to_inventory_kinds(
        [NodeType.meal, NodeType.experience, NodeType.free_time, NodeType.subway]
    )
    assert kinds == ["meal", "experience"]  # free_time / subway aren't inventory


def test_search_radius_is_bounded() -> None:
    assert _search_radius_m(1) == 2_000  # tiny gap floors at the min
    assert _search_radius_m(100_000) == 150_000  # huge gap caps at the max
    mid = _search_radius_m(360)  # 6h gap -> ~75 km
    assert 70_000 <= mid <= 80_000


def _graph_node(node_type: NodeType, lat: float, lng: float) -> GraphNode:
    return GraphNode(
        node_id=uuid.uuid4(),
        type=node_type,
        status=NodeStatus.approved,
        title="anchor",
        starts_lower=_at(10),
        starts_upper=_at(11),
        lat=lat,
        lng=lng,
        cost_amount=None,
        metadata={},
    )


def test_party_eval_meal_allergen_is_a_hard_block() -> None:
    item = _meal("m", *_PRIOR, tags=["tree-nut"])
    party_ok, warnings, hard_block = _party_eval(
        item, NodeType.meal, allergens={"tree-nut"}, has_mobility_limit=False
    )
    assert hard_block is True
    assert party_ok is False
    assert "tree-nut" in warnings[0]


def test_party_eval_allergen_only_applies_to_meals() -> None:
    item = _exp("e", *_PRIOR, tags=["tree-nut"])
    party_ok, _warnings, hard_block = _party_eval(
        item, NodeType.experience, allergens={"tree-nut"}, has_mobility_limit=False
    )
    assert hard_block is False
    assert party_ok is True  # allergen tag on an experience isn't a meal allergen


def test_party_eval_mobility_is_a_soft_warning() -> None:
    item = _exp("e", *_PRIOR, tags=["strenuous"])
    party_ok, warnings, hard_block = _party_eval(
        item, NodeType.experience, allergens=set(), has_mobility_limit=True
    )
    assert hard_block is False  # kept, not dropped
    assert party_ok is False
    assert warnings and "mobility" in warnings[0]


def test_build_proposal_scores_feasible_above_tootight_above_nothing() -> None:
    prior = _graph_node(NodeType.experience, *_PRIOR)
    nxt = _graph_node(NodeType.experience, *_NEXT)
    feasible = _build_proposal(
        _meal("near", 35.67, 139.73),
        NodeType.meal,
        gap=_GAP,
        gap_min=360.0,
        prior=prior,
        nxt=nxt,
        party_ok=True,
        warnings=[],
    )
    assert feasible.fits_in_gap is True
    assert feasible.score >= 0.5
    assert feasible.drive_time_in_min is not None and feasible.drive_time_out_min is not None

    # Same candidate, but only a 20-min window -> can't fit -> low score.
    tiny_gap = GapWindow(start=_at(12), end=_at(12, 20))
    too_tight = _build_proposal(
        _meal("near", 35.67, 139.73),
        NodeType.meal,
        gap=tiny_gap,
        gap_min=20.0,
        prior=prior,
        nxt=nxt,
        party_ok=True,
        warnings=[],
    )
    assert too_tight.fits_in_gap is False
    assert too_tight.score < feasible.score


def test_build_proposal_downranks_a_meal_right_after_a_meal() -> None:
    prior = _graph_node(NodeType.experience, *_PRIOR)
    nxt = _graph_node(NodeType.experience, *_NEXT)
    # A meal node ending exactly when the gap opens — "you just ate".
    prior_meal = GraphNode(
        node_id=uuid.uuid4(),
        type=NodeType.meal,
        status=NodeStatus.approved,
        title="Lunch",
        starts_lower=_at(11),
        starts_upper=_at(12),
        lat=_PRIOR[0],
        lng=_PRIOR[1],
        cost_amount=None,
        metadata={},
    )

    def _meal_score(prior_neighbor: GraphNode | None) -> float:
        return _build_proposal(
            _meal("near", 35.67, 139.73),
            NodeType.meal,
            gap=_GAP,
            gap_min=360.0,
            prior=prior,
            nxt=nxt,
            party_ok=True,
            warnings=[],
            prior_neighbor=prior_neighbor,
            next_neighbor=None,
        )

    after_meal = _meal_score(prior_meal)
    after_activity = _meal_score(_graph_node(NodeType.experience, *_PRIOR))
    assert after_meal.score < after_activity.score
    assert after_meal.score < 0.5  # excluded by the default min_score
    assert "meal is already scheduled" in after_meal.rationale


def test_build_proposal_does_not_downrank_an_activity_after_a_meal() -> None:
    prior = _graph_node(NodeType.experience, *_PRIOR)
    nxt = _graph_node(NodeType.experience, *_NEXT)
    prior_meal = _graph_node(NodeType.meal, *_PRIOR)  # cooldown is meal→meal only
    p = _build_proposal(
        _exp("near", 35.67, 139.73),
        NodeType.experience,
        gap=_GAP,
        gap_min=360.0,
        prior=prior,
        nxt=nxt,
        party_ok=True,
        warnings=[],
        prior_neighbor=prior_meal,
        next_neighbor=None,
    )
    assert p.score >= 0.5  # an activity after a meal is fine


def test_build_proposal_marks_unknown_when_no_anchors() -> None:
    p = _build_proposal(
        _meal("near", 35.67, 139.73),
        NodeType.meal,
        gap=_GAP,
        gap_min=360.0,
        prior=None,
        nxt=None,
        party_ok=True,
        warnings=[],
    )
    assert p.feasibility_unknown is True
    assert p.fits_in_gap is False
    assert p.drive_time_in_min is None
    assert p.score == 0.5  # neutral — survives the default min_score


# ── integration ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _seed_gap_trip(s: AsyncSession) -> uuid.UUID:
    iid = await insert_itinerary(s)
    await insert_node(
        s,
        itinerary_id=iid,
        type="experience",
        title="Morning",
        status="approved",
        starts_lower=_at(10),
        starts_upper=_at(12),
        lat=_PRIOR[0],
        lng=_PRIOR[1],
    )
    await insert_node(
        s,
        itinerary_id=iid,
        type="experience",
        title="Evening",
        status="approved",
        starts_lower=_at(18),
        starts_upper=_at(20),
        lat=_NEXT[0],
        lng=_NEXT[1],
    )
    return iid


async def _seed_party(s: AsyncSession, iid: uuid.UUID, *, allergens: list[str]) -> uuid.UUID:
    pid = uuid.uuid4()
    await s.execute(
        text("insert into public.parties (id, itinerary_id, label) values (:id, :iid, 'Party')"),
        {"id": pid, "iid": iid},
    )
    await s.execute(
        text(
            """
            insert into public.travelers (id, party_id, name, profile_attrs)
            values (:id, :pid, 'Traveler', cast(:attrs as jsonb))
            """
        ),
        {"id": uuid.uuid4(), "pid": pid, "attrs": _json_allergens(allergens)},
    )
    await s.commit()
    return pid


def _json_allergens(allergens: list[str]) -> str:
    import json

    return json.dumps({"allergens": allergens})


@integration
async def test_fill_returns_feasible_tokyo_and_excludes_far_osaka(db_session: AsyncSession) -> None:
    iid = await _seed_gap_trip(db_session)
    items: list[InventoryItem] = [
        _meal("m-tokyo", 35.67, 139.73),
        _exp("e-tokyo", 35.68, 139.76),
        _exp("e-osaka", 34.6937, 135.5023),  # ~400 km away — can't fit a 6h gap
    ]
    result = await fill_gap(db_session, registry=_registry(items), itinerary_id=iid, gap=_GAP)

    ids = {p.inventory_id for p in result.proposals}
    assert "m-tokyo" in ids
    assert "e-tokyo" in ids
    assert "e-osaka" not in ids  # filtered: drive time blows the window
    assert result.analysis_id is None  # none seeded — feasibility still computed

    tokyo = next(p for p in result.proposals if p.inventory_id == "m-tokyo")
    assert tokyo.fits_in_gap is True
    assert tokyo.feasibility_unknown is False
    assert tokyo.drive_time_in_min is not None and tokyo.drive_time_out_min is not None
    assert tokyo.score >= 0.5
    # The proposal carries exactly what POST /nodes/from-inventory needs to accept.
    assert tokyo.inventory_source == "fake" and tokyo.inventory_id == "m-tokyo"


@integration
async def test_fill_surfaces_far_candidate_only_when_min_score_lowered(
    db_session: AsyncSession,
) -> None:
    iid = await _seed_gap_trip(db_session)
    result = await fill_gap(
        db_session,
        registry=_registry([_exp("e-osaka", 34.6937, 135.5023)]),
        itinerary_id=iid,
        gap=_GAP,
        min_score=0.0,
    )
    osaka = next(p for p in result.proposals if p.inventory_id == "e-osaka")
    assert osaka.fits_in_gap is False  # honest: surfaced but flagged unreachable


@integration
async def test_fill_drops_meals_with_a_party_allergen(db_session: AsyncSession) -> None:
    iid = await _seed_gap_trip(db_session)
    pid = await _seed_party(db_session, iid, allergens=["tree-nut"])
    items: list[InventoryItem] = [
        _meal("m-nut", 35.67, 139.73, tags=["tree-nut"]),
        _meal("m-ok", 35.671, 139.731),
    ]
    result = await fill_gap(
        db_session,
        registry=_registry(items),
        itinerary_id=iid,
        gap=_GAP,
        party_id=pid,
        desired_kinds=[NodeType.meal],
    )
    ids = {p.inventory_id for p in result.proposals}
    assert "m-nut" not in ids  # hard-blocked by the tree-nut allergy
    assert "m-ok" in ids


@integration
async def test_fill_downranks_a_meal_right_after_a_meal(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Prior stop is a MEAL that ends exactly as the gap opens — "you just ate".
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="meal",
        title="Lunch",
        status="approved",
        starts_lower=_at(11),
        starts_upper=_at(12),
        lat=_PRIOR[0],
        lng=_PRIOR[1],
    )
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Evening",
        status="approved",
        starts_lower=_at(18),
        starts_upper=_at(20),
        lat=_NEXT[0],
        lng=_NEXT[1],
    )
    items: list[InventoryItem] = [
        _meal("m-tokyo", 35.67, 139.73),
        _exp("e-tokyo", 35.68, 139.76),
    ]
    # Default min_score: the back-to-back meal is suppressed, the activity stays.
    result = await fill_gap(db_session, registry=_registry(items), itinerary_id=iid, gap=_GAP)
    ids = {p.inventory_id for p in result.proposals}
    assert "m-tokyo" not in ids
    assert "e-tokyo" in ids

    # Drop the bar and it resurfaces — honest, flagged, not silently hidden.
    surfaced = await fill_gap(
        db_session, registry=_registry(items), itinerary_id=iid, gap=_GAP, min_score=0.0
    )
    meal = next(p for p in surfaced.proposals if p.inventory_id == "m-tokyo")
    assert "meal is already scheduled" in meal.rationale


@integration
async def test_fill_excludes_node_types_a_block_finding_rules_out(
    db_session: AsyncSession,
) -> None:
    iid = await _seed_gap_trip(db_session)
    analysis = Analysis(
        itinerary_id=iid,
        status=AnalysisStatus.completed,
        completed_at=datetime.now(UTC),
        result={"summary": "x"},
        summary="x",
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)
    db_session.add(
        AnalysisFinding(
            analysis_id=analysis.id,
            severity=FindingSeverity.block,
            category="weather",
            message="Outdoor activities closed.",
            evidence={"exclude_node_types": ["experience"]},
        )
    )
    await db_session.commit()

    result = await fill_gap(
        db_session,
        registry=_registry([_meal("m-tokyo", 35.67, 139.73), _exp("e-tokyo", 35.68, 139.76)]),
        itinerary_id=iid,
        gap=_GAP,
        desired_kinds=[NodeType.meal, NodeType.experience],
    )
    assert result.analysis_id == analysis.id
    assert all(p.type is not NodeType.experience for p in result.proposals)
    assert any(p.type is NodeType.meal for p in result.proposals)


@integration
async def test_fill_marks_unknown_when_no_located_anchors(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Timed but unlocated neighbors -> no geometry to measure travel against.
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Morning",
        status="approved",
        starts_lower=_at(10),
        starts_upper=_at(12),
    )
    result = await fill_gap(
        db_session,
        registry=_registry([_meal("m-tokyo", 35.67, 139.73)]),
        itinerary_id=iid,
        gap=_GAP,
    )
    assert len(result.proposals) == 1
    p = result.proposals[0]
    assert p.feasibility_unknown is True
    assert p.fits_in_gap is False
    assert p.drive_time_in_min is None
    assert p.score == 0.5


@integration
async def test_fill_empty_gap_returns_no_proposals(db_session: AsyncSession) -> None:
    iid = await _seed_gap_trip(db_session)
    result = await fill_gap(
        db_session,
        registry=_registry([_meal("m-tokyo", 35.67, 139.73)]),
        itinerary_id=iid,
        gap=GapWindow(start=_at(12), end=_at(12)),  # zero-width
    )
    assert result.proposals == []
