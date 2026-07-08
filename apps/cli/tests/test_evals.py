"""ovb.evals — scenario parsing + per-turn check logic (offline, no stack)."""

from __future__ import annotations

import pytest

from ovb.agent import TurnResult
from ovb.errors import OvbError
from ovb.evals import (
    CheckResult,
    DiffExpectation,
    EvalReport,
    JudgeUnavailable,
    TurnReport,
    TurnSpec,
    evaluate_turn,
    scenarios_from_json,
)
from ovb.scenario import GraphDiff
from ovb.sse import CardProposedFrame, ErrorFrame, ToolTraceFrame


def _trace(*names: str) -> list[ToolTraceFrame]:
    return [
        ToolTraceFrame(type="tool_trace", tool=n, phase="call", tool_use_id=f"tu-{i}")
        for i, n in enumerate(names)
    ]


def _result(
    *,
    content: str = "done.",
    tools: list[str] | None = None,
    frames: list[str] | None = None,
    error: str | None = None,
) -> TurnResult:
    result = TurnResult(content=content)
    result.tool_trace = _trace(*(tools or []))
    result.frames = list(result.tool_trace)
    for ft in frames or []:
        result.frames.append(CardProposedFrame(type=ft, node={}))
    if error is not None:
        result.error = ErrorFrame(type="error", reason=error)
    return result


def _diff(
    added: list[str] | None = None,
    changed: dict[str, dict[str, tuple[object, object]]] | None = None,
) -> GraphDiff:
    return GraphDiff(
        added_nodes=added or [],
        removed_nodes=[],
        changed_nodes=changed or {},
        added_edges=[],
        removed_edges=[],
    )


def _outcome(checks: list[CheckResult], name: str) -> str:
    matches = [c for c in checks if c.name == name]
    assert matches, f"no {name!r} check in {[c.name for c in checks]}"
    return matches[0].outcome


# ── parsing ──────────────────────────────────────────────────────────────────


def test_scenarios_from_json_accepts_object_list_and_wrapper() -> None:
    one = '{"name": "s1", "turns": [{"say": "hi"}]}'
    assert [s.name for s in scenarios_from_json(one)] == ["s1"]
    many = '[{"name": "a", "turns": [{"say": "x"}]}, {"name": "b", "turns": [{"say": "y"}]}]'
    assert [s.name for s in scenarios_from_json(many)] == ["a", "b"]
    wrapped = '{"scenarios": [{"name": "w", "audience": "traveler", "turns": [{"say": "z"}]}]}'
    (scenario,) = scenarios_from_json(wrapped)
    assert scenario.audience == "traveler"


def test_scenarios_from_json_rejects_bad_shapes() -> None:
    with pytest.raises(OvbError):
        scenarios_from_json("not json")
    with pytest.raises(OvbError):
        scenarios_from_json('{"name": "no-turns", "turns": []}')
    with pytest.raises(OvbError):
        scenarios_from_json('{"name": "empty-say", "turns": [{"say": "  "}]}')


def test_turn_spec_parses_full_shape() -> None:
    spec = TurnSpec.from_dict(
        {
            "say": "check the plan",
            "expect_tools": ["run_analysis", "get_analysis_findings"],
            "tools_ordered": True,
            "forbid_tools": ["propose_card"],
            "expect_frames": ["card_proposed"],
            "expect_prose": ["```ov-timeline"],
            "expect_diff": {"min_nodes_added": 1, "statuses_to": ["approved"]},
            "rubric": "narrates the findings",
        }
    )
    assert spec.tools_ordered and spec.expect_diff is not None
    assert spec.expect_diff.min_nodes_added == 1


# ── tool checks ──────────────────────────────────────────────────────────────


def test_expected_tools_as_set_subset() -> None:
    spec = TurnSpec(say="s", expect_tools=["search_inventory", "propose_card"])
    ok = _result(tools=["get_itinerary", "propose_card", "search_inventory"])
    assert _outcome(evaluate_turn(spec, ok, None), "tools") == "pass"
    missing = _result(tools=["get_itinerary"])
    assert _outcome(evaluate_turn(spec, missing, None), "tools") == "fail"


def test_expected_tools_as_ordered_subsequence() -> None:
    spec = TurnSpec(
        say="s", expect_tools=["run_analysis", "get_analysis_findings"], tools_ordered=True
    )
    in_order = _result(tools=["get_itinerary", "run_analysis", "get_analysis_findings"])
    assert _outcome(evaluate_turn(spec, in_order, None), "tools") == "pass"
    reversed_ = _result(tools=["get_analysis_findings", "run_analysis"])
    assert _outcome(evaluate_turn(spec, reversed_, None), "tools") == "fail"


def test_forbidden_tool_fails() -> None:
    spec = TurnSpec(say="s", expect_tools=["get_itinerary"], forbid_tools=["update_node_status"])
    result = _result(tools=["get_itinerary", "update_node_status"])
    checks = evaluate_turn(spec, result, None)
    assert _outcome(checks, "forbid_tools") == "fail"


def test_missing_trace_fails_with_actionable_detail() -> None:
    spec = TurnSpec(say="s", expect_tools=["run_analysis"])
    checks = evaluate_turn(spec, _result(tools=[]), None)
    (tools_check,) = [c for c in checks if c.name == "tools"]
    assert tools_check.outcome == "fail"
    assert "EMIT_TOOL_TRACE" in tools_check.detail


