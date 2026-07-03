"""Bokun (Seller) API ``InventoryProvider`` adapter.

Adapts Bokun's REST ``activity`` endpoints to the shared
``InventoryProvider`` seam so ``search_inventory(kinds=['experience'])``
returns normalized :class:`ExperienceItem` records (single-day operator
experiences) alongside OV trips, Duffel flights, etc.

- ``search`` → ``POST /activity.json/search`` (body is a Bokun ``ActivityQuery``;
  the response envelope carries ``items`` — a list of ``SearchResultItem``).
- ``get_detail`` → ``GET /activity.json/{id}`` (a richer ``ActivityDto``).

Both shapes share enough field names (``id``, ``title``, ``excerpt``,
``keyPhoto``/``photos``, price, location) that a single defensive
:func:`normalize_bokun_activity` maps either; the full upstream object rides in
``raw`` for later card mapping / re-normalization.

Design notes (mirrors :mod:`app.inventory.providers.duffel`):

- One ``httpx.AsyncClient`` per provider instance. Tests swap it for one backed
  by ``httpx.MockTransport`` so the suite stays offline.
- Auth is Bokun's HMAC-SHA1 scheme: the string-to-sign is
  ``date + accessKey + METHOD + path`` (path *includes* the query string), the
  date is UTC ``"%Y-%m-%d %H:%M:%S"``, and the base64 HmacSHA1 digest rides in
  ``X-Bokun-Signature`` alongside ``X-Bokun-Date`` / ``X-Bokun-AccessKey``. The
  signed path must byte-match the wire path, so query params are baked into the
  URL string (not passed via ``params=``) to keep httpx from re-encoding them.
- ``search()`` degrades to ``[]`` + a warning on any upstream failure
  (best-effort multi-source aggregation); ``get_detail()`` returns ``None`` on
  404 and raises :class:`BokunUpstreamError` on anything else.
- With no credentials the provider stays registered but every ``search``
  returns ``[]`` + a warning, so a misconfigured deploy degrades instead of
  crashing boot.
- ``bokun_secret_key`` NEVER appears in a header, a log line, or ``raw`` — only
  the derived signature is transmitted (``repr=False`` on the settings field).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
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

logger = logging.getLogger("ov_black.inventory.bokun")


class BokunUpstreamError(Exception):
    """Raised by ``get_detail`` when Bokun returns a non-404 upstream error.

    The router layer maps this to HTTP 502 so the caller sees an unambiguous
    "external dependency failed" signal rather than a 500.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# Experience search hits Bokun's search index — comparable to a simple GET, but
# give it Duffel-like headroom over the OV 5s default for a cold marketplace.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)

# Bokun prices on ``SearchResultItem`` are a bare number in the currency passed
# as the ``currency`` query param; we ask for a stable default and record it.
_DEFAULT_CURRENCY = "USD"
_DEFAULT_LANG = "EN"

# The experience kind this provider emits. When a caller scopes a search to
# specific kinds that don't include this one, we skip the upstream call so
# experiences never leak into (say) a flight-only aggregate search.
_KIND = "experience"


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce ``value`` to a dict, or ``{}`` — keeps extraction defensive."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _non_empty_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _photo_url(photo: Any) -> str | None:
    """Best client-facing URL for a Bokun ``PhotoDto`` (originalUrl, hero-first).

    Bokun serves public image URLs directly (unlike Google Places photo refs),
    so ``originalUrl`` is safe to hand to the browser without a keyed proxy.
    """
    p = _as_dict(photo)
    url = _non_empty_str(p.get("originalUrl"))
    if url:
        return url
    # ``derived`` carries resized variants; fall back to the first one's url.
    for derived in _as_list(p.get("derived")):
        durl = _non_empty_str(_as_dict(derived).get("url"))
        if durl:
            return durl
    return None


def _build_photos(activity: dict[str, Any]) -> list[str]:
    """Hero photo (``keyPhoto``) first, then ``photos``, de-duplicated."""
    urls: list[str] = []
    key_url = _photo_url(activity.get("keyPhoto"))
    if key_url:
        urls.append(key_url)
    for photo in _as_list(activity.get("photos")):
        url = _photo_url(photo)
        if url and url not in urls:
            urls.append(url)
    return urls


def _build_price(activity: dict[str, Any]) -> Price | None:
    """Read a price from the detail (``nextDefaultPriceMoney``) or search shape.

    ``ActivityDto`` carries ``nextDefaultPriceMoney`` (``{amount, currency}``);
    ``SearchResultItem`` carries a bare ``price`` number quoted in the currency
    we requested via the query param. ``nextDefaultPrice`` is the detail-shape
    bare fallback. All best-effort — missing/zero yields ``None``.
    """
    money = _as_dict(activity.get("nextDefaultPriceMoney"))
    amount = _as_float(money.get("amount"))
    currency = _non_empty_str(money.get("currency"))
    if amount is None:
        amount = _as_float(activity.get("price"))
        if amount is None:
            amount = _as_float(activity.get("nextDefaultPrice"))
        if amount is not None and currency is None:
            currency = _DEFAULT_CURRENCY
    if amount is None and currency is None:
        return None
    return Price(amount_min=amount, amount_max=amount, currency=currency)


