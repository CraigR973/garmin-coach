"""Batch 303 — medical follow-through: the floors do not quietly lapse.

Four things a symptom floor did not do, each re-checked against the code and production
on 2 Oct 2026 (the ledger's "Corrections made at /batch-start 303"):

(a) the morning after a fever-or-aches floor was an ordinary day, VO2 included, though
    the notice said "a few easy days before anything hard";
(b) breathlessness out of proportion to effort was in neither the "Chest or heart"
    answer nor the note reader's chest flag;
(c) a possible chest or heart mention in his note only asked, and the hard session went
    ahead unanswered;
(d) saving the check-in again counted as his answer to Home's question, and with None
    preselected dropped a symptom his note had named. He saves again on 9 mornings in 78.

Decided by Craig on 2 Oct: two easy mornings after a fever; an unclear chest mention
eases the hard session until he answers; no change after a chest or heart report. On
both easings the day is at least Amber and never Red for it, and a hard session becomes
the easy spin. Wording: ``docs/drafts/2026-10-02-batch-303-wording.md``.
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import (
    Analysis,
    CheckInReading,
    DailyMetric,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.routers import daily_loop as daily_loop_router
from src.services.daily_loop import DailyLoopService
from src.services.daily_loop_envelope import _chest_question_eases, _serialize_analysis
from src.services.executable_coaching import MorningContext, morning_ir
from src.services.generation_requests import manual_entry_generation_version
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_SYSTEM_PROMPT,
    SYMPTOM_FOLLOW_THROUGH_RULE,
    MorningAnalysisService,
    _eased_ride_detail,
)
from src.services.morning_verdict import (
    GRADED_EASE_HARD_LINE,
    GRADED_ZONE_TWO_LINE,
    _acute_physiology_rail,
    graded_verdict_packet,
    morning_verdict,
)
from src.services.notes_eval import (
    SOURCE_HELD_OUT,
    expected_effects,
    gate_failures,
    load_cases,
    recorded_passes,
    render_report,
    score_pass,
)
from src.services.notes_reader import (
    FLAGS,
    PROMPT_VERSION,
    STATUS_READ,
    SYSTEM_PROMPT,
    day_effects,
    notes_hash,
    reading_effects,
)
from src.services.symptom_check import (
    EASING_CHEST_QUESTION,
    EASING_FEVER_RETURN,
    EASY_RIDING_PLAN_LINE,
    ILLNESS_RETURN_MORNINGS,
    SYMPTOM_ANSWERS,
    SYMPTOM_FLOORS,
    SYMPTOM_LABELS,
    SYMPTOM_SEVERITY,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
    SYMPTOMS_NONE,
    IllnessReturn,
    chest_question_easing,
    chest_question_line,
    fever_return_easing,
    illness_return,
    symptom_signal,
)
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_HOLD_TARGETS,
    ACTION_RECOVERY,
    FLOOR_BIKE_REST,
    FLOOR_EASY_RIDING,
    FLOOR_HARD_WORK_TO_EASY,
    FLOOR_NO_TRAINING,
    GradedVerdict,
    classify_planned_workout,
    grade,
    ride_transform,
)
from src.services.weekly_mix import DROPPING_ACTIONS
from src.services.weekly_restructure import SwapSuggestion
from src.services.workout_delivery import build_structured_workout_ir
from tests.test_batch_295_verdict_grading import LEVELS, RANK, VO2, Z2, _acute, _inputs
from tests.test_batch_296_graded_colour import DAILY_METRIC_PHASE_MORNING, VO2_STRUCTURED
from tests.test_batch_297_notes_reader import _entry, _flag, _reading, _stored
from tests.test_batch_300_light_week_marked import (
    W13_VO2_PRIMER,
    _plan_lines,
    _ride,
    _sweet_spot,
    _z2,
)
from tests.test_batch_302_stored_morning import _db_override, _savepoint_session

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-02-batch-303-wording.md"
FIXTURES = Path(__file__).parent / "fixtures"
EVAL_CASES = FIXTURES / "notes_eval_2026_09.json"
RECORDED = FIXTURES / "notes_eval_recorded"
WEB_NOTES_ASK = REPO / "apps" / "web" / "src" / "lib" / "notesAsk.ts"

#: A Friday, so the fever in these tests was reported on a Thursday, as the draft's is.
FRIDAY = date(2026, 10, 9)
THURSDAY = FRIDAY - timedelta(days=1)


def _draft() -> str:
    """The signed-off draft as running text: no block-quote marks, no line breaks."""
    text = DRAFT.read_text(encoding="utf-8")
    return " ".join(text.replace("\n> ", " ").replace("**", "").split())


def _fever_return(day: int = 1) -> dict[str, Any]:
    return fever_return_easing(IllnessReturn(reported_on=THURSDAY, day=day))


def _acute_with(easing: dict[str, Any] | None, **overrides: Any) -> dict[str, Any]:
    """The grid's acute rail, carrying what follows a symptom as production's does."""
    symptoms = overrides.pop("symptoms", None)
    acute = _acute(symptoms=symptoms, **overrides)
    acute["symptoms"] = symptom_signal(symptoms, easing=easing)
    return acute


def _actions(verdict: GradedVerdict) -> list[str]:
    return [action.action for action in verdict.actions]


# -- (b) the chest-or-heart answer names breathlessness -------------------------------------


def test_the_chest_or_heart_answer_names_breathlessness_wherever_it_is_named() -> None:
    floor = SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART]
    assert "unusual breathlessness" in SYMPTOM_LABELS[SYMPTOMS_CHEST_HEART]
    assert "faintness or unusual breathlessness sets a Red floor" in floor.reason
    assert "feeling faint, or unusual breathlessness." in floor.notice
    # The one new piece of medical advice in the batch (Craig, 2 Oct).
    assert floor.notice.endswith(
        "If you have chest pain or are struggling to breathe right now, call 999."
    )
    # What it does is unchanged: no training of any kind, and a doctor the same day.
    assert floor.requires_training_rest is True
    assert "Speak to your GP or call 111 today." in floor.notice


def test_the_note_reader_is_asked_about_breathlessness_and_told_what_is_not_one() -> None:
    assert PROMPT_VERSION == "notes-reader-v2-2026-10-02"
    chest_flag = SYSTEM_PROMPT.split("- chest_heart:")[1].split("- fever_aches:")[0]
    assert "breathlessness that is" in chest_flag and "unusual for him" in chest_flag
    # Two of his 56 real notes mention his breathing exercises (R33, R42), and the gate
    # has no margin on his real notes, so the prompt rules both ordinary cases out.
    rules = " ".join(SYSTEM_PROMPT.split())
    assert "His breathing exercises or breathwork, done or missed" in rules
    assert "out of breath during or just after a hard effort" in rules
    assert "A blocked nose that makes it hard to breathe is head_cold." in rules
    assert "without saying how hard he was working, or cannot explain: chest_heart unclear" in rules


def _recorded(model: str) -> dict[str, Any]:
    recording: dict[str, Any] = json.loads((RECORDED / f"{model}.json").read_text("utf-8"))
    return recording


def test_the_v2_reader_was_recorded_and_met_the_gate_on_breathlessness() -> None:
    """303.6: the eval re-run on the production model (2 Oct 2026, $2.23), under the
    prompt the reader now sends. Until Batch 307 pins it, this is what says so."""
    recording = _recorded("claude-sonnet-5")
    assert recording["promptVersion"] == PROMPT_VERSION
    cases = load_cases(EVAL_CASES)
    passes = recorded_passes(recording)
    scores = [score_pass(cases, readings) for readings in passes]
    assert len(scores) == 2
    assert gate_failures(scores) == []

    by_id = {case.id: case for case in cases}
    for readings in passes:
        # The new red flags: unusual breathlessness is caught, as a floor or the question.
        for case_id in ("B01", "B02", "B03", "B04"):
            assert expected_effects(by_id[case_id]).floor == SYMPTOMS_CHEST_HEART
            effects = reading_effects(readings[case_id])
            assert effects.symptom_answer == SYMPTOMS_CHEST_HEART or effects.chest_question
        # Breathlessness he cannot explain asks, and holds the hard session meanwhile.
        for case_id in ("B05", "B06"):
            effects = reading_effects(readings[case_id])
            assert (effects.symptom_answer, effects.chest_question) == (None, True)
        # What is not a symptom stays quiet: hard efforts, his breathing exercises, a
        # figure, someone else, and last month. His two real notes about his breathing
        # exercises (R33, R42) are the reason the prompt says so outright.
        for case_id in ("B07", "B08", "B09", "B10", "B12", "B13", "B14", "B15", "R33", "R42"):
            effects = reading_effects(readings[case_id])
            assert (effects.symptom_answer, effects.ask_symptom_question) == (None, False), case_id
        # A blocked nose is a head cold, not his chest.
        assert reading_effects(readings["B11"]).symptom_answer == SYMPTOMS_HEAD_COLD


def test_the_held_out_notes_are_reported_on_their_own_and_one_false_alarm_is_on_record() -> None:
    """307.3, brought forward so one paid run scored it. Ten notes written after the v2
    prompt was frozen; the prompt was not changed to fit them."""
    cases = load_cases(EVAL_CASES)
    held_out = [case.id for case in cases if case.source == SOURCE_HELD_OUT]
    assert held_out == [f"X{number:02d}" for number in range(1, 11)]
    scores = [
        score_pass(cases, readings) for readings in recorded_passes(_recorded("claude-sonnet-5"))
    ]
    # Every held-out red flag was caught on both passes...
    for score in scores:
        assert score.held_out == held_out
        assert not set(score.missed_red_flags) & set(held_out)
    # ...and one quiet note raised a question on one pass of two: a stitch in his side.
    assert [score.held_out_wrong for score in scores] == [["X07"], []]


def test_the_report_names_an_earlier_prompts_recording_without_scoring_it() -> None:
    """Haiku 4.5 was recorded under v1 and is not the production model, so it was not
    re-run. Scored against today's cases it would read as 25 failed readings."""
    haiku = _recorded("claude-haiku-4-5-20251001")
    assert haiku["promptVersion"] != PROMPT_VERSION
    sonnet = _recorded("claude-sonnet-5")
    cases = load_cases(EVAL_CASES)
    scores = [score_pass(cases, readings) for readings in recorded_passes(sonnet)]
    report = render_report(
        cases,
        [(sonnet, scores)],
        generated="Generated for a test",
        labelled_by="Craig",
        not_rerun=[haiku],
    )
    assert "125 cases: 56 of Mark's real morning notes, 59 hand-written hard cases" in report
    assert "10 held out (written after the prompt was frozen)" in report
    assert "- **Held-out cases as keyed:** 9 of 10 ['X07']; 10 of 10" in report
    assert "## Not re-run under this prompt" in report
    assert "claude-haiku-4-5-20251001: recorded under `notes-reader-v1-2026-09-30`" in report
    assert "## claude-haiku-4-5-20251001" not in report


