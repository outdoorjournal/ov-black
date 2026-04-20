"""Unit tests for ``app.agent.prompt``."""

from __future__ import annotations

from app.agent.prompt import build_system_prompt

# Rubric text that MUST appear in the prompt byte-for-byte (R004 contract).
RUBRIC_VERBATIM = (
    "If the client's first message names a specific destination or trip, "
    "orient toward it with a grounded observation drawn from the Voodoo "
    "Doll. Otherwise, steer through conversation without feeling "
    "mechanical — no questionnaires, no bullet lists, no spinners, no "
    "emoji. Single serif agent voice. Slow-deliberate pacing."
)


def test_prompt_embeds_rubric_verbatim() -> None:
    """The R004 rubric must land unmodified in the returned prompt."""
    prompt = build_system_prompt("CONTEXT_PLACEHOLDER")
    assert RUBRIC_VERBATIM in prompt


def test_prompt_embeds_context_block() -> None:
    """The caller's context string slots into the prompt."""
    ctx = "Client: Jane Doe\nGroup type: couple"
    prompt = build_system_prompt(ctx)
    assert ctx in prompt


def test_prompt_has_role_header() -> None:
    """Every prompt opens with the OV Black concierge role framing."""
    prompt = build_system_prompt("")
    assert prompt.startswith("You are Outdoor Voyage's Black-tier concierge agent.")


def test_prompt_is_deterministic() -> None:
    """Pure function — same input → identical output across calls."""
    ctx = "Group type: solo"
    assert build_system_prompt(ctx) == build_system_prompt(ctx)
