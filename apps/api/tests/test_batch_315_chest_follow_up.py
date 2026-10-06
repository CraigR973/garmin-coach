"""Batch 315 — after a chest or heart report, ask before hard work.

A "Chest or heart" answer set the no-training floor that day only. The next morning,
if he tapped None and his numbers were fine, read "Green light · Make it count" before
VO2, and nothing asked whether he had been checked (Decision #375, Craig 2 Oct). The
guidance has exertional chest symptoms assessed before vigorous exercise resumes (ESC
2020, Pelliccia 2021; IOC 2022, Schwellnus 2022). Craig chose on 6 Oct to build the
follow-up, amending #375.

The rule: from the morning after a day whose latest stored morning carried the
chest-or-heart floor, until he says the symptoms have gone and that he has spoken to his
GP or 111, a hard session takes 303's ``recovery`` action and the day is at least Amber,
never Red for it; Zone 2, strength and mobility stay as planned; a stricter floor that
morning wins. Home asks each morning. "Still there" sets the chest-or-heart floor again.
Wording: ``docs/drafts/2026-10-06-batch-315-wording.md``.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import Analysis, SymptomFollowUp
from src.routers import daily_loop as daily_loop_router
from src.services.coaching_state import KB_SECTION_BUILDERS, PROFILE_MEDICATION
from src.services.daily_loop import DailyLoopService
from src.services.daily_loop_envelope import _chest_follow_up, _serialize_analysis
from src.services.generation_requests import with_chest_follow_up
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_SYSTEM_PROMPT,
    SYMPTOM_FOLLOW_THROUGH_RULE,
    MorningAnalysisService,
)
from src.services.morning_verdict import (
    GRADED_ZONE_TWO_LINE,
    _acute_physiology_rail,
    graded_verdict_packet,
    morning_verdict,
)
from src.services.symptom_check import (
    EASING_CHEST_FOLLOW_UP,
    EASING_FEVER_RETURN,
    EASY_RIDING_PLAN_LINE,
    FOLLOW_UP_ANSWERS,
    FOLLOW_UP_CLEARED,
    FOLLOW_UP_NOT_SEEN,
    FOLLOW_UP_STILL_THERE,
    SYMPTOM_FLOORS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
    SYMPTOMS_NONE,
    ChestFollowUp,
    IllnessReturn,
    chest_follow_up,
    chest_follow_up_easing,
    chest_follow_up_line,
    fever_return_easing,
    follow_up_symptom_answer,
    morning_easing,
    symptom_signal,
)
from src.services.todays_call import EASY_DAY, EASY_DAY_LINE, todays_call
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_RECOVERY,
    FLOOR_BIKE_REST,
    FLOOR_HARD_WORK_TO_EASY,
    FLOOR_NO_TRAINING,
    GradedVerdict,
    classify_planned_workout,
    grade,
)
from tests.test_batch_295_verdict_grading import LEVELS, RANK, VO2, Z2, _acute, _inputs
from tests.test_batch_300_light_week_marked import _sweet_spot, _z2
from tests.test_batch_302_stored_morning import _db_override, _savepoint_session
from tests.test_batch_303_medical_follow_through import (
    _graded,
    _ride_action,
    _seed_good_days,
    _swap,
)

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-06-batch-315-wording.md"
WEB_CARD = REPO / "apps" / "web" / "src" / "lib" / "chestFollowUp.ts"

#: He reports chest or heart symptoms on a Tuesday, as the draft's card names it.
TUESDAY = date(2026, 10, 13)
WEDNESDAY = TUESDAY + timedelta(days=1)


def _draft() -> str:
    text = DRAFT.read_text(encoding="utf-8")
    return " ".join(text.replace("\n> ", " ").replace("**", "").split())


def _follow_up(answer: str | None = None) -> ChestFollowUp:
    return ChestFollowUp(reported_on=TUESDAY, answer=answer)


def _acute_following(
    follow_up: ChestFollowUp | None, *, easing: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    """The grid's acute rail, carrying the follow-up as production's does."""
    symptoms = overrides.pop("symptoms", None)
    acute = _acute(symptoms=symptoms, **overrides)
    if easing is None and follow_up is not None and follow_up.open:
        easing = chest_follow_up_easing(follow_up)
    acute["symptoms"] = symptom_signal(symptoms, easing=easing, follow_up=follow_up)
    return acute


def _actions(verdict: GradedVerdict) -> list[str]:
    return [action.action for action in verdict.actions]


# -- when a follow-up starts, carries on and ends ------------------------------------------


def test_a_chest_or_heart_floor_starts_a_follow_up_the_next_morning() -> None:
    reported = symptom_signal(SYMPTOMS_CHEST_HEART)
    follow_up = chest_follow_up(TUESDAY, reported)
    assert follow_up == ChestFollowUp(reported_on=TUESDAY, answer=None)
    assert follow_up.open is True
    assert follow_up.to_packet() == {"reportedOn": "2026-10-13", "answer": None, "open": True}


@pytest.mark.parametrize(
    "previous",
    [
        None,
        symptom_signal(None),
        symptom_signal(SYMPTOMS_NONE),
        symptom_signal(SYMPTOMS_HEAD_COLD),
        symptom_signal(SYMPTOMS_FEVER_ACHES),
        # The floor did not stand: a stored record that names the answer untriggered.
        {**symptom_signal(SYMPTOMS_CHEST_HEART), "triggered": False},
    ],
)
def test_nothing_but_a_chest_or_heart_floor_starts_one(previous: dict[str, Any] | None) -> None:
    assert chest_follow_up(TUESDAY, previous) is None
    assert chest_follow_up(None, symptom_signal(SYMPTOMS_CHEST_HEART)) is None


def test_it_carries_on_until_he_says_he_has_been_checked() -> None:
    """Asked every morning until he answers "cleared" (the row's recommendation)."""
    wednesday = symptom_signal(None, follow_up=_follow_up())
    thursday = chest_follow_up(WEDNESDAY, wednesday)
    assert thursday == ChestFollowUp(reported_on=TUESDAY, answer=None)

    not_seen = symptom_signal(None, follow_up=_follow_up(FOLLOW_UP_NOT_SEEN))
    assert chest_follow_up(WEDNESDAY, not_seen) == ChestFollowUp(reported_on=TUESDAY)

    cleared = symptom_signal(None, follow_up=_follow_up(FOLLOW_UP_CLEARED))
    assert cleared["chestFollowUp"]["open"] is False
    assert chest_follow_up(WEDNESDAY, cleared) is None

    # His answer this morning: only "cleared" ends it.
    assert chest_follow_up(TUESDAY, symptom_signal(SYMPTOMS_CHEST_HEART), FOLLOW_UP_CLEARED) == (
        ChestFollowUp(reported_on=TUESDAY, answer=FOLLOW_UP_CLEARED)
    )
    for answer in (FOLLOW_UP_NOT_SEEN, FOLLOW_UP_STILL_THERE, None, "maybe"):
        follow_up = chest_follow_up(TUESDAY, symptom_signal(SYMPTOMS_CHEST_HEART), answer)
        assert follow_up is not None and follow_up.open is True
        assert follow_up.answer == (answer if answer in FOLLOW_UP_ANSWERS else None)


def test_a_stricter_floor_drops_the_easing_but_not_the_follow_up() -> None:
    """A fever on Thursday does not end Tuesday's chest follow-up: Friday asks again."""
    thursday = symptom_signal(
        SYMPTOMS_FEVER_ACHES,
        easing=chest_follow_up_easing(_follow_up()),
        follow_up=_follow_up(),
    )
    assert thursday["triggered"] is True and thursday["easing"] is None
    assert thursday["chestFollowUp"] == _follow_up().to_packet()
    assert chest_follow_up(TUESDAY + timedelta(2), thursday) == _follow_up()


def test_still_there_is_his_own_chest_or_heart_answer() -> None:
    assert follow_up_symptom_answer(FOLLOW_UP_STILL_THERE) == SYMPTOMS_CHEST_HEART
    for answer in (FOLLOW_UP_CLEARED, FOLLOW_UP_NOT_SEEN, None):
        assert follow_up_symptom_answer(answer) is None

    ladder = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=[],
        follow_up_symptom_answer=follow_up_symptom_answer(FOLLOW_UP_STILL_THERE),
        chest_follow_up=_follow_up(FOLLOW_UP_STILL_THERE),
    )
    symptoms = ladder["acutePhysiology"]["symptoms"]
    assert (symptoms["answer"], symptoms["source"], symptoms["triggered"]) == (
        SYMPTOMS_CHEST_HEART,
        "answer",
        True,
    )
    assert ladder["acutePhysiology"]["requiresTrainingRest"] is True
    assert ladder["acutePhysiology"]["escalations"][0]["message"] == (
        SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART].notice
    )
    # So the next morning starts a new follow-up from today, whatever it recorded.
    assert chest_follow_up(WEDNESDAY, symptoms) == ChestFollowUp(reported_on=WEDNESDAY)


