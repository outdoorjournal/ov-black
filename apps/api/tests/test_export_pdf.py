"""PDF rendering smoke: page count, %PDF prefix, notes section survives."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.export.pdf import build_pdf

from tests._export_fixtures import make_day, make_item, make_trip


def _trip(n_days: int) -> object:
    days = tuple(
        make_day(
            date(2026, 6, day),
            (
                make_item(
                    title=f"Activity {day}",
                    start=f"2026-06-{day:02d}T09:00:00+09:00",
                    cost="100.00",
                    currency="USD",
                    cost_kind="total",
                ),
            ),
            label=f"Day {day}",
            subtotals={"USD": Decimal("100.00")},
        )
        for day in range(1, n_days + 1)
    )
    return make_trip(days, totals={"USD": Decimal(str(100 * n_days)) + Decimal("0.00")})


def test_build_pdf_page_count_and_prefix() -> None:
    trip = _trip(3)
    notes = {
        date(2026, 6, 1): {"bring": ["Camera", "Water"], "tips": ["Early start"]},
    }
    pdf = build_pdf(trip, notes)  # type: ignore[arg-type]
    # Overview page + one per day (may overflow to more, never fewer).
    assert pdf.page_no() >= 1 + 3
    data = bytes(pdf.output())
    assert data[:4] == b"%PDF"


def test_build_pdf_without_notes() -> None:
    pdf = build_pdf(_trip(1))  # type: ignore[arg-type]
    assert pdf.page_no() >= 2
    assert bytes(pdf.output())[:4] == b"%PDF"


def test_build_pdf_handles_unicode_and_cjk_title() -> None:
    # DejaVu lacks CJK glyphs but must not raise — degrades to replacement chars.
    day = make_day(
        date(2026, 6, 1),
        (make_item(title="京都の庭園 · Café façade", location="Kyoto"),),
        label="Day 1",
    )
    trip = make_trip((day,), title="日本 2026")
    pdf = build_pdf(trip)  # type: ignore[arg-type]
    assert bytes(pdf.output())[:4] == b"%PDF"
