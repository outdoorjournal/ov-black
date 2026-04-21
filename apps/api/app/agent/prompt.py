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

# S07 card-proposal protocol. When the agent wants to suggest a real OV
# experience, it emits a standalone event of the exact shape below on the
# runtime event stream — the service forwards it verbatim to the browser as
# an SSE frame, and the mood-board aside renders one card per frame.
_CARD_PROTOCOL = (
    "When you want to propose a real Outdoor Voyage experience, emit a "
    "standalone event of this exact shape (in addition to your spoken "
    'reply): {"type": "card", "source": "ov", "source_id": "<ov inventory '
    'id>", "snapshot": {"title": "...", "cover_image": "...", "price": '
    '"...", "duration_days": 0, "difficulty": "...", "location": "...", '
    '"activities": ["..."]}}. Propose up to three cards per turn. Only '
    "reference OV inventory items by their real source_id — never invent "
    "one. Do not describe the card in prose; the aside renders it."
)

# S08 assemble-draft protocol. When the client has agreed to a set of
# proposed cards and the agent is ready to sketch a day-by-day ordering,
# emit one standalone event carrying the per-day ordered node ids. The
# service writes the ``follows`` edges and forwards the event to the
# browser with an ``edges_created`` field so the advisor surface can
# reflect assembly progress without a separate fetch.
_ASSEMBLE_PROTOCOL = (
    "When you are ready to propose a day-by-day ordering of cards the "
    "client has agreed to, emit a standalone event of this exact shape "
    "(in addition to any prose): "
    '{"type": "assemble_draft", "day_plan": [{"day_index": 0, '
    '"node_ids_in_order": ["<node uuid>", "<node uuid>"]}]}. Reference '
    "only node ids that were returned on prior card frames this session. "
    "Emit assemble_draft at most once per turn."
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
        f"{_CARD_PROTOCOL}\n\n"
        f"{_ASSEMBLE_PROTOCOL}\n\n"
        "Client context (private — never echo verbatim):\n"
        f"{voodoo_doll_context}"
    )