# -- what it does to the morning -------------------------------------------------------------


def test_the_morning_after_a_chest_report_eases_vo2_and_keeps_zone_two() -> None:
    """315.3 on the engine. On `main` the good-numbers morning was Green, VO2 as planned."""
    good_morning = _inputs()
    assert grade(good_morning).label == "Green"
    assert set(_actions(grade(good_morning))) == {ACTION_AS_PLANNED}

    verdict = grade(replace(good_morning, acute=_acute_following(_follow_up())))
    assert (verdict.status, verdict.held) == ("Amber", False)
    assert verdict.floor == FLOOR_HARD_WORK_TO_EASY
    assert verdict.easing == EASING_CHEST_FOLLOW_UP
    assert _actions(verdict) == [ACTION_RECOVERY, ACTION_AS_PLANNED]
    assert chest_follow_up_line(TUESDAY) in verdict.reasons
    assert verdict.actions[0].detail == (
        "Chest or heart symptoms reported and not yet checked: an easy spin instead until "
        "he has spoken to his GP or 111."
    )


def test_with_no_hard_session_the_day_is_unchanged_and_home_only_asks() -> None:
    for sessions in ((Z2,), ()):
        quiet = grade(replace(_inputs(sessions=sessions), acute=_acute_following(_follow_up())))
        assert (quiet.label, quiet.floor, quiet.easing) == ("Green", None, None)
        assert ACTION_RECOVERY not in _actions(quiet)


