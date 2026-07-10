"""Place brief — the server-side spine of the chat place drawer.

The agent references places as loose human strings (``place:Hakone+Ropeway``);
client-side Mapbox geocoding proved too literal for those, so resolution moved
here: Google Places Text Search (already integrated for inventory) is far more
forgiving of colloquial names, and the same round-trip composes the rest of
the drawer — photos as signed proxy tokens, CIA World Factbook country
texture, and a Wikipedia summary.

One endpoint, browser-called with the user's JWT. Texture sources are
best-effort: a brief with ``factbook=null`` / ``wikipedia=null`` is normal
and the drawer renders what it gets. Only an unresolvable place is a 404.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.config import get_settings
from app.inventory.providers.google_places import (
    GooglePlacesProvider,
    display_name_of,
    editorial_summary_of,
    formatted_address_of,
    lat_lng_of,
    photo_refs_of,
    place_id_of,
    rating_of,
    types_of,
    user_rating_count_of,
    website_of,
)
from app.routers.integrations.google_places import get_google_places_provider
from app.services.place_texture import (
    FactbookTexture,
    WikipediaTexture,
    country_from_address,
    fetch_factbook_texture,
    fetch_wikipedia_texture,
)
from app.services.places_photo_token import mint_photo_token

router = APIRouter(prefix="/places", tags=["places"])

_MAX_PHOTOS = 3
_TEXTURE_TIMEOUT_SECONDS = 6.0


# ── Models ───────────────────────────────────────────────────────────────


class PlaceBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)


class ResolvedPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: str
    name: str
    formatted_address: str
    lat: float
    lng: float
    types: list[str] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    editorial_summary: str | None = None
    website: str | None = None
    maps_url: str
    # Signed handles for the keyed photo proxy — the client builds
    # ``{apiBase}/integrations/google-places/photo?token=…`` (same contract
    # as PlaceFacts.photo_token on experience cards).
    photo_tokens: list[str] = Field(default_factory=list)


class PlaceBrief(BaseModel):
    resolved: ResolvedPlace
    factbook: FactbookTexture | None = None
    wikipedia: WikipediaTexture | None = None


# ── Dependencies (override in tests) ────────────────────────────────────


def get_texture_client() -> httpx.AsyncClient:
    """A fresh client for the texture fetches (Factbook + Wikipedia).

    Tests override this with a ``MockTransport``-backed client so the suite
    stays offline. Closed by the endpoint after use.
    """
    return httpx.AsyncClient(timeout=_TEXTURE_TIMEOUT_SECONDS)


# ── Route ────────────────────────────────────────────────────────────────


def _maps_deep_link(name: str, place_id: str) -> str:
    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={quote_plus(name)}&query_place_id={quote_plus(place_id)}"
    )


def _resolve_place(place: dict[str, object]) -> ResolvedPlace | None:
    place_id = place_id_of(place)
    name = display_name_of(place)
    lat_lng = lat_lng_of(place)
    if not place_id or not name or lat_lng is None:
        return None
    tokens = [
        token
        for ref in photo_refs_of(place)[:_MAX_PHOTOS]
        if (token := mint_photo_token(ref)) is not None
    ]
    return ResolvedPlace(
        place_id=place_id,
        name=name,
        formatted_address=formatted_address_of(place) or "",
        lat=lat_lng[0],
        lng=lat_lng[1],
        types=types_of(place),
        rating=rating_of(place),
        rating_count=user_rating_count_of(place),
        editorial_summary=editorial_summary_of(place),
        website=website_of(place),
        maps_url=_maps_deep_link(name, place_id),
        photo_tokens=tokens,
    )


@router.post(
    "/brief",
    response_model=PlaceBrief,
    summary="Resolve a loose place string into a drawer-ready brief.",
    responses={404: {"description": "The query resolved to no usable place."}},
)
async def place_brief(
    payload: PlaceBriefRequest,
    _user: AuthenticatedUser = Depends(require_user),
    provider: GooglePlacesProvider = Depends(get_google_places_provider),
    texture_client: httpx.AsyncClient = Depends(get_texture_client),
) -> PlaceBrief:
    """Resolve ``query`` via Places Text Search and attach texture.

    Resolution is the only hard requirement; both texture fetches run
    concurrently and independently degrade to ``None``.
    """
    settings = get_settings()
    try:
        query = payload.query.strip()
        places = await provider.text_search(text_query=query, max_results=1) if query else []
        resolved = _resolve_place(places[0]) if places else None
        if resolved is None:
            raise HTTPException(status_code=404, detail="place_not_found")

        country = country_from_address(resolved.formatted_address)
        factbook_task = (
            fetch_factbook_texture(country, client=texture_client, settings=settings)
            if country
            else None
        )
        wikipedia_task = fetch_wikipedia_texture(
            resolved.name, client=texture_client, settings=settings
        )
        factbook: FactbookTexture | None = None
        wikipedia: WikipediaTexture | None
        if factbook_task is not None:
            factbook, wikipedia = await asyncio.gather(factbook_task, wikipedia_task)
        else:
            wikipedia = await wikipedia_task
    finally:
        await provider.aclose()
        await texture_client.aclose()

    return PlaceBrief(resolved=resolved, factbook=factbook, wikipedia=wikipedia)
