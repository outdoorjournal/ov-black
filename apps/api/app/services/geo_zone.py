"""Location → IANA zone lookup (doc/itin-time.md "Zone acquisition").

A scheduled node needs a real IANA zone; location data is the best acquisition
source when the caller didn't supply one. ``tzfpy`` resolves lat/lng offline
against the timezone-boundary dataset — no network, ~µs per lookup.

Node metadata conventions (mirroring ``kernel/analysis.py``): ground nodes
carry ``location: {lat, lng}``; flights carry ``from_location`` /
``to_location`` per endpoint. Everything here is fail-safe: bad coordinates,
ocean hits (tzfpy answers ``Etc/GMT±N`` there), or lookup errors all resolve
to ``None`` and the caller falls back to the offset's pseudo-zone.
"""

from __future__ import annotations

import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzfpy import get_tz

from app.models.itinerary import Node, NodeType

logger = logging.getLogger("ov_black.geo_zone")


def zone_for_latlng(lat: float, lng: float) -> str | None:
    """The real IANA zone containing the point, or ``None`` when unknown.

    Ocean/no-man's-land answers come back as ``Etc/GMT±N`` fixed offsets —
    those are exactly what the cascade is trying to escape, so they count as
    no answer. The result is validated against the local tzdb before use.
    """
    try:
        zone = get_tz(lng, lat)  # tzfpy speaks (lng, lat)
    except Exception:  # noqa: BLE001 — a lookup failure must never fail a write
        logger.warning("geo_zone.lookup_failed", extra={"lat": lat, "lng": lng})
        return None
    if not zone or zone.startswith("Etc/"):
        return None
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("geo_zone.unknown_zone", extra={"zone": zone})
        return None
    return zone


def _latlng(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    lat, lng = value.get("lat"), value.get("lng")
    if isinstance(lat, int | float) and isinstance(lng, int | float):
        if isinstance(lat, bool) or isinstance(lng, bool):
            return None
        return float(lat), float(lng)
    return None


def node_location_zones(node: Node) -> tuple[str | None, str | None]:
    """(start_zone, end_zone) derived from the node's location metadata.

    Flights are two-endpoint: ``from_location`` zones the departure,
    ``to_location`` the arrival. Everything else happens in one place —
    ``location`` zones both ends.
    """
    metadata = node.metadata_ if isinstance(node.metadata_, dict) else {}
    if node.type is NodeType.flight:
        origin = _latlng(metadata.get("from_location"))
        dest = _latlng(metadata.get("to_location"))
        return (
            zone_for_latlng(*origin) if origin is not None else None,
            zone_for_latlng(*dest) if dest is not None else None,
        )
    where = _latlng(metadata.get("location"))
    if where is None:
        return (None, None)
    zone = zone_for_latlng(*where)
    return (zone, zone)
