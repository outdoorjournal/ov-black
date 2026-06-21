"""Ratehawk (Emerging Travel Group / Worldota) hotels ``InventoryProvider``.

Adapts the ETG B2B v3 hotel-search API to the shared ``InventoryProvider``
seam so ``search_inventory(kinds=['hotel'])`` returns normalized
:class:`HotelItem` records alongside OV experiences and Duffel flights.

Search flow (one POST, unlike Duffel's two-step):

- by region: ``POST /search/serp/region/`` with a ``region_id``;
- by coordinates: ``POST /search/serp/geo/`` with ``latitude`` + ``longitude``.

Both return ``{data: {hotels: [...]}, status, error}`` where each hotel
carries ``id`` / ``hid`` and a ``rates[]`` list. Each hotel maps to one
:class:`HotelItem` headlined by its *cheapest* rate; the full hotel object
(every rate, ``book_hash`` per rate) rides in ``raw`` so a later
card-mapping / booking slice can pick a specific rate without re-searching.

**Fixture honesty (net-new — no ``voyage-site`` reference, see mvp-plan §8/B3).**
The ETG SERP response proper carries *only* ``id``/``hid``/``rates`` per
hotel — name, star rating, coordinates and images live in a separate static
content store (the hotel content dump, or ``POST /hotel/info/``). To keep the
adapter's full name→geo→price mapping demonstrable offline, the committed
fixture inlines that static content under a ``static_vm`` key per hotel and
:func:`_static_block` reads it defensively. Wiring the *real* static join
(content dump vs. per-hotel ``/hotel/info/``) is the documented follow-up to
do during the ETG credential spike — at which point the fixture should be
re-recorded from a live call. ``get_detail`` already hits ``/hotel/info/`` and
reuses the same static extractor, so the static shape is exercised both ways.

Design notes (mirror :mod:`app.inventory.providers.ov` / ``.duffel``):

- One ``httpx.AsyncClient`` per provider instance; tests swap it for one
  backed by ``httpx.MockTransport`` so the suite stays offline.
- ``normalize_ratehawk_hotel`` / ``summarize_hotel`` are pure functions over
  the recorded fixture shape at ``tests/fixtures/ratehawk_hotels.json``.
- Search params don't fit ``keyword``; they ride in ``filters``:
  ``region_id`` *or* (``latitude`` + ``longitude``), plus ``checkin`` +
  ``checkout`` (all required for a hotel search), and optional ``adults``,
  ``children`` (ages), ``residency``, ``currency``, ``language``, ``radius``,
  ``limit``. Missing required params → ``[]`` + a warning (a hotel-less
  aggregate search shouldn't 500 the whole page).
- ``search()`` degrades to ``[]`` + a warning on any upstream failure or a
  non-``ok`` ETG envelope; ``get_detail()`` returns ``None`` when the hotel
  is absent and raises :class:`ProviderUpstreamError` on transport/HTTP errors.
- ETG auth is HTTP Basic (``key_id`` : ``api_key``); the credential is sent
  in the ``Authorization`` header and NEVER logged (``repr=False`` on the
  settings field). With no credentials the provider stays registered but every
  ``search`` returns ``[]`` + a warning, so a misconfigured deploy degrades
  instead of crashing boot.
"""

from __future__ import annotations

import base64
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

logger = logging.getLogger("ov_black.inventory.ratehawk")


