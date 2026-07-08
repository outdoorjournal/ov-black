"""Declarative agent-eval scenarios over the LIVE agent (EVAL-1, Wave B).

A scenario is a turn script plus per-turn expectations:

  - **tools** — which agent tools fired, observed via the debug-gated
    ``tool_trace`` SSE frames (restart the agent with ``EMIT_TOOL_TRACE=1``;
    ``scripts/restart-agent.sh`` and the mprocs pane both set it). Expected
    tools check as a set-subset by default, or an ordered subsequence with
    ``tools_ordered``.
  - **frames** — SSE frame types the turn must emit (``card_proposed``, …).
  - **prose markers** — substrings that must appear in the reply (fenced
    shortcodes like ``\\`\\`\\`ov-timeline`` — structural, not wording).
  - **a graph diff** — what the turn changed on the pinned itinerary,
    snapshotted around every turn via :class:`ovb.scenario.GraphSnapshot`.
  - **an optional LLM-judge rubric** — a semantic pass/fail over the turn's
    transcript (Bedrock Converse; the check reports *skip* when boto3 or
    creds are absent, never false-green).

The runner drives the real SSE turn loop through
:class:`ovb.agent.Conversation` — exactly what the browser does — so every
assertion lands on invariants (tools fired, graph changed, frames emitted),
never on the agent's wording (the ADV-3 posture).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ovb.agent import Conversation, TurnResult
from ovb.errors import OvbError
from ovb.scenario import GraphDiff, GraphSnapshot
from ovb.sdk import Ovb

# ─────────────────────────────────────────────────────────────────────────────
# Scenario shapes (declarative — JSON-loadable for the CLI, constructible for
# pytest)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class DiffExpectation:
    """Constraints on the GraphDiff a turn produced on the pinned itinerary."""

    min_nodes_added: int = 0
    min_nodes_removed: int = 0
    statuses_to: list[str] = field(default_factory=list)
    no_change: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffExpectation:
        return cls(
            min_nodes_added=int(data.get("min_nodes_added", 0)),
            min_nodes_removed=int(data.get("min_nodes_removed", 0)),
            statuses_to=[str(s) for s in data.get("statuses_to", [])],
            no_change=bool(data.get("no_change", False)),
        )


@dataclass(slots=True)
class TurnSpec:
    """One scripted user turn + everything it is expected to cause."""

    say: str
    expect_tools: list[str] = field(default_factory=list)
    tools_ordered: bool = False
    forbid_tools: list[str] = field(default_factory=list)
    expect_frames: list[str] = field(default_factory=list)
    expect_prose: list[str] = field(default_factory=list)
    expect_diff: DiffExpectation | None = None
    rubric: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnSpec:
        say = data.get("say")
        if not isinstance(say, str) or not say.strip():
            raise OvbError("eval turn needs a non-empty 'say'")
        raw_diff = data.get("expect_diff")
        return cls(
            say=say,
            expect_tools=[str(t) for t in data.get("expect_tools", [])],
            tools_ordered=bool(data.get("tools_ordered", False)),
            forbid_tools=[str(t) for t in data.get("forbid_tools", [])],
            expect_frames=[str(f) for f in data.get("expect_frames", [])],
            expect_prose=[str(p) for p in data.get("expect_prose", [])],
            expect_diff=(
                DiffExpectation.from_dict(raw_diff) if isinstance(raw_diff, dict) else None
            ),
            rubric=data.get("rubric") if isinstance(data.get("rubric"), str) else None,
        )


@dataclass(slots=True)
class EvalScenario:
    """A named turn script run over one live conversation."""

    name: str
    turns: list[TurnSpec]
    audience: str = "advisor"
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalScenario:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise OvbError("eval scenario needs a 'name'")
        raw_turns = data.get("turns")
        if not isinstance(raw_turns, list) or not raw_turns:
            raise OvbError(f"eval scenario {name!r} needs a non-empty 'turns' list")
        return cls(
            name=name,
            turns=[TurnSpec.from_dict(t) for t in raw_turns if isinstance(t, dict)],
            audience=str(data.get("audience", "advisor")),
            description=str(data.get("description", "")),
        )


def scenarios_from_json(text: str) -> list[EvalScenario]:
    """Parse a scenario file: one object, a list, or ``{"scenarios": [...]}``."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OvbError(f"scenario file is not valid JSON: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("scenarios"), list):
        payload = payload["scenarios"]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise OvbError("scenario file must hold an object or a list of objects")
    return [EvalScenario.from_dict(item) for item in payload if isinstance(item, dict)]


# ─────────────────────────────────────────────────────────────────────────────
# Report shapes
# ─────────────────────────────────────────────────────────────────────────────

CheckOutcome = Literal["pass", "fail", "skip"]


@dataclass(slots=True)
class CheckResult:
    name: str
    outcome: CheckOutcome
    detail: str = ""


@dataclass(slots=True)
class TurnReport:
    say: str
    content: str
    tools_called: list[str]
    frame_types: list[str]
    diff_summary: str | None
    error: str | None
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.outcome != "fail" for c in self.checks)


