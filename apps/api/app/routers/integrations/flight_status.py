"""Flight-status integration — STUB.

Returns a canned status payload for known demo flight codes
(``DL275`` / ``DL276`` from the Japan template); anything else is a
404. The agent / Analyze pipeline can call this when the user asks
"is my flight on time?" once the live provider lands.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser, require_user

router = APIRouter(prefix="/integrations/flight-status", tags=["integrations"])


class CannedFlight(TypedDict):
    """Static fixture row for a known demo flight code."""

    iata_from: str
    iata_to: str
    depart_local_time: time
    depart_tz: tzinfo
    arrive_local_time: time
    arrive_tz: tzinfo
    arrive_day_offset: int
    gate: str
    terminal: str
    aircraft: str


class FlightStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_code: str
    flight_date: date
    status: Literal["scheduled", "boarding", "in_air", "landed", "delayed", "cancelled"]
    scheduled_departure: datetime
    scheduled_arrival: datetime
    actual_departure: datetime | None = None
    actual_arrival: datetime | None = None
    gate: str | None = None
    terminal: str | None = None
    delay_minutes: int = 0
    aircraft: str | None = None


_PDT = timezone(timedelta(hours=-7))
_JST = timezone(timedelta(hours=9))


_CANNED: dict[str, CannedFlight] = {
    "DL275": {
        # LAX 15:25 PDT → HND next-day 18:40 JST (≈13h15m).
        "iata_from": "LAX",
        "iata_to": "HND",
        "depart_local_time": time(15, 25),
        "depart_tz": _PDT,
        "arrive_local_time": time(18, 40),
        "arrive_tz": _JST,
        "arrive_day_offset": 1,
        "gate": "A38",
        "terminal": "TBIT",
        "aircraft": "Airbus A350-900",
    },
    "DL276": {
        # HND 17:30 JST → LAX same-day 11:25 PDT (eastbound, gain a day).
        "iata_from": "HND",
        "iata_to": "LAX",
        "depart_local_time": time(15, 25),
        "depart_tz": _JST,
        "arrive_local_time": time(11, 25),
        "arrive_tz": _PDT,
        "arrive_day_offset": 0,
        "gate": "143",
        "terminal": "T2",
        "aircraft": "Airbus A350-900",
    },
}


def _scheduled_pair(canned: CannedFlight, flight_date: date) -> tuple[datetime, datetime]:
    depart_local = datetime.combine(
        flight_date,
        canned["depart_local_time"],
        tzinfo=canned["depart_tz"],
    )
    arrive_local = datetime.combine(
        flight_date + timedelta(days=canned["arrive_day_offset"]),
        canned["arrive_local_time"],
        tzinfo=canned["arrive_tz"],
    )
    return depart_local, arrive_local


@router.get(
    "/{flight_code}",
    response_model=FlightStatus,
    summary="Look up flight status (stub).",
)
async def status(
    flight_code: str,
    flight_date: date = Query(alias="date"),
    _user: AuthenticatedUser = Depends(require_user),
) -> FlightStatus:
    canned = _CANNED.get(flight_code.upper())
    if canned is None:
        raise HTTPException(status_code=404, detail="flight_not_found")
    sched_dep, sched_arr = _scheduled_pair(canned, flight_date)
    return FlightStatus(
        flight_code=flight_code.upper(),
        flight_date=flight_date,
        status="scheduled",
        scheduled_departure=sched_dep,
        scheduled_arrival=sched_arr,
        gate=canned["gate"],
        terminal=canned["terminal"],
        aircraft=canned["aircraft"],
        delay_minutes=0,
    )