def test_forbid_only_turn_with_zero_tool_calls_passes() -> None:
    """A forbid-only turn asserts "the agent needed NO tool for this" — an
    empty trace is the *desired* outcome, not a trace-infra failure (that case
    is covered scenario-wide by ``EvalReport.trace_available``; pair a
    forbid-only turn with at least one tool-firing turn)."""
    spec = TurnSpec(say="s", forbid_tools=["get_itinerary"])
    checks = evaluate_turn(spec, _result(tools=[]), None)
    assert all(c.outcome != "fail" for c in checks), [c.detail for c in checks]


# ── frame / prose / diff checks ──────────────────────────────────────────────


def test_expected_frames_and_prose() -> None:
    spec = TurnSpec(say="s", expect_frames=["card_proposed"], expect_prose=["```ov-timeline"])
    hit = _result(content="here:\n```ov-timeline\n{}\n```", frames=["card_proposed"])
    checks = evaluate_turn(spec, hit, None)
    assert _outcome(checks, "frames") == "pass" and _outcome(checks, "prose") == "pass"
    miss = _result(content="plain prose")
    checks = evaluate_turn(spec, miss, None)
    assert _outcome(checks, "frames") == "fail" and _outcome(checks, "prose") == "fail"


def test_diff_expectations() -> None:
    added = TurnSpec(say="s", expect_diff=DiffExpectation(min_nodes_added=1))
    assert _outcome(evaluate_turn(added, _result(), _diff(added=["n1"])), "diff") == "pass"
    assert _outcome(evaluate_turn(added, _result(), _diff()), "diff") == "fail"

    frozen = TurnSpec(say="s", expect_diff=DiffExpectation(no_change=True))
    assert _outcome(evaluate_turn(frozen, _result(), _diff()), "diff") == "pass"
    assert _outcome(evaluate_turn(frozen, _result(), _diff(added=["n1"])), "diff") == "fail"

    moved = TurnSpec(say="s", expect_diff=DiffExpectation(statuses_to=["approved"]))
    status_change = _diff(changed={"n1": {"status": ("proposed", "approved")}})
    assert _outcome(evaluate_turn(moved, _result(), status_change), "diff") == "pass"
    assert _outcome(evaluate_turn(moved, _result(), _diff(added=["n1"])), "diff") == "fail"


def test_diff_without_pinned_itinerary_skips() -> None:
    spec = TurnSpec(say="s", expect_diff=DiffExpectation(min_nodes_added=1))
    assert _outcome(evaluate_turn(spec, _result(), None), "diff") == "skip"


# ── turn error + rubric ──────────────────────────────────────────────────────


def test_turn_error_short_circuits_all_checks() -> None:
    spec = TurnSpec(say="s", expect_tools=["run_analysis"])
    checks = evaluate_turn(spec, _result(error="upstream_unavailable"), None)
    assert [c.name for c in checks] == ["turn_ok"]
    assert checks[0].outcome == "fail" and "upstream_unavailable" in checks[0].detail


def test_rubric_uses_judge_and_skips_when_unavailable() -> None:
    spec = TurnSpec(say="s", rubric="mentions the analysis")

    def approving(rubric: str, transcript: str) -> tuple[bool, str]:
        assert "USER: s" in transcript
        return True, "grounded"

    assert _outcome(evaluate_turn(spec, _result(), None, judge=approving), "rubric") == "pass"

    def rejecting(rubric: str, transcript: str) -> tuple[bool, str]:
        return False, "generic"

    assert _outcome(evaluate_turn(spec, _result(), None, judge=rejecting), "rubric") == "fail"

    def unavailable(rubric: str, transcript: str) -> tuple[bool, str]:
        raise JudgeUnavailable("no creds")

    assert _outcome(evaluate_turn(spec, _result(), None, judge=unavailable), "rubric") == "skip"
    assert _outcome(evaluate_turn(spec, _result(), None, judge=None), "rubric") == "skip"


# ── report aggregation ───────────────────────────────────────────────────────


def test_report_passed_and_trace_available() -> None:
    good = TurnReport(
        say="s",
        content="c",
        tools_called=["get_itinerary"],
        frame_types=[],
        diff_summary=None,
        error=None,
        checks=[CheckResult(name="turn_ok", outcome="pass")],
    )
    bad = TurnReport(
        say="s2",
        content="",
        tools_called=[],
        frame_types=[],
        diff_summary=None,
        error=None,
        checks=[CheckResult(name="tools", outcome="fail", detail="missing")],
    )
    report = EvalReport(scenario="x", turns=[good, bad])
    assert not report.passed and report.trace_available
    assert report.failures() == ["turn 2 [tools] missing"]
    payload = report.to_dict()
    assert payload["passed"] is False and len(payload["turns"]) == 2
    skipped_only = EvalReport(
        scenario="y",
        turns=[
            TurnReport(
                say="s",
                content="c",
                tools_called=[],
                frame_types=[],
                diff_summary=None,
                error=None,
                checks=[CheckResult(name="rubric", outcome="skip")],
            )
        ],
    )
    assert skipped_only.passed and not skipped_only.trace_available
