"""EVAL-1 — declarative agent evals over the LIVE agent (Wave B).

These drive real Bedrock turns through :func:`ovb.evals.run_scenario` — the
same SSE loop the browser uses — and assert on invariants: which tools fired
(via the debug-gated ``tool_trace`` frames), which frames were emitted, and
what the graph diff was. Never on wording (ADV-3 posture).

Posture:
  * **Live agent required** — a turn that errors ``upstream_unavailable``
    self-skips (no Bedrock creds / agent down), mirroring the pillar suite.
  * **Trace required** — a live turn that surfaces no ``tool_trace`` frames
    means the agent is running without ``EMIT_TOOL_TRACE=1``; that's an infra
    gap, so we skip with the restart hint rather than false-failing.
  * Run isolated (``--workers=1`` posture): live turns contend for the same
    local agent, so don't parallelize these with other live-turn specs.
"""

from __future__ import annotations

import pytest

from ovb.evals import DiffExpectation, EvalReport, EvalScenario, TurnSpec, run_scenario
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = [pytest.mark.e2e, pytest.mark.live_agent]


def _gate_infra(report: EvalReport) -> None:
    """Self-skip on the two infra (not product) failure modes."""
    for turn in report.turns:
        if turn.error in {"upstream_unavailable", "agent_unavailable"}:
            pytest.skip(f"agent upstream unavailable ({turn.error}) — needs live Bedrock")
    if not report.trace_available:
        pytest.skip(
            "no tool_trace frames on any turn — agent is running without "
            "EMIT_TOOL_TRACE=1 (scripts/restart-agent.sh sets it)"
        )


async def test_advisor_asks_for_analysis_and_agent_fires_the_tools(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str, harness: Harness
) -> None:
    """ADV-6's live half: "check this plan" → run_analysis fires; graph untouched.

    The analyze tools are read-only over the graph, so the eval also pins the
    structural boundary: a conversational analysis must not mutate the plan.
    """
    client_id, _ = client_under_test
    harness.itinerary_id = built_itinerary

    scenario = EvalScenario(
        name="analyze-conversational",
        audience="advisor",
        turns=[
            TurnSpec(
                say=(
                    "Before I show this plan to the client, please run a check for "
                    "conflicts or feasibility problems and tell me what you find."
                ),
                expect_tools=["run_analysis"],
                forbid_tools=["propose_card", "update_node_status"],
                expect_diff=DiffExpectation(no_change=True),
            )
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())


async def test_advisor_build_turn_grounds_search_and_lands_a_card(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """ADV-3's structural core as an eval: a build ask → search_inventory then
    propose_card (in that order), a card_proposed frame on the wire, and a new
    node actually landing on the pinned graph."""
    client_id, _ = client_under_test

    scenario = EvalScenario(
        name="grounded-build-turn",
        audience="advisor",
        turns=[
            TurnSpec(
                say=(
                    "Find one wonderful sushi dinner experience in Tokyo for this "
                    "trip and add it to the plan as a proposal."
                ),
                expect_tools=["search_inventory", "propose_card"],
                tools_ordered=True,
                expect_frames=["card_proposed"],
                expect_diff=DiffExpectation(min_nodes_added=1),
            )
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())
