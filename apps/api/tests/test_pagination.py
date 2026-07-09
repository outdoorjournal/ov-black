"""The Wave F cursor codec — pure, no DB."""

from __future__ import annotations

import pytest
from app.services.pagination import clamp_limit, decode_cursor, encode_cursor, require_cursor
from fastapi import HTTPException


def test_round_trip_preserves_keys() -> None:
    payload = {"at": "2026-07-08T12:00:00+00:00", "kind": "payment", "source_id": "abc"}
    assert decode_cursor(encode_cursor(payload)) == payload


def test_token_is_urlsafe_and_unpadded() -> None:
    token = encode_cursor({"v": "Chen, Margaret", "id": "x"})
    assert "=" not in token
    assert all(c.isalnum() or c in "-_" for c in token)


def test_malformed_base64_decodes_to_none() -> None:
    assert decode_cursor("!!not-base64!!") is None


def test_valid_base64_of_non_json_decodes_to_none() -> None:
    import base64

    token = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
    assert decode_cursor(token) is None


def test_json_scalar_is_rejected() -> None:
    import base64

    token = base64.urlsafe_b64encode(b'"just a string"').decode().rstrip("=")
    assert decode_cursor(token) is None


def test_require_cursor_passes_none_through() -> None:
    assert require_cursor(None) is None


def test_require_cursor_raises_400_on_garbage() -> None:
    with pytest.raises(HTTPException) as exc:
        require_cursor("garbage!!!")
    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid_cursor"


def test_clamp_limit_bounds() -> None:
    assert clamp_limit(0) == 50
    assert clamp_limit(-5) == 50
    assert clamp_limit(30) == 30
    assert clamp_limit(500) == 100
    assert clamp_limit(500, ceiling=500) == 500
