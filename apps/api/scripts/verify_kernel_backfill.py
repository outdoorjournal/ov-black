"""Run the 0055 dual-read verification against a live database.

Usage (local stack):
    cd apps/api && uv run python scripts/verify_kernel_backfill.py

Against another environment (e.g. staging via the pooler):
    DATABASE_URL=postgresql+asyncpg://… uv run python scripts/verify_kernel_backfill.py

Exits non-zero unless every scheduled node's canonical schedule columns resolve
to exactly the stored starts_at range. See doc/itin-time.md Phase 2.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # apps/api on path

from app.services.kernel_backfill_verify import verify_dual_read  # noqa: E402

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"


async def main() -> int:
    url = os.environ.get("DATABASE_URL", LOCAL_DB_URL)
    engine = create_async_engine(url, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as session:
            report = await verify_dual_read(session)
    finally:
        await engine.dispose()

    print(f"scheduled:   {report.scheduled}")
    print(f"verified:    {report.verified}")
    print(f"unconverted: {report.unconverted}")
    print(f"malformed:   {report.malformed}")
    print(f"mismatched:  {report.mismatched}")
    for sample in report.samples:
        print(f"  - {sample}")
    if report.clean:
        print("OK — dual read is exact; the kernel schedule columns are trustworthy.")
        return 0
    print("FAIL — do not switch reads/writes to the kernel columns yet.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