# -- (a) the two easy mornings after a fever ------------------------------------------------


def test_the_two_mornings_after_a_fever_are_easy_days_back_and_the_third_is_not() -> None:
    assert ILLNESS_RETURN_MORNINGS == 2
    fever_on_thursday = {THURSDAY: SYMPTOMS_FEVER_ACHES}
    assert illness_return(THURSDAY, fever_on_thursday) is None  # the day itself is the floor
    assert illness_return(FRIDAY, fever_on_thursday) == IllnessReturn(THURSDAY, day=1)
    assert illness_return(FRIDAY + timedelta(1), fever_on_thursday) == IllnessReturn(
        THURSDAY, day=2
    )
    assert illness_return(FRIDAY + timedelta(2), fever_on_thursday) is None


def test_the_nearest_fever_day_decides_so_the_count_restarts() -> None:
    two_days = {THURSDAY - timedelta(1): SYMPTOMS_FEVER_ACHES, THURSDAY: SYMPTOMS_FEVER_ACHES}
    assert illness_return(FRIDAY, two_days) == IllnessReturn(THURSDAY, day=1)
    # A fever, then a clear day: the clear day was day 1, so today is day 2.
    then_clear = {THURSDAY - timedelta(1): SYMPTOMS_FEVER_ACHES, THURSDAY: None}
    assert illness_return(FRIDAY, then_clear) == IllnessReturn(THURSDAY - timedelta(1), day=2)


@pytest.mark.parametrize("answer", [None, SYMPTOMS_NONE, SYMPTOMS_HEAD_COLD, SYMPTOMS_CHEST_HEART])
def test_only_a_fever_starts_the_easy_days_back(answer: str | None) -> None:
    # A head cold is above the neck. A chest or heart report starts a follow-up of its own
    # since Batch 315 (Craig, 6 Oct, amending his 2 Oct "no change"), not easy days back.
    assert illness_return(FRIDAY, {THURSDAY: answer}) is None


