from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Values are read from process env (and an optional local .env during dev).
    Never hardcode secrets — they come from Secrets Manager in staging/prod
    and are injected via the ECS task definition (D002).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    env: Literal["local", "staging", "production"] = Field(
        default="local",
        description="Deployment environment.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Root log level for the app.",
    )
    # ── Observability (M005 / obs) ─────────────────────────────────────────
    service_name: str = Field(
        default="ov-black-api",
        description="Logical service name stamped on every log line + metric dimension.",
    )
    log_format: Literal["auto", "json", "text"] = Field(
        default="auto",
        description=(
            "Log line format. 'json' (one structured object per line, for "
            "CloudWatch Logs Insights), 'text' (human console format for local "
            "dev), or 'auto' — text when env=='local', json otherwise."
        ),
    )
    request_log_enabled: bool = Field(
        default=True,
        description="Emit one access-log line per HTTP request (method/route/status/duration).",
    )
    metrics_enabled: bool = Field(
        default=True,
        description=(
            "Emit CloudWatch EMF metric lines (request latency/count, span "
            "durations, payment outcomes). Harmless JSON locally; set false to mute."
        ),
    )
    metrics_namespace: str = Field(
        default="OVBlack/API",
        description="CloudWatch metrics namespace for EMF emissions.",
    )
    db_slow_query_ms: int = Field(
        default=500,
        ge=1,
        description="Log a 'db.slow_query' warning + metric for any query slower than this (ms).",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:54322/postgres",
        description=(
            "Async SQLAlchemy DSN (asyncpg driver). Points at the Supabase "
            "Postgres instance in staging/prod, local Supabase in dev."
        ),
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)

    supabase_url: str = Field(
        default="",
        description="Supabase project URL (e.g. https://<project>.supabase.co).",
    )
    supabase_jwt_issuer: str = Field(
        default="",
        description="Expected JWT issuer — usually <supabase_url>/auth/v1.",
    )
    supabase_jwks_url: str = Field(
        default="",
        description="JWKS endpoint used to verify Supabase-issued JWTs.",
    )
    supabase_service_role_key: str = Field(
        default="",
        description=(
            "Supabase service role key — NEVER log this value. Used only by "
            "the admin-surface routes (e.g. magic-link issuance)."
        ),
        repr=False,
    )

    web_origin: str = Field(
        default="http://localhost:3000",
        description=(
            "Origin of the advisor web app (e.g. https://advisor.ov.com). Used "
            "to build invite redirect_to targets — the magic link lands here "
            "and the client app drives the post-signup flow."
        ),
    )

    ov_base_url: str = Field(
        default="https://www.outdoorvoyage.com",
        description="Base URL for the Outdoor Voyage public API (M001 default).",
    )
    ov_api_key: str = Field(
        default="",
        description=(
            "Optional OV API key. The public search endpoint does not require "
            "one in M001, but if set we forward it as the x-api-key header. "
            "NEVER log this value."
        ),
        repr=False,
    )

    duffel_base_url: str = Field(
        default="https://api.duffel.com",
        description="Base URL for the Duffel flights API.",
    )
    duffel_api_key: str = Field(
        default="",
        description=(
            "Duffel access token, forwarded as the Authorization: Bearer "
            "header. When empty the Duffel provider stays registered but "
            "every search returns []. NEVER log this value."
        ),
        repr=False,
    )
    duffel_api_version: str = Field(
        default="v2",
        description="Duffel API version sent as the Duffel-Version header.",
    )

    ratehawk_base_url: str = Field(
        default="https://api.worldota.net/api/b2b/v3",
        description="Base URL for the Ratehawk (ETG / Worldota) B2B hotels API.",
    )
    ratehawk_key_id: str = Field(
        default="",
        description=(
            "Ratehawk (ETG) key id — the username half of the HTTP Basic "
            "credential. Paired with ratehawk_api_key; both must be set for "
            "the provider to issue calls."
        ),
    )
    ratehawk_api_key: str = Field(
        default="",
        description=(
            "Ratehawk (ETG) API key — the password half of the HTTP Basic "
            "credential, sent in the Authorization header. When empty (or the "
            "key id is empty) the Ratehawk provider stays registered but every "
            "search returns []. NEVER log this value."
        ),
        repr=False,
    )

    google_places_base_url: str = Field(
        default="https://places.googleapis.com",
        description="Base URL for the Google Places API (New) — places.googleapis.com/v1.",
    )
    google_places_api_key: str = Field(
        default="",
        description=(
            "Google Places API key, forwarded as the X-Goog-Api-Key header. "
            "When empty the Google Places provider stays registered but every "
            "search returns []. NEVER log this value — and it must never leak "
            "into a client-facing URL (photo media needs a keyed backend proxy)."
        ),
        repr=False,
    )

    # ── Payments (M005/I2, D025/D-PAY): Braintree ─────────────────────────
    # The gateway is selected by config; when these are empty the payments
    # service degrades to a Fake gateway (CI/local need no credentials) and a
    # live pay call returns ``payments_unconfigured``. NEVER log the keys.
    braintree_environment: str = Field(
        default="sandbox",
        description="Braintree environment: 'sandbox' (default, MVP) or 'production'.",
    )
    braintree_merchant_id: str = Field(
        default="",
        description="Braintree merchant id. When empty, payments degrade to the Fake gateway.",
        repr=False,
    )
    braintree_public_key: str = Field(
        default="",
        description="Braintree public key. NEVER log this value.",
        repr=False,
    )
    braintree_private_key: str = Field(
        default="",
        description="Braintree private key. NEVER log this value.",
        repr=False,
    )
    braintree_timeout_seconds: float = Field(
        default=8.0,
        ge=1.0,
        le=60.0,
        description=(
            "HTTP timeout for Braintree SDK calls (client-token + sale). The "
            "SDK is synchronous; the service offloads it to a worker thread and "
            "this caps how long a charge can hang before raising a timeout."
        ),
    )
    payment_token_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "Bounded retry budget for the READ-ONLY client-token call only. The "
            "charge (sale) is NEVER auto-retried — a retried sale risks a double "
            "charge; safe client retries go through the idempotency key instead."
        ),
    )

    inventory_providers_enabled: str = Field(
        default="ov,mock",
        description=(
            "Comma-separated list of inventory provider sources to register at "
            "startup. Known values: 'ov', 'mock', 'duffel', 'ratehawk', "
            "'google_places'. Unknown names are skipped with a warning so a typo "
            "doesn't crash the boot."
        ),
    )

    aws_region: str = Field(
        default="us-west-2",
        description=(
            "AWS region for the bedrock-agentcore client. Defaults to us-west-2 "
            "where AgentCore Runtime is early-available (S04 research)."
        ),
    )
    bedrock_agentcore_runtime_arn: str = Field(
        default="",
        description=(
            "Full ARN of the provisioned AgentCore Runtime agent. Empty during "
            "local dev / tests — callers must check before invoking."
        ),
    )
    vault_bucket_name: str = Field(
        default="",
        description=(
            "S3 bucket for the secure document vault (M003/V3). Empty during "
            "local dev / tests — the lifespan wires a MockVaultStorage when "
            "unset so pytest runs without AWS. Objects are SSE-KMS encrypted via "
            "the bucket's default (aws/s3 managed) key."
        ),
    )
    vault_presigned_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        description=(
            "Lifetime of presigned upload/download URLs for vault documents. "
            "Short by design (default 15 min) — access is re-minted per request."
        ),
    )
    agent_first_token_timeout_seconds: float = Field(
        default=8.0,
        ge=0.1,
        description=(
            "Hard ceiling on time-to-first-token before we cut the upstream "
            "and fall into the retry envelope. Belt for the 2 s R015 target."
        ),
    )
    agent_max_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        description=(
            "Silent retry budget per turn. R018 specifies 'within one retry' "
            "so the default is 1 (i.e. 1 original + 1 retry = 2 attempts)."
        ),
    )
    bedrock_agentcore_memory_id: str = Field(
        default="",
        description=(
            "AgentCore Memory id for the per-session scratchpad. Empty value "
            "disables CreateEvent calls — the write becomes a no-op so local "
            "runs don't require a provisioned Memory resource."
        ),
    )
    analyze_reaper_max_running_seconds: int = Field(
        default=600,
        ge=30,
        description=(
            "Startup reaper threshold (Phase 5 Analyze): a 'running' analyses "
            "row older than this is marked 'failed' (abandoned_at_restart). "
            "10 min leaves headroom for slow live providers without leaving "
            "genuinely orphaned rows around for hours."
        ),
    )
    agent_local_url: str = Field(
        default="",
        description=(
            "When set (e.g. ``http://localhost:8080``), the FastAPI lifespan "
            "wires LocalAgentRuntimeClient instead of Boto3 — lets local dev "
            "exercise the ``apps/agent`` runtime over HTTP without AWS creds."
        ),
    )
    agent_token_signing_secret: str = Field(
        default="",
        description=(
            "HS256 signing key for per-session agent tokens minted at "
            "POST /sessions. The token authenticates the agent runtime to "
            "backend-only /agent/* endpoints (Dossier + Profile + OSINT "
            "context, private fact writes) — those routes must never accept "
            "a Supabase client JWT. Empty value disables minting; verify "
            "fails closed. Use a random 32+ byte value in staging/prod."
        ),
        repr=False,
    )
    agent_token_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=43200,
        description=(
            "Lifetime of a freshly minted per-session agent token. 15 min "
            "default keeps the blast radius small if the token leaks. The "
            "agent runtime must not require a longer-lived token because "
            "POST /sessions is called for every fresh session — and "
            "long-running sessions can ask for a refresh in a later slice."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
