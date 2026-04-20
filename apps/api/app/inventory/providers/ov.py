"""Outdoor Voyage ``InventoryProvider`` adapter.

Hits the public OV search + detail endpoints, maps each
``Adventures.Entry`` to an :class:`ExperienceItem`, and translates upstream
failures into log + empty-list (search) or typed error (get_detail) so
router code never sees raw ``httpx`` exceptions.

Design notes:
- One ``httpx.AsyncClient`` per provider instance. Tests swap it for one
  backed by ``httpx.MockTransport`` so the suite stays offline.
- ``normalize_ov_entry`` is a pure function against the recorded fixture
  shape at ``tests/fixtures/ov_search_como.json``. Any field we skip here
  flows through in ``raw`` so a later agent can re-normalize without
  re-hitting the network.
- Timeouts / 5xx are *not* escalated on ``search()`` — the UI-side is a
  best-effort aggregation across providers and one slow source should not
  blank the whole result. ``get_detail()`` treats 404 as "not found" and
  raises :class:`ProviderUpstreamError` on anything else.
- ``OV_API_KEY`` is forwarded as ``x-api-key`` when present but never
  logged (``repr=False`` on the settings field).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import (
    ExperienceItem,
    InventoryItem,
    Location,
    Price,
    Range,
)

logger = logging.getLogger("ov_black.inventory.ov")


class ProviderUpstreamError(Exception):
    """Raised by ``get_detail`` when OV returns a non-404 upstream error.

    The router layer maps this to HTTP 502 (bad gateway) so the caller sees
    an unambiguous "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


_DEFAULT_TIMEOUT = httpx.Timeout(5.0)


def _extract_photos(entry: dict[str, Any]) -> list[str]:
    """Return hero-first image URLs from an OV entry.

    ``coverImage`` wins the first slot when present; remaining images
    come from ``images[]`` ordered by their ``index`` field (OV is
    already sorted, but we defend against shuffled fixtures).
    """
    photos: list[str] = []
    cover = entry.get("coverImage")
    if isinstance(cover, dict):
        url = cover.get("accessUrl")
        if isinstance(url, str) and url:
            photos.append(url)
    images = entry.get("images") or []
    if isinstance(images, list):
        ordered = sorted(
            (img for img in images if isinstance(img, dict)),
            key=lambda img: img.get("index") if isinstance(img.get("index"), int) else 0,
        )
        for img in ordered:
            url = img.get("accessUrl")
            if isinstance(url, str) and url and url not in photos:
                photos.append(url)
    return photos


def _extract_price(entry: dict[str, Any]) -> Price | None:
    mp = entry.get("minPrice")
    if not isinstance(mp, dict):
        return None
    amount = mp.get("amount")
    currency = mp.get("currency")
    # OV quotes amounts in minor units (exponent=2 ⇒ cents). Normalize to
    # a major-unit float so downstream UI doesn't need to know the vendor
    # quirk. If exponent is missing, fall back to treating the value as
    # already a major amount.
    currency_code: str | None = None
    exponent = 2
    if isinstance(currency, dict):
        code = currency.get("code")
        if isinstance(code, str):
            currency_code = code
        exp = currency.get("exponent")
        if isinstance(exp, int) and exp >= 0:
            exponent = exp
    elif isinstance(currency, str):
        currency_code = currency
    major: float | None = None
    if isinstance(amount, (int, float)):
        major = float(amount) / (10**exponent)
    if major is None and currency_code is None:
        return None
    return Price(amount_min=major, amount_max=major, currency=currency_code)


def _extract_location(entry: dict[str, Any]) -> Location | None:
    loc = entry.get("location")
    if not isinstance(loc, dict):
        return None
    lat = loc.get("lat")
    lng = loc.get("lng")
    place = loc.get("place")
    country = loc.get("country")
    country_name: str | None = None
    if isinstance(country, dict):
        name = country.get("name")
        if isinstance(name, str):
            country_name = name
    label: str | None = None
    if isinstance(place, str) and place:
        label = f"{place}, {country_name}" if country_name else place
    elif country_name:
        label = country_name
    return Location(
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
        label=label,
    )


def _extract_range(entry: dict[str, Any], key: str) -> Range | None:
    r = entry.get(key)
    if not isinstance(r, dict):
        return None
    lo = r.get("min")
    hi = r.get("max")
    if lo is None and hi is None:
        return None
    return Range(
        min=float(lo) if isinstance(lo, (int, float)) else None,
        max=float(hi) if isinstance(hi, (int, float)) else None,
    )