def test_an_easy_day_back_says_which_day_it_is_and_names_the_day_it_followed() -> None:
    first, second = _fever_return(1), _fever_return(2)
    assert first["kind"] == EASING_FEVER_RETURN
    assert (first["reportedOn"], first["day"], first["of"]) == ("2026-10-08", 1, 2)
    assert first["reason"] == (
        "Easing back after the fever you reported on Thursday: easy riding only, day 1 of 2."
    )
    assert first["notice"] == (
        "You told me about a fever, aches or a chest infection on Thursday. This is the first "
        "of two easy days back: easy riding at most, nothing hard. If any of it comes back, "
        "tell me in your check-in and rest."
    )
    assert "This is the second of two easy days back" in second["notice"]
    assert second["reason"].endswith("day 2 of 2.")
    assert first["planLine"] == EASY_RIDING_PLAN_LINE


def test_an_easy_day_back_is_amber_and_swaps_the_hard_session_for_the_easy_spin() -> None:
    """303.2 on the engine. The good-numbers morning after a fever was Green, VO2 as planned."""
    good_morning = _inputs()
    assert grade(good_morning).label == "Green"
    assert set(_actions(grade(good_morning))) == {ACTION_AS_PLANNED}

    back = replace(good_morning, acute=_acute_with(_fever_return()))
    verdict = grade(replace(back, sessions=(VO2, Z2)))
    assert (verdict.status, verdict.held) == ("Amber", False)
    assert verdict.floor == FLOOR_HARD_WORK_TO_EASY
    assert verdict.easing == EASING_FEVER_RETURN
    assert _actions(verdict) == [ACTION_RECOVERY, ACTION_AS_PLANNED]
    assert _fever_return()["reason"] in verdict.reasons
    assert verdict.to_packet()["easing"] == EASING_FEVER_RETURN

    # It is about him, not the plan: with nothing hard planned the day is still eased.
    for sessions in ((Z2,), ()):
        quiet = grade(replace(back, sessions=sessions))
        assert (quiet.status, quiet.floor) == ("Amber", FLOOR_HARD_WORK_TO_EASY)
        assert ACTION_RECOVERY not in _actions(quiet)


def test_the_easy_spin_is_the_rails_recovery_ride_and_the_week_counts_it_as_dropped() -> None:
    # The same action a Red gives a hard session, so every surface that follows actions
    # (the delivery rail, the weekly mix, the ride summary) already knows it.
    assert ride_transform("Amber", graded=True, action=ACTION_RECOVERY) == "Red"
    assert ACTION_RECOVERY in DROPPING_ACTIONS
    primer = _ride(
        W13_VO2_PRIMER, title="VO₂ Primer (3 × 1 min @ 120%)", workout_type="bike_vo2", minutes=30
    )
    context = MorningContext(status="Amber", graded=True, actions={str(primer.id): ACTION_RECOVERY})
    spin = morning_ir(
        build_structured_workout_ir(primer, ftp_watts=280), context, primer, companion_session=False
    )
    assert spin["origin"] == "red_substitution"
    assert max(int(step["powerEndPct"]) for step in spin["steps"]) <= 60


def test_an_easy_day_back_never_gives_a_better_day_and_is_never_red_on_its_own() -> None:
    """Over the whole grid: the easing only adds caution, and adds no Red."""
    keys = list(LEVELS)
    easing = _fever_return()
    violations: list[str] = []
    for combo in itertools.product(*(range(len(LEVELS[key])) for key in keys)):
        inputs = _inputs(**{key: LEVELS[key][i] for key, i in zip(keys, combo, strict=True)})
        without = grade(inputs)
        acute = dict(inputs.acute)
        answer = acute["symptoms"]["answer"]
        acute["symptoms"] = symptom_signal(answer, easing=easing)
        back = grade(replace(inputs, acute=acute))
        if RANK[back.label] < RANK[without.label]:
            violations.append(f"{combo}: better, {without.label} -> {back.label}")
        if back.status == "Red" and without.status != "Red":
            violations.append(f"{combo}: Red from the easing alone")
        if without.status == "Green" and back.status != "Amber":
            violations.append(f"{combo}: a Green morning not held at Amber")
        if without.floor is not None and back.floor != without.floor:
            violations.append(f"{combo}: floor {without.floor} became {back.floor}")
        if without.floor is None and back.floor != FLOOR_HARD_WORK_TO_EASY:
            violations.append(f"{combo}: no easing floor")
        for before, after in zip(without.actions, back.actions, strict=True):
            if before.is_hard and after.action == ACTION_AS_PLANNED:
                violations.append(f"{combo}: a hard session ridden as planned")
    assert violations == []


def test_a_floor_reported_today_outranks_the_easy_day_back() -> None:
    for answer, floor in (
        (SYMPTOMS_HEAD_COLD, FLOOR_EASY_RIDING),
        (SYMPTOMS_FEVER_ACHES, FLOOR_NO_TRAINING),
        (SYMPTOMS_CHEST_HEART, FLOOR_NO_TRAINING),
    ):
        assert symptom_signal(answer, easing=_fever_return())["easing"] is None
        verdict = grade(_inputs(symptoms=answer))
        easing_too = grade(
            replace(_inputs(symptoms=answer), acute=_acute_with(_fever_return(), symptoms=answer))
        )
        assert (
            (easing_too.status, easing_too.floor)
            == ("Red", floor)
            == (
                verdict.status,
                verdict.floor,
            )
        )
        assert easing_too.easing is None


def test_off_the_bike_outranks_the_easy_day_back() -> None:
    verdict = grade(
        replace(
            _inputs(overnight="illness"),
            acute=_acute_with(_fever_return(), overnight="illness"),
        )
    )
    assert verdict.floor == FLOOR_BIKE_REST
    assert ACTION_RECOVERY not in _actions(verdict)
    # "Easy riding only" is not said beside "no riding": the stricter floor is the reason.
    assert verdict.easing is None
    assert _fever_return()["reason"] not in verdict.reasons


def test_a_light_week_does_not_hold_a_hard_session_on_an_easy_day_back() -> None:
    """A session held at its targets is still hard work. W12 and W13 are light weeks."""
    sweet_spot, zone_two = _sweet_spot(), _z2()
    sessions = tuple(classify_planned_workout(workout) for workout in (sweet_spot, zone_two))
    light = replace(
        _inputs(), recovery_class_block=True, light_week="consolidation", sessions=sessions
    )
    # Nothing clearly off: a light week holds an Amber morning's sessions (Batch 300)...
    back = grade(replace(light, acute=_acute_with(_fever_return())))
    assert back.status == "Amber"
    # ...but not the hard one on an easy day back. The Zone 2 ride is the same ride held.
    assert _actions(back) == [ACTION_RECOVERY, ACTION_HOLD_TARGETS]
    lines = _plan_lines(back, [sweet_spot, zone_two])
    assert lines[0] == EASY_RIDING_PLAN_LINE
    assert GRADED_EASE_HARD_LINE not in lines
    # Outside a light week the Zone 2 ride is simply as planned.
    ordinary = grade(
        replace(
            light,
            recovery_class_block=False,
            light_week=None,
            acute=_acute_with(_fever_return()),
        )
    )
    assert _actions(ordinary) == [ACTION_RECOVERY, ACTION_AS_PLANNED]
    assert _plan_lines(ordinary, [sweet_spot, zone_two]) == [
        EASY_RIDING_PLAN_LINE,
        GRADED_ZONE_TWO_LINE,
    ]


