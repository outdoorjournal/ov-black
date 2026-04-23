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
from app.inventory.providers.mock import MockProvider
from app.inventory.providers.ov import OVProvider
from app.inventory.registry import get_registry
from app.routers.agent import router as agent_router
from app.routers.auth import router as auth_router
from app.routers.clients import router as clients_router
from app.routers.inventory import router as inventory_router
from app.routers.itineraries import router as itineraries_router
from app.routers.me import router as me_router

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
        name.strip()
        for name in settings.inventory_providers_enabled.split(",")
        if name.strip()
    ]
    registered: list[str] = []
    for name in enabled:
        if name == "ov":
            registry.register(OVProvider(settings=settings))
            registered.append("ov")
        elif name == "mock":
            registry.register(MockProvider())
            registered.append("mock")
        else:
            logger.warning(
                "inventory.providers.unknown",
                extra={"source": name},
            )
    logger.info(
        "inventory.providers.registered",
        extra={"sources": registered},
    )

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
    public_paths=PUBLIC_PATHS | {"/auth/redeem-invite", "/auth/login"},
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
app.include_router(inventory_router)
app.include_router(clients_router)
app.include_router(agent_router)
app.include_router(me_router)


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
