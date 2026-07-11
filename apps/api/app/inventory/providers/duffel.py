"""Duffel flights ``InventoryProvider`` adapter.

Adapts Duffel's two-step offer flow to the shared ``InventoryProvider``
seam so ``search_inventory(kinds=['flight'])`` returns normalized
:class:`FlightItem` records alongside OV experiences, hotels, etc.:

1. ``POST /air/offer_requests`` (``return_offers=false``) → an offer-request id.
2. ``GET /air/offers?offer_request_id=…&sort=total_amount`` → ranked offers.

Each Duffel offer maps to a :class:`FlightItem`; the full offer rides in
``raw`` so a later card-mapping slice (``FlightCardAttrs``) can read segment
detail — cabin, seat, departing/arriving times — without re-hitting Duffel.

Design notes (mirrors :mod:`app.inventory.providers.ov`):

- One ``httpx.AsyncClient`` per provider instance. Tests swap it for one
  backed by ``httpx.MockTransport`` so the suite stays offline.
- ``normalize_duffel_offer`` / ``summarize_offer`` are pure functions over
  the recorded fixture shape at ``tests/fixtures/duffel_offers.json``. Any
  field we skip flows through in ``raw``.
- Flight search needs a route + date, which don't fit ``keyword``. They ride
  in ``filters``: ``origin``, ``destination``, ``departure_date`` (required),
  plus optional ``return_date``, ``cabin_class``, ``adults``, ``limit``.
  Missing required params → ``[]`` + a warning (a flightless aggregate
  search shouldn't 500 the whole page).
- ``search()`` degrades to ``[]`` + a warning on any upstream failure
  (best-effort multi-source aggregation); ``get_detail()`` returns ``None``
  on 404 and raises :class:`ProviderUpstreamError` on anything else.
- ``DUFFEL_API_KEY`` is forwarded as ``Authorization: Bearer`` and NEVER
  logged (``repr=False`` on the settings field). With no key configured the
  provider stays registered but every ``search`` returns ``[]`` + a warning,
  so a misconfigured deploy degrades instead of crashing boot.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import (
    FlightItem,
    InventoryItem,
    Location,
    Price,
)

logger = logging.getLogger("ov_black.inventory.duffel")


class ProviderUpstreamError(Exception):
    """Raised by ``get_detail`` when Duffel returns a non-404 upstream error.

    The router layer maps this to HTTP 502 so the caller sees an
    unambiguous "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# Offer search can be slower than a simple GET — Duffel polls airline GDS
# systems synchronously. Give it more headroom than the OV 5s default.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce ``value`` to a dict, or ``{}`` — keeps extraction defensive."""
    return value if isinstance(value, dict) else {}


def _iata(node: Any) -> str | None:
    code = _as_dict(node).get("iata_code")
    return code if isinstance(code, str) and code else None


def _slice_endpoints(offer: dict[str, Any]) -> tuple[str | None, str | None]:
    """(origin_iata, destination_iata) of the OUTBOUND leg (first slice).

    Scoped entirely to the first slice, mirroring ``_last_outbound_segment``.
    A round-trip offer's LAST slice is the return leg, whose destination is the
    original origin — reading ``slices[-1]`` would collapse an outbound like
    DTW→NRT (return NRT→DTW) into DTW→DTW. The card represents the outbound
    journey (its depart/arrive already come off the first slice), so both
    endpoints must too.
    """
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return (None, None)
    first = _as_dict(slices[0])
    return (_iata(first.get("origin")), _iata(first.get("destination")))


def _first_segment(offer: dict[str, Any]) -> dict[str, Any]:
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return {}
    segments = _as_dict(slices[0]).get("segments")
    if not isinstance(segments, list) or not segments:
        return {}
    return _as_dict(segments[0])


def _last_outbound_segment(offer: dict[str, Any]) -> dict[str, Any]:
    """Final segment of the FIRST slice — the true arrival leg.

    A one-way offer can still route via a connection (e.g. HND→MNL→LAX is one
    slice, two segments), so the arrival airport + time live on the LAST
    segment, not the first. Taking them from ``_first_segment`` would report a
    layover as the destination. Scoped to the first slice so a round-trip
    offer's arrival is the outbound arrival, not the return leg.
    """
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return {}
    segments = _as_dict(slices[0]).get("segments")
    if not isinstance(segments, list) or not segments:
        return {}
    return _as_dict(segments[-1])