# -- (c) a possible chest or heart mention eases the hard session until he answers ----------


def test_an_open_chest_question_eases_a_hard_session_and_only_asks_otherwise() -> None:
    easing = chest_question_easing("heartburn")
    assert (easing["kind"], easing["words"], easing["notice"]) == (
        EASING_CHEST_QUESTION,
        "heartburn",
        None,
    )
    open_question = replace(_inputs(), acute=_acute_with(easing))

    hard = grade(replace(open_question, sessions=(VO2, Z2)))
    assert (hard.status, hard.floor, hard.easing) == (
        "Amber",
        FLOOR_HARD_WORK_TO_EASY,
        EASING_CHEST_QUESTION,
    )
    assert _actions(hard) == [ACTION_RECOVERY, ACTION_AS_PLANNED]
    assert hard.reasons[0] == (
        "Your note mentions “heartburn”. Until you answer, today’s hard session is an easy ride."
    )

    # Nothing hard planned, or a rest day: the day is what it was, and Home only asks.
    for quiet in (
        replace(open_question, sessions=(Z2,)),
        replace(open_question, sessions=()),
        replace(open_question, sessions=(VO2,), rest_day=True),
    ):
        verdict = grade(quiet)
        assert (verdict.label, verdict.floor, verdict.easing) == ("Green", None, None)
        assert easing["reason"] not in verdict.reasons


def test_an_unclear_chest_mention_is_a_chest_question_and_a_clear_one_is_the_floor() -> None:
    unclear = reading_effects(_reading(chest_heart=_flag("unclear", words="heartburn")))
    assert (unclear.symptom_answer, unclear.ask_symptom_question) == (None, True)
    assert (unclear.chest_question, unclear.chest_question_words) == (True, "heartburn")
    assert unclear.to_packet()["chestQuestion"] is True
    assert unclear.to_packet()["chestQuestionWords"] == "heartburn"

    # His, and now: that is the floor (no training), not a question about the session.
    clear = reading_effects(_reading(chest_heart=_flag("present", words="tight chest")))
    assert (clear.symptom_answer, clear.chest_question) == (SYMPTOMS_CHEST_HEART, False)

    # Present but not clearly his or current: as much as the reader will say, so it asks.
    maybe = reading_effects(_reading(chest_heart=_flag("present", who="unknown")))
    assert (maybe.symptom_answer, maybe.chest_question) == (None, True)

    # Someone else's, or over: nothing. A fever or a cold he may have: only the question.
    for reading in (
        _reading(chest_heart=_flag("present", who="someone_else")),
        _reading(chest_heart=_flag("unclear", when="earlier")),
        _reading(fever_aches=_flag("unclear")),
        _reading(head_cold=_flag("unclear")),
        _reading(unwell=_flag("present")),
    ):
        assert reading_effects(reading).chest_question is False

    # Once he answers, or has already told the app it is his chest, it is not open.
    reading = _reading(chest_heart=_flag("unclear", words="heartburn"))
    assert reading_effects(reading, answered_after_reading=True).chest_question is False
    assert reading_effects(reading, tapped_answer=SYMPTOMS_CHEST_HEART).chest_question is False


# -- (d) only his answer to Home's question relaxes a note's symptom ------------------------


def test_saving_the_check_in_again_is_not_an_answer() -> None:
    """303.5. On `main` this save was "his answer": the floor went and Home stopped asking."""
    read_at = datetime(2026, 10, 9, 7, 0)
    # He saved the check-in again half an hour after the note was read, None still selected.
    entry = _entry("Sore throat since yesterday.", read_at + timedelta(minutes=30))
    entry.symptoms = SYMPTOMS_NONE
    stored = _stored(entry, STATUS_READ, _reading(head_cold=_flag("present")), read_at)

    effects = day_effects([entry], [stored])
    assert effects.answered_after_reading is False
    assert effects.symptom_answer == SYMPTOMS_HEAD_COLD
    assert effects.ask_symptom_question is True


def test_his_answer_on_home_relaxes_the_note_and_a_changed_note_asks_again() -> None:
    read_at = datetime(2026, 10, 9, 7, 0)
    entry = _entry("Sore throat since yesterday.", read_at - timedelta(minutes=1))
    entry.symptoms = SYMPTOMS_NONE
    entry.symptoms_answered_at_utc = read_at + timedelta(minutes=5)
    stored = _stored(entry, STATUS_READ, _reading(head_cold=_flag("present")), read_at)

    answered = day_effects([entry], [stored])
    assert answered.answered_after_reading is True
    assert (answered.symptom_answer, answered.ask_symptom_question) == (None, False)

    # He rewrites the note afterwards: a new reading, later than his answer, asks again.
    entry.notes = "Sore throat, and now a bit of a temperature."
    reread = _stored(
        entry,
        STATUS_READ,
        _reading(fever_aches=_flag("present", words="a bit of a temperature")),
        read_at + timedelta(minutes=20),
    )
    again = day_effects([entry], [stored, reread])
    assert again.answered_after_reading is False
    assert again.symptom_answer == SYMPTOMS_FEVER_ACHES


def test_his_answer_is_a_new_input_and_a_plain_save_is_not() -> None:
    """The morning is regraded when he answers, even when the answer is the stored None."""
    morning = datetime(2026, 10, 9, 7, 0)
    entry = _entry("Sore throat.", morning)
    entry.symptoms = SYMPTOMS_NONE
    before = manual_entry_generation_version(entry)

    entry.entry_at_utc = morning + timedelta(hours=1)  # saved again, nothing changed
    assert manual_entry_generation_version(entry) == before

    entry.symptoms_answered_at_utc = morning + timedelta(hours=2)
    answered = manual_entry_generation_version(entry)
    assert answered != before
    entry.symptoms_answered_at_utc = morning + timedelta(hours=3)  # he answers again
    assert manual_entry_generation_version(entry) != answered