def test_his_cleared_answer_relaxes_it_and_not_seen_does_not() -> None:
    cleared = grade(replace(_inputs(), acute=_acute_following(_follow_up(FOLLOW_UP_CLEARED))))
    assert (cleared.label, _actions(cleared)) == ("Green", [ACTION_AS_PLANNED, ACTION_AS_PLANNED])
    not_seen = grade(replace(_inputs(), acute=_acute_following(_follow_up(FOLLOW_UP_NOT_SEEN))))
    assert (not_seen.status, _actions(not_seen)) == ("Amber", [ACTION_RECOVERY, ACTION_AS_PLANNED])


def test_still_there_is_the_floor_again_that_day() -> None:
    verdict = grade(
        replace(
            _inputs(symptoms=SYMPTOMS_CHEST_HEART),
            acute=_acute_following(
                _follow_up(FOLLOW_UP_STILL_THERE), symptoms=SYMPTOMS_CHEST_HEART
            ),
        )
    )
    assert (verdict.status, verdict.floor, verdict.easing) == ("Red", FLOOR_NO_TRAINING, None)


def test_off_the_bike_outranks_the_follow_up() -> None:
    verdict = grade(
        replace(
            _inputs(overnight="illness"),
            acute=_acute_following(_follow_up(), overnight="illness"),
        )
    )
    assert (verdict.floor, verdict.easing) == (FLOOR_BIKE_REST, None)
    assert chest_follow_up_line(TUESDAY) not in verdict.reasons


