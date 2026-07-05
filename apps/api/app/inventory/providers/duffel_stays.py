"""Duffel Stays (hotels) ``InventoryProvider`` adapter.

Duffel exposes hotels through its **Stays** product — a different API surface
from the ``/air/*`` flights endpoints wrapped by
:mod:`app.inventory.providers.duffel`. This adapter maps Stays to the shared
``InventoryProvider`` seam so ``search_inventory(kinds=['hotel'])`` returns
normalized :class:`HotelItem` records alongside OV experiences, Duffel flights,
and Ratehawk hotels.

Search is a single POST (unlike Duffel flights' two-step offer flow):

- ``POST /stays/search`` with a ``location`` (geographic coordinates + radius),
  ``check_in_date`` / ``check_out_date``, ``guests`` and ``rooms`` →
  ``{data: {id, results: [...]}}`` where each result carries an ``accommodation``
  block plus a headline ``cheapest_rate_total_amount`` / ``cheapest_rate_currency``.

Each result maps to one :class:`HotelItem` headlined by that cheapest rate; the
full result rides in ``raw`` so a later card-mapping / booking slice can call
``POST /stays/search_results/{id}/actions/fetch_all_rates`` to pick a specific
room + rate without re-searching. Like a Duffel flight offer, a Stays search
result is a *time-boxed quote* (``expires_at``): the headline amount is a
best-effort figure at search time and must be re-priced before booking.

Design notes (mirror :mod:`app.inventory.providers.duffel` / ``.ratehawk``):

- One ``httpx.AsyncClient`` per provider instance; tests swap it for one backed
  by ``httpx.MockTransport`` so the suite stays offline.
- ``normalize_duffel_stay`` / ``summarize_stay`` are pure functions over the
  recorded fixture shape at ``tests/fixtures/duffel_stays.json``. Any field we
  skip flows through in ``raw``.
- Search params don't fit ``keyword``; they ride in ``filters``: ``latitude`` +
  ``longitude`` and ``checkin`` + ``checkout`` (all required for a hotel
  search), plus optional ``adults``, ``children`` (ages), ``rooms``, ``radius``
  (km, 1–100), ``limit``. Missing required params → ``[]`` + a warning (a
  hotel-less aggregate search shouldn't 500 the whole page).
- ``search()`` degrades to ``[]`` + a warning on any upstream failure;
  ``get_detail()`` returns ``None`` when the result is gone (expired/404) and
  raises :class:`ProviderUpstreamError` on transport/other HTTP errors.
- Credentials + version are shared with the flights adapter (same Duffel
  account): ``DUFFEL_API_KEY`` is forwarded as ``Authorization: Bearer`` and
  NEVER logged (``repr=False`` on the settings field). With no key the provider
  stays registered but every ``search`` returns ``[]`` + a warning, so a
  misconfigured deploy degrades instead of crashing boot.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import (
    HotelItem,
    InventoryItem,
    Location,
    Price,
)

logger = logging.getLogger("ov_black.inventory.duffel_stays")


class ProviderUpstreamError(Exception):
    """Raised by ``get_detail`` when Duffel Stays fails for a non-"gone" reason.

    The router layer maps this to HTTP 502 so the caller sees an unambiguous
    "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# Stays search polls supplier systems synchronously and can be slow — give it
# the same headroom as the flights adapter rather than OV's 5s default.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)

# Duffel radius is in km, clamped to 1–100 with a 5km default.
_DEFAULT_RADIUS_KM = 5


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce ``value`` to a dict, or ``{}`` — keeps extraction defensive."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_or_none(value: Any) -> int | None:
    """A plain int (``bool`` is an int subclass, so exclude it), else ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _accommodation(result: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(result.get("accommodation"))


def _coordinates(accommodation: dict[str, Any]) -> tuple[float | None, float | None]:
    """(latitude, longitude) from an accommodation's ``location`` block."""
    coords = _as_dict(_as_dict(accommodation.get("location")).get("geographic_coordinates"))
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    lat_f = float(lat) if isinstance(lat, (int, float)) and not isinstance(lat, bool) else None
    lng_f = float(lng) if isinstance(lng, (int, float)) and not isinstance(lng, bool) else None
    return lat_f, lng_f


