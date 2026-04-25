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
from datetime import datetime, timezone

import pytest

from app.agent.traveler_context import assemble_traveler_context
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


_NOW = datetime(2026, 4, 25, tzinfo=timezone.utc)


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


def _dossier_fact(text: str, *, source_kind: FactSourceKind = FactSourceKind.advisor) -> DossierFact:
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


def test_dossier_section_skipped_when_no_dossier_and_no_facts() -> None:
    out = assemble_traveler_context(
        dossier=None,
        dossier_facts=[],
        profile_facts=[_profile_fact("favors small lodges")],
        osint_facts=[],
    )
    assert "Dossier (private" not in out
    assert "Profile (traveler self-expressed" in out


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
            _dossier_fact(
                "inferred_by_agent", source_kind=FactSourceKind.agent_inferred
            ),
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
                f"{sentinel!r} leaked into log record {rec.name} {rec.levelname}: "
                f"{assembled[:200]}"
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
