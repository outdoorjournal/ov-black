"""Pydantic models that validate the payload FastAPI sends on InvokeAgentRuntime.

The boto3 side (FastAPI's ``_sse_encode``) does not enforce a shape — the
runtime is on the hook for validation. :class:`TurnPayload` is the
contract. A malformed payload surfaces to the caller as an ``error``
frame; the runtime must not crash on a shape mismatch (AgentCore treats
an unclean exit as a crash and may mark the agent unhealthy).
"""

from __future__ import annotations

import enum
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, enum.Enum):
    """Which concierge persona the agent runs this turn.

    Detected on the FastAPI side from the session + itinerary state; the
    runtime trusts the value verbatim to avoid a redundant DB round-trip.
    """

    onboarding = "onboarding"
    planning = "planning"
    qa = "qa"


class PriorTurn(BaseModel):
    """One historical message from ``agent_turns``, for prompt replay."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str


class TurnPayload(BaseModel):
    """Validated envelope for one turn invocation.

    Every field is load-bearing:

    - ``system`` — voice preamble + traveler context (Dossier + Profile +
      OSINT), assembled on the API side. Concatenated with the
      mode-specific rubric on the runtime side to form the final system
      prompt.
    - ``input_text`` — the current user message.
    - ``prior_turns`` — last N turns for the same session.
    - ``mode`` — selects the rubric + tool set.
    - ``auth_bearer`` — forwarded Supabase JWT. Tools that act on the
      *user's* own resources (itineraries, mutations) set this as the
      Authorization header on outbound calls; ``require_user`` /
      ``require_advisor`` enforce access.
    - ``agent_token`` — backend-only HS256 token minted at POST /sessions
      and stashed only here. The traveler-context tools
      (``get_traveler_context``, ``record_profile_fact``,
      ``record_dossier_inference``) present this token instead of the
      user JWT — the ``/agent/*`` routes reject Supabase JWTs by design.
    - ``actor_kind`` — ``user`` (client) or ``advisor``.
    - ``client_id`` — UUID of the ``clients`` row.
    - ``itinerary_id`` — non-null for planning / approved-itinerary Q&A.
    """

    model_config = ConfigDict(extra="ignore")

    system: str = Field(default="", description="Voice + traveler-context preamble.")
    input_text: str = Field(min_length=1, max_length=16000)
    prior_turns: list[PriorTurn] = Field(default_factory=list, max_length=200)
    mode: Mode
    auth_bearer: str = Field(min_length=1, max_length=8000)
    agent_token: str = Field(default="", max_length=8000)
    actor_kind: Literal["user", "advisor"] = "user"
    client_id: uuid.UUID
    itinerary_id: uuid.UUID | None = None
    # Set by the API only on turn_index 0 of an onboarding session that
    # opened from /basecamp's single-prompt UI. The runtime appends a
    # directive instructing the agent to echo this opener verbatim as its
    # first message, so the streamed response matches the prompt the user
    # already saw on the page. Empty / None on every other turn.
    seeded_opener: str | None = Field(default=None, max_length=500)


class ProposeCardArgs(BaseModel):
    """Args for the ``propose_card`` tool."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=40, description="Provider key (e.g. 'ov').")
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=400)
    snapshot: dict = Field(default_factory=dict)


class AssembleDraftDay(BaseModel):
    """One day in ``assemble_draft``'s plan."""

    model_config = ConfigDict(extra="forbid")

    day_index: int = Field(ge=0, le=365)
    node_ids_in_order: list[uuid.UUID] = Field(min_length=1, max_length=40)


class AssembleDraftArgs(BaseModel):
    """Args for the ``assemble_draft`` tool."""

    model_config = ConfigDict(extra="forbid")

    day_plan: list[AssembleDraftDay] = Field(min_length=1, max_length=90)


class UpdateNodeStatusArgs(BaseModel):
    """Args for the ``update_node_status`` tool."""

    model_config = ConfigDict(extra="forbid")

    node_id: uuid.UUID
    status: Literal[
        "idea", "proposed", "approved", "booked", "confirmed", "discarded"
    ]


class SearchInventoryArgs(BaseModel):
    """Args for the ``search_inventory`` tool."""

    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, max_length=200)
    kinds: list[str] | None = Field(default=None, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=50)
