"""Render a VoodooDoll row as a structured context block for the agent.

The returned string is passed into the system prompt so the model can
ground its opening turn on known signals (R003/R004). Three discipline
rules govern this module:

1. The returned text MUST NEVER be logged at INFO/WARN. Net-worth and
   OSINT notes live in here; the redaction sweep test in
   ``test_agent_voodoo_doll_context.py`` walks every caplog record after
   a call and asserts no secret substring leaks.
2. The only log this module emits is ``agent.context.assembled`` at DEBUG
   level, carrying ``doll_id`` only — never the context text.
3. Tolerate sparse / long-tail JSONB shapes. Any empty section is skipped;
   unknown extra keys in the JSONB dicts pass through ``.get(...)``
   without raising.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.voodoo_doll import VoodooDoll

logger = logging.getLogger("ov_black.agent.context")


def _fmt_list(items: Any) -> list[str]:
    if not items:
        return []
    try:
        return [str(item).strip() for item in items if item not in (None, "")]
    except TypeError:
        return []


def _fmt_mapping(mapping: Any) -> list[str]:
    if not isinstance(mapping, dict) or not mapping:
        return []
    rendered: list[str] = []
    for key, value in mapping.items():
        if value in (None, "", [], {}):
            continue
        rendered.append(f"- {key}: {value}")
    return rendered


def _fmt_travel_history(history: Any) -> list[str]:
    if not history:
        return []
    lines: list[str] = []
    if isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict):
                place = entry.get("destination") or entry.get("place") or entry.get("where")
                year = entry.get("year")
                note = entry.get("note") or entry.get("summary")
                bits = [str(x) for x in (place, year, note) if x not in (None, "")]
                if bits:
                    lines.append("- " + " · ".join(bits))
            elif entry not in (None, ""):
                lines.append(f"- {entry}")
    elif isinstance(history, dict):
        lines.extend(_fmt_mapping(history))
    return lines


def assemble_context(doll: VoodooDoll, *, client_full_name: str | None = None) -> str:
    """Return a plaintext context block for the agent.

    ``client_full_name`` is optional so unit tests (and callers that only
    have the VoodooDoll row in hand) can skip the Client join; the service
    layer in T04 passes the real name fetched alongside the doll.
    """
    sections: list[str] = []

    header_bits: list[str] = []
    if client_full_name:
        header_bits.append(f"Client: {client_full_name}")
    header_bits.append(f"Group type: {doll.group_type.value if hasattr(doll.group_type, 'value') else doll.group_type}")
    if doll.children_ages:
        header_bits.append(f"Children ages: {list(doll.children_ages)}")
    contact_pref = (
        doll.contact_preference.value
        if hasattr(doll.contact_preference, "value")
        else doll.contact_preference
    )
    header_bits.append(f"Preferred contact: {contact_pref}")
    if doll.travel_party_notes:
        header_bits.append(f"Travel party: {doll.travel_party_notes}")
    sections.append("\n".join(header_bits))

    # Passions — JSONB list of free-form strings/dicts.
    passion_lines = _fmt_list(doll.passions)
    if passion_lines:
        sections.append("Passions:\n" + "\n".join(f"- {p}" for p in passion_lines))

    # Motivations — JSONB dict keyed by motivation label.
    motivation_lines = _fmt_mapping(doll.motivations)
    if motivation_lines:
        sections.append("Motivations:\n" + "\n".join(motivation_lines))

    # Travel history — list of dicts or free-form strings.
    history_lines = _fmt_travel_history(doll.travel_history)
    if history_lines:
        sections.append("Travel history:\n" + "\n".join(history_lines))

    trigger_lines = _fmt_list(doll.triggers)
    if trigger_lines:
        sections.append("Triggers:\n" + "\n".join(f"- {t}" for t in trigger_lines))

    constraint_lines = _fmt_list(doll.constraints)
    if constraint_lines:
        sections.append("Constraints:\n" + "\n".join(f"- {c}" for c in constraint_lines))

    deal_breaker_lines = _fmt_list(doll.deal_breakers)
    if deal_breaker_lines:
        sections.append(
            "Deal-breakers:\n" + "\n".join(f"- {d}" for d in deal_breaker_lines)
        )

    dream_lines = _fmt_mapping(doll.dream_trip_signals)
    if dream_lines:
        sections.append("Dream trip signals:\n" + "\n".join(dream_lines))

    # Sensitive grounding signals per the PRD — these MUST NOT appear in
    # any log record. The redaction sweep test in the test module walks
    # caplog and asserts they never leak.
    if doll.estimated_net_worth_usd is not None:
        sections.append(
            f"Estimated net worth (USD): {int(doll.estimated_net_worth_usd)}"
        )

    osint_lines = _fmt_mapping(doll.osint_notes)
    if osint_lines:
        sections.append("OSINT notes:\n" + "\n".join(osint_lines))

    # DEBUG only — name the doll, never the contents.
    logger.debug(
        "agent.context.assembled",
        extra={"doll_id": str(doll.id)},
    )

    return "\n\n".join(sections)
