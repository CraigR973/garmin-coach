"""Wake detection — the pure decision core for the wake-triggered morning verdict.

No I/O. The scheduler feeds this the parsed Garmin sleep reading plus the
``sleepEnd`` it persisted on the previous poll, and gets back a decision
(``fire`` / ``wait`` / ``nap_ignored``) together with the ``sleepEnd`` to
persist for the next poll's stability comparison.

The morning run used to fire on a fixed 06:30 cron, which — for Mark — fired
~2 h before he actually woke on 98.6 % of mornings, reading a pre-dawn placeholder
for time-of-day-live Training Readiness and an unfinalized sleep score. Instead we
poll today's sleep every ~15 min within a morning window and fire when his wake is
*stable*, so the verdict is built from his finalized overnight metrics.

The key correctness point is the **back-to-sleep stability guard**: Garmin records
one consolidated overnight session (brief awakenings are awake epochs *inside* it),
but a genuine two-block night can close the first session early. So we never fire on
first detection — only once today's ``sleepEnd`` has survived a prior poll unchanged
*and* sat ``settle_min`` in the past, clearing a duration floor that excludes naps.
A later ``sleepEnd`` means he drifted back to sleep, so we keep waiting until it
settles at his true get-up. A ~09:30 backstop guarantees a verdict regardless.

See docs/designs/wake-triggered-morning.md for the full rationale + test matrix.
Calibrated to Mark's 363-night backfill (median wake 08:22, range 03:45–09:24).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

# --- Calibration (Europe/London local) -------------------------------------
# Window brackets his real wake distribution: start before the earliest riser
# (03:45), end past the latest (09:24). Backstop clears p90 (08:50) with margin.
WINDOW_START = time(3, 30)
WINDOW_END = time(10, 0)
BACKSTOP = time(9, 30)
# Duration floor excludes a morning nap from ever counting as the wake; settle is
# ~2 polls so a quick wake-then-resleep that moves sleepEnd is caught first.
DURATION_FLOOR_MIN = 180
SETTLE_MIN = 20

# Audit-row identity in the ``analyses`` table (migration-free state, mirrors the
# nudge/insight audit rows). One row per (user, day) tracks the last-seen sleepEnd.
WAKE_CHECK_ANALYSIS_TYPE = "wake_check"
WAKE_CHECK_PROMPT_VERSION = "wake-check-v1-2026-06-24"

WakeAction = Literal["fire", "wait", "nap_ignored"]


@dataclass(frozen=True)
class SleepReading:
    """Normalized view of today's Garmin sleep session for the wake decision.

    Built from :func:`src.services.garmin_sync.parse_sleep_fields` output so the
    decision core stays decoupled from both the raw Garmin JSON and the ORM.
    ``sleep_end_utc`` is UTC-naive, matching ``parse_sleep_fields``.
    """

    calendar_date: date | None
    sleep_end_utc: datetime | None
    duration_min: int | None

    @classmethod
    def from_sleep_fields(cls, fields: Mapping[str, Any] | None) -> SleepReading | None:
        """Adapt ``parse_sleep_fields`` output; ``None`` when there is no session."""
        if not fields:
            return None
        duration_sec = fields.get("duration_sec")
        duration_min = round(duration_sec / 60) if isinstance(duration_sec, int | float) else None
        return cls(
            calendar_date=fields.get("calendar_date"),
            sleep_end_utc=fields.get("sleep_end_utc"),
            duration_min=duration_min,
        )


@dataclass(frozen=True)
class WakeDecision:
    """A poll's outcome: what to do now + the sleepEnd to persist for next poll."""

    action: WakeAction
    sleep_end_to_persist: datetime | None
    reason: str


def is_morning_ready(
    *,
    today: date,
    sleep: SleepReading | None,
    prev_sleep_end: datetime | None,
    now: datetime,
    backstop: time = BACKSTOP,
    duration_floor_min: int = DURATION_FLOOR_MIN,
    settle_min: int = SETTLE_MIN,
) -> WakeDecision:
    """Decide whether to fire today's morning verdict now. Pure — no I/O.

    ``now`` must be timezone-aware in the user's local zone (the wall-clock time
    is compared against ``backstop``; the UTC instant against ``sleep_end_utc``).
    """
    now_utc = now.astimezone(UTC).replace(tzinfo=None)
    past_backstop = now.time() >= backstop

    sleep_end = sleep.sleep_end_utc if sleep is not None else None
    is_today = sleep is not None and sleep.calendar_date == today
    finalized = is_today and sleep_end is not None and sleep_end <= now_utc
    is_nap = (
        finalized
        and sleep is not None
        and sleep.duration_min is not None
        and sleep.duration_min < duration_floor_min
    )

    # Backstop: always produce a verdict by the fallback time, on whatever data
    # exists (watch not worn / never synced / two-block night that never settled).
    if past_backstop:
        persist = sleep_end if (finalized and not is_nap) else prev_sleep_end
        return WakeDecision("fire", persist, "backstop")

    # A short session is a nap, not the real wake — keep waiting, and don't let it
    # overwrite the real session's last-seen sleepEnd.
    if is_nap:
        return WakeDecision("nap_ignored", prev_sleep_end, "nap_below_floor")

    # Nothing finalized for today yet (still asleep / not synced) — wait.
    if not finalized:
        return WakeDecision("wait", prev_sleep_end, "unfinalized")

    assert sleep_end is not None  # narrowed by ``finalized``

    # Stability guard: fire only once the same sleepEnd has survived a prior poll
    # AND the wake is at least settle_min in the past.
    stable = prev_sleep_end is not None and sleep_end == prev_sleep_end
    settled = (now_utc - sleep_end) >= timedelta(minutes=settle_min)
    if stable and settled:
        return WakeDecision("fire", sleep_end, "stable_wake")

    # First sighting, a later sleepEnd (back-to-sleep), or not yet settled —
    # persist the current value and wait for the next poll.
    return WakeDecision("wait", sleep_end, "awaiting_stability")
