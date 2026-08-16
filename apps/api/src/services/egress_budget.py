"""App-level proxy for Supabase's shared egress budget (Batch 204, DS190-07).

Supabase has no public Management API for egress bytes — only the account
dashboard exposes the org-wide meter (confirmed against Supabase's docs and
community tooling while authoring this batch). This module is therefore a
**leading-indicator proxy**, not the real meter: it sums the response bytes
this API serves — which are built from ``coach`` schema reads moments
earlier, so roughly track the same Postgres-egress that bills — plus the
day's backup dump size (the one *exact* known contributor, see
``services/backup.py``). A stage crossing here means "go check the Supabase
dashboard," not "the org is definitely over."

``BUDGET_BYTES`` is the org-wide free-plan cap already blown once
(2026-08-04, DECISIONS #262) and shared with a co-tenant app on the same
Supabase project — see ``docs/runbooks/sync-and-analysis.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

BUDGET_BYTES = 5_500_000_000

STAGE_ORDINAL: dict[str, int] = {"ok": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True, slots=True)
class _Stage:
    name: str
    threshold: float


# Checked highest-first so the first match wins.
_STAGES: tuple[_Stage, ...] = (
    _Stage("critical", 0.85),
    _Stage("warning", 0.5),
)


def evaluate_stage(bytes_used_today: int, budget_bytes: int = BUDGET_BYTES) -> str:
    """Return the highest staged threshold ``bytes_used_today`` has crossed."""

    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    fraction = max(bytes_used_today, 0) / budget_bytes
    for stage in _STAGES:
        if fraction >= stage.threshold:
            return stage.name
    return "ok"


class DailyByteCounter:
    """Process-local, UTC-day-scoped counter of response bytes served.

    Not durable across a container restart — Railway restarts the API more
    than once a day (DS190-01). ``drain()`` is called every ~15 minutes by
    the scheduled ``egress-budget`` job, whose result lands in ``job_runs``;
    that periodic flush, not this in-memory value, is what survives a
    restart. A restart between flushes loses only the delta since the last
    one, not the whole day.
    """

    def __init__(self) -> None:
        self._day: date = datetime.now(UTC).date()
        self._bytes = 0

    def add(self, n: int) -> None:
        if n <= 0:
            return
        self._roll_if_new_day()
        self._bytes += n

    def drain(self) -> int:
        """Return and reset the bytes accumulated since the last drain."""

        self._roll_if_new_day()
        value = self._bytes
        self._bytes = 0
        return value

    def _roll_if_new_day(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day = today
            self._bytes = 0


response_byte_counter = DailyByteCounter()