def _build_location(activity: dict[str, Any]) -> Location | None:
    """Anchor at ``googlePlace`` (detail) or ``location`` (search)."""
    lat: float | None = None
    lng: float | None = None
    city: str | None = None
    country: str | None = None

    google = _as_dict(activity.get("googlePlace"))
    if google:
        center = _as_dict(google.get("geoLocationCenter"))
        lat = _as_float(center.get("lat"))
        lng = _as_float(center.get("lng"))
        city = _non_empty_str(google.get("city"))
        country = _non_empty_str(google.get("country"))

    loc = _as_dict(activity.get("location"))
    if lat is None:
        lat = _as_float(loc.get("latitude"))
    if lng is None:
        lng = _as_float(loc.get("longitude"))
    if city is None:
        city = _non_empty_str(loc.get("city"))
    if country is None:
        country = _non_empty_str(loc.get("countryCode"))

    label_parts = [part for part in (city, country) if part]
    label = ", ".join(label_parts) if label_parts else None
    if lat is None and lng is None and label is None:
        return None
    return Location(lat=lat, lng=lng, label=label)


def _build_tags(activity: dict[str, Any]) -> list[str]:
    """Operator name + keywords + difficulty, de-duplicated, order-stable."""
    tags: list[str] = []
    vendor = _non_empty_str(_as_dict(activity.get("vendor")).get("title"))
    if vendor:
        tags.append(vendor)
    for keyword in _as_list(activity.get("keywords")):
        kw = _non_empty_str(keyword)
        if kw and kw not in tags:
            tags.append(kw)
    return tags


def _build_duration(activity: dict[str, Any]) -> Range | None:
    """Duration in days, if Bokun expresses one (``durationDays``)."""
    days = _as_float(activity.get("durationDays"))
    if days is None or days <= 0:
        return None
    return Range(min=days, max=days)


def _build_difficulty(activity: dict[str, Any]) -> Range | None:
    level = _as_float(activity.get("difficultyLevel"))
    if level is None:
        return None
    return Range(min=level, max=level)


def normalize_bokun_activity(activity: dict[str, Any]) -> ExperienceItem:
    """Map one Bokun activity (search item OR detail dto) to an ExperienceItem.

    Pure function over the wire shape. Raises ``ValueError`` on an activity
    with no id; callers (``BokunProvider.search``) catch that and skip it. The
    full object is preserved in ``raw`` for later card mapping.
    """
    raw_id = activity.get("id")
    # Search ids are strings; detail ids are int64 — coerce to a stable str.
    if isinstance(raw_id, bool) or raw_id is None or raw_id == "":
        raise ValueError("bokun activity missing id")
    source_id = str(raw_id)

    title = _non_empty_str(activity.get("title")) or "Experience"
    description = (
        _non_empty_str(activity.get("description"))
        or _non_empty_str(activity.get("excerpt"))
        or _non_empty_str(activity.get("summary"))
    )

    return ExperienceItem(
        source="bokun",
        source_id=source_id,
        title=title,
        description=description,
        photos=_build_photos(activity),
        location=_build_location(activity),
        price=_build_price(activity),
        editorial_links=[],
        tags=_build_tags(activity),
        duration_days=_build_duration(activity),
        difficulty=_build_difficulty(activity),
        raw=activity,
    )


