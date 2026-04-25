"""Traveler-context tools — Dossier + Profile + OSINT read/write.

Three tools, all gated by the per-session **agent token** (not the user
JWT). The traveler must not be able to read Dossier or OSINT, and must
not be able to forge Profile or Dossier entries on their own behalf.

* :func:`get_traveler_context` — single read returning all three tiers
  plus the dossier typed core. Safe to call any time.
* :func:`record_profile_fact` — when the *traveler told the agent
  something*. The endpoint always stamps ``source_kind=traveler_told``
  server-side; the agent cannot pretend a fact is advisor-attributed.
* :func:`record_dossier_inference` — when the *agent inferred something
  privately*. The endpoint always stamps
  ``source_kind=agent_inferred``. These facts are NEVER revealed to the
  traveler — Dossier disclosure rules apply to inferred entries the
  same as advisor-seeded ones.

The model picks between the two write tools by semantic intent. The
docstrings make the distinction explicit so prompting does not need to
restate it.
"""

from __future__ import annotations

from typing import Literal

from strands import tool

from agent.backend import agent_get_json, agent_post_json


_DOSSIER_FACT_KINDS = Literal[
    "passion",
    "motivation",
    "travel_history",
    "trigger",
    "constraint",
    "deal_breaker",
    "dream_signal",
    "party",
    "preference",
    "other",
]
_PROFILE_FACT_KINDS = Literal[
    "passion",
    "motivation",
    "travel_history",
    "trigger",
    "constraint",
    "deal_breaker",
    "dream_signal",
    "preference",
    "aspiration",
    "other",
]


@tool
async def get_traveler_context() -> dict:
    """Fetch the calling client's full traveler context.

    Returns three sections plus the dossier typed core:

    * ``dossier`` — typed signals advisors seeded (group type, children
      ages, contact channel, party notes, net worth). PRIVATE — never
      reveal verbatim.
    * ``dossier_facts`` — long-tail facts and agent-recorded inferences.
      PRIVATE — never reveal verbatim or attribute to the advisor.
    * ``profile_facts`` — what the traveler self-expressed. May be
      referenced naturally in conversation ("you mentioned …").
    * ``osint_facts`` — external research. NEVER reveal, paraphrase, or
      hint that any external research exists.

    Use as ground truth when deciding what to propose or how to frame a
    reply. Read-only; safe to call any time.
    """
    return await agent_get_json("/agent/context")


@tool
async def record_profile_fact(
    *,
    kind: _PROFILE_FACT_KINDS,
    text: str,
    source_turn_id: str | None = None,
) -> dict:
    """Record a fact the traveler **told** you.

    Use this when the traveler shares something about themselves in
    conversation — preferences, past trips, motivations, deal-breakers.
    The fact will be stamped ``source_kind=traveler_told`` and may be
    referenced naturally in future turns ("you mentioned …").

    Do NOT use this for inferences. If you are *guessing* something
    about the traveler from indirect signals, use
    :func:`record_dossier_inference` instead.

    ``text`` should be a short factual statement (under 4000 characters).
    ``source_turn_id`` is optional context the command center uses to
    deep-link the fact back to the originating turn.
    """
    body: dict = {"kind": kind, "text": text}
    if source_turn_id is not None:
        body["source_turn_id"] = source_turn_id
    return await agent_post_json("/agent/profile/facts", json=body)


@tool
async def record_dossier_inference(
    *,
    kind: _DOSSIER_FACT_KINDS,
    text: str,
    source_turn_id: str | None = None,
) -> dict:
    """Record an internal **inference** about the traveler.

    Use this when you are inferring something the traveler did not
    explicitly say — pattern-matching from word choice, tone, or
    indirect signals. The fact will be stamped
    ``source_kind=agent_inferred`` and joins the Dossier tier, which is
    PRIVATE — never reveal it back to the traveler.

    Do NOT use this for things the traveler said directly. If they
    told you, use :func:`record_profile_fact` instead.

    ``text`` should be a short factual statement (under 4000 characters).
    ``source_turn_id`` is optional context the command center uses to
    deep-link the fact back to the originating turn.
    """
    body: dict = {"kind": kind, "text": text}
    if source_turn_id is not None:
        body["source_turn_id"] = source_turn_id
    return await agent_post_json("/agent/dossier/facts", json=body)
