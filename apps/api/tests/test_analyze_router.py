"""Analyze HTTP endpoints + auth gate (Phase 5 / B5).

Integration (gated on local Supabase, via the ``client`` TestClient fixture):
the four endpoints under ``/itinerary/{id}/analyses`` and the shared
draft-read gate. ``BackgroundTasks`` complete before the TestClient response
returns, so a queued run is already ``completed`` by the time we GET it.

Itineraries are seeded directly in the DB (``seed_itinerary_sync``) rather than
through ``POST /itinerary`` — the latter stamps ``created_by`` from the JWT
``sub``, which would violate the ``auth.users`` FK for a synthetic test token.
``approved`` itineraries skip the draft-read gate, so any authenticated caller
can drive the endpoints.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from tests._graph_seed import integration, seed_itinerary_sync

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient


def _bearer(make_token: Callable[..., str], sub: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=sub or str(uuid.uuid4()))}"}


@integration
def test_post_analysis_returns_202(client: TestClient, make_token: Callable[..., str]) -> None:
    headers = _bearer(make_token)
    iid = seed_itinerary_sync()
    resp = client.post(f"/itinerary/{iid}/analyses", json={"depth": "shallow"}, headers=headers)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "analysis_id" in body
    assert body["status"] in {"queued", "running", "completed"}


@integration
def test_get_detail_after_run_is_completed(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    headers = _bearer(make_token)
    iid = seed_itinerary_sync()
    aid = client.post(
        f"/itinerary/{iid}/analyses", json={"depth": "shallow"}, headers=headers
    ).json()["analysis_id"]

    detail = client.get(f"/itinerary/{iid}/analyses/{aid}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # Background task has run by now under the TestClient transport.
    assert body["status"] == "completed"
    assert body["result"] is not None
    assert "stats" in body["result"]
    assert isinstance(body["findings"], list)


@integration
def test_list_analyses(client: TestClient, make_token: Callable[..., str]) -> None:
    headers = _bearer(make_token)
    iid = seed_itinerary_sync()
    client.post(f"/itinerary/{iid}/analyses", json={"depth": "shallow"}, headers=headers)
    listed = client.get(f"/itinerary/{iid}/analyses", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) >= 1
    assert rows[0]["itinerary_id"] == str(iid)


@integration
def test_cancel_completed_is_idempotent(client: TestClient, make_token: Callable[..., str]) -> None:
    headers = _bearer(make_token)
    iid = seed_itinerary_sync()
    aid = client.post(
        f"/itinerary/{iid}/analyses", json={"depth": "shallow"}, headers=headers
    ).json()["analysis_id"]
    # The run already completed; cancel is a no-op that returns the row.
    resp = client.post(f"/itinerary/{iid}/analyses/{aid}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@integration
def test_unknown_itinerary_404(client: TestClient, make_token: Callable[..., str]) -> None:
    headers = _bearer(make_token)
    resp = client.post(f"/itinerary/{uuid.uuid4()}/analyses", json={}, headers=headers)
    assert resp.status_code == 404


@integration
def test_unknown_analysis_404(client: TestClient, make_token: Callable[..., str]) -> None:
    headers = _bearer(make_token)
    iid = seed_itinerary_sync()
    resp = client.get(f"/itinerary/{iid}/analyses/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


@integration
def test_requires_jwt(client: TestClient) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/analyses", json={})
    assert resp.status_code == 401


@integration
def test_draft_read_gate_forbids_stranger(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    # Draft itinerary with no owner/creator — only an advisor could read it, so
    # a synthetic non-advisor caller is forbidden (same gate as GET /itinerary).
    iid = seed_itinerary_sync(status="draft")
    stranger = _bearer(make_token)
    assert (client.post(f"/itinerary/{iid}/analyses", json={}, headers=stranger)).status_code == 403
    assert (client.get(f"/itinerary/{iid}/analyses", headers=stranger)).status_code == 403
