"""Bedrock AgentCore Runtime entrypoint.

The ``BedrockAgentCoreApp`` exposes ``/invocations`` on port 8080 — the
shape ``bedrock-agentcore:InvokeAgentRuntime`` calls. Each request lands
as a JSON payload + request context; we validate, set up the JWT
contextvar, build a Strands ``Agent`` for the turn's mode, and stream
translated events back as SSE dicts.

Redaction: the payload carries sensitive data (Voodoo Doll context,
user JWT). Log only session-identifying fields and stable short
reasons; never log the payload body, tool inputs, or tool outputs.
"""

from __future__ import annotations

import logging
import os
import uuid

from bedrock_agentcore import BedrockAgentCoreApp
from pydantic import ValidationError
from strands.models import BedrockModel

from agent.backend import jwt_ctx, pin_ctx
from agent.config import get_settings
from agent.modes import build_agent
from agent.schemas import TurnPayload
from agent.translate import translate_event


logger = logging.getLogger("agent.app")


_settings = get_settings()
_model = BedrockModel(
    model_id=_settings.bedrock_model_id,
    region_name=_settings.aws_region,
    streaming=True,
)

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
    token_pin = pin_ctx.set(
        {
            "client_id": str(req.client_id),
            "itinerary_id": str(req.itinerary_id) if req.itinerary_id else None,
            "actor_kind": req.actor_kind,
        }
    )

    try:
        agent = build_agent(_model, req)
        agent.messages = [
            {"role": turn.role, "content": [{"text": turn.content}]}
            for turn in prior
        ]

        async for ev in agent.stream_async(req.input_text):
            if not isinstance(ev, dict):
                continue
            for frame in translate_event(ev):
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