def test_the_follow_up_only_ever_adds_caution_and_is_never_red_on_its_own() -> None:
    """Over the whole grid, with a hard session planned."""
    keys = list(LEVELS)
    follow_up = _follow_up()
    violations: list[str] = []
    for combo in itertools.product(*(range(len(LEVELS[key])) for key in keys)):
        inputs = _inputs(**{key: LEVELS[key][i] for key, i in zip(keys, combo, strict=True)})
        without = grade(inputs)
        acute = dict(inputs.acute)
        answer = acute["symptoms"]["answer"]
        acute["symptoms"] = symptom_signal(
            answer, easing=chest_follow_up_easing(follow_up), follow_up=follow_up
        )
        asked = grade(replace(inputs, acute=acute))
        if RANK[asked.label] < RANK[without.label]:
            violations.append(f"{combo}: better, {without.label} -> {asked.label}")
        if asked.status == "Red" and without.status != "Red":
            violations.append(f"{combo}: Red from the follow-up alone")
        if without.floor is not None and asked.floor != without.floor:
            violations.append(f"{combo}: floor {without.floor} became {asked.floor}")
        for before, after in zip(without.actions, asked.actions, strict=True):
            if before.is_hard and after.action == ACTION_AS_PLANNED:
                violations.append(f"{combo}: a hard session ridden as planned")
    assert violations == []


def _packet(
    workouts: list[Any],
    easing: dict[str, Any] | None,
    follow_up: ChestFollowUp | None,
) -> tuple[dict[str, Any], GradedVerdict]:
    """A good-numbers morning's packet, as production builds it."""
    ladder = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=workouts,
        symptom_easing=easing,
        chest_follow_up=follow_up,
    )
    verdict = grade(
        replace(
            _inputs(),
            acute=ladder["acutePhysiology"],
            sessions=tuple(classify_planned_workout(workout) for workout in workouts),
        )
    )
    return graded_verdict_packet(ladder, verdict, workouts, breathwork_line=None), verdict


def test_the_reason_and_the_plan_line_lead_and_there_is_no_notice() -> None:
    follow_up = _follow_up()
    packet, verdict = _packet([_sweet_spot()], chest_follow_up_easing(follow_up), follow_up)
    assert verdict.easing == EASING_CHEST_FOLLOW_UP
    assert packet["reasons"][0] == (
        "Easing off after the chest or heart symptoms you reported on Tuesday: easy riding "
        "only until you've spoken to your GP or 111."
    )
    assert packet["planAdjustments"][0] == EASY_RIDING_PLAN_LINE
    assert "chest_follow_up_easy_riding" in packet["safetyRulesApplied"]
    # Home's card says it; the notice card is for what he has told the app today.
    symptoms_notices = [
        item for item in packet["acutePhysiology"]["escalations"] if item["kind"] == "symptoms"
    ]
    assert symptoms_notices == []
    assert packet["acutePhysiology"]["symptoms"]["chestFollowUp"] == follow_up.to_packet()

    # Today's call is state 10, "Easy day", whose line points at the card.
    call = todays_call({"verdict": packet, "plannedWorkouts": [{"id": "x"}]})
    assert (call.headline, call.line) == (EASY_DAY, EASY_DAY_LINE)


def test_a_fever_return_and_a_chest_follow_up_together_read_once() -> None:
    """The morning reads one easing: the fever's, which holds whatever is planned and
    carries its notice. The follow-up is still recorded, so Home still asks."""
    follow_up = _follow_up()
    illness = IllnessReturn(reported_on=TUESDAY - timedelta(1), day=2)
    fever = fever_return_easing(illness)
    # The morning reads the fever's easing, whatever else is open.
    for chest_question in (False, True):
        assert (
            morning_easing(
                illness=illness,
                follow_up=follow_up,
                chest_question=chest_question,
                chest_question_words="tight chest",
            )
            == fever
        )
    # Then the follow-up, before a chest question in today's note.
    assert morning_easing(
        illness=None, follow_up=follow_up, chest_question=True, chest_question_words="tight"
    ) == chest_follow_up_easing(follow_up)
    cleared = _follow_up(FOLLOW_UP_CLEARED)
    assert morning_easing(illness=None, follow_up=cleared, chest_question=False) is None
    packet, verdict = _packet([_sweet_spot(), _z2()], fever, follow_up)
    assert verdict.easing == EASING_FEVER_RETURN
    assert packet["reasons"].count(fever["reason"]) == 1
    assert chest_follow_up_line(TUESDAY) not in packet["reasons"]
    assert packet["planAdjustments"].count(EASY_RIDING_PLAN_LINE) == 1
    assert GRADED_ZONE_TWO_LINE in packet["planAdjustments"]
    notices = [n for n in packet["acutePhysiology"]["escalations"] if n["kind"] == "symptoms"]
    assert [n["message"] for n in notices] == [fever["notice"]]
    card = _chest_follow_up(packet)
    assert card is not None and (card.reportedOn, card.eases) == ("2026-10-13", False)


