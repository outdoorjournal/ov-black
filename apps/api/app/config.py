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
        description="Base URL for the Duffel API (shared by flights + Stays hotels).",
    )
    duffel_api_key: str = Field(
        default="",
        description=(
            "Duffel access token, forwarded as the Authorization: Bearer "
            "header by both the flights ('duffel') and hotels ('duffel_stays') "
            "providers. When empty those providers stay registered but every "
            "search returns []. NEVER log this value."
        ),
        repr=False,
    )
    duffel_api_version: str = Field(
        default="v2",
        description="Duffel API version sent as the Duffel-Version header (flights + Stays).",
    )

    exchange_rate_api_base_url: str = Field(
        default="https://v6.exchangerate-api.com/v6",
        description=(
            "Base URL for exchangerate-api.com v6 (shared with voyage-site). "
            "Rates are fetched as ``/{key}/latest/{base}`` and cached in-process."
        ),
    )
    exchange_rates_api_key: str = Field(
        default="",
        description=(
            "exchangerate-api.com v6 API key. When empty the FX service is "
            "disabled and money is displayed in its native (provider) currency "
            "with no conversion. NEVER log this value."
        ),
        repr=False,
    )
    exchange_rate_cache_ttl_seconds: int = Field(
        default=21600,
        ge=60,
        le=86400,
        description="In-process cache lifetime for fetched exchange-rate tables (default 6h).",
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

    google_routes_base_url: str = Field(
        default="https://routes.googleapis.com",
        description=(
            "Base URL for the Google Routes API (computeRoutes). Authenticated "
            "with google_places_api_key (one Google key, Routes API enabled)."
        ),
    )

    factbook_base_url: str = Field(
        default="https://raw.githubusercontent.com/factbook/factbook.json/master",
        description=(
            "Base URL of the factbook.json mirror (public-domain CIA World "
            "Factbook data) used for place-drawer country texture."
        ),
    )
    wikipedia_api_base_url: str = Field(
        default="https://en.wikipedia.org/api/rest_v1",
        description="Wikipedia REST API base used for place-drawer summaries (no key).",
    )

    bokun_base_url: str = Field(
        default="https://api.bokun.io",
        description=(
            "Base URL for the Bokun (Seller) REST API. Production is "
            "api.bokun.io; the sandbox is api.bokuntest.com (a SEPARATE account "
            "with its own access/secret keys — production keys 401 there)."
        ),
    )
    bokun_access_key: str = Field(
        default="",
        description=(
            "Bokun API access key — the public half of the HMAC credential, sent "
            "as the X-Bokun-AccessKey header. Paired with bokun_secret_key; both "
            "must be set for the provider to issue calls. When empty the Bokun "
            "provider stays registered but every search returns []."
        ),
        repr=False,
    )
    bokun_secret_key: str = Field(
        default="",
        description=(
            "Bokun API secret key — used to compute the HmacSHA1 request "
            "signature (X-Bokun-Signature). NEVER log this value; it never "
            "appears in a request header or response body directly."
        ),
        repr=False,
    )
    bokun_booking_enabled: bool = Field(
        default=False,
        description=(
            "Gate the real supplier-booking path (reserve + confirm + cancel with "
            "Bokun) in the money gate. When False (default) a Bokun-sourced node "
            "books like any other source — a local booking record whose supplier "
            "confirmation # is recorded manually by an advisor. When True, booking "
            "an approved+paid Bokun node RESERVES then CONFIRMS the reservation "
            "upstream and stores the returned confirmation code automatically. "
            "Requires bokun_access_key / bokun_secret_key to be set."
        ),
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
    payment_quote_ttl_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description=(
            "Lifetime of a pay-time FX lock (payment_quotes, 0050). When a traveler "
            "opens the pay dialog we freeze the native→settlement rate for this long; "
            "an expired quote forces a re-quote at a fresher rate. Distinct from (and "
            "much shorter than) exchange_rate_cache_ttl_seconds, which is the longer "
            "read-side DISPLAY cache."
        ),
    )

    serp_api_key: str = Field(
        default="",
        description=(
            "SerpApi key for the Google Hotels engine. Used by "
            "scripts/scrape_serp_hotels.py to harvest a region's hotels into "
            "app/inventory/data/serp_hotels.json, which the 'serp' provider "
            "serves with local haversine geo-search. Not called at request "
            "time (the scrape is offline), so an empty value only disables the "
            "scraper, not the provider."
        ),
        repr=False,
    )

    inventory_providers_enabled: str = Field(
        default="ov,mock,serp",
        description=(
            "Comma-separated list of inventory provider sources to register at "
            "startup. Known values: 'ov', 'mock', 'serp' (scraped hotels), "
            "'duffel' (flights), 'duffel_stays' (hotels), 'ratehawk' (hotels), "
            "'google_places', 'bokun'. Unknown names are skipped with a "
            "warning so a typo doesn't crash the boot."
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
    s3_endpoint_url: str = Field(
        default="",
        description=(
            "Override the S3 endpoint for vault presigning. Empty = real AWS S3 "
            "(staging/prod, ambient credential chain). Set to an S3-compatible "
            "endpoint to back the vault locally without AWS — e.g. local "
            "Supabase Storage at http://127.0.0.1:54321/storage/v1/s3. When set, "
            "the presigner uses path-style addressing + the s3_* credentials "
            "below instead of the AWS chain."
        ),
    )
    s3_region: str = Field(
        default="",
        description=(
            "Signing region for s3_endpoint_url (SigV4 scope). Empty falls back "
            "to aws_region. Supabase Storage validates this — use 'local' "
            "(S3_PROTOCOL_REGION from `supabase status`)."
        ),
    )
    s3_access_key_id: str = Field(
        default="",
        description=(
            "Access key id for s3_endpoint_url. Only used when s3_endpoint_url "
            "is set; real AWS uses the ambient credential chain instead. "
            "Locally this is S3_PROTOCOL_ACCESS_KEY_ID from `supabase status`."
        ),
    )
    s3_secret_access_key: str = Field(
        default="",
        repr=False,
        description=(
            "Secret key for s3_endpoint_url (paired with s3_access_key_id). "
            "Locally this is S3_PROTOCOL_ACCESS_KEY_SECRET from `supabase "
            "status`. repr=False so it never lands in a log or traceback."
        ),
    )
    agent_first_token_timeout_seconds: float = Field(
        default=15.0,
        ge=0.1,
        description=(
            "Hard ceiling on a silent upstream gap before the first text "
            "token: any runtime event (tool activity, cards) re-arms the "
            "window, so tool-first turns aren't cut while visibly working. "
            "On expiry we cut the stream and fall into the retry envelope. "
            "Sized for this concierge's cold-start reasoning (observed "
            "first tokens land at 7-10 s, and reasoning frames don't reach "
            "the wire), NOT the 2 s R015 aspiration — this is a liveness "
            "belt for a dead runtime, not an SLO. While a tool is actively "
            "in flight the wider agent_tool_liveness_timeout_seconds applies "
            "instead."
        ),
    )
    agent_tool_liveness_timeout_seconds: float = Field(
        default=20.0,
        ge=0.1,
        description=(
            "Silent-gap ceiling that replaces the first-token deadline once "
            "an activity 'call' frame proves a tool is executing (until its "
            "matching 'result'). A tool-first turn is provably alive while a "
            "tool runs, and a single tool call is bounded by the agent's own "
            "per-call HTTP timeout (backend_timeout_seconds, default 15 s), "
            "so this must sit comfortably above it — else an 8-15 s tool call "
            "(flight search, hydrate) trips the cut and drops the turn to the "
            "fallback with no retry."
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
    feed_poll_seconds: float = Field(
        default=4.0,
        ge=0.5,
        description=(
            "Tick interval for the advisor SSE feed (/advisor/feed) — each "
            "connected advisor re-queries the watermarked activity sources "
            "this often. ~4s reads as live at single-advisor scale without "
            "meaningful DB load."
        ),
    )
    feed_heartbeat_seconds: float = Field(
        default=20.0,
        ge=5.0,
        description=(
            "Idle keepalive cadence for the advisor SSE feed. Must stay well "
            "under the ALB idle timeout (120s in ApiStack) — 20s gives 6x "
            "margin."
        ),
    )
    feed_max_stream_seconds: int = Field(
        default=900,
        ge=60,
        description=(
            "Hard lifetime cap on one advisor feed connection. The stream "
            "closes with a bye frame at min(JWT exp, this cap); the browser "
            "reconnects with a fresh token."
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
    export_day_notes_enabled: bool = Field(
        default=False,
        description=(
            "Gate the LLM lane of export day notes (the PDF's per-day 'what "
            "to bring / tips' section). When False (default) exports use the "
            "deterministic fallback rules only — local mock lanes, pytest, "
            "and CI stay AWS-free. When True, stale/missing days are filled "
            "by one bedrock-runtime converse call per export (cached in "
            "itinerary_day_notes; advisor-authored rows are never touched)."
        ),
    )
    export_day_notes_model_id: str = Field(
        default="us.anthropic.claude-haiku-4-5",
        description=(
            "Bedrock model id (cross-region inference profile) for export "
            "day-notes generation. A small/fast Claude — the call is one "
            "short JSON-only prompt per export."
        ),
    )
    places_photo_signing_secret: str = Field(
        default="",
        description=(
            "HS256 signing key for Places photo-proxy tokens. The proxy route "
            "GET /integrations/google-places/photo is whitelisted (an <img> "
            "tag cannot send a bearer header), so the signed token IS its "
            "auth — it binds one photo resource name and stops third parties "
            "from burning our Places quota. Falls back to "
            "``agent_token_signing_secret`` when empty so local dev works "
            "without extra provisioning; empty for both disables photo URLs "
            "(cards fall back to the tint stub). NEVER log this value."
        ),
        repr=False,
    )
    places_photo_token_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 365,
        ge=3600,
        description=(
            "Lifetime of a Places photo-proxy token. Minted at card-build "
            "time and persisted in node metadata, so it must outlive the "
            "inventory cache (30 days) and ordinary node longevity — a year "
            "by default. Re-builds re-mint, so expiry only bites a long-dormant "
            "itinerary (it then degrades to the tint stub, never an error)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
