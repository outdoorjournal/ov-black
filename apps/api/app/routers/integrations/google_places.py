"""Google Places integration — STUB.

Returns canned responses with the shape a real Google Places integration
would produce. The agent / Fill / Analyze pipeline can call these
endpoints today; swapping the stub for the live API is a future slice.

Lookups currently match by ``query`` substring against a small in-memory
catalogue keyed off a few real Tokyo / Kyoto places used in the seed
Japan template. Anything else returns an empty result list — callers
must handle the empty case as if Google had no match. That mirrors how
the live API would behave once we wire it in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user

router = APIRouter(prefix="/integrations/google-places", tags=["integrations"])


# ── Models ─────────────────────────────────────────────────────────────


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


# ── Stub catalogue ─────────────────────────────────────────────────────
# Curated to match the real places in the Japan seed template so demo
# enrichment calls return plausible data. Add entries when a new template
# needs Places-style enrichment.

_CATALOGUE: list[PlaceDetail] = [
    PlaceDetail(
        place_id="stub-aman-tokyo",
        name="Aman Tokyo",
        location=GeoPoint(lat=35.6889, lng=139.7672),
        formatted_address="Otemachi Tower, 1-5-6 Otemachi, Chiyoda City, Tokyo",
        types=["lodging", "spa"],
        rating=4.8,
        user_ratings_total=1342,
        opening_hours=["Open 24 hours"],
        photos=[
            PlacePhoto(
                photo_reference="stub-aman-tokyo-photo-1",
                width=1920,
                height=1080,
            )
        ],
        website="https://www.aman.com/hotels/aman-tokyo",
        phone="+81 3-5224-3333",
    ),
    PlaceDetail(
        place_id="stub-sushi-saito",
        name="Sushi Saito",
        location=GeoPoint(lat=35.6647, lng=139.7339),
        formatted_address="1-4-5 Roppongi, Minato City, Tokyo",
        types=["restaurant", "food"],
        rating=4.7,
        user_ratings_total=421,
        opening_hours=[
            "Mon-Sat 12:00-13:30, 18:00-22:00",
            "Sun closed",
        ],
    ),
    PlaceDetail(
        place_id="stub-fushimi-inari",
        name="Fushimi Inari Taisha",
        location=GeoPoint(lat=34.9671, lng=135.7727),
        formatted_address="68 Fukakusa Yabunouchicho, Fushimi Ward, Kyoto",
        types=["tourist_attraction", "place_of_worship"],
        rating=4.7,
        user_ratings_total=92_134,
        opening_hours=["Open 24 hours"],
        photos=[
            PlacePhoto(
                photo_reference="stub-fushimi-photo-1",
                width=1920,
                height=1280,
            )
        ],
    ),
]


def _to_summary(detail: PlaceDetail) -> PlaceSummary:
    return PlaceSummary(
        place_id=detail.place_id,
        name=detail.name,
        location=detail.location,
        types=detail.types,
        rating=detail.rating,
    )


# ── Routes ────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse, summary="Search places (stub).")
async def search(
    payload: SearchRequest,
    _user: AuthenticatedUser = Depends(require_user),
) -> SearchResponse:
    """Return canned matches whose ``name`` contains the query string.

    Live Google Places replaces this with a Text Search request; the
    response shape we return matches the subset our cards consume.
    """
    needle = payload.query.casefold().strip()
    if not needle:
        return SearchResponse(results=[])
    matches = [d for d in _CATALOGUE if needle in d.name.casefold()]
    return SearchResponse(results=[_to_summary(d) for d in matches])


@router.get(
    "/details/{place_id}",
    response_model=PlaceDetail,
    summary="Get place details (stub).",
)
async def details(
    place_id: str,
    _user: AuthenticatedUser = Depends(require_user),
) -> PlaceDetail:
    """Return the full canned record for ``place_id`` or 404."""
    # uuid validation on stub ids is intentionally lax — Google's place_ids
    # are opaque strings, not UUIDs. Reject obviously-wrong shapes only if
    # we want to mimic Places' "INVALID_REQUEST" — for now any mismatch is
    # 404.
    _ = uuid.UUID  # noqa: imported for parity with other routers
    for entry in _CATALOGUE:
        if entry.place_id == place_id:
            return entry
    raise HTTPException(status_code=404, detail="place_not_found")
