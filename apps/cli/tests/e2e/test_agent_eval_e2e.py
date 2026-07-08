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


async def test_agent_edits_a_card_in_place_with_the_field_editor(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """AGT-1: a field-edit ask fires update_node_details (not a re-create or a
    status flip) and a node_updated frame reaches the wire.

    The Japan demo seeds mostly *firmed* cards (approved/booked/confirmed),
    which correctly refuse field edits behind the G1 gate — so seed one fresh
    ``proposed`` card and aim the edit at it. The gate itself is P5's job;
    this eval is about the editor."""
    client_id, _ = client_under_test
    await advisor.add_node(
        built_itinerary,
        type="experience",
        title="Sunset kaiseki dinner",
        status="proposed",
    )

    scenario = EvalScenario(
        name="field-edit-in-place",
        audience="advisor",
        turns=[
            TurnSpec(
                say=(
                    "There's a proposed card called 'Sunset kaiseki dinner' on "
                    "this plan. Give it a one-sentence description and price it "
                    "at 400 USD total — edit the existing card in place, don't "
                    "add anything new."
                ),
                expect_tools=["update_node_details"],
                forbid_tools=["propose_card", "update_node_status"],
                expect_frames=["node_updated"],
                expect_diff=DiffExpectation(min_nodes_added=0),
            )
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())


async def test_agent_answers_plan_state_from_the_digest_without_a_graph_read(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """AGT-2: the per-turn 'Live plan state' block carries lifecycle status +
    card counts, so a status question needs NO get_itinerary call — the exact
    tool burn the digest exists to remove. Graph untouched.

    Turn 1 fires a known tool first so the trace channel is *proven* live —
    only then is turn 2's empty trace meaningful (a forbid-only turn can't
    distinguish "no tools called" from "traceless agent" on its own)."""
    client_id, _ = client_under_test

    scenario = EvalScenario(
        name="digest-answers-plan-state",
        audience="advisor",
        turns=[
            TurnSpec(
                say="What's been invoiced on this trip so far?",
                expect_tools=["get_billing_state"],
                expect_diff=DiffExpectation(no_change=True),
            ),
            TurnSpec(
                say=(
                    "Quick status check, from what you already know without "
                    "opening the itinerary or calling any tool: what state is "
                    "this plan in and roughly how many cards are on it?"
                ),
                forbid_tools=["get_itinerary"],
                expect_diff=DiffExpectation(no_change=True),
            ),
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())


async def test_agent_reads_billing_state_for_a_money_question(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """AGT-3: a money question fires the read-only get_billing_state — and
    never a mutation (the human-in-the-loop boundary is structural)."""
    client_id, _ = client_under_test

    scenario = EvalScenario(
        name="money-question-reads-billing",
        audience="advisor",
        turns=[
            TurnSpec(
                say=(
                    "Where do we stand on money for this trip — what has been "
                    "invoiced so far and what's still unbilled?"
                ),
                expect_tools=["get_billing_state"],
                forbid_tools=["propose_card", "update_node_status", "update_node_details"],
                expect_diff=DiffExpectation(no_change=True),
            )
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())


async def test_agent_escalates_to_the_human_thread(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """AGT-4: an escalation ask fires post_thread_message, the graph stays
    untouched, and — the API-seam backstop — an artemis-authored message
    actually lands on the scope's human thread."""
    client_id, _ = client_under_test

    scenario = EvalScenario(
        name="escalate-to-advisor-thread",
        audience="advisor",
        turns=[
            TurnSpec(
                say=(
                    "Post a note on this trip's client thread letting them know "
                    "we're checking availability for a private chef evening in "
                    "Kyoto and will come back with options."
                ),
                expect_tools=["post_thread_message"],
                expect_diff=DiffExpectation(no_change=True),
            )
        ],
    )
    report = await run_scenario(
        advisor, scenario, client_id=client_id, itinerary_id=built_itinerary
    )
    _gate_infra(report)
    assert report.passed, "\n".join(report.failures())

    # API-seam backstop: the message is real, on the shared thread, and
    # attributed to artemis (the server pins the author kind).
    thread = await advisor.open_thread(client_id=client_id, itinerary_id=built_itinerary)
    messages = await advisor.list_thread_messages(str(thread.thread_id))
    artemis_rows = [m for m in messages if str(m.author_kind) == "artemis"]
    assert artemis_rows, "no artemis-authored message landed on the human thread"


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
