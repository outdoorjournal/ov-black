"""Google Places ``InventoryProvider`` adapter (Places API **New**).

Adapts Google's Places API (New) Text Search + Place Details to the shared
``InventoryProvider`` seam so ``search_inventory(kinds=['meal','experience'])``
returns normalized :class:`MealItem` / :class:`ExperienceItem` records
alongside OV experiences, Duffel flights and Ratehawk hotels.

Search flow (one POST):

- ``POST /v1/places:searchText`` with ``{textQuery, includedType?,
  maxResultCount, locationBias?}`` → ``{places: [...]}``.

Detail flow:

- ``GET /v1/places/{place_id}`` → a single place object (same shape as one
  element of ``places[]``).

Each Google place maps to one inventory item whose ``kind`` is classified
from the place's types (a dining type → :class:`MealItem`, otherwise
:class:`ExperienceItem`). The full place object rides in ``raw`` so a later
card-mapping slice can read opening hours / website / phone / photo refs
without re-hitting Google.

Design notes (mirror :mod:`app.inventory.providers.ov` / ``.duffel`` /
``.ratehawk``):

- One ``httpx.AsyncClient`` per provider instance; tests swap it for one
  backed by ``httpx.MockTransport`` so the suite stays offline.
- The pure wire-shape accessors (``display_name_of`` … ``photos_of``) and
  ``normalize_place`` / ``summarize_place`` are exported so the integration
  router (``routers/integrations/google_places.py``) reads the *same* field
  shape rather than re-deriving it. Text Search field-masks fields under a
  ``places.`` prefix; Place Details returns them unprefixed — both yield the
  identical per-place object the accessors read.
- The Places API (New) is authenticated with the API key in the
  ``X-Goog-Api-Key`` header; the response is shaped by an ``X-Goog-FieldMask``
  header. The key is NEVER logged (``repr=False`` on the settings field) and
  must never leak into a client-facing URL.
- **Price honesty.** Places quotes only a coarse ``priceLevel`` enum, never a
  bookable amount, so items carry no numeric ``price`` (the level rides in
  ``tags`` as a ``$``-symbol). Meals/experiences are not first-class bookable
  cost (B4) — that's flights/hotels.
- **Photo honesty.** A Places (New) photo is a resource *name*
  (``places/…/photos/…``), not a URL; turning it into an image needs a keyed
  ``…/media`` fetch. To keep the API key server-side we leave ``photos`` empty
  here and preserve the photo refs in ``raw`` — a keyed backend photo-proxy is
  the documented follow-up (see doc/mvp-plan.md §8/B1).
- Text Search **requires** a ``textQuery``: a keyword-less call returns ``[]`` +
  a warning (a mood-board "browse" with no query legitimately has no Places
  hits). ``search()`` degrades to ``[]`` + a warning on any upstream failure;
  ``get_detail()`` returns ``None`` on 404 and raises
  :class:`ProviderUpstreamError` on anything else. With no key configured the
  provider stays registered but every ``search`` returns ``[]``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import (
    ExperienceItem,
    InventoryItem,
    Location,
    MealItem,
)

logger = logging.getLogger("ov_black.inventory.google_places")


class ProviderUpstreamError(Exception):
    """Raised by ``get_detail`` when Places fails for a non-"not found" reason.

    The router layer maps this to HTTP 502 so the caller sees an unambiguous
    "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# Text Search can be slower than a simple GET — give it the same headroom as
# the other live providers rather than OV's 5s default.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)

# Default circle radius (metres) when a caller supplies a centre but no radius.
_DEFAULT_RADIUS_M = 5000.0
# Places Text Search returns at most 20 results per page.
_MAX_RESULTS = 20

# Field mask shared by search + detail. Text Search wants the ``places.``
# prefix on each path; Place Details wants them bare. We build both from this
# single list so the two never drift.
_FIELDS = (
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "types",
    "primaryType",
    "rating",
    "userRatingCount",
    "priceLevel",
    "editorialSummary",
    "websiteUri",
    "internationalPhoneNumber",
    "regularOpeningHours",
    "photos",
)
_SEARCH_FIELD_MASK = ",".join(f"places.{f}" for f in _FIELDS)
_DETAIL_FIELD_MASK = ",".join(_FIELDS)