def test_the_ladder_is_given_nothing() -> None:
    """The rollback path is unchanged: `VERDICT_ENGINE=ladder` applies no follow-up."""
    rail = _acute_physiology_rail(
        daily_metric=None, sleep=None, baselines={}, recent_daily_metrics=[], recent_sleeps=[]
    )
    assert rail["symptoms"]["chestFollowUp"] is None
    assert rail["symptoms"]["easing"] is None
    assert SYMPTOM_FOLLOW_THROUGH_RULE not in LADDER_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_a_week_swap_is_withheld_while_the_follow_up_is_open() -> None:
    """The question comes before a rearranged week, as for 303's chest question."""
    zone_two = _z2()
    session = Mock()
    session.get = AsyncMock(return_value=zone_two)
    service = MorningAnalysisService(session)
    easing = chest_follow_up_easing(_follow_up())
    asking = grade(replace(_inputs(), acute=_acute_following(_follow_up()), sessions=(VO2,)))
    later = WEDNESDAY + timedelta(days=4)
    assert await service._swap_blocked_by_easing(
        _swap(later, zone_two), graded=asking, easing=easing
    )


def test_the_brief_is_told_the_follow_up_and_the_version_moved() -> None:
    assert GRADED_PROMPT_VERSION == "morning-analysis-v58-2026-10-06"
    assert SYMPTOM_FOLLOW_THROUGH_RULE in GRADED_SYSTEM_PROMPT
    rule = " ".join(SYMPTOM_FOLLOW_THROUGH_RULE.split())
    assert "Kind chest_follow_up means he reported chest or heart symptoms" in rule
    assert "never decide for him whether he needs a doctor" in rule
    assert "symptoms.chestFollowUp is the follow-up the morning is in" in rule
    assert "Add no medical advice of your own." in rule


def test_his_answer_is_a_new_input_and_none_leaves_every_identity_as_it_was() -> None:
    assert with_chest_follow_up("abc", None, None) == "abc"
    assert with_chest_follow_up(None, None, None) is None
    at = datetime(2026, 10, 14, 7, 30)
    answers = {with_chest_follow_up("abc", answer, at) for answer in FOLLOW_UP_ANSWERS}
    assert len(answers) == 3 and "abc" not in answers
    later = with_chest_follow_up("abc", FOLLOW_UP_NOT_SEEN, at + timedelta(minutes=5))
    assert later != with_chest_follow_up("abc", FOLLOW_UP_NOT_SEEN, at)


# -- Home: the card --------------------------------------------------------------------------


def _stored(packet: dict[str, Any]) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=WEDNESDAY,
        generated_at_utc=datetime(2026, 10, 14, 7, 0),
        verdict=str(packet.get("status")),
        prompt_version=GRADED_PROMPT_VERSION,
        model_name=None,
        output_markdown="",
        raw_response={},
        context_packet={"verdict": packet},
    )


