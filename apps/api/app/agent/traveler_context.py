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
from typing import Iterable

from app.models import Dossier, DossierFact, OsintFact, ProfileFact

logger = logging.getLogger("ov_black.agent.context")


def _enum_value(maybe_enum) -> str:
    return maybe_enum.value if hasattr(maybe_enum, "value") else str(maybe_enum)


def _typed_core_lines(dossier: Dossier | None) -> list[str]:
    if dossier is None:
        return []
    bits: list[str] = [
        f"Group type: {_enum_value(dossier.group_type)}",
    ]
    if dossier.children_ages:
        bits.append(f"Children ages: {list(dossier.children_ages)}")
    bits.append(f"Preferred contact: {_enum_value(dossier.contact_preference)}")
    if dossier.travel_party_notes:
        bits.append(f"Travel party: {dossier.travel_party_notes}")
    if dossier.estimated_net_worth_usd is not None:
        # Sensitive — must never appear in any log record. The redaction
        # sweep test enforces this at the test layer; here we just emit it.
        bits.append(
            f"Estimated net worth (USD): {int(dossier.estimated_net_worth_usd)}"
        )
    return bits


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


def assemble_traveler_context(
    *,
    dossier: Dossier | None,
    dossier_facts: list[DossierFact],
    profile_facts: list[ProfileFact],
    osint_facts: list[OsintFact],
    client_full_name: str | None = None,
) -> str:
    """Return the three-tier context block for the system prompt.

    The output is plaintext — no JSON, no Markdown — because the runtime
    appends its mode-specific rubric on top of this and concatenation is
    the simplest reliable framing.
    """
    sections: list[str] = []

    if client_full_name:
        sections.append(f"Client: {client_full_name}")

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
