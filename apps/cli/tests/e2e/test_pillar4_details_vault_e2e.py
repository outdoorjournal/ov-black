"""Pillar 4 — Traveler enters party details and stores documents securely.

Demo-script stage 4 (mvp.md §7): *"Traveler enters party members and uploads a
passport to the vault; advisor sees them."*

Acceptance (mvp.md Pillar 4):
  - Traveler-facing form captures party members + per-member detail; persists to
    the parties/travelers model; visible to the advisor.
  - Vault: encrypted upload (passport/visa/insurance/loyalty/other), access-scoped
    to client + assigned advisor, with expiry tracking (flag passports < 6 months).
  - Documents are stored once and re-attachable to a later trip.

Status: ✅ BUILT. V1 (party member model, 0019) and V3 (secure document vault,
0020 — S3 + SSE-KMS + presigned, D-VAULT) have landed; these tests drive both
over the wire against `local`. The vault's storage is the AWS-free
MockVaultStorage there, so the upload/download tests exercise the API/DB contract
(init → complete → list → download) rather than a real byte PUT — a real
presigned round-trip is only exercisable against a deployed bucket (F2 staging).
"""

from __future__ import annotations

from datetime import date, timedelta

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


async def test_passport_upload_to_vault_with_expiry_flag(
    traveler: Ovb, advisor: Ovb, linked_traveler_client_id: str
) -> None:
    """V3 — presigned upload, expiry flagging, advisor visibility, member link.

    Drives the real vault over the wire (against `local`, where storage is the
    MockVaultStorage — so we exercise the init→complete→download API/DB contract,
    not a real byte PUT):
      1. traveler links a child party member,
      2. inits a passport upload expiring < 6 months out → presigned PUT URL,
      3. confirms it (complete) → uploaded,
      4. lists it back with expires_soon flagged + the member name resolved,
      5. mints a presigned download URL,
      6. the assigned advisor sees the same document.
    """
    # A member to attribute the document to (e.g. a child's passport).
    member = await traveler.create_my_party_member({"full_name": "Small Traveler"})

    soon = (date.today() + timedelta(days=30)).isoformat()
    init = await traveler.init_my_document(
        {
            "doc_type": "passport",
            "file_name": "passport.pdf",
            "content_type": "application/pdf",
            "label": "Kid passport",
            "party_member_id": str(member.id),
            "expires_at": soon,
        }
    )
    assert init.upload_url  # a presigned PUT URL is returned to the uploader
    assert init.document.uploaded_at is None  # pending until confirmed
    doc_id = str(init.document.id)

    confirmed = await traveler.complete_my_document(doc_id, size_bytes=2048)
    assert confirmed.uploaded_at is not None

    mine = await traveler.my_documents()
    row = next(d for d in mine.documents if str(d.id) == doc_id)
    assert row.expires_soon is True and row.expired is False
    assert row.party_member_name == "Small Traveler"

    dl = await traveler.download_my_document(doc_id)
    assert dl.url  # a presigned GET URL

    # The assigned advisor sees the same household document.
    advisor_view = await advisor.list_client_documents(linked_traveler_client_id)
    assert doc_id in {str(d.id) for d in advisor_view.documents}


async def test_document_reuses_across_trips(
    advisor: Ovb, client_under_test: tuple[str, str], built_itinerary: str
) -> None:
    """V3 — a stored document is available on every trip without re-upload.

    Documents are client-scoped (household assets), so the itinerary read-only
    listing surfaces the same document on two distinct trips — no attach, no
    re-upload (the cross-trip reuse promise).
    """
    client_id, _ = client_under_test

    init = await advisor.init_client_document(
        client_id,
        {
            "doc_type": "insurance",
            "file_name": "policy.pdf",
            "content_type": "application/pdf",
            "label": "Travel insurance",
        },
    )
    doc_id = str(init.document.id)
    await advisor.complete_client_document(client_id, doc_id, size_bytes=512)

    second = await flows.ensure_japan_itinerary(advisor, client_id=client_id)
    if second == built_itinerary:
        pytest.skip("demo itinerary is idempotent per client — need two distinct trips")

    docs_a = await advisor.itinerary_documents(built_itinerary)
    docs_b = await advisor.itinerary_documents(second)
    # Same household → the one stored document shows on both trips, no re-upload.
    assert doc_id in {str(d.id) for d in docs_a.documents}
    assert doc_id in {str(d.id) for d in docs_b.documents}
