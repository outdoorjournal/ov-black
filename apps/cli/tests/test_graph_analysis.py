"""ovb.graph_analysis + StateExpectation checks (offline, no stack).

Graphs are built with ``model_construct`` (no validation round-trip) so the
pure analysis logic — shift uniformity, interaction health, post-turn state
checks — is locked down without a live API.
"""

from __future__ import annotations

import datetime as dt

from ovb import graph_analysis as ga
from ovb._generated import models as gm
from ovb.agent import TurnResult
from ovb.evals import (
    StateExpectation,
    StateProbe,
    TurnSpec,
    evaluate_turn,
)
from ovb.scenario import GraphSnapshot
from ovb.sse import ToolTraceFrame


def _node(
    nid: str,
    *,
    status: str = "pending",
    ntype: str = "experience",
    title: str = "Card",
    day: int | None = None,
    on: dt.date | None = None,
    synthesized: bool = False,
    schedulable: bool = True,
    metadata: dict | None = None,
) -> gm.NodeResponse:
    sched = None
    if day is not None or on is not None:
        sched = gm.ResolvedScheduleResponse.model_construct(
            kind="relative",
            start=gm.ResolvedStampResponse.model_construct(
                day_index=day, date=on, wall_time="09:00", tz="Europe/Athens"
            ),
            end=None,
            day_span=1,
            synthesized=synthesized,
        )
    return gm.NodeResponse.model_construct(
        id=nid,
        itinerary_id="itin",
        parent_subgraph_id=None,
        type=ntype,
        status=status,
        title=title,
        source=None,
        source_id=None,
        metadata=metadata or {},
        schedulable=schedulable,
        schedule=sched,
    )


def _graph(
    nodes: list[gm.NodeResponse],
    *,
    timing_kind: str | None = None,
    date_start: dt.date | None = None,
    date_end: dt.date | None = None,
    duration_nights: int | None = None,
    anchor_date: dt.date | None = None,
    findings: list[gm.GraphFindingResponse] | None = None,
) -> gm.GraphResponse:
    itin = gm.ItineraryResponse.model_construct(
        id="itin",
        title="Trip",
        client_id=None,
        created_by=None,
        timing_kind=timing_kind,
        date_start=date_start,
        date_end=date_end,
        duration_nights=duration_nights,
        anchor_date=anchor_date,
    )
    return gm.GraphResponse.model_construct(
        itinerary=itin, nodes=nodes, edges=[], findings=findings or []
    )


def _finding(code: str, severity: str) -> gm.GraphFindingResponse:
    return gm.GraphFindingResponse.model_construct(
        code=code, severity=severity, message=f"{code} happened", node_ids=[]
    )


_D0 = dt.date(2026, 9, 14)


# ── shift analysis ───────────────────────────────────────────────────────────


def test_uniform_shift_clean() -> None:
    before = _graph([_node("a", on=_D0), _node("b", on=_D0 + dt.timedelta(days=2))])
    after = _graph(
        [
            _node("a", on=_D0 + dt.timedelta(days=7)),
            _node("b", on=_D0 + dt.timedelta(days=9)),
        ]
    )
    assert ga.uniform_shift_violations(before, after, expect_days=7) == []


def test_uniform_shift_flags_straggler() -> None:
    before = _graph([_node("a", on=_D0), _node("b", on=_D0)])
    after = _graph([_node("a", on=_D0 + dt.timedelta(days=7)), _node("b", on=_D0)])
    codes = [v.code for v in ga.uniform_shift_violations(before, after, expect_days=7)]
    assert "shift_nonuniform" in codes


def test_uniform_shift_flags_moved_booking_and_lost_schedule() -> None:
    before = _graph([_node("a", status="booked", on=_D0), _node("b", on=_D0)])
    after = _graph([_node("a", status="booked", on=_D0 + dt.timedelta(days=7)), _node("b")])
    codes = [v.code for v in ga.uniform_shift_violations(before, after, expect_days=7)]
    assert "shift_moved_pinned" in codes
    assert "shift_lost_schedule" in codes


# ── interaction health ───────────────────────────────────────────────────────


def test_health_flags_empty_window_and_block_finding() -> None:
    graph = _graph(
        [_node("art", ntype="article", schedulable=True)],
        timing_kind="window",
        findings=[_finding("flight_infeasible", "block"), _finding("overlap", "warn")],
    )
    codes = [v.code for v in ga.interaction_health(graph)]
    assert "timing_window_empty" in codes
    assert "kernel_block" in codes
    assert "article_schedulable" in codes
    assert codes.count("kernel_block") == 1  # warn finding is not a block


def test_health_clean_trip_is_silent() -> None:
    graph = _graph(
        [_node("a", on=_D0, day=1), _node("art", ntype="article", schedulable=False)],
        timing_kind="window",
        duration_nights=7,
    )
    assert ga.interaction_health(graph) == []


