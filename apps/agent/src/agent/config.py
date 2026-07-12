"""Runtime settings — Pydantic Settings over environment variables.

The runtime is a single long-lived process inside AgentCore. All
configuration is read at startup from env; there is no runtime reload.
Secrets (nothing sensitive today — AWS creds come from the task role)
would be injected via Secrets Manager if we needed them.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded once at import time via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── AWS / Bedrock ──────────────────────────────────────────────────────
    aws_region: str = Field(
        default="us-west-2",
        description="AWS region for Bedrock model invocations.",
    )
    bedrock_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        description=(
            "Bedrock inference profile id (cross-region routing). Claude 4.x "
            "Sonnet/Opus do not support on-demand throughput against raw model "
            "ids — must be an inference profile. Sonnet 4.6 runs without "
            "extended thinking by default (fast, no silent between-tool think), "
            "unlike Sonnet 5 whose adaptive thinking is always on."
        ),
    )

    # ── Backend API ────────────────────────────────────────────────────────
    backend_base_url: str = Field(
        default="http://localhost:8000",
        description=(
            "FastAPI base URL the tools call back into. In staging/prod this "
            "is the internal ALB DNS; locally it is the uvicorn dev server."
        ),
    )
    backend_timeout_seconds: float = Field(
        default=15.0,
        ge=1.0,
        description="HTTP timeout per outbound tool call.",
    )

    # ── Observability ──────────────────────────────────────────────────────
    emit_tool_trace: bool = Field(
        default=False,
        description=(
            "When true, the translator emits a `tool_trace` SSE frame per tool "
            "call/result (name + toolUseId + status ONLY — never inputs or "
            "outputs, which can carry Dossier/OSINT content). The browser drops "
            "unknown frame types, so this is only visible to harness consumers "
            "(ovb / the eval runner). Debug-gated: off by default; local dev "
            "turns it on via EMIT_TOOL_TRACE=1."
        ),
    )

    # ── Prompts / pacing ───────────────────────────────────────────────────
    max_prior_turns: int = Field(
        default=20,
        ge=0,
        le=200,
        description=(
            "Upper bound on the number of prior-turn messages we accept in "
            "the payload. The API side caps at the same number on its end; "
            "this is a belt-and-suspenders guard against oversized payloads."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached so repeated calls are free."""
    return Settings()
