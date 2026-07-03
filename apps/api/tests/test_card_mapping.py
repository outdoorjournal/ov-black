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
from app.inventory.providers.google_places import normalize_place
from app.inventory.providers.ratehawk import normalize_ratehawk_hotel
from app.inventory.schemas import (
    DestinationItem,
    ExperienceItem,
    FlightItem,
    HotelItem,
    MealItem,
)
from app.schemas.card_attrs import (
    ExperienceCardAttrs,
    FlightCardAttrs,
    HotelCardAttrs,
    MealCardAttrs,
    parse_card_attrs,
)
from app.services import card_mapping as card_mapping_module
from app.services.card_mapping import (
    experience_item_to_card_attrs,
    flight_item_to_card_attrs,
    hotel_item_to_card_attrs,
    inventory_item_to_card_metadata,
    meal_item_to_card_attrs,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "duffel_offers.json"
HOTEL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ratehawk_hotels.json"
PLACES_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_places_searchtext.json"


@pytest.fixture(scope="module")
def flight_item() -> FlightItem:
    offers = json.loads(FIXTURE_PATH.read_text())["data"]
    item = normalize_duffel_offer(offers[0])
    assert isinstance(item, FlightItem)
    return item


@pytest.fixture(scope="module")
def hotel_item() -> HotelItem:
    hotels = json.loads(HOTEL_FIXTURE_PATH.read_text())["data"]["hotels"]
    item = normalize_ratehawk_hotel(hotels[0])
    assert isinstance(item, HotelItem)
    return item


@pytest.fixture(scope="module")
def meal_item() -> MealItem:
    places = json.loads(PLACES_FIXTURE_PATH.read_text())["places"]
    item = normalize_place(places[0])  # Sushi Saito (sushi_restaurant)
    assert isinstance(item, MealItem)
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
    # Duffel-local ISO strings, localized to the airport tz (LAX PDT / HND JST),
    # coerced to tz-aware datetime by Pydantic.
    assert attrs.depart_at == datetime.fromisoformat("2026-07-10T11:05:00-07:00")
    assert attrs.arrive_at == datetime.fromisoformat("2026-07-11T15:40:00+09:00")


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


def test_non_typed_kind_falls_back_to_snapshot() -> None:
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


# ── Hotel (Ratehawk) → HotelCardAttrs ──────────────────────────────────────


def test_hotel_item_to_card_attrs_carries_room_nights_geo(
    hotel_item: HotelItem,
) -> None:
    attrs = hotel_item_to_card_attrs(hotel_item)
    assert isinstance(attrs, HotelCardAttrs)
    assert attrs.kind == "hotel"
    assert attrs.name == "Grand Hotel Tremezzo"
    # Headline reflects the cheapest rate (Prestige room, 2 nights).
    assert attrs.room_type == "Prestige Room"
    assert attrs.bedding == "king bed"
    assert attrs.nights == 2
    # Geo anchor carried from the normalized location.
    assert attrs.location is not None
    assert attrs.location.lat == pytest.approx(45.98765)
    assert attrs.location.label == "Grand Hotel Tremezzo, Lake Como"
    # Lodging spans the night → renderer night band.
    assert attrs.night_bar is True
    # Snapshot chip strip mirrors the seed's hotel card shape.
    assert attrs.snapshot is not None
    assert attrs.snapshot.title == "Grand Hotel Tremezzo"
    assert attrs.snapshot.price == "USD 3,190"


def test_hotel_check_in_out_recompute_nights(hotel_item: HotelItem) -> None:
    # check_in/check_out aren't in the ETG response — the caller threads the
    # search dates, and nights is recomputed from the stay length.
    attrs = hotel_item_to_card_attrs(hotel_item, check_in="2026-09-12", check_out="2026-09-15")
    assert attrs.check_in == datetime.fromisoformat("2026-09-12T00:00:00")
    assert attrs.check_out == datetime.fromisoformat("2026-09-15T00:00:00")
    assert attrs.nights == 3  # 12→15, overriding the 2-night daily_prices count


def test_hotel_metadata_shape_matches_frontend_contract(
    hotel_item: HotelItem,
) -> None:
    meta = inventory_item_to_card_metadata(hotel_item)
    assert meta["kind"] == "hotel"
    assert meta["name"] == "Grand Hotel Tremezzo"
    assert meta["nights"] == 2
    assert meta["night_bar"] is True
    # exclude_none drops unthreaded check-in/out rather than emitting null.
    assert "check_in" not in meta
    assert meta["snapshot"]["price"] == "USD 3,190"


def test_hotel_sparse_item_maps_without_error() -> None:
    # A static-less hotel (humanized-id title, no geo/price) still yields a
    # valid sparse card.
    item = normalize_ratehawk_hotel({"id": "casa_del_lago", "hid": 1})
    attrs = hotel_item_to_card_attrs(item)
    assert attrs.kind == "hotel"
    assert attrs.name == "Casa Del Lago"
    assert attrs.location is None
    assert attrs.nights is None


# ── Meal (Google Places) → MealCardAttrs ───────────────────────────────────


def test_meal_item_to_card_attrs_carries_cuisine_price_geo(
    meal_item: MealItem,
) -> None:
    attrs = meal_item_to_card_attrs(meal_item)
    assert isinstance(attrs, MealCardAttrs)
    assert attrs.kind == "meal"
    # ``sushi_restaurant`` primary type → bare cuisine class.
    assert attrs.cuisine_class == "sushi"
    # Coarse priceLevel → $-symbol (Places has no bookable amount).
    assert attrs.price == "$$$$"
    # Geo anchor carried from the normalized location.
    assert attrs.location is not None
    assert attrs.location.lat == pytest.approx(35.6647321)
    assert attrs.location.label and "Roppongi" in attrs.location.label
    # No table held yet → no seating time / reservation.
    assert attrs.seating_at is None
    assert attrs.reservation_number is None
    # Snapshot chip strip mirrors the seed's meal card shape.
    assert attrs.snapshot is not None
    assert attrs.snapshot.title == "Sushi Saito"
    assert attrs.snapshot.activities == ["sushi"]


def test_meal_metadata_shape_matches_frontend_contract(meal_item: MealItem) -> None:
    meta = inventory_item_to_card_metadata(meal_item)
    assert meta["kind"] == "meal"
    assert meta["cuisine_class"] == "sushi"
    assert meta["price"] == "$$$$"
    # exclude_none drops absent fields (no ambient_image — Places photos need a
    # keyed proxy) rather than emitting null.
    assert "ambient_image" not in meta
    assert "seating_at" not in meta
    assert meta["snapshot"]["location"]


def test_meal_generic_restaurant_has_no_cuisine_class() -> None:
    # A bare ``restaurant`` primary type collapses to no cuisine word.
    item = normalize_place(
        {
            "id": "place_generic",
            "displayName": {"text": "The Corner Bistro"},
            "primaryType": "restaurant",
            "types": ["restaurant", "food"],
            "location": {"latitude": 1.0, "longitude": 2.0},
        }
    )
    assert isinstance(item, MealItem)
    attrs = meal_item_to_card_attrs(item)
    assert attrs.cuisine_class is None
    assert attrs.snapshot is not None
    assert attrs.snapshot.activities == []


# ── POI ``place`` block (rating / hours / contact / map link / photo) ────


@pytest.fixture(scope="module")
def experience_item() -> ExperienceItem:
    places = json.loads(PLACES_FIXTURE_PATH.read_text())["places"]
    item = normalize_place(places[1])  # Fushimi Inari Taisha (tourist_attraction)
    assert isinstance(item, ExperienceItem)
    return item


def test_experience_place_block_carries_rating_hours_contact(
    experience_item: ExperienceItem,
) -> None:
    attrs = experience_item_to_card_attrs(experience_item)
    assert isinstance(attrs, ExperienceCardAttrs)
    assert attrs.kind == "experience"
    assert attrs.snapshot is not None
    assert attrs.snapshot.title == "Fushimi Inari Taisha"
    # The POI enrichment that used to be dropped on the floor.
    assert attrs.place is not None
    assert attrs.place.rating == pytest.approx(4.7)
    assert attrs.place.rating_count and attrs.place.rating_count > 0
    assert attrs.place.hours  # weekday-description lines
    assert attrs.place.website
    # Deep link points at the exact place (coords + place id), keyless.
    assert attrs.place.maps_url is not None
    assert attrs.place.maps_url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert "query_place_id=" in attrs.place.maps_url


def test_meal_place_block_present(meal_item: MealItem) -> None:
    attrs = meal_item_to_card_attrs(meal_item)
    assert attrs.place is not None
    assert attrs.place.rating == pytest.approx(4.6)
    assert attrs.place.maps_url and "query_place_id=" in attrs.place.maps_url


def test_experience_photo_token_minted_from_first_ref(
    experience_item: ExperienceItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The raw photo resource name must never reach a card — only a signed token.
    monkeypatch.setattr(card_mapping_module, "mint_photo_token", lambda ref: f"signed::{ref}")
    attrs = experience_item_to_card_attrs(experience_item)
    assert attrs.place is not None
    assert attrs.place.photo_token == f"signed::{experience_item.photo_refs[0]}"


def test_experience_metadata_round_trips_through_parse_card_attrs(
    experience_item: ExperienceItem,
) -> None:
    # node.metadata IS the card-attrs dump, and the read side re-validates it
    # against the extra="forbid" model — so the ``place`` block must be a
    # declared field, not a stray key.
    meta = inventory_item_to_card_metadata(experience_item)
    assert meta["kind"] == "experience"
    assert meta["place"]["rating"] == pytest.approx(4.7)
    reparsed = parse_card_attrs("experience", meta)
    assert isinstance(reparsed, ExperienceCardAttrs)
    assert reparsed.place is not None
    assert reparsed.place.rating == pytest.approx(4.7)


def test_non_places_experience_stays_on_snapshot_fallback() -> None:
    # An OV-sourced experience carries no POI enrichment and must not grow a
    # (necessarily empty) ``place`` block.
    item = ExperienceItem(
        source="ov",
        source_id="ov-123",
        title="Guided Ridge Hike",
        location=None,
    )
    meta = inventory_item_to_card_metadata(item)
    assert "place" not in meta
    assert meta["snapshot"]["title"] == "Guided Ridge Hike"
