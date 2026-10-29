"""Batch 319: progress has a signal.

319.2 fitness drift is read only from fixed-power rides, and the weekly review stops
proposing an FTP from watts per heartbeat across every ride; 319.3 a "ready to progress"
note after three hard sessions in a row on target with fresh next mornings, which changes
nothing. Each failed on 322's branch first.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.services import reviews
from src.services.progress_signal import (
    READY_NOTE,
    STATUS_IMPROVING,
    STATUS_NOT_ENOUGH,
    STATUS_SLIPPING,
    STATUS_STEADY,
    FixedPowerRide,
    HardSession,
    fitness_drift,
    hard_sessions_from_packets,
    progress_signal,
    rides_from_packets,
)

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-319-wording.md"
AS_OF = date(2026, 10, 28)


def _rides(before: float, after: float, watts: float = 184) -> list[FixedPowerRide]:
    return [
        FixedPowerRide(AS_OF - timedelta(days=day), watts, after if day < 28 else before)
        for day in (2, 9, 16, 30, 37, 44)
    ]


def test_heart_rate_at_the_same_power_says_how_fitness_is_moving() -> None:
    assert fitness_drift(_rides(116, 111), as_of=AS_OF)["status"] == STATUS_IMPROVING
    assert fitness_drift(_rides(111, 115), as_of=AS_OF)["status"] == STATUS_SLIPPING
    steady = fitness_drift(_rides(112, 113), as_of=AS_OF)
    assert (steady["status"], steady["powerWatts"]) == (STATUS_STEADY, 184)
    assert fitness_drift(_rides(116, 111)[:4], as_of=AS_OF)["status"] == STATUS_NOT_ENOUGH


def test_a_ride_at_another_power_is_not_compared() -> None:
    rides = [*_rides(116, 116), FixedPowerRide(AS_OF - timedelta(days=1), 230, 140)]
    assert fitness_drift(rides, as_of=AS_OF)["heartRateAfter"] == 116


def _hard(days_ago: int, share_hit: int, fresh: bool | None) -> HardSession:
    return HardSession(AS_OF - timedelta(days=days_ago), 10, share_hit, fresh)


def test_three_hard_sessions_on_target_with_fresh_mornings_bring_the_note() -> None:
    ready = progress_signal(
        [], [_hard(8, 9, True), _hard(5, 10, True), _hard(1, 9, True)], as_of=AS_OF
    )
    assert ready["readyToProgress"] is True
    assert ready["note"] == READY_NOTE
    assert ready["changesNothing"] is True
    tired = progress_signal(
        [], [_hard(8, 9, True), _hard(5, 10, False), _hard(1, 9, True)], as_of=AS_OF
    )
    assert (tired["readyToProgress"], tired["note"]) == (False, None)
    missed = progress_signal(
        [], [_hard(8, 9, True), _hard(5, 8, True), _hard(1, 9, True)], as_of=AS_OF
    )
    assert missed["readyToProgress"] is False


def _interval(minutes: float, target: float, pct: float, adherence: str | None) -> dict[str, Any]:
    return {
        "durationSec": minutes * 60,
        "avgPowerWatts": 184,
        "avgHeartRateBpm": 112,
        "pctFtp": pct,
        "targetPctFtpLow": target,
        "targetPctFtpHigh": target,
        "adherence": adherence,
    }


def test_stored_ride_reads_feed_both_halves() -> None:
    zone2 = (AS_OF - timedelta(days=1), [_interval(35, 66, 66, "on")])
    sweet = (
        AS_OF - timedelta(days=2),
        [_interval(20, 89, 89, "on"), _interval(20, 89, 85, "under")],
    )
    assert [ride.power_watts for ride in rides_from_packets([zone2, sweet])] == [184.0]
    [session] = hard_sessions_from_packets([zone2, sweet], {AS_OF - timedelta(days=1): "Green"})
    assert (session.work_intervals, session.on_target, session.fresh_next_morning) == (2, 1, True)


def test_the_review_proposes_no_ftp_and_reads_the_signal() -> None:
    assert '"ftpDrift"' not in inspect.getsource(reviews._build_packet)
    assert reviews.PROGRESS_SIGNAL_RULE in reviews.SYSTEM_PROMPT
    assert "never estimate or propose an FTP" in reviews.PROGRESS_SIGNAL_RULE
    assert reviews.PROMPT_VERSION == "reviews-v13-2026-10-29"


def test_the_note_is_in_the_draft() -> None:
    assert READY_NOTE in DRAFT.read_text(encoding="utf-8")