def _localize(naive_local: Any, place: Any) -> str | None:
    """Attach an airport's UTC offset to a Duffel offset-less local datetime.

    Duffel emits ``departing_at`` / ``arriving_at`` as wall-clock at the
    airport with NO offset (e.g. ``"2026-07-29T21:40:00"``); the airport
    ``place`` carries an IANA ``time_zone`` (e.g. ``"America/Los_Angeles"``).
    A trip spans zones (LAX departs PDT, HND arrives JST), so without the
    offset the same string is an ambiguous instant. Return an offset-bearing
    ISO 8601 string for the SAME wall-clock (e.g. ``"…-07:00"`` / ``"…+09:00"``);
    fall back to the raw string when the time or zone is missing/unknown, and
    leave an already offset-bearing value untouched.
    """
    if not isinstance(naive_local, str) or not naive_local:
        return None
    try:
        dt = datetime.fromisoformat(naive_local)
    except ValueError:
        return naive_local
    if dt.tzinfo is not None:
        return naive_local
    tz_name = _as_dict(place).get("time_zone")
    if not isinstance(tz_name, str) or not tz_name:
        return naive_local
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return naive_local
    return dt.replace(tzinfo=tz).isoformat()


def _carrier_name(offer: dict[str, Any]) -> str | None:
    name = _as_dict(offer.get("owner")).get("name")
    return name if isinstance(name, str) and name else None


def _cabin_classes(offer: dict[str, Any]) -> list[str]:
    """Distinct cabin classes across every segment passenger, in order."""
    seen: list[str] = []
    slices = offer.get("slices")
    if not isinstance(slices, list):
        return seen
    for sl in slices:
        segments = _as_dict(sl).get("segments")
        if not isinstance(segments, list):
            continue
        for seg in segments:
            for pax in _as_dict(seg).get("passengers") or []:
                cabin = _as_dict(pax).get("cabin_class")
                if isinstance(cabin, str) and cabin and cabin not in seen:
                    seen.append(cabin)
    return seen


def _stop_count(offer: dict[str, Any]) -> int | None:
    """Stops on the first (outbound) slice = segment count − 1, or None."""
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return None
    segments = _as_dict(slices[0]).get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    return len(segments) - 1


def summarize_offer(offer: dict[str, Any]) -> dict[str, Any]:
    """Pull the headline flight facts out of a raw Duffel offer.

    A stable, provider-agnostic summary used here to build the card title /
    tags and exported so a later node-mapping slice can populate
    ``FlightCardAttrs`` (iata_from/to, flight_code, cabin, depart/arrive)
    without re-walking Duffel's nested shape. Every field is best-effort —
    missing data yields ``None`` rather than raising.
    """
    iata_from, iata_to = _slice_endpoints(offer)
    seg = _first_segment(offer)
    arr_seg = _last_outbound_segment(offer)
    carrier = seg.get("marketing_carrier") or seg.get("operating_carrier")
    flight_number = seg.get("marketing_carrier_flight_number")
    carrier_code = _iata(carrier)
    flight_code: str | None = None
    if carrier_code and isinstance(flight_number, str) and flight_number:
        flight_code = f"{carrier_code}{flight_number}"
    cabins = _cabin_classes(offer)
    # ``expires_at`` / ``total_amount`` make the time-boxed nature of a flight
    # quote first-class: a Duffel offer is a price HELD for a fixed window, not
    # a stable listing price. Downstream (pre-booking refresh, money gate) must
    # treat the amount as valid only until ``expires_at`` and re-price before
    # booking — the refreshed amount can differ. See doc/mvp-plan.md §8.
    return {
        "iata_from": iata_from,
        "iata_to": iata_to,
        "flight_code": flight_code,
        "carrier": _carrier_name(offer),
        "cabin": cabins[0] if cabins else None,
        "depart_at": _localize(seg.get("departing_at"), seg.get("origin")),
        "arrive_at": _localize(arr_seg.get("arriving_at"), arr_seg.get("destination")),
        "stops": _stop_count(offer),
        "total_amount": offer.get("total_amount")
        if isinstance(offer.get("total_amount"), str)
        else None,
        "total_currency": offer.get("total_currency")
        if isinstance(offer.get("total_currency"), str)
        else None,
        "expires_at": offer.get("expires_at") if isinstance(offer.get("expires_at"), str) else None,
    }


