import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.db import dispose_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger("ov_black.api")


class HealthResponse(BaseModel):
    status: str


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


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Public liveness probe used by the ALB target group (S01)."""
    return HealthResponse(status="ok")
