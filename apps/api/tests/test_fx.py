"""Unit tests for the FX conversion service (0048).

No network: the upstream fetch (:meth:`FxService._fetch_latest`) is
monkeypatched, so these exercise the rate math, the disabled-when-no-key
posture, identity conversion, and the per-base TTL cache (one fetch serves
repeated conversions off the same base).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
from app.services.fx import FxService


def _settings(*, key: str = "test-key", ttl: int = 3600) -> Settings:
    return Settings(
        exchange_rates_api_key=key,
        exchange_rate_cache_ttl_seconds=ttl,
    )


async def test_disabled_without_key_returns_none() -> None:
    fx = FxService(_settings(key=""))
    assert fx.enabled is False
    assert await fx.convert(Decimal("100"), "EUR", "USD") is None
    assert await fx.get_rate("EUR", "USD") is None


async def test_identity_conversion_needs_no_key() -> None:
    fx = FxService(_settings(key=""))
    # base == target short-circuits to 1 even while disabled.
    assert await fx.get_rate("USD", "usd") == Decimal(1)
    assert await fx.convert(Decimal("42.50"), "USD", "USD") == Decimal("42.50")


async def test_convert_applies_fetched_rate() -> None:
    fx = FxService(_settings())

    async def fake_fetch(base: str) -> dict[str, Decimal]:
        assert base == "EUR"
        return {"USD": Decimal("1.10"), "GBP": Decimal("0.85")}

    fx._fetch_latest = fake_fetch  # type: ignore[method-assign]

    assert await fx.get_rate("EUR", "USD") == Decimal("1.10")
    assert await fx.convert(Decimal("200"), "EUR", "USD") == Decimal("220.00")
    # Unknown target in the table → None (caller falls back to native).
    assert await fx.get_rate("EUR", "JPY") is None


async def test_cache_serves_repeated_conversions_with_one_fetch() -> None:
    fx = FxService(_settings())
    calls = {"n": 0}

    async def counting_fetch(base: str) -> dict[str, Decimal]:
        calls["n"] += 1
        return {"USD": Decimal("1.2")}

    fx._fetch_latest = counting_fetch  # type: ignore[method-assign]

    await fx.convert(Decimal("1"), "EUR", "USD")
    await fx.convert(Decimal("2"), "EUR", "USD")
    await fx.get_rate("EUR", "USD")
    assert calls["n"] == 1  # cached after the first miss


async def test_failed_fetch_yields_none() -> None:
    fx = FxService(_settings())

    async def failing_fetch(base: str) -> None:
        return None

    fx._fetch_latest = failing_fetch  # type: ignore[method-assign]
    assert await fx.convert(Decimal("100"), "EUR", "USD") is None


async def test_normalisation_is_case_insensitive() -> None:
    fx = FxService(_settings())

    async def fake_fetch(base: str) -> dict[str, Decimal]:
        assert base == "EUR"  # lower-cased input normalised before fetch
        return {"USD": Decimal("1.05")}

    fx._fetch_latest = fake_fetch  # type: ignore[method-assign]
    assert await fx.convert(Decimal("10"), "eur", "usd") == Decimal("10.50")


@pytest.mark.parametrize("bad", ["", "  ", None])
async def test_blank_codes_return_none(bad: str | None) -> None:
    fx = FxService(_settings())
    assert await fx.get_rate(bad or "", "USD") is None
