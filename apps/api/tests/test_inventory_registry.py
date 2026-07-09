"""Unit tests for the inventory provider registry + InventoryItem union.

No adapters are registered here — we construct fresh
``InventoryProviderRegistry`` instances so each test is isolated from
``get_registry()``'s process-wide singleton and from each other.
"""

from __future__ import annotations

import asyncio

import pytest
from app.inventory import (
    InventoryCtx,
    InventoryItem,
    InventoryProvider,
    InventoryProviderRegistry,
    UnknownSourceError,
)
from app.inventory.schemas import ExperienceItem
from pydantic import TypeAdapter, ValidationError


class _FakeProvider(InventoryProvider):
    """Deterministic provider that returns a preset list.

    ``search`` optionally sleeps so the parallel-fan-out test can prove
    ``asyncio.gather`` is actually concurrent (total wall time should be
    close to the MAX of sleeps, not the sum).
    """

    def __init__(
        self,
        source: str,
        items: list[InventoryItem],
        *,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.source = source
        self._items = items
        self._sleep_seconds = sleep_seconds

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        if self._sleep_seconds:
            await asyncio.sleep(self._sleep_seconds)
        return list(self._items)

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        for item in self._items:
            if item.source_id == source_id:
                return item
        return None


def _experience(source: str, source_id: str, title: str) -> ExperienceItem:
    return ExperienceItem(source=source, source_id=source_id, title=title)


def test_register_and_get_round_trip() -> None:
    registry = InventoryProviderRegistry()
    provider = _FakeProvider("ov", [])

    registry.register(provider)

    assert registry.get("ov") is provider


def test_get_unknown_source_raises_typed_error() -> None:
    registry = InventoryProviderRegistry()

    with pytest.raises(UnknownSourceError) as exc_info:
        registry.get("missing")

    assert exc_info.value.source == "missing"
    # Subclass of LookupError so callers can catch the stdlib base too.
    assert isinstance(exc_info.value, LookupError)


def test_enabled_sources_preserves_registration_order() -> None:
    registry = InventoryProviderRegistry()
    registry.register(_FakeProvider("ov", []))
    registry.register(_FakeProvider("mock", []))
    registry.register(_FakeProvider("zebra", []))

    assert registry.enabled_sources() == ["ov", "mock", "zebra"]


async def test_search_all_fans_out_in_parallel_and_stable_sorts() -> None:
    # Each provider sleeps 50ms. Serial execution would take ~150ms+; parallel
    # should finish in ~50–70ms. We assert <120ms to keep the test robust on
    # slow CI while still proving concurrency.
    sleep = 0.05
    ov = _FakeProvider(
        "ov",
        [_experience("ov", "b", "Bormio"), _experience("ov", "a", "Alps")],
        sleep_seconds=sleep,
    )
    mock = _FakeProvider(
        "mock",
        [_experience("mock", "z", "Zermatt"), _experience("mock", "a", "Annapurna")],
        sleep_seconds=sleep,
    )
    third = _FakeProvider(
        "third",
        [_experience("third", "m", "Matterhorn")],
        sleep_seconds=sleep,
    )
    registry = InventoryProviderRegistry()
    registry.register(ov)
    registry.register(mock)
    registry.register(third)

    loop = asyncio.get_running_loop()
    started = loop.time()
    results = await registry.search_all(
        sources=None,
        kinds=None,
        keyword=None,
        filters={},
        ctx=InventoryCtx(),
    )
    elapsed = loop.time() - started

    # Parallel fan-out: total time is close to max(sleep), not 3*sleep.
    assert elapsed < sleep * 3, f"fan-out was not parallel (took {elapsed:.3f}s)"

    # Stable-sorted by (source, source_id).
    assert [(item.source, item.source_id) for item in results] == [
        ("mock", "a"),
        ("mock", "z"),
        ("ov", "a"),
        ("ov", "b"),
        ("third", "m"),
    ]


async def test_search_all_empty_registry_returns_empty_list() -> None:
    registry = InventoryProviderRegistry()

    results = await registry.search_all(
        sources=None,
        kinds=None,
        keyword=None,
        filters={},
        ctx=InventoryCtx(),
    )

    assert results == []


async def test_search_all_with_explicit_sources_routes_only_those() -> None:
    ov = _FakeProvider("ov", [_experience("ov", "1", "Alps")])
    mock = _FakeProvider("mock", [_experience("mock", "1", "Mock")])
    registry = InventoryProviderRegistry()
    registry.register(ov)
    registry.register(mock)

    results = await registry.search_all(
        sources=["mock"],
        kinds=None,
        keyword=None,
        filters={},
        ctx=InventoryCtx(),
    )

    assert [item.source for item in results] == ["mock"]


async def test_search_all_unknown_source_raises() -> None:
    registry = InventoryProviderRegistry()
    registry.register(_FakeProvider("ov", []))

    with pytest.raises(UnknownSourceError):
        await registry.search_all(
            sources=["nope"],
            kinds=None,
            keyword=None,
            filters={},
            ctx=InventoryCtx(),
        )


class _BrokenProvider(_FakeProvider):
    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        raise RuntimeError("boom")


async def test_search_all_detailed_returns_outcomes_in_selection_order() -> None:
    registry = InventoryProviderRegistry()
    registry.register(_FakeProvider("ov", [_experience("ov", "1", "Alps")]))
    registry.register(_FakeProvider("mock", [_experience("mock", "1", "Mock")]))

    outcomes = await registry.search_all_detailed(
        sources=None,
        kinds=None,
        keyword=None,
        filters={},
        ctx=InventoryCtx(),
    )

    assert [o.source for o in outcomes] == ["ov", "mock"]
    assert all(o.error is None for o in outcomes)
    assert all(o.elapsed_ms >= 0 for o in outcomes)
    assert [len(o.items) for o in outcomes] == [1, 1]


async def test_search_all_detailed_captures_provider_error() -> None:
    registry = InventoryProviderRegistry()
    registry.register(_FakeProvider("ov", [_experience("ov", "1", "Alps")]))
    registry.register(_BrokenProvider("broken", []))

    outcomes = await registry.search_all_detailed(
        sources=None,
        kinds=None,
        keyword=None,
        filters={},
        ctx=InventoryCtx(),
    )

    by_source = {o.source: o for o in outcomes}
    assert by_source["ov"].error is None
    assert by_source["ov"].items
    assert by_source["broken"].error == "RuntimeError: boom"
    assert by_source["broken"].items == []


async def test_search_all_detailed_unknown_source_raises() -> None:
    registry = InventoryProviderRegistry()
    registry.register(_FakeProvider("ov", []))

    with pytest.raises(UnknownSourceError):
        await registry.search_all_detailed(
            sources=["nope"],
            kinds=None,
            keyword=None,
            filters={},
            ctx=InventoryCtx(),
        )


def test_inventory_item_discriminator_parses_experience_kind() -> None:
    adapter = TypeAdapter(InventoryItem)

    parsed = adapter.validate_python(
        {
            "kind": "experience",
            "source": "ov",
            "source_id": "trip-42",
            "title": "Como Hike",
        }
    )

    assert isinstance(parsed, ExperienceItem)
    assert parsed.source_id == "trip-42"


def test_inventory_item_discriminator_rejects_unknown_kind() -> None:
    adapter = TypeAdapter(InventoryItem)

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "banana",
                "source": "ov",
                "source_id": "x",
                "title": "y",
            }
        )


def test_inventory_ctx_defaults_and_immutability() -> None:
    ctx = InventoryCtx()
    assert ctx.actor_kind == "system"
    assert ctx.actor_id is None

    # frozen=True + slots=True → FrozenInstanceError on mutation.
    with pytest.raises(Exception):
        ctx.actor_kind = "user"  # type: ignore[misc]
