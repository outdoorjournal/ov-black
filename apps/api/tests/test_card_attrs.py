"""Tests for the per-type card-attribute schemas (Phase 2).

Two layers:

1. **Schema-level guards** — discriminator routing, kind/node_type
   coupling, optional-by-default semantics, sub-model validation
   (lat/lng bounds, energy meter range, time window range).

2. **Real-trip fixture round-trip** — the Japan fixture in
   ``tests/fixtures/japan_itinerary.py`` mirrors a curated subset of
   the production prototype trip. We dump every item through Pydantic
   and re-parse via :func:`parse_card_attrs` to prove the shape the
   service layer would store on ``nodes.metadata`` reads back into the
   same model. If the schema or the fixture drifts the test fails.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.card_attrs import (
    CardAttributes,
    DriveCardAttrs,
    Driver,
    ExperienceCardAttrs,
    FlightCardAttrs,
    GeoPoint,
    HotelCardAttrs,
    MealCardAttrs,
    NoteCardAttrs,
    SubwayCardAttrs,
    SubwayLine,
    SubwayTransfer,
    TimeOfDayWindow,
    TrainCardAttrs,
    TrainStop,
    Vehicle,
    parse_card_attrs,
)
from app.seed_data.japan_itinerary import (
    JAPAN_DAYS,
    all_items,
    metadata_dump,
)


# ── Schema-level guards ────────────────────────────────────────────────


def test_discriminator_routes_by_kind() -> None:
    """parse_card_attrs picks the right model from node_type."""
    assert isinstance(parse_card_attrs("flight", {}), FlightCardAttrs)
    assert isinstance(parse_card_attrs("subway", {}), SubwayCardAttrs)
    assert isinstance(parse_card_attrs("train", {}), TrainCardAttrs)
    assert isinstance(parse_card_attrs("drive", {}), DriveCardAttrs)
    assert isinstance(parse_card_attrs("hotel", {}), HotelCardAttrs)
    assert isinstance(parse_card_attrs("meal", {}), MealCardAttrs)
    assert isinstance(parse_card_attrs("experience", {}), ExperienceCardAttrs)
    assert isinstance(parse_card_attrs("note", {}), NoteCardAttrs)


def test_kind_mismatch_in_payload_raises() -> None:
    """If raw carries a contradictory ``kind`` the discriminator rejects."""
    with pytest.raises(ValidationError):
        # node_type says flight, but raw says hotel — Pydantic's discriminator
        # enforces match because we re-set kind from node_type. parse_card_attrs
        # overwrites raw["kind"], so this only triggers if a caller bypasses
        # the helper. We exercise that path directly.
        from pydantic import TypeAdapter

        TypeAdapter(CardAttributes).validate_python(
            {"kind": "hotel", "iata_from": "HND"}
        )


def test_unknown_kind_raises() -> None:
    """A kind that doesn't match any model is rejected by the union."""
    with pytest.raises(ValidationError):
        parse_card_attrs("not_a_real_kind", {})


def test_all_fields_optional_by_default() -> None:
    """Empty raw → fully empty model with no errors; all fields default."""
    attrs = parse_card_attrs("flight", None)
    assert isinstance(attrs, FlightCardAttrs)
    assert attrs.iata_from is None
    assert attrs.flight_code is None


def test_extra_fields_are_rejected() -> None:
    """``extra='forbid'`` keeps the metadata blob from accumulating cruft."""
    with pytest.raises(ValidationError):
        parse_card_attrs("flight", {"unknown_field": "oops"})


def test_geopoint_lat_lng_bounds_enforced() -> None:
    """Lat must be [-90, 90]; lng must be [-180, 180]."""
    with pytest.raises(ValidationError):
        GeoPoint(lat=91.0, lng=0.0)
    with pytest.raises(ValidationError):
        GeoPoint(lat=0.0, lng=181.0)


def test_experience_energy_required_range_enforced() -> None:
    """Energy meter is 1..5 — enforced so the renderer can trust it."""
    ExperienceCardAttrs(energy_required=1)  # ok
    ExperienceCardAttrs(energy_required=5)  # ok
    with pytest.raises(ValidationError):
        ExperienceCardAttrs(energy_required=0)
    with pytest.raises(ValidationError):
        ExperienceCardAttrs(energy_required=6)


def test_time_of_day_window_bounds_enforced() -> None:
    """Best-window hours must be 0..24; both ends inclusive."""
    TimeOfDayWindow(start_hour=14, end_hour=16)
    with pytest.raises(ValidationError):
        TimeOfDayWindow(start_hour=-1, end_hour=12)
    with pytest.raises(ValidationError):
        TimeOfDayWindow(start_hour=14, end_hour=25)


