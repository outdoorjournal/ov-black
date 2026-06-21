"""Pure-Python guards for the Analyze ORM models (Phase 5 / B5).

Mirrors ``test_itinerary_models.py``: assert the new Postgres ENUMs bind with
``create_type=False`` (the migration owns DDL — D003) and that the Python enum
values are byte-identical to ``0017_async_analyze.sql`` so the
``values_callable`` rendering round-trips.
"""

from __future__ import annotations

from app.models import AnalysisDepth, AnalysisStatus, FindingSeverity
from app.models.analysis import (
    Analysis,
    AnalysisFinding,
    analysis_depth_enum,
    analysis_status_enum,
    finding_severity_enum,
)


def test_saenum_create_type_is_false_for_all_analyze_enums() -> None:
    for sa_enum in (
        analysis_status_enum,
        analysis_depth_enum,
        finding_severity_enum,
    ):
        assert sa_enum.create_type is False, (
            f"Postgres ENUM {sa_enum.name!r} must have create_type=False so "
            "SQLAlchemy never emits CREATE TYPE (migration owns it)."
        )
        assert sa_enum.schema == "public"


def test_analyze_enum_values_match_migration() -> None:
    assert [m.value for m in AnalysisStatus] == [
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    assert [m.value for m in AnalysisDepth] == ["shallow", "standard", "deep"]
    assert [m.value for m in FindingSeverity] == [
        "info",
        "suggest",
        "warn",
        "block",
    ]


def test_tablenames() -> None:
    assert Analysis.__tablename__ == "analyses"
    assert AnalysisFinding.__tablename__ == "analysis_findings"