def test_home_is_told_the_follow_up_while_it_is_open() -> None:
    follow_up = _follow_up()
    packet, _ = _packet([_sweet_spot()], chest_follow_up_easing(follow_up), follow_up)
    served = _serialize_analysis(_stored(packet))
    assert served is not None and served.chestFollowUp is not None
    card = served.chestFollowUp
    assert (card.reportedOn, card.reportedWeekday, card.answer, card.eases) == (
        "2026-10-13",
        "Tuesday",
        None,
        True,
    )

    # No hard session planned: Home asks, and nothing was eased.
    quiet, _ = _packet([_z2()], chest_follow_up_easing(follow_up), follow_up)
    quiet_card = _chest_follow_up(quiet)
    assert quiet_card is not None and quiet_card.eases is False

    # "Not seen yet": the card stays and says so.
    not_seen = _follow_up(FOLLOW_UP_NOT_SEEN)
    kept, _ = _packet([_sweet_spot()], chest_follow_up_easing(not_seen), not_seen)
    kept_card = _chest_follow_up(kept)
    assert kept_card is not None and kept_card.answer == FOLLOW_UP_NOT_SEEN

    # Cleared: the card is gone.
    cleared, _ = _packet([_sweet_spot()], None, _follow_up(FOLLOW_UP_CLEARED))
    assert _chest_follow_up(cleared) is None
    # A morning with the chest-or-heart warning itself: its notice says it, not the card.
    still = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=[],
        follow_up_symptom_answer=SYMPTOMS_CHEST_HEART,
        chest_follow_up=_follow_up(FOLLOW_UP_STILL_THERE),
    )
    assert _chest_follow_up(still) is None
    # A morning stored before the batch carries no record.
    assert _chest_follow_up({"acutePhysiology": {"symptoms": {"answer": None}}}) is None
    assert _chest_follow_up(None) is None


# -- the words are the ones signed off ---------------------------------------------------------


def test_every_new_line_is_in_the_signed_off_draft() -> None:
    draft = _draft()
    assert "signed off on Mark's behalf under Craig's delegation of 6 Oct 2026" in draft
    assert chest_follow_up_line(TUESDAY) in draft
    assert (
        "Chest or heart symptoms reported and not yet checked: an easy spin instead until "
        "he has spoken to his GP or 111." in draft
    )
    web = WEB_CARD.read_text(encoding="utf-8")
    for words in (
        "Chest or heart symptoms on ",
        "Have they gone, and have you spoken to your GP or 111? Until you have, hard "
        "sessions are easy rides.",
        "Thanks. Hard sessions stay easy rides until you've spoken to your GP or 111. "
        "I'll ask again tomorrow.",
        "Gone, and I've spoken to my GP or 111",
        "Gone, but I haven't spoken to anyone yet",
        "Still there",
    ):
        assert words in draft, words
        assert words in web, words


def test_coach_memory_knows_he_takes_nothing_that_changes_his_heart_rate() -> None:
    """315.6: his medication (Craig, 6 Oct). A fresh profile is seeded with it; his live
    row gains it by read-modify-write at close-out, because seeding fills only what is
    missing."""
    profile = KB_SECTION_BUILDERS["profile"]()
    assert profile["medication"] == PROFILE_MEDICATION
    assert PROFILE_MEDICATION["current"] == "none beyond vitamin D and fish oil"
    draft = _draft()
    assert PROFILE_MEDICATION["current"] in draft
    assert PROFILE_MEDICATION["note"] in draft


# -- on Postgres ------------------------------------------------------------------------------

#: A Tuesday well before any plausible "today": a fresh profile's first morning seeds a
#: default plan from the real current week, which a test dated this month collides with.
SEEDED_TUESDAY = date(2026, 8, 11)


def _follow_up_record(verdict: dict[str, Any]) -> dict[str, Any] | None:
    record: dict[str, Any] | None = verdict["acutePhysiology"]["symptoms"]["chestFollowUp"]
    return record


