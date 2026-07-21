"""Transaction-scoped Postgres advisory locks for read-then-insert idempotence.

Several services follow a "reuse the existing row for this logical scope, else
insert one" shape (a user's open fork of a baseline, the live chat session for
a scope). Two concurrent callers can both miss the reuse SELECT and each mint
a row — React strict-mode double-effects and replayed dev renders do exactly
this in practice. Serializing the scope with an advisory lock closes the race:
the loser blocks until the winner's transaction commits, then its reuse SELECT
reads a fresh snapshot (READ COMMITTED takes one per statement) and sees the
winner's row.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def advisory_xact_lock(session: AsyncSession, key: str) -> None:
    """Take a transaction-scoped advisory lock on ``key`` (Postgres only).

    Released automatically when the session's current transaction commits or
    rolls back — there is nothing to unlock. ``key`` is hashed server-side
    (``hashtextextended``) into the bigint lock space.

    No-op off Postgres: offline unit tests drive services with duck-typed fake
    sessions that carry no bind at all, and those must keep running without a
    database.
    """
    get_bind = getattr(session, "get_bind", None)
    if get_bind is None:  # duck-typed fake session in offline unit tests
        return
    if get_bind().dialect.name != "postgresql":
        return
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": key},
    )
