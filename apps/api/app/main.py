import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from app.auth import PUBLIC_PATHS, AuthenticatedUser, JWTAuthMiddleware, require_user
from app.config import get_settings
from app.db import dispose_engine
from app.inventory.providers.mock import MockProvider
from app.inventory.providers.ov import OVProvider
from app.inventory.registry import get_registry
from app.routers.auth import router as auth_router
from app.routers.clients import router as clients_router
from app.routers.inventory import router as inventory_router
from app.routers.itineraries import router as itineraries_router

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
# (health probe, OpenAPI surfaces, and the invite-redeem entry point). R017.
# /auth/redeem-invite is intentionally public — it's the front door of the
# auth flow and has no token yet to validate.
app.add_middleware(
    JWTAuthMiddleware,
    public_paths=PUBLIC_PATHS | {"/auth/redeem-invite"},
)

app.include_router(auth_router)
app.include_router(itineraries_router)
app.include_router(inventory_router)
app.include_router(clients_router)


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
