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

from ovb import graph_analysis as ga
from ovb._generated import models as gm
from ovb.agent import Conversation, TurnResult
from ovb.errors import ApiError, OvbError
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
class NodeDayExpectation:
    """A named card must sit on a given trip day (kernel-resolved)."""

    title_contains: str
    day_index: int


@dataclass(slots=True)
class StateExpectation:
    """Post-turn assertions on *persisted* state, probed over the live API.

    Where :class:`DiffExpectation` counts what a turn touched, this asserts
    what the conversation was supposed to *leave behind* — the intake ledger
    (trip timing, seated party, recorded profile facts), the kernel's view of
    the schedule, and flight placement. Every sub-check reports ``skip`` when
    its probe is unavailable (e.g. no advisor inspector to read facts with),
    never false-green.
    """

    # Trip timing (the intake contract). ``timing_kind`` pins one value;
    # ``timing_kind_in`` allows a set ("" = unset) — e.g. a traveler who
    # refused dates may legitimately leave "" or "flexible" behind, but
    # anything else means the agent fabricated timing.
    timing_kind: str | None = None
    timing_kind_in: list[str] = field(default_factory=list)
    duration_nights: int | None = None
    date_start: str | None = None
    date_end: str | None = None
    # Seated party.
    min_party: int | None = None
    party_contains: list[str] = field(default_factory=list)
    party_not_contains: list[str] = field(default_factory=list)
    # Recorded profile facts (vs. the scenario-start baseline).
    min_profile_facts_added: int | None = None
    profile_facts_contain: list[str] = field(default_factory=list)
    # Kernel schedule surface.
    min_scheduled_nodes: int | None = None
    node_on_day: list[NodeDayExpectation] = field(default_factory=list)
    all_shift_days: int | None = None
    # Flights.
    min_flight_nodes: int | None = None
    flight_meta_contains: list[str] = field(default_factory=list)
    # Judgements.
    no_block_findings: bool = False
    healthy: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateExpectation:
        def _opt_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if isinstance(value, (int, float)) else None

        def _opt_str(key: str) -> str | None:
            value = data.get(key)
            return str(value) if isinstance(value, str) else None

        def _strs(key: str) -> list[str]:
            return [str(v) for v in data.get(key, [])]

        return cls(
            timing_kind=_opt_str("timing_kind"),
            timing_kind_in=_strs("timing_kind_in"),
            duration_nights=_opt_int("duration_nights"),
            date_start=_opt_str("date_start"),
            date_end=_opt_str("date_end"),
            min_party=_opt_int("min_party"),
            party_contains=_strs("party_contains"),
            party_not_contains=_strs("party_not_contains"),
            min_profile_facts_added=_opt_int("min_profile_facts_added"),
            profile_facts_contain=_strs("profile_facts_contain"),
            min_scheduled_nodes=_opt_int("min_scheduled_nodes"),
            node_on_day=[
                NodeDayExpectation(
                    title_contains=str(item.get("title_contains", "")),
                    day_index=int(item.get("day_index", 0)),
                )
                for item in data.get("node_on_day", [])
                if isinstance(item, dict)
            ],
            all_shift_days=_opt_int("all_shift_days"),
            min_flight_nodes=_opt_int("min_flight_nodes"),
            flight_meta_contains=_strs("flight_meta_contains"),
            no_block_findings=bool(data.get("no_block_findings", False)),
            healthy=bool(data.get("healthy", False)),
        )


