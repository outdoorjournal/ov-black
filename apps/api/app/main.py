import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from app.auth import AuthenticatedUser, JWTAuthMiddleware, require_user
from app.config import get_settings
from app.db import dispose_engine

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
# (health probe + OpenAPI surfaces). R017.
app.add_middleware(JWTAuthMiddleware)


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
