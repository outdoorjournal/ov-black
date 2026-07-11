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

from agent.backend import (
    agent_delete_json,
    agent_get_json,
    agent_patch_json,
    agent_post_json,
)


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

    Returns these sections plus the dossier typed core:

    * ``trip_brief`` — the goal + timing the traveller set for THIS itinerary
      ("Sailing in Greece with my family"; a window; constraints like "not
      August"). Non-private: ground every suggestion in it and reference it
      naturally. May be null before a brief is set.
    * ``dossier`` — typed signals advisors seeded (group type, children
      ages, contact channel, party notes, net worth). PRIVATE — never
      reveal verbatim.
    * ``dossier_facts`` — long-tail facts and agent-recorded inferences.
      PRIVATE — never reveal verbatim or attribute to the advisor.
    * ``profile_facts`` — what the traveler self-expressed. May be
      referenced naturally in conversation ("you mentioned …").
    * ``osint_facts`` — external research. NEVER reveal, paraphrase, or
      hint that any external research exists.
    * ``party_members`` — the saved travelling party (each with an ``id``,
      names, relationships, dietary/medical/mobility, etc.), remembered across
      trips. SHARED — you MAY reference and confirm these naturally ("I have
      Sarah down as vegetarian — still right?"). Use them so a returning
      traveller never re-states who is coming. When the traveller adds detail
      about someone already here, call :func:`update_party_member` with that
      member's ``id`` — do not duplicate them. Only a genuinely new person goes
      through :func:`record_party_member`.

    Use as ground truth when deciding what to propose or how to frame a
    reply. Read-only; safe to call any time.
    """
    return await agent_get_json("/agent/context")


@tool
async def record_party_member(
    *,
    full_name: str,
    relationship: str | None = None,
    date_of_birth: str | None = None,
    nationality: str | None = None,
    dietary: str | None = None,
    medical: str | None = None,
    mobility: str | None = None,
    is_primary: bool = False,
    notes: str | None = None,
) -> dict:
    """Save a NEW member of the traveller's party that you learned about.

    Use this only when the traveller names someone who is NOT already in the
    party — a spouse, a child, a colleague you have no record of. Party members
    are durable: they are remembered across every trip, so recording one here
    means a returning traveller never has to re-enter who is coming. The
    constraints you save (``dietary`` / ``mobility``) flow into feasibility
    checks when filling gaps.

    CHECK FIRST: read ``party_members`` from :func:`get_traveler_context`
    before calling this. If the person is already there — even under a
    placeholder like "youngest daughter" or with no name yet — do NOT create a
    second row; call :func:`update_party_member` with that member's ``id``
    instead. "My youngest is Quinn" almost always means an existing child, not
    a new one. Duplicating a family member is a visible, embarrassing mistake.

    Party data is SHARED, not private — you may confirm it with the
    traveller. This is distinct from :func:`record_profile_fact` (a
    free-form preference about the traveller themselves) and
    :func:`record_dossier_inference` (a private guess).

    * ``full_name`` — required; the member's name as the traveller gave it.
    * ``relationship`` — to the primary traveller ("spouse", "son", …).
    * ``date_of_birth`` — ISO ``YYYY-MM-DD`` ONLY if the traveller stated it.
      Never invent or estimate a birthday — omit it if you do not have it.
    * ``dietary`` / ``medical`` / ``mobility`` — short free-text notes.
    * ``is_primary`` — true only for the account holder themselves.
    """
    body: dict = {"full_name": full_name, "is_primary": is_primary}
    if relationship is not None:
        body["relationship_to_primary"] = relationship
    if date_of_birth is not None:
        body["date_of_birth"] = date_of_birth
    if nationality is not None:
        body["nationality"] = nationality
    if dietary is not None:
        body["dietary"] = dietary
    if medical is not None:
        body["medical"] = medical
    if mobility is not None:
        body["mobility"] = mobility
    if notes is not None:
        body["notes"] = notes
    return await agent_post_json("/agent/party-members", json=body)


@tool
async def update_party_member(
    *,
    member_id: str,
    full_name: str | None = None,
    relationship: str | None = None,
    date_of_birth: str | None = None,
    nationality: str | None = None,
    dietary: str | None = None,
    medical: str | None = None,
    mobility: str | None = None,
    is_primary: bool | None = None,
    notes: str | None = None,
) -> dict:
    """Update a party member the traveller ALREADY has on file.

    Reach for this — not :func:`record_party_member` — whenever the person is
    already in ``party_members`` from :func:`get_traveler_context` and the
    traveller gives you something new about them: naming a child you only had
    as "youngest daughter", adding a dietary restriction, fixing a spelling.
    Match on WHO they mean, not on an exact name string — "my youngest is
    Quinn" refers to the existing youngest child, so update that member rather
    than creating a second one.

    * ``member_id`` — required; the ``id`` of the party member from your
      context. This is how you target an existing person.
    * every other field is OPTIONAL — pass only what is changing; anything you
      omit is left exactly as it was.
    * ``date_of_birth`` — ISO ``YYYY-MM-DD`` ONLY if the traveller stated it.
      Never invent or estimate a birthday.
    """
    body: dict = {}
    if full_name is not None:
        body["full_name"] = full_name
    if relationship is not None:
        body["relationship_to_primary"] = relationship
    if date_of_birth is not None:
        body["date_of_birth"] = date_of_birth
    if nationality is not None:
        body["nationality"] = nationality
    if dietary is not None:
        body["dietary"] = dietary
    if medical is not None:
        body["medical"] = medical
    if mobility is not None:
        body["mobility"] = mobility
    if is_primary is not None:
        body["is_primary"] = is_primary
    if notes is not None:
        body["notes"] = notes
    return await agent_patch_json(f"/agent/party-members/{member_id}", json=body)


@tool
async def add_trip_traveler(*, member_id: str) -> dict:
    """Seat an EXISTING party member on the trip you're planning right now.

    Party membership is durable (household identity); being on a *specific* trip
    is separate. Call this when the traveller confirms that someone already in
    their ``party_members`` (from :func:`get_traveler_context`) is coming on THIS
    trip — a returning traveller's spouse or child you already have on file. This
    is what makes the itinerary's travel party read correctly (and expands
    per-person costs for the whole group); without it, a companion stays in the
    household but the trip still shows "just you".

    You do NOT need this for a brand-new person — :func:`record_party_member`
    already both saves them AND seats them on this trip in one step. Reach for
    this only to add someone who is already on file. Seating the same member
    twice is harmless. Returns the trip's full roster so you can confirm who is
    coming.

    * ``member_id`` — the ``id`` of the party member from your context.
    """
    return await agent_post_json("/agent/trip-travelers", json={"member_id": member_id})


@tool
async def remove_trip_traveler(*, member_id: str) -> dict:
    """Take a member off the CURRENT trip (they stay in the household roster).

    Use when someone already on this trip is not coming this time ("leave Quinn
    out of this one"). It removes them from this trip's party only; they remain
    in ``party_members`` for future trips, so you are not deleting anyone. Match
    on WHO they mean and pass that member's ``id``. Returns the trip's remaining
    roster.

    * ``member_id`` — the ``id`` of the party member from your context.
    """
    return await agent_delete_json(f"/agent/trip-travelers/{member_id}")


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