def _extract_tags(entry: dict[str, Any]) -> list[str]:
    activities = entry.get("activities") or []
    if not isinstance(activities, list):
        return []
    tags: list[str] = []
    for act in activities:
        if isinstance(act, dict):
            name = act.get("name")
            if isinstance(name, str) and name:
                tags.append(name)
    return tags


def normalize_ov_entry(entry: dict[str, Any]) -> ExperienceItem:
    """Map one OV ``Adventures.Entry`` to an :class:`ExperienceItem`.

    Pure function over the wire shape. Raises
    :class:`pydantic.ValidationError` on a partial/malformed entry; callers
    (``OVProvider.search``) catch that and skip the offending item.
    """
    source_id = entry.get("id")
    if not isinstance(source_id, str) or not source_id:
        # Pydantic would raise on the empty ``source_id`` anyway, but a
        # dedicated guard keeps the log line meaningful.
        raise ValueError("ov entry missing id")
    title = entry.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError("ov entry missing title")
    return ExperienceItem(
        source="ov",
        source_id=source_id,
        title=title,
        description=entry.get("description") if isinstance(entry.get("description"), str) else None,
        photos=_extract_photos(entry),
        location=_extract_location(entry),
        price=_extract_price(entry),
        editorial_links=[],
        tags=_extract_tags(entry),
        duration_days=_extract_range(entry, "durationDays"),
        difficulty=_extract_range(entry, "difficulty"),
        raw=entry,
    )


class OVProvider(InventoryProvider):
    """Adapter for the Outdoor Voyage public API."""

    source = "ov"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.ov_base_url.rstrip("/")
        self._api_key = self._settings.ov_api_key or None
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"x-api-key": self._api_key}
        return {}

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return matching :class:`ExperienceItem` records; [] on upstream error."""
        params: dict[str, str] = {}
        if keyword:
            params["keyword"] = keyword
        if kinds:
            params["activityKinds[]"] = ",".join(kinds)
        limit = filters.get("limit") if isinstance(filters, dict) else None
        if isinstance(limit, int) and limit > 0:
            params["limit"] = str(limit)

        url = f"{self._base_url}/api/search"
        try:
            resp = await self._client.get(url, params=params, headers=self._headers())
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ov", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "ov",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "ov",
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
                    "source": "ov",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return []

        entries: list[dict[str, Any]] = []
        if isinstance(body, dict):
            for key in ("trips", "extraTrips"):
                items = body.get(key)
                if isinstance(items, list):
                    entries.extend(item for item in items if isinstance(item, dict))

        results: list[InventoryItem] = []
        for entry in entries:
            try:
                results.append(normalize_ov_entry(entry))
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "ov",
                        "source_id": entry.get("id") if isinstance(entry.get("id"), str) else None,
                        "reason": exc.__class__.__name__,
                    },
                )
                continue

        logger.info(
            "inventory.provider.search",
            extra={
                "source": "ov",
                "keyword": keyword,
                "result_count": len(results),
            },
        )
        return results

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch a single trip by id.

        OV exposes detail at ``GET /api/adventure/{id}``. On 404 we return
        ``None``; on any other failure we raise :class:`ProviderUpstreamError`
        so the router can distinguish "not found" from "upstream broken".
        """
        url = f"{self._base_url}/api/adventure/{source_id}"
        try:
            resp = await self._client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "ov", "upstream_status": None, "reason": "timeout"},
            )
            raise ProviderUpstreamError("ov_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "ov",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            raise ProviderUpstreamError("ov_detail_network_error") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "ov",
                    "upstream_status": resp.status_code,
                    "reason": "non_2xx",
                },
            )
            raise ProviderUpstreamError(
                "ov_detail_upstream_error",
                status_code=resp.status_code,
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderUpstreamError("ov_detail_invalid_json") from exc

        # Shape observed in voyage-site: { success: bool, data: Adventure }.
        entry: dict[str, Any] | None = None
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict):
                entry = data
            elif isinstance(body.get("id"), str):
                entry = body
        if entry is None:
            raise ProviderUpstreamError("ov_detail_missing_body")

        try:
            return normalize_ov_entry(entry)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={"source": "ov", "source_id": source_id, "reason": exc.__class__.__name__},
            )
            raise ProviderUpstreamError("ov_detail_malformed") from exc
