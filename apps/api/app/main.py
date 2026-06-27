import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent.bedrock import (
    Boto3AgentRuntimeClient,
    LocalAgentRuntimeClient,
    MockAgentRuntimeClient,
)
from app.auth import PUBLIC_PATHS, AuthenticatedUser, JWTAuthMiddleware, require_user
from app.config import get_settings
from app.db import dispose_engine
from app.inventory.providers.duffel import DuffelProvider
from app.inventory.providers.google_places import GooglePlacesProvider
from app.inventory.providers.mock import MockProvider
from app.inventory.providers.ov import OVProvider
from app.inventory.providers.ratehawk import RatehawkProvider
from app.inventory.registry import get_registry
from app.payments import build_gateway
from app.routers.advisor_itineraries import router as advisor_itineraries_router
from app.routers.agent import router as agent_router
from app.routers.agent_internal import router as agent_internal_router
from app.routers.analyze import router as analyze_router
from app.routers.auth import router as auth_router
from app.routers.client_documents import router as client_documents_router
from app.routers.clients import router as clients_router
from app.routers.demos import router as demos_router
from app.routers.facts import router as facts_router
from app.routers.fill import router as fill_router
from app.routers.integrations.flight_status import router as flight_status_router
from app.routers.integrations.google_places import router as google_places_router
from app.routers.integrations.weather import router as weather_router
from app.routers.inventory import router as inventory_router
from app.routers.invoices import router as invoices_router
from app.routers.itineraries import router as itineraries_router
from app.routers.me import router as me_router
from app.routers.onboarding import router as onboarding_router
from app.routers.party_members import router as party_members_router
from app.vault.storage import MockVaultStorage, S3VaultStorage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger("ov_black.api")


class HealthResponse(BaseModel):
    status: str


class AuthedHealthResponse(BaseModel):
    status: str
    sub: str
    role: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> "AsyncIterator[None]":
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("api.startup", extra={"env": settings.env})

    registry = get_registry()
    enabled = [
        name.strip() for name in settings.inventory_providers_enabled.split(",") if name.strip()
    ]
    registered: list[str] = []
    for name in enabled:
        if name == "ov":
            registry.register(OVProvider(settings=settings))
            registered.append("ov")
        elif name == "mock":
            registry.register(MockProvider())
            registered.append("mock")
        elif name == "duffel":
            registry.register(DuffelProvider(settings=settings))
            registered.append("duffel")
        elif name == "ratehawk":
            registry.register(RatehawkProvider(settings=settings))
            registered.append("ratehawk")
        elif name == "google_places":
            registry.register(GooglePlacesProvider(settings=settings))
            registered.append("google_places")
        else:
            logger.warning(
                "inventory.providers.unknown",
                extra={"source": name},
            )
    logger.info(
        "inventory.providers.registered",
        extra={"sources": registered},
    )

    # ── Analyze reaper (Phase 5 / B5) ──────────────────────────────────────
    # A runner abandoned by a crash/restart leaves a 'running' analyses row no
    # live BackgroundTask will ever finish. Sweep them to 'failed' once at
    # boot, sequentially with the rest of startup so a DB failure here surfaces
    # as "refused to start" rather than silent half-running state.
    from app.db import get_sessionmaker
    from app.services.analyze import reap_orphaned_analyses

    async with get_sessionmaker()() as reaper_session:
        reaped = await reap_orphaned_analyses(
            reaper_session,
            max_running_seconds=settings.analyze_reaper_max_running_seconds,
        )
    if reaped:
        logger.info("analyze.reaper.reaped", extra={"count": reaped})

    # ── AgentCore runtime wiring (S04 T05) ─────────────────────────────────
    # Stash a single AgentRuntimeClient on app.state so request handlers can
    # resolve it through the get_agent_runtime dependency. In local dev with
    # an unset ARN we install a canned mock so `uv run pytest` and
    # `uvicorn --reload` work without AWS creds.
    if settings.agent_local_url:
        _app.state.agent_runtime = LocalAgentRuntimeClient(
            base_url=settings.agent_local_url,
        )
        logger.info(
            "agent.runtime.configured",
            extra={"arn_tail": None, "mode": "local_http"},
        )
    elif settings.env == "local" and not settings.bedrock_agentcore_runtime_arn:
        _app.state.agent_runtime = MockAgentRuntimeClient(
            events=[
                {"type": "delta", "text": "Hello, I'm your AgentCore scratchpad."},
                {"type": "done"},
            ]
        )
        logger.info(
            "agent.runtime.configured",
            extra={"arn_tail": None, "mode": "mock"},
        )
    else:
        _app.state.agent_runtime = Boto3AgentRuntimeClient(settings=settings)
        arn_tail = (
            settings.bedrock_agentcore_runtime_arn[-16:]
            if settings.bedrock_agentcore_runtime_arn
            else None
        )
        logger.info(
            "agent.runtime.configured",
            extra={"arn_tail": arn_tail, "mode": "boto3"},
        )

    # ── Vault storage wiring (M003/V3) ─────────────────────────────────────
    # Presigned S3 URLs for the document vault. Mirror the runtime mock: in
    # local dev with no bucket configured, install a deterministic mock so
    # pytest + uvicorn run without AWS. The bucket name (never a secret) is
    # injected by CDK as VAULT_BUCKET_NAME in staging/prod.
    if settings.env == "local" and not settings.vault_bucket_name:
        _app.state.vault_storage = MockVaultStorage()
        logger.info("vault.storage.configured", extra={"mode": "mock"})
    else:
        _app.state.vault_storage = S3VaultStorage(settings=settings)
        logger.info("vault.storage.configured", extra={"mode": "s3"})

    # ── Payments gateway wiring (M005/I2, D025) ────────────────────────────
    # Mirror the runtime/vault mocks: a real Braintree gateway when keys are
    # set, a deterministic Fake in non-prod when unconfigured (so pytest +
    # uvicorn run without Braintree), and None in production-without-keys so a
    # missing secret refuses rather than silently faking a charge.
    _app.state.payment_gateway = build_gateway(settings)
    logger.info(
        "payments.gateway.configured",
        extra={
            "mode": (
                _app.state.payment_gateway.name
                if _app.state.payment_gateway is not None
                else "unconfigured"
            )
        },
    )

    try:
        yield
    finally:
        await dispose_engine()
        logger.info("api.shutdown")