@pytest.mark.asyncio
async def test_on_postgres_a_chest_report_eases_hard_work_until_he_says_he_has_been_checked(
    db_conn: AsyncConnection,
) -> None:
    """315 end to end. On `main` the morning after the report was Green, VO2 as planned."""
    reported = SEEDED_TUESDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported, 4)
        days = sorted(entries)
        entries[reported].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        floor = await _graded(session, player, reported)
        assert floor["status"] == "Red"
        assert floor["acutePhysiology"]["requiresTrainingRest"] is True

        # Wednesday: he taps None and his numbers are good. Asked, and VO2 is a spin.
        asked = await _graded(session, player, days[1])
        assert (asked["status"], asked["held"]) == ("Amber", False)
        assert _ride_action(asked) == ACTION_RECOVERY
        assert asked["graded"]["easing"] == EASING_CHEST_FOLLOW_UP
        assert asked["reasons"][0] == chest_follow_up_line(reported)
        assert _follow_up_record(asked) == {
            "reportedOn": reported.isoformat(),
            "answer": None,
            "open": True,
        }
        assert "swapSuggestion" not in asked
        stored = await MorningAnalysisService(session).latest_analysis(player.id, days[1])
        served = _serialize_analysis(stored)
        assert served is not None and served.chestFollowUp is not None
        assert (served.chestFollowUp.reportedWeekday, served.chestFollowUp.eases) == (
            "Tuesday",
            True,
        )

        # "Gone, but I haven't spoken to anyone yet": still eased, asked again tomorrow.
        await DailyLoopService(session).answer_chest_follow_up(
            player, subject_date=days[1], answer=FOLLOW_UP_NOT_SEEN
        )
        kept = await _graded(session, player, days[1])
        assert _ride_action(kept) == ACTION_RECOVERY
        assert _follow_up_record(kept) == {
            "reportedOn": reported.isoformat(),
            "answer": FOLLOW_UP_NOT_SEEN,
            "open": True,
        }
        thursday = await _graded(session, player, days[2])
        assert _ride_action(thursday) == ACTION_RECOVERY
        assert _follow_up_record(thursday) == {
            "reportedOn": reported.isoformat(),
            "answer": None,
            "open": True,
        }

        # "Gone, and I've spoken to my GP or 111": hard sessions are back from today.
        await DailyLoopService(session).answer_chest_follow_up(
            player, subject_date=days[2], answer=FOLLOW_UP_CLEARED
        )
        cleared = await _graded(session, player, days[2])
        assert (cleared["status"], _ride_action(cleared)) == ("Green", ACTION_AS_PLANNED)
        record = _follow_up_record(cleared)
        assert record is not None and record["open"] is False
        friday = await _graded(session, player, days[3])
        assert (friday["status"], _ride_action(friday)) == ("Green", ACTION_AS_PLANNED)
        assert _follow_up_record(friday) is None


@pytest.mark.asyncio
async def test_on_postgres_still_there_sets_the_floor_and_starts_again_from_that_day(
    db_conn: AsyncConnection,
) -> None:
    reported = SEEDED_TUESDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported, 3)
        days = sorted(entries)
        entries[reported].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        await _graded(session, player, reported)
        await _graded(session, player, days[1])

        await DailyLoopService(session).answer_chest_follow_up(
            player, subject_date=days[1], answer=FOLLOW_UP_STILL_THERE
        )
        still = await _graded(session, player, days[1])
        assert still["status"] == "Red"
        assert still["acutePhysiology"]["requiresTrainingRest"] is True
        assert still["acutePhysiology"]["symptoms"]["answer"] == SYMPTOMS_CHEST_HEART
        assert still["acutePhysiology"]["symptoms"]["source"] == "answer"
        stored = await MorningAnalysisService(session).latest_analysis(player.id, days[1])
        served = _serialize_analysis(stored)
        assert served is not None and served.chestFollowUp is None  # the warning says it

        thursday = await _graded(session, player, days[2])
        assert _ride_action(thursday) == ACTION_RECOVERY
        assert _follow_up_record(thursday) == {
            "reportedOn": days[1].isoformat(),
            "answer": None,
            "open": True,
        }


@pytest.mark.asyncio
async def test_on_postgres_a_fever_return_and_a_chest_follow_up_read_once(
    db_conn: AsyncConnection,
) -> None:
    """A fever on Monday, chest symptoms on Tuesday: Wednesday reads the fever's second
    easy day, once, and still records Tuesday's follow-up so Home asks."""
    fever_day = SEEDED_TUESDAY - timedelta(days=1)
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, fever_day, 3)
        days = sorted(entries)
        entries[days[0]].symptoms = SYMPTOMS_FEVER_ACHES
        entries[days[1]].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        await _graded(session, player, days[0])
        await _graded(session, player, days[1])

        wednesday = await _graded(session, player, days[2])
        assert wednesday["graded"]["easing"] == EASING_FEVER_RETURN
        assert _ride_action(wednesday) == ACTION_RECOVERY
        fever_reasons = [r for r in wednesday["reasons"] if r.startswith("Easing back after")]
        assert len(fever_reasons) == 1
        assert not any(r.startswith("Easing off after the chest") for r in wednesday["reasons"])
        assert _follow_up_record(wednesday) == {
            "reportedOn": days[1].isoformat(),
            "answer": None,
            "open": True,
        }


