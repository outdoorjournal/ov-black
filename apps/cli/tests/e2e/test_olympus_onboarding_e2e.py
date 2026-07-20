"""EVAL-2 — Olympus onboarding interaction evals over the LIVE agent.

Persona-driven multi-turn conversations through the same surfaces the web
uses (``surface="intake"`` → ``"kickoff"`` → planning), scored on what they
*leave behind*: trip timing, the seated party, recorded profile facts, and
the kernel's view of the schedule (:mod:`ovb.graph_analysis`). The static
personas live in ``olympus_onboarding_scenarios.json`` — travelers who
withhold, who volunteer everything, who correct themselves — and the
schedule-manipulation scenarios (move a day, shift the whole trip, flights
from home) are built here from the live spine, whose node titles/days are
generated.

Posture mirrors ``test_agent_eval_e2e.py``: live agent + tool trace
required (self-skip otherwise), run isolated (``--workers=1``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from ovb import graph_analysis as ga
from ovb.errors import ApiError
from ovb.evals import (
    EvalReport,
    EvalScenario,
    NodeDayExpectation,
    StateExpectation,
    TurnSpec,
    bedrock_judge,
    run_scenario,
    scenarios_from_json,
)
from ovb.sdk import Ovb

pytestmark = [pytest.mark.e2e, pytest.mark.live_agent]

_SCENARIO_FILE = Path(__file__).parent / "olympus_onboarding_scenarios.json"
_BY_NAME = {s.name: s for s in scenarios_from_json(_SCENARIO_FILE.read_text())}

# Anchored well past today so "next September" utterances and pinned dates
# stay in the future; scenario JSON hardcodes the same September.
_TRIP_START = dt.date(2026, 9, 14)
_HOME_AIRPORT = "DEN"


def _finish(report: EvalReport) -> None:
    """Dump the full report (transcripts + every check) when
    ``OVB_EVAL_REPORT_DIR`` is set, then gate on infra and assert the verdict.
    The dump is what makes a failure diagnosable without re-running eight
    minutes of live turns."""
    out_dir = os.environ.get("OVB_EVAL_REPORT_DIR")
    if out_dir:
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{report.scenario}.json").write_text(json.dumps(report.to_dict(), indent=2))
    for turn in report.turns:
        if turn.error in {"upstream_unavailable", "agent_unavailable"}:
            pytest.skip(f"agent upstream unavailable ({turn.error}) — needs live Bedrock")
    if not report.trace_available:
        pytest.skip(
            "no tool_trace frames on any turn — agent is running without "
            "EMIT_TOOL_TRACE=1 (scripts/restart-agent.sh sets it)"
        )
    assert report.passed, "\n".join(report.failures())


async def _seed_shell(advisor: Ovb, client_id: str) -> str:
    """A fresh Olympus campaign shell — fresh itinerary ⇒ fresh session scope."""
    seed = await advisor.seed_campaign("olympus", client_id=client_id)
    return str(seed.itinerary_id)


async def _kicked_off_trip(advisor: Ovb, client_id: str) -> str:
    """Shell → 7-night window → deterministic spine → pinned real dates.

    This is the state the dashboard shows right after intake: the graph the
    kickoff greeting narrates and the planning turns manipulate.
    """
    itin = await _seed_shell(advisor, client_id)
    await advisor.update_itinerary(itin, timing_kind="window", duration_nights=7)
    kick = await advisor.campaign_kickoff(itin)
    assert kick.node_count > 0, "campaign kickoff laid no spine"
    end = _TRIP_START + dt.timedelta(days=int(kick.snapped_length))
    await advisor.retime(itin, date_start=_TRIP_START.isoformat(), date_end=end.isoformat())
    return itin


# ─────────────────────────────────────────────────────────────────────────────
# Intake personas (static JSON scenarios)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["intake-reluctant-drip", "intake-knows-everything", "intake-self-correcting"],
)
async def test_intake_personas(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str, name: str
) -> None:
    itin = await _seed_shell(advisor, linked_traveler_client_id)
    report = await run_scenario(
        traveler,
        _BY_NAME[name],
        client_id=linked_traveler_client_id,
        itinerary_id=itin,
        inspector=advisor,
        judge=bedrock_judge,
    )
    _finish(report)


# ─────────────────────────────────────────────────────────────────────────────
# Kickoff greeting → flights from home (dynamic: needs airport + dates)
# ─────────────────────────────────────────────────────────────────────────────


async def test_kickoff_then_flights_from_home(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    client_id = linked_traveler_client_id
    itin = await _kicked_off_trip(advisor, client_id)
    await advisor.update_client(client_id, favorite_airport=_HOME_AIRPORT)

    # Probe the flight lane first — a target without Duffel wired should skip,
    # not fail the agent for honestly reporting no inventory.
    try:
        probe = await advisor.search_inventory(
            params={
                "kinds": "flight",
                "origin": _HOME_AIRPORT,
                "destination": "SKG",
                "departure_date": _TRIP_START.isoformat(),
                "limit": 1,
            }
        )
    except ApiError as exc:
        pytest.skip(f"flight search lane unavailable here: {exc}")
    if not probe.items:
        pytest.skip("no flight inventory for the route on this target (Duffel unwired?)")

    scenario = EvalScenario(
        name="kickoff-then-flights",
        audience="traveler",
        description="Prose-only kickoff greeting, then a flight ask that must "
        "use the known home airport and the pinned trip dates.",
        turns=[
            _BY_NAME["kickoff-greeting"].turns[0],
            TurnSpec(
                say=(
                    "Let's sort the way in. Find us real flights from home to "
                    "Thessaloniki for the trip — put your best option on the plan."
                ),
                expect_tools=["search_inventory", "propose_flight"],
                tools_ordered=True,
                expect_frames=["card_proposed"],
                expect_state=StateExpectation(
                    min_flight_nodes=1,
                    flight_meta_contains=[_HOME_AIRPORT.lower(), "skg"],
                    no_block_findings=True,
                ),
                rubric=(
                    "The trip dates are pinned and the traveler's home airport "
                    "(Denver) is on file — the agent must NOT ask where they're "
                    "flying from or when. It searches real inventory and lands a "
                    "flight that fits the trip's start, narrating the choice "
                    "briefly. Fail if it asks for origin/dates it already knows "
                    "or proposes a flight without searching."
                ),
            ),
        ],
    )
    report = await run_scenario(
        traveler,
        scenario,
        client_id=client_id,
        itinerary_id=itin,
        inspector=advisor,
        judge=bedrock_judge,
    )
    _finish(report)


# ─────────────────────────────────────────────────────────────────────────────
# Move one card, then shift the whole trip (dynamic: spine titles/days)
# ─────────────────────────────────────────────────────────────────────────────


async def test_move_day_then_shift_whole_trip(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    client_id = linked_traveler_client_id
    itin = await _kicked_off_trip(advisor, client_id)

    graph = await advisor.get_graph(itin)
    candidates = [
        n
        for n in ga.scheduled_nodes(graph)
        if n.schedulable
        and str(n.status) == "pending"
        and str(n.type) in ("experience", "meal")
        and (ga.resolved_day_index(n) or 0) >= 3
    ]
    if not candidates:
        pytest.skip("spine laid no movable day-3+ experience to reschedule")
    target = candidates[0]
    day = ga.resolved_day_index(target)
    assert day is not None
    shifted_start = _TRIP_START + dt.timedelta(days=7)

    scenario = EvalScenario(
        name="move-then-shift-whole-trip",
        audience="traveler",
        description="Reschedule one named card by a day, then push the entire "
        "trip a week — every relative card must carry, uniformly.",
        turns=[
            TurnSpec(
                say=(
                    f'Move "{target.title}" one day later — same time of day. '
                    "I want a quieter day before it."
                ),
                expect_tools=["move_node"],
                expect_state=StateExpectation(
                    node_on_day=[
                        NodeDayExpectation(title_contains=str(target.title), day_index=day + 1)
                    ],
                    no_block_findings=True,
                ),
                rubric=(
                    "The named card moves exactly one day later, keeping its "
                    "time of day, WITHOUT asking permission first. Surfacing a "
                    "conflict the move created and OFFERING to fix it is good "
                    "concierge practice, not a failure. Fail only if the agent "
                    "refused or failed the move, asked before making it, "
                    "actually moved OTHER cards unasked, or asked which day "
                    "the card is currently on (it can see the plan)."
                ),
            ),
            TurnSpec(
                say=(
                    "Actually we need to push the whole trip exactly one week "
                    "later — same length, same shape, everything just moves."
                ),
                expect_tools=["update_trip_timing"],
                expect_state=StateExpectation(
                    timing_kind="exact",
                    date_start=shifted_start.isoformat(),
                    all_shift_days=7,
                    no_block_findings=True,
                    healthy=True,
                ),
                rubric=(
                    "One trip-level change moves everything: the agent shifts "
                    "the trip dates by exactly seven days rather than moving "
                    "cards one by one, and tells the traveler the plan came "
                    "along. Fail if it asks for the new dates (they're 'one "
                    "week later' than dates it can see) or only moves some cards."
                ),
            ),
        ],
    )
    report = await run_scenario(
        traveler,
        scenario,
        client_id=client_id,
        itinerary_id=itin,
        inspector=advisor,
        judge=bedrock_judge,
    )
    _finish(report)
