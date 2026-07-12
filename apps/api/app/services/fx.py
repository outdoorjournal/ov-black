"""Currency conversion via exchangerate-api.com v6 (shared key with voyage-site).

Money in the graph is stored in its *native* provider currency — a Greek
supplier quotes EUR, a US one USD (D-COST). To show a traveler a single
comfortable number we convert at read time into their preferred currency.

Rates are pulled per *base* currency from ``/{key}/latest/{base}``, which
returns ``conversion_rates: {TARGET: multiplier}`` — units of TARGET per one
unit of BASE. We cache the whole table per base currency for
``exchange_rate_cache_ttl_seconds`` so a graph read touching many EUR nodes
hits the network at most once per (base, TTL window).

Disabled-by-default posture: when no key is configured (local dev / tests)
:meth:`FxService.convert` returns ``None`` and every caller falls back to the
native currency. Nothing here needs the network to keep the suite green — the
network call lives in :meth:`FxService._fetch_latest`, which tests monkeypatch.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(6.0)


def _norm(code: str | None) -> str | None:
    """ISO 4217 codes are case-insensitive here; normalise to upper, drop blanks."""
    if not code:
        return None
    c = code.strip().upper()
    return c or None


class FxService:
    """Fetches + caches ``base → {target: rate}`` tables and converts amounts.

    One instance is shared process-wide (see :func:`get_fx_service`). The
    cache is a plain dict guarded by a lock so concurrent graph reads for the
    same base don't stampede the upstream API.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        # base_code -> (fetched_at_monotonic, {target: rate})
        self._cache: dict[str, tuple[float, dict[str, Decimal]]] = {}
        # base_code -> wall-clock time the table was fetched (for "rate as of …"
        # display); monotonic can't be turned into a calendar time, so track both.
        self._fetched_wall: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        """False when no API key is set — callers must fall back to native currency."""
        return bool(self._settings.exchange_rates_api_key)

    async def get_rate(self, base: str, target: str) -> Decimal | None:
        """Multiplier to convert one unit of ``base`` into ``target`` (or None).

        Returns ``Decimal(1)`` for an identity conversion, ``None`` when the
        service is disabled or the rate can't be resolved.
        """
        b, t = _norm(base), _norm(target)
        if b is None or t is None:
            return None
        if b == t:
            return Decimal(1)
        if not self.enabled:
            return None
        table = await self._latest(b)
        if table is None:
            return None
        return table.get(t)

    async def convert(self, amount: Decimal, base: str, target: str) -> Decimal | None:
        """Convert ``amount`` (in ``base``) into ``target``; None if unresolved."""
        rate = await self.get_rate(base, target)
        if rate is None:
            return None
        return amount * rate

    def fetched_at(self, base: str) -> datetime | None:
        """Wall-clock time the cached table for ``base`` was last pulled (or None).

        Powers the invoice's "rate as of …" display. ``None`` when nothing has been
        fetched for that base yet (identity conversions never fetch)."""
        b = _norm(base)
        if b is None:
            return None
        return self._fetched_wall.get(b)

    async def _latest(self, base: str) -> dict[str, Decimal] | None:
        """Return the cached ``{target: rate}`` table for ``base``, refreshing on miss."""
        ttl = self._settings.exchange_rate_cache_ttl_seconds
        now = time.monotonic()
        cached = self._cache.get(base)
        if cached is not None and (now - cached[0]) < ttl:
            return cached[1]

        async with self._lock:
            # Re-check under the lock — another coroutine may have filled it.
            cached = self._cache.get(base)
            if cached is not None and (time.monotonic() - cached[0]) < ttl:
                return cached[1]
            table = await self._fetch_latest(base)
            if table is not None:
                self._cache[base] = (time.monotonic(), table)
                self._fetched_wall[base] = datetime.now(UTC)
            elif cached is not None:
                # Upstream hiccup — serve the stale table rather than dropping to native.
                return cached[1]
            return table

    async def _fetch_latest(self, base: str) -> dict[str, Decimal] | None:
        """Hit ``/{key}/latest/{base}`` and parse ``conversion_rates`` (or None)."""
        key = self._settings.exchange_rates_api_key
        url = f"{self._settings.exchange_rate_api_base_url.rstrip('/')}/{key}/latest/{base}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:  # ValueError == bad JSON
            # Never log the URL (it embeds the key). Base code is safe.
            logger.warning("fx.fetch_failed", extra={"base": base, "error": type(exc).__name__})
            return None

        if not isinstance(body, dict) or body.get("result") != "success":
            logger.warning("fx.fetch_unsuccessful", extra={"base": base})
            return None
        rates = body.get("conversion_rates")
        if not isinstance(rates, dict):
            return None
        out: dict[str, Decimal] = {}
        for code, rate in rates.items():
            norm = _norm(code)
            if norm is None:
                continue
            try:
                out[norm] = Decimal(str(rate))
            except (TypeError, ArithmeticError):
                continue
        return out


@lru_cache(maxsize=1)
def get_fx_service() -> FxService:
    """Process-wide singleton so the rate cache is shared across requests."""
    return FxService()
