"""Batch 355: coach chat v29 — the symptom answer, plain figures, and the plan's numbers.

Three changes Craig asked for in one prompt version:

* **The symptom answer today's call used** (Craig, 22 Oct 2026, "yes to 1-3"). The chat
  had no symptom rule and saw a symptom only as a floor's reason line, which quotes the
  colour its answer guard rejects: on the one day a floor fired, quoting it would have
  cost Mark his answer. It now holds ``todaysSymptomAnswer`` — never the bare tap — and a
  symptom rule, and the floor is in the registry so the brief and the chat are audited
  for it.
* **Plain figures** (Decisions #432 and #440): 8 of 83 October answers said "median" or
  "samples"; the chat takes the brief's words.
* **The plan's numbers** (v28's replay): two answers repeated an earlier answer's week-1
  sets for a session the plan had since moved on, one called the plan's list general
  guidance, and two offered to restate instead of answering.

The packets below are built by the app's own functions (``symptom_signal`` and the
easings), never hand-written, so a change to the stored shape fails here. Every reading
and every word in a note is invented: Mark has never reported a symptom. The two path
tests need a real Postgres and skip locally without one; CI runs them.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from structlog.testing import capture_logs

from src.models.coaching import Analysis
from src.models.profile import Profile, UserRole
from src.services import morning_analysis
from src.services.brief_chat import (
    FINAL_REPLY_RULE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    _guard_mark_answer,
    _log_answer_shape,
)
from src.services.chat_context import _DROP_ORDER, ChatContextService, CoachOrigin
from src.services.coach_policy import (
    CHEST_HEART_NOTICE,
    FLOORS,
    GENERAL_SCIENCE_RULE,
    READ_PROMPT_FLOORS,
    STATISTICS_WORDING_LEAKS,
    SYMPTOM_RULE,
    floors_sentence,
    missing_floors,
    statistics_wording_leaks,
)
from src.services.recent_mornings import (
    MorningCall,
    build_recent_mornings,
    todays_symptom_answer,
)
from src.services.symptom_check import (
    EASING_CHEST_QUESTION,
    EASING_FEVER_RETURN,
    FOLLOW_UP_ANSWER_LABELS,
    FOLLOW_UP_ANSWERS,
    FOLLOW_UP_NOT_SEEN,
    FOLLOW_UP_STILL_THERE,
    SYMPTOM_ANSWERS,
    SYMPTOM_FLOORS,
    SYMPTOM_LABELS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
    SYMPTOMS_NONE,
    ChestFollowUp,
    IllnessReturn,
    chest_question_easing,
    fever_return_easing,
    plain_floor_reason,
    symptom_signal,
)

FLAT_PROMPT = " ".join(SYSTEM_PROMPT.split())
FLAT_FINAL = " ".join(FINAL_REPLY_RULE.split())

#: Well in the past, so no seeded default plan can share these dates.
TODAY = date(2026, 7, 29)
EARLIER = date(2026, 7, 27)
WEB_FOLLOW_UP = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "chestFollowUp.ts"

#: Every code the stored record can carry. None may reach the coach as a value.
CODES = {
    *SYMPTOM_ANSWERS,
    *FOLLOW_UP_ANSWERS,
    "no_training_see_doctor",
    "no_training_until_clear",
    "easy_riding_only",
    "red_floor",
    EASING_FEVER_RETURN,
    EASING_CHEST_QUESTION,
    "chest_follow_up",
}
SNAKE_CASE = re.compile(r"\b[a-z]+_[a-z_]+\b")


def _symptoms(
    answer: str | None,
    *,
    source: str = "answer",
    words: str | None = None,
    easing: dict[str, Any] | None = None,
    follow_up: ChestFollowUp | None = None,
) -> dict[str, Any]:
    """The stored record, as ``morning_verdict.acute_physiology_rail`` writes it."""
    record = symptom_signal(answer, easing=easing, follow_up=follow_up)
    record["source"] = source if answer is not None else None
    record["words"] = words if source == "notes" else None
    return record


def _call(
    symptoms: dict[str, Any] | None,
    *,
    day: date = TODAY,
    at: time = time(8, 30),
    reasons: list[str] | None = None,
    graded_easing: str | None = None,
) -> MorningCall:
    return MorningCall(
        subject_date=day,
        generated_at_utc=datetime.combine(day, at),
        verdict="Red" if symptoms and symptoms.get("triggered") else "Green",
        reasons=reasons or [],
        verdict_adjustment=None,
        requires_bike_rest=bool(symptoms and symptoms["requiresBikeRest"]),
        requires_training_rest=bool(symptoms and symptoms["requiresTrainingRest"]),
        rest_day={},
        planned_workouts=[],
        symptoms=symptoms,
        graded_easing=graded_easing,
    )


def _values(record: dict[str, Any]) -> list[str]:
    """Every string the coach is given as a value (the meaning names its own fields)."""
    found: list[str] = []
    for key, value in record.items():
        if key == "meaning":
            continue
        if isinstance(value, dict):
            found.extend(_values(value))
        elif isinstance(value, str):
            found.append(value)
    return found


# ---------------------------------------------------------------------------
# The version
# ---------------------------------------------------------------------------


def test_v29_is_one_prompt_version_for_all_three_changes() -> None:
    assert PROMPT_VERSION == "coach-chat-v30-2026-10-29"


# ---------------------------------------------------------------------------
# 1. Plain figures, as the brief and the weekly review give them
# ---------------------------------------------------------------------------


def test_the_final_rule_gives_figures_in_the_briefs_plain_words() -> None:
    assert "Any median, whatever its field is called, is his usual" in FLAT_FINAL
    assert "'your usual' says all of it" in FLAT_FINAL
    assert "'usually' for a timing" in FLAT_FINAL
    assert "the span between its quartiles is his usual range" in FLAT_FINAL
    assert "'higher than usual for you'" in FLAT_FINAL
    assert (
        "Median, quartile, percentile and standard deviation are words for your reasoning, "
        "never for Mark, even beside 'your usual'"
    ) in FLAT_FINAL
    assert "('over 84 nights'), never 'n=', 'samples' or a sample size" in FLAT_FINAL
    assert "give a change as a plain figure" in FLAT_FINAL
    # The brief's last-line check (Decision #440's draft 3); draft 1 left a median in a
    # replayed REM-timing answer.
    assert (
        "Before sending, reread every line for median, quartile, percentile, standard "
        "deviation, 'n=' and 'samples', and say any line with one again without it."
    ) in FLAT_FINAL
    # What the old sentence held stays held.
    assert "Use no physiology jargon" in FLAT_FINAL
    assert "colour words in any form (including hyphenated phrases" in FLAT_FINAL


def test_the_chat_logs_the_same_statistics_words_the_brief_does() -> None:
    assert morning_analysis._BRIEF_WORDING_LEAKS is STATISTICS_WORDING_LEAKS
    # Invented phrasings of the October shapes, not Mark's figures.
    assert statistics_wording_leaks("against your baseline median of 50 ms") == ("median",)
    assert statistics_wording_leaks("a 3% drift over 20 samples") == ("sample_count",)
    assert statistics_wording_leaks("not a large sample size") == ("sample_count",)
    assert statistics_wording_leaks("n=12 nights, upper quartile 60") == (
        "quartile_or_percentile",
        "sample_count",
    )
    assert statistics_wording_leaks("one standard deviation below") == ("standard_deviation",)
    assert statistics_wording_leaks("50 ms against your usual 46, over 20 rides") == ()

    with capture_logs() as logs:
        _log_answer_shape("Your usual is 46 ms, but your median says more.", uuid.uuid4())
    (shape,) = [entry for entry in logs if entry["event"] == "coach_answer_shape"]
    assert shape["statistics_words"] == ["median"]
    assert shape["banned_terms"] == []


# ---------------------------------------------------------------------------
# 2. The symptom rule and the floor
# ---------------------------------------------------------------------------


def test_the_symptom_rule_is_composed_into_the_coachs_brief() -> None:
    flat_rule = " ".join(SYMPTOM_RULE.split())
    assert flat_rule in FLAT_PROMPT
    # The record is named where the prompt lists what the coach holds (a closed list).
    assert "the symptom answer this morning's call used and what it set" in FLAT_PROMPT
    # 1. Fixed, explained by his answer, never eased; no training of any kind on a rest floor.
    assert "Explain a symptom's limit, and what follows it, by his own answer" in flat_rule
    assert "never ease, shorten or argue either down" in flat_rule
    assert "no ride, strength, mobility or training walk" in flat_rule
    # 2. Never diagnose or explain it away.
    assert "Never diagnose, never call a symptom harmless or explain it away" in flat_rule
    assert "give no medical advice but the app's own words" in flat_rule
    # 3. The app's own notice, word for word, from the one copy the app shows. Draft 1's
    # "give the app's notice word for word" was copied exactly in 1 of 3 replayed answers.
    assert CHEST_HEART_NOTICE == SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART].notice
    assert (
        "copy the app's notice into your answer exactly, as its own paragraph, changing no "
        f'word: "{CHEST_HEART_NOTICE}"'
    ) in flat_rule
    assert "or he describes chest or heart symptoms to you" in flat_rule
    # 4. A symptom told only to the coach sets nothing.
    assert "changes nothing in today's plan" in flat_rule
    assert "answer the symptom question in his check-in now, so today's plan fits it" in flat_rule
    assert "never decide for him whether it counts" in flat_rule
    # Draft 1's replay told him updating his check-in answer would lift the floor.
    assert "Never suggest that changing an answer would lift a limit" in flat_rule
    # 5. Only Home ends the chest or heart follow-up.
    assert (
        "Only his answer to the chest or heart question Home asks from the morning after a "
        "report ends that follow-up"
    ) in flat_rule
    # 6. "None" is preselected.
    assert '"None", which the check-in preselects, and no answer are never evidence' in flat_rule
    # 7. Chest or heart is never the illness behind a dip.
    assert "Chest or heart symptoms are never the illness that explains a dip" in flat_rule


def test_the_final_rule_keeps_the_notice_whole() -> None:
    assert (
        "Never ease a symptom's limit, diagnose, call a symptom harmless, or tell him there "
        "is nothing to worry about while a symptom or what follows it stands"
    ) in FLAT_FINAL
    # Restated last, with the notice itself: draft 3 left it out of 1 of 2 replayed
    # answers on a chest or heart day, where the rule named it only far above.
    assert (
        "When today's call used a chest or heart answer, or he describes chest or heart "
        "symptoms to you, your answer must include the app's notice exactly, as its own "
        f'paragraph: "{CHEST_HEART_NOTICE}"'
    ) in FLAT_FINAL
    assert "leaving out a list he asked for and the chest or heart notice" in FLAT_FINAL
    assert "remove secondary detail, never the notice" in FLAT_FINAL
    # v27's illness definition stands beside it.
    assert "illness (a cold, fever or aches, never chest or heart symptoms)" in FLAT_FINAL


def test_the_symptom_floor_is_registered_and_audited() -> None:
    (floor,) = [floor for floor in FLOORS if floor.key == "symptom_floor"]
    assert floor.sentence in floors_sentence()
    assert floor.sentence in FLAT_PROMPT
    # The brief has stated it since Batch 294.
    assert "symptom_floor" in READ_PROMPT_FLOORS["morning_analysis"]
    assert missing_floors(morning_analysis.SYSTEM_PROMPT, ("symptom_floor",)) == ()
    assert missing_floors(floor.negative_control, ("symptom_floor",)) == ("symptom_floor",)
    # The last clause of the sentence is still the one it was.
    assert floors_sentence().endswith(f"and {FLOORS[-1].sentence}.")
    assert FLOORS[-1].key == "no_invented_derivation"


# ---------------------------------------------------------------------------
# The floor's reason no longer costs Mark his answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer", list(SYMPTOM_FLOORS))
def test_a_floor_reason_reaches_the_coach_without_its_colour(answer: str) -> None:
    stored = SYMPTOM_FLOORS[answer].reason
    plain = plain_floor_reason(stored)

    assert "Red floor" in stored
    assert not re.search(r"\b(?:red|amber|green)\b", plain, re.IGNORECASE)
    assert plain == stored.replace(" sets a Red floor: ", ": ")
    # Quoted as given, it is delivered unchanged.
    assert _guard_mark_answer(plain, uuid.uuid4()) == plain


@pytest.mark.parametrize("answer", list(SYMPTOM_FLOORS))
def test_a_quoted_stored_reason_is_translated_rather_than_refused(answer: str) -> None:
    """A question from the brief holds the stored copy, colour and all.

    v28's guard refused all three (checked 22 and 27 Oct at $0), so on the day a floor
    fired, quoting its reason would have shown Mark "The coach couldn't answer just now".
    """
    stored = SYMPTOM_FLOORS[answer].reason
    delivered = _guard_mark_answer(stored, uuid.uuid4())
    assert "sets a recovery floor:" in delivered
    assert "Red" not in delivered


def test_the_guard_still_refuses_a_colour_that_is_not_a_grade() -> None:
    with pytest.raises(HTTPException):
        _guard_mark_answer("Today is Red, so rest.", uuid.uuid4())
    assert plain_floor_reason("Your numbers are all within your usual range.") == (
        "Your numbers are all within your usual range."
    )


def test_recent_mornings_quote_the_floor_reason_without_its_colour() -> None:
    stored = SYMPTOM_FLOORS[SYMPTOMS_FEVER_ACHES].reason
    section = build_recent_mornings(
        today=TODAY,
        mornings=[_call(_symptoms(SYMPTOMS_FEVER_ACHES), reasons=[stored, "A summary line."])],
        audits=[],
    )
    reasons = section["days"][0]["reasons"]
    assert reasons == [plain_floor_reason(stored), "A summary line."]
    for reason in reasons:
        assert _guard_mark_answer(reason, uuid.uuid4()) == reason


# ---------------------------------------------------------------------------
# todaysSymptomAnswer: the answer the call used, never the bare tap
# ---------------------------------------------------------------------------


def test_no_morning_yet_today_says_so() -> None:
    record = todays_symptom_answer(
        today=TODAY, mornings=[_call(_symptoms(SYMPTOMS_NONE), day=EARLIER)]
    )
    assert record["morningOf"] is None
    assert set(record) == {"morningOf", "meaning"}


def test_none_and_no_answer_are_given_as_they_are() -> None:
    none = todays_symptom_answer(today=TODAY, mornings=[_call(_symptoms(SYMPTOMS_NONE))])
    assert none["answer"] == "None"
    assert none["answeredWith"] == "his answer to the check-in's symptom question"
    assert "whatItMeans" not in none
    assert '"None" is preselected on the form' in none["meaning"]

    unanswered = todays_symptom_answer(today=TODAY, mornings=[_call(_symptoms(None))])
    assert unanswered["answer"] is None
    assert unanswered["answeredWith"] is None
    assert "never means he is well" in unanswered["meaning"]


def test_a_chest_or_heart_floor_carries_the_notice_word_for_word() -> None:
    record = todays_symptom_answer(today=TODAY, mornings=[_call(_symptoms(SYMPTOMS_CHEST_HEART))])
    floor = SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART]
    assert record["morningOf"] == TODAY.isoformat()
    assert record["answer"] == SYMPTOM_LABELS[SYMPTOMS_CHEST_HEART]
    assert record["whatItMeans"] == plain_floor_reason(floor.reason)
    assert record["planLine"] == floor.plan_line
    assert record["notice"] == CHEST_HEART_NOTICE


def test_a_floor_from_his_note_is_the_answer_the_call_used() -> None:
    """The case the bare tap gets wrong: he tapped "None" and his note named it."""
    record = todays_symptom_answer(
        today=TODAY,
        mornings=[
            _call(
                _symptoms(
                    SYMPTOMS_CHEST_HEART, source="notes", words="fluttery heart on the stairs"
                )
            )
        ],
    )
    assert record["answer"] == SYMPTOM_LABELS[SYMPTOMS_CHEST_HEART]
    assert record["answeredWith"] == "his check-in note"
    assert record["hisWords"] == "fluttery heart on the stairs"
    assert record["notice"] == CHEST_HEART_NOTICE


def test_still_there_on_home_is_named_as_his_answer_there() -> None:
    follow_up = ChestFollowUp(reported_on=EARLIER, answer=FOLLOW_UP_STILL_THERE)
    record = todays_symptom_answer(
        today=TODAY,
        mornings=[_call(_symptoms(SYMPTOMS_CHEST_HEART, follow_up=follow_up))],
    )
    assert record["answeredWith"] == "his answer to Home's chest or heart question"
    assert record["chestFollowUp"] == {
        "reportedOn": EARLIER.isoformat(),
        "hisAnswerToday": "Still there",
        "stillOpen": True,
    }


@pytest.mark.parametrize("answer", [SYMPTOMS_FEVER_ACHES, SYMPTOMS_HEAD_COLD])
def test_the_other_floors_give_their_own_words(answer: str) -> None:
    record = todays_symptom_answer(today=TODAY, mornings=[_call(_symptoms(answer))])
    floor = SYMPTOM_FLOORS[answer]
    assert record["whatItMeans"] == plain_floor_reason(floor.reason)
    assert record["planLine"] == floor.plan_line
    assert record["notice"] == floor.notice


def test_an_easy_day_back_says_whether_it_eased_a_session() -> None:
    easing = fever_return_easing(IllnessReturn(reported_on=EARLIER, day=2))
    record = todays_symptom_answer(
        today=TODAY,
        mornings=[
            _call(_symptoms(SYMPTOMS_NONE, easing=easing), graded_easing=EASING_FEVER_RETURN)
        ],
    )
    assert record["answer"] == "None"
    assert record["whatItMeans"] == easing["reason"]
    assert record["planLine"] == easing["planLine"]
    assert record["notice"] == easing["notice"]
    assert record["easedTodaysHardSession"] is True


def test_a_chest_question_with_no_hard_session_eased_nothing() -> None:
    easing = chest_question_easing("tight across the chest")
    record = todays_symptom_answer(
        today=TODAY, mornings=[_call(_symptoms(SYMPTOMS_NONE, easing=easing))]
    )
    assert record["whatItMeans"] == easing["reason"]
    assert record["notice"] is None
    assert record["easedTodaysHardSession"] is False


def test_an_open_follow_up_gives_his_answer_in_homes_words() -> None:
    follow_up = ChestFollowUp(reported_on=EARLIER, answer=FOLLOW_UP_NOT_SEEN)
    record = todays_symptom_answer(
        today=TODAY, mornings=[_call(_symptoms(SYMPTOMS_NONE, follow_up=follow_up))]
    )
    assert record["chestFollowUp"] == {
        "reportedOn": EARLIER.isoformat(),
        "hisAnswerToday": "Gone, but I haven't spoken to anyone yet",
        "stillOpen": True,
    }


def test_the_latest_morning_today_is_the_one_used() -> None:
    record = todays_symptom_answer(
        today=TODAY,
        mornings=[
            _call(_symptoms(SYMPTOMS_NONE), at=time(6, 30)),
            _call(_symptoms(SYMPTOMS_HEAD_COLD), at=time(9, 5)),
            _call(_symptoms(SYMPTOMS_CHEST_HEART), day=EARLIER),
        ],
    )
    assert record["answer"] == SYMPTOM_LABELS[SYMPTOMS_HEAD_COLD]


def test_a_morning_from_before_the_question_was_asked_reads_as_unanswered() -> None:
    record = todays_symptom_answer(today=TODAY, mornings=[_call(None)])
    assert record["answer"] is None
    assert record["answeredWith"] is None


@pytest.mark.parametrize(
    "symptoms",
    [
        _symptoms(SYMPTOMS_CHEST_HEART, follow_up=ChestFollowUp(EARLIER, FOLLOW_UP_STILL_THERE)),
        _symptoms(SYMPTOMS_FEVER_ACHES),
        _symptoms(SYMPTOMS_HEAD_COLD, source="notes", words="blocked nose"),
        _symptoms(SYMPTOMS_NONE, easing=chest_question_easing(None)),
        _symptoms(SYMPTOMS_NONE, follow_up=ChestFollowUp(EARLIER, None)),
    ],
)
def test_the_record_carries_words_never_codes(symptoms: dict[str, Any]) -> None:
    record = todays_symptom_answer(today=TODAY, mornings=[_call(symptoms)])
    for value in _values(record):
        assert value not in CODES, value
        assert not SNAKE_CASE.search(value), value
        assert not re.search(r"\b(?:red|amber|green)\b", value, re.IGNORECASE), value


def test_homes_answer_labels_match_its_buttons() -> None:
    web = WEB_FOLLOW_UP.read_text()
    for code, label in FOLLOW_UP_ANSWER_LABELS.items():
        quoted = re.escape(label).replace("'", "['\"]?")
        assert re.search(rf"value: '{code}', label: [\"']{quoted}[\"']", web), code
    assert set(FOLLOW_UP_ANSWER_LABELS) == set(FOLLOW_UP_ANSWERS)


def test_the_record_is_never_dropped_for_length() -> None:
    assert "todaysSymptomAnswer" not in _DROP_ORDER


# ---------------------------------------------------------------------------
# 3. A session's numbers come from his plan as it stands
# ---------------------------------------------------------------------------


def test_a_sessions_numbers_come_from_the_plan_not_an_earlier_answer() -> None:
    assert "every exercise or step with its sets, reps, effort and rest" in FLAT_FINAL
    assert "from his plan as it stands now" in FLAT_FINAL
    assert "or points you to an earlier answer about one, he is asking for detail" in FLAT_FINAL
    # Draft 1's replay still recounted the 15 Oct answer's numbers and its "general
    # guidance" label in 2 of 3 answers.
    assert (
        "say they are his plan's, even where an earlier answer gave other numbers or called "
        "them general guidance"
    ) in FLAT_FINAL
    assert "never from an earlier answer, which may describe an earlier week" in FLAT_FINAL
    # Draft 2's replay repeated the 24 Oct live answers' "the plan only stores sets/reps".
    assert "never say it holds less than its contents show, even if an earlier answer said so" in (
        FLAT_FINAL
    )
    assert (
        "When he asks for something you said before, give it in full; never offer to give it "
        "or more of it."
    ) in FLAT_FINAL
    flat_science = " ".join(GENERAL_SCIENCE_RULE.split())
    assert "as his plan holds it now" in flat_science
    assert "say that only this added part is general guidance" in flat_science
    assert "the exercises, sets, reps, effort and rest are his plan's" in flat_science
    assert "Keep the plan's sets, reps and effort as written" in flat_science


# ---------------------------------------------------------------------------
# Every path: Postgres (CI)
# ---------------------------------------------------------------------------


async def _profile(session: AsyncSession, name: str) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


def _morning_row(user_id: uuid.UUID, symptoms: dict[str, Any], at: time) -> Analysis:
    reasons = [symptoms["reason"]] if symptoms.get("reason") else []
    return Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        analysis_type="morning",
        subject_date=TODAY,
        generated_at_utc=datetime.combine(TODAY, at),
        prompt_version="morning-x",
        verdict="Red" if symptoms.get("triggered") else "Green",
        context_packet={
            "verdict": {
                "reasons": [*reasons, "A summary line."],
                "acutePhysiology": {
                    "requiresBikeRest": symptoms["requiresBikeRest"],
                    "requiresTrainingRest": symptoms["requiresTrainingRest"],
                    "symptoms": symptoms,
                },
                "graded": {"actions": [], "easing": None},
            },
            "restDay": {},
            "plannedWorkouts": [],
        },
        output_markdown="A read.",
        raw_response={},
    )


@pytest.mark.asyncio
async def test_a_question_from_home_sees_the_answer_the_call_used(
    db_conn: AsyncConnection,
) -> None:
    """Unanchored, so nothing but the live block can tell the coach."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session, "Symptom answer from Home")
        chest = _symptoms(SYMPTOMS_CHEST_HEART, source="notes", words="tight chest")
        session.add_all(
            [
                _morning_row(player.id, _symptoms(SYMPTOMS_NONE), time(6, 30)),
                _morning_row(player.id, chest, time(8, 40)),
                # After the question: never seen by it.
                _morning_row(player.id, _symptoms(SYMPTOMS_HEAD_COLD), time(9, 30)),
            ]
        )
        await session.commit()

        context = await ChatContextService(session).build(
            player,
            None,
            asked_at_utc=datetime.combine(TODAY, time(9, 0)),
            origin=CoachOrigin(kind="home", subject_date=TODAY),
        )

    record = context.app_state["todaysSymptomAnswer"]
    assert record["answer"] == SYMPTOM_LABELS[SYMPTOMS_CHEST_HEART]
    assert record["answeredWith"] == "his check-in note"
    assert record["hisWords"] == "tight chest"
    assert record["notice"] == CHEST_HEART_NOTICE
    today_row = context.app_state["recentMornings"]["days"][0]
    assert today_row["reasons"][0] == plain_floor_reason(
        SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART].reason
    )
    assert today_row["noTrainingAdvised"] is True


@pytest.mark.asyncio
async def test_a_question_before_the_morning_call_says_none_was_made(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session, "Symptom answer before the call")
        context = await ChatContextService(session).build(
            player,
            None,
            asked_at_utc=datetime.combine(TODAY, time(6, 0)),
            origin=CoachOrigin(kind="home", subject_date=TODAY),
        )

    assert context.app_state["todaysSymptomAnswer"]["morningOf"] is None