def test_home_asks_only_about_something_more_serious_than_he_tapped() -> None:
    sore_throat = _reading(head_cold=_flag("present", words="sore throat"))
    # A note of "sore throat" beside a tapped "Head cold" has nothing left to ask...
    told = reading_effects(sore_throat, tapped_answer=SYMPTOMS_HEAD_COLD)
    assert told.ask_symptom_question is False
    # ...and the floor is his note's and his tap's alike.
    assert told.symptom_answer == SYMPTOMS_HEAD_COLD
    # Beside None, or no answer at all (an older client), Home asks as before.
    assert reading_effects(sore_throat, tapped_answer=SYMPTOMS_NONE).ask_symptom_question is True
    assert reading_effects(sore_throat, tapped_answer=None).ask_symptom_question is True
    assert reading_effects(sore_throat).ask_symptom_question is True

    # Something more serious than he tapped is still asked about, with its own words.
    heartburn = _reading(
        head_cold=_flag("present", words="sore throat"),
        chest_heart=_flag("unclear", words="heartburn"),
    )
    more = reading_effects(heartburn, tapped_answer=SYMPTOMS_HEAD_COLD)
    assert (more.ask_symptom_question, more.ask_words) == (True, "heartburn")
    assert more.chest_question is True

    # Feeling unwell sits below a head cold: he has said what it is.
    off = _reading(unwell=_flag("present", words="feel rough"))
    assert reading_effects(off, tapped_answer=SYMPTOMS_NONE).ask_symptom_question is True
    assert reading_effects(off, tapped_answer=SYMPTOMS_HEAD_COLD).ask_symptom_question is False


def test_no_tapped_answer_ever_changes_the_floor_or_adds_a_question() -> None:
    """Every flag, state, person, time and tapped answer: his tap only removes a question."""
    for name in FLAGS:
        for state, who, when in itertools.product(
            ("present", "absent", "unclear"),
            ("him", "someone_else", "unknown"),
            ("now", "last_night", "earlier", "unknown"),
        ):
            reading = _reading(**{name: _flag(state, who, when, words="words")})
            untapped = reading_effects(reading)
            for tapped in (None, *SYMPTOM_ANSWERS):
                effects = reading_effects(reading, tapped_answer=tapped)
                assert effects.symptom_answer == untapped.symptom_answer
                assert effects.feel_notch == untapped.feel_notch
                assert not (effects.ask_symptom_question and not untapped.ask_symptom_question)
                if effects.chest_question:
                    assert effects.ask_symptom_question is True
                    assert name == SYMPTOMS_CHEST_HEART and effects.symptom_answer is None
                if effects.symptom_answer is not None and tapped is not None:
                    # A floor the note sets is asked about unless his tap already covers it.
                    covered = SYMPTOM_SEVERITY[tapped] >= SYMPTOM_SEVERITY[effects.symptom_answer]
                    assert effects.ask_symptom_question is not covered


# -- the packet: reasons, notice, plan lines, Today's action --------------------------------


def _packet(
    workouts: list[PlannedWorkout], easing: dict[str, Any] | None
) -> tuple[dict[str, Any], GradedVerdict]:
    """A good-numbers morning's ladder packet and graded verdict, as production builds them."""
    ladder = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=workouts,
        symptom_easing=easing,
    )
    verdict = grade(
        replace(
            _inputs(),
            acute=ladder["acutePhysiology"],
            sessions=tuple(classify_planned_workout(workout) for workout in workouts),
        )
    )
    return graded_verdict_packet(ladder, verdict, workouts, breathwork_line=None), verdict


def test_the_easy_day_back_reads_first_carries_its_notice_and_swaps_the_plan_line() -> None:
    sweet_spot = _sweet_spot()
    easing = _fever_return()
    packet, verdict = _packet([sweet_spot], easing)

    # The rail was built with no rows, so missing data would hold the day at Amber anyway;
    # what matters here is that the easing leads and the session is swapped.
    assert verdict.floor == FLOOR_HARD_WORK_TO_EASY
    assert packet["reasons"][0] == easing["reason"]
    assert packet["planAdjustments"][0] == EASY_RIDING_PLAN_LINE
    assert GRADED_EASE_HARD_LINE not in packet["planAdjustments"]
    assert "fever_return_easy_riding" in packet["safetyRulesApplied"]
    assert packet["graded"]["actions"][0]["action"] == ACTION_RECOVERY
    assert packet["graded"]["floor"] == FLOOR_HARD_WORK_TO_EASY

    acute = packet["acutePhysiology"]
    assert acute["symptoms"]["easing"]["kind"] == EASING_FEVER_RETURN
    assert acute["symptoms"]["triggered"] is False  # nothing sets a floor today
    assert acute["requiresTrainingRest"] is False
    # The notice stands where the fever's stood, under the head cold's heading: the web
    # heads a symptom notice at level "ease" with "Why today is capped".
    assert acute["escalations"][0] == {
        "kind": "symptoms",
        "level": "ease",
        "message": easing["notice"],
    }


def test_the_chest_question_has_no_notice_and_says_why_under_the_colour() -> None:
    easing = chest_question_easing("heartburn")
    packet, verdict = _packet([_sweet_spot()], easing)
    assert verdict.easing == EASING_CHEST_QUESTION
    assert packet["reasons"][0] == chest_question_line("heartburn")
    assert packet["planAdjustments"][0] == EASY_RIDING_PLAN_LINE
    assert "chest_question_easy_riding" in packet["safetyRulesApplied"]
    # Its card on Home says it; the notice card is for what he has told the app.
    assert [
        item for item in packet["acutePhysiology"]["escalations"] if item["kind"] == "symptoms"
    ] == []


def test_the_ladder_is_given_neither_easing_and_no_notice() -> None:
    """The rollback path is unchanged: `VERDICT_ENGINE=ladder` applies neither."""
    rail = _acute_physiology_rail(
        daily_metric=None, sleep=None, baselines={}, recent_daily_metrics=[], recent_sleeps=[]
    )
    assert rail["symptoms"]["easing"] is None
    assert rail["escalations"] == []
    assert SYMPTOM_FOLLOW_THROUGH_RULE not in LADDER_SYSTEM_PROMPT


def test_todays_action_describes_the_ride_by_what_was_done_to_it() -> None:
    """An Amber morning with the easy spin read "Ease the hard intervals to ~60% FTP —
    full length" for a ride cut in half."""
    spin = {
        "verdict": "Red",
        "graded": True,
        "adjustedDurationMin": 15,
        "adjustedWorkPowerPct": 60,
    }
    assert _eased_ride_detail("Amber", spin) == (
        "Substitute recovery — no intervals, ~60% FTP for 15 min."
    )
    # The graded Amber's own ease, and a Red morning's spin, read as they did.
    eased = {"verdict": "Amber", "graded": True, "adjustedWorkPowerPct": 76}
    assert _eased_ride_detail("Amber", eased) == (
        "Ease the hard intervals to ~76% FTP — full length."
    )
    assert _eased_ride_detail("Red", spin) == _eased_ride_detail("Amber", spin)


