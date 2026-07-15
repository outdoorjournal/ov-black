"""Unit tests for the three-tier traveler-context renderer.

Two contracts under test:

1. **Shape** — the renderer produces three explicitly-labeled sections in
   the order Dossier / Profile / OSINT, with empty tiers fully skipped
   (no ``Profile (…): \\n`` lone-header lines).
2. **Redaction discipline** — sensitive substrings (net worth, OSINT
   fact text, dossier-fact text, profile-fact text) MUST NEVER appear in
   any log record emitted during context assembly. Sweep ``caplog`` after
   every call and assert no sentinel leaks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
from app.agent.traveler_context import assemble_traveler_context, format_trip_brief
from app.models import (
    ContactChannel,
    Dossier,
    DossierFact,
    DossierFactKind,
    FactSourceKind,
    OsintFact,
    OsintFactKind,
    ProfileFact,
    ProfileFactKind,
)

_NOW = datetime(2026, 4, 25, tzinfo=UTC)


def _dossier(*, net_worth: int | None = 250_000_000) -> Dossier:
    return Dossier(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        authored_by=uuid.uuid4(),
        contact_preference=ContactChannel.email,
        children_ages=[6, 9],
        travel_party_notes="party_note_sentinel",
        estimated_net_worth_usd=net_worth,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _dossier_fact(
    text: str, *, source_kind: FactSourceKind = FactSourceKind.advisor
) -> DossierFact:
    return DossierFact(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        kind=DossierFactKind.passion,
        text=text,
        source_kind=source_kind,
        source_ref={},
        observed_at=_NOW,
        recorded_by=uuid.uuid4(),
        redacted_at=None,
        redacted_by=None,
        redacted_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _profile_fact(text: str) -> ProfileFact:
    return ProfileFact(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        kind=ProfileFactKind.preference,
        text=text,
        source_kind=FactSourceKind.traveler_told,
        source_ref={},
        observed_at=_NOW,
        recorded_by=uuid.uuid4(),
        redacted_at=None,
        redacted_by=None,
        redacted_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _osint_fact(text: str) -> OsintFact:
    return OsintFact(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        kind=OsintFactKind.linkedin,
        text=text,
        source_kind=FactSourceKind.advisor,
        source_ref={"url": "https://example.com/profile"},
        observed_at=_NOW,
        recorded_by=uuid.uuid4(),
        redacted_at=None,
        redacted_by=None,
        redacted_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ── Shape ────────────────────────────────────────────────────────────────


def test_renders_three_labeled_sections_in_order() -> None:
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[_dossier_fact("loves heli-skiing")],
        profile_facts=[_profile_fact("morning person")],
        osint_facts=[_osint_fact("CFO at Acme")],
        client_full_name="Alex Stone",
    )
    dossier_idx = out.index("Dossier (private")
    profile_idx = out.index("Profile (traveler self-expressed")
    osint_idx = out.index("OSINT (external research")
    assert dossier_idx < profile_idx < osint_idx
    assert "Alex Stone" in out


def test_empty_tiers_are_skipped_entirely() -> None:
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[],
        profile_facts=[],
        osint_facts=[],
    )
    # The Dossier section still renders because the typed core has values.
    assert "Dossier (private" in out
    # Profile and OSINT have no facts and no typed core fallback — they
    # must not produce a "Profile (…): " lone-header line.
    assert "Profile (traveler self-expressed" not in out
    assert "OSINT (external research" not in out


def test_logistics_section_renders_currency_airport_address() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Robin Thurston",
        home_airport="JFK",
        preferred_currency="USD",
        home_address="1 Park Ave, New York",
    )
    assert "Traveler logistics:" in out
    # The currency line is imperative so the agent quotes in it.
    assert "Preferred currency: USD" in out
    assert "quote all prices in USD" in out
    assert "Home airport: JFK" in out
    assert "1 Park Ave, New York" in out
    # Logistics leads the client-specific context (right after the name).
    assert out.index("Client: Robin Thurston") < out.index("Traveler logistics:")


def test_logistics_section_omitted_when_all_unset() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Robin Thurston",
    )
    assert "Traveler logistics:" not in out


def test_dossier_section_skipped_when_no_dossier_and_no_facts() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("favors small lodges")],
        osint_facts=[],
    )
    assert "Dossier (private" not in out
    assert "Profile (traveler self-expressed" in out


def test_alternative_version_framing_leads_when_fork() -> None:
    """G3: a forked pin gets a leading 'alternative version' directive."""
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Alex Stone",
        alternative_of="Japan in Spring",
    )
    assert "ALTERNATIVE VERSION of 'Japan in Spring'" in out
    assert "cannot merge it yourself" in out
    # The directive leads the prompt (most salient instruction every turn).
    assert out.index("ALTERNATIVE VERSION") < out.index("Alex Stone")


def test_no_alternative_framing_for_a_normal_itinerary() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("x")],
        osint_facts=[],
    )
    assert "ALTERNATIVE VERSION" not in out


# ── Trip brief (0033) ──────────────────────────────────────────────────────


def test_format_trip_brief_exact_dates() -> None:
    out = format_trip_brief(
        brief="Sailing in Greece",
        timing_kind="exact",
        date_start="2027-03-18",
        date_end="2027-03-25",
    )
    assert out is not None
    assert "Goal: Sailing in Greece" in out
    assert "When: 2027-03-18 to 2027-03-25" in out


def test_format_trip_brief_window_with_duration() -> None:
    out = format_trip_brief(
        brief="A week in the sun",
        timing_kind="window",
        date_start="2027-06-01",
        date_end="2027-08-31",
        duration_nights=7,
    )
    assert out is not None
    assert "sometime between 2027-06-01 and 2027-08-31" in out
    assert "about 7 nights" in out


def test_format_trip_brief_flexible_with_constraints() -> None:
    out = format_trip_brief(
        brief="Ski trip",
        timing_kind="flexible",
        timing_note="not August; back by a Sunday",
    )
    assert out is not None
    # No calendar dates → the model is told to collect them (not a passive line).
    assert "NOT SET" in out
    assert "start and an end date" in out
    assert "Constraints: not August; back by a Sunday" in out


def test_format_trip_brief_surfaces_length_without_window() -> None:
    # The campaign kickoff persists a snapped/default ``duration_nights`` (Olympus:
    # 14) WITHOUT setting ``timing_kind`` to ``window`` — the trip still reads
    # unset/flexible. The length is a settled fact and must reach the prompt so the
    # agent doesn't re-ask "how many nights?" (the bug this guards).
    for kind in (None, "flexible"):
        out = format_trip_brief(
            brief="A guided ascent of Olympus",
            timing_kind=kind,
            duration_nights=14,
        )
        assert out is not None
        assert "When: about 14 nights" in out
        # Dates are still open, so the collection directive still fires.
        assert "NOT SET" in out


def test_format_trip_brief_no_dates_prompts_collection() -> None:
    # An itinerary with nothing pinned still has something to say: the agent must
    # ask the traveler for dates before the trip can be finalized.
    out = format_trip_brief(brief=None)
    assert out is not None
    assert "NOT SET" in out

    out2 = format_trip_brief(brief="   ", timing_kind=None)
    assert out2 is not None
    assert "NOT SET" in out2


def test_format_trip_brief_pinned_dates_no_directive() -> None:
    # With real dates the collection directive stays silent.
    out = format_trip_brief(
        brief="Sailing in Greece",
        timing_kind="exact",
        date_start="2027-03-18",
        date_end="2027-03-25",
    )
    assert out is not None
    assert "NOT SET" not in out


def test_assemble_includes_trip_brief_after_client_before_dossier() -> None:
    brief = format_trip_brief(
        brief="Sailing in Greece with my family",
        timing_kind="window",
        date_start="2027-06-01",
        date_end="2027-08-31",
        duration_nights=7,
    )
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[_dossier_fact("loves heli-skiing")],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Alex Stone",
        trip_brief=brief,
    )
    assert "Trip brief" in out
    assert "Sailing in Greece with my family" in out
    # Placed after the client name, before the Dossier tier.
    assert out.index("Alex Stone") < out.index("Trip brief") < out.index("Dossier (private")


def test_assemble_includes_graph_digest_after_trip_brief() -> None:
    """AGT-2: the live plan state rides right behind the trip brief, ahead of
    the private tiers — the plan's facts frame the turn like the goal does."""
    digest = "Live plan state (auto-refreshed every turn ...):\n- Status: draft"
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[_dossier_fact("loves heli-skiing")],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Alex Stone",
        trip_brief="Trip brief (...):\nGoal: Sailing in Greece",
        graph_digest=digest,
    )
    assert "Live plan state" in out
    assert out.index("Trip brief") < out.index("Live plan state") < out.index("Dossier (private")


