"""Bedrock AgentCore Runtime entrypoint.

The ``BedrockAgentCoreApp`` exposes ``/invocations`` on port 8080 — the
shape ``bedrock-agentcore:InvokeAgentRuntime`` calls. Each request lands
as a JSON payload + request context; we validate, set up the JWT
contextvar, build a Strands ``Agent`` for the turn's mode, and stream
translated events back as SSE dicts.

Redaction: the payload carries sensitive data (traveler context, user
JWT, agent token). Log only session-identifying fields and stable
short reasons; never log the payload body, tool inputs, or tool outputs.
"""

from __future__ import annotations

import logging
import os
import uuid

from bedrock_agentcore import BedrockAgentCoreApp
from pydantic import ValidationError
from strands.models import BedrockModel

from agent.backend import agent_token_ctx, jwt_ctx, pin_ctx
from agent.config import get_settings
from agent.modes import build_agent
from agent.schemas import TurnPayload
from agent.translate import EventTranslator


logger = logging.getLogger("agent.app")


_settings = get_settings()


def _build_model() -> BedrockModel:
    """The shared Bedrock model for every turn.

    When ``thinking_budget_tokens > 0`` we enable **interleaved** extended
    thinking: the model does its planning — which tools to call, how to react
    to a tool failure, what to do next — in a hidden reasoning channel that the
    translator suppresses (surfacing only an anonymous "thinking" pulse for
    liveness). Without it the model has nowhere to put that reasoning and spills
    raw scratchpad — tool names, "the timing call failed", bulleted plans —
    straight into the traveler-visible reply. Interleaved (not plain) so the
    hidden reasoning also covers the steps BETWEEN tool calls, not just the
    turn's opener.
    """
    budget = _settings.thinking_budget_tokens
    extra: dict[str, object] = {}
    if budget > 0:
        extra["additional_request_fields"] = {
            "thinking": {"type": "enabled", "budget_tokens": budget},
            "anthropic_beta": ["interleaved-thinking-2025-05-14"],
        }
    return BedrockModel(
        model_id=_settings.bedrock_model_id,
        region_name=_settings.aws_region,
        streaming=True,
        **extra,
    )


_model = _build_model()

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context=None):  # type: ignore[no-untyped-def]
    """Handle one turn.

    ``payload`` is whatever FastAPI JSON-encoded and sent. ``context``
    is the AgentCore RequestContext (request headers, session id) —
    ignored for M001 since all auth context is carried in the payload.
    """
    try:
        req = TurnPayload.model_validate(payload)
    except ValidationError as exc:
        logger.info(
            "agent.turn.invalid_payload",
            extra={"errors": len(exc.errors())},
        )
        yield {"type": "error", "reason": "invalid_payload"}
        yield {"type": "done"}
        return

    cap = _settings.max_prior_turns
    prior = req.prior_turns[-cap:] if cap else []

    logger.info(
        "agent.turn.start",
        extra={
            "mode": req.mode.value,
            "actor_kind": req.actor_kind,
            "has_itinerary": req.itinerary_id is not None,
            "prior_count": len(prior),
            "client_id": str(req.client_id),
        },
    )

    token_jwt = jwt_ctx.set(req.auth_bearer)
    token_agent = agent_token_ctx.set(req.agent_token or None)
    token_pin = pin_ctx.set(
        {
            "client_id": str(req.client_id),
            "itinerary_id": str(req.itinerary_id) if req.itinerary_id else None,
            "actor_kind": req.actor_kind,
            "audience": req.audience,
        }
    )

    try:
        agent = build_agent(_model, req)
        agent.messages = [
            {"role": turn.role, "content": [{"text": turn.content}]}
            for turn in prior
        ]

        translator = EventTranslator(emit_tool_trace=_settings.emit_tool_trace)
        async for ev in agent.stream_async(req.input_text):
            if not isinstance(ev, dict):
                continue
            for frame in translator.translate(ev):
                yield frame
        yield {"type": "done"}
    except Exception as exc:  # noqa: BLE001 — runtime must never crash
        logger.exception(
            "agent.turn.unhandled",
            extra={"reason": exc.__class__.__name__},
        )
        yield {"type": "error", "reason": "internal_error"}
        yield {"type": "done"}
    finally:
        jwt_ctx.reset(token_jwt)
        agent_token_ctx.reset(token_agent)
        pin_ctx.reset(token_pin)


def main() -> None:
    """Local-dev entry point — ``python -m agent`` serves on :8080."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # BedrockAgentCoreApp.run() binds :8080 on 0.0.0.0 by default.
    app.run()


if __name__ == "__main__":  # pragma: no cover
    main()