def _swap(move_to: date, bring_forward: PlannedWorkout) -> SwapSuggestion:
    return SwapSuggestion(
        subject_date=FRIDAY,
        hard_workout_id=uuid.uuid4(),
        hard_title="VO2 Max 30/30",
        hard_category="bike",
        move_to_date=move_to,
        bring_forward_workout_id=bring_forward.id,
        bring_forward_title=bring_forward.title,
    )


@pytest.mark.asyncio
async def test_a_week_swap_is_not_offered_where_it_would_undo_the_easing() -> None:
    """The verdict leads with a swap on a cautious morning (Batch 66). After a symptom it
    must not move the hard session onto another easy day back, or bring one forward."""
    zone_two, sweet_spot = _z2(), _sweet_spot()
    rides = {zone_two.id: zone_two, sweet_spot.id: sweet_spot}
    session = Mock()
    session.get = AsyncMock(side_effect=lambda _model, key: rides.get(key))
    service = MorningAnalysisService(session)
    easing = _fever_return(1)  # reported Thursday: Friday and Saturday are the easy days
    back = grade(replace(_inputs(), acute=_acute_with(easing), sessions=(VO2,)))
    saturday, sunday = FRIDAY + timedelta(1), FRIDAY + timedelta(2)

    blocked = service._swap_blocked_by_easing
    # Onto the second easy day: it would only be eased again.
    assert await blocked(_swap(saturday, zone_two), graded=back, easing=easing) is True
    # Past the easy days, for an easy ride today: that is the week kept, as he prefers.
    assert await blocked(_swap(sunday, zone_two), graded=back, easing=easing) is False
    # Past the easy days, but for a session that is hard work today.
    assert await blocked(_swap(sunday, sweet_spot), graded=back, easing=easing) is True

    # While a chest question is open, the question comes first, wherever the swap goes.
    question = chest_question_easing("heartburn")
    asking = grade(replace(_inputs(), acute=_acute_with(question), sessions=(VO2,)))
    assert await blocked(_swap(sunday, zone_two), graded=asking, easing=question) is True

    # An ordinary Amber morning is untouched.
    ordinary = grade(replace(_inputs(sleep_score=55), sessions=(VO2,)))
    assert ordinary.easing is None
    assert await blocked(_swap(saturday, sweet_spot), graded=ordinary, easing=None) is False


def test_the_brief_is_told_what_follows_a_symptom_and_the_version_moved() -> None:
    assert GRADED_PROMPT_VERSION == "morning-analysis-v58-2026-10-06"
    assert SYMPTOM_FOLLOW_THROUGH_RULE in GRADED_SYSTEM_PROMPT
    rule = " ".join(SYMPTOM_FOLLOW_THROUGH_RULE.split())
    assert "Never call the day Red for it" in rule
    assert "never decide for him whether it is a symptom" in rule
    assert "Add no medical advice of your own." in rule


# -- Home: the card knows whether the question is holding the session -----------------------


def _stored_morning(
    *,
    ask: bool,
    chest_question: bool,
    floor: str | None,
    easing: str | None = EASING_CHEST_QUESTION,
) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=FRIDAY,
        generated_at_utc=datetime(2026, 10, 9, 7, 0),
        verdict="Amber",
        prompt_version=GRADED_PROMPT_VERSION,
        model_name=None,
        output_markdown="",
        raw_response={},
        context_packet={
            "verdict": {
                "engine": "graded",
                "status": "Amber",
                "graded": {"floor": floor, "easing": easing if floor else None},
                "notesReading": {
                    "status": "read",
                    "askSymptomQuestion": ask,
                    "askWords": "heartburn",
                    "chestQuestion": chest_question,
                },
            }
        },
    )


def test_home_is_told_when_the_question_is_holding_the_hard_session() -> None:
    held = _serialize_analysis(
        _stored_morning(ask=True, chest_question=True, floor=FLOOR_HARD_WORK_TO_EASY)
    )
    assert held is not None
    assert (held.notesAsk, held.notesAskWords, held.notesAskEases) == (True, "heartburn", True)

    # No hard session was planned, so nothing was eased and the card keeps its usual line.
    asks = _serialize_analysis(_stored_morning(ask=True, chest_question=True, floor=None))
    assert asks is not None and (asks.notesAsk, asks.notesAskEases) == (True, False)
    # A sore throat on an easy day back: eased, but not by this question.
    other = _serialize_analysis(
        _stored_morning(
            ask=True,
            chest_question=False,
            floor=FLOOR_HARD_WORK_TO_EASY,
            easing=EASING_FEVER_RETURN,
        )
    )
    assert other is not None and other.notesAskEases is False
    # Heartburn on an easy day back: the session is eased whatever he answers, so the card
    # does not promise that answering brings it back.
    both = _serialize_analysis(
        _stored_morning(
            ask=True,
            chest_question=True,
            floor=FLOOR_HARD_WORK_TO_EASY,
            easing=EASING_FEVER_RETURN,
        )
    )
    assert both is not None and (both.notesAsk, both.notesAskEases) == (True, False)
    # Answered: the card is gone, so it says nothing.
    done = _stored_morning(ask=False, chest_question=False, floor=FLOOR_HARD_WORK_TO_EASY)
    assert _chest_question_eases(done.context_packet["verdict"]) is False
    # A morning stored before the batch carries neither field.
    assert _chest_question_eases({"notesReading": {"askSymptomQuestion": True}}) is False
    assert _chest_question_eases(None) is False


# -- the words are the ones Craig signed off -------------------------------------------------


def test_every_new_line_is_in_the_signed_off_draft() -> None:
    draft = _draft()
    assert "signed off by Craig on Mark's behalf, 2 Oct 2026" in draft
    floor = SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART]
    first = _fever_return(1)
    for words in (
        floor.notice,
        floor.reason,
        first["notice"],
        first["reason"],
        EASY_RIDING_PLAN_LINE,
        GRADED_ZONE_TWO_LINE,
        "Until you answer, today's hard session is an easy ride.",
    ):
        assert words in draft, words
    # The second morning's notice differs by its one word, as the draft says.
    assert 'The second morning reads "the second of two easy days back"' in draft


def test_the_server_and_the_card_say_the_question_holds_the_session_in_the_same_words() -> None:
    """The card's line is the web's (`notesAsk.ts`); the reason under the colour is the
    server's. One sentence, so one test holds the two together."""
    web = WEB_NOTES_ASK.read_text(encoding="utf-8")
    for words in (None, "heartburn"):
        line = chest_question_line(words)
        lead, tail = line.split(". ", 1)
        assert tail == "Until you answer, today’s hard session is an easy ride."
        assert tail in web
        assert lead.split("“")[0] in web


# -- on Postgres ------------------------------------------------------------------------------

