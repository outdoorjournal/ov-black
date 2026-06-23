"""Rendering — rich for humans, JSON for agents. One ``emit`` switch per command.

Craft line (R014): no emoji, no spinners. Status carries colour, prose stays plain.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ovb._compat import unwrap_root

console = Console()
err_console = Console(stderr=True)

STATUS_STYLE: dict[str, str] = {
    "idea": "white",
    "proposed": "yellow",
    "approved": "green",
    "booked": "cyan",
    "confirmed": "bold blue",
    "discarded": "dim strike",
    "draft": "yellow",
}

SEVERITY_STYLE: dict[str, str] = {
    "info": "dim",
    "suggest": "cyan",
    "warn": "yellow",
    "block": "bold red",
}


def to_jsonable(obj: Any) -> Any:
    """Best-effort conversion of SDK results to JSON-safe primitives."""
    obj = unwrap_root(obj)
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    return obj


def print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(to_jsonable(obj), indent=2, default=str) + "\n")


def emit(json_mode: bool, obj: Any, human: Any) -> None:
    """JSON when ``json_mode``, else render ``human`` (a callable → renderable)."""
    if json_mode:
        print_json(obj)
    else:
        console.print(human())


def status_text(status: str) -> Text:
    return Text(status, style=STATUS_STYLE.get(status, "white"))


def _cost(node: dict[str, Any]) -> str:
    amount = node.get("cost_amount")
    currency = node.get("cost_currency")
    if amount is None or not currency:
        return ""
    kind = node.get("cost_kind") or ""
    suffix = "/pp" if kind == "per_person" else ""
    return f"{amount} {currency}{suffix}"


# ── tables ───────────────────────────────────────────────────────────────────
def clients_table(rows: list[Any]) -> Table:
    t = Table(title="clients", header_style="bold")
    for col in ("id", "full_name", "email", "invite", "dossier"):
        t.add_column(col)
    for r in rows:
        d = to_jsonable(r)
        t.add_row(
            str(d["id"]),
            d.get("full_name", ""),
            d.get("email", ""),
            str(d.get("invite_status", "")),
            "yes" if d.get("has_dossier") else "no",
        )
    return t


def itineraries_table(payload: Any) -> Table:
    d = to_jsonable(payload)
    rows = d.get("itineraries", d) if isinstance(d, dict) else d
    t = Table(title="itineraries", header_style="bold")
    for col in ("id", "title", "status", "client", "nodes"):
        t.add_column(col)
    for r in rows:
        client = r.get("client") or {}
        client_name = (
            client.get("full_name") if isinstance(client, dict) else r.get("client_id", "")
        )
        t.add_row(
            str(r.get("id", r.get("itinerary_id", ""))),
            r.get("title", ""),
            str(r.get("status", "")),
            str(client_name or ""),
            str(r.get("node_count", "")),
        )
    return t


def turns_table(rows: list[Any]) -> Table:
    t = Table(title="turns", header_style="bold")
    for col in ("#", "role", "content", "model", "latency"):
        t.add_column(col)
    for r in rows:
        d = to_jsonable(r)
        content = (d.get("content") or "").replace("\n", " ")
        if len(content) > 80:
            content = content[:77] + "…"
        t.add_row(
            str(d.get("turn_index", "")),
            str(d.get("role", "")),
            content,
            str(d.get("model") or ""),
            f"{d.get('latency_ms')}ms" if d.get("latency_ms") is not None else "",
        )
    return t


def analyses_table(rows: list[Any]) -> Table:
    t = Table(title="analyses", header_style="bold")
    for col in ("id", "depth", "status", "summary", "created"):
        t.add_column(col)
    for r in rows:
        d = to_jsonable(r)
        t.add_row(
            str(d["id"]),
            str(d.get("depth", "")),
            str(d.get("status", "")),
            (d.get("summary") or "")[:60],
            str(d.get("created_at", ""))[:19],
        )
    return t


def findings_table(rows: list[Any]) -> Table:
    t = Table(title="findings", header_style="bold")
    for col in ("severity", "category", "message", "node"):
        t.add_column(col)
    for r in rows:
        d = to_jsonable(r)
        sev = str(d.get("severity", ""))
        t.add_row(
            Text(sev, style=SEVERITY_STYLE.get(sev, "white")),
            str(d.get("category", "")),
            str(d.get("message", "")),
            str(d.get("node_id") or "")[:8],
        )
    return t


def inventory_table(payload: Any) -> Table:
    d = to_jsonable(payload)
    items = d.get("items", []) if isinstance(d, dict) else d
    t = Table(title=f"inventory ({d.get('count', len(items))})", header_style="bold")
    for col in ("kind", "source", "source_id", "title", "price"):
        t.add_column(col)
    for it in items:
        price = it.get("price") or {}
        price_s = ""
        if isinstance(price, dict) and price.get("amount") is not None:
            price_s = f"{price.get('amount')} {price.get('currency', '')}"
        t.add_row(
            str(it.get("kind", "")),
            str(it.get("source", "")),
            str(it.get("source_id", ""))[:24],
            str(it.get("title", ""))[:40],
            price_s,
        )
    return t


def fill_table(payload: Any) -> Table:
    d = to_jsonable(payload)
    props = d.get("proposals", [])
    t = Table(
        title=f"fill proposals (analysis {str(d.get('analysis_id') or 'none')[:8]})",
        header_style="bold",
    )
    for col in ("score", "type", "title", "fits", "drive_in/out", "rationale"):
        t.add_column(col)
    for p in props:
        fits = "yes" if p.get("fits_in_gap") else ("?" if p.get("feasibility_unknown") else "no")
        drive = f"{p.get('drive_time_in_min')}/{p.get('drive_time_out_min')}"
        t.add_row(
            f"{p.get('score', 0):.2f}",
            str(p.get("type", "")),
            str(p.get("title", ""))[:36],
            fits,
            drive,
            str(p.get("rationale", ""))[:48],
        )
    return t


def graph_tree(payload: Any) -> Tree:
    """Render an itinerary graph the way the UI's canvas reads — a follows-chain."""
    d = to_jsonable(payload)
    itin = d["itinerary"]
    nodes = {str(n["id"]): n for n in d["nodes"]}
    edges = d["edges"]

    root = Tree(
        Text.assemble(
            (itin.get("title") or "(untitled)", "bold"),
            "  ",
            status_text(str(itin.get("status", ""))),
            (f"  {itin['id']}", "dim"),
        )
    )

    follows = {e["from_node_id"]: e["to_node_id"] for e in edges if e.get("type") == "follows"}
    has_incoming = {e["to_node_id"] for e in edges if e.get("type") == "follows"}
    starts = [nid for nid in nodes if nid not in has_incoming]
    starts.sort(key=lambda nid: (nodes[nid].get("starts_at") or "", nodes[nid].get("title") or ""))

    def line(n: dict[str, Any]) -> Text:
        parts = Text()
        parts.append(f"{n.get('type', ''):<11}", style="magenta")
        parts.append(status_text(str(n.get("status", ""))))
        parts.append("  ")
        parts.append(n.get("title") or "(untitled)")
        when = n.get("starts_at")
        if when:
            parts.append(f"  {str(when)[:16]}", style="dim")
        cost = _cost(n)
        if cost:
            parts.append(f"  {cost}", style="green")
        parts.append(f"  {n['id'][:8]}", style="dim")
        return parts

    seen: set[str] = set()
    for start in starts:
        branch = root
        nid: str | None = start
        while nid is not None and nid in nodes and nid not in seen:
            seen.add(nid)
            branch = branch.add(line(nodes[nid]))
            nid = follows.get(nid)
    # Orphans (nodes not on any follows chain, e.g. alternatives / ideas).
    for nid, n in nodes.items():
        if nid not in seen:
            root.add(line(n))
    return root


def kv_panel(title: str, payload: Any) -> Any:
    from rich.panel import Panel

    d = to_jsonable(payload)
    body = Text()
    items = d.items() if isinstance(d, dict) else [("value", d)]
    for k, v in items:
        body.append(f"{k}: ", style="bold")
        body.append(f"{v}\n")
    return Panel(body, title=title, border_style="blue")
