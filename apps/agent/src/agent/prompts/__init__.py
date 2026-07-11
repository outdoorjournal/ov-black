"""Per-mode system-prompt builders.

Every builder consumes the payload-side ``system`` block (voice preamble
+ Dossier context) and appends a mode-specific rubric. The rubric
lives here, not on the API side, because it is the runtime's product
surface — we iterate the wording without redeploying FastAPI.
"""

from __future__ import annotations

from agent.prompts.intake import build_intake_prompt
from agent.prompts.onboarding import build_onboarding_prompt
from agent.prompts.planning import build_planning_prompt
from agent.prompts.qa import build_qa_prompt
from agent.prompts.shared import RENDERING_NOTE, VOICE_PREAMBLE
from agent.schemas import Mode


def build_prompt(
    *,
    mode: Mode,
    api_system: str,
    actor_kind: str,
    itinerary_id_present: bool,
) -> str:
    """Assemble the full system prompt for a turn.

    ``api_system`` is whatever FastAPI put in ``payload['system']`` —
    today that is the voice preamble + Dossier context block. If it
    ever arrives empty we still emit the hard-coded voice preamble so
    the agent never runs without one.
    """
    preamble = api_system.strip() or VOICE_PREAMBLE

    if mode is Mode.onboarding:
        rubric = build_onboarding_prompt()
    elif mode is Mode.intake:
        rubric = build_intake_prompt()
    elif mode is Mode.planning:
        rubric = build_planning_prompt(
            actor_kind=actor_kind,
            itinerary_id_present=itinerary_id_present,
        )
    else:
        rubric = build_qa_prompt(itinerary_id_present=itinerary_id_present)

    return f"{preamble}\n\n{rubric}\n\n{RENDERING_NOTE}"


__all__ = ["build_prompt", "VOICE_PREAMBLE"]
