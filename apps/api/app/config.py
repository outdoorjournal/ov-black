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

    inventory_providers_enabled: str = Field(
        default="ov,mock",
        description=(
            "Comma-separated list of inventory provider sources to register at "
            "startup. Known values: 'ov', 'mock'. Unknown names are skipped "
            "with a warning so a typo doesn't crash the whole boot."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
