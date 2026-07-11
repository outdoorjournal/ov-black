"""PDF rendering of an :class:`~app.services.export.grouping.ExportTrip`.

Page 1 is the condensed trip overview — title, brief, dates, party, and a
per-day / per-currency cost table. Then one page (or more, natural overflow)
per day spelling out every item, closed by the day's "For this day" notes
section (what to bring / tips).

Typography follows the OV Black direction: serif voice (DejaVu Serif, vendored
— fpdf2's core fonts are latin-1-only), near-black ink, and the brand orange
#F5701F as restrained punctuation (day rules, small-caps labels) only. DejaVu
carries no CJK — titles in those scripts degrade to replacement glyphs, an
accepted v1 limitation.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fpdf import FPDF

from app.services.export.grouping import ExportDay, ExportItem, ExportTrip

_FONT_DIR = Path(__file__).parent / "fonts"

_ORANGE = (245, 112, 31)  # #F5701F
_INK = (26, 24, 22)
_MUTED = (110, 104, 98)
_RULE = (228, 222, 214)

_MARGIN = 18.0


def _register_fonts(pdf: FPDF) -> None:
    pdf.add_font("Serif", "", _FONT_DIR / "DejaVuSerif.ttf")
    pdf.add_font("Serif", "B", _FONT_DIR / "DejaVuSerif-Bold.ttf")
    pdf.add_font("Serif", "I", _FONT_DIR / "DejaVuSerif-Italic.ttf")
    pdf.add_font("Sans", "", _FONT_DIR / "DejaVuSans.ttf")
    pdf.add_font("Sans", "B", _FONT_DIR / "DejaVuSans-Bold.ttf")


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def _cost_text(item: ExportItem, party_size: int) -> str | None:
    if item.cost_amount is None or item.cost_currency is None:
        return None
    if item.cost_kind == "per_person":
        return f"{item.cost_currency} {_money(item.cost_amount)} / person"
    return f"{item.cost_currency} {_money(item.cost_amount)}"


def _time_range(item: ExportItem) -> str | None:
    if item.start_local is None:
        return None
    start = item.start_local.strftime("%H:%M")
    if item.duration_minutes is None:
        return start
    end = (item.start_local + timedelta(minutes=item.duration_minutes)).strftime("%H:%M")
    return f"{start} – {end}"


def _type_label(item: ExportItem) -> str:
    return item.type.replace("_", " ").upper()


def _day_heading(day: ExportDay) -> str:
    pretty = day.day_date.strftime("%A, %B %-d").upper()
    label = day.label.upper()
    return pretty if label == day.day_date.isoformat().upper() else f"{label} — {pretty}"


def _orange_rule(pdf: FPDF, width: float = 24.0) -> None:
    pdf.set_draw_color(*_ORANGE)
    pdf.set_line_width(0.8)
    y = pdf.get_y()
    pdf.line(_MARGIN, y, _MARGIN + width, y)
    pdf.ln(4)


class _ExportPdf(FPDF):
    """Adds the running footer (trip title · page number)."""

    trip_title: str = ""

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Sans", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(0, 5, f"{self.trip_title}  ·  {self.page_no()}", align="C")


def _overview_page(pdf: FPDF, trip: ExportTrip, epw: float) -> None:
    pdf.add_page()

    pdf.set_font("Sans", "B", 8)
    pdf.set_text_color(*_ORANGE)
    pdf.cell(0, 5, "OUTDOOR VOYAGE — BLACK", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Serif", "B", 26)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(epw, 11, trip.title or "Untitled trip", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    if trip.brief:
        pdf.set_font("Serif", "I", 11)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(epw, 6, trip.brief, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    facts: list[str] = []
    if trip.date_start and trip.date_end:
        facts.append(
            f"{trip.date_start.strftime('%b %-d, %Y')} – {trip.date_end.strftime('%b %-d, %Y')}"
        )
    elif trip.duration_nights:
        facts.append(f"{trip.duration_nights} nights")
    if trip.timing_note:
        facts.append(trip.timing_note)
    facts.append(f"Party of {trip.party_size}")
    facts.append(f"{len(trip.days)} planned day{'s' if len(trip.days) != 1 else ''}")
    if trip.is_fork:
        facts.append("Working copy")
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(epw, 5.5, "  ·  ".join(facts), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ── Cost breakdown table ─────────────────────────────────────────────
    currencies = sorted(
        {c for day in trip.days for c in day.subtotals}
        | {c for i in trip.collection if i.cost_currency for c in [i.cost_currency]}
        | set(trip.totals)
    )
    if currencies:
        pdf.set_font("Sans", "B", 8)
        pdf.set_text_color(*_ORANGE)
        pdf.cell(0, 5, "COST BREAKDOWN", new_x="LMARGIN", new_y="NEXT")
        _orange_rule(pdf)

        label_w = epw * 0.4
        col_w = (epw - label_w) / len(currencies)

        pdf.set_font("Sans", "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(label_w, 6, "")
        for currency in currencies:
            pdf.cell(col_w, 6, currency, align="R")
        pdf.ln(6)

        pdf.set_draw_color(*_RULE)
        pdf.set_line_width(0.2)

        def _cost_row(label: str, amounts: dict[str, Decimal], *, bold: bool = False) -> None:
            pdf.set_font("Sans", "B" if bold else "", 9)
            pdf.set_text_color(*_INK)
            pdf.cell(label_w, 6.5, label)
            for currency in currencies:
                amount = amounts.get(currency)
                pdf.cell(col_w, 6.5, _money(amount) if amount is not None else "—", align="R")
            pdf.ln(6.5)
            y = pdf.get_y()
            pdf.line(_MARGIN, y, _MARGIN + epw, y)

        for day in trip.days:
            heading = f"{day.label} · {day.day_date.strftime('%b %-d')}"
            _cost_row(heading, day.subtotals)
        unscheduled: dict[str, Decimal] = {}
        for item in trip.collection:
            if item.cost_amount is None or item.cost_currency is None:
                continue
            amount = (
                item.cost_amount * max(trip.party_size, 1)
                if item.cost_kind == "per_person"
                else item.cost_amount
            )
            unscheduled[item.cost_currency] = (
                unscheduled.get(item.cost_currency, Decimal(0)) + amount
            )
        if unscheduled:
            _cost_row("Collection (unscheduled)", unscheduled)
        _cost_row("Trip total", dict(trip.totals), bold=True)

        pdf.ln(2)
        pdf.set_font("Sans", "", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(
            0,
            5,
            f"Per-person prices expanded × party of {trip.party_size}. "
            "Totals are summed per currency; unpriced items are not included.",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    if trip.collection:
        pdf.ln(4)
        pdf.set_font("Sans", "B", 8)
        pdf.set_text_color(*_ORANGE)
        pdf.cell(0, 5, "IN THE COLLECTION (UNSCHEDULED)", new_x="LMARGIN", new_y="NEXT")
        _orange_rule(pdf)
        pdf.set_font("Serif", "", 9.5)
        pdf.set_text_color(*_INK)
        for item in trip.collection:
            line = item.title
            if item.location:
                line += f" — {item.location}"
            cost = _cost_text(item, trip.party_size)
            if cost:
                line += f" ({cost})"
            pdf.multi_cell(epw, 5.5, f"·  {line}", new_x="LMARGIN", new_y="NEXT")


def _day_page(
    pdf: FPDF,
    day: ExportDay,
    notes: dict[str, Any] | None,
    party_size: int,
    epw: float,
) -> None:
    pdf.add_page()

    pdf.set_font("Sans", "B", 9)
    pdf.set_text_color(*_ORANGE)
    pdf.cell(0, 6, _day_heading(day), new_x="LMARGIN", new_y="NEXT")
    _orange_rule(pdf, width=epw)

    if day.night_hotel:
        pdf.set_font("Sans", "", 8.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 5, f"Tonight: {day.night_hotel}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    for item in day.items:
        # One block per item: time + title line, meta line, notes.
        time_text = _time_range(item)
        pdf.set_font("Sans", "B", 9)
        pdf.set_text_color(*_INK)
        if time_text:
            pdf.cell(26, 6.5, time_text)
        else:
            pdf.cell(26, 6.5, "—")
        pdf.set_font("Serif", "B", 11)
        pdf.multi_cell(epw - 26, 6.5, item.title, new_x="LMARGIN", new_y="NEXT")

        meta_bits: list[str] = [_type_label(item)]
        if item.journey is not None:
            meta_bits.append(
                f"day {item.journey.index} of {item.journey.total} — {item.journey.parent_title}"
            )
        if item.location:
            meta_bits.append(item.location)
        if item.duration_minutes:
            hours, minutes = divmod(item.duration_minutes, 60)
            meta_bits.append(f"{hours}h {minutes:02d}m" if hours else f"{minutes} min")
        cost = _cost_text(item, party_size)
        if cost:
            meta_bits.append(cost)
        meta_bits.append(item.status)
        pdf.set_x(_MARGIN + 26)
        pdf.set_font("Sans", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(epw - 26, 4.5, "  ·  ".join(meta_bits), new_x="LMARGIN", new_y="NEXT")

        if item.description:
            pdf.set_x(_MARGIN + 26)
            pdf.set_font("Serif", "", 9)
            pdf.set_text_color(*_INK)
            pdf.multi_cell(epw - 26, 5, item.description[:500], new_x="LMARGIN", new_y="NEXT")
        for note in item.notes:
            pdf.set_x(_MARGIN + 26)
            pdf.set_font("Serif", "I", 9)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(epw - 26, 5, f"Note: {note}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.5)

    if day.subtotals:
        pdf.set_font("Sans", "", 8.5)
        pdf.set_text_color(*_MUTED)
        subtotal = "   ".join(
            f"{currency} {_money(amount)}" for currency, amount in sorted(day.subtotals.items())
        )
        pdf.cell(0, 5.5, f"Day subtotal: {subtotal}", new_x="LMARGIN", new_y="NEXT")

    # ── "For this day" — the day-notes box ───────────────────────────────
    bring = [b for b in (notes or {}).get("bring", []) if isinstance(b, str)]
    tips = [t for t in (notes or {}).get("tips", []) if isinstance(t, str)]
    if not bring and not tips:
        return

    pdf.ln(4)
    box_top = pdf.get_y()
    pdf.set_x(_MARGIN + 4)
    pdf.set_font("Sans", "B", 8)
    pdf.set_text_color(*_ORANGE)
    pdf.cell(0, 5.5, "FOR THIS DAY", new_x="LMARGIN", new_y="NEXT")
    if bring:
        pdf.set_x(_MARGIN + 4)
        pdf.set_font("Sans", "B", 8.5)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5.5, "What you should bring", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "", 9)
        for bullet in bring:
            pdf.set_x(_MARGIN + 6)
            pdf.multi_cell(epw - 10, 5, f"·  {bullet}", new_x="LMARGIN", new_y="NEXT")
    if tips:
        pdf.set_x(_MARGIN + 4)
        pdf.set_font("Sans", "B", 8.5)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5.5, "Good to know", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "", 9)
        for bullet in tips:
            pdf.set_x(_MARGIN + 6)
            pdf.multi_cell(epw - 10, 5, f"·  {bullet}", new_x="LMARGIN", new_y="NEXT")
    # Thin orange rule down the left of the box (drawn last — height is known).
    pdf.set_draw_color(*_ORANGE)
    pdf.set_line_width(0.6)
    pdf.line(_MARGIN + 1, box_top, _MARGIN + 1, pdf.get_y())


def build_pdf(trip: ExportTrip, day_notes: dict[date, dict[str, Any]] | None = None) -> FPDF:
    """Render the trip; returns the FPDF (callers serialize with ``bytes(pdf.output())``)."""
    pdf = _ExportPdf(orientation="P", unit="mm", format="A4")
    pdf.trip_title = trip.title or "Outdoor Voyage"
    _register_fonts(pdf)
    pdf.set_margins(_MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=18)
    epw = pdf.w - 2 * _MARGIN

    _overview_page(pdf, trip, epw)
    for day in trip.days:
        notes = (day_notes or {}).get(day.day_date)
        _day_page(pdf, day, notes, trip.party_size, epw)
    return pdf
