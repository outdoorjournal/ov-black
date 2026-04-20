"""Public surface for the inventory provider abstraction.

Callers import from ``app.inventory`` directly — the module layout
(``schemas.py``, ``registry.py``) is an implementation detail.
"""

from app.inventory.registry import (
    InventoryCtx,
    InventoryProvider,
    InventoryProviderRegistry,
    UnknownSourceError,
    get_registry,
)
from app.inventory.schemas import InventoryItem

__all__ = [
    "InventoryCtx",
    "InventoryItem",
    "InventoryProvider",
    "InventoryProviderRegistry",
    "UnknownSourceError",
    "get_registry",
]