def _build_location(offer: dict[str, Any]) -> Location | None:
    """Anchor a flight at its origin airport (first slice origin)."""
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return None
    origin = _as_dict(_as_dict(slices[0]).get("origin"))
    lat = origin.get("latitude")
    lng = origin.get("longitude")
    city = origin.get("city_name")
    code = origin.get("iata_code")
    label: str | None = None
    if isinstance(city, str) and city:
        label = f"{city} ({code})" if isinstance(code, str) and code else city
    elif isinstance(code, str) and code:
        label = code
    if lat is None and lng is None and label is None:
        return None
    return Location(
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
        label=label,
    )


def _build_price(offer: dict[str, Any]) -> Price | None:
    """Duffel quotes ``total_amount`` as a decimal string in major units."""
    amount = offer.get("total_amount")
    currency = offer.get("total_currency")
    value: float | None = None
    if isinstance(amount, str) and amount:
        try:
            value = float(amount)
        except ValueError:
            value = None
    elif isinstance(amount, (int, float)):
        value = float(amount)
    currency_code = currency if isinstance(currency, str) and currency else None
    if value is None and currency_code is None:
        return None
    return Price(amount_min=value, amount_max=value, currency=currency_code)


def _build_tags(summary: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    if summary.get("carrier"):
        tags.append(str(summary["carrier"]))
    if summary.get("cabin"):
        tags.append(str(summary["cabin"]))
    stops = summary.get("stops")
    if isinstance(stops, int):
        tags.append("nonstop" if stops == 0 else f"{stops} stop" + ("s" if stops > 1 else ""))
    return tags


def normalize_duffel_offer(offer: dict[str, Any]) -> FlightItem:
    """Map one Duffel offer to a :class:`FlightItem`.

    Pure function over the wire shape. Raises ``ValueError`` on an offer
    with no id; callers (``DuffelProvider.search``) catch that and skip the
    offending offer. The full offer is preserved in ``raw`` for later
    re-normalization / card mapping.
    """
    source_id = offer.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("duffel offer missing id")

    summary = summarize_offer(offer)
    iata_from = summary["iata_from"]
    iata_to = summary["iata_to"]
    carrier = summary["carrier"]

    if iata_from and iata_to:
        route = f"{iata_from} → {iata_to}"
    elif iata_from or iata_to:
        route = str(iata_from or iata_to)
    else:
        route = "Flight"
    title = f"{route} · {carrier}" if carrier else route

    logo = _as_dict(offer.get("owner")).get("logo_symbol_url")
    photos = [logo] if isinstance(logo, str) and logo else []

    return FlightItem(
        source="duffel",
        source_id=source_id,
        title=title,
        description=None,
        photos=photos,
        location=_build_location(offer),
        price=_build_price(offer),
        editorial_links=[],
        tags=_build_tags(summary),
        raw=offer,
    )


class DuffelProvider(InventoryProvider):
    """Adapter for the Duffel flights API."""

    source = "duffel"

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

    def _build_slices(self, filters: dict[str, Any]) -> list[dict[str, str]] | None:
        origin = filters.get("origin")
        destination = filters.get("destination")
        departure_date = filters.get("departure_date")
        if not (
            isinstance(origin, str)
            and origin
            and isinstance(destination, str)
            and destination
            and isinstance(departure_date, str)
            and departure_date
        ):
            return None
        slices = [
            {
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
            }
        ]
        return_date = filters.get("return_date")
        if isinstance(return_date, str) and return_date:
            slices.append(
                {
                    "origin": destination,
                    "destination": origin,
                    "departure_date": return_date,
                }
            )
        return slices

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return ranked :class:`FlightItem` offers; ``[]`` on any failure.

        ``kinds`` is accepted for interface parity but ignored — every
        Duffel result is a flight. Route + date come from ``filters``.
        """
        if not self._api_key:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel", "upstream_status": None, "reason": "no_credentials"},
            )
            return []

        filters = filters if isinstance(filters, dict) else {}
        slices = self._build_slices(filters)
        if slices is None:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": None,
                    "reason": "missing_search_params",
                },
            )
            return []

        adults = filters.get("adults")
        passenger_count = adults if isinstance(adults, int) and adults > 0 else 1
        passengers = [{"type": "adult"} for _ in range(passenger_count)]
        request_data: dict[str, Any] = {"slices": slices, "passengers": passengers}
        cabin_class = filters.get("cabin_class")
        if isinstance(cabin_class, str) and cabin_class:
            request_data["cabin_class"] = cabin_class

        offer_request_id = await self._create_offer_request(request_data)
        if offer_request_id is None:
            return []

        limit = filters.get("limit")
        offers = await self._list_offers(
            offer_request_id,
            limit=limit if isinstance(limit, int) and limit > 0 else 50,
        )

        results: list[InventoryItem] = []
        for offer in offers:
            try:
                results.append(normalize_duffel_offer(offer))
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "duffel",
                        "source_id": offer.get("id") if isinstance(offer.get("id"), str) else None,
                        "reason": exc.__class__.__name__,
                    },
                )
                continue

        logger.info(
            "inventory.provider.search",
            extra={"source": "duffel", "keyword": keyword, "result_count": len(results)},
        )
        return results

    async def _create_offer_request(self, request_data: dict[str, Any]) -> str | None:
        """POST an offer request; return its id, or ``None`` on any failure."""
        url = f"{self._base_url}/air/offer_requests"
        try:
            resp = await self._client.post(
                url,
                params={"return_offers": "false"},
                json={"data": request_data},
                headers=self._headers(),
            )
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel", "upstream_status": None, "reason": "timeout"},
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return None

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            return None

        try:
            body = resp.json()
        except ValueError:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return None

        offer_request_id = _as_dict(_as_dict(body).get("data")).get("id")
        if not isinstance(offer_request_id, str) or not offer_request_id:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "missing_offer_request_id",
                },
            )
            return None
        return offer_request_id

    async def _list_offers(self, offer_request_id: str, *, limit: int) -> list[dict[str, Any]]:
        """GET offers for a request; ``[]`` on any failure."""
        url = f"{self._base_url}/air/offers"
        params = {
            "offer_request_id": offer_request_id,
            "sort": "total_amount",
            "limit": str(limit),
        }
        try:
            resp = await self._client.get(url, params=params, headers=self._headers())
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            return []

        try:
            body = resp.json()
        except ValueError:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return []

        data = _as_dict(body).get("data")
        if not isinstance(data, list):
            return []
        return [offer for offer in data if isinstance(offer, dict)]

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch a single offer by id.

        Duffel exposes detail at ``GET /air/offers/{id}``. On 404 we return
        ``None``; on any other failure we raise :class:`ProviderUpstreamError`
        so the router can distinguish "not found" from "upstream broken".
        Note: Duffel offers expire (minutes), so a stale id legitimately 404s.
        """
        if not self._api_key:
            raise ProviderUpstreamError("duffel_no_credentials")
        url = f"{self._base_url}/air/offers/{source_id}"
        try:
            resp = await self._client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "duffel", "upstream_status": None, "reason": "timeout"},
            )
            raise ProviderUpstreamError("duffel_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("duffel_detail_network_error") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "duffel",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            raise ProviderUpstreamError(
                "duffel_detail_upstream_error", status_code=resp.status_code
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderUpstreamError("duffel_detail_invalid_json") from exc

        offer = _as_dict(body).get("data")
        if not isinstance(offer, dict):
            raise ProviderUpstreamError("duffel_detail_missing_body")

        try:
            return normalize_duffel_offer(offer)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={
                    "source": "duffel",
                    "source_id": source_id,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("duffel_detail_malformed") from exc
