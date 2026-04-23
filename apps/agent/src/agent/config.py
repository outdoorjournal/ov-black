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
        default="anthropic.claude-sonnet-4-5-20250929-v1:0",
        description=(
            "Foundation model id for Bedrock. Claude Sonnet 4.5 is the "
            "concierge-voice balance point; swap to Opus for slower, "
            "more-considered planning sessions if needed."
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