def test_subway_card_carries_typed_lines_and_transfers() -> None:
    """The signature detail of the subway card is preserved through round-trip."""
    raw = {
        "from_station": "Asakusa",
        "to_station": "Shibuya",
        "lines": [{"name": "Ginza", "agency_color": "#f39700"}],
        "transfers": [{"station": "Omotesando", "line_color": "#9b7cb6"}],
    }
    attrs = parse_card_attrs("subway", raw)
    assert isinstance(attrs, SubwayCardAttrs)
    assert attrs.lines == [SubwayLine(name="Ginza", agency_color="#f39700")]
    assert attrs.transfers == [
        SubwayTransfer(station="Omotesando", line_color="#9b7cb6")
    ]


def test_train_card_stops_are_typed() -> None:
    """TrainStop list of dicts validates into typed sub-models."""
    raw = {
        "train_name": "Hikari",
        "train_number": "635",
        "stops": [
            {"station": "Shinagawa"},
            {"station": "Shin-Yokohama"},
            {"station": "Nagoya"},
        ],
    }
    attrs = parse_card_attrs("train", raw)
    assert isinstance(attrs, TrainCardAttrs)
    assert len(attrs.stops) == 3
    assert all(isinstance(s, TrainStop) for s in attrs.stops)
    assert attrs.stops[0].station == "Shinagawa"


def test_drive_card_nested_vehicle_and_driver() -> None:
    """Driver / Vehicle round-trip from dicts."""
    raw = {
        "vehicle": {"make": "Toyota Alphard", "capacity": 6},
        "driver": {"name": "Mr. Tanaka", "languages": ["ja", "en"]},
        "prior_trip_continuity": True,
    }
    attrs = parse_card_attrs("drive", raw)
    assert isinstance(attrs, DriveCardAttrs)
    assert attrs.vehicle == Vehicle(make="Toyota Alphard", capacity=6)
    assert attrs.driver == Driver(name="Mr. Tanaka", languages=["ja", "en"])
    assert attrs.prior_trip_continuity is True


def test_waiting_card_uuid_field_round_trips() -> None:
    """``whats_next_node_id`` parses from string and dumps back to string."""
    nid = uuid.uuid4()
    attrs = parse_card_attrs(
        "waiting", {"whats_next_node_id": str(nid), "use_this_time_to": ["x"]}
    )
    assert attrs.kind == "waiting"
    dumped = attrs.model_dump(mode="json")
    assert dumped["whats_next_node_id"] == str(nid)


# ── Real-trip fixture round-trip ──────────────────────────────────────


def test_japan_fixture_loads() -> None:
    """Importing the fixture validates every CardAttributes constructor.

    If a per-type schema rejects a real-trip field, the import fails — so
    the fixture itself acts as a smoke test on top of these explicit checks.
    """
    items = all_items()
    assert len(items) > 0
    # Day-level structure preserved.
    assert {d.date for d in JAPAN_DAYS} == {
        "2024-06-20",
        "2024-06-21",
        "2024-06-24",
        "2024-07-04",
    }


def test_japan_fixture_round_trips_through_parse_card_attrs() -> None:
    """Each item dumps to a dict that parse_card_attrs reads back.

    This is the contract the service layer would honor: dump on write,
    parse on read. Drift between them surfaces as a test failure.
    """
    for item in all_items():
        dumped = metadata_dump(item)
        # parse_card_attrs sets kind from node_type; the persisted blob
        # carries kind too, but parse re-applies it from the node row's
        # type column. Both paths must agree.
        kind = item.attrs.kind
        reparsed = parse_card_attrs(kind, dumped)
        assert reparsed.kind == kind, (
            f"kind drift on {item.id_hint}: {reparsed.kind} != {kind}"
        )
        # Re-dump the reparsed model and compare — proves the round-trip
        # is information-preserving for every populated field.
        assert reparsed.model_dump(exclude_none=True, mode="json") == dumped


def test_japan_fixture_covers_phase2_card_kinds() -> None:
    """Sanity: the curated fixture exercises the major card types so any
    Phase 2 consumer (agent prompt, frontend renderer, validations) can
    be smoke-tested against real data.
    """
    kinds = {item.attrs.kind for item in all_items()}
    # We don't need every kind — boat / waiting / drive don't appear in
    # this trip. But the most-used kinds must be present so a failure on
    # any of these surfaces in this single test.
    for required in ("flight", "subway", "train", "hotel", "experience", "meal", "note"):
        assert required in kinds, f"missing {required!r} in Japan fixture"


def test_shinkansen_scenery_callout_preserved() -> None:
    """The Hikari card's Mt. Fuji callout is the train type's signature
    detail — failure here means we lost the Cards Style Guide property
    the schema exists to preserve.
    """
    hikari = next(
        item
        for item in all_items()
        if item.id_hint == "day05-shinkansen"
    )
    assert isinstance(hikari.attrs, TrainCardAttrs)
    assert len(hikari.attrs.scenery_callouts) == 1
    fuji = hikari.attrs.scenery_callouts[0]
    assert fuji.what == "Mt. Fuji"
    assert fuji.side == "right"
    assert fuji.minute_offset == 50
