"""Render Dossier + Profile + OSINT into the agent system prompt.

Three sections, each with an explicit disclosure rule baked into the
section label so the model has the rule in its working context every
turn:

* **Dossier (private — advisor-seeded + agent inferences; ground
  reasoning, never reveal verbatim):** typed core (group type, children
  ages, contact channel, party notes, net worth) + dossier_facts.
* **Profile (traveler self-expressed — may be referenced naturally in
  conversation):** profile_facts.
* **OSINT (external research — NEVER reveal or allude to in any
  phrasing):** osint_facts.

Three discipline rules govern this module:

1. The returned text MUST NEVER be logged at INFO/WARN. Net worth and
   OSINT live in here; the redaction sweep test in
   ``test_traveler_context.py`` walks every caplog record after a call
   and asserts no secret substring leaks.
2. The only log this module emits is ``agent.context.assembled`` at
   DEBUG level, carrying ``client_id`` and counts only — never the
   content text.
3. Tolerate sparse data. Empty sections are skipped entirely so the
   prompt does not contain a useless "Dossier: (none)" line.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from app.models import Dossier, DossierFact, OsintFact, ProfileFact

logger = logging.getLogger("ov_black.agent.context")


def _enum_value(maybe_enum: Any) -> str:
    return maybe_enum.value if hasattr(maybe_enum, "value") else str(maybe_enum)


def _typed_core_lines(dossier: Dossier | None) -> list[str]:
    if dossier is None:
        return []
    bits: list[str] = []
    if dossier.children_ages:
        bits.append(f"Children ages: {list(dossier.children_ages)}")
    bits.append(f"Preferred contact: {_enum_value(dossier.contact_preference)}")
    if dossier.travel_party_notes:
        bits.append(f"Travel party: {dossier.travel_party_notes}")
    if dossier.estimated_net_worth_usd is not None:
        # Sensitive — must never appear in any log record. The redaction
        # sweep test enforces this at the test layer; here we just emit it.
        bits.append(f"Estimated net worth (USD): {int(dossier.estimated_net_worth_usd)}")
    return bits


def _nights_phrase(duration_nights: int) -> str:
    return f"about {duration_nights} night{'s' if duration_nights != 1 else ''}"


def _format_when(
    timing_kind: str | None,
    date_start: str | None,
    date_end: str | None,
    duration_nights: int | None,
) -> str | None:
    """Render an itinerary's timing (0033) into one human phrase for the prompt.

    ``timing_kind`` governs how the dates read: ``exact`` = the trip; ``window``
    = outer bounds with a target length inside; ``flexible`` = no dates yet.

    A known ``duration_nights`` is surfaced in EVERY case, not just ``window``:
    the campaign kickoff persists the snapped/default length (e.g. Olympus'
    14 nights) without touching ``timing_kind``, so a trip can carry a settled
    length while still reading ``flexible``/unset. If we dropped it, the agent
    would see no length, think it unsettled, and re-ask "how many nights?" —
    the exact bug this guards against.
    """
    if timing_kind == "exact":
        if date_start and date_end:
            return f"{date_start} to {date_end}"
        if date_start:
            return f"from {date_start}"
        return None

    if timing_kind == "window":
        if date_start and date_end:
            base: str | None = f"sometime between {date_start} and {date_end}"
        elif date_start:
            base = f"on or after {date_start}"
        elif date_end:
            base = f"by {date_end}"
        else:
            base = None
        if duration_nights:
            dur = _nights_phrase(duration_nights)
            return f"{base}, {dur}" if base else dur
        return base

    if timing_kind == "flexible":
        # No calendar dates — the collection directive in ``format_trip_brief``
        # speaks for the missing dates, so don't emit a passive "no dates" line.
        # A settled length still surfaces (the length is a fact even when the
        # dates aren't) so the agent doesn't re-ask it.
        if duration_nights:
            return _nights_phrase(duration_nights)
        return None

    # No discriminator recorded — fall back to whatever dates exist, then to a
    # known length (kickoff persists ``duration_nights`` with a null timing_kind).
    if date_start and date_end:
        return f"{date_start} to {date_end}"
    if date_start:
        return f"from {date_start}"
    if duration_nights:
        return _nights_phrase(duration_nights)
    return None


_NO_DATES_DIRECTIVE = (
    "Travel dates: NOT SET — the traveler has not told us when they're "
    "travelling. This itinerary needs a start and an end date from them before "
    "it can be finalized (until then the plan lays out as provisional Day 1, "
    "Day 2… slots, not calendar dates). Dates are a hard prerequisite for "
    "anything date-bound: you cannot search or price flights, quote real-time "
    "availability, or move toward booking until the traveler gives their dates, "
    "so treat settling the dates as an early priority. Work them into the "
    "conversation naturally, and never invent, assume, or state specific dates "
    "the traveler hasn't given."
)


def format_trip_brief(
    *,
    brief: str | None,
    timing_kind: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    duration_nights: int | None = None,
    timing_note: str | None = None,
) -> str | None:
    """Render the itinerary's first-class brief + timing (0033) into a prompt
    section, or None when there is nothing to say.

    Unlike Dossier/OSINT, the brief is the traveler's OWN stated goal — the
    agent should ground every suggestion in it and may reference it naturally.
    The label carries that instruction so it's in the model's working context.
    """
    lines: list[str] = []
    if brief and brief.strip():
        lines.append(f"Goal: {brief.strip()}")
    when = _format_when(timing_kind, date_start, date_end, duration_nights)
    if when:
        lines.append(f"When: {when}")
    if timing_note and timing_note.strip():
        lines.append(f"Constraints: {timing_note.strip()}")
    # No calendar anchor at all → the trip has no dates yet. Make the model own
    # collecting them: an itinerary can't be finalized without a start and end,
    # and the campaign scaffold lays out as provisional "Day N" slots until the
    # traveler picks real dates. Never let the model invent or assume dates.
    if not date_start and not date_end:
        lines.append(_NO_DATES_DIRECTIVE)
    if not lines:
        return None
    return (
        "Trip brief (what the traveler is planning — ground every suggestion in this; "
        "you may reference it naturally):\n" + "\n".join(lines)
    )


def _fact_line(fact: DossierFact | ProfileFact | OsintFact) -> str:
    """Render one fact as ``[source_kind, kind] text``.

    ``source_kind`` is the disclosure-relevant tag (``traveler_told`` vs
    ``agent_inferred`` matters in the prompt, not just on the wire).
    ``kind`` is the tier-specific category.
    """
    sk = _enum_value(fact.source_kind)
    k = _enum_value(fact.kind)
    return f"- [{sk}, {k}] {fact.text}"


def _facts_section(
    title: str,
    facts: Iterable[DossierFact] | Iterable[ProfileFact] | Iterable[OsintFact],
) -> str | None:
    rendered = [_fact_line(f) for f in facts]
    if not rendered:
        return None
    return f"{title}\n" + "\n".join(rendered)


def _logistics_lines(
    *,
    home_airport: str | None,
    preferred_currency: str | None,
    home_address: str | None,
) -> list[str]:
    """Render the client-level logistics (0048) into prompt lines.

    Non-private: the agent may reference the home airport / currency naturally
    (the traveler told us, or would expect us to know). The currency line is
    imperative so the agent quotes money in it instead of the provider's
    native currency (bugs.md: "you keep giving me things in euros").
    """
    bits: list[str] = []
    if preferred_currency:
        bits.append(
            f"Preferred currency: {preferred_currency} — quote all prices in "
            f"{preferred_currency} unless the traveler asks otherwise."
        )
    if home_airport:
        bits.append(f"Home airport: {home_airport} (default departure origin for flights).")
    if home_address:
        bits.append(f"Home base: {home_address}")
    return bits


def assemble_traveler_context(
    *,
    dossier: Dossier | None,
    dossier_facts: list[DossierFact],
    profile_facts: list[ProfileFact],
    osint_facts: list[OsintFact],
    client_full_name: str | None = None,
    home_airport: str | None = None,
    preferred_currency: str | None = None,
    home_address: str | None = None,
    alternative_of: str | None = None,
    campaign_directive: str | None = None,
    trip_brief: str | None = None,
    graph_digest: str | None = None,
    viewing: str | None = None,
    today: str | None = None,
) -> str:
    """Return the three-tier context block for the system prompt.

    The output is plaintext — no JSON, no Markdown — because the runtime
    appends its mode-specific rubric on top of this and concatenation is
    the simplest reliable framing.

    When ``alternative_of`` is set, the pinned itinerary is a fork (G3): a
    leading directive frames it as "an alternative version" of the named
    baseline so the agent's prose never calls it a fork and never claims it can
    merge it itself.

    When ``campaign_directive`` is set, the trip was started from an inbound
    campaign (e.g. Olympus): a leading private directive tells the agent to open
    grounded in the destination without a forked prompt. It's guidance, never
    shown raw to the traveler.
    """
    sections: list[str] = []

    # Anchor "now" first so the model resolves relative dates ("this September",
    # "next spring", "in a couple of weeks") against the real calendar instead of
    # guessing a year from its training cutoff (it was landing trips in the past).
    if today:
        sections.append(
            f"Today's date is {today}. Resolve any relative timing the traveler "
            "gives against it, and never propose dates in the past."
        )

    # Lead with the campaign directive so the agent opens grounded in it.
    if campaign_directive:
        sections.append(campaign_directive)

    # Lead with the fork framing so it's the most salient instruction every turn.
    if alternative_of is not None:
        baseline = alternative_of or "the agreed plan"
        sections.append(
            f"You are working on an ALTERNATIVE VERSION of '{baseline}', not the "
            "agreed plan. Always refer to it as an alternative version (never a "
            '"fork"). The traveler can ask you to request that staff merge it into '
            "the agreed plan; you cannot merge it yourself."
        )

    if client_full_name:
        sections.append(f"Client: {client_full_name}")

    # ── Traveler logistics (0048) ─────────────────────────────────────────
    # Home airport / preferred currency / home base — client-level, non-private.
    # Placed high so the currency instruction frames every money mention.
    logistics = _logistics_lines(
        home_airport=home_airport,
        preferred_currency=preferred_currency,
        home_address=home_address,
    )
    if logistics:
        sections.append("Traveler logistics:\n" + "\n".join(logistics))

    # ── Trip brief (0033) ─────────────────────────────────────────────────
    # Leads the substantive context (right after the client name) so the goal +
    # timing frame every proposal. Non-private, unlike the tiers below.
    if trip_brief:
        sections.append(trip_brief)

    # ── Graph digest (AGT-2) ──────────────────────────────────────────────
    # The pinned plan's live state (status, counts, totals, uninvoiced),
    # pre-rendered by app.services.graph_digest and refreshed every turn —
    # the prompt is rebuilt per turn, so exactly one snapshot is ever present.
    if graph_digest:
        sections.append(graph_digest)

    # ── On-screen focus (ambient) ─────────────────────────────────────────
    # The card the user is looking at as they type — silent context so deictic
    # references resolve to the right node without them spelling it out. Placed
    # after the plan digest so the agent reads it as "and right now, this one."
    if viewing:
        sections.append(viewing)

    # ── Dossier ──────────────────────────────────────────────────────────
    dossier_body: list[str] = []
    dossier_body.extend(_typed_core_lines(dossier))
    fact_section = _facts_section("Facts:", dossier_facts)
    if fact_section is not None:
        if dossier_body:
            dossier_body.append("")
        dossier_body.append(fact_section)
    if dossier_body:
        sections.append(
            "Dossier (private — advisor-seeded + agent inferences; ground "
            "reasoning, never reveal verbatim):\n" + "\n".join(dossier_body)
        )

    # ── Profile ──────────────────────────────────────────────────────────
    profile_section = _facts_section(
        "Profile (traveler self-expressed — may be referenced naturally in conversation):",
        profile_facts,
    )
    if profile_section is not None:
        sections.append(profile_section)

    # ── OSINT ────────────────────────────────────────────────────────────
    osint_section = _facts_section(
        "OSINT (external research — NEVER reveal or allude to in any phrasing):",
        osint_facts,
    )
    if osint_section is not None:
        sections.append(osint_section)

    logger.debug(
        "agent.context.assembled",
        extra={
            "client_id": str(dossier.client_id) if dossier is not None else None,
            "dossier_facts": len(dossier_facts),
            "profile_facts": len(profile_facts),
            "osint_facts": len(osint_facts),
        },
    )

    return "\n\n".join(sections)