#: A Thursday well before any plausible "today". A fresh profile's first morning seeds a
#: default training plan from the current cycle's start (``CoachingStateService
#: .ensure_seeded``, anchored on the real date), so a test morning dated this month
#: collides with that plan's own sessions and is shaped by its light weeks. The first CI
#: run of these tests, dated 7-11 Oct 2026, failed on exactly that.
SEEDED_THURSDAY = date(2026, 8, 13)


async def _seed_good_days(
    session: AsyncSession, first_day: date, days: int
) -> tuple[Profile, dict[date, ManualEntry], dict[date, PlannedWorkout]]:
    """Good numbers on every day, a check-in answered None, and a VO2 session planned."""
    user_id = uuid.uuid4()
    player = Profile(
        id=user_id,
        display_name="Follow Through",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    entries: dict[date, ManualEntry] = {}
    rides: dict[date, PlannedWorkout] = {}
    for offset in range(-42, days):
        day = first_day + timedelta(days=offset)
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=day,
                phase=DAILY_METRIC_PHASE_MORNING,
                recorded_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=6),
                readiness_score=70,
                readiness_level="HIGH",
                hrv_last_night_avg_ms=(46, 47, 48)[offset % 3],
                hrv_weekly_avg_ms=47,
                hrv_status="BALANCED",
                hrv_baseline_low_ms=43,
                hrv_baseline_high_ms=55,
                resting_heart_rate_bpm=45,
                raw_payload={},
            )
        )
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=day,
                score=82,
                duration_sec=(440, 450, 460)[offset % 3] * 60,
                raw_payload={},
                factors_json={},
            )
        )
        if offset < 0:
            continue
        entry = ManualEntry(
            user_id=user_id,
            entry_date=day,
            entry_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=6),
            subjective_score=8,
            feel="good",
            supplements_json={},
            food_json={},
            sleep_setup_json={},
            symptoms=SYMPTOMS_NONE,
        )
        ride = PlannedWorkout(
            user_id=user_id,
            workout_date=day,
            version=1,
            title="VO2 Max 30/30",
            workout_type="bike_vo2",
            status="planned",
            is_active=True,
            planned_duration_min=60,
            intensity_target="105-110% FTP",
            structured_workout=VO2_STRUCTURED,
            source="test",
        )
        session.add_all([entry, ride])
        entries[day], rides[day] = entry, ride
    await session.commit()
    return player, entries, rides


async def _graded(session: AsyncSession, player: Profile, day: date) -> dict[str, Any]:
    """The morning as the pipeline's first stage stores it; no paid call is made."""
    morning = await MorningAnalysisService(session).grade_and_store(player, day, force=True)
    verdict: dict[str, Any] = morning.analysis.context_packet["verdict"]
    return verdict


def _ride_action(verdict: dict[str, Any]) -> str:
    [action] = verdict["graded"]["actions"]
    return str(action["action"])


@pytest.mark.asyncio
async def test_on_postgres_the_two_mornings_after_a_fever_are_eased_and_the_third_is_not(
    db_conn: AsyncConnection,
) -> None:
    """303.2 end to end. On `main` the first morning after the fever was Green, VO2 as planned."""
    fever_day = SEEDED_THURSDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, fever_day - timedelta(1), 5)
        days = sorted(entries)

        ordinary = await _graded(session, player, days[0])
        assert (ordinary["status"], _ride_action(ordinary)) == ("Green", ACTION_AS_PLANNED)
        assert ordinary["acutePhysiology"]["symptoms"]["easing"] is None

        entries[fever_day].symptoms = SYMPTOMS_FEVER_ACHES
        await session.commit()
        fever = await _graded(session, player, fever_day)
        assert fever["status"] == "Red"
        assert fever["acutePhysiology"]["requiresTrainingRest"] is True

        for day, number, ordinal in ((days[2], 1, "first"), (days[3], 2, "second")):
            back = await _graded(session, player, day)
            easing = back["acutePhysiology"]["symptoms"]["easing"]
            assert (easing["kind"], easing["day"], easing["reportedOn"]) == (
                EASING_FEVER_RETURN,
                number,
                fever_day.isoformat(),
            )
            assert (back["status"], back["held"]) == ("Amber", False)
            assert back["graded"]["floor"] == FLOOR_HARD_WORK_TO_EASY
            assert _ride_action(back) == ACTION_RECOVERY
            assert back["reasons"][0] == (
                f"Easing back after the fever you reported on Thursday: easy riding only, "
                f"day {number} of 2."
            )
            assert EASY_RIDING_PLAN_LINE in back["planAdjustments"]
            notice = back["acutePhysiology"]["escalations"][0]
            assert (notice["kind"], notice["level"]) == ("symptoms", "ease")
            assert f"the {ordinal} of two easy days back" in notice["message"]
            # The ride Home offers is the easy spin, and Today's action says so.
            adjustment = back["verdictAdjustment"]
            assert adjustment["verdict"] == "Red" and adjustment["adjustedWorkPowerPct"] <= 60
            [approve] = [item for item in back["todayActions"] if item["kind"] == "approve_ride"]
            assert approve["detail"].startswith("Substitute recovery")

        third = await _graded(session, player, days[4])
        assert (third["status"], _ride_action(third)) == ("Green", ACTION_AS_PLANNED)
        assert third["acutePhysiology"]["symptoms"]["easing"] is None
        notices = third["acutePhysiology"]["escalations"]
        assert [item for item in notices if item["kind"] == "symptoms"] == []


@pytest.mark.asyncio
async def test_on_postgres_a_fever_he_corrected_the_same_day_starts_no_easy_days(
    db_conn: AsyncConnection,
) -> None:
    """The latest stored morning of a day decides, so a mis-tap he put right leaves nothing."""
    fever_day = SEEDED_THURSDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, fever_day, 2)
        entries[fever_day].symptoms = SYMPTOMS_FEVER_ACHES
        await session.commit()
        assert (await _graded(session, player, fever_day))["status"] == "Red"

        entries[fever_day].symptoms = SYMPTOMS_NONE
        await session.commit()
        assert (await _graded(session, player, fever_day))["status"] == "Green"

        next_day = await _graded(session, player, fever_day + timedelta(1))
        assert (next_day["status"], _ride_action(next_day)) == ("Green", ACTION_AS_PLANNED)
        assert next_day["acutePhysiology"]["symptoms"]["easing"] is None


