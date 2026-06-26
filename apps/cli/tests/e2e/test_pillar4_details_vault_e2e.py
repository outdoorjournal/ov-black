"""Pillar 4 — Traveler enters party details and stores documents securely.

Demo-script stage 4 (mvp.md §7): *"Traveler enters party members and uploads a
passport to the vault; advisor sees them."*

Acceptance (mvp.md Pillar 4):
  - Traveler-facing form captures party members + per-member detail; persists to
    the parties/travelers model; visible to the advisor.
  - Vault: encrypted upload (passport/visa/insurance/loyalty/other), access-scoped
    to client + assigned advisor, with expiry tracking (flag passports < 6 months).
  - Documents are stored once and re-attachable to a later trip.

Status: 🔨 NOT BUILT (M003). The `parties`/`travelers` tables exist (migration
0014) but carry no member-identity/document model, no traveler entry surface, and
there is no vault. These tests are complete scaffolds that `skip_until` the slice
that lands the backend — they do not depend on a live stack, so the skip reason is
always the *milestone*, never the environment.
"""

from __future__ import annotations

import flows
import pytest

from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_advisor_party_member_crud_and_attach_to_trip(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """V1 — advisor saves a durable member, edits it, and attaches it to a trip.

    Proves the collaborative roster over the wire: create (actor=advisor) →
    list → patch a constraint → attach onto the itinerary's party → the trip's
    party resolves back to the same durable member.
    """
    client_id, _ = client_under_test

    created = await advisor.create_party_member(
        client_id,
        {"full_name": "Avery Stone", "is_primary": True, "dietary": "no shellfish"},
    )
    assert created.full_name == "Avery Stone"
    assert str(created.created_by_actor) == "advisor"
    member_id = str(created.id)

    listing = await advisor.list_party_members(client_id)
    assert member_id in {str(m.id) for m in listing.members}

    patched = await advisor.update_party_member(client_id, member_id, {"mobility": "wheelchair"})
    assert patched.mobility == "wheelchair"

    # Attach the saved member onto the seeded trip (same household → authorized).
    party = await advisor.attach_party_member(built_itinerary, member_id)
    assert member_id in {str(e.party_member_id) for e in party.members}
    # The per-trip row resolves back to the durable member.
    entry = next(e for e in party.members if str(e.party_member_id) == member_id)
    assert entry.member is not None and entry.member.full_name == "Avery Stone"


async def test_party_member_is_remembered_across_trips(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """V1 — the same saved member attaches to a second itinerary without re-entry.

    The "remember previous travelers" promise: a member lives on the client, so a
    new trip just references the existing person rather than recreating them.
    """
    client_id, _ = client_under_test
    member = await advisor.create_party_member(client_id, {"full_name": "Returning Guest"})
    member_id = str(member.id)

    # A second, distinct itinerary for the same client.
    second = await flows.ensure_japan_itinerary(advisor, client_id=client_id)
    if second == built_itinerary:
        pytest.skip("demo itinerary is idempotent per client — need two distinct trips")

    await advisor.attach_party_member(built_itinerary, member_id)
    await advisor.attach_party_member(second, member_id)

    party_a = await advisor.list_itinerary_party(built_itinerary)
    party_b = await advisor.list_itinerary_party(second)
    assert member_id in {str(e.party_member_id) for e in party_a.members}
    assert member_id in {str(e.party_member_id) for e in party_b.members}


async def test_traveler_self_service_party_member(
    traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """V1 — the traveler maintains their own household via /me (collaboration).

    Self-skips when no linked-traveler identity is provisioned on this machine.
    """
    created = await traveler.create_my_party_member(
        {"full_name": "My Companion", "dietary": "vegetarian"}
    )
    assert str(created.created_by_actor) == "traveler"

    mine = await traveler.my_party_members()
    assert str(created.id) in {str(m.id) for m in mine.members}


async def test_passport_upload_to_vault_with_expiry_flag() -> None:
    """V3 — encrypted, access-scoped passport upload with expiry flagging.

    Intended flow once the vault lands (M003/V3 — S3 + SSE-KMS + presigned, D-VAULT):

        # 1. Traveler requests a presigned upload URL, scoped to their client.
        slot = await traveler.request_vault_upload(
            client_id, doc_type="passport", expiry="2026-10-01")
        await put_to_presigned(slot.upload_url, passport_bytes)   # direct-to-S3, not via our API

        # 2. Advisor (assigned) can list + fetch it via a presigned download URL.
        docs = await advisor.list_vault(client_id)
        assert any(d.type == "passport" for d in docs)

        # 3. Expiry tracking: a passport valid < 6 months is flagged.
        assert docs[0].expires_soon is True

        # 4. Access control: an *unassigned* advisor / another client is refused (403).
    """
    flows.skip_until("M003/V3", "secure document vault (S3 + SSE-KMS, presigned, expiry)")


async def test_document_reuses_across_trips() -> None:
    """V3 — a stored document attaches to a second itinerary without re-upload.

    Intended flow:

        doc = (await advisor.list_vault(client_id))[0]
        second = await advisor.create_itinerary(client_id=client_id)
        await advisor.attach_document(second.id, doc.id)   # reference, not re-upload
        assert doc.id in {d.id for d in await advisor.itinerary_documents(second.id)}
    """
    flows.skip_until("M003/V3", "cross-trip document reuse (attach existing vault doc)")
