"""Shared offline test builders (imported directly, not via conftest).

Kept out of conftest.py so the two conftest modules (tests/ and tests/e2e/)
don't collide when imported by name.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from ovb._generated import models as gm


def make_jwt(
    *, sub: str = "u1", email: str = "a@x.com", role: str = "advisor", exp: int | None = None
) -> str:
    """Build an unsigned-but-well-formed JWT for offline auth tests."""
    if exp is None:
        exp = int(time.time()) + 3600

    def seg(obj: dict[str, Any]) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = seg({"alg": "HS256", "typ": "JWT"})
    payload = seg({"sub": sub, "email": email, "role": role, "exp": exp})
    return f"{header}.{payload}.{seg({'sig': 'x'})}"


def make_node(node_id: str, itinerary_id: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": node_id,
        "itinerary_id": itinerary_id,
        "parent_subgraph_id": None,
        "type": "experience",
        "status": "pending",
        "title": "Node",
        "source": None,
        "source_id": None,
        "metadata": {},
        "cost_amount": None,
        "cost_currency": None,
        "cost_kind": None,
        "starts_at": None,
        "duration_minutes": None,
        "depth": 0,
    }
    base.update(over)
    return base


def make_graph(
    itinerary_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    status: str = "in_studio",
) -> gm.GraphResponse:
    return gm.GraphResponse.model_validate(
        {
            "itinerary": {
                "id": itinerary_id,
                "title": "Trip",
                "client_id": None,
                "created_by": None,
                "display_status": status,
            },
            "nodes": nodes or [],
            "edges": edges or [],
        }
    )