def test_assemble_omits_graph_digest_when_none() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("x")],
        osint_facts=[],
        graph_digest=None,
    )
    assert "Live plan state" not in out


def test_assemble_includes_viewing_cue_after_digest_before_dossier() -> None:
    """The on-screen-focus cue rides just behind the live plan state and ahead
    of the private tiers, so 'and right now, this one' reads in context."""
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[_dossier_fact("loves heli-skiing")],
        profile_facts=[],
        osint_facts=[],
        client_full_name="Alex Stone",
        graph_digest="Live plan state (...):\n- Status: draft",
        viewing="On screen right now: the user is looking at 'Aman Kyoto' (hotel, pending) ...",
    )
    assert "On screen right now" in out
    assert out.index("Live plan state") < out.index("On screen right now")
    assert out.index("On screen right now") < out.index("Dossier (private")


def test_assemble_omits_viewing_cue_when_none() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("x")],
        osint_facts=[],
        viewing=None,
    )
    assert "On screen right now" not in out


def test_assemble_omits_trip_brief_when_none() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("x")],
        osint_facts=[],
        trip_brief=None,
    )
    assert "Trip brief" not in out


def test_alternative_framing_falls_back_when_baseline_untitled() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[],
        osint_facts=[],
        alternative_of="",  # a fork whose baseline carries no title
    )
    assert "ALTERNATIVE VERSION of 'the agreed plan'" in out


