"""System-prompt builder — voice preamble + traveler context.

The mode-specific rubric (onboarding vs. planning vs. Q&A) and the
tool-use protocol (how to propose cards, how to assemble a draft) both
live in the runtime workspace at
[apps/agent/src/agent/prompts/](../../../../agent/src/agent/prompts/).
This module stays narrow: it assembles what the *API* knows — the voice
and the private traveler context — and hands it to the runtime via the
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


_DISCLOSURE_RULES = (
    "Disclosure rules — apply per tier:\n"
    "- Dossier facts: ground your reasoning, but never quote them, never "
    "attribute them to the advisor, and never confirm to the traveler that "
    "you have a dossier on them. If they ask what you 'know,' answer in "
    "terms of what they have shared.\n"
    "- Profile facts: may be referenced naturally — these came from the "
    "traveler ('you mentioned …', 'as you said …'). Use them to make the "
    "conversation feel like a continuation, not an interview.\n"
    "- OSINT facts: NEVER mention, allude to, paraphrase, or hint that any "
    "external research exists. Internal grounding only — they shape what "
    "you suggest, never what you say."
)


def build_system_prompt(traveler_context: str) -> str:
    """Return voice preamble + disclosure rules + traveler context block.

    ``traveler_context`` comes from
    :func:`app.agent.traveler_context.assemble_traveler_context` and
    carries sensitive signals (net worth, OSINT) — the caller must NEVER
    log it. The runtime appends its own mode-specific rubric on top of
    this text to form the final system prompt.
    """
    return (
        f"{_VOICE}\n\n"
        f"{_DISCLOSURE_RULES}\n\n"
        f"Traveler context (private):\n"
        f"{traveler_context}"
    )
