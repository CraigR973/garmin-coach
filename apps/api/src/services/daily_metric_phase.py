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

Two **field-level** exceptions sit on top of that, and neither is a change of
mind about which row a consumer means. ``index_day_aggregates_by_date`` (Batch
216) takes running local-day totals off the settled row because the wake row
holds a real but partial figure; ``index_post_activity_by_date`` (Batch 225)
takes ``vo2max`` off it because the wake row holds *nothing* — Garmin writes the
number after the day's activity. Both are named so the reason survives at the
call site; neither moves the recovery reads on the same date.
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
    "index_day_aggregates_by_date",
    "index_morning_by_date",
    "index_post_activity_by_date",
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


def index_post_activity_by_date(rows: Iterable[DailyMetric]) -> dict[date, DailyMetric]:
    """``{calendar_date: the row that can hold a post-activity reading}``.

    The mirror image of :func:`index_day_aggregates_by_date`, and a field-level
    exception for the opposite reason. VO2 max is not a running local-day total
    the wake row holds a *partial* copy of — Garmin recomputes it only after a
    qualifying activity, so on a two-phase date the wake row is structurally
    empty and the settled row is the only one that ever carries the number.
    Preferring morning here does not return a worse value, it returns ``None``:
    in production July holds 13 settled readings against **none** across its 30
    morning rows, and August 12 against 25 (measured 2026-08-25).

    The fallback to the morning row is load-bearing rather than defensive
    padding. Exactly one morning row has ever carried a ``vo2max`` — 2026-06-21,
    the first date two-phase writes existed — and a settled-only lookup would
    drop that reading and that date's whole sample. Recovery readings on the
    same date still come from :func:`index_morning_by_date` (Batch 205); this
    exception is for ``vo2max`` alone.
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
