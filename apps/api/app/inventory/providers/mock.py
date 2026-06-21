"""In-memory ``InventoryProvider`` driven by a committed JSON fixture.

The mock adapter exists to prove the abstraction is source-agnostic: its
fixture ships ``InventoryItem`` dicts in the already-normalized shape, so
loading one just validates it through the Pydantic union. That means
feature work can point a request at ``source='mock'`` and get items that
are byte-identical in shape to what OV emits — no conditional branches
downstream.

The fixture is loaded eagerly in ``__init__``: a missing file or an
invalid ``kind`` must fail loudly at startup (or at test construction),
not silently hours later during a search. ``get_registry().register``
calls ``MockProvider()`` during lifespan, so startup will crash before
the ALB marks the task healthy if the fixture drifts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import InventoryItem

logger = logging.getLogger("ov_black.inventory.mock")


DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "mock_inventory.json"
)

_ITEMS_ADAPTER: TypeAdapter[list[InventoryItem]] = TypeAdapter(list[InventoryItem])


def _load_fixture(path: Path) -> list[InventoryItem]:
    """Parse and validate the fixture. Raises on missing file or bad shape."""
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f"mock inventory fixture at {path} must be a JSON array of items")
    # ``validate_python`` surfaces ``ValidationError`` on any bad ``kind`` or
    # missing required field — exactly the loud-startup behavior we want.
    return _ITEMS_ADAPTER.validate_python(payload)


class MockProvider(InventoryProvider):
    """Fixture-backed provider that mirrors the OV adapter's output shape."""

    source = "mock"

    def __init__(self, *, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path or DEFAULT_FIXTURE_PATH
        self._items: list[InventoryItem] = _load_fixture(self._fixture_path)
        logger.info(
            "inventory.mock.loaded",
            extra={
                "source": self.source,
                "fixture_path": str(self._fixture_path),
                "item_count": len(self._items),
            },
        )

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        kinds_set = set(kinds) if kinds else None
        needle = keyword.casefold() if keyword else None

        matches: list[InventoryItem] = []
        for item in self._items:
            if kinds_set is not None and item.kind not in kinds_set:
                continue
            if needle is not None and not _keyword_matches(item, needle):
                continue
            matches.append(item)

        logger.info(
            "inventory.provider.search",
            extra={
                "source": self.source,
                "keyword": keyword,
                "result_count": len(matches),
            },
        )
        return matches

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


def _keyword_matches(item: InventoryItem, needle: str) -> bool:
    """Case-insensitive substring match over title, description, and tags."""
    haystacks: list[str] = [item.title]
    if item.description:
        haystacks.append(item.description)
    haystacks.extend(item.tags)
    return any(needle in h.casefold() for h in haystacks)
