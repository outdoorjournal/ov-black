"""Persistent, file-backed cache for inventory provider results.

Live providers (Google Places, Duffel) are slow, rate-limited, and metered.
Caching their normalized ``InventoryItem`` output across calls — explicitly
permitted by the providers' terms for this use — makes repeat builds fast,
keeps the demo working when a provider is briefly down, and avoids re-billing
the same query. The cache key is a hash of the normalized query
(source + kinds + keyword + the search-shaping filters), so two identical
searches hit; an unrelated query misses and goes live.

Storage is plain JSON files under ``INVENTORY_CACHE_DIR`` (default a gitignored
dir beside the app). Each entry stores the serialized items plus a stored-at
stamp so a TTL can expire stale entries; flights default to a short TTL
(offer prices drift) while places effectively never change.

This wraps :func:`app.services.inventory.search_inventory` — it does not
change the live search path used by the search endpoint, agent, or fill
flows; callers opt in by calling :func:`cached_search`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.inventory.registry import InventoryCtx, InventoryProviderRegistry
from app.inventory.schemas import InventoryItem
from app.services.inventory import search_inventory

logger = logging.getLogger("ov_black.inventory.cache")

_ITEM_LIST_ADAPTER: TypeAdapter[list[InventoryItem]] = TypeAdapter(list[InventoryItem])

# Default TTLs (seconds). Places listings are stable; flight offers drift, so
# they get a shorter window. ``None`` means never expire.
_DEFAULT_TTL_SECONDS: dict[str, int | None] = {
    "duffel": 60 * 60 * 24,  # 1 day — offer prices move
    "google_places": 60 * 60 * 24 * 30,  # 30 days — places are stable
}
_FALLBACK_TTL_SECONDS = 60 * 60 * 24 * 7


def _cache_dir() -> Path:
    override = os.environ.get("INVENTORY_CACHE_DIR")
    if override:
        return Path(override)
    # Default: a gitignored dir beside the app package (apps/api/.inventory_cache).
    return Path(__file__).resolve().parents[2] / ".inventory_cache"


def _cache_key(
    *,
    source: str,
    kinds: list[str] | None,
    keyword: str | None,
    filters: dict[str, Any],
) -> str:
    """Stable hash of the query shape. ``limit`` is excluded so a larger
    fetch can still serve a smaller request from the same entry.
    """
    shaped = {k: v for k, v in sorted(filters.items()) if k != "limit"}
    payload = json.dumps(
        {
            "source": source,
            "kinds": sorted(kinds) if kinds else None,
            "keyword": (keyword or "").strip().lower(),
            "filters": shaped,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _is_fresh(stored_at_iso: str, ttl_seconds: int | None) -> bool:
    if ttl_seconds is None:
        return True
    try:
        stored = datetime.fromisoformat(stored_at_iso)
    except ValueError:
        return False
    age = (datetime.now(UTC) - stored).total_seconds()
    return age <= ttl_seconds


async def cached_search(
    registry: InventoryProviderRegistry,
    *,
    source: str,
    kinds: list[str] | None,
    keyword: str | None,
    filters: dict[str, Any],
    ctx: InventoryCtx,
    ttl_seconds: int | None = -1,
    refresh: bool = False,
) -> list[InventoryItem]:
    """Search one provider, serving from disk when a matching entry is fresh.

    ``ttl_seconds=-1`` (default) selects the per-source default TTL. Pass an
    explicit number to override, ``None`` to never expire, or ``refresh=True``
    to force a live fetch (and refresh the entry). On a live-call failure with
    a stale-but-present entry, the stale entry is served rather than raising —
    the cache doubles as a resilience layer.
    """
    effective_ttl = (
        _DEFAULT_TTL_SECONDS.get(source, _FALLBACK_TTL_SECONDS)
        if ttl_seconds == -1
        else ttl_seconds
    )
    key = _cache_key(source=source, kinds=kinds, keyword=keyword, filters=filters)
    path = _cache_dir() / source / f"{key}.json"

    entry: dict[str, Any] | None = None
    if path.exists():
        try:
            entry = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            entry = None

    if not refresh and entry is not None and _is_fresh(entry.get("stored_at", ""), effective_ttl):
        try:
            items = _ITEM_LIST_ADAPTER.validate_python(entry.get("items", []))
            logger.info("inventory.cache.hit", extra={"source": source, "key": key})
            return items
        except Exception:  # noqa: BLE001 — a corrupt entry just forces a live fetch
            logger.info("inventory.cache.corrupt", extra={"source": source, "key": key})

    try:
        items = await search_inventory(
            registry,
            sources=[source],
            kinds=kinds,
            keyword=keyword,
            filters=filters,
            ctx=ctx,
        )
    except Exception:  # noqa: BLE001 — fall back to a stale entry if we have one
        if entry is not None:
            try:
                stale = _ITEM_LIST_ADAPTER.validate_python(entry.get("items", []))
                logger.warning(
                    "inventory.cache.serve_stale_on_error",
                    extra={"source": source, "key": key},
                )
                return stale
            except Exception:  # noqa: BLE001
                pass
        raise

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "stored_at": datetime.now(UTC).isoformat(),
                    "source": source,
                    "keyword": keyword,
                    "items": [it.model_dump(mode="json") for it in items],
                },
                default=str,
            ),
            "utf-8",
        )
        logger.info(
            "inventory.cache.store",
            extra={"source": source, "key": key, "count": len(items)},
        )
    except OSError:
        # A cache write failure must never break the search.
        logger.warning("inventory.cache.write_failed", extra={"source": source, "key": key})

    return items


__all__ = ["cached_search"]
