"""Opaque keyset cursors for the advisor list/feed endpoints (Wave F).

A cursor is a base64url-encoded JSON object of resume-from keys — e.g.
``{"at": "<iso8601>", "kind": "payment", "source_id": "…"}`` for the activity
feed, or ``{"v": "<sort value>", "id": "<uuid>"}`` for a roster page. Opaque so
clients treat it as a token (echo it back verbatim), JSON so each endpoint owns
its own key shape without a registry.

``decode_cursor`` returns ``None`` on anything malformed (bad base64, bad JSON,
not an object) — routers translate that to a 400 ``invalid_cursor`` rather than
guessing. A tampered-but-well-formed cursor simply resumes from whatever keys
it names; every consumer scopes its query by owner first, so the worst a forged
cursor can do is page through the caller's own data in a strange order.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from fastapi import HTTPException


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode resume-from keys as an opaque, URL-safe token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any] | None:
    """Decode a cursor token; ``None`` for anything that isn't ours."""
    # Re-pad: encode_cursor strips '=' so tokens stay clean in query strings.
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def require_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Router-side guard: pass-through for absent cursors, 400 for malformed ones."""
    if cursor is None:
        return None
    payload = decode_cursor(cursor)
    if payload is None:
        raise HTTPException(status_code=400, detail="invalid_cursor")
    return payload


def clamp_limit(limit: int, *, default: int = 50, ceiling: int = 100) -> int:
    """The house limit clamp (see routers/analyze.py): 1..ceiling, defaulted."""
    if limit <= 0:
        return default
    return min(limit, ceiling)
