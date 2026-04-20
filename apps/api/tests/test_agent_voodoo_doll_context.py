"""Unit tests for ``app.agent.voodoo_doll_context``.

Covers:
  - Field iteration — the assembled string carries every section the
    PRD/R004 expects the agent to ground on.
  - Missing-key tolerance — sparse JSONB shapes don't raise.
  - Redaction sweep — net worth and OSINT notes NEVER appear in any log
    record emitted during ``assemble_context``.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from app.agent.voodoo_doll_context import assemble_context
from app.models.client import ContactChannel, GroupType
from app.models.voodoo_doll import VoodooDoll


def _make_doll(**overrides) -> VoodooDoll:
    """Build an unpersisted VoodooDoll with sane defaults + overrides.

    We never add it to a Session — these tests exercise a pure function
    that only reads attribute values off the ORM object.
    """
    defaults: dict = {
        "id": uuid.uuid4(),
        "client_id": uuid.uuid4(),
        "authored_by": uuid.uuid4(),
        "contact_preference": ContactChannel.email,
        "group_type": GroupType.solo,
        "children_ages": [],
        "travel_party_notes": "",
        "estimated_net_worth_usd": None,
        "passions": [],
        "motivations": {},
        "travel_history": [],
        "triggers": [],
        "constraints": [],
        "deal_breakers": [],
        "dream_trip_signals": {},
        "osint_notes": {},
    }
    defaults.update(overrides)
    return VoodooDoll(**defaults)


def test_assemble_context_renders_every_populated_section() -> None:
    """Every non-empty field appears in the returned context block."""
    doll = _make_doll(
        group_type=GroupType.family,
        children_ages=[7, 11],
        travel_party_notes="Plus nanny on long trips.",
        estimated_net_worth_usd=25_000_000,
        passions=["heli-skiing", "natural wine"],
        motivations={"status": "quiet luxury", "depth": "culture over checklist"},
        travel_history=[
            {"destination": "Aman Tokyo", "year": 2024, "note": "loved omakase"},
        ],
        triggers=["crowded lobbies"],
        constraints=["no long-haul in school term"],
        deal_breakers=["chain hotels"],
        dream_trip_signals={"vibe": "remote patagonia"},
        osint_notes={"linkedin": "profile/jane-doe", "press": "feature in FT"},
    )

    text = assemble_context(doll, client_full_name="Jane Doe")

    assert "Client: Jane Doe" in text
    assert "Group type: family" in text
    assert "Children ages: [7, 11]" in text
    assert "Plus nanny on long trips." in text
    assert "heli-skiing" in text
    assert "natural wine" in text
    assert "quiet luxury" in text
    assert "Aman Tokyo" in text
    assert "crowded lobbies" in text
    assert "no long-haul in school term" in text
    assert "chain hotels" in text
    assert "remote patagonia" in text
    assert "25000000" in text  # net worth included
    assert "linkedin" in text  # osint key present


def test_assemble_context_tolerates_sparse_doll() -> None:
    """A doll with all JSONB fields empty still produces a valid block."""
    doll = _make_doll(group_type=GroupType.solo)
    text = assemble_context(doll)

    # Header always renders.
    assert "Group type: solo" in text
    # Sensitive sections are absent when their source is empty.
    assert "Estimated net worth" not in text
    assert "OSINT notes:" not in text
    assert "Passions:" not in text


def test_assemble_context_skips_empty_sections() -> None:
    """Empty list / dict fields do not produce empty section headers."""
    doll = _make_doll(
        passions=[],
        motivations={},
        travel_history=[],
    )
    text = assemble_context(doll)
    assert "Passions:" not in text
    assert "Motivations:" not in text
    assert "Travel history:" not in text


def test_assemble_context_tolerates_long_tail_extra_keys() -> None:
    """Unknown keys inside JSONB dicts pass through without raising."""
    doll = _make_doll(
        motivations={"status": "quiet luxury", "brand_new_future_key": "ok"},
        dream_trip_signals={"vibe": "remote", "unexpected": {"nested": "value"}},
    )
    # Must not raise and must surface the known keys.
    text = assemble_context(doll)
    assert "status" in text
    assert "brand_new_future_key" in text


def test_assemble_context_redaction_sweep_blocks_secret_leaks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Net-worth and OSINT substrings must never appear in any log record.

    Pattern lifted from tests/test_inventory_ov_provider.py::
    test_api_key_never_logged — walk every captured record and confirm no
    field (message, extras, stringified values) carries the secret.
    """
    net_worth_sentinel = 999999
    osint_sentinel = "DO_NOT_LOG"
    doll = _make_doll(
        estimated_net_worth_usd=net_worth_sentinel,
        osint_notes={"sensitive": osint_sentinel},
        passions=["also-" + osint_sentinel],  # force sentinel into more places
    )

    # Capture everything — DEBUG + WARN + INFO — across both the agent
    # logger and the root, to match what a caplog-walking redaction test
    # would see in production under any log level.
    caplog.set_level(logging.DEBUG)
    returned = assemble_context(doll)

    # Sanity: the returned STRING (which the caller will never log) does
    # carry the sensitive data — that's the whole point of assembling it.
    assert str(net_worth_sentinel) in returned
    assert osint_sentinel in returned

    # Redaction bar: nothing emitted to the log should carry either sentinel.
    for record in caplog.records:
        message = record.getMessage()
        assert str(net_worth_sentinel) not in message
        assert osint_sentinel not in message
        for value in vars(record).values():
            rendered = repr(value)
            assert str(net_worth_sentinel) not in rendered
            assert osint_sentinel not in rendered


def test_assemble_context_emits_debug_log_with_doll_id_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The module emits exactly one DEBUG event naming the doll id — nothing else."""
    doll = _make_doll(estimated_net_worth_usd=42)
    caplog.set_level(logging.DEBUG, logger="ov_black.agent.context")

    assemble_context(doll)

    context_logs = [
        rec for rec in caplog.records if rec.name == "ov_black.agent.context"
    ]
    assert len(context_logs) == 1
    record = context_logs[0]
    assert record.message == "agent.context.assembled"
    assert record.levelno == logging.DEBUG
    assert getattr(record, "doll_id", None) == str(doll.id)