@dataclass(slots=True)
class EvalReport:
    scenario: str
    turns: list[TurnReport]

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def trace_available(self) -> bool:
        """Whether ANY turn surfaced tool_trace frames — the infra gate a
        pytest caller inspects to skip (agent up but running without
        ``EMIT_TOOL_TRACE``) instead of false-failing."""
        return any(t.tools_called for t in self.turns)

    def failures(self) -> list[str]:
        out = []
        for i, turn in enumerate(self.turns):
            for check in turn.checks:
                if check.outcome == "fail":
                    out.append(f"turn {i + 1} [{check.name}] {check.detail}")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "turns": [
                {
                    "say": t.say,
                    "content": t.content,
                    "tools_called": t.tools_called,
                    "frame_types": t.frame_types,
                    "diff": t.diff_summary,
                    "error": t.error,
                    "passed": t.passed,
                    "checks": [
                        {"name": c.name, "outcome": c.outcome, "detail": c.detail} for c in t.checks
                    ],
                }
                for t in self.turns
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# LLM judge (optional, Bedrock-gated)
# ─────────────────────────────────────────────────────────────────────────────


class JudgeUnavailable(Exception):
    """The judge backend cannot run here (no boto3 / no creds) — skip, not fail."""


# (rubric, transcript) → (passed, reason)
JudgeFn = Callable[[str, str], tuple[bool, str]]

_JUDGE_SYSTEM = (
    "You are a strict QA judge for a travel-concierge agent. Evaluate the "
    "transcript against the rubric. Respond with ONLY a JSON object: "
    '{"pass": true|false, "reason": "<one sentence>"}'
)


def bedrock_judge(rubric: str, transcript: str) -> tuple[bool, str]:
    """Judge a transcript against a rubric via Bedrock Converse.

    Model/region come from ``OVB_JUDGE_MODEL_ID`` / ``AWS_REGION`` (defaults
    mirror the agent's). Raises :class:`JudgeUnavailable` when boto3 or
    credentials are absent so the check reports *skip*.
    """
    try:
        import boto3  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError as exc:
        raise JudgeUnavailable("boto3 not installed") from exc

    model_id = os.environ.get("OVB_JUDGE_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    region = os.environ.get("AWS_REGION", "us-west-2")
    client = boto3.client("bedrock-runtime", region_name=region)
    prompt = f"RUBRIC:\n{rubric}\n\nTRANSCRIPT:\n{transcript}"
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": _JUDGE_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
    except Exception as exc:  # noqa: BLE001 — any botocore failure means "can't judge here"
        raise JudgeUnavailable(exc.__class__.__name__) from exc

    blocks = resp.get("output", {}).get("message", {}).get("content", [])
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise JudgeUnavailable("judge returned no JSON verdict")
    try:
        verdict = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeUnavailable("judge verdict was not valid JSON") from exc
    return bool(verdict.get("pass")), str(verdict.get("reason", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────────


def _is_subsequence(expected: list[str], actual: list[str]) -> bool:
    it = iter(actual)
    return all(any(tool == got for got in it) for tool in expected)


def _check_tools(spec: TurnSpec, result: TurnResult) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if not spec.expect_tools and not spec.forbid_tools:
        return checks
    called = result.tools_called
    if spec.expect_tools and not result.tool_trace:
        # Only an *expectation* can distinguish "traceless agent" from "the
        # agent genuinely called no tools". A forbid-only turn with an empty
        # trace passes here — a zero-tool turn is exactly what it asserts —
        # and the traceless-agent case is caught scenario-wide by
        # ``EvalReport.trace_available`` (the pytest gate skips on it), so
        # pair a forbid-only turn with at least one tool-firing turn.
        checks.append(
            CheckResult(
                name="tools",
                outcome="fail",
                detail=(
                    "no tool_trace frames on the turn — the agent is running "
                    "without EMIT_TOOL_TRACE=1 (scripts/restart-agent.sh sets it)"
                ),
            )
        )
        return checks
    if spec.expect_tools:
        if spec.tools_ordered:
            ok = _is_subsequence(spec.expect_tools, called)
            detail = f"expected in order {spec.expect_tools}, called {called}"
        else:
            missing = [t for t in spec.expect_tools if t not in called]
            ok = not missing
            detail = f"missing {missing}, called {called}" if missing else f"called {called}"
        checks.append(CheckResult(name="tools", outcome="pass" if ok else "fail", detail=detail))
    for tool in spec.forbid_tools:
        if tool in called:
            checks.append(
                CheckResult(name="forbid_tools", outcome="fail", detail=f"{tool} was called")
            )
    return checks


def _check_frames(spec: TurnSpec, result: TurnResult) -> list[CheckResult]:
    if not spec.expect_frames:
        return []
    seen = [f.type for f in result.frames]
    missing = [ft for ft in spec.expect_frames if ft not in seen]
    return [
        CheckResult(
            name="frames",
            outcome="fail" if missing else "pass",
            detail=f"missing {missing}, saw {sorted(set(seen))}" if missing else f"saw {seen}",
        )
    ]


def _check_prose(spec: TurnSpec, result: TurnResult) -> list[CheckResult]:
    if not spec.expect_prose:
        return []
    missing = [marker for marker in spec.expect_prose if marker not in result.content]
    return [
        CheckResult(
            name="prose",
            outcome="fail" if missing else "pass",
            detail=f"reply is missing marker(s) {missing}" if missing else "all markers present",
        )
    ]


def _check_diff(spec: TurnSpec, diff: GraphDiff | None) -> list[CheckResult]:
    if spec.expect_diff is None:
        return []
    want = spec.expect_diff
    if diff is None:
        return [
            CheckResult(
                name="diff",
                outcome="skip",
                detail="no pinned itinerary to snapshot around this turn",
            )
        ]
    failures: list[str] = []
    if want.no_change and not diff.empty:
        failures.append(f"expected no change, got {diff.summary()}")
    if len(diff.added_nodes) < want.min_nodes_added:
        failures.append(f"expected ≥{want.min_nodes_added} added nodes, got {diff.summary()}")
    if len(diff.removed_nodes) < want.min_nodes_removed:
        failures.append(f"expected ≥{want.min_nodes_removed} removed nodes, got {diff.summary()}")
    for status in want.statuses_to:
        moved = any(
            f == "status" and str(after) == status
            for deltas in diff.changed_nodes.values()
            for f, (_, after) in deltas.items()
        )
        if not moved:
            failures.append(f"no node moved to status {status!r} ({diff.summary()})")
    return [
        CheckResult(
            name="diff",
            outcome="fail" if failures else "pass",
            detail="; ".join(failures) if failures else diff.summary(),
        )
    ]


def _check_rubric(spec: TurnSpec, result: TurnResult, judge: JudgeFn | None) -> list[CheckResult]:
    if spec.rubric is None:
        return []
    if judge is None:
        return [CheckResult(name="rubric", outcome="skip", detail="no judge configured")]
    transcript = (
        f"USER: {spec.say}\n"
        f"TOOLS CALLED: {', '.join(result.tools_called) or '(none observed)'}\n"
        f"ASSISTANT: {result.content}"
    )
    try:
        ok, reason = judge(spec.rubric, transcript)
    except JudgeUnavailable as exc:
        return [CheckResult(name="rubric", outcome="skip", detail=f"judge unavailable: {exc}")]
    return [CheckResult(name="rubric", outcome="pass" if ok else "fail", detail=reason)]


def evaluate_turn(
    spec: TurnSpec,
    result: TurnResult,
    diff: GraphDiff | None,
    *,
    judge: JudgeFn | None = None,
) -> list[CheckResult]:
    """All checks for one turn. Pure — unit-testable without a live stack."""
    checks: list[CheckResult] = []
    if result.error is not None:
        checks.append(
            CheckResult(name="turn_ok", outcome="fail", detail=f"turn error: {result.error.reason}")
        )
        return checks
    checks.append(CheckResult(name="turn_ok", outcome="pass"))
    checks += _check_tools(spec, result)
    checks += _check_frames(spec, result)
    checks += _check_prose(spec, result)
    checks += _check_diff(spec, diff)
    checks += _check_rubric(spec, result, judge)
    return checks


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────


async def run_scenario(
    ovb: Ovb,
    scenario: EvalScenario,
    *,
    client_id: str,
    itinerary_id: str | None = None,
    judge: JudgeFn | None = None,
    on_frame: Any = None,
) -> EvalReport:
    """Drive one scenario over a live conversation and score every turn.

    Opens (or reuses) the session for ``(client_id, audience, itinerary_id)``
    exactly as the UI does, snapshots the pinned itinerary's graph around each
    turn, and evaluates the spec's expectations against what actually happened.
    Never raises on a failed expectation — the report carries the verdicts.
    """
    convo = await Conversation.open(
        ovb, client_id=client_id, itinerary_id=itinerary_id, audience=scenario.audience
    )
    turns: list[TurnReport] = []
    for spec in scenario.turns:
        before: GraphSnapshot | None = None
        if convo.itinerary_id is not None:
            before = GraphSnapshot.of(await ovb.get_graph(convo.itinerary_id))
        result = await convo.say(spec.say, on_frame=on_frame)
        diff: GraphDiff | None = None
        if before is not None and convo.itinerary_id is not None:
            after = GraphSnapshot.of(await ovb.get_graph(convo.itinerary_id))
            diff = before.diff(after)
        turns.append(
            TurnReport(
                say=spec.say,
                content=result.content,
                tools_called=result.tools_called,
                frame_types=[f.type for f in result.frames],
                diff_summary=diff.summary() if diff is not None else None,
                error=result.error.reason if result.error else None,
                checks=evaluate_turn(spec, result, diff, judge=judge),
            )
        )
    return EvalReport(scenario=scenario.name, turns=turns)
