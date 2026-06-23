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

pytestmark = pytest.mark.e2e


async def test_traveler_adds_party_members() -> None:
    """V1+V2 — identity-bearing party members captured by the traveler, read by the advisor.

    Intended flow once the party-member model + form land (M003/V1, V2):

        traveler = <linked traveler Ovb>
        client_id = await traveler.my_client()

        # 1. Traveler adds each party member with full identity + constraints.
        await traveler.add_party_member(client_id, {
            "full_name": "...", "date_of_birth": "...", "nationality": "...",
            "dietary": ["vegetarian"], "medical": [...], "mobility": "...",
            "loyalty": {...}, "emergency_contact": {...},
        })

        # 2. Advisor reads the same members back (RLS: client + assigned advisor only).
        members = await advisor.list_party_members(client_id)
        assert {m.full_name for m in members} >= {...}

        # 3. The agent can reference party constraints in Fill (vegetarian → no-meat meals),
        #    closing the B6 resume-hook-2 gap (richer party constraints from V1).
    """
    flows.skip_until("M003/V1+V2", "party-member identity model + traveler entry form")


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
