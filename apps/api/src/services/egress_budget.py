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

# Batch 247 (DS237-02): the *other* Supabase free-plan cap, and the one this app
# has already hit the hard version of. DECISIONS #93 records the 2026-06-28
# backfill overshooting to ~625 MB and filling the physical disk, at which point
# ``VACUUM FULL`` could not run because there was no room to write the compacted
# copy. Egress got a meter after its incident; storage — which had already caused
# one — got nothing until now.
STORAGE_BUDGET_BYTES = 500_000_000

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

# Storage crosses its thresholds far more slowly than egress and cannot be
# recovered by waiting for a billing cycle, so it warns earlier and leaves more
# room to act. At the measured ~1.85 MB/day, 75% is roughly a fortnight of notice
# and 90% is roughly four days — and the escape from a *full* disk is a
# dump/truncate/reload, not a flag.
_STORAGE_STAGES: tuple[_Stage, ...] = (
    _Stage("critical", 0.90),
    _Stage("warning", 0.75),
)


def evaluate_stage(bytes_used: int, budget_bytes: int = BUDGET_BYTES) -> str:
    """Return the highest staged threshold ``bytes_used`` has crossed.

    Batch 247 (DS237-03, Defect C) renamed the parameter, because the old name
    said ``bytes_used_today`` and the budget it is measured against is the
    org-wide **monthly** cap. Warning therefore fired at 2.75 GB *in a single
    day*, while a steady 200 MB/day — 6 GB/month, over the cap — scored 0.036 and
    read ``ok`` for ever. The caller now passes month-to-date.
    """

    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    fraction = max(bytes_used, 0) / budget_bytes
    for stage in _STAGES:
        if fraction >= stage.threshold:
            return stage.name
    return "ok"


def evaluate_storage_stage(bytes_used: int, budget_bytes: int = STORAGE_BUDGET_BYTES) -> str:
    """Return the highest storage threshold ``pg_database_size`` has crossed."""

    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    fraction = max(bytes_used, 0) / budget_bytes
    for stage in _STORAGE_STAGES:
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
