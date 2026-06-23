"""Unit tests for ``app.agent.prompt``.

S11: the prompt builder was shrunk to just the voice preamble + Dossier
context block. The mode-specific rubric (onboarding / planning /
Q&A) and the card / assemble tool-use protocol both live in the
runtime workspace at [apps/agent](../../../agent). These tests assert
the voice preamble remains load-bearing and the context block round-
trips verbatim.
"""

from __future__ import annotations

from app.agent.prompt import build_system_prompt

# Voice preamble that MUST appear byte-for-byte — the apps/agent runtime
# duplicates this verbatim as its fallback when ``payload.system`` is
# empty, so any drift here would break the runtime's opening voice.
VOICE_VERBATIM = (
    "You are Outdoor Voyage's Black-tier concierge agent. Speak like a "
    "trusted correspondent — single serif voice, slow-deliberate pacing, "
    "no emoji, no bullet lists, no spinners, no questionnaire feel. "
    "Every reply is prose. Brevity is a craft signal; say less, but say "
    "it well. Never echo the client's private context verbatim."
)


def test_prompt_embeds_voice_verbatim() -> None:
    """The voice preamble must land unmodified in the returned prompt."""
    prompt = build_system_prompt("CONTEXT_PLACEHOLDER")
    assert VOICE_VERBATIM in prompt


def test_prompt_embeds_context_block() -> None:
    """The caller's context string slots into the prompt."""
    ctx = "Client: Jane Doe\nGroup type: couple"
    prompt = build_system_prompt(ctx)
    assert ctx in prompt


def test_prompt_starts_with_voice() -> None:
    """Every prompt opens with the concierge voice framing."""
    prompt = build_system_prompt("")
    assert prompt.startswith("You are Outdoor Voyage's Black-tier concierge agent.")


def test_prompt_is_deterministic() -> None:
    """Pure function — same input → identical output across calls."""
    ctx = "Group type: solo"
    assert build_system_prompt(ctx) == build_system_prompt(ctx)


def test_prompt_no_longer_hardcodes_card_protocol() -> None:
    """S11: card protocol moved to the runtime's prompts/ package."""
    prompt = build_system_prompt("x")
    assert '"type": "card"' not in prompt
    assert "assemble_draft" not in prompt
