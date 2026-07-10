"""Seed a demo itinerary showcasing an OV multi-day adventure as an embedded subgraph.

Builds a 7-day Ethiopia trip around the live Outdoor Voyage "4 Days Simien
Mountain Wildlife Safari": arrival day (flight, transfer, dinner, hotel night)
→ the OV adventure as ONE experience card whose 4-day journey materializes as
subgraph children server-side → a decompression day → departure flight. Every
node is scheduled, so the whole story renders on the Journal spine, with the
adventure card carrying the expandable "journey within".

Run against the local stack (API :8000 + Supabase up; OV enabled in
inventory_providers_enabled):

    cd apps/cli && uv run python scripts/seed_ov_subgraph_demo.py

Idempotent: reuses the demo client AND the demo itinerary (matched by title)
across runs — an existing timeline is wiped (root deletes cascade over
subgraphs and attached notes) and reseeded in place, so the web URL stays
stable while you iterate. Uses the same ovb SDK the e2e suite drives, via the
default (local, admin-minted) profile — pass OVB_PROFILE to target another
stack.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from ovb.config import resolve_profile
from ovb.errors import ApiError
from ovb.sdk import Ovb

# Ethiopia is UTC+3 year-round.
TZ = "+03:00"
DAY = [f"2026-09-{d:02d}" for d in range(14, 21)]  # Day 1 .. Day 7

DEMO_EMAIL = "simien-demo@example.com"
DEMO_NAME = "Simien Demo Traveler"
DEMO_TITLE = "Ethiopia — Simien Mountains"

OV_KEYWORD = "simien wildlife"
OV_TITLE_HINT = "4 Days Simien"


async def ensure_client(advisor: Ovb) -> str:
    """Create (or reuse, on 409) the demo client. Returns client_id."""
    payload = {
        "full_name": DEMO_NAME,
        "email": DEMO_EMAIL,
        "dossier": {"typed": {"contact_preference": "email"}},
    }
    try:
        created = await advisor.create_client(payload)
        return str(created.client_id)
    except ApiError as exc:
        if exc.status != 409:
            raise
        for summary in (await advisor.list_clients()).clients:
            if str(summary.email).lower() == DEMO_EMAIL:
                return str(summary.id)
        raise


async def ensure_itinerary(advisor: Ovb, client_id: str) -> str:
    """Reuse (wiped) or create the demo itinerary. Returns itinerary_id."""
    for it in (await advisor.list_advisor_itineraries()).itineraries:
        client = getattr(it, "client", None)
        if str(getattr(client, "id", "")) != client_id or it.title != DEMO_TITLE:
            continue
        itin_id = str(it.id)
        graph = await advisor.get_graph(itin_id)
        roots = [n for n in graph.nodes if n.parent_subgraph_id is None]
        for node in roots:
            await advisor.delete_node(itin_id, str(node.id))
        print(f"itinerary: {itin_id} (reused — wiped {len(roots)} root nodes)")
        return itin_id
    itin = await advisor.create_itinerary(
        title=DEMO_TITLE,
        client_id=client_id,
        timing_kind="exact",
        date_start=DAY[0],
        date_end=DAY[6],
    )
    print(f"itinerary: {itin.id} (created, {DAY[0]} → {DAY[6]})")
    return str(itin.id)


async def find_simien(advisor: Ovb) -> tuple[str, str]:
    """Locate the 4-day Simien safari on live OV. Returns (source_id, title)."""
    resp = await advisor.search_inventory(
        params={"source": "ov", "keyword": OV_KEYWORD, "limit": 9}
    )
    items = resp.items or []
    item = next(
        (i for i in items if OV_TITLE_HINT.lower() in str(i.title).lower()),
        items[0] if items else None,
    )
    if item is None:
        raise SystemExit("no OV result for the Simien search — is OV enabled + reachable?")
    return str(item.source_id), str(item.title)


async def add(
    advisor: Ovb,
    itin: str,
    *,
    type: str,
    title: str,
    day: str,
    time: str,
    minutes: int,
    metadata: dict[str, Any] | None = None,
    cost: tuple[str, str, str] | None = None,  # (amount, currency, kind)
) -> None:
    await advisor.add_node(
        itin,
        type=type,
        title=title,
        starts_at=f"{day}T{time}:00{TZ}",
        duration_minutes=minutes,
        metadata=metadata or {},
        cost_amount=cost[0] if cost else None,
        cost_currency=cost[1] if cost else None,
        cost_kind=cost[2] if cost else None,
    )


async def main() -> None:
    profile = resolve_profile(os.environ.get("OVB_PROFILE"))
    advisor = Ovb.for_identity(profile)
    try:
        client_id = await ensure_client(advisor)
        print(f"client: {client_id} ({DEMO_EMAIL})")
        itin_id = await ensure_itinerary(advisor, client_id)

        # ── Day 1 — arrival in Addis ────────────────────────────────────
        await add(advisor, itin_id, type="flight",
                  title="Flight — LHR → Addis Ababa (ET701)",
                  day=DAY[0], time="07:30", minutes=465,
                  cost=("4820.00", "USD", "total"))
        await add(advisor, itin_id, type="transit",
                  title="Private transfer — Bole to the Sheraton",
                  day=DAY[0], time="16:15", minutes=40)
        await add(advisor, itin_id, type="meal",
                  title="Dinner at Yod Abyssinia — traditional welcome",
                  day=DAY[0], time="19:30", minutes=105,
                  cost=("140.00", "USD", "per_person"))
        await add(advisor, itin_id, type="hotel",
                  title="Sheraton Addis — Executive Suite",
                  day=DAY[0], time="21:30", minutes=45,
                  metadata={"night_bar": True})

        # ── Days 2–5 — the OV adventure (subgraph materializes server-side) ──
        source_id, ov_title = await find_simien(advisor)
        print(f"ov item: {source_id} — {ov_title}")
        parent = await advisor.node_from_inventory(
            itin_id, source="ov", source_id=source_id, status="pending"
        )
        # from-inventory lands unscheduled; put the card on Day 2 morning,
        # honestly spanning the 4 adventure days. Merge into the metadata the
        # card mapping already wrote (PATCH replaces the whole dict).
        meta = dict(parent.metadata or {})
        meta.update({
            "start_time": f"{DAY[1]}T08:00:00{TZ}",
            "duration_minutes": 4 * 24 * 60,
        })
        await advisor.update_node(itin_id, str(parent.id), fields={"metadata": meta})
        print(f"adventure node: {parent.id} — scheduled {DAY[1]} 08:00 (4 days)")

        # ── Day 6 — back in Addis, decompression ────────────────────────
        await add(advisor, itin_id, type="experience",
                  title="Coffee ceremony & National Museum morning",
                  day=DAY[5], time="10:00", minutes=150)
        await add(advisor, itin_id, type="meal",
                  title="Farewell dinner — Kategna",
                  day=DAY[5], time="19:00", minutes=120,
                  cost=("90.00", "USD", "per_person"))
        await add(advisor, itin_id, type="hotel",
                  title="Sheraton Addis — Executive Suite",
                  day=DAY[5], time="21:30", minutes=45,
                  metadata={"night_bar": True})

        # ── Day 7 — departure ────────────────────────────────────────────
        await add(advisor, itin_id, type="flight",
                  title="Flight — Addis Ababa → LHR (ET700)",
                  day=DAY[6], time="11:05", minutes=480,
                  cost=("4820.00", "USD", "total"))

        # ── Verify the subgraph landed ───────────────────────────────────
        graph = await advisor.get_graph(itin_id)
        children = [n for n in graph.nodes if str(n.parent_subgraph_id or "") == str(parent.id)]
        children.sort(key=lambda n: (n.metadata or {}).get("subgraph_day", {}).get("index", 99))
        print(f"\ngraph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        print(f"the journey within ({len(children)} days):")
        for child in children:
            sd = (child.metadata or {}).get("subgraph_day", {})
            print(f"  Day {sd.get('index')}: {child.title}  [{sd.get('lat'):.3f}, {sd.get('lng'):.3f}]")

        print(f"\nopen: http://localhost:3000/itinerary/{itin_id}")
    finally:
        await advisor.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
