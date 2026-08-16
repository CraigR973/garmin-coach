from __future__ import annotations

from datetime import date

from src.services.egress_budget import (
    BUDGET_BYTES,
    STAGE_ORDINAL,
    DailyByteCounter,
    evaluate_stage,
)


def test_evaluate_stage_ok_below_warning() -> None:
    assert evaluate_stage(0) == "ok"
    assert evaluate_stage(int(BUDGET_BYTES * 0.49)) == "ok"


def test_evaluate_stage_warning_at_50_percent() -> None:
    assert evaluate_stage(int(BUDGET_BYTES * 0.5)) == "warning"
    assert evaluate_stage(int(BUDGET_BYTES * 0.84)) == "warning"


def test_evaluate_stage_critical_at_85_percent() -> None:
    assert evaluate_stage(int(BUDGET_BYTES * 0.85)) == "critical"
    assert evaluate_stage(BUDGET_BYTES * 2) == "critical"


def test_evaluate_stage_ordinal_is_monotonic() -> None:
    assert STAGE_ORDINAL["ok"] < STAGE_ORDINAL["warning"] < STAGE_ORDINAL["critical"]


def test_daily_byte_counter_accumulates_and_drains() -> None:
    counter = DailyByteCounter()
    counter.add(100)
    counter.add(250)
    assert counter.drain() == 350
    # Drained counter starts back at zero.
    assert counter.drain() == 0


def test_daily_byte_counter_ignores_non_positive() -> None:
    counter = DailyByteCounter()
    counter.add(0)
    counter.add(-10)
    assert counter.drain() == 0


def test_daily_byte_counter_rolls_over_on_new_day() -> None:
    counter = DailyByteCounter()
    counter.add(500)
    # Simulate the day having rolled over since the last add/drain.
    counter._day = date(2000, 1, 1)
    assert counter.drain() == 0


def test_daily_byte_counter_add_after_rollover_starts_fresh() -> None:
    counter = DailyByteCounter()
    counter.add(500)
    counter._day = date(2000, 1, 1)
    counter.add(10)
    assert counter.drain() == 10