@dataclass(slots=True)
class TurnSpec:
    """One scripted user turn + everything it is expected to cause."""

    say: str
    surface: str | None = None
    expect_tools: list[str] = field(default_factory=list)
    tools_ordered: bool = False
    forbid_tools: list[str] = field(default_factory=list)
    expect_frames: list[str] = field(default_factory=list)
    expect_prose: list[str] = field(default_factory=list)
    expect_diff: DiffExpectation | None = None
    expect_state: StateExpectation | None = None
    rubric: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnSpec:
        say = data.get("say")
        if not isinstance(say, str) or not say.strip():
            raise OvbError("eval turn needs a non-empty 'say'")
        raw_diff = data.get("expect_diff")
        raw_state = data.get("expect_state")
        surface = data.get("surface")
        if surface is not None and surface not in ("intake", "kickoff"):
            raise OvbError(f"eval turn surface must be intake|kickoff, got {surface!r}")
        return cls(
            say=say,
            surface=surface,
            expect_tools=[str(t) for t in data.get("expect_tools", [])],
            tools_ordered=bool(data.get("tools_ordered", False)),
            forbid_tools=[str(t) for t in data.get("forbid_tools", [])],
            expect_frames=[str(f) for f in data.get("expect_frames", [])],
            expect_prose=[str(p) for p in data.get("expect_prose", [])],
            expect_diff=(
                DiffExpectation.from_dict(raw_diff) if isinstance(raw_diff, dict) else None
            ),
            expect_state=(
                StateExpectation.from_dict(raw_state) if isinstance(raw_state, dict) else None
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
    seeded_opener: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalScenario:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise OvbError("eval scenario needs a 'name'")
        raw_turns = data.get("turns")
        if not isinstance(raw_turns, list) or not raw_turns:
            raise OvbError(f"eval scenario {name!r} needs a non-empty 'turns' list")
        opener = data.get("seeded_opener")
        return cls(
            name=name,
            turns=[TurnSpec.from_dict(t) for t in raw_turns if isinstance(t, dict)],
            audience=str(data.get("audience", "advisor")),
            description=str(data.get("description", "")),
            seeded_opener=opener if isinstance(opener, str) and opener.strip() else None,
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
# State probe — persisted-state reads backing StateExpectation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class StateProbe:
    """Everything a StateExpectation can assert against, gathered post-turn.

    ``None`` on any field means "could not probe" — the paired check reports
    ``skip``. ``before``/``after`` are the same snapshots the diff check uses.
    """

    before: GraphSnapshot | None = None
    after: GraphSnapshot | None = None
    party: gm.ItineraryPartyResponse | None = None
    profile_fact_texts: list[str] | None = None
    baseline_profile_fact_count: int | None = None


async def _profile_fact_texts(inspector: Ovb, client_id: str) -> list[str] | None:
    try:
        detail = await inspector.get_client(client_id)
    except (ApiError, OvbError):
        return None
    facts = getattr(detail, "profile_facts", None) or []
    return [str(f.text) for f in facts]


async def gather_probe(
    inspector: Ovb | None,
    *,
    client_id: str,
    itinerary_id: str | None,
    before: GraphSnapshot | None,
    after: GraphSnapshot | None,
    baseline_profile_fact_count: int | None,
) -> StateProbe:
    probe = StateProbe(
        before=before,
        after=after,
        baseline_profile_fact_count=baseline_profile_fact_count,
    )
    if inspector is None:
        return probe
    if itinerary_id is not None:
        try:
            probe.party = await inspector.list_itinerary_party(itinerary_id)
        except (ApiError, OvbError):
            probe.party = None
    probe.profile_fact_texts = await _profile_fact_texts(inspector, client_id)
    return probe


def _check_state(spec: TurnSpec, probe: StateProbe | None) -> list[CheckResult]:
    want = spec.expect_state
    if want is None:
        return []
    if probe is None or probe.after is None:
        return [
            CheckResult(
                name="state",
                outcome="skip",
                detail="no pinned itinerary / no probe for state checks",
            )
        ]
    checks: list[CheckResult] = []
    graph = probe.after.graph
    itin = graph.itinerary

    # ── timing ──
    timing_failures: list[str] = []
    if want.timing_kind is not None:
        got = ga.enum_str(itin.timing_kind)
        if got != want.timing_kind:
            timing_failures.append(f"timing_kind={got or None!r}, wanted {want.timing_kind!r}")
    if want.timing_kind_in:
        got = ga.enum_str(itin.timing_kind)
        if got not in want.timing_kind_in:
            timing_failures.append(
                f"timing_kind={got or None!r}, wanted one of {want.timing_kind_in}"
            )
    if want.duration_nights is not None and itin.duration_nights != want.duration_nights:
        timing_failures.append(
            f"duration_nights={itin.duration_nights}, wanted {want.duration_nights}"
        )
    if want.date_start is not None and str(itin.date_start or "") != want.date_start:
        timing_failures.append(f"date_start={itin.date_start}, wanted {want.date_start}")
    if want.date_end is not None and str(itin.date_end or "") != want.date_end:
        timing_failures.append(f"date_end={itin.date_end}, wanted {want.date_end}")
    if (
        want.timing_kind is not None
        or want.timing_kind_in
        or want.duration_nights is not None
        or want.date_start is not None
        or want.date_end is not None
    ):
        checks.append(
            CheckResult(
                name="state.timing",
                outcome="fail" if timing_failures else "pass",
                detail="; ".join(timing_failures)
                or (
                    f"timing {ga.enum_str(itin.timing_kind)} "
                    f"start={itin.date_start} nights={itin.duration_nights}"
                ),
            )
        )

    # ── party ──
    if want.min_party is not None or want.party_contains or want.party_not_contains:
        if probe.party is None:
            checks.append(
                CheckResult(name="state.party", outcome="skip", detail="party unreadable here")
            )
        else:
            names = [str(m.name) for m in probe.party.members]
            lowered = [n.lower() for n in names]
            party_failures: list[str] = []
            if want.min_party is not None and len(names) < want.min_party:
                party_failures.append(f"{len(names)} seated, wanted ≥{want.min_party}")
            for needle in want.party_contains:
                if not any(needle.lower() in n for n in lowered):
                    party_failures.append(f"nobody matching {needle!r} seated")
            for needle in want.party_not_contains:
                if any(needle.lower() in n for n in lowered):
                    party_failures.append(f"{needle!r} should NOT be seated")
            checks.append(
                CheckResult(
                    name="state.party",
                    outcome="fail" if party_failures else "pass",
                    detail="; ".join(party_failures) or f"seated: {names}",
                )
            )

    # ── profile facts ──
    if want.min_profile_facts_added is not None or want.profile_facts_contain:
        if probe.profile_fact_texts is None:
            checks.append(
                CheckResult(
                    name="state.facts",
                    outcome="skip",
                    detail="profile facts unreadable (no advisor inspector?)",
                )
            )
        else:
            fact_failures: list[str] = []
            texts = probe.profile_fact_texts
            if want.min_profile_facts_added is not None:
                base = probe.baseline_profile_fact_count or 0
                added = len(texts) - base
                if added < want.min_profile_facts_added:
                    fact_failures.append(
                        f"{added} profile fact(s) added this scenario, "
                        f"wanted ≥{want.min_profile_facts_added}"
                    )
            blob = " | ".join(texts).lower()
            for needle in want.profile_facts_contain:
                if needle.lower() not in blob:
                    fact_failures.append(f"no profile fact mentions {needle!r}")
            checks.append(
                CheckResult(
                    name="state.facts",
                    outcome="fail" if fact_failures else "pass",
                    detail="; ".join(fact_failures) or f"{len(texts)} profile fact(s)",
                )
            )

    # ── schedule ──
    schedule_failures: list[str] = []
    if want.min_scheduled_nodes is not None:
        placed = ga.scheduled_nodes(graph)
        if len(placed) < want.min_scheduled_nodes:
            schedule_failures.append(
                f"{len(placed)} scheduled nodes, wanted ≥{want.min_scheduled_nodes}"
            )
    for expect in want.node_on_day:
        matches = ga.find_nodes(graph, expect.title_contains)
        if not matches:
            schedule_failures.append(f"no node titled ~{expect.title_contains!r}")
            continue
        days = {ga.resolved_day_index(n) for n in matches}
        if expect.day_index not in days:
            schedule_failures.append(
                f"{expect.title_contains!r} on day(s) {sorted(d for d in days if d is not None)}, "
                f"wanted day {expect.day_index}"
            )
    if want.all_shift_days is not None:
        if probe.before is None:
            schedule_failures.append("no before-snapshot to measure the shift against")
        else:
            for v in ga.uniform_shift_violations(
                probe.before.graph, graph, expect_days=want.all_shift_days
            ):
                schedule_failures.append(str(v))
    if want.min_scheduled_nodes is not None or want.node_on_day or want.all_shift_days is not None:
        checks.append(
            CheckResult(
                name="state.schedule",
                outcome="fail" if schedule_failures else "pass",
                detail="; ".join(schedule_failures) or "schedule as expected",
            )
        )

    # ── flights ──
    if want.min_flight_nodes is not None or want.flight_meta_contains:
        flights = ga.flight_nodes(graph)
        flight_failures: list[str] = []
        if want.min_flight_nodes is not None and len(flights) < want.min_flight_nodes:
            flight_failures.append(
                f"{len(flights)} flight node(s), wanted ≥{want.min_flight_nodes}"
            )
        if want.flight_meta_contains:
            blob = " ".join(
                str(n.title).lower() + " " + ga._meta_blob(n)
                for n in flights  # noqa: SLF001
            )
            for needle in want.flight_meta_contains:
                if needle.lower() not in blob:
                    flight_failures.append(f"no flight mentions {needle!r}")
        checks.append(
            CheckResult(
                name="state.flights",
                outcome="fail" if flight_failures else "pass",
                detail="; ".join(flight_failures) or f"{len(flights)} flight node(s)",
            )
        )

    # ── kernel judgements / health ──
    if want.no_block_findings:
        blocks = ga.findings_at_or_above(graph, "block")
        checks.append(
            CheckResult(
                name="state.findings",
                outcome="fail" if blocks else "pass",
                detail="; ".join(f"{f.code}: {f.message}" for f in blocks) or "no block findings",
            )
        )
    if want.healthy:
        violations = ga.interaction_health(graph, party=probe.party)
        errors = [v for v in violations if v.severity == "error"]
        warns = [v for v in violations if v.severity != "error"]
        detail = "; ".join(str(v) for v in violations) or "healthy"
        checks.append(
            CheckResult(
                name="state.health",
                outcome="fail" if errors else "pass",
                detail=detail if (errors or warns) else "healthy",
            )
        )

    return checks


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
    probe: StateProbe | None = None,
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
    checks += _check_state(spec, probe)
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
    inspector: Ovb | None = None,
    judge: JudgeFn | None = None,
    on_frame: Any = None,
) -> EvalReport:
    """Drive one scenario over a live conversation and score every turn.

    Opens (or reuses) the session for ``(client_id, audience, itinerary_id)``
    exactly as the UI does, snapshots the pinned itinerary's graph around each
    turn, and evaluates the spec's expectations against what actually happened.
    ``inspector`` is the identity used for privileged state probes (profile
    facts, party) — pass an advisor ``Ovb`` when the driver is a traveler;
    it defaults to the driving identity. Never raises on a failed
    expectation — the report carries the verdicts.
    """
    convo = await Conversation.open(
        ovb,
        client_id=client_id,
        itinerary_id=itinerary_id,
        seeded_opener=scenario.seeded_opener,
        audience=scenario.audience,
    )
    inspector = inspector or ovb

    # Baseline for min_profile_facts_added: facts on record before turn one.
    baseline_fact_count: int | None = None
    if any(t.expect_state is not None for t in scenario.turns):
        baseline_texts = await _profile_fact_texts(inspector, client_id)
        baseline_fact_count = len(baseline_texts) if baseline_texts is not None else None

    turns: list[TurnReport] = []
    for spec in scenario.turns:
        before: GraphSnapshot | None = None
        if convo.itinerary_id is not None:
            before = GraphSnapshot.of(await ovb.get_graph(convo.itinerary_id))
        result = await convo.say(spec.say, surface=spec.surface, on_frame=on_frame)
        # The agent may fork mid-turn (a traveler content-write on a trunk
        # lazy-forks, mirroring the web's working-copy toggle) — the session
        # re-pins to the fork server-side, so follow it or every subsequent
        # snapshot/probe reads the abandoned trunk.
        if "fork_itinerary" in result.tools_called:
            try:
                sessions = await inspector.list_client_sessions(client_id)
                for s in sessions.sessions:
                    if str(s.id) == convo.session_id and s.itinerary_id is not None:
                        convo.itinerary_id = str(s.itinerary_id)
                        break
            except (ApiError, OvbError):
                pass
        diff: GraphDiff | None = None
        after: GraphSnapshot | None = None
        if convo.itinerary_id is not None:
            after = GraphSnapshot.of(await ovb.get_graph(convo.itinerary_id))
            if before is not None:
                diff = before.diff(after)
        probe: StateProbe | None = None
        if spec.expect_state is not None:
            probe = await gather_probe(
                inspector,
                client_id=client_id,
                itinerary_id=convo.itinerary_id,
                before=before,
                after=after,
                baseline_profile_fact_count=baseline_fact_count,
            )
        turns.append(
            TurnReport(
                say=spec.say,
                content=result.content,
                tools_called=result.tools_called,
                frame_types=[f.type for f in result.frames],
                diff_summary=diff.summary() if diff is not None else None,
                error=result.error.reason if result.error else None,
                checks=evaluate_turn(spec, result, diff, probe=probe, judge=judge),
            )
        )
    return EvalReport(scenario=scenario.name, turns=turns)
