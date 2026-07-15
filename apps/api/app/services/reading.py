"""Full-text search over the reading catalog (0052).

The basecamp agent calls this (via ``GET /agent/reading/search``) to find
editorial articles from the concierge's owned properties that match a
traveler's destination + interests. Retrieval is Postgres FTS:
``websearch_to_tsquery`` parses the free-text query the way a search box would
(quoted phrases, ``or``, ``-term``), ranked by ``ts_rank`` over the weighted,
GIN-indexed ``search_tsv`` column. An empty/no-match query falls back to the
most recent articles so the agent always has something to offer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.registry import ArticleSeed
from app.models import Itinerary, Node, NodeStatus, NodeType
from app.models.reading import ReadingArticle
from app.services.itineraries import (
    ActorContext,
    ItineraryError,
    add_node,
    create_itinerary,
)

# Clamp so a chatty agent can't page the whole corpus in one call.
_MAX_LIMIT = 10


@dataclass(frozen=True, slots=True)
class ReadingHit:
    """One ranked article result, shaped for the suggestion flyout."""

    id: str
    title: str
    url: str
    source_property: str
    og_image: str | None
    excerpt: str | None
    reading_time_minutes: int | None


def _to_hit(row: ReadingArticle) -> ReadingHit:
    return ReadingHit(
        id=str(row.id),
        title=row.title,
        url=row.url,
        source_property=row.source_property,
        og_image=row.og_image,
        excerpt=row.excerpt,
        reading_time_minutes=row.reading_time_minutes,
    )


async def search_reading_catalog(
    session: AsyncSession, *, query: str, limit: int = 3
) -> list[ReadingHit]:
    """Rank catalog articles for ``query`` (best first); recent-first fallback.

    ``limit`` is clamped to ``[1, _MAX_LIMIT]``. A blank query — or one whose
    terms match nothing — returns the newest articles rather than an empty
    list, so the agent can still make an editorial suggestion.
    """
    n = max(1, min(limit, _MAX_LIMIT))
    q = (query or "").strip()

    if q:
        tsquery = func.websearch_to_tsquery("english", q)
        rank = func.ts_rank(ReadingArticle.search_tsv, tsquery)
        stmt = (
            select(ReadingArticle)
            .where(ReadingArticle.search_tsv.op("@@")(tsquery))
            .order_by(rank.desc(), ReadingArticle.published_at.desc().nullslast())
            .limit(n)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if rows:
            return [_to_hit(r) for r in rows]

    # Blank query or nothing matched — most recent, so there's always an offer.
    fallback = (
        select(ReadingArticle).order_by(ReadingArticle.published_at.desc().nullslast()).limit(n)
    )
    return [_to_hit(r) for r in (await session.execute(fallback)).scalars().all()]


async def _reading_target_itinerary(
    session: AsyncSession, actor: ActorContext, *, client_id: uuid.UUID
) -> Itinerary:
    """Where a browser-saved read lands: the client's most-recent owned trunk.

    The Reading destination (web) aggregates ``article`` nodes across the
    traveler's OFFICIAL itineraries (``listMyItineraries`` reads trunks), so a
    saved read must land on a trunk to surface there — which the trunk fork-gate
    now admits for non-schedulable articles. We reuse the client's newest owned
    trunk (repeat saves converge on it) and only spin up a draft when they have
    no trip yet — mirroring the agent's ``save_link_to_collection`` semantics
    rather than inventing a separate container that would read as a stray trip.
    """
    existing = (
        (
            await session.execute(
                select(Itinerary)
                .where(
                    Itinerary.client_id == client_id,
                    Itinerary.forked_from_id.is_(None),
                )
                .order_by(Itinerary.updated_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    # No trip yet — a solo traveler's draft is their working itinerary.
    return await create_itinerary(session, actor, title="", client_id=client_id)


def _article_metadata(
    *,
    title: str,
    url: str,
    publication: str | None,
    og_image: str | None,
    excerpt: str | None,
) -> dict[str, Any]:
    """The ``article`` node metadata shape shared by every save path.

    Mirrors the pasted-link/from-catalog card (``snapshot`` + ``url`` +
    ``publication``) so both the Collection card (``ArticleBody``) and the
    Reading destination (``toReadingItem``) — and the concierge's article
    flyout — render it identically.
    """
    snapshot: dict[str, Any] = {"title": title, "url": url}
    if og_image:
        snapshot["cover_image"] = og_image
    if excerpt:
        snapshot["description"] = excerpt
    metadata: dict[str, Any] = {"snapshot": snapshot, "url": url}
    if publication:
        metadata["publication"] = publication
    return metadata


async def seed_campaign_reading_list(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    seeds: Sequence[ArticleSeed],
) -> list[Node]:
    """Drop a campaign's curated reads onto ``itinerary_id`` as article nodes.

    Called from the dashboard kickoff, in the same fresh-itinerary breath as the
    spine (see :func:`campaign_kickoff_endpoint`), so the traveler's reading list
    is stocked deterministically rather than gated on the model choosing to call
    ``suggest_reading``. Each seed becomes an unscheduled ``article`` node
    carrying the curated metadata verbatim (no OG re-fetch of the auth-walled
    source). Returns the created nodes so the caller can stream them onto the
    canvas and reference them as chips. A seed that fails to persist is skipped
    rather than sinking the whole kickoff.
    """
    created: list[Node] = []
    for seed in seeds:
        result = await add_node(
            session,
            actor,
            itinerary_id=itinerary_id,
            type=NodeType.article,
            status=NodeStatus.pending,
            title=seed.title,
            source="reading_catalog",
            source_id=seed.url,
            metadata=_article_metadata(
                title=seed.title,
                url=seed.url,
                publication=seed.publication,
                og_image=seed.og_image,
                excerpt=seed.excerpt,
            ),
        )
        if isinstance(result, Node):
            created.append(result)
    return created


async def add_article_to_reading_list(
    session: AsyncSession,
    actor: ActorContext,
    *,
    client_id: uuid.UUID,
    title: str,
    url: str,
    publication: str | None = None,
    og_image: str | None = None,
    excerpt: str | None = None,
) -> Node | ItineraryError:
    """Save a suggested article into the traveler's reading list.

    Persists an unscheduled ``article`` node carrying the metadata we already
    hold from the catalog — no re-fetch of the (auth-walled) source page. The
    metadata shape mirrors the pasted-link path (``snapshot`` + ``url`` +
    ``publication``) so both the Collection card (``ArticleBody``) and the
    Reading destination (``toReadingItem``) render it. Lands on the client's
    trunk so the cross-trip Reading rack picks it up.
    """
    itinerary = await _reading_target_itinerary(session, actor, client_id=client_id)

    return await add_node(
        session,
        actor,
        itinerary_id=itinerary.id,
        type=NodeType.article,
        status=NodeStatus.pending,
        title=title,
        source="reading_catalog",
        source_id=url,
        metadata=_article_metadata(
            title=title,
            url=url,
            publication=publication,
            og_image=og_image,
            excerpt=excerpt,
        ),
    )
