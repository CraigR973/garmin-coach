"""Batch 339: a symptom anywhere reaches a floor, and the health words match the evidence.

339.2 a chest or heart symptom in a note he left on a session, or told to the coach, reaches
the next morning (HS332-01); 339.3 an open chest or heart follow-up applies on a day with no
hard ride, and loaded strength becomes mobility (HS332-05); 339.4 a night far above his
usual HRV is a watch notice and left out of his week (HS332-06), breathing up two nights
beside a heart reading speaks (HS332-07), one low oxygen night is "a low reading"
(HS332-08), the drivers cache keeps its calendar adjustment (HS332-09), and a note the
reader failed on is read again after the brief is written (HS332-10; in
``test_batch_302_stored_morning``). Every test here failed on ``main`` first.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.models.coaching import BriefMessage, ManualEntry, PlannedWorkout
from src.services import brief_chat, coach_policy, post_workout_analysis
from src.services.coach_policy import (
    CHEST_HEART_NOTICE,
    POST_SESSION_CHEST_RULE,
    READ_PROMPT_FLOORS,
    SYMPTOM_RULE,
    missing_floors,
)
from src.services.insights import (
    DriverCorrelation,
    DriversReport,
    _drivers_packet,
    _drivers_report_from_packet,
)
from src.services.morning_verdict import (
    CHEST_FOLLOW_UP_PLAN_LINE,
    MOBILITY_INSTEAD_LINE,
    graded_plan_adjustments,
)
from src.services.notes_reader import (
    STATUS_FAILED,
    STATUS_NO_NOTES,
    NotesEffects,
    post_session_effects,
    session_note_text,
    with_coach_mention,
    with_post_session,
)
from src.services.symptom_check import (
    ASK_SOURCE_COACH,
    COACH_CHEST_LEAD,
    COACH_CHEST_NOTICE_MARKER,
    EASING_CHEST_FOLLOW_UP,
    EASING_CHEST_QUESTION,
    FLOOR_NO_TRAINING_SEE_DOCTOR,
    SYMPTOMS_CHEST_HEART,
    chest_question_line,
)
from src.services.todays_call import (
    EASY_DAY,
    EASY_RIDING_ONLY,
    EASY_RIDING_ONLY_LINE,
    STATE_EASY_RIDING_ONLY,
    todays_call,
)
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_MOBILITY_INSTEAD,
    ACTION_RECOVERY,
    FLOOR_HARD_WORK_TO_EASY,
    classify_session,
    grade,
)
from tests.test_batch_295_verdict_grading import VO2, Z2, _inputs
from tests.test_batch_297_notes_reader import _flag, _reading
from tests.test_batch_302_stored_morning import _savepoint_session
from tests.test_batch_303_medical_follow_through import (
    SEEDED_THURSDAY,
    _graded,
    _ride_action,
    _seed_good_days,
    _store_reading,
)
from tests.test_batch_315_chest_follow_up import _actions, _acute_following, _follow_up
from tests.test_morning_verdict import _complete_verdict, _metric, _sleep

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-339-wording.md"
WEB_NOTES_ASK = REPO / "apps" / "web" / "src" / "lib" / "notesAsk.ts"
TODAY = date(2026, 9, 2)  # test_morning_verdict's morning

STRENGTH = classify_session(
    session_id="strength-a",
    title="Dumbbells A",
    workout_type="strength",
    planned_minutes=40,
    ir=None,
)
RECOVERY_STRENGTH = classify_session(
    session_id="strength-r",
    title="Recovery strength",
    workout_type="strength_recovery",
    planned_minutes=20,
    ir=None,
)


# -- 339.2: a note he left on a session ------------------------------------------------------


class _Entry:
    def __init__(self, notes: str, *, entry_date: date = TODAY) -> None:
        self.id = uuid.uuid4()
        self.notes = notes
        self.entry_date = entry_date
        self.planned_workout_id = uuid.uuid4()
        self.activity_id = None
        self.entry_at_utc = datetime(2026, 9, 1, 17)


class _Reading:
    def __init__(self, entry: _Entry, reading: dict[str, Any], status: str = "read") -> None:
        from src.services.notes_reader import notes_hash

        self.manual_entry_id = entry.id
        self.notes_sha256 = notes_hash(entry.notes)
        self.status = status
        self.reading = reading
        self.created_at = datetime(2026, 9, 2, 6)
        self.updated_at = None


def _session_effects(
    flag: dict[str, Any], *, answered_at: datetime | None = None, status: str = "read"
) -> tuple[Any, ...]:
    entry = _Entry("Chest tight on the last interval, fine after a minute.")
    reading = _Reading(entry, _reading(chest_heart=flag), status=status)
    return post_session_effects([entry], [reading], answered_at=answered_at)  # type: ignore[list-item]


def test_a_chest_symptom_in_a_ride_note_sets_the_floor_whenever_the_reader_places_it() -> None:
    # Reader v2 has no word for "on yesterday's ride": "earlier" counts for a session note.
    for when in ("now", "earlier", "unknown"):
        _records, floor, question, unread = _session_effects(
            _flag("present", when=when, words="chest tight on the last interval")
        )
        assert floor == "chest tight on the last interval", when
        assert (question, unread) == (None, None)


def test_a_possible_one_asks_and_someone_elses_sets_nothing() -> None:
    _r, floor, question, _u = _session_effects(_flag("unclear", words="tight chest?"))
    assert (floor, question) == (None, "tight chest?")
    _r, floor, question, _u = _session_effects(
        _flag("present", who="someone_else", words="his chest pain")
    )
    assert (floor, question) == (None, None)


def test_his_answer_on_home_after_the_reading_governs() -> None:
    _r, floor, question, _u = _session_effects(
        _flag("present", words="heart racing"), answered_at=datetime(2026, 9, 2, 7)
    )
    assert (floor, question) == (None, None)


def test_a_failed_reading_is_reported_so_the_next_trigger_reads_it_again() -> None:
    records, floor, _q, unread = _session_effects(_flag("absent"), status=STATUS_FAILED)
    assert (floor, unread, records[0]["status"]) == (None, STATUS_FAILED, STATUS_FAILED)


def test_the_floor_from_a_ride_note_outranks_a_lesser_morning_note_and_only_adds() -> None:
    morning = NotesEffects(status="read", symptom_answer="head_cold", ask_symptom_question=True)
    merged = with_post_session(morning, ({"status": "read"},), "heart racing", None)
    assert merged.symptom_answer == SYMPTOMS_CHEST_HEART
    assert merged.symptom_words == "heart racing"
    # Nothing in a session note ever relaxes the morning's own reading.
    quiet = with_post_session(morning, ({"status": "read"},), None, None)
    assert (quiet.symptom_answer, quiet.ask_symptom_question) == ("head_cold", True)
    assert quiet.post_session == ({"status": "read"},)


def test_the_reader_is_told_the_note_was_written_after_a_session() -> None:
    assert session_note_text("  chest tight  ") == "[Written after a session]\nchest tight"


# -- 339.2: what he told the coach ----------------------------------------------------------


def test_a_chest_notice_from_the_coach_asks_and_eases_but_sets_no_floor() -> None:
    effects = with_coach_mention(NotesEffects(status=STATUS_NO_NOTES), told_coach=True)
    assert (effects.ask_symptom_question, effects.chest_question) == (True, True)
    assert (effects.symptom_answer, effects.ask_source) == (None, ASK_SOURCE_COACH)
    assert effects.to_packet()["askSource"] == ASK_SOURCE_COACH
    # A note that already asks, or one that sets a floor, is left as it is.
    noted = NotesEffects(status="read", ask_symptom_question=True, ask_words="heartburn")
    assert with_coach_mention(noted, told_coach=True) is noted
    assert with_coach_mention(NotesEffects(status="read"), told_coach=False).chest_question is False


def test_the_marker_is_the_notices_own_last_sentence() -> None:
    assert CHEST_HEART_NOTICE.endswith(COACH_CHEST_NOTICE_MARKER)
    assert "'" not in COACH_CHEST_NOTICE_MARKER


def test_home_names_the_coach_and_the_card_says_it_in_the_same_words() -> None:
    line = chest_question_line(None, ASK_SOURCE_COACH)
    assert line.startswith(COACH_CHEST_LEAD)
    web = WEB_NOTES_ASK.read_text(encoding="utf-8")
    assert COACH_CHEST_LEAD in web


def test_the_coach_and_the_post_ride_read_carry_the_chest_rule() -> None:
    assert "the app will ask him about them on Home the next morning" in SYMPTOM_RULE
    assert brief_chat.PROMPT_VERSION == "coach-chat-v30-2026-10-29"
    assert POST_SESSION_CHEST_RULE in post_workout_analysis.SYSTEM_PROMPT
    assert CHEST_HEART_NOTICE in post_workout_analysis.SYSTEM_PROMPT
    assert post_workout_analysis.PROMPT_VERSION == "post-workout-analysis-v19-2026-10-29"
    # The audit now holds the post-ride read to the symptom floor as well.
    assert "symptom_floor" in READ_PROMPT_FLOORS["post_workout_analysis"]
    assert missing_floors(post_workout_analysis.SYSTEM_PROMPT, ("symptom_floor",)) == ()
    assert coach_policy.internal_vocabulary_hits(POST_SESSION_CHEST_RULE) == ()


# -- 339.3: an open follow-up on a day with no hard ride -----------------------------------


def test_a_quiet_day_keeps_its_colour_but_is_not_recovered_and_strength_is_mobility() -> None:
    verdict = grade(replace(_inputs(sessions=(Z2, STRENGTH)), acute=_acute_following(_follow_up())))
    # The colour does not move without a hard ride (#386 item 3)...
    assert verdict.status == "Green"
    # ...but the follow-up applies: strength is mobility, Zone 2 stays easy.
    assert (verdict.floor, verdict.easing) == (FLOOR_HARD_WORK_TO_EASY, EASING_CHEST_FOLLOW_UP)
    assert _actions(verdict) == [ACTION_AS_PLANNED, ACTION_MOBILITY_INSTEAD]
    packet = {
        "plannedWorkouts": [{"id": "z2"}, {"id": "strength-a"}],
        "restDay": {"isRestDay": False},
        "verdict": {
            "status": "Green",
            "engine": "graded",
            "acutePhysiology": {},
            "graded": {
                "easing": verdict.easing,
                "actions": [
                    {"action": action.action, "workoutType": action.workout_type, "isHard": False}
                    for action in verdict.actions
                ],
            },
        },
    }
    call = todays_call(packet)
    assert (call.state, call.headline, call.line) == (
        STATE_EASY_RIDING_ONLY,
        EASY_RIDING_ONLY,
        EASY_RIDING_ONLY_LINE,
    )
    assert "recovered" not in call.line.lower()


def test_recovery_strength_and_a_cleared_follow_up_are_left_as_planned() -> None:
    verdict = grade(
        replace(_inputs(sessions=(RECOVERY_STRENGTH,)), acute=_acute_following(_follow_up()))
    )
    assert _actions(verdict) == [ACTION_AS_PLANNED]
    cleared = grade(
        replace(
            _inputs(sessions=(Z2, STRENGTH)),
            acute=_acute_following(_follow_up("cleared")),
        )
    )
    assert (cleared.easing, _actions(cleared)) == (None, [ACTION_AS_PLANNED, ACTION_AS_PLANNED])


def test_a_hard_ride_keeps_the_easy_day_it_had() -> None:
    verdict = grade(
        replace(_inputs(sessions=(VO2, STRENGTH)), acute=_acute_following(_follow_up()))
    )
    assert verdict.status == "Amber"
    assert _actions(verdict) == [ACTION_RECOVERY, ACTION_MOBILITY_INSTEAD]
    packet = {
        "plannedWorkouts": [{"id": "vo2"}, {"id": "strength-a"}],
        "restDay": {"isRestDay": False},
        "verdict": {
            "status": "Amber",
            "engine": "graded",
            "acutePhysiology": {},
            "graded": {
                "easing": verdict.easing,
                "actions": [
                    {"action": "recovery", "workoutType": "bike_vo2", "isHard": True},
                    {"action": "mobility_instead", "workoutType": "strength", "isHard": False},
                ],
            },
        },
    }
    assert todays_call(packet).headline == EASY_DAY


def test_the_plan_lines_say_riding_stays_easy_and_strength_is_mobility() -> None:
    verdict = grade(replace(_inputs(sessions=(Z2, STRENGTH)), acute=_acute_following(_follow_up())))
    workouts = [
        PlannedWorkout(id=uuid.uuid4(), workout_type="bike_z2", status="planned", title="Z2"),
        PlannedWorkout(id=uuid.uuid4(), workout_type="strength", status="planned", title="DB A"),
    ]
    verdict = replace(
        verdict,
        actions=tuple(
            replace(action, session_id=str(workout.id))
            for action, workout in zip(verdict.actions, workouts, strict=True)
        ),
    )
    lines = graded_plan_adjustments(
        verdict, workouts, is_rest_day=False, acute=_acute_following(_follow_up()), has_vo2=False
    )
    assert lines[0] == CHEST_FOLLOW_UP_PLAN_LINE
    assert MOBILITY_INSTEAD_LINE in lines


# -- 339.4: the high side of HRV, breathing, oxygen, the cache ------------------------------


def _hrv_history(*values: int) -> list[Any]:
    return [
        _metric(day=TODAY - timedelta(days=offset + 1), last_night_hrv=value)
        for offset, value in enumerate(values)
    ]


HISTORY = [46, 47, 48, 52, 42] * 6  # median 47, SD about 3.2: the high line is about 56.6


def test_a_night_far_above_his_usual_is_a_watch_notice_and_not_recovery() -> None:
    context = _complete_verdict(
        daily_metric=_metric(last_night_hrv=85), recent_daily_metrics=_hrv_history(*HISTORY)
    )
    acute = context["acutePhysiology"]
    high = acute["overnightHrvHigh"]
    assert high["triggered"] is True
    assert acute["requiresBikeRest"] is False
    [notice] = [item for item in acute["escalations"] if item["kind"] == "overnight_hrv_high"]
    assert notice["level"] == "watch"
    assert "racing or irregular heartbeat" in notice["message"]
    assert "“Chest or heart”" in notice["message"]
    # An ordinary good night, however welcome, is not flagged.
    ordinary = _complete_verdict(
        daily_metric=_metric(last_night_hrv=55), recent_daily_metrics=_hrv_history(*HISTORY)
    )
    assert ordinary["acutePhysiology"]["overnightHrvHigh"]["triggered"] is False


def test_a_night_far_above_his_usual_is_left_out_of_his_week() -> None:
    nights = {TODAY - timedelta(days=offset + 1): float(v) for offset, v in enumerate(HISTORY)}
    week = {TODAY - timedelta(days=offset): 42.0 for offset in range(6)}
    base = _inputs()
    with_spike = replace(
        base,
        subject_date=TODAY,
        hrv_nights=tuple(sorted({**nights, **week, TODAY: 120.0}.items())),
    )
    without = replace(
        base,
        subject_date=TODAY,
        hrv_nights=tuple(sorted({**nights, **week}.items())),
    )
    # One implausible night would lift a dipped week to normal; left out, the dip shows.
    from src.services.verdict_grading import _hrv_week_on

    assert (
        _hrv_week_on(with_spike, TODAY, in_recovery_week=False).rating
        == _hrv_week_on(without, TODAY, in_recovery_week=False).rating
    )
    assert _hrv_week_on(without, TODAY, in_recovery_week=False).rating != "none"


def test_breathing_up_two_nights_beside_a_heart_reading_speaks_and_alone_it_does_not() -> None:
    sleeps = [_sleep(day=TODAY - timedelta(days=1), respiration=14)]
    low_hrv = _complete_verdict(
        daily_metric=_metric(last_night_hrv=42),
        sleep=_sleep(respiration=14),
        recent_sleeps=sleeps,
        recent_daily_metrics=_hrv_history(*HISTORY),
    )
    signal = low_hrv["acutePhysiology"]["respiration"]
    assert (signal["triggered"], signal["autonomicConcern"]) == (True, True)
    [notice] = [
        item for item in low_hrv["acutePhysiology"]["escalations"] if item["kind"] == "respiration"
    ]
    assert notice["level"] == "watch"
    assert notice["message"].endswith("If you feel one coming, tell me in your check-in.")
    alone = _complete_verdict(
        daily_metric=_metric(last_night_hrv=47),
        sleep=_sleep(respiration=14),
        recent_sleeps=sleeps,
        recent_daily_metrics=_hrv_history(*HISTORY),
    )
    assert alone["acutePhysiology"]["respiration"]["triggered"] is False
    assert alone["acutePhysiology"]["respiration"]["raisedTwoNights"] is True


def test_one_low_oxygen_night_is_a_low_reading_not_sustained() -> None:
    context = _complete_verdict(sleep=_sleep(average_spo2=91, lowest_spo2=89, respiration=11))
    message = context["acutePhysiology"]["oxygenRespiration"]["escalation"]
    assert "A low reading like this is often the watch; if it repeats" in message
    assert "Sustained" not in message


def test_the_drivers_cache_keeps_the_calendar_adjustment() -> None:
    report = DriversReport(
        outcomes={
            "rem_sleep_pct": [
                DriverCorrelation(
                    driver="bedroom_temp",
                    outcome="rem_sleep_pct",
                    coefficient=-0.26,
                    sample_count=107,
                    adjusted_coefficient=-0.24,
                    interval_low=-0.43,
                    interval_high=-0.07,
                )
            ]
        },
        record_count=107,
        window_start=date(2026, 6, 1),
        window_end=date(2026, 10, 9),
    )
    [round_trip] = _drivers_report_from_packet(_drivers_packet(report)).outcomes["rem_sleep_pct"]
    assert round_trip.interval == (-0.43, -0.07)
    assert round_trip.effect == -0.24
    assert round_trip.excludes_zero


# -- the words -------------------------------------------------------------------------------


def test_every_new_line_is_in_the_wording_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    for words in (
        COACH_CHEST_LEAD,
        EASY_RIDING_ONLY,
        EASY_RIDING_ONLY_LINE,
        CHEST_FOLLOW_UP_PLAN_LINE,
        MOBILITY_INSTEAD_LINE,
        "A low reading like this is often the watch; if it repeats, it has causes worth "
        "checking properly",
        "doesn't count as extra recovery today",
        "If you feel one coming, tell me in your check-in.",
        "the app will ask him about it on Home tomorrow morning",
    ):
        assert words.replace("’", "'") in draft.replace("’", "'"), words


# -- on Postgres -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_postgres_a_chest_note_left_on_a_ride_sets_the_floor_the_next_morning(
    db_conn: AsyncConnection,
) -> None:
    """339's acceptance. On `main` the note was never read and the next morning was Green
    with VO2 as planned."""
    ride_day = SEEDED_THURSDAY
    next_day = ride_day + timedelta(days=1)
    async with _savepoint_session(db_conn) as session:
        player, _entries, rides = await _seed_good_days(session, ride_day, 2)
        note = ManualEntry(
            user_id=player.id,
            planned_workout_id=rides[ride_day].id,
            entry_date=ride_day,
            entry_at_utc=datetime.combine(ride_day, datetime.min.time()) + timedelta(hours=18),
            rpe=8,
            notes="Heart racing and chest tight on the last interval.",
            supplements_json={},
            food_json={},
            sleep_setup_json={},
        )
        session.add(note)
        await session.commit()
        await _store_reading(
            session,
            note,
            _reading(chest_heart=_flag("present", when="earlier", words="chest tight")),
        )

        verdict = await _graded(session, player, next_day)

        symptoms = verdict["acutePhysiology"]["symptoms"]
        assert (symptoms["answer"], symptoms["floor"]) == (
            SYMPTOMS_CHEST_HEART,
            FLOOR_NO_TRAINING_SEE_DOCTOR,
        )
        assert verdict["status"] == "Red"
        assert verdict["notesReading"]["postSessionNotes"][0]["status"] == "read"


@pytest.mark.asyncio
async def test_on_postgres_chest_symptoms_told_to_the_coach_ask_the_next_morning(
    db_conn: AsyncConnection,
) -> None:
    """On `main` a chest symptom told only to the coach changed nothing the next morning."""
    chat_day = SEEDED_THURSDAY
    next_day = chat_day + timedelta(days=1)
    async with _savepoint_session(db_conn) as session:
        player, _entries, _rides = await _seed_good_days(session, chat_day, 2)
        session.add_all(
            [
                BriefMessage(
                    user_id=player.id,
                    role="user",
                    content="My heart was fluttering on the stairs earlier.",
                    created_utc=datetime.combine(chat_day, datetime.min.time())
                    + timedelta(hours=19),
                ),
                BriefMessage(
                    user_id=player.id,
                    role="assistant",
                    content=f"I'm glad you told me.\n\n{CHEST_HEART_NOTICE}",
                    created_utc=datetime.combine(chat_day, datetime.min.time())
                    + timedelta(hours=19, minutes=1),
                ),
            ]
        )
        await session.commit()

        verdict = await _graded(session, player, next_day)

        assert verdict["notesReading"]["askSource"] == ASK_SOURCE_COACH
        assert verdict["notesReading"]["askSymptomQuestion"] is True
        assert verdict["graded"]["easing"] == EASING_CHEST_QUESTION
        assert _ride_action(verdict) == ACTION_RECOVERY
        assert verdict["reasons"][0] == chest_question_line(None, ASK_SOURCE_COACH)