class BokunProvider(InventoryProvider):
    """Adapter for the Bokun (Seller) REST API."""

    source = "bokun"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.bokun_base_url.rstrip("/")
        self._access_key = self._settings.bokun_access_key or None
        self._secret_key = self._settings.bokun_secret_key or None
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _has_credentials(self) -> bool:
        return bool(self._access_key and self._secret_key)

    def _sign(self, string_to_sign: str) -> str:
        """Base64 HmacSHA1 of the canonical string with the secret key."""
        assert self._secret_key is not None  # guarded by _has_credentials
        digest = hmac.new(self._secret_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    def _signed_headers(self, method: str, path: str, *, with_body: bool) -> dict[str, str]:
        """Build the three Bokun auth headers for ``METHOD path`` (path incl. query).

        ``path`` MUST equal the wire path (query string and all) or the
        signature won't verify. Never log the returned dict — the signature is
        derived from the secret.
        """
        date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        string_to_sign = f"{date}{self._access_key}{method.upper()}{path}"
        headers = {
            "X-Bokun-Date": date,
            "X-Bokun-AccessKey": self._access_key or "",
            "X-Bokun-Signature": self._sign(string_to_sign),
            "Accept": "application/json",
        }
        if with_body:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        return headers

    def _query_suffix(self, filters: dict[str, Any]) -> str:
        """``?lang=..&currency=..`` — baked into the URL so signing byte-matches."""
        lang = _non_empty_str(filters.get("lang")) or _DEFAULT_LANG
        currency = _non_empty_str(filters.get("currency")) or _DEFAULT_CURRENCY
        return f"?lang={lang}&currency={currency}"

    def _build_query(self, keyword: str | None, filters: dict[str, Any]) -> dict[str, Any]:
        """Assemble a Bokun ``ActivityQuery`` body from keyword + filters.

        Bokun's ``textFilter`` is a ``TextFilter`` OBJECT (``{text, searchTitle,
        searchFullText, wildcard, …}``), not a bare string — sending a string is
        a 400. We search title + full text with a wildcard so a loose keyword
        ("tokyo") still matches.
        """
        query: dict[str, Any] = {}
        text = _non_empty_str(keyword) or _non_empty_str(filters.get("textFilter"))
        if text:
            query["textFilter"] = {
                "text": text,
                "searchTitle": True,
                "searchFullText": True,
                "wildcard": True,
            }
        page = filters.get("page")
        if isinstance(page, int) and page > 0:
            query["page"] = page
        page_size = filters.get("pageSize")
        if isinstance(page_size, int) and page_size > 0:
            query["pageSize"] = page_size
        return query

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Return :class:`ExperienceItem` results; ``[]`` on any failure.

        Bokun only yields experiences, so a search scoped to kinds that exclude
        ``experience`` short-circuits to ``[]`` without hitting the upstream.
        """
        if kinds is not None and _KIND not in kinds:
            return []

        if not self._has_credentials:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "bokun", "upstream_status": None, "reason": "no_credentials"},
            )
            return []

        filters = filters if isinstance(filters, dict) else {}
        path = f"/activity.json/search{self._query_suffix(filters)}"
        body = self._build_query(keyword, filters)

        try:
            resp = await self._client.post(
                f"{self._base_url}{path}",
                content=_json_bytes(body),
                headers=self._signed_headers("POST", path, with_body=True),
            )
        except httpx.TimeoutException:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "bokun", "upstream_status": None, "reason": "timeout"},
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "bokun",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            return []

        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "bokun", "upstream_status": resp.status_code, "reason": "non_2xx"},
            )
            return []

        try:
            payload = resp.json()
        except ValueError:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "bokun",
                    "upstream_status": resp.status_code,
                    "reason": "invalid_json",
                },
            )
            return []

        items = _as_list(_as_dict(payload).get("items"))
        results: list[InventoryItem] = []
        for activity in items:
            if not isinstance(activity, dict):
                continue
            try:
                results.append(normalize_bokun_activity(activity))
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "inventory.provider.malformed",
                    extra={
                        "source": "bokun",
                        "source_id": (
                            str(activity.get("id")) if activity.get("id") is not None else None
                        ),
                        "reason": exc.__class__.__name__,
                    },
                )
                continue

        logger.info(
            "inventory.provider.search",
            extra={"source": "bokun", "keyword": keyword, "result_count": len(results)},
        )
        return results

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        """Fetch a single activity by id.

        Bokun exposes detail at ``GET /activity.json/{id}``. On 404 we return
        ``None``; on any other failure we raise :class:`BokunUpstreamError` so
        the router can distinguish "not found" from "upstream broken".
        """
        if not self._has_credentials:
            raise BokunUpstreamError("bokun_no_credentials")

        path = f"/activity.json/{source_id}{self._query_suffix({})}"
        try:
            resp = await self._client.get(
                f"{self._base_url}{path}",
                headers=self._signed_headers("GET", path, with_body=False),
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "bokun", "upstream_status": None, "reason": "timeout"},
            )
            raise BokunUpstreamError("bokun_detail_timeout") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "inventory.provider.error",
                extra={
                    "source": "bokun",
                    "upstream_status": None,
                    "reason": exc.__class__.__name__,
                },
            )
            raise BokunUpstreamError("bokun_detail_network_error") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "inventory.provider.error",
                extra={"source": "bokun", "upstream_status": resp.status_code, "reason": "non_2xx"},
            )
            raise BokunUpstreamError("bokun_detail_upstream_error", status_code=resp.status_code)

        try:
            activity = resp.json()
        except ValueError as exc:
            raise BokunUpstreamError("bokun_detail_invalid_json") from exc

        if not isinstance(activity, dict):
            raise BokunUpstreamError("bokun_detail_missing_body")

        try:
            return normalize_bokun_activity(activity)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "inventory.provider.malformed",
                extra={"source": "bokun", "source_id": source_id, "reason": exc.__class__.__name__},
            )
            raise BokunUpstreamError("bokun_detail_malformed") from exc


def _json_bytes(body: dict[str, Any]) -> bytes:
    """Serialize the request body with no spaces so the wire bytes are stable."""
    return json.dumps(body, separators=(",", ":")).encode()
