"""Batch 289 — the coach sees the session the morning left.

The fixtures are Mark's own stored morning reads and delivery records for 19–26 Sep
2026 (production, read 2026-09-26), reduced to the fields the section is projected
from. Asked from Home at 11:34 BST on 24 Sep, the coach called the morning's
sweet spot "unmodified"; the read had cut it from 94 minutes to 47 with the hardest
interval at 60%, and Mark had approved that at 09:00.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.dialects import postgresql

from src.services.bulk_history_reads import select_morning_calls
from src.services.chat_context import _DROP_ORDER, _FETCHABLE_OMISSIONS, APP_STATE_CHAR_BUDGET
from src.services.coach_tools import TOOL_NAMES
from src.services.recent_mornings import (
    MORNING_CALL_ADJUSTED,
    MORNING_CALL_NO_BIKE,
    MORNING_CALL_UNCHANGED,
    ON_DEVICE_APPROVED,
    ON_DEVICE_NOT_OFFERED,
    ON_DEVICE_OFFERED_NOT_APPROVED,
    RECENT_MORNINGS_DAYS,
    DeliveryAudit,
    MorningCall,
    build_recent_mornings,
    load_recent_mornings,
)

HRV_REASON = "HRV is below baseline and marked low/unbalanced."
NOT_SKIPPED: dict[str, Any] = {
    "reason": None,
    "isRestDay": False,
    "holidayWindows": [],
    "insideHolidayWindow": False,
    "allPlannedWorkoutsSkipped": False,
}

SWEET_SPOT_ID = "fdc7072a-3359-4885-ba9c-06ecd08335d2"
Z2_23_ID = "4412a85a-9f34-4cb4-ab1c-c6133541bfcc"
EASY_Z2_19_ID = "3008c544-5e98-47ba-86f4-6e2d0c82af2b"
LONG_Z2_26_ID = "e8bd3d6e-ef92-4dd0-a23c-69feaa584468"


def _workout(
    workout_id: str, title: str, workout_type: str, intensity: str, minutes: int, basis: str
) -> dict[str, Any]:
    return {
        "id": workout_id,
        "title": title,
        "workoutType": workout_type,
        "intensityTarget": intensity,
        "plannedDurationMin": minutes,
        "basis": basis,
        "status": "planned",
        # The stored rows also carry the structured workout; the section never reads it.
        "structuredWorkout": {"format": "bike", "steps": []},
    }


def _adjustment(
    workout_id: str, planned_min: int, adjusted_min: int, planned_pct: int, adjusted_pct: int
) -> dict[str, Any]:
    return {
        "source": "deterministic",
        "changed": True,
        "verdict": "Red",
        "removedHit": False,
        "plannedWorkoutId": workout_id,
        "plannedDurationMin": planned_min,
        "adjustedDurationMin": adjusted_min,
        "plannedWorkPowerPct": planned_pct,
        "adjustedWorkPowerPct": adjusted_pct,
        "classificationImpact": "none",
    }


def _morning(
    day: date,
    generated: datetime,
    verdict: str,
    reasons: list[str],
    workouts: list[dict[str, Any]],
    *,
    adjustment: dict[str, Any] | None = None,
    no_bike: bool = False,
) -> MorningCall:
    return MorningCall(
        subject_date=day,
        generated_at_utc=generated,
        verdict=verdict,
        reasons=reasons,
        verdict_adjustment=adjustment,
        requires_bike_rest=no_bike,
        rest_day=NOT_SKIPPED,
        planned_workouts=workouts,
    )


PLAN = "imported from your training plan"
MOVED = "moved to this day from the app's Today card"

MORNINGS = [
    _morning(
        date(2026, 9, 19),
        datetime(2026, 9, 19, 8, 17, 27),
        "Red",
        [HRV_REASON],
        [_workout(EASY_Z2_19_ID, "Easy Z2", "bike_endurance", "Zone 2 ~65–72% FTP", 90, MOVED)],
        adjustment=_adjustment(EASY_Z2_19_ID, 90, 63, 62, 62),
    ),
    _morning(
        date(2026, 9, 20),
        datetime(2026, 9, 20, 8, 37, 46),
        "Green",
        ["Sleep, measured HRV, and the current subjective signal clear the green rule."],
        [
            _workout(
                "bc0f6d44-3b75-435a-871e-6b78fe77d1a3",
                "Easy Z2",
                "bike_endurance",
                "Zone 2 ~65–72% FTP",
                45,
                MOVED,
            )
        ],
    ),
    _morning(
        date(2026, 9, 21),
        datetime(2026, 9, 21, 8, 58, 19),
        "Red",
        [
            HRV_REASON,
            "Overnight HRV sets an Amber ceiling: 37 ms is below the acute personal floor "
            "of 39.7 ms.",
        ],
        [],
        no_bike=True,
    ),
    _morning(
        date(2026, 9, 22),
        datetime(2026, 9, 22, 8, 58, 50),
        "Red",
        [
            HRV_REASON,
            "Overnight HRV sets an Amber ceiling: 39 ms is below the acute personal floor "
            "of 39.6 ms.",
        ],
        [
            _workout(
                "c2bb371a-6499-4aad-8bc1-47870639bb33",
                "Dumbbells (full-body)",
                "strength_maintenance",
                "Dumbbell circuit",
                22,
                MOVED,
            ),
            _workout(
                "a9046266-0dec-40c1-b842-c92801eac32b",
                "VO₂ (5 × 2:30 @ 119%)",
                "bike_vo2",
                "119% FTP intervals",
                57,
                "edited in the app's interval editor",
            ),
        ],
        no_bike=True,
    ),
    _morning(
        date(2026, 9, 23),
        datetime(2026, 9, 23, 9, 5, 16),
        "Red",
        [HRV_REASON],
        [_workout(Z2_23_ID, "Z2", "bike_endurance", "Zone 2 ~65–72% FTP", 75, PLAN)],
        adjustment=_adjustment(Z2_23_ID, 75, 52, 67, 67),
    ),
    _morning(
        date(2026, 9, 24),
        datetime(2026, 9, 24, 7, 41, 26),
        "Red",
        [HRV_REASON],
        [
            _workout(
                SWEET_SPOT_ID,
                "Sweet Spot (3 × 20 min @ 89%)",
                "bike_sweet_spot",
                "Sweet Spot ~89% FTP",
                94,
                PLAN,
            )
        ],
        adjustment=_adjustment(SWEET_SPOT_ID, 94, 47, 100, 60),
    ),
    _morning(date(2026, 9, 25), datetime(2026, 9, 25, 10, 1, 29), "Red", [HRV_REASON], []),
    _morning(
        date(2026, 9, 26),
        datetime(2026, 9, 26, 7, 41, 41),
        "Red",
        [
            HRV_REASON,
            "Resting heart rate sets an Amber ceiling: it has been above the personal upper "
            "quartile of 45 bpm for two mornings.",
        ],
        [
            _workout(LONG_Z2_26_ID, "Long Z2", "bike_endurance", "Zone 2 ~65–72% FTP", 120, MOVED),
            _workout(
                "25033e9f-f1be-4391-986e-9aa74e6a650c",
                "Bodyweight",
                "strength_maintenance",
                "Bodyweight circuit",
                15,
                PLAN,
            ),
        ],
        no_bike=True,
    ),
]

AUDITS = [
    DeliveryAudit(
        date(2026, 9, 19),
        "workout_proposed",
        datetime(2026, 9, 19, 8, 17, 28),
        f"red-regen:{EASY_Z2_19_ID}:v2",
    ),
    DeliveryAudit(
        date(2026, 9, 23),
        "workout_proposed",
        datetime(2026, 9, 23, 9, 5, 17),
        f"red-regen:{Z2_23_ID}:v1",
    ),
    DeliveryAudit(
        date(2026, 9, 23),
        "workout_pushed",
        datetime(2026, 9, 23, 9, 47, 30),
        f"approve:{Z2_23_ID}:v1",
    ),
    DeliveryAudit(
        date(2026, 9, 24),
        "workout_proposed",
        datetime(2026, 9, 24, 7, 41, 27),
        f"red-regen:{SWEET_SPOT_ID}:v1",
    ),
    DeliveryAudit(
        date(2026, 9, 24),
        "workout_pushed",
        datetime(2026, 9, 24, 8, 0, 49),
        f"approve:{SWEET_SPOT_ID}:v1",
    ),
    DeliveryAudit(
        date(2026, 9, 26),
        "workout_proposed",
        datetime(2026, 9, 26, 7, 41, 42),
        f"red-regen:{LONG_Z2_26_ID}:v4",
    ),
]


def _days(today: date, mornings: list[MorningCall] = MORNINGS) -> dict[str, dict[str, Any]]:
    section = build_recent_mornings(today=today, mornings=mornings, audits=AUDITS)
    return {day["date"]: day for day in section["days"]}


def test_24_sep_carries_the_cut_beside_the_plan_with_its_reason_and_his_approval() -> None:
    """The 11:34 question: 47 minutes at 60% beside 94 minutes, and why (289.4)."""

    day = _days(date(2026, 9, 24))["2026-09-24"]

    assert day["morningRead"] is True
    assert day["verdict"] == "Red"
    assert day["reasons"] == [HRV_REASON]
    (session,) = day["sessions"]
    assert session["title"] == "Sweet Spot (3 × 20 min @ 89%)"
    assert session["planned"] == {
        "durationMin": 94,
        "intensity": "Sweet Spot ~89% FTP",
        "hardestIntervalPctFtp": 100,
    }
    assert session["morningCall"] == MORNING_CALL_ADJUSTED
    assert session["adjusted"] == {"durationMin": 47, "hardestIntervalPctFtp": 60}
    assert session["onHisDevice"] == ON_DEVICE_APPROVED
    assert session["approvedAtUtc"] == "2026-09-24T08:00:49Z"


def test_the_day_before_carries_its_own_cut() -> None:
    day = _days(date(2026, 9, 24))["2026-09-23"]

    (session,) = day["sessions"]
    assert session["morningCall"] == MORNING_CALL_ADJUSTED
    assert (session["planned"]["durationMin"], session["adjusted"]["durationMin"]) == (75, 52)
    assert session["adjusted"]["hardestIntervalPctFtp"] == 67
    assert session["onHisDevice"] == ON_DEVICE_APPROVED


def test_a_day_with_no_adjustment_shows_the_prescription_unchanged() -> None:
    day = _days(date(2026, 9, 24))["2026-09-20"]

    assert day["verdict"] == "Green"
    (session,) = day["sessions"]
    assert session["morningCall"] == MORNING_CALL_UNCHANGED
    assert session["planned"] == {"durationMin": 45, "intensity": "Zone 2 ~65–72% FTP"}
    assert "adjusted" not in session
    assert "onHisDevice" not in session


def test_a_cut_he_never_approved_says_the_planned_session_stayed() -> None:
    """19 Sep: 90 → 63 minutes offered and never approved."""

    day = _days(date(2026, 9, 25))["2026-09-19"]

    (session,) = day["sessions"]
    assert session["morningCall"] == MORNING_CALL_ADJUSTED
    assert session["onHisDevice"] == ON_DEVICE_OFFERED_NOT_APPROVED
    assert "approvedAtUtc" not in session


def test_a_cut_the_rail_never_offered_says_so() -> None:
    audits_without_offer = [a for a in AUDITS if a.subject_date != date(2026, 9, 24)]
    section = build_recent_mornings(
        today=date(2026, 9, 24), mornings=MORNINGS, audits=audits_without_offer
    )
    (session,) = section["days"][0]["sessions"]
    assert session["onHisDevice"] == ON_DEVICE_NOT_OFFERED


def test_an_approval_before_the_offer_is_not_an_approval_of_it() -> None:
    early = DeliveryAudit(
        date(2026, 9, 24),
        "workout_pushed",
        datetime(2026, 9, 24, 6, 0),
        f"approve:{SWEET_SPOT_ID}:v1",
    )
    offer = next(a for a in AUDITS if a.tag == f"red-regen:{SWEET_SPOT_ID}:v1")
    section = build_recent_mornings(
        today=date(2026, 9, 24), mornings=MORNINGS, audits=[early, offer]
    )
    (session,) = section["days"][0]["sessions"]
    assert session["onHisDevice"] == ON_DEVICE_OFFERED_NOT_APPROVED


def test_a_morning_that_ruled_out_riding_is_not_read_as_unchanged() -> None:
    """21, 22 and 26 Sep carry no adjustment because riding was ruled out."""

    days = _days(date(2026, 9, 26))
    vo2 = next(s for s in days["2026-09-22"]["sessions"] if s["workoutType"] == "bike_vo2")
    dumbbells = next(
        s for s in days["2026-09-22"]["sessions"] if s["workoutType"] == "strength_maintenance"
    )

    assert days["2026-09-22"]["noBikeAdvised"] is True
    assert vo2["morningCall"] == MORNING_CALL_NO_BIKE
    assert dumbbells["morningCall"] == MORNING_CALL_UNCHANGED
    assert days["2026-09-21"]["noBikeAdvised"] is True
    assert days["2026-09-21"]["sessions"] == []


def test_an_eased_ride_offered_on_a_no_bike_morning_is_named() -> None:
    """26 Sep: the brief says take the day off the bike; the rail still offered one."""

    day = _days(date(2026, 9, 26))["2026-09-26"]
    long_z2 = next(s for s in day["sessions"] if s["title"] == "Long Z2")

    assert long_z2["morningCall"] == MORNING_CALL_NO_BIKE
    assert long_z2["easedVersionOffered"] is True
    assert long_z2["onHisDevice"] == ON_DEVICE_OFFERED_NOT_APPROVED


def test_seven_days_newest_first_and_a_day_without_a_read_says_so() -> None:
    section = build_recent_mornings(today=date(2026, 9, 27), mornings=MORNINGS, audits=AUDITS)

    dates = [day["date"] for day in section["days"]]
    assert len(dates) == RECENT_MORNINGS_DAYS == 7
    assert dates[0] == "2026-09-27"
    assert dates[-1] == "2026-09-21"
    assert section["days"][0] == {"date": "2026-09-27", "morningRead": False}
    assert "Check here before telling Mark a session was unchanged" in section["meaning"]
    assert "never name a rule that is not listed" in section["meaning"]


def test_the_latest_read_of_a_day_is_the_one_that_counts() -> None:
    earlier = _morning(
        date(2026, 9, 24),
        datetime(2026, 9, 24, 6, 0),
        "Amber",
        ["An earlier reason."],
        MORNINGS[5].planned_workouts,
    )
    day = _days(date(2026, 9, 24), [earlier, *MORNINGS])["2026-09-24"]

    assert day["verdict"] == "Red"
    assert day["reasons"] == [HRV_REASON]


def test_the_real_week_fits_the_room_the_block_has() -> None:
    """Measured on production 2026-09-26 with the section present, untrimmed: 50,757
    characters unanchored and 51,167 on that morning's brief; 55,502 replaying the
    24 Sep question (an upper bound — it counts check-ins logged after 11:34).

    The ordinary blocks keep at least the 8,135 characters of headroom Batch 256
    sized for the unanchored block, and the busy day is not trimmed at all.
    """

    section = build_recent_mornings(today=date(2026, 9, 26), mornings=MORNINGS, audits=AUDITS)
    size = len(json.dumps(section, ensure_ascii=True, sort_keys=True, default=str))

    assert size < 5_000
    assert APP_STATE_CHAR_BUDGET - 51_167 >= 8_135
    assert APP_STATE_CHAR_BUDGET > 55_502


def test_the_section_is_dropped_late_and_can_be_fetched_back() -> None:
    assert _DROP_ORDER.index("recentMornings") > _DROP_ORDER.index("sleepHistory")
    assert _DROP_ORDER.index("recentMornings") < _DROP_ORDER.index("knowledgeBase")
    assert _FETCHABLE_OMISSIONS["recentMornings"] == "get_read"
    assert "get_read" in TOOL_NAMES


# --------------------------------------------------------------------------
# The wire: seven whole morning packets would be ~450 KB a question
# --------------------------------------------------------------------------


def _compiled(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_the_projection_reads_each_packet_once_and_ships_none_of_it() -> None:
    sql = _compiled(select_morning_calls())

    assert sql.count("analyses.context_packet") == 1
    assert "JOIN LATERAL" in sql
    assert "OFFSET" in sql
    assert "analyses.context_packet," not in sql
    for label in (
        "reasons",
        "verdict_adjustment",
        "requires_bike_rest",
        "rest_day",
        "planned_workouts",
    ):
        assert f"AS {label}" in sql, label
    assert "analyses.analysis_type" in sql


class _Rows:
    def all(self) -> list[Any]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows()


async def test_the_loader_never_selects_a_whole_packet() -> None:
    session = _RecordingSession()

    section = await load_recent_mornings(
        session,  # type: ignore[arg-type]
        uuid.uuid4(),
        today=date(2026, 9, 24),
        as_of_utc=datetime(2026, 9, 24, 10, 34, 7),
    )

    assert len(session.statements) == 2
    morning_sql, audit_sql = (_compiled(statement) for statement in session.statements)
    assert morning_sql.count("analyses.context_packet") == 1
    assert "JOIN LATERAL" in morning_sql
    assert "analyses.generated_at_utc <=" in morning_sql
    # The audit read takes one small key, never the record around it.
    assert "analyses.context_packet ->>" in audit_sql
    assert "analyses.context_packet," not in audit_sql
    assert "analyses.generated_at_utc <=" in audit_sql
    assert [day["morningRead"] for day in section["days"]] == [False] * 7
