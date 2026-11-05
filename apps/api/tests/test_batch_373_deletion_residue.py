"""Class-wide SQL NULL guard and historical packet boundary (Batch 373)."""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.dialects.postgresql import JSONB

from src.models import Base
from src.services.verdict_grading import ENGINE_GRADED, ENGINE_LADDER, stored_engine


def test_every_nullable_jsonb_column_stores_python_none_as_sql_null() -> None:
    columns = [
        c
        for table in Base.metadata.tables.values()
        for c in table.columns
        if c.nullable and isinstance(c.type, JSONB)
    ]
    assert columns, "The class guard must inspect registered model columns"
    assert not [str(c) for c in columns if not c.type.none_as_null]


@pytest.mark.parametrize("day", ["2026-10-01", "2026-11-05"])
def test_missing_engine_after_retirement_is_logged_and_uses_graded_actions(day: str) -> None:
    with patch("src.services.verdict_grading.log") as log:
        assert stored_engine({"subjectDate": day, "verdict": {}}) == ENGINE_GRADED
    log.error.assert_called_once_with("stored_morning_missing_engine", subject_date=day)


@pytest.mark.parametrize("day", ["2026-09-29", "2026-09-30", None, "bad-date"])
def test_historical_or_undated_packet_keeps_its_reader(day: str | None) -> None:
    with patch("src.services.verdict_grading.log") as log:
        assert stored_engine({"subjectDate": day, "verdict": {}}) == ENGINE_LADDER
    log.error.assert_not_called()


def test_an_explicit_engine_is_preserved_without_logging() -> None:
    with patch("src.services.verdict_grading.log") as log:
        assert (
            stored_engine(
                {"subjectDate": date(2026, 11, 5).isoformat(), "verdict": {"engine": ENGINE_GRADED}}
            )
            == ENGINE_GRADED
        )
    log.error.assert_not_called()