async def _store_reading(
    session: AsyncSession, entry: ManualEntry, reading: dict[str, Any]
) -> CheckInReading:
    row = CheckInReading(
        user_id=entry.user_id,
        manual_entry_id=entry.id,
        notes_sha256=notes_hash(entry.notes),
        status=STATUS_READ,
        reading=reading,
        model_name="claude-test",
        prompt_version=PROMPT_VERSION,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_on_postgres_heartburn_eases_the_hard_session_until_he_answers_on_home(
    db_conn: AsyncConnection,
) -> None:
    """303.4 and 303.5 end to end. On `main` the VO2 session went ahead unanswered, and
    any save of the check-in was the answer."""
    day = SEEDED_THURSDAY + timedelta(days=1)
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, day, 1)
        user_id = player.id
        entry = entries[day]
        entry.notes = "Big curry late last night and heartburn kept me awake."
        await session.commit()
        await _store_reading(
            session,
            entry,
            _reading(chest_heart=_flag("unclear", when="last_night", words="heartburn")),
        )

        asked = await _graded(session, player, day)
        assert (asked["status"], _ride_action(asked)) == ("Amber", ACTION_RECOVERY)
        assert asked["graded"]["easing"] == EASING_CHEST_QUESTION
        assert asked["reasons"][0] == chest_question_line("heartburn")
        assert asked["planAdjustments"][0] == EASY_RIDING_PLAN_LINE
        assert "swapSuggestion" not in asked  # the question comes before a rearranged week
        assert asked["notesReading"]["askSymptomQuestion"] is True
        stored = await MorningAnalysisService(session).latest_analysis(user_id, day)
        serialized = _serialize_analysis(stored)
        assert serialized is not None
        assert (serialized.notesAsk, serialized.notesAskEases) == (True, True)

        # He saves the check-in again an hour later, to add his breakfast: not an answer.
        resaved_at = entry.entry_at_utc + timedelta(days=1)  # well after the reading
        entry.food_json = {"breakfast": "porridge"}
        entry.entry_at_utc = resaved_at
        await session.commit()
        resaved = await _graded(session, player, day)
        assert (resaved["status"], _ride_action(resaved)) == ("Amber", ACTION_RECOVERY)
        assert resaved["notesReading"]["answeredAfterReading"] is False
        assert resaved["notesReading"]["askSymptomQuestion"] is True

        # He taps "None" on Home: an answer of its own, which saves nothing else.
        await DailyLoopService(session).answer_symptom_question(
            player, subject_date=day, answer=SYMPTOMS_NONE
        )
        await session.refresh(entry)
        assert entry.symptoms == SYMPTOMS_NONE
        assert entry.symptoms_answered_at_utc is not None
        assert entry.entry_at_utc == resaved_at
        assert entry.food_json == {"breakfast": "porridge"}
        assert entry.notes == "Big curry late last night and heartburn kept me awake."

        answered = await _graded(session, player, day)
        assert (answered["status"], _ride_action(answered)) == ("Green", ACTION_AS_PLANNED)
        assert answered["notesReading"]["answeredAfterReading"] is True
        assert answered["notesReading"]["askSymptomQuestion"] is False
        assert answered["acutePhysiology"]["symptoms"]["easing"] is None


@pytest.mark.asyncio
async def test_on_postgres_a_chest_answer_on_home_is_the_floor(
    db_conn: AsyncConnection,
) -> None:
    """The question can make the day stricter as well as restore it."""
    day = SEEDED_THURSDAY + timedelta(days=1)
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, day, 1)
        entry = entries[day]
        entry.notes = "Big curry late last night and heartburn kept me awake."
        await session.commit()
        await _store_reading(
            session,
            entry,
            _reading(chest_heart=_flag("unclear", when="last_night", words="heartburn")),
        )
        await DailyLoopService(session).answer_symptom_question(
            player, subject_date=day, answer=SYMPTOMS_CHEST_HEART
        )
        answered = await _graded(session, player, day)
        assert answered["status"] == "Red"
        assert answered["acutePhysiology"]["requiresTrainingRest"] is True
        assert answered["acutePhysiology"]["symptoms"]["source"] == "answer"
        assert answered["notesReading"]["askSymptomQuestion"] is False


@pytest.mark.asyncio
async def test_on_postgres_the_answer_route_records_it_and_regrades_today_only(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date(2026, 7, 12)
    saved_at = datetime(2026, 7, 12, 7, 0)
    queued = AsyncMock()
    monkeypatch.setattr(daily_loop_router, "_generate_brief_after_checkin", queued)
    monkeypatch.setattr(daily_loop_router, "local_today", lambda _timezone: day)

    async with _savepoint_session(db_conn) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Answer Route",
            role=UserRole.player,
            timezone="UTC",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        user_id = player.id
        for entry_date in (day, day - timedelta(days=1)):
            session.add(
                ManualEntry(
                    user_id=user_id,
                    entry_date=entry_date,
                    entry_at_utc=saved_at - (day - entry_date),
                    subjective_score=7,
                    supplements_json={},
                    food_json={},
                    notes="Bit of heartburn.",
                    symptoms=SYMPTOMS_NONE,
                )
            )
        await session.commit()

        app.dependency_overrides[get_current_user] = lambda: player
        app.dependency_overrides[get_db] = _db_override(session)
        base = "/api/v1/daily-loop"
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                today = await client.post(
                    f"{base}/{day.isoformat()}/symptom-answer", json={"answer": "head_cold"}
                )
                yesterday = await client.post(
                    f"{base}/{(day - timedelta(days=1)).isoformat()}/symptom-answer",
                    json={"answer": "none"},
                )
                not_an_answer = await client.post(
                    f"{base}/{day.isoformat()}/symptom-answer", json={"answer": "a bit"}
                )
                no_check_in = await client.post(
                    f"{base}/{(day - timedelta(days=30)).isoformat()}/symptom-answer",
                    json={"answer": "none"},
                )
        finally:
            app.dependency_overrides.clear()

        assert today.status_code == 200, today.text
        assert yesterday.status_code == 200, yesterday.text
        assert not_an_answer.status_code == 422
        assert no_check_in.status_code == 404
        # Today's answer starts the regrade, and the envelope says a brief is on its way.
        queued.assert_awaited_once_with(user_id, day)
        assert today.json()["data"]["briefGeneration"] == {"status": "generating", "reason": None}
        assert today.json()["data"]["manualEntry"]["symptoms"] == "head_cold"

        rows = (
            (
                await session.execute(
                    select(ManualEntry)
                    .where(ManualEntry.user_id == user_id)
                    .order_by(ManualEntry.entry_date.desc())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        answered, earlier = rows
        assert (answered.symptoms, earlier.symptoms) == (SYMPTOMS_HEAD_COLD, SYMPTOMS_NONE)
        assert answered.symptoms_answered_at_utc is not None
        assert earlier.symptoms_answered_at_utc is not None
        # It was an answer, not a save: the time he checked in, and his note, are his.
        assert answered.entry_at_utc == saved_at
        assert answered.notes == "Bit of heartburn."