def _address(accommodation: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_as_dict(accommodation.get("location")).get("address"))


def _stars(accommodation: dict[str, Any]) -> int | None:
    """Official star classification (1–5). ``bool`` excluded (int subclass)."""
    rating = accommodation.get("rating")
    if isinstance(rating, bool):
        return None
    if isinstance(rating, (int, float)) and rating > 0:
        return int(rating)
    return None


def _review_score(accommodation: dict[str, Any]) -> float | None:
    """Guest review score (0–10). Distinct from the 1–5 star classification."""
    score = accommodation.get("review_score")
    if isinstance(score, bool):
        return None
    if isinstance(score, (int, float)) and score > 0:
        return float(score)
    return None


def _photos(accommodation: dict[str, Any]) -> list[str]:
    """Hero-first photo URLs. Duffel photos are ``[{"url": "https://…"}, …]``."""
    photos: list[str] = []
    for raw in _as_list(accommodation.get("photos")):
        url = _as_dict(raw).get("url")
        if isinstance(url, str) and url and url not in photos:
            photos.append(url)
    return photos


def _amount_str(value: Any) -> float | None:
    """Duffel money is a decimal string in major units (e.g. ``"1840.00"``)."""
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def summarize_stay(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the headline hotel facts out of a raw Duffel Stays search result.

    A stable, provider-agnostic summary used here to build the card title /
    tags and exported so a later node-mapping slice can populate
    ``HotelCardAttrs`` (name, star rating, review score, dates, price) without
    re-walking Duffel's nested shape. Every field is best-effort — missing data
    yields ``None`` rather than raising.
    """
    acc = _accommodation(result)
    lat, lng = _coordinates(acc)
    address = _address(acc)
    name = acc.get("name")
    return {
        "result_id": result.get("id") if isinstance(result.get("id"), str) else None,
        "accommodation_id": acc.get("id") if isinstance(acc.get("id"), str) else None,
        "name": name if isinstance(name, str) and name else None,
        "star_rating": _stars(acc),
        "review_score": _review_score(acc),
        "review_count": _int_or_none(acc.get("review_count")),
        "latitude": lat,
        "longitude": lng,
        "city": address.get("city_name") if isinstance(address.get("city_name"), str) else None,
        "address": address.get("line_one") if isinstance(address.get("line_one"), str) else None,
        "check_in_date": result.get("check_in_date")
        if isinstance(result.get("check_in_date"), str)
        else None,
        "check_out_date": result.get("check_out_date")
        if isinstance(result.get("check_out_date"), str)
        else None,
        "rooms": _int_or_none(result.get("rooms")),
        "amount": _amount_str(result.get("cheapest_rate_total_amount")),
        "currency": result.get("cheapest_rate_currency")
        if isinstance(result.get("cheapest_rate_currency"), str)
        else None,
        "expires_at": result.get("expires_at")
        if isinstance(result.get("expires_at"), str)
        else None,
    }


def _humanize_id(source_id: str) -> str:
    return source_id.replace("_", " ").replace("-", " ").strip().title() or source_id


def _build_location(accommodation: dict[str, Any]) -> Location | None:
    lat, lng = _coordinates(accommodation)
    address = _address(accommodation)
    name = accommodation.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    city = address.get("city_name")
    city = city if isinstance(city, str) and city else None
    if name and city:
        label: str | None = f"{name}, {city}"
    else:
        label = name or city
    has_geo = lat is not None and lng is not None
    if not has_geo and label is None:
        return None
    return Location(lat=lat if has_geo else None, lng=lng if has_geo else None, label=label)


def _build_price(result: dict[str, Any]) -> Price | None:
    """Headline the cheapest rate for the whole stay (a single total, not a range)."""
    amount = _amount_str(result.get("cheapest_rate_total_amount"))
    currency = result.get("cheapest_rate_currency")
    code = currency if isinstance(currency, str) and currency else None
    if amount is None and code is None:
        return None
    return Price(amount_min=amount, amount_max=amount, currency=code)


def _build_tags(summary: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    stars = summary.get("star_rating")
    if isinstance(stars, int):
        tags.append(f"{stars}-star")
    score = summary.get("review_score")
    if isinstance(score, (int, float)):
        # ``:g`` trims a trailing ``.0`` so 9.0 reads "9/10", 9.4 reads "9.4/10".
        tags.append(f"{score:g}/10")
    return tags


def normalize_duffel_stay(result: dict[str, Any]) -> HotelItem:
    """Map one Duffel Stays search result to a :class:`HotelItem`.

    Pure function over the wire shape. Raises ``ValueError`` on a result with
    no id; callers (``DuffelStaysProvider.search``) catch that and skip the
    offending result. The full result (accommodation + cheapest-rate headline)
    is preserved in ``raw`` so a later rate-fetch / booking slice can re-use the
    result id.
    """
    source_id = result.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("duffel stays result missing id")

    acc = _accommodation(result)
    name = acc.get("name")
    title = name.strip() if isinstance(name, str) and name.strip() else _humanize_id(source_id)

    description = acc.get("description")
    if not (isinstance(description, str) and description):
        # Fall back to a street/city line so a description-less accommodation
        # still carries a legible sub-title.
        address = _address(acc)
        line = address.get("line_one")
        city = address.get("city_name")
        parts = [p for p in (line, city) if isinstance(p, str) and p]
        description = ", ".join(parts) or None

    summary = summarize_stay(result)
    phone = acc.get("phone_number")

    return HotelItem(
        source="duffel_stays",
        source_id=source_id,
        title=title,
        description=description,
        photos=_photos(acc),
        location=_build_location(acc),
        price=_build_price(result),
        editorial_links=[],
        tags=_build_tags(summary),
        rating=summary["review_score"],
        rating_count=summary["review_count"],
        phone=phone if isinstance(phone, str) and phone else None,
        stars=summary["star_rating"],
        raw=result,
    )


def _cheapest_room_rate(accommodation: dict[str, Any]) -> tuple[float | None, str | None]:
    """(amount, currency) of the cheapest room rate on a fetched accommodation.

    ``fetch_all_rates`` returns the accommodation with ``rooms[].rates[]`` where
    each rate has ``total_amount`` / ``total_currency``. Used only by
    ``get_detail`` to synthesize a headline price the search step gets from
    ``cheapest_rate_total_amount``.
    """
    best_amount: float | None = None
    best_currency: str | None = None
    for room in _as_list(accommodation.get("rooms")):
        for rate in _as_list(_as_dict(room).get("rates")):
            amount = _amount_str(_as_dict(rate).get("total_amount"))
            if amount is None:
                continue
            if best_amount is None or amount < best_amount:
                best_amount = amount
                currency = _as_dict(rate).get("total_currency")
                best_currency = currency if isinstance(currency, str) and currency else None
    return best_amount, best_currency


class DuffelStaysProvider(InventoryProvider):
    """Adapter for the Duffel Stays (hotels) API."""

    source = "duffel_stays"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.duffel_base_url.rstrip("/")
        self._api_key = self._settings.duffel_api_key or None
        self._api_version = self._settings.duffel_api_version
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        # Authorization carries the secret; the rest are Duffel protocol
        # headers. Never log this dict.
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Duffel-Version": self._api_version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_search_body(self, filters: dict[str, Any]) -> dict[str, Any] | None:
        """Build the ``/stays/search`` request body, or ``None`` on missing params.

        Requires ``latitude`` + ``longitude`` (geo search) and ``checkin`` +
        ``checkout`` dates. Returns ``None`` (→ ``[]`` + a warning) otherwise.
        """
        latitude = filters.get("latitude")
        longitude = filters.get("longitude")
        checkin = filters.get("checkin")
        checkout = filters.get("checkout")
        if not (
            isinstance(latitude, (int, float))
            and not isinstance(latitude, bool)
            and isinstance(longitude, (int, float))
            and not isinstance(longitude, bool)
            and isinstance(checkin, str)
            and checkin
            and isinstance(checkout, str)
            and checkout
        ):
            return None

        radius = filters.get("radius")
        radius_km = radius if isinstance(radius, int) and 1 <= radius <= 100 else _DEFAULT_RADIUS_KM

        adults = filters.get("adults")
        adult_count = adults if isinstance(adults, int) and adults > 0 else 1
        guests: list[dict[str, Any]] = [{"type": "adult"} for _ in range(adult_count)]
        for age in _as_list(filters.get("children")):
            if isinstance(age, int) and not isinstance(age, bool):
                guests.append({"type": "child", "age": age})

        rooms = filters.get("rooms")
        room_count = rooms if isinstance(rooms, int) and rooms > 0 else 1

        return {
            "location": {
                "radius": radius_km,
                "geographic_coordinates": {
                    "longitude": float(longitude),
                    "latitude": float(latitude),
                },
            },
            "check_in_date": checkin,
            "check_out_date": checkout,
            "guests": guests,
            "rooms": room_count,
        }

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return :class:`HotelItem` records (cheapest rate each); ``[]`` on failure.

        ``kinds`` is accepted for interface parity but ignored — every Duffel
        Stays result is a hotel. Geo + dates come from ``filters``.
        """
        if not self._api_key:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
                    "upstream_status": None,
                    "reason": "no_credentials",
                },
            )
            return []

        filters = filters if isinstance(filters, dict) else {}
        body = self._build_search_body(filters)
        if body is None:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
                    "upstream_status": None,
                    "reason": "missing_search_params",
                },
            )
            return []

        url = f"{self._base_url}/stays/search"
        try:
            resp = await self._client.post(url, json={"data": body}, headers=self._headers())
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel_stays", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
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
                    "source": "duffel_stays",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return []

        results = _as_list(_as_dict(_as_dict(payload).get("data")).get("results"))
        limit = filters.get("limit")
        if isinstance(limit, int) and limit > 0:
            results = results[:limit]

        items: list[InventoryItem] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            try:
                items.append(normalize_duffel_stay(result))
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "duffel_stays",
                        "source_id": result.get("id")
                        if isinstance(result.get("id"), str)
                        else None,
                        "reason": exc.__class__.__name__,
                    },
                )
                continue

        logger.info(
            "inventory.provider.search",
            extra={"source": "duffel_stays", "keyword": keyword, "result_count": len(items)},
        )
        return items

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch a single search result's rooms + rates by its result id.

        Duffel Stays detail is ``POST /stays/search_results/{id}/actions/fetch_all_rates``,
        which returns the full accommodation with every room + rate. A search
        result is time-boxed, so a stale id legitimately 404s → ``None``; other
        transport/HTTP errors raise :class:`ProviderUpstreamError` so the router
        can tell "gone" from "upstream broken".
        """
        if not self._api_key:
            raise ProviderUpstreamError("duffel_stays_no_credentials")
        url = f"{self._base_url}/stays/search_results/{source_id}/actions/fetch_all_rates"
        try:
            resp = await self._client.post(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel_stays", "upstream_status": None, "reason": "timeout"},
            )
            raise ProviderUpstreamError("duffel_stays_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("duffel_stays_detail_network_error") from exc

        if resp.status_code in (404, 410, 422):
            # A gone/expired search result — not an upstream fault.
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel_stays",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            raise ProviderUpstreamError(
                "duffel_stays_detail_upstream_error", status_code=resp.status_code
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderUpstreamError("duffel_stays_detail_invalid_json") from exc

        data = _as_dict(body).get("data")
        if not isinstance(data, dict):
            raise ProviderUpstreamError("duffel_stays_detail_missing_body")

        # ``fetch_all_rates`` returns the accommodation with live rooms/rates but
        # no ``cheapest_rate_total_amount`` headline — synthesize one from the
        # cheapest room rate so the normalizer produces a priced HotelItem.
        accommodation = _as_dict(data.get("accommodation"))
        amount, currency = _cheapest_room_rate(accommodation)
        result_id = data.get("id")
        wrapped: dict[str, Any] = {
            "id": result_id if isinstance(result_id, str) and result_id else source_id,
            "accommodation": accommodation,
            "check_in_date": data.get("check_in_date"),
            "check_out_date": data.get("check_out_date"),
            "rooms": data.get("rooms"),
            "cheapest_rate_total_amount": f"{amount:.2f}" if amount is not None else None,
            "cheapest_rate_currency": currency,
        }
        try:
            return normalize_duffel_stay(wrapped)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={
                    "source": "duffel_stays",
                    "source_id": source_id,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("duffel_stays_detail_malformed") from exc
