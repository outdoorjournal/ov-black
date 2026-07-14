"""Harvest a region's hotels from SerpApi (Google Hotels) into a snapshot.

Offline scraper for the ``serp`` inventory provider. It walks a list of
anchor queries (towns around the target region), pages through Google Hotels
via ``next_page_token``, dedups by ``property_token``, clips to a radius so
far-flung matches don't leak in, normalizes each property to a ``HotelItem``,
and writes ``app/inventory/data/serp_hotels.json``. That committed snapshot is
what the ``serp`` provider serves at request time — no key or network needed
once this has run.

Run it from ``apps/api`` (uv-managed, like the rest of the API):

    uv run python scripts/scrape_serp_hotels.py            # default: Mt Olympus
    uv run python scripts/scrape_serp_hotels.py --dry-run  # fetch + report, no write
    uv run python scripts/scrape_serp_hotels.py --max-pages 5 --radius-km 50

The key comes from ``settings.serp_api_key`` (i.e. ``serp_api_key`` in
``apps/api/.env``). Google Hotels requires check-in/check-out dates; they only
affect the quoted nightly rate, so the defaults are a representative 2-night
stay a couple of months out.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter

# Ensure ``app`` is importable when run as a bare script from apps/api.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.inventory.schemas import HotelItem  # noqa: E402
from app.services.analyze_runners.common import haversine_km  # noqa: E402

SERPAPI_URL = "https://serpapi.com/search.json"

OUTPUT_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "inventory" / "data" / "serp_hotels.json"
)

_HOTELS_ADAPTER: TypeAdapter[list[HotelItem]] = TypeAdapter(list[HotelItem])


@dataclass
class Region:
    """A scrape target: anchor queries + a centre/radius to clip results."""

    name: str
    centre: tuple[float, float]
    radius_km: float
    queries: list[str] = field(default_factory=list)


# Mt Olympus base cluster — Litochoro and the towns fanning out along the
# Olympian Riviera and up toward Katerini/Dion. Centre = Litochoro
# (matches app/seed_data/olympus_itinerary.py LITOCHORO).
OLYMPUS = Region(
    name="olympus",
    centre=(40.1008, 22.5011),
    radius_km=40.0,
    queries=[
        "Litochoro, Greece",
        "Plaka Litochorou, Greece",
        "Leptokarya, Pieria, Greece",
        "Paralia Katerini, Greece",
        "Katerini, Greece",
        "Dion, Pieria, Greece",
        "Neos Panteleimonas, Greece",
        "Skotina, Pieria, Greece",
        "Olympian Riviera hotels, Greece",
        "Mount Olympus, Greece hotels",
    ],
)


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def _property_to_hotel(prop: dict[str, Any], *, currency: str) -> HotelItem | None:
    """Normalize one Google Hotels property to a ``HotelItem`` (or ``None``)."""
    token = prop.get("property_token")
    name = prop.get("name")
    gps = prop.get("gps_coordinates") or {}
    lat, lng = gps.get("latitude"), gps.get("longitude")
    if not token or not name or lat is None or lng is None:
        return None

    photos = [
        img["original_image"]
        for img in prop.get("images", [])
        if isinstance(img, dict) and img.get("original_image")
    ][:8]

    rate = prop.get("rate_per_night") or {}
    amount_min = rate.get("extracted_lowest")

    # Trim the raw pass-through: drop the bulky/opaque bits already projected
    # into first-class fields or useless offline (image lists, serpapi links).
    raw = {
        k: v
        for k, v in prop.items()
        if k not in {"images", "serpapi_property_details_link"} and not k.startswith("serpapi_")
    }

    return HotelItem(
        source="serp",
        source_id=str(token),
        title=str(name),
        description=prop.get("description"),
        photos=photos,
        location={"lat": float(lat), "lng": float(lng), "label": str(name)},
        price=(
            {"amount_min": float(amount_min), "currency": currency}
            if isinstance(amount_min, (int, float))
            else None
        ),
        tags=[a for a in prop.get("amenities", []) if isinstance(a, str)][:12],
        stars=prop.get("extracted_hotel_class"),
        rating=_first(prop.get("overall_rating")),
        rating_count=_first(prop.get("reviews")),
        website=prop.get("link"),
        raw=raw,
    )


def _fetch_query(
    client: httpx.Client,
    *,
    query: str,
    api_key: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Page through Google Hotels for one anchor query; return raw properties."""
    props: list[dict[str, Any]] = []
    next_token: str | None = None
    for page in range(1, args.max_pages + 1):
        params: dict[str, Any] = {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": args.check_in,
            "check_out_date": args.check_out,
            "adults": args.adults,
            "currency": args.currency,
            "gl": "us",
            "hl": "en",
            "api_key": api_key,
        }
        if next_token:
            params["next_page_token"] = next_token
        resp = client.get(SERPAPI_URL, params=params, timeout=45.0)
        resp.raise_for_status()
        data = resp.json()
        if err := data.get("error"):
            print(f"    ! {query!r} page {page}: {err}", file=sys.stderr)
            break
        batch = data.get("properties", [])
        props.extend(batch)
        print(f"    {query!r} page {page}: +{len(batch)} properties", file=sys.stderr)
        next_token = (data.get("serpapi_pagination") or {}).get("next_page_token")
        if not next_token:
            break
    return props


def scrape(region: Region, args: argparse.Namespace) -> list[HotelItem]:
    settings = get_settings()
    api_key = settings.serp_api_key
    if not api_key:
        raise SystemExit("serp_api_key is empty — set it in apps/api/.env before scraping.")

    by_token: dict[str, HotelItem] = {}
    clipped = 0
    with httpx.Client() as client:
        for query in region.queries:
            print(f"  → {query}", file=sys.stderr)
            for prop in _fetch_query(client, query=query, api_key=api_key, args=args):
                hotel = _property_to_hotel(prop, currency=args.currency)
                if hotel is None:
                    continue
                loc = hotel.location
                assert loc is not None and loc.lat is not None and loc.lng is not None
                dist = haversine_km(region.centre[0], region.centre[1], loc.lat, loc.lng)
                if dist > args.radius_km:
                    clipped += 1
                    continue
                # Dedup by token — the same hotel surfaces under several anchors.
                by_token.setdefault(hotel.source_id, hotel)

    hotels = sorted(by_token.values(), key=lambda h: (-(h.rating or 0.0), h.title))
    print(
        f"\n  {len(hotels)} unique hotels within {args.radius_km:g} km "
        f"({clipped} clipped as too far)",
        file=sys.stderr,
    )
    return hotels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-in", default="2026-09-15")
    parser.add_argument("--check-out", default="2026-09-17")
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--max-pages", type=int, default=3, help="pages per anchor query")
    parser.add_argument(
        "--radius-km",
        type=float,
        default=OLYMPUS.radius_km,
        help="clip hotels farther than this from the region centre",
    )
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch + report but do not write the file"
    )
    args = parser.parse_args()

    region = OLYMPUS
    region.radius_km = args.radius_km
    hotels = scrape(region, args)

    if args.dry_run:
        for h in hotels[:20]:
            stars = f"{h.stars}★" if h.stars else "  "
            rating = f"{h.rating}" if h.rating else "-"
            print(f"    {stars}  {rating:>3}  {h.title}", file=sys.stderr)
        print(f"\n  dry-run: would write {len(hotels)} hotels to {args.out}", file=sys.stderr)
        return

    payload = _HOTELS_ADAPTER.dump_python(hotels, mode="json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n  wrote {len(hotels)} hotels → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
