"""Dual-read verification for the 0055 kernel-schedule backfill.

Phase 2's acceptance gate (doc/itin-time.md): for every scheduled node, the
kernel's resolution of the new canonical columns must reproduce the stored
``starts_at`` range exactly — ``resolve(schedule, anchor) == [lower, upper)``.
Nothing may switch to reading the new columns until this sweep is clean.

Used by the integration test (tests/test_kernel_backfill.py) against the local
stack and by scripts/verify_kernel_backfill.py against any environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel import KernelViolation, resolve_schedule, schedule_from_columns
from app.models.itinerary import Itinerary, Node

_SAMPLE_CAP = 20


@dataclass
class DualReadReport:
    scheduled: int = 0
    verified: int = 0
    unconverted: int = 0  # starts_at set but schedule_kind still NULL
    malformed: int = 0  # columns violate the shape rules
    mismatched: int = 0  # resolves to a different instant than starts_at
    samples: list[str] = field(default_factory=list)  # capped problem details

    @property
    def clean(self) -> bool:
        return not (self.unconverted or self.malformed or self.mismatched)

    def _problem(self, detail: str) -> None:
        if len(self.samples) < _SAMPLE_CAP:
            self.samples.append(detail)


async def verify_dual_read(session: AsyncSession) -> DualReadReport:
    """Sweep every scheduled node and compare kernel resolution to starts_at."""
    report = DualReadReport()
    rows = await session.execute(
        select(Node, Itinerary.anchor_date)
        .join(Itinerary, Itinerary.id == Node.itinerary_id)
        .where(Node.starts_at.is_not(None))
    )
    for node, anchor_date in rows.tuples():
        rng = node.starts_at
        if rng is None:  # filtered in SQL; keeps the type-narrowing honest
            continue
        report.scheduled += 1
        if node.schedule_kind is None:
            report.unconverted += 1
            report._problem(f"{node.id}: unconverted")
            continue
        try:
            schedule = schedule_from_columns(
                schedule_kind=node.schedule_kind,
                start_day_offset=node.start_day_offset,
                start_date=node.start_date,
                start_wall_time=node.start_wall_time,
                start_tz=node.start_tz,
                end_day_offset=node.end_day_offset,
                end_date=node.end_date,
                end_wall_time=node.end_wall_time,
                end_tz=node.end_tz,
            )
        except KernelViolation as exc:
            report.malformed += 1
            report._problem(f"{node.id}: {exc.code}: {exc.message}")
            continue
        if schedule is None:
            report.malformed += 1
            report._problem(f"{node.id}: schedule row decoded to None")
            continue
        span = resolve_schedule(schedule, anchor_date)
        if span is None:
            report.mismatched += 1
            report._problem(f"{node.id}: relative row on an anchorless itinerary")
            continue
        stored_lower = rng.lower
        stored_upper = rng.upper
        if span.start != stored_lower or span.end != stored_upper:
            report.mismatched += 1
            report._problem(
                f"{node.id}: resolved [{span.start}, {span.end}) "
                f"!= stored [{stored_lower}, {stored_upper})"
            )
            continue
        report.verified += 1
    return report
