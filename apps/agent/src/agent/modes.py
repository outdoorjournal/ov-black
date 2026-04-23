"""Per-mode Strands ``Agent`` factory.

One ``Agent`` is built per turn — cheap (just a tool-list and prompt
bind) and lets the system prompt + tool set vary with the payload's
``mode`` field. The model object itself is shared across turns.
"""

from __future__ import annotations

from typing import Any

from strands import Agent

from agent.prompts import build_prompt
from agent.schemas import TurnPayload
from agent.tools import tools_for


def build_agent(model: Any, payload: TurnPayload) -> Agent:
    """Return an ``Agent`` configured for the requested mode."""
    system_prompt = build_prompt(
        mode=payload.mode,
        api_system=payload.system,
        actor_kind=payload.actor_kind,
        itinerary_id_present=payload.itinerary_id is not None,
    )
    tools = tools_for(payload.mode)
    return Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )
