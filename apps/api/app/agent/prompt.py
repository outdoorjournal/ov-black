"""System-prompt builder for the R004 adaptive-onboarding agent.

This file is small on purpose — it is the load-bearing craft artifact for
R003/R004 and will be audited for every wording change. Keep the rubric
verbatim; the tests assert it appears in the returned prompt byte-for-byte.
"""

from __future__ import annotations

# The rubric below is the R004 contract — do not paraphrase without
# updating tests and DECISIONS.md.
_RUBRIC = (
    "If the client's first message names a specific destination or trip, "
    "orient toward it with a grounded observation drawn from the Voodoo "
    "Doll. Otherwise, steer through conversation without feeling "
    "mechanical — no questionnaires, no bullet lists, no spinners, no "
    "emoji. Single serif agent voice. Slow-deliberate pacing."
)


def build_system_prompt(voodoo_doll_context: str) -> str:
    """Wrap the R004 rubric around an assembled Voodoo Doll context block.

    ``voodoo_doll_context`` comes from
    :func:`app.agent.voodoo_doll_context.assemble_context` and carries
    sensitive signals (net worth, OSINT notes) — the caller must NEVER log
    it. This function returns a single concatenated string; the agent
    service injects it as the system-role message on the InvokeAgentRuntime
    payload.
    """
    return (
        "You are Outdoor Voyage's Black-tier concierge agent.\n\n"
        f"{_RUBRIC}\n\n"
        "Client context (private — never echo verbatim):\n"
        f"{voodoo_doll_context}"
    )
