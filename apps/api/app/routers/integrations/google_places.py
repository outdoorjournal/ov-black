"""Google Places integration — live (Places API New).

A thin enrichment surface over Google Places used by the Fill / Analyze
pipeline (distinct from inventory ``search_inventory``, which goes through
:class:`~app.inventory.providers.google_places.GooglePlacesProvider`). Both
share that provider's single HTTP layer — this router calls its public
``text_search`` / ``place_details`` and maps the raw place into the stable
``PlaceSummary`` / ``PlaceDetail`` response contract (unchanged from the
former stub, so the generated client surface is identical).

The provider degrades to ``[]`` when the API key is unset or Google fails, so
``/search`` returns an empty result list rather than 5xx — callers must handle
the empty case as if Google had no match. ``/details`` returns 404 when the
place is absent and 502 when Google itself is broken.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.config import get_settings
from app.inventory.providers.google_places import (
    GooglePlacesProvider,
    ProviderUpstreamError,
    display_name_of,
    formatted_address_of,
    lat_lng_of,
    opening_hours_of,
    phone_of,
    photos_of,
    place_id_of,
    rating_of,
    types_of,
    user_rating_count_of,
    website_of,
)
from app.services.places_photo_token import PhotoTokenError, verify_photo_token

router = APIRouter(prefix="/integrations/google-places", tags=["integrations"])


# ── Models (unchanged response contract) ───────────────────────────────


class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float
    lng: float


class PlacePhoto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_reference: str
    width: int
    height: int


class PlaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: str
    name: str
    location: GeoPoint
    types: list[str]
    rating: float | None = None


class PlaceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: str
    name: str
    location: GeoPoint
    formatted_address: str
    types: list[str]
    rating: float | None = None
    user_ratings_total: int | None = None
    opening_hours: list[str] = Field(default_factory=list)
    photos: list[PlacePhoto] = Field(default_factory=list)
    website: str | None = None
    phone: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    near: GeoPoint | None = None
    radius_m: int | None = Field(default=None, ge=1, le=50_000)


class SearchResponse(BaseModel):
    results: list[PlaceSummary]


# ── Dependency (override in tests) ─────────────────────────────────────


def get_google_places_provider() -> GooglePlacesProvider:
    """FastAPI dependency — a fresh provider per request.

    Tests override via ``app.dependency_overrides[get_google_places_provider]``
    to inject a ``MockTransport``-backed provider so the suite stays offline.
    """
    return GooglePlacesProvider(settings=get_settings())


# ── Raw place → response mapping ───────────────────────────────────────


def _photos(place: dict[str, Any]) -> list[PlacePhoto]:
    """Map raw Places photo objects → ``PlacePhoto`` (resource name as ref).

    A Places (New) photo ``name`` is a resource path, not a URL — resolving it
    to an image needs a keyed backend proxy (a documented follow-up). The
    reference is surfaced here so a later proxy can fetch it server-side.
    """
    out: list[PlacePhoto] = []
    for photo in photos_of(place):
        name = photo.get("name")
        if not isinstance(name, str) or not name:
            continue
        width = photo.get("widthPx")
        height = photo.get("heightPx")
        out.append(
            PlacePhoto(
                photo_reference=name,
                width=width if isinstance(width, int) and not isinstance(width, bool) else 0,
                height=height if isinstance(height, int) and not isinstance(height, bool) else 0,
            )
        )
    return out


def _to_summary(place: dict[str, Any]) -> PlaceSummary | None:
    """Map a raw place → ``PlaceSummary``; ``None`` if it lacks id/name/geo."""
    place_id = place_id_of(place)
    name = display_name_of(place)
    lat_lng = lat_lng_of(place)
    if not place_id or not name or lat_lng is None:
        return None
    return PlaceSummary(
        place_id=place_id,
        name=name,
        location=GeoPoint(lat=lat_lng[0], lng=lat_lng[1]),
        types=types_of(place),
        rating=rating_of(place),
    )


def _to_detail(place: dict[str, Any]) -> PlaceDetail:
    """Map a raw place → ``PlaceDetail``; raise 502 when it lacks id/name/geo."""
    place_id = place_id_of(place)
    name = display_name_of(place)
    lat_lng = lat_lng_of(place)
    if not place_id or not name or lat_lng is None:
        raise HTTPException(status_code=502, detail="place_detail_malformed")
    return PlaceDetail(
        place_id=place_id,
        name=name,
        location=GeoPoint(lat=lat_lng[0], lng=lat_lng[1]),
        formatted_address=formatted_address_of(place) or "",
        types=types_of(place),
        rating=rating_of(place),
        user_ratings_total=user_rating_count_of(place),
        opening_hours=opening_hours_of(place),
        photos=_photos(place),
        website=website_of(place),
        phone=phone_of(place),
    )


# ── Routes ────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse, summary="Search places (live).")
async def search(
    payload: SearchRequest,
    _user: AuthenticatedUser = Depends(require_user),
    provider: GooglePlacesProvider = Depends(get_google_places_provider),
) -> SearchResponse:
    """Text-search Google Places and return matching summaries.

    A blank query is a no-op (empty results), mirroring how Text Search
    treats a blank input — and how the provider degrades when unconfigured.
    """
    location_bias: dict[str, Any] | None = None
    if payload.near is not None:
        bias_filters: dict[str, Any] = {
            "near_lat": payload.near.lat,
            "near_lng": payload.near.lng,
        }
        if payload.radius_m is not None:
            bias_filters["radius_m"] = payload.radius_m
        location_bias = GooglePlacesProvider._location_bias(bias_filters)

    try:
        query = payload.query.strip()
        if not query:
            return SearchResponse(results=[])
        places = await provider.text_search(text_query=query, location_bias=location_bias)
    finally:
        await provider.aclose()

    summaries = [s for s in (_to_summary(p) for p in places) if s is not None]
    return SearchResponse(results=summaries)


@router.get(
    "/photo",
    summary="Resolve a signed Places photo ref → image (public, token-gated).",
    responses={302: {"description": "Redirect to a keyless image URL."}},
)
async def photo(
    token: str,
    provider: GooglePlacesProvider = Depends(get_google_places_provider),
) -> RedirectResponse:
    """Redirect to the image bytes for a signed photo reference.

    Whitelisted from the Supabase JWT middleware because an ``<img>`` tag can't
    send a bearer header — the HS256 ``token`` (minted at card-build time,
    binding one photo resource name) is the gate instead. We resolve the ref to
    a keyless googleusercontent URL **server-side** (so the API key never leaves
    the backend) and 302 there; the browser fetches the bytes straight from
    Google's CDN and caches them per ``Cache-Control``. Any failure — bad/expired
    token, unknown ref, upstream hiccup — collapses to 404 so the card falls
    back to its tint stub rather than showing a broken image with a reason.
    """
    try:
        ref = verify_photo_token(token)
    except PhotoTokenError as exc:
        await provider.aclose()
        raise HTTPException(status_code=404, detail="photo_not_found") from exc

    try:
        url = await provider.resolve_photo_url(ref)
    finally:
        await provider.aclose()

    if not url:
        raise HTTPException(status_code=404, detail="photo_not_found")
    return RedirectResponse(
        url,
        status_code=302,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/details/{place_id}",
    response_model=PlaceDetail,
    summary="Get place details (live).",
)
async def details(
    place_id: str,
    _user: AuthenticatedUser = Depends(require_user),
    provider: GooglePlacesProvider = Depends(get_google_places_provider),
) -> PlaceDetail:
    """Return the full record for ``place_id`` (404 absent, 502 upstream-broken)."""
    try:
        place = await provider.place_details(place_id)
    except ProviderUpstreamError as exc:
        raise HTTPException(status_code=502, detail="place_upstream_error") from exc
    finally:
        await provider.aclose()

    if place is None:
        raise HTTPException(status_code=404, detail="place_not_found")
    return _to_detail(place)
