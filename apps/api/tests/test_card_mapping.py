"""Tests for inventory-item → node card metadata mapping.

Proves the chain a Duffel flight rides to render: a raw Duffel offer →
``normalize_duffel_offer`` → :class:`FlightItem` → ``flight_item_to_card_attrs``
→ a valid :class:`FlightCardAttrs` whose dump is the exact ``metadata`` shape
the frontend flight card reads (iata_from/to, flight_code, cabin, depart_at,
arrive_at, from/to_location). Uses the committed, live-validated fixture.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.inventory.providers.duffel import normalize_duffel_offer
from app.inventory.schemas import DestinationItem, FlightItem
from app.schemas.card_attrs import FlightCardAttrs
from app.services.card_mapping import (
    flight_item_to_card_attrs,
    inventory_item_to_card_metadata,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "duffel_offers.json"


@pytest.fixture(scope="module")
def flight_item() -> FlightItem:
    offers = json.loads(FIXTURE_PATH.read_text())["data"]
    item = normalize_duffel_offer(offers[0])
    assert isinstance(item, FlightItem)
    return item


def test_flight_item_to_card_attrs_carries_cabin_times_route(
    flight_item: FlightItem,
) -> None:
    attrs = flight_item_to_card_attrs(flight_item)
    assert isinstance(attrs, FlightCardAttrs)
    assert attrs.kind == "flight"
    assert attrs.iata_from == "LAX"
    assert attrs.iata_to == "HND"
    assert attrs.flight_code == "NH105"
    assert attrs.cabin == "business"
    # Duffel-local ISO strings coerced to datetime by Pydantic.
    assert attrs.depart_at == datetime.fromisoformat("2026-07-10T11:05:00")
    assert attrs.arrive_at == datetime.fromisoformat("2026-07-11T15:40:00")


def test_flight_item_to_card_attrs_builds_airport_geometry(
    flight_item: FlightItem,
) -> None:
    attrs = flight_item_to_card_attrs(flight_item)
    assert attrs.from_location is not None
    assert attrs.from_location.lat == pytest.approx(33.942501)
    assert attrs.from_location.label == "Los Angeles (LAX)"
    assert attrs.to_location is not None
    assert attrs.to_location.lat == pytest.approx(35.553333)
    assert attrs.to_location.label == "Tokyo (HND)"
    # Map anchor is the arrival airport, mirroring the seed.
    assert attrs.location is not None
    assert attrs.location.label == "Tokyo (HND)"


def test_metadata_shape_matches_frontend_contract(flight_item: FlightItem) -> None:
    # node.metadata IS the card-attrs dump (top-level keys, kind discriminator).
    meta = inventory_item_to_card_metadata(flight_item)
    assert meta["kind"] == "flight"
    assert meta["iata_from"] == "LAX"
    assert meta["cabin"] == "business"
    # exclude_none drops absent fields (e.g. seat) rather than emitting null.
    assert "seat" not in meta
    # depart_at/arrive_at serialized as ISO strings the adapter parses.
    assert meta["depart_at"].startswith("2026-07-10T11:05:00")


def test_sparse_offer_maps_without_error() -> None:
    # An offer missing slices/cabin still yields a valid (sparse) card.
    item = normalize_duffel_offer(
        {"id": "off_sparse", "total_amount": "100.00", "total_currency": "USD"}
    )
    attrs = flight_item_to_card_attrs(item)
    assert attrs.kind == "flight"
    assert attrs.iata_from is None
    assert attrs.from_location is None


def test_non_flight_falls_back_to_snapshot() -> None:
    item = DestinationItem(
        source="mock",
        source_id="d1",
        title="Kyoto",
        photos=["https://example.com/kyoto.jpg"],
    )
    meta: dict[str, Any] = inventory_item_to_card_metadata(item)
    assert "kind" not in meta  # snapshot shape, not typed card attrs
    assert meta["snapshot"]["title"] == "Kyoto"
    assert meta["snapshot"]["cover_image"].endswith("kyoto.jpg")
