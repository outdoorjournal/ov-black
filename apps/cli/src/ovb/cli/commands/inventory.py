"""`ovb inventory` — search live providers and inspect a single item."""

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of
from ovb.transport import QueryValue

app = typer.Typer(help="Inventory: search providers (flights/hotels/meals/experiences).")


@app.command("search")
def search(
    ctx: typer.Context,
    source: list[str] = typer.Option([], "--source", help="Limit to provider(s)."),
    kinds: list[str] = typer.Option([], "--kind", help="flight|hotel|meal|experience|…"),
    keyword: str | None = typer.Option(None, "--keyword", "-q"),
    limit: int | None = typer.Option(None, "--limit"),
    # flights
    origin: str | None = typer.Option(None, "--origin"),
    destination: str | None = typer.Option(None, "--destination"),
    departure_date: str | None = typer.Option(None, "--departure-date"),
    return_date: str | None = typer.Option(None, "--return-date"),
    cabin_class: str | None = typer.Option(None, "--cabin-class"),
    adults: int | None = typer.Option(None, "--adults"),
    # hotels
    region_id: str | None = typer.Option(None, "--region-id"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    checkin: str | None = typer.Option(None, "--checkin"),
    checkout: str | None = typer.Option(None, "--checkout"),
    residency: str | None = typer.Option(None, "--residency"),
    currency: str | None = typer.Option(None, "--currency"),
    # places bias
    near_lat: float | None = typer.Option(None, "--near-lat"),
    near_lng: float | None = typer.Option(None, "--near-lng"),
    radius_m: int | None = typer.Option(None, "--radius-m"),
    # OV adventures
    regions: list[str] = typer.Option(
        [], "--region", help="Adventure continent (OV): Europe|Asia|Africa|…"
    ),
    activity_kinds: list[str] = typer.Option(
        [], "--activity-kind", help="OV kind: Air|Land|Water|Motor|Snow|Lodging"
    ),
    activities: list[str] = typer.Option(
        [], "--activity", help="OV activity name, e.g. Hiking, Rafting."
    ),
    min_price: int | None = typer.Option(None, "--min-price"),
    max_price: int | None = typer.Option(None, "--max-price"),
    min_difficulty: int | None = typer.Option(None, "--min-difficulty"),
    max_difficulty: int | None = typer.Option(None, "--max-difficulty"),
    page: int | None = typer.Option(None, "--page", help="OV result page (9/page)."),
) -> None:
    """Search inventory across enabled providers (params mirror the API)."""
    state = state_of(ctx)
    params: dict[str, QueryValue] = {
        "source": source or None,
        "kinds": kinds or None,
        "keyword": keyword,
        "limit": limit,
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "cabin_class": cabin_class,
        "adults": adults,
        "region_id": region_id,
        "latitude": latitude,
        "longitude": longitude,
        "checkin": checkin,
        "checkout": checkout,
        "residency": residency,
        "currency": currency,
        "near_lat": near_lat,
        "near_lng": near_lng,
        "radius_m": radius_m,
        "regions": regions or None,
        "activity_kinds": activity_kinds or None,
        "activities": activities or None,
        "min_price": min_price,
        "max_price": max_price,
        "min_difficulty": min_difficulty,
        "max_difficulty": max_difficulty,
        "page": page,
    }
    params = {k: v for k, v in params.items() if v is not None}
    res = run_op(ctx, lambda ovb: ovb.search_inventory(params=params))
    render.emit(state.json_mode, res, lambda: render.inventory_table(res))


@app.command("get")
def get(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Provider source."),
    source_id: str = typer.Argument(..., help="Provider item id."),
) -> None:
    """Fetch one inventory item's detail."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.inventory_detail(source, source_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel(f"{source}/{source_id}", res))