def test_profile_facts_render_with_source_kind_and_kind_tags() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("morning person")],
        osint_facts=[],
    )
    assert "[traveler_told, preference] morning person" in out


def test_dossier_inferred_facts_render_distinctly_from_advisor() -> None:
    out = assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[
            _dossier_fact("seeded_by_advisor", source_kind=FactSourceKind.advisor),
            _dossier_fact("inferred_by_agent", source_kind=FactSourceKind.agent_inferred),
        ],
        profile_facts=[],
        osint_facts=[],
    )
    assert "[advisor, passion] seeded_by_advisor" in out
    assert "[agent_inferred, passion] inferred_by_agent" in out


# ── Redaction sweep ──────────────────────────────────────────────────────


_RENDERED_SENSITIVE_SUBSTRINGS = [
    "250000000",  # net worth as rendered
    "party_note_sentinel",
    "loves_heli_skiing_sentinel",
    "morning_person_sentinel",
    "cfo_at_acme_sentinel",
]
# source_ref is NOT rendered into the prompt today, but a future change
# could regress that. Keep the URL in the leak-sweep set so a regression
# would be caught.
_LEAK_SWEEP_SUBSTRINGS = _RENDERED_SENSITIVE_SUBSTRINGS + ["linkedin_url_sentinel"]


def _assert_no_leak(records: list[logging.LogRecord]) -> None:
    for rec in records:
        message = rec.getMessage()
        assembled = (
            message
            + " "
            + str(rec.args or "")
            + " "
            + str(getattr(rec, "extra", ""))
            + " "
            + str(rec.__dict__)
        )
        for sentinel in _LEAK_SWEEP_SUBSTRINGS:
            assert sentinel not in assembled, (
                f"{sentinel!r} leaked into log record {rec.name} {rec.levelname}: {assembled[:200]}"
            )


def test_no_sensitive_substring_leaks_into_log_records(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="ov_black.agent.context")

    osint = _osint_fact("cfo_at_acme_sentinel")
    osint.source_ref = {"url": "linkedin_url_sentinel"}

    out = assemble_traveler_context(
        dossier=_dossier(net_worth=250_000_000),
        dossier_facts=[_dossier_fact("loves_heli_skiing_sentinel")],
        profile_facts=[_profile_fact("morning_person_sentinel")],
        osint_facts=[osint],
    )
    # Sanity: the rendered text DOES contain the sentinels (so the
    # redaction sweep is meaningful). source_ref (URL) is NOT rendered;
    # it lives only on the model object and could only leak if a
    # logger included the model's repr.
    for sentinel in _RENDERED_SENSITIVE_SUBSTRINGS:
        assert sentinel in out

    _assert_no_leak(caplog.records)


def test_debug_log_contains_only_counts_and_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="ov_black.agent.context")

    assemble_traveler_context(
        dossier=_dossier(),
        dossier_facts=[_dossier_fact("loves heli-skiing")],
        profile_facts=[_profile_fact("morning person")],
        osint_facts=[_osint_fact("CFO at Acme")],
    )

    matched = [r for r in caplog.records if r.name == "ov_black.agent.context"]
    assert matched, "expected a DEBUG record from the context renderer"
    record = matched[-1]
    assert record.levelno == logging.DEBUG
    # The DEBUG record carries the counts + client_id only — no fact text.
    assert record.dossier_facts == 1
    assert record.profile_facts == 1
    assert record.osint_facts == 1
