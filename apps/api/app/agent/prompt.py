"""System-prompt builder — voice preamble + Voodoo Doll context.

The mode-specific rubric (onboarding vs. planning vs. Q&A) and the
tool-use protocol (how to propose cards, how to assemble a draft) both
live in the runtime workspace at
[apps/agent/src/agent/prompts/](../../../../agent/src/agent/prompts/).
This module stays narrow: it assembles what the *API* knows — the voice
and the private client context — and hands it to the runtime via the
``system`` field of the InvokeAgentRuntime payload.

The voice preamble is duplicated verbatim in ``apps/agent``'s
``prompts/shared.py`` so the runtime still has a voice anchor even if
the API sends an empty ``system`` field during a bug or rollback.
"""

from __future__ import annotations

# Kept verbatim so the rest of the stack (redaction tests, agent runtime
# shared preamble) continues to match byte-for-byte.
_VOICE = (
    "You are Outdoor Voyage's Black-tier concierge agent. Speak like a "
    "trusted correspondent — single serif voice, slow-deliberate pacing, "
    "no emoji, no bullet lists, no spinners, no questionnaire feel. "
    "Every reply is prose. Brevity is a craft signal; say less, but say "
    "it well. Never echo the client's private context verbatim."
)


def build_system_prompt(voodoo_doll_context: str) -> str:
    """Return voice preamble + Voodoo Doll context block.

    ``voodoo_doll_context`` comes from
    :func:`app.agent.voodoo_doll_context.assemble_context` and carries
    sensitive signals (net worth, OSINT notes) — the caller must NEVER
    log it. The runtime appends its own mode-specific rubric on top of
    this text to form the final system prompt.
    """
    return (
        f"{_VOICE}\n\n"
        "Client context (private — never echo verbatim):\n"
        f"{voodoo_doll_context}"
    )
