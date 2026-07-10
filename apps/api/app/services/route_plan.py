"""Google Routes (computeRoutes) client for the agent's route brochure.

The agent presents an A→B journey as a drawer surface; the geometry and
timings must come from a real routing engine, and the Google key must never
leave the backend — so the agent tool calls ``POST /agent/route`` and this
module makes the one upstream call. Origin / destination / waypoints are
loose address strings (Routes accepts them directly; no geocoding step).

Authenticates with ``google_places_api_key`` (one Google key, Routes API
enabled on it) against ``google_routes_base_url``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

logger = logging.getLogger("ov_black.services.route_plan")

_TRAVEL_MODES = {
    "drive": "DRIVE",
    "walk": "WALK",
    "bicycle": "BICYCLE",
    "transit": "TRANSIT",
}

_FIELD_MASK = ",".join(
    (
        "routes.duration",
        "routes.distanceMeters",
        "routes.polyline.encodedPolyline",
        "routes.legs.duration",
        "routes.legs.distanceMeters",
        "routes.legs.startLocation",
        "routes.legs.endLocation",
    )
)

_TIMEOUT_SECONDS = 10.0


class RoutePlanError(Exception):
    """Upstream failure or unusable response from computeRoutes."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RouteLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_meters: int
    duration_seconds: int
    start_lat: float | None = None
    start_lng: float | None = None
    end_lat: float | None = None
    end_lng: float | None = None


class RoutePlan(BaseModel):
    """One computed route, shaped for the browser's route surface."""

    model_config = ConfigDict(extra="forbid")

    origin: str
    destination: str
    waypoints: list[str] = Field(default_factory=list)
    mode: str
    distance_meters: int
    duration_seconds: int
    encoded_polyline: str
    legs: list[RouteLeg] = Field(default_factory=list)


def _duration_seconds(raw: Any) -> int:
    """Parse the protobuf-JSON duration shape (``"3600s"``) to whole seconds."""
    if isinstance(raw, str) and raw.endswith("s"):
        try:
            return int(float(raw[:-1]))
        except ValueError:
            return 0
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return int(raw)
    return 0


def _lat_lng(node: Any) -> tuple[float | None, float | None]:
    if not isinstance(node, dict):
        return None, None
    lat_lng = node.get("latLng")
    if not isinstance(lat_lng, dict):
        return None, None
    lat = lat_lng.get("latitude")
    lng = lat_lng.get("longitude")
    return (
        float(lat) if isinstance(lat, int | float) and not isinstance(lat, bool) else None,
        float(lng) if isinstance(lng, int | float) and not isinstance(lng, bool) else None,
    )


def _leg(raw: dict[str, Any]) -> RouteLeg:
    start_lat, start_lng = _lat_lng(raw.get("startLocation"))
    end_lat, end_lng = _lat_lng(raw.get("endLocation"))
    distance = raw.get("distanceMeters")
    return RouteLeg(
        distance_meters=distance if isinstance(distance, int) else 0,
        duration_seconds=_duration_seconds(raw.get("duration")),
        start_lat=start_lat,
        start_lng=start_lng,
        end_lat=end_lat,
        end_lng=end_lng,
    )


async def compute_route(
    *,
    origin: str,
    destination: str,
    waypoints: list[str] | None = None,
    mode: str = "drive",
    settings: Settings,
    client: httpx.AsyncClient,
) -> RoutePlan:
    """Compute one route; raise :class:`RoutePlanError` on any unusable outcome.

    Reasons: ``routes_not_configured`` (no key), ``invalid_mode``,
    ``route_not_found`` (Google returned no route — unroutable pair),
    ``route_upstream_error`` (network / non-2xx / malformed body).
    """
    if not settings.google_places_api_key:
        raise RoutePlanError("routes_not_configured")
    travel_mode = _TRAVEL_MODES.get(mode)
    if travel_mode is None:
        raise RoutePlanError("invalid_mode")

    clean_waypoints = [w.strip() for w in (waypoints or []) if w.strip()]
    body: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
        "languageCode": "en-US",
        "units": "METRIC",
    }
    if clean_waypoints:
        body["intermediates"] = [{"address": w} for w in clean_waypoints]

    url = f"{settings.google_routes_base_url}/directions/v2:computeRoutes"
    try:
        resp = await client.post(
            url,
            json=body,
            headers={
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "route_plan.upstream_error",
            extra={"reason": exc.__class__.__name__, "upstream_status": None},
        )
        raise RoutePlanError("route_upstream_error") from exc

    if resp.status_code >= 400:
        logger.warning(
            "route_plan.upstream_error",
            extra={"reason": "non_2xx", "upstream_status": resp.status_code},
        )
        raise RoutePlanError("route_upstream_error")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RoutePlanError("route_upstream_error") from exc

    routes = payload.get("routes") if isinstance(payload, dict) else None
    first = routes[0] if isinstance(routes, list) and routes else None
    if not isinstance(first, dict):
        raise RoutePlanError("route_not_found")

    polyline = first.get("polyline")
    encoded = polyline.get("encodedPolyline") if isinstance(polyline, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise RoutePlanError("route_not_found")

    distance = first.get("distanceMeters")
    raw_legs = first.get("legs")
    return RoutePlan(
        origin=origin,
        destination=destination,
        waypoints=clean_waypoints,
        mode=mode,
        distance_meters=distance if isinstance(distance, int) else 0,
        duration_seconds=_duration_seconds(first.get("duration")),
        encoded_polyline=encoded,
        legs=[_leg(leg) for leg in raw_legs if isinstance(leg, dict)]
        if isinstance(raw_legs, list)
        else [],
    )
