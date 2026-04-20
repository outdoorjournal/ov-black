"""Inventory provider abstraction: ABC, registry, and ambient context.

A ``InventoryProvider`` adapts a single upstream source (OV, mock, a
future third-party) to the shared ``InventoryItem`` shape. The registry
is a simple source→provider dispatch table with a parallel fan-out
(``search_all``) for multi-source queries.

``get_registry()`` returns an empty, lru-cached singleton. Default
providers are registered by ``app.main`` at startup — *not* here — so
tests can construct isolated registries without reaching into module
globals.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

from app.inventory.schemas import InventoryItem

logger = logging.getLogger("ov_black.inventory")


class UnknownSourceError(LookupError):
    """Raised when a registry lookup targets a source that isn't registered.

    Router code maps this to HTTP 400 so the client sees a deterministic
    reason rather than a 500.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(f"unknown inventory source: {source!r}")


@dataclass(frozen=True, slots=True)
class InventoryCtx:
    """Ambient per-call context threaded through provider methods.

    Kept thin on purpose — expand when agent identity lands in S04
    (AgentCore will pass a service-identity header that maps to
    ``actor_kind='agent'``).
    """

    actor_kind: str = "system"
    actor_id: str | None = None


class InventoryProvider(ABC):
    """Adapter interface that every upstream source implements.

    Subclasses MUST set a class-level ``source`` string (e.g. ``"ov"``,
    ``"mock"``). The registry uses that value as the lookup key.
    """

    source: str

    @abstractmethod
    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]: ...

    @abstractmethod
    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None: ...


class InventoryProviderRegistry:
    """Source→provider dispatch table with a parallel fan-out helper."""

    def __init__(self) -> None:
        self._by_source: dict[str, InventoryProvider] = {}

    def register(self, provider: InventoryProvider) -> None:
        self._by_source[provider.source] = provider
        logger.info("inventory.registry.register", extra={"source": provider.source})

    def get(self, source: str) -> InventoryProvider:
        try:
            return self._by_source[source]
        except KeyError as exc:
            raise UnknownSourceError(source) from exc

    def enabled_sources(self) -> list[str]:
        # dict preserves insertion order — callers rely on registration order
        # so tests and logs are deterministic.
        return list(self._by_source.keys())

    async def search_all(
        self,
        *,
        sources: list[str] | None,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        """Fan out a search across sources and return a stably-sorted list.

        ``sources=None`` means "every enabled source". Unknown sources
        raise ``UnknownSourceError`` so the caller fails fast instead of
        silently dropping a requested upstream.
        """
        selected: list[InventoryProvider]
        if sources is None:
            selected = list(self._by_source.values())
        else:
            selected = [self.get(s) for s in sources]

        if not selected:
            return []

        results = await asyncio.gather(
            *(
                provider.search(
                    kinds=kinds, keyword=keyword, filters=filters, ctx=ctx
                )
                for provider in selected
            )
        )
        flattened: list[InventoryItem] = [item for batch in results for item in batch]
        flattened.sort(key=lambda item: (item.source, item.source_id))
        return flattened


@lru_cache(maxsize=1)
def get_registry() -> InventoryProviderRegistry:
    """Process-wide registry singleton.

    Returned empty — ``app.main`` wires the default providers at startup.
    Tests should construct ``InventoryProviderRegistry()`` directly
    rather than mutating this singleton.
    """
    return InventoryProviderRegistry()
