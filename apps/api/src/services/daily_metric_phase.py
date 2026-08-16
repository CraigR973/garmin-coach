"""Choosing which observation of a day a consumer means (Batch 205 / CI191-02).

``daily_metrics`` holds up to two rows per date: the ``morning`` wake
observation the verdict was computed from, and the ``settled`` observation
Garmin lands on once the local day has closed. After a training day the two
diverge directionally — recovery debt higher, readiness lower — so a consumer
that does not say which one it means gets whichever row the query returned.

Every helper here collapses to **exactly one row per calendar date**, which is
the property the old unique constraint used to provide for free. Prefer these
over a bare ``select(DailyMetric)``: the failure mode this replaces is silent,
because ``{row.calendar_date: row for row in rows}`` still type-checks and still
returns a plausible number.

Which phase a consumer wants is a real decision, recorded at each call site:

* **morning** — anything comparing against, explaining, or aggregating the reads
  Mark was actually given: the personal baselines, the readiness history, the
  Red-morning cluster and its evidence, trends, reviews and insight drivers.
* **settled** — anything asking what a *whole day* cost once it was over:
  yesterday's training load at wake, and the "is Garmin data fresh?" check,
  which wants the newest observation of any phase.

Both directions fall back to the other phase when the preferred one is missing,
so a date with no stored morning read still contributes its settled row rather
than dropping out of a window entirely.
"""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import Case, case

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
    DailyMetric,
)

__all__ = [
    "index_morning_by_date",
    "index_settled_by_date",
    "morning_first_order",
    "prefer_morning",
    "prefer_settled",
    "settled_first_order",
]


def _collapse(rows: Iterable[DailyMetric], preferred: str) -> list[DailyMetric]:
    chosen: dict[date, DailyMetric] = {}
    for row in rows:
        current = chosen.get(row.calendar_date)
        if current is None or (row.phase == preferred and current.phase != preferred):
            chosen[row.calendar_date] = row
    return [chosen[day] for day in sorted(chosen)]


def prefer_morning(rows: Iterable[DailyMetric]) -> list[DailyMetric]:
    """One row per date, ascending — the wake observation wherever one exists."""
    return _collapse(rows, DAILY_METRIC_PHASE_MORNING)


def prefer_settled(rows: Iterable[DailyMetric]) -> list[DailyMetric]:
    """One row per date, ascending — the closed-day observation where one exists."""
    return _collapse(rows, DAILY_METRIC_PHASE_SETTLED)


def index_morning_by_date(rows: Iterable[DailyMetric]) -> dict[date, DailyMetric]:
    """``{calendar_date: wake observation}``, replacing an ambiguous dict comprehension."""
    return {row.calendar_date: row for row in prefer_morning(rows)}


def index_settled_by_date(rows: Iterable[DailyMetric]) -> dict[date, DailyMetric]:
    """``{calendar_date: closed-day observation}``."""
    return {row.calendar_date: row for row in prefer_settled(rows)}


def index_day_aggregates_by_date(rows: Iterable[DailyMetric]) -> dict[date, DailyMetric]:
    """``{calendar_date: the row whose local-day aggregates are finished}``.

    A field-level exception to "morning for retrospection", not a change of mind
    about the row. Stress and Body Battery are running local-day totals rather
    than point-in-time readings, so the wake row holds a real but *partial*
    figure — which is exactly what ``daily_metric_coverage`` already reports as
    ``incomplete`` and gates to ``None``. Taking them off the morning row would
    blank every historical day's value; taking them off the settled row is what
    those columns mean. Recovery readings on the same date still come from
    ``index_morning_by_date``.
    """
    return index_settled_by_date(rows)


def morning_first_order() -> Case[int]:
    """ORDER BY fragment putting the wake row ahead of the settled row.

    For single-date and ``limit(1)`` lookups, where collapsing in Python would
    mean fetching a row only to discard it.
    """
    return case((DailyMetric.phase == DAILY_METRIC_PHASE_MORNING, 0), else_=1)


def settled_first_order() -> Case[int]:
    """ORDER BY fragment putting the closed-day row ahead of the wake row."""
    return case((DailyMetric.phase == DAILY_METRIC_PHASE_SETTLED, 0), else_=1)
