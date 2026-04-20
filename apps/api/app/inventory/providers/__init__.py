"""Concrete ``InventoryProvider`` implementations.

Each submodule ships one adapter; ``app.main`` decides which ones to
register at startup. Tests that want isolation build their own
``InventoryProviderRegistry`` and register adapters directly.
"""