# Resolved photo CDN URLs are stable for a while; cache them in-process so a
# cold-browser reload of a card doesn't re-bill Google's Photo SKU. Keyed by
# photo resource name → (keyless CDN url, monotonic expiry).
# TODO(prod): in-process = per-task, lost on restart. In production this belongs
# in a shared store (Postgres/Redis) alongside the inventory cache so every task
# and every deploy reuses a resolved URL rather than re-billing the Photo SKU.
# (Low urgency: the browser's Cache-Control does most of the repeat-view work.)
_PHOTO_URL_TTL_SECONDS = 3600.0
_photo_url_cache: dict[str, tuple[str, float]] = {}


def _photo_url_cache_get(ref: str) -> str | None:
    entry = _photo_url_cache.get(ref)
    if entry is None:
        return None
    url, expires_at = entry
    if time.monotonic() >= expires_at:
        _photo_url_cache.pop(ref, None)
        return None
    return url


def _photo_url_cache_put(ref: str, url: str) -> None:
    _photo_url_cache[ref] = (url, time.monotonic() + _PHOTO_URL_TTL_SECONDS)


def reset_photo_url_cache() -> None:
    """Test helper — drop the module-level resolved-photo-URL cache."""
    _photo_url_cache.clear()


# Coarse Places price-level enum → a $-symbol tag.
_PRICE_SYMBOLS = {
    "PRICE_LEVEL_FREE": "free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}

# Places types that mean "somewhere you eat/drink" → MealItem. Anything else
# (attraction, museum, park, spa, …) classifies as an experience. We match on
# membership OR the ``*_restaurant`` suffix so Google's long-tail of cuisine
# types (sushi_restaurant, ramen_restaurant, …) all land as meals.
_DINING_TYPES = frozenset(
    {
        "restaurant",
        "food",
        "cafe",
        "coffee_shop",
        "bar",
        "bakery",
        "meal_takeaway",
        "meal_delivery",
        "fast_food_restaurant",
        "fine_dining_restaurant",
        "ice_cream_shop",
        "sandwich_shop",
        "pub",
        "wine_bar",
    }
)

# kind → Google ``includedType`` to narrow Text Search when the caller asks for
# exactly one kind. Omitted for a mixed/empty ``kinds`` (results are classified
# from their types instead).
_KIND_TO_INCLUDED_TYPE = {
    "meal": "restaurant",
    "experience": "tourist_attraction",
}


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce ``value`` to a dict, or ``{}`` — keeps extraction defensive."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _localized_text(node: Any) -> str | None:
    """Read a Places ``{text, languageCode}`` localized-text node → ``text``."""
    text = _as_dict(node).get("text")
    return text if isinstance(text, str) and text else None


# ── Pure wire-shape accessors (shared with the integration router) ──────────


def place_id_of(place: dict[str, Any]) -> str | None:
    pid = place.get("id")
    return pid if isinstance(pid, str) and pid else None


def display_name_of(place: dict[str, Any]) -> str | None:
    return _localized_text(place.get("displayName"))


def formatted_address_of(place: dict[str, Any]) -> str | None:
    addr = place.get("formattedAddress")
    return addr if isinstance(addr, str) and addr else None


def lat_lng_of(place: dict[str, Any]) -> tuple[float, float] | None:
    loc = _as_dict(place.get("location"))
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    if (
        isinstance(lat, (int, float))
        and not isinstance(lat, bool)
        and isinstance(lng, (int, float))
        and not isinstance(lng, bool)
    ):
        return (float(lat), float(lng))
    return None


def types_of(place: dict[str, Any]) -> list[str]:
    return [t for t in _as_list(place.get("types")) if isinstance(t, str) and t]


def primary_type_of(place: dict[str, Any]) -> str | None:
    pt = place.get("primaryType")
    if isinstance(pt, str) and pt:
        return pt
    types = types_of(place)
    return types[0] if types else None


def rating_of(place: dict[str, Any]) -> float | None:
    rating = place.get("rating")
    if isinstance(rating, (int, float)) and not isinstance(rating, bool):
        return float(rating)
    return None


def user_rating_count_of(place: dict[str, Any]) -> int | None:
    count = place.get("userRatingCount")
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    return None


def price_level_of(place: dict[str, Any]) -> str | None:
    level = place.get("priceLevel")
    return level if isinstance(level, str) and level else None


def editorial_summary_of(place: dict[str, Any]) -> str | None:
    return _localized_text(place.get("editorialSummary"))


def website_of(place: dict[str, Any]) -> str | None:
    uri = place.get("websiteUri")
    return uri if isinstance(uri, str) and uri else None


def phone_of(place: dict[str, Any]) -> str | None:
    phone = place.get("internationalPhoneNumber")
    return phone if isinstance(phone, str) and phone else None


def opening_hours_of(place: dict[str, Any]) -> list[str]:
    descriptions = _as_dict(place.get("regularOpeningHours")).get("weekdayDescriptions")
    return [d for d in _as_list(descriptions) if isinstance(d, str) and d]


def photos_of(place: dict[str, Any]) -> list[dict[str, Any]]:
    """Raw Places photo objects (``{name, widthPx, heightPx, …}``).

    Returned for the integration router's ``PlacePhoto`` mapping. The
    inventory normalizer deliberately does NOT turn these into image URLs —
    see the module docstring's photo-honesty note.
    """
    return [p for p in _as_list(place.get("photos")) if isinstance(p, dict)]


def photo_refs_of(place: dict[str, Any]) -> list[str]:
    """The photo resource *names* (``places/…/photos/…``), hero first.

    These are opaque handles — the keyed ``/media`` proxy turns one into an
    image. We surface them onto the inventory item so the card-mapping layer
    can mint a signed proxy token without re-walking ``raw``.
    """
    out: list[str] = []
    for photo in photos_of(place):
        name = photo.get("name")
        if isinstance(name, str) and name:
            out.append(name)
    return out


def _humanize_type(value: str | None) -> str | None:
    """``sushi_restaurant`` → ``sushi restaurant``; ``None`` passes through."""
    if not value:
        return None
    return value.replace("_", " ").strip() or None


def classify_kind(place: dict[str, Any]) -> str:
    """Classify a place as ``meal`` or ``experience`` from its types.

    Any dining type (membership in ``_DINING_TYPES`` or a ``*_restaurant``
    suffix, checked against ``primaryType`` first then every ``types`` entry)
    yields ``meal``; everything else is an ``experience``.
    """
    candidates = [primary_type_of(place), *types_of(place)]
    for t in candidates:
        if t and (t in _DINING_TYPES or t.endswith("_restaurant")):
            return "meal"
    return "experience"


def summarize_place(place: dict[str, Any]) -> dict[str, Any]:
    """Pull the headline facts out of a raw Google place.

    A stable, provider-agnostic summary used here to build the card title /
    tags and exported so a later node-mapping slice can populate a meal /
    experience card (name, address, geo, primary type, rating, price level)
    without re-walking Google's nested shape. Every field is best-effort.
    """
    lat_lng = lat_lng_of(place)
    return {
        "place_id": place_id_of(place),
        "name": display_name_of(place),
        "address": formatted_address_of(place),
        "latitude": lat_lng[0] if lat_lng else None,
        "longitude": lat_lng[1] if lat_lng else None,
        "primary_type": primary_type_of(place),
        "kind": classify_kind(place),
        "rating": rating_of(place),
        "user_rating_count": user_rating_count_of(place),
        "price_level": price_level_of(place),
        "price_symbol": _PRICE_SYMBOLS.get(price_level_of(place) or ""),
        "website": website_of(place),
        "phone": phone_of(place),
    }


def _build_location(place: dict[str, Any]) -> Location | None:
    lat_lng = lat_lng_of(place)
    # Anchor the card on the place's formatted address (its geographic
    # context), falling back to the display name.
    label = formatted_address_of(place) or display_name_of(place)
    if lat_lng is None and label is None:
        return None
    return Location(
        lat=lat_lng[0] if lat_lng else None,
        lng=lat_lng[1] if lat_lng else None,
        label=label,
    )


def _build_tags(summary: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    primary = _humanize_type(summary.get("primary_type"))
    if primary:
        tags.append(primary)
    symbol = summary.get("price_symbol")
    if symbol:
        tags.append(str(symbol))
    return tags


def normalize_place(place: dict[str, Any]) -> InventoryItem:
    """Map one Google place to a :class:`MealItem` or :class:`ExperienceItem`.

    Pure function over the wire shape. Raises ``ValueError`` on a place with
    no id or no display name; callers (``GooglePlacesProvider.search``) catch
    that and skip the offending place. The full place rides in ``raw`` for
    later card mapping (opening hours / website / phone / photo refs).
    """
    source_id = place_id_of(place)
    if not source_id:
        raise ValueError("google place missing id")
    title = display_name_of(place)
    if not title:
        raise ValueError("google place missing displayName")

    summary = summarize_place(place)
    description = editorial_summary_of(place) or formatted_address_of(place)
    location = _build_location(place)
    tags = _build_tags(summary)

    common = {
        "source": "google_places",
        "source_id": source_id,
        "title": title,
        "description": description,
        "photos": [],  # see photo-honesty note in the module docstring
        "location": location,
        "price": None,  # Places gives only a coarse priceLevel, never an amount
        "editorial_links": [],
        "tags": tags,
        # POI enrichment — extracted here so callers never re-walk ``raw``.
        # ``photo_refs`` stay opaque handles (resolved via the keyed proxy);
        # ``photos`` stays empty per the photo-honesty note above.
        "rating": rating_of(place),
        "rating_count": user_rating_count_of(place),
        "opening_hours": opening_hours_of(place),
        "website": website_of(place),
        "phone": phone_of(place),
        "photo_refs": photo_refs_of(place),
        "raw": place,
    }
    if classify_kind(place) == "meal":
        return MealItem(**common)
    return ExperienceItem(**common)


class GooglePlacesProvider(InventoryProvider):
    """Adapter for the Google Places API (New)."""

    source = "google_places"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.google_places_base_url.rstrip("/")
        self._api_key = self._settings.google_places_api_key or None
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _has_credentials(self) -> bool:
        return bool(self._api_key)

    def _headers(self, field_mask: str) -> dict[str, str]:
        # X-Goog-Api-Key carries the secret; never log this dict.
        return {
            "X-Goog-Api-Key": self._api_key or "",
            "X-Goog-FieldMask": field_mask,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _media_headers(self) -> dict[str, str]:
        # The Place Photo /media endpoint takes no field mask — only the key.
        # Never log this dict.
        return {"X-Goog-Api-Key": self._api_key or "", "Accept": "application/json"}

    @staticmethod
    def _location_bias(filters: dict[str, Any]) -> dict[str, Any] | None:
        """Build a ``locationBias`` circle from ``near_lat`` + ``near_lng``.

        Optional ``radius_m`` (metres) narrows it; absent ⇒ a default radius.
        Missing either coordinate ⇒ no bias (Google ranks by relevance).
        """
        lat = filters.get("near_lat")
        lng = filters.get("near_lng")
        if not (
            isinstance(lat, (int, float))
            and not isinstance(lat, bool)
            and isinstance(lng, (int, float))
            and not isinstance(lng, bool)
        ):
            return None
        radius = filters.get("radius_m")
        radius_m = (
            float(radius)
            if isinstance(radius, (int, float)) and not isinstance(radius, bool) and radius > 0
            else _DEFAULT_RADIUS_M
        )
        return {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": radius_m,
            }
        }

    @staticmethod
    def _included_type(kinds: list[str] | None) -> str | None:
        """Narrow Text Search to one ``includedType`` when ``kinds`` is a single
        mappable kind; otherwise return ``None`` (classify results instead)."""
        if not kinds or len(kinds) != 1:
            return None
        return _KIND_TO_INCLUDED_TYPE.get(kinds[0])

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return classified :class:`MealItem` / :class:`ExperienceItem` records.

        ``keyword`` drives the Text Search ``textQuery`` (required — no query ⇒
        ``[]`` + a warning). ``kinds`` both narrows the upstream search (when a
        single mappable kind) and filters the classified results. ``[]`` on any
        upstream failure so a flightless/hotelless aggregate page doesn't 500.
        """
        if not self._has_credentials:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": "no_credentials",
                },
            )
            return []

        filters = filters if isinstance(filters, dict) else {}
        text_query = keyword.strip() if isinstance(keyword, str) else ""
        if not text_query:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": "missing_search_params",
                },
            )
            return []

        limit = filters.get("limit")
        max_results = min(limit, _MAX_RESULTS) if isinstance(limit, int) and limit > 0 else 10

        places = await self.text_search(
            text_query=text_query,
            included_type=self._included_type(kinds),
            location_bias=self._location_bias(filters),
            max_results=max_results,
        )

        wanted = set(kinds) if kinds else None
        results: list[InventoryItem] = []
        for place in places:
            try:
                item = normalize_place(place)
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "google_places",
                        "source_id": place_id_of(place),
                        "reason": exc.__class__.__name__,
                    },
                )
                continue
            # When the caller asked for specific kinds, drop classified items
            # that don't match (Text Search's includedType is a hint, not a
            # hard filter, and a mixed kinds list never set one).
            if wanted is not None and item.kind not in wanted:
                continue
            results.append(item)

        logger.info(
            "inventory.provider.search",
            extra={"source": "google_places", "keyword": keyword, "result_count": len(results)},
        )
        return results

    async def text_search(
        self,
        *,
        text_query: str,
        included_type: str | None = None,
        location_bias: dict[str, Any] | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """POST a Text Search; return the raw ``places`` list, ``[]`` on failure.

        Public so the integration router shares this single HTTP layer rather
        than re-implementing the call. Degrades (logs + ``[]``) on every
        upstream failure mode — never raises.
        """
        if not self._has_credentials:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": "no_credentials",
                },
            )
            return []

        body: dict[str, Any] = {
            "textQuery": text_query,
            "maxResultCount": max(1, min(max_results, _MAX_RESULTS)),
        }
        if included_type:
            body["includedType"] = included_type
        if location_bias:
            body["locationBias"] = location_bias

        url = f"{self._base_url}/v1/places:searchText"
        try:
            resp = await self._client.post(
                url, json=body, headers=self._headers(_SEARCH_FIELD_MASK)
            )
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "google_places", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            return []

        try:
            payload = resp.json()
        except ValueError:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return []

        places = _as_dict(payload).get("places")
        return [p for p in _as_list(places) if isinstance(p, dict)]

    async def place_details(self, place_id: str) -> dict[str, Any] | None:
        """GET one place's detail; raw dict, ``None`` on 404, raise otherwise.

        Public so the integration router shares this single HTTP layer. Unlike
        ``text_search`` this raises :class:`ProviderUpstreamError` on non-404
        failures so the router can tell "not found" from "upstream broken".
        """
        if not self._has_credentials:
            raise ProviderUpstreamError("google_places_no_credentials")
        url = f"{self._base_url}/v1/places/{place_id}"
        try:
            resp = await self._client.get(url, headers=self._headers(_DETAIL_FIELD_MASK))
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "google_places", "upstream_status": None, "reason": "timeout"},
            )
            raise ProviderUpstreamError("google_places_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("google_places_detail_network_error") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            raise ProviderUpstreamError(
                "google_places_detail_upstream_error", status_code=resp.status_code
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderUpstreamError("google_places_detail_invalid_json") from exc

        if not isinstance(payload, dict) or not place_id_of(payload):
            return None
        return payload

    async def resolve_photo_url(self, photo_ref: str, *, max_width_px: int = 1600) -> str | None:
        """Resolve a Places photo resource name → a keyless, loadable image URL.

        Calls the Place Photo ``…/media`` endpoint with ``skipHttpRedirect=true``
        so Google returns ``{photoUri}`` (a googleusercontent CDN URL that needs
        no API key) as JSON rather than 302-ing to it. That keeps our key
        server-side while letting the browser fetch bytes straight from Google's
        CDN. Returns ``None`` — never raises — on no key / bad ref / any upstream
        failure, so the proxy degrades to a 404 the card treats as "no photo".

        A small in-process TTL cache avoids re-billing the Photo SKU on repeat
        loads; the proxy also sets ``Cache-Control`` so the browser caches too.
        """
        if not self._has_credentials or not photo_ref:
            return None

        cached = _photo_url_cache_get(photo_ref)
        if cached is not None:
            return cached

        url = f"{self._base_url}/v1/{photo_ref.lstrip('/')}/media"
        params = {"maxWidthPx": str(max_width_px), "skipHttpRedirect": "true"}
        try:
            resp = await self._client.get(url, params=params, headers=self._media_headers())
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return None

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "google_places",
                    "upstream_status": resp.status_code,
                    "reason": "photo_non_2xx",
                },
            )
            return None

        try:
            payload = resp.json()
        except ValueError:
            return None

        photo_uri = _as_dict(payload).get("photoUri")
        if not isinstance(photo_uri, str) or not photo_uri:
            return None
        _photo_url_cache_put(photo_ref, photo_uri)
        return photo_uri

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch one place by id and normalize it.

        ``None`` when the place is absent (404 / empty body); raises
        :class:`ProviderUpstreamError` on transport/HTTP errors so the router
        can distinguish "not found" from "upstream broken".
        """
        place = await self.place_details(source_id)
        if place is None:
            return None
        try:
            return normalize_place(place)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={
                    "source": "google_places",
                    "source_id": source_id,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("google_places_detail_malformed") from exc
