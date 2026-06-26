"""Pure-Python guards for the ClientDocument ORM model (M003/V3).

Mirrors ``test_analyze_models.py``: assert the new Postgres ENUMs bind with
``create_type=False`` (the migration owns DDL — D003) and that the Python enum
values are byte-identical to ``0020_client_documents.sql`` so the
``values_callable`` rendering round-trips.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.models import ClientDocument, DocumentActor, DocumentType
from app.models.document import document_actor_enum, document_type_enum
from app.schemas.client_documents import DocumentDetail
from app.services.client_documents import build_s3_key


def test_saenum_create_type_is_false_for_all_document_enums() -> None:
    for sa_enum in (document_type_enum, document_actor_enum):
        assert sa_enum.create_type is False, (
            f"Postgres ENUM {sa_enum.name!r} must have create_type=False so "
            "SQLAlchemy never emits CREATE TYPE (migration owns it)."
        )
        assert sa_enum.schema == "public"


def test_document_enum_values_match_migration() -> None:
    assert [m.value for m in DocumentType] == [
        "passport",
        "visa",
        "drivers_license",
        "national_id",
        "vaccination",
        "insurance",
        "loyalty_card",
        "other",
    ]
    assert [m.value for m in DocumentActor] == ["advisor", "traveler"]


def test_tablename() -> None:
    assert ClientDocument.__tablename__ == "client_documents"


# ── pure logic: key sanitization + expiry derivation ─────────────────────


def test_build_s3_key_is_prefixed_and_sanitized() -> None:
    cid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    did = uuid.UUID("22222222-2222-2222-2222-222222222222")
    key = build_s3_key(client_id=cid, document_id=did, file_name="../../etc/passwd")
    assert key.startswith(f"vault/{cid}/{did}/")
    # No path traversal survives the sanitizer.
    assert ".." not in key
    assert "/etc/" not in key.split(f"{did}/", 1)[1]


def test_build_s3_key_falls_back_when_name_empty() -> None:
    cid = uuid.uuid4()
    did = uuid.uuid4()
    assert build_s3_key(client_id=cid, document_id=did, file_name="///").endswith("/document")


def _doc(expires_at: date | None) -> ClientDocument:
    return ClientDocument(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        party_member_id=None,
        doc_type=DocumentType.passport,
        label=None,
        file_name="passport.pdf",
        content_type="application/pdf",
        s3_key="vault/x/y/passport.pdf",
        expires_at=expires_at,
        notes=None,
        created_by_actor=DocumentActor.traveler,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_expiry_derivation_flags() -> None:
    today = date(2026, 6, 25)
    # Expired.
    d = DocumentDetail.from_model(_doc(date(2026, 1, 1)), today=today)
    assert d.expired is True and d.expires_soon is False
    # Within ~6 months → expires_soon, not expired.
    d = DocumentDetail.from_model(_doc(date(2026, 9, 1)), today=today)
    assert d.expired is False and d.expires_soon is True
    # Comfortably valid.
    d = DocumentDetail.from_model(_doc(date(2030, 1, 1)), today=today)
    assert d.expired is False and d.expires_soon is False
    # No expiry → neither flag, and the s3_key never leaks into the shape.
    d = DocumentDetail.from_model(_doc(None), today=today)
    assert d.expired is False and d.expires_soon is False
    assert "s3_key" not in d.model_dump()
