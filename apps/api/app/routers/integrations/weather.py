"""Weather integration — STUB.

Returns a deterministic-but-realistic forecast keyed off the
day-of-year + lat hash so the same lat/lng/date always produces the
same answer (lets demo agents reason about a stable "forecast" without
flicker between calls). Live integration would proxy a real provider
(Open-Meteo / WeatherKit / similar) and cache.
"""

from __future__ import annotations

import hashlib
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser, require_user

router = APIRouter(prefix="/integrations/weather", tags=["integrations"])


class WeatherForecast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float
    lng: float
    date: date
    condition: str
    emoji: str
    temp_c_high: float
    temp_c_low: float
    precipitation_chance: float
    summary: str


_CONDITIONS: list[tuple[str, str]] = [
    ("Sunny", "☀"),
    ("Partly cloudy", "⛅"),
    ("Cloudy", "☁"),
    ("Light rain", "🌦"),
    ("Rain", "🌧"),
    ("Thunder", "⛈"),
    ("Snow", "🌨"),
    ("Mist", "🌫"),
]


def _deterministic_pick(seed: str, n: int) -> int:
    """Stable in-band index from a string. Same seed → same answer."""
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    return h[0] % n


@router.get(
    "/forecast",
    response_model=WeatherForecast,
    summary="Forecast for lat/lng + date (stub).",
)
async def forecast(
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
    date_param: date = Query(alias="date"),
    _user: AuthenticatedUser = Depends(require_user),
) -> WeatherForecast:
    """Stable canned forecast. Output is identical across calls so
    demo flows ("show me a free-time card with weather advice") don't
    flicker between requests.
    """
    seed = f"{lat:.2f}|{lng:.2f}|{date_param.isoformat()}"
    pick = _deterministic_pick(seed, len(_CONDITIONS))
    condition, emoji = _CONDITIONS[pick]
    base_high = 14.0 + (pick * 2.7)
    base_low = base_high - 6.0
    return WeatherForecast(
        lat=lat,
        lng=lng,
        date=date_param,
        condition=condition,
        emoji=emoji,
        temp_c_high=round(base_high, 1),
        temp_c_low=round(base_low, 1),
        precipitation_chance=round((pick % 5) * 0.18, 2),
        summary=(
            f"{condition} with daytime highs near {round(base_high)}°C; "
            f"mornings around {round(base_low)}°C."
        ),
    )
