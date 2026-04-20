"""Tests for ``MockProvider`` — fixture loader + search + shape parity with OV.

The parity test is load-bearing: it's the thing that would catch a future
refactor where we slip OV-specific fields into ``ExperienceItem``. If it
breaks, either (a) the abstraction has grown a provider-specific wart, or
(b) the two fixtures genuinely drifted and need to be reconciled. Don't
paper over a parity failure by loosening the assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.inventory.providers.mock import MockProvider, _load_fixture
from app.inventory.providers.ov import normalize_ov_entry
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import ExperienceItem

MOCK_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mock_inventory.json"
)
OV_FIXTURE = (
    Path(__file__).parent / "fixtures" / "ov_search_como.json"
)


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider(fixture_path=MOCK_FIXTURE)


@pytest.fixture()
def ctx() -> InventoryCtx:
    return InventoryCtx(actor_kind="system", actor_id=None)


# ── happy-path search ─────────────────────────────────────────────────────


async def test_search_no_filters_returns_all_fixture_items(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(kinds=None, keyword=None, filters={}, ctx=ctx)
    # The fixture ships a deterministic set; the count is a tripwire for
    # accidental edits. Update here when the fixture intentionally grows.
    assert len(results) == 4
    # Every item must carry source='mock' — proves the source tag is honored.
    assert {item.source for item in results} == {"mock"}


async def test_search_is_deterministic_across_calls(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    """Same inputs ⇒ same ordered output. Fixture-backed determinism matters
    because downstream tests (agent runs, graph writes) pin on source_id."""
    first = await provider.search(kinds=None, keyword=None, filters={}, ctx=ctx)
    second = await provider.search(kinds=None, keyword=None, filters={}, ctx=ctx)
    assert [i.source_id for i in first] == [i.source_id for i in second]


# ── keyword filter ────────────────────────────────────────────────────────


async def test_search_keyword_matches_title_case_insensitive(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(kinds=None, keyword="como", filters={}, ctx=ctx)
    ids = {item.source_id for item in results}
    assert "mock-exp-como-01" in ids
    assert "mock-dest-como-region" in ids
    # The Dolomites experience and Patagonia destination should NOT match.
    assert "mock-exp-dolomites-01" not in ids
    assert "mock-dest-patagonia" not in ids


async def test_search_keyword_matches_tag(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(
        kinds=None, keyword="via ferrata", filters={}, ctx=ctx
    )
    assert [item.source_id for item in results] == ["mock-exp-dolomites-01"]


async def test_search_keyword_no_matches_returns_empty(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(
        kinds=None, keyword="nonexistent-xyz", filters={}, ctx=ctx
    )
    assert results == []


# ── kinds filter ──────────────────────────────────────────────────────────


async def test_search_kinds_filter_narrows_results(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(
        kinds=["destination"], keyword=None, filters={}, ctx=ctx
    )
    assert {item.kind for item in results} == {"destination"}
    assert len(results) == 2


async def test_search_kinds_with_no_fixture_entries_returns_empty(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    # Negative test — fixture has no hotels, so the filter must return [].
    results = await provider.search(
        kinds=["hotel"], keyword=None, filters={}, ctx=ctx
    )
    assert results == []


async def test_search_combined_kinds_and_keyword(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    results = await provider.search(
        kinds=["experience"], keyword="como", filters={}, ctx=ctx
    )
    assert [item.source_id for item in results] == ["mock-exp-como-01"]


# ── get_detail ────────────────────────────────────────────────────────────


async def test_get_detail_known_source_id(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    item = await provider.get_detail(source_id="mock-exp-como-01", ctx=ctx)
    assert item is not None
    assert item.title == "Lakeside Walks Around Lake Como"
    assert item.kind == "experience"


async def test_get_detail_unknown_source_id_returns_none(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    # Negative test — unknown ids must return None, not raise.
    item = await provider.get_detail(source_id="does-not-exist", ctx=ctx)
    assert item is None


# ── fixture loader failure modes ──────────────────────────────────────────


def test_missing_fixture_raises_at_construction(tmp_path: Path) -> None:
    """Fixture file missing → loud error at construction, not at first search."""
    missing = tmp_path / "absent.json"
    with pytest.raises(FileNotFoundError):
        MockProvider(fixture_path=missing)


def test_fixture_with_invalid_kind_raises_validation_error(tmp_path: Path) -> None:
    """An unknown ``kind`` value must fail the Pydantic union at load time.

    This is the main proof that a drifting fixture can't silently ship bad
    data to callers — the discriminated union rejects it before the process
    accepts traffic.
    """
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "kind": "spaceship",  # not a valid InventoryItem kind
                    "source": "mock",
                    "source_id": "x",
                    "title": "invalid",
                }
            ]
        )
    )
    with pytest.raises(ValidationError):
        _load_fixture(bad)


def test_fixture_missing_required_field_raises(tmp_path: Path) -> None:
    bad = tmp_path / "missing.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "kind": "experience",
                    # missing source, source_id, title
                }
            ]
        )
    )
    with pytest.raises(ValidationError):
        _load_fixture(bad)


def test_fixture_non_list_payload_raises(tmp_path: Path) -> None:
    bad = tmp_path / "object.json"
    bad.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError):
        _load_fixture(bad)


# ── cross-adapter shape parity ────────────────────────────────────────────


async def test_experience_item_shape_matches_across_adapters(
    provider: MockProvider, ctx: InventoryCtx
) -> None:
    """Normalize an OV entry and a Mock entry, then prove the resulting
    ``ExperienceItem.model_dump()`` payloads are keyword-for-keyword the
    same shape — same top-level keys, same value types for each key.

    If this assertion ever has to be loosened to pass, the abstraction has
    regressed and the fix is in the adapter, not in the test.
    """
    ov_data = json.loads(OV_FIXTURE.read_text())
    ov_trip = ov_data["trips"][0]
    ov_item: ExperienceItem = normalize_ov_entry(ov_trip)

    mock_item = await provider.get_detail(source_id="mock-exp-como-01", ctx=ctx)
    assert isinstance(mock_item, ExperienceItem)

    ov_dump = ov_item.model_dump(mode="python")
    mock_dump = mock_item.model_dump(mode="python")

    # Same top-level keys on both sides — no provider-specific field leakage.
    assert set(ov_dump.keys()) == set(mock_dump.keys())

    # Parity bar from the task plan: verify the contract fields specifically.
    contract_keys = {
        "source",
        "source_id",
        "title",
        "kind",
        "photos",
        "location",
        "price",
        "tags",
    }
    missing = contract_keys - set(ov_dump.keys())
    assert missing == set(), f"contract keys missing from OV dump: {missing}"
    assert contract_keys.issubset(mock_dump.keys())

    # Per-key type equivalence. None is allowed on either side so that an
    # item without a price (e.g. a destination) doesn't break the parity —
    # what we care about is that *when* a field is populated, the type on
    # both sides is identical.
    for key in contract_keys:
        ov_val = ov_dump[key]
        mock_val = mock_dump[key]
        if ov_val is None or mock_val is None:
            continue
        assert type(ov_val) is type(mock_val), (
            f"type mismatch for {key!r}: OV={type(ov_val).__name__} "
            f"Mock={type(mock_val).__name__}"
        )

    # Discriminator must resolve identically — the union picked the same
    # variant for both entries.
    assert ov_dump["kind"] == mock_dump["kind"] == "experience"

    # Source is the one field where the values MUST differ: this proves the
    # source tag is not hardcoded downstream.
    assert ov_dump["source"] == "ov"
    assert mock_dump["source"] == "mock"