app = FastAPI(
    title="OV Black API",
    version="0.1.0",
    description="Backend API for OV Black — invite-gated advisor platform.",
    lifespan=lifespan,
)

# Enforce Supabase JWT validation on every route except the public whitelist
# (health probe, OpenAPI surfaces, and the two auth front doors). R017.
# Both /auth/redeem-invite and /auth/login are intentionally public — they
# issue tokens rather than consume them, so there is no JWT yet to validate.
app.add_middleware(
    JWTAuthMiddleware,
    public_paths=PUBLIC_PATHS
    | {
        "/auth/redeem-invite",
        "/auth/login",
        # Backend-only agent surfaces — they validate a per-session agent
        # token themselves; the Supabase JWT middleware would reject them
        # because the agent is not a Supabase user.
        "/agent/context",
        "/agent/profile/facts",
        "/agent/dossier/facts",
        "/agent/party-members",
    },
)

# Starlette stacks middleware LIFO — CORS is added *after* the JWT middleware
# so it wraps it as the outermost layer. That way preflight OPTIONS requests
# are answered by CORSMiddleware before JWTAuthMiddleware rejects them for
# having no Authorization header.
_settings = get_settings()
# In local dev the web app is reachable under both http://localhost:3000 and
# http://127.0.0.1:3000 (Supabase's site_url uses the loopback IP). We accept
# either variant of whatever web_origin is configured so the browser doesn't
# 400 on preflight when the host name differs from the bookmark.
_cors_origins = {_settings.web_origin}
if "://localhost:" in _settings.web_origin:
    _cors_origins.add(_settings.web_origin.replace("://localhost:", "://127.0.0.1:"))
elif "://127.0.0.1:" in _settings.web_origin:
    _cors_origins.add(_settings.web_origin.replace("://127.0.0.1:", "://localhost:"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(itineraries_router)
app.include_router(invoices_router)
app.include_router(advisor_itineraries_router)
app.include_router(analyze_router)
app.include_router(fill_router)
app.include_router(inventory_router)
app.include_router(clients_router)
app.include_router(client_documents_router)
app.include_router(facts_router)
app.include_router(agent_router)
app.include_router(agent_internal_router)
app.include_router(me_router)
app.include_router(party_members_router)
app.include_router(onboarding_router)
app.include_router(demos_router)
app.include_router(google_places_router)
app.include_router(weather_router)
app.include_router(flight_status_router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Public liveness probe used by the ALB target group (S01)."""
    return HealthResponse(status="ok")


@app.get(
    "/health/authed",
    response_model=AuthedHealthResponse,
    tags=["health"],
)
async def health_authed(
    user: AuthenticatedUser = Depends(require_user),
) -> AuthedHealthResponse:
    """Authenticated inspection surface — proves the JWT middleware is wired."""
    return AuthedHealthResponse(status="ok", sub=user.sub, role=user.role)
