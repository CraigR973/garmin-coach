"""Which morning read counts as *the* verdict for a date (Batch 205 / CI191-02).

``analyses`` deliberately keeps every historical morning row: a new check-in or
a new prompt version creates another one rather than editing the old. Reading
back "the verdict for that day" therefore needs a rule, and the rule used to be
*the newest row wins*. That made a stored verdict mutable — 2026-07-05 reads
``Amber@07:23 -> Green@22:03`` — and the later row was the one the Red-morning
cluster, the reviews and the block-progression trend all counted. A colour Mark
was never shown could silently replace the one he was.

The rule here is the last read that could still have come from the morning run:
the newest morning analysis generated at or before the local end of the
wake-detection window. A post-check-in regeneration lands inside that window and
rightly counts — the check-in is real evidence the first read lacked. An evening
regeneration does not.

This only decides *which stored row is counted*. It never recomputes a verdict,
and it cannot change one: the Green/Amber/Red ladder stays deterministic Python
in ``morning_analysis``, and nothing here writes.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.models.coaching import Analysis
from src.services.wake_detection import WINDOW_END

#: A wake-triggered read cannot be produced after the wake window closes, so
#: this is the latest a stored row can still be the read Mark woke up to.
MORNING_READ_CUTOFF: time = WINDOW_END

__all__ = ["MORNING_READ_CUTOFF", "delivered_verdicts"]


def _local_time(value: datetime, timezone_name: str) -> time:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC  # type: ignore[assignment]
    return value.replace(tzinfo=UTC).astimezone(zone).time()


def delivered_verdicts(
    rows: Iterable[Analysis],
    *,
    timezone_name: str,
) -> dict[date, str | None]:
    """``{subject_date: the verdict that date's morning read actually carried}``.

    ``rows`` are morning analyses in any order; only ``subject_date``,
    ``generated_at_utc``, ``created_at`` and ``verdict`` are read. A date whose
    every read falls after the cutoff — a morning missed entirely and generated
    late — keeps its *earliest* read, which is the closest thing to the one Mark
    was given, rather than dropping out of the window.
    """
    by_date: dict[date, list[Analysis]] = {}
    for row in rows:
        by_date.setdefault(row.subject_date, []).append(row)

    delivered: dict[date, str | None] = {}
    for subject_date, day_rows in by_date.items():
        day_rows.sort(key=lambda row: (row.generated_at_utc, row.created_at))
        in_window = [
            row
            for row in day_rows
            if _local_time(row.generated_at_utc, timezone_name) <= MORNING_READ_CUTOFF
        ]
        chosen = in_window[-1] if in_window else day_rows[0]
        delivered[subject_date] = chosen.verdict
    return delivered
