"""Per-mode system-prompt builders.

Every builder consumes the payload-side ``system`` block (voice preamble
+ Voodoo Doll context) and appends a mode-specific rubric. The rubric
lives here, not on the API side, because it is the runtime's product
surface — we iterate the wording without redeploying FastAPI.
"""

from __future__ import annotations

from agent.prompts.onboarding import build_onboarding_prompt
from agent.prompts.planning import build_planning_prompt
from agent.prompts.qa import build_qa_prompt
from agent.prompts.shared import VOICE_PREAMBLE
from agent.schemas import Mode


def build_prompt(
    *,
    mode: Mode,
    api_system: str,
    actor_kind: str,
    itinerary_id_present: bool,
    seeded_opener: str | None = None,
) -> str:
    """Assemble the full system prompt for a turn.

    ``api_system`` is whatever FastAPI put in ``payload['system']`` —
    today that is the voice preamble + Voodoo Doll context block. If it
    ever arrives empty we still emit the hard-coded voice preamble so
    the agent never runs without one.

    ``seeded_opener`` is honored only in onboarding mode. The API only
    sets it on turn_index == 0 to avoid making the agent repeat the
    opener on later turns.
    """
    preamble = api_system.strip() or VOICE_PREAMBLE

    if mode is Mode.onboarding:
        rubric = build_onboarding_prompt(seeded_opener=seeded_opener)
    elif mode is Mode.planning:
        rubric = build_planning_prompt(
            actor_kind=actor_kind,
            itinerary_id_present=itinerary_id_present,
        )
    else:
        rubric = build_qa_prompt(itinerary_id_present=itinerary_id_present)

    return f"{preamble}\n\n{rubric}"


__all__ = ["build_prompt", "VOICE_PREAMBLE"]
