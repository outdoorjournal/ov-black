"""Reading-catalog ORM row (owned-media editorial corpus).

Schema owned by ``supabase/migrations/0052_reading_catalog.sql``. Shared,
client-agnostic editorial inventory the basecamp agent searches to suggest
reading; a chosen row is saved into a traveler's Collection as an ``article``
node (0046). Read-only from the app — populated by seed / an ingestion job.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, FetchedValue, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ReadingArticle(Base):
    """One editorial article in the searchable reading catalog.

    ``search_tsv`` (weighted title/tags/excerpt, GIN-indexed) is a STORED
    generated column owned by Postgres — not mapped here; the search service
    queries it with ``websearch_to_tsquery`` + ``ts_rank``.
    """

    __tablename__ = "reading_catalog"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_property: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    og_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Postgres-owned generated column (weighted title/tags/excerpt). Read-only:
    # ``FetchedValue`` keeps the ORM from ever writing it, so it's available for
    # the FTS ``@@`` / ``ts_rank`` query without appearing in inserts.
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR, nullable=False, server_default=FetchedValue()
    )