@pytest.mark.asyncio
async def test_on_postgres_a_day_without_a_stored_morning_does_not_end_the_follow_up(
    db_conn: AsyncConnection,
) -> None:
    reported = SEEDED_TUESDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported, 3)
        days = sorted(entries)
        entries[reported].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        await _graded(session, player, reported)
        # Wednesday is never graded.
        thursday = await _graded(session, player, days[2])
        assert _ride_action(thursday) == ACTION_RECOVERY
        assert _follow_up_record(thursday) == {
            "reportedOn": reported.isoformat(),
            "answer": None,
            "open": True,
        }


@pytest.mark.asyncio
async def test_on_postgres_a_chest_report_he_corrected_the_same_day_starts_no_follow_up(
    db_conn: AsyncConnection,
) -> None:
    """The latest stored morning of a day decides, so a mis-tap he put right leaves nothing."""
    reported = SEEDED_TUESDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported, 2)
        entries[reported].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        assert (await _graded(session, player, reported))["status"] == "Red"
        entries[reported].symptoms = SYMPTOMS_NONE
        await session.commit()
        assert (await _graded(session, player, reported))["status"] == "Green"

        wednesday = await _graded(session, player, reported + timedelta(days=1))
        assert (wednesday["status"], _ride_action(wednesday)) == ("Green", ACTION_AS_PLANNED)
        assert _follow_up_record(wednesday) is None


@pytest.mark.asyncio
async def test_on_postgres_the_follow_up_route_records_the_answer_and_regrades_today_only(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    reported = SEEDED_TUESDAY
    queued = AsyncMock()
    monkeypatch.setattr(daily_loop_router, "_generate_brief_after_checkin", queued)

    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported, 2)
        days = sorted(entries)
        monkeypatch.setattr(daily_loop_router, "local_today", lambda _timezone: days[1])
        entries[reported].symptoms = SYMPTOMS_CHEST_HEART
        await session.commit()
        await _graded(session, player, reported)
        await _graded(session, player, days[1])

        app.dependency_overrides[get_current_user] = lambda: player
        app.dependency_overrides[get_db] = _db_override(session)
        base = "/api/v1/daily-loop"
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await client.post(
                    f"{base}/{days[1].isoformat()}/symptom-follow-up",
                    json={"answer": "not_seen"},
                )
                second = await client.post(
                    f"{base}/{days[1].isoformat()}/symptom-follow-up",
                    json={"answer": "cleared"},
                )
                not_an_answer = await client.post(
                    f"{base}/{days[1].isoformat()}/symptom-follow-up",
                    json={"answer": "fine"},
                )
                no_follow_up = await client.post(
                    f"{base}/{reported.isoformat()}/symptom-follow-up",
                    json={"answer": "cleared"},
                )
        finally:
            app.dependency_overrides.clear()

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert not_an_answer.status_code == 422
        assert no_follow_up.status_code == 404
        assert queued.await_count == 2
        queued.assert_awaited_with(player.id, days[1])

        rows = (
            (
                await session.execute(
                    select(SymptomFollowUp)
                    .where(SymptomFollowUp.user_id == player.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        # One answer per morning; the second replaced the first.
        assert [(row.subject_date, row.reported_on, row.answer) for row in rows] == [
            (days[1], reported, FOLLOW_UP_CLEARED)
        ]
        assert rows[0].answered_at_utc is not None
        # It was an answer, not a check-in: the check-in is as he left it.
        await session.refresh(entries[days[1]])
        assert entries[days[1]].symptoms == SYMPTOMS_NONE