def test_health_flags_duplicate_party() -> None:
    party = gm.ItineraryPartyResponse.model_construct(
        itinerary_id="itin",
        members=[
            gm.ItineraryPartyEntry.model_construct(
                traveler_id="t1", party_id="p", name="June", party_member_id=None, member=None
            ),
            gm.ItineraryPartyEntry.model_construct(
                traveler_id="t2", party_id="p", name="june ", party_member_id=None, member=None
            ),
        ],
    )
    graph = _graph([], timing_kind="window", duration_nights=7)
    codes = [v.code for v in ga.interaction_health(graph, party=party)]
    assert "party_duplicate" in codes


# ── state checks through evaluate_turn ───────────────────────────────────────


def _result_with_tools(*names: str) -> TurnResult:
    result = TurnResult(content="ok")
    result.tool_trace = [
        ToolTraceFrame(type="tool_trace", tool=n, phase="call", tool_use_id=str(i))
        for i, n in enumerate(names)
    ]
    return result


def _probe(
    graph: gm.GraphResponse,
    *,
    before: gm.GraphResponse | None = None,
    party_names: list[str] | None = None,
    fact_texts: list[str] | None = None,
    baseline_facts: int = 0,
) -> StateProbe:
    party = None
    if party_names is not None:
        party = gm.ItineraryPartyResponse.model_construct(
            itinerary_id="itin",
            members=[
                gm.ItineraryPartyEntry.model_construct(
                    traveler_id=f"t{i}", party_id="p", name=n, party_member_id=None, member=None
                )
                for i, n in enumerate(party_names)
            ],
        )
    return StateProbe(
        before=GraphSnapshot.of(before) if before is not None else None,
        after=GraphSnapshot.of(graph),
        party=party,
        profile_fact_texts=fact_texts,
        baseline_profile_fact_count=baseline_facts,
    )


def _outcomes(spec: TurnSpec, probe: StateProbe) -> dict[str, str]:
    checks = evaluate_turn(spec, _result_with_tools("update_trip_timing"), None, probe=probe)
    return {c.name: c.outcome for c in checks}


def test_state_timing_and_party_pass_and_fail() -> None:
    graph = _graph([], timing_kind="window", duration_nights=7)
    spec = TurnSpec(
        say="x",
        expect_state=StateExpectation(
            timing_kind="window",
            duration_nights=7,
            min_party=2,
            party_contains=["robert"],
            party_not_contains=["june"],
        ),
    )
    good = _outcomes(spec, _probe(graph, party_names=["Me", "Robert Sr."]))
    assert good["state.timing"] == "pass"
    assert good["state.party"] == "pass"

    bad = _outcomes(spec, _probe(graph, party_names=["Me", "June"]))
    assert bad["state.party"] == "fail"


def test_state_facts_baseline_and_day_placement() -> None:
    graph = _graph(
        [_node("s", title="Summit Push", day=5, on=_D0 + dt.timedelta(days=4))],
        timing_kind="exact",
        date_start=_D0,
        date_end=_D0 + dt.timedelta(days=7),
    )
    spec = TurnSpec(
        say="x",
        expect_state=StateExpectation.from_dict(
            {
                "min_profile_facts_added": 1,
                "profile_facts_contain": ["summit"],
                "node_on_day": [{"title_contains": "summit push", "day_index": 5}],
            }
        ),
    )
    good = _outcomes(
        spec, _probe(graph, fact_texts=["old", "dreams of the summit"], baseline_facts=1)
    )
    assert good["state.facts"] == "pass"
    assert good["state.schedule"] == "pass"

    stale = _outcomes(spec, _probe(graph, fact_texts=["old"], baseline_facts=1))
    assert stale["state.facts"] == "fail"


def test_state_shift_and_findings() -> None:
    before = _graph([_node("a", on=_D0)])
    after_good = _graph([_node("a", on=_D0 + dt.timedelta(days=7))])
    spec = TurnSpec(
        say="x",
        expect_state=StateExpectation(all_shift_days=7, no_block_findings=True),
    )
    good = _outcomes(spec, _probe(after_good, before=before))
    assert good["state.schedule"] == "pass"
    assert good["state.findings"] == "pass"

    blocked = _graph(
        [_node("a", on=_D0 + dt.timedelta(days=6))],
        findings=[_finding("flight_infeasible", "block")],
    )
    bad = _outcomes(spec, _probe(blocked, before=before))
    assert bad["state.schedule"] == "fail"
    assert bad["state.findings"] == "fail"


def test_state_skips_without_probe_pieces() -> None:
    graph = _graph([], timing_kind="window", duration_nights=7)
    spec = TurnSpec(
        say="x",
        expect_state=StateExpectation(min_party=1, min_profile_facts_added=1),
    )
    outcomes = _outcomes(spec, _probe(graph))
    assert outcomes["state.party"] == "skip"
    assert outcomes["state.facts"] == "skip"