class ProviderUpstreamError(Exception):
    """Raised by ``get_detail`` when Ratehawk fails for a non-"not found" reason.

    The router layer maps this to HTTP 502 so the caller sees an
    unambiguous "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# Hotel SERP polls supplier systems synchronously and can be slow — give it the
# same headroom as Duffel rather than OV's 5s default.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)

# Static image URLs are templated with a ``{size}`` placeholder (e.g.
# ``.../t/{size}/content/.../1.jpg``); pick a sensible card-hero size.
_IMAGE_SIZE = "x500"

_DEFAULT_RESIDENCY = "us"
_DEFAULT_CURRENCY = "USD"
_DEFAULT_LANGUAGE = "en"


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce ``value`` to a dict, or ``{}`` — keeps extraction defensive."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _static_block(hotel: dict[str, Any]) -> dict[str, Any]:
    """The hotel's static content (name/geo/star/images).

    For a SERP hotel this is the inlined ``static_vm`` block (see the module
    docstring on fixture honesty); for a ``/hotel/info/`` response the caller
    passes the static ``data`` straight through as ``static_vm``. Either way
    a missing block degrades to ``{}`` and the item still normalizes off its
    id + rates.
    """
    return _as_dict(hotel.get("static_vm"))


def _hotel_name(static: dict[str, Any], hotel_id: str) -> str:
    name = static.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    # Fall back to a humanized id ("grand_hotel_tremezzo" → "Grand Hotel
    # Tremezzo") so a static-less SERP result still has a legible title.
    return hotel_id.replace("_", " ").replace("-", " ").strip().title() or hotel_id


def _hotel_stars(static: dict[str, Any]) -> int | None:
    rating = static.get("star_rating")
    if isinstance(rating, bool):  # bool is an int subclass — exclude it
        return None
    if isinstance(rating, int) and rating > 0:
        return rating
    if isinstance(rating, float) and rating > 0:
        return int(rating)
    return None


def _hotel_photos(static: dict[str, Any]) -> list[str]:
    photos: list[str] = []
    for raw in _as_list(static.get("images")):
        if isinstance(raw, str) and raw:
            url = raw.replace("{size}", _IMAGE_SIZE)
            if url not in photos:
                photos.append(url)
    return photos


def _region_name(static: dict[str, Any]) -> str | None:
    name = _as_dict(static.get("region")).get("name")
    return name if isinstance(name, str) and name else None


def _hotel_location(static: dict[str, Any]) -> Location | None:
    """Build a Location from *static* content only.

    Label is derived from the real static name/region — never the humanized-id
    title fallback, so a static-less SERP hotel (no geo, no name) yields ``None``
    rather than a useless coordinate-free label that just echoes the title.
    """
    lat = static.get("latitude")
    lng = static.get("longitude")
    name = static.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    region = _region_name(static)
    if name and region:
        label: str | None = f"{name}, {region}"
    else:
        label = name or region
    has_geo = isinstance(lat, (int, float)) and not isinstance(lat, bool)
    has_geo = has_geo and isinstance(lng, (int, float)) and not isinstance(lng, bool)
    if not has_geo and label is None:
        return None
    return Location(
        lat=float(lat) if has_geo else None,
        lng=float(lng) if has_geo else None,
        label=label,
    )


def _show_amount(payment_type: dict[str, Any]) -> tuple[float | None, str | None]:
    """(amount, currency) in the partner's *display* currency for one payment type.

    ETG quotes both a settlement ``amount``/``currency_code`` and a
    ``show_amount``/``show_currency_code`` in the requested display currency.
    The traveler-facing card wants the display figure, so prefer ``show_*``.
    """
    amount = payment_type.get("show_amount")
    currency = payment_type.get("show_currency_code")
    value: float | None = None
    if isinstance(amount, str) and amount:
        try:
            value = float(amount)
        except ValueError:
            value = None
    elif isinstance(amount, (int, float)) and not isinstance(amount, bool):
        value = float(amount)
    code = currency if isinstance(currency, str) and currency else None
    return value, code


def _rate_payment_type(rate: dict[str, Any]) -> dict[str, Any]:
    types = _as_list(_as_dict(rate.get("payment_options")).get("payment_types"))
    return _as_dict(types[0]) if types else {}


def _rate_price(rate: dict[str, Any]) -> tuple[float | None, str | None]:
    return _show_amount(_rate_payment_type(rate))


def _cheapest_rate(rates: list[Any]) -> dict[str, Any] | None:
    """The rate with the lowest display ``show_amount``.

    Rates whose price can't be parsed sort last (``+inf``) so a hotel that has
    at least one priceable rate still headlines off it. ``None`` only when
    there are no rate objects at all.
    """
    dict_rates = [_as_dict(r) for r in rates if isinstance(r, dict)]
    if not dict_rates:
        return None

    def _key(rate: dict[str, Any]) -> float:
        value, _ = _rate_price(rate)
        return value if value is not None else float("inf")

    return min(dict_rates, key=_key)


def _rate_nights(rate: dict[str, Any]) -> int | None:
    daily = _as_list(rate.get("daily_prices"))
    return len(daily) if daily else None


def _rate_room_name(rate: dict[str, Any]) -> str | None:
    name = rate.get("room_name")
    return name if isinstance(name, str) and name else None


def _rate_room_type(rate: dict[str, Any]) -> str | None:
    rtype = _as_dict(rate.get("room_data_trans")).get("main_room_type")
    return rtype if isinstance(rtype, str) and rtype else None


def _rate_bedding(rate: dict[str, Any]) -> str | None:
    bedding = _as_dict(rate.get("room_data_trans")).get("bedding_type")
    return bedding if isinstance(bedding, str) and bedding else None


def _rate_board(rate: dict[str, Any]) -> str | None:
    """Normalize ETG ``meal`` to a human board descriptor (``nomeal`` → None)."""
    meal = rate.get("meal")
    if not isinstance(meal, str) or not meal or meal == "nomeal":
        return None
    return meal.replace("-", " ").replace("_", " ")


def _free_cancellation_before(rate: dict[str, Any]) -> str | None:
    fcb = _as_dict(_rate_payment_type(rate).get("cancellation_penalties")).get(
        "free_cancellation_before"
    )
    return fcb if isinstance(fcb, str) and fcb else None


def summarize_hotel(hotel: dict[str, Any]) -> dict[str, Any]:
    """Pull the headline hotel facts out of a raw Ratehawk SERP hotel.

    A stable, provider-agnostic summary used here to build the card title /
    tags and exported so a later node-mapping slice can populate
    ``HotelCardAttrs`` (name, room_type, nights, board, free-cancellation
    deadline) without re-walking ETG's nested shape. ``check_in``/``check_out``
    are NOT in the per-hotel response — they're the search-request dates, so
    the node-mapping slice stamps them from the originating search. Every
    field is best-effort: missing data yields ``None`` rather than raising.
    """
    static = _static_block(hotel)
    hotel_id = hotel.get("id")
    cheapest = _cheapest_rate(_as_list(hotel.get("rates"))) or {}
    amount, currency = _rate_price(cheapest)
    return {
        "hotel_id": hotel_id if isinstance(hotel_id, str) else None,
        "hid": hotel.get("hid") if isinstance(hotel.get("hid"), int) else None,
        "name": static.get("name") if isinstance(static.get("name"), str) else None,
        "star_rating": _hotel_stars(static),
        "latitude": static.get("latitude")
        if isinstance(static.get("latitude"), (int, float))
        else None,
        "longitude": static.get("longitude")
        if isinstance(static.get("longitude"), (int, float))
        else None,
        "address": static.get("address")
        if isinstance(static.get("address"), str)
        else None,
        "room_name": _rate_room_name(cheapest),
        "room_type": _rate_room_type(cheapest),
        "bedding": _rate_bedding(cheapest),
        "nights": _rate_nights(cheapest),
        "board": _rate_board(cheapest),
        "amount": amount,
        "currency": currency,
        "free_cancellation_before": _free_cancellation_before(cheapest),
        "book_hash": cheapest.get("book_hash")
        if isinstance(cheapest.get("book_hash"), str)
        else None,
    }


def _build_price(rate: dict[str, Any]) -> Price | None:
    amount, currency = _rate_price(rate)
    if amount is None and currency is None:
        return None
    # A hotel rate is a single total for the stay (not a min/max range), so the
    # ``amount_min``/``amount_max`` collapse to one figure like the OV adapter.
    return Price(amount_min=amount, amount_max=amount, currency=currency)


def _build_tags(summary: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    stars = summary.get("star_rating")
    if isinstance(stars, int):
        tags.append(f"{stars}-star")
    if summary.get("board"):
        tags.append(str(summary["board"]))
    if summary.get("room_type"):
        tags.append(str(summary["room_type"]))
    if summary.get("free_cancellation_before"):
        tags.append("free cancellation")
    return tags


def normalize_ratehawk_hotel(hotel: dict[str, Any]) -> HotelItem:
    """Map one Ratehawk SERP hotel to a :class:`HotelItem`.

    Pure function over the wire shape. Raises ``ValueError`` on a hotel with
    no id; callers (``RatehawkProvider.search``) catch that and skip the
    offending hotel. The full hotel object (all rates + ``book_hash`` values)
    is preserved in ``raw`` for later rate selection / booking.
    """
    source_id = hotel.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("ratehawk hotel missing id")

    static = _static_block(hotel)
    name = _hotel_name(static, source_id)
    summary = summarize_hotel(hotel)
    cheapest = _cheapest_rate(_as_list(hotel.get("rates"))) or {}

    address = static.get("address")
    description = address if isinstance(address, str) and address else None

    return HotelItem(
        source="ratehawk",
        source_id=source_id,
        title=name,
        description=description,
        photos=_hotel_photos(static),
        location=_hotel_location(static),
        price=_build_price(cheapest),
        editorial_links=[],
        tags=_build_tags(summary),
        stars=_hotel_stars(static),
        raw=hotel,
    )


class RatehawkProvider(InventoryProvider):
    """Adapter for the Ratehawk (ETG / Worldota) B2B hotels API."""

    source = "ratehawk"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.ratehawk_base_url.rstrip("/")
        self._key_id = self._settings.ratehawk_key_id or None
        self._api_key = self._settings.ratehawk_api_key or None
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _has_credentials(self) -> bool:
        return bool(self._key_id and self._api_key)

    def _headers(self) -> dict[str, str]:
        # ETG uses HTTP Basic (key_id:api_key). The Authorization value carries
        # the secret; never log this dict.
        token = base64.b64encode(f"{self._key_id}:{self._api_key}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_search(self, filters: dict) -> tuple[str, dict[str, Any]] | None:
        """Pick the SERP endpoint + request body from ``filters``.

        Region search wins when ``region_id`` is present; otherwise a geo
        search runs when both ``latitude`` and ``longitude`` are present.
        ``checkin`` + ``checkout`` are required for either. Returns ``None``
        (→ ``[]`` + a warning) when the required params are missing.
        """
        checkin = filters.get("checkin")
        checkout = filters.get("checkout")
        if not (
            isinstance(checkin, str) and checkin and isinstance(checkout, str) and checkout
        ):
            return None

        adults = filters.get("adults")
        adult_count = adults if isinstance(adults, int) and adults > 0 else 1
        children = [
            age for age in _as_list(filters.get("children")) if isinstance(age, int)
        ]

        residency = filters.get("residency")
        currency = filters.get("currency")
        language = filters.get("language")
        body: dict[str, Any] = {
            "checkin": checkin,
            "checkout": checkout,
            "residency": residency
            if isinstance(residency, str) and residency
            else _DEFAULT_RESIDENCY,
            "language": language
            if isinstance(language, str) and language
            else _DEFAULT_LANGUAGE,
            "currency": currency
            if isinstance(currency, str) and currency
            else _DEFAULT_CURRENCY,
            "guests": [{"adults": adult_count, "children": children}],
        }

        region_id = filters.get("region_id")
        if isinstance(region_id, int) and not isinstance(region_id, bool):
            body["region_id"] = region_id
            return f"{self._base_url}/search/serp/region/", body

        latitude = filters.get("latitude")
        longitude = filters.get("longitude")
        if (
            isinstance(latitude, (int, float))
            and not isinstance(latitude, bool)
            and isinstance(longitude, (int, float))
            and not isinstance(longitude, bool)
        ):
            body["latitude"] = float(latitude)
            body["longitude"] = float(longitude)
            radius = filters.get("radius")
            if isinstance(radius, int) and radius > 0:
                body["radius"] = radius
            return f"{self._base_url}/search/serp/geo/", body

        return None

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return :class:`HotelItem` records (cheapest rate each); ``[]`` on failure.

        ``kinds`` is accepted for interface parity but ignored — every
        Ratehawk result is a hotel. Region/geo + dates come from ``filters``.
        """
        if not self._has_credentials:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": "no_credentials"},
            )
            return []

        filters = filters if isinstance(filters, dict) else {}
        built = self._build_search(filters)
        if built is None:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "ratehawk",
                    "upstream_status": None,
                    "reason": "missing_search_params",
                },
            )
            return []
        url, body = built

        try:
            resp = await self._client.post(url, json=body, headers=self._headers())
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": exc.__class__.__name__},
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": resp.status_code, "reason": "non_2xx"},
            )
            return []

        try:
            payload = resp.json()
        except ValueError:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": resp.status_code, "reason": "invalid_json"},
            )
            return []

        body_data = self._unwrap_envelope(payload)
        if body_data is None:
            return []

        hotels = _as_list(_as_dict(body_data).get("hotels"))
        limit = filters.get("limit")
        if isinstance(limit, int) and limit > 0:
            hotels = hotels[:limit]

        results: list[InventoryItem] = []
        for hotel in hotels:
            if not isinstance(hotel, dict):
                continue
            try:
                results.append(normalize_ratehawk_hotel(hotel))
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "ratehawk",
                        "source_id": hotel.get("id") if isinstance(hotel.get("id"), str) else None,
                        "reason": exc.__class__.__name__,
                    },
                )
                continue

        logger.info(
            "inventory.provider.search",
            extra={"source": "ratehawk", "keyword": keyword, "result_count": len(results)},
        )
        return results

    def _unwrap_envelope(self, payload: Any) -> dict[str, Any] | None:
        """Return the ETG ``data`` object, or ``None`` on a non-``ok`` envelope.

        ETG wraps every response in ``{status, error, data}`` and returns HTTP
        200 even for business errors (``status='error'``). A non-``ok`` status,
        a populated ``error``, or a null ``data`` all degrade to ``None`` + a
        warning so ``search`` returns ``[]`` rather than raising.
        """
        envelope = _as_dict(payload)
        status = envelope.get("status")
        if status is not None and status != "ok":
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": "envelope_status"},
            )
            return None
        if envelope.get("error"):
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": "envelope_error"},
            )
            return None
        data = envelope.get("data")
        if not isinstance(data, dict):
            return None
        return data

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch one hotel's static content via ``POST /hotel/info/``.

        ETG hotel detail is static content (name/geo/star/images) with no live
        rates, so the returned :class:`HotelItem` carries no ``price`` — pricing
        comes from a fresh ``search``. A missing hotel (null ``data`` / non-``ok``
        envelope) returns ``None``; transport/HTTP errors raise
        :class:`ProviderUpstreamError` so the router can tell "not found" from
        "upstream broken".
        """
        if not self._has_credentials:
            raise ProviderUpstreamError("ratehawk_no_credentials")
        url = f"{self._base_url}/hotel/info/"
        try:
            resp = await self._client.post(
                url,
                json={"id": source_id, "language": _DEFAULT_LANGUAGE},
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": "timeout"},
            )
            raise ProviderUpstreamError("ratehawk_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": None, "reason": exc.__class__.__name__},
            )
            raise ProviderUpstreamError("ratehawk_detail_network_error") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ratehawk", "upstream_status": resp.status_code, "reason": "non_2xx"},
            )
            raise ProviderUpstreamError("ratehawk_detail_upstream_error", status_code=resp.status_code)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderUpstreamError("ratehawk_detail_invalid_json") from exc

        envelope = _as_dict(payload)
        if (envelope.get("status") not in (None, "ok")) or envelope.get("error"):
            # ETG signals an unknown hotel as a business error, not an HTTP 404.
            return None
        data = envelope.get("data")
        if not isinstance(data, dict):
            return None

        # ``/hotel/info/`` returns the static content directly; re-shape it into
        # the SERP ``{id, static_vm, rates}`` form the normalizer expects.
        info_id = data.get("id")
        wrapped = {
            "id": info_id if isinstance(info_id, str) and info_id else source_id,
            "static_vm": data,
            "rates": [],
        }
        try:
            return normalize_ratehawk_hotel(wrapped)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={"source": "ratehawk", "source_id": source_id, "reason": exc.__class__.__name__},
            )
            raise ProviderUpstreamError("ratehawk_detail_malformed") from exc
