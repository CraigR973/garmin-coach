"""Batch 320: tonight's advice from today's reason, and whether it helped.

320.2 one thing for tonight from the domain that made the morning cautious, with how
strong its evidence is; 320.3 a one-tap "did it" at the next check-in, and the weekly
review's next-morning change labelled weak evidence; HS332-02 the REM experiment calls no
direction when its two arms sit in different weeks of the year. Each failed on the base
branch first.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.models.coaching import Analysis, ManualEntry
from src.services import morning_analysis, reviews
from src.services.daily_loop_envelope import _tonight_advice_check_in
from src.services.experiment_evaluation import (
    RECOMMEND_INCONCLUSIVE,
    RECOMMEND_SUPPORTED,
    RemInterventionNight,
    evaluate_rem_interventions,
)
from src.services.morning_output_contract import TODAYS_CALL_INSTRUCTION
from src.services.reviews import ReviewService
from src.services.tonight_advice import (
    ADVICE_HRV,
    ADVICE_LOAD,
    ADVICE_SLEEP,
    ADVICE_WORDS,
    FOLLOW_LABELS,
    FOLLOW_QUESTION,
    FOLLOWED,
    NOT_FOLLOWED,
    AdviceNight,
    review_summary,
    tonight_advice,
)
from tests.test_batch_302_stored_morning import _savepoint_session
from tests.test_batch_303_medical_follow_through import SEEDED_THURSDAY, _seed_good_days

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-320-wording.md"
WEB = REPO / "apps" / "web" / "src" / "lib" / "tonightAdvice.ts"


def _verdict(**ratings: str) -> dict[str, Any]:
    return {
        "graded": {
            "domains": [
                {"domain": domain, "rating": ratings.get(domain, "none")}
                for domain in ("autonomic", "sleep", "load", "subjective")
            ]
        }
    }


# -- 320.2: the advice follows the reason ------------------------------------------------------


def test_the_most_off_domain_chooses_tonights_advice() -> None:
    assert tonight_advice(_verdict(sleep="marked", autonomic="mild")).key == ADVICE_SLEEP
    assert tonight_advice(_verdict(sleep="mild", autonomic="mild")).key == ADVICE_HRV
    assert tonight_advice(_verdict(load="mild")).key == ADVICE_LOAD
    advice = tonight_advice(_verdict(autonomic="marked"))
    assert advice is not None
    assert advice.line.startswith("Tonight:")
    assert "hasn't measured" in advice.evidence  # the strength of the evidence, plainly
    assert advice.to_packet()["evidenceStrength"] == "general"


def test_a_morning_with_nothing_off_has_no_advice() -> None:
    assert tonight_advice(_verdict()) is None
    assert tonight_advice({}) is None  # a morning the ladder graded


def test_the_brief_uses_it_and_the_version_moved() -> None:
    assert "tonightAdvice.line" in TODAYS_CALL_INSTRUCTION
    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v65-2026-10-29"


# -- 320.3: did it help? ------------------------------------------------------------------


def _night(day: int, answer: str | None, sleep: float, hrv: float) -> AdviceNight:
    return AdviceNight(
        given_on=date(2026, 10, day),
        key=ADVICE_SLEEP,
        answer=answer,
        sleep_score_change=sleep,
        hrv_change_ms=hrv,
    )


def test_the_review_compares_only_with_two_nights_each_way_and_always_says_weak() -> None:
    few = review_summary([_night(19, FOLLOWED, 4, 2), _night(20, NOT_FOLLOWED, -2, -1)])
    assert (few["comparable"], few["followed"], few["evidence"]) == (False, None, "weak")
    enough = review_summary(
        [
            _night(19, FOLLOWED, 4, 2),
            _night(20, FOLLOWED, 6, 0),
            _night(21, NOT_FOLLOWED, -2, -1),
            _night(22, NOT_FOLLOWED, 0, -3),
            _night(23, None, 9, 9),  # unanswered: never counted either way
        ]
    )
    assert enough["comparable"] is True
    assert enough["followed"] == {"sleepScoreChange": 5.0, "hrvChangeMs": 1.0}
    assert enough["notFollowed"] == {"sleepScoreChange": -1.0, "hrvChangeMs": -2.0}
    assert (enough["nightsAdvised"], enough["nightsAnswered"]) == (5, 4)
    assert "never as proof" in enough["meaning"]


def test_the_review_is_told_it_is_weak_evidence_and_the_version_moved() -> None:
    assert "weak evidence" in reviews.TONIGHT_ADVICE_REVIEW_RULE
    assert reviews.TONIGHT_ADVICE_REVIEW_RULE in reviews.SYSTEM_PROMPT
    assert reviews.PROMPT_VERSION == "reviews-v14-2026-10-29"


# -- HS332-02: the season is not the lever ----------------------------------------------------


def _rem(day: date, response: str, rem: float) -> RemInterventionNight:
    return RemInterventionNight(
        day=day, intervention_id="cool_room", response=response, rem_sleep_pct=rem, awake_min=20
    )


def test_arms_in_different_months_call_no_direction() -> None:
    september = [_rem(date(2026, 9, 1) + timedelta(days=i), "not_applied", 10) for i in range(7)]
    october = [_rem(date(2026, 10, 10) + timedelta(days=i), "applied", 16) for i in range(7)]
    apart = evaluate_rem_interventions([*september, *october])
    assert apart.recommendation == RECOMMEND_INCONCLUSIVE
    assert apart.evidence["calendarApart"] is True
    assert "different weeks of the year" in apart.reasons[1]
    # The same difference, interleaved through the same weeks, still reads supported.
    mixed = [
        _rem(
            date(2026, 10, 1) + timedelta(days=i),
            "applied" if i % 2 else "not_applied",
            16 + (i % 3) * 0.1 if i % 2 else 10 + (i % 3) * 0.1,
        )
        for i in range(14)
    ]
    together = evaluate_rem_interventions(mixed)
    assert together.evidence["calendarApart"] is False
    assert together.recommendation == RECOMMEND_SUPPORTED


# -- the words ---------------------------------------------------------------------------------


def test_every_new_line_is_in_the_draft_and_the_card() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    for words in ADVICE_WORDS.values():
        for text in words.values():
            assert text in draft, text
    assert FOLLOW_QUESTION in draft
    web = WEB.read_text(encoding="utf-8")
    assert FOLLOW_QUESTION in web
    for label in FOLLOW_LABELS.values():
        assert label in draft and label in web


# -- on Postgres -------------------------------------------------------------------------------


async def _store_morning(session: Any, user_id: uuid.UUID, day: date, key: str | None) -> None:
    session.add(
        Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=day,
            generated_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
            prompt_version="test",
            verdict="Amber",
            context_packet={
                "tonightAdvice": None if key is None else {**ADVICE_WORDS[key], "key": key}
            },
            output_markdown="",
            raw_response={},
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_on_postgres_last_nights_advice_is_asked_and_the_week_reports_it(
    db_conn: AsyncConnection,
) -> None:
    first = SEEDED_THURSDAY
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, first, 3)
        await _store_morning(session, player.id, first, ADVICE_SLEEP)
        await _store_morning(session, player.id, first + timedelta(days=1), None)

        next_day = first + timedelta(days=1)
        asked = await _tonight_advice_check_in(session, player.id, next_day, entries[next_day])
        assert asked is not None
        assert (asked.givenOn, asked.key, asked.answer) == (first.isoformat(), ADVICE_SLEEP, None)
        # No advice the morning before: nothing to ask.
        later = first + timedelta(days=2)
        assert await _tonight_advice_check_in(session, player.id, later, entries[later]) is None

        entry: ManualEntry = entries[next_day]
        entry.tonight_advice_feedback_json = {
            "givenOn": first.isoformat(),
            "key": ADVICE_SLEEP,
            "answer": FOLLOWED,
        }
        await session.commit()
        answered = await _tonight_advice_check_in(session, player.id, next_day, entry)
        assert answered is not None and answered.answer == FOLLOWED

        nights = await ReviewService(session)._tonight_advice_nights(
            player.id, first, first + timedelta(days=6)
        )
        assert [(night.given_on, night.key, night.answer) for night in nights] == [
            (first, ADVICE_SLEEP, FOLLOWED)
        ]
        # The seeded days score 82 every night; HRV runs 46, 47, 48.
        assert nights[0].sleep_score_change == 0
        assert nights[0].hrv_change_ms is not None
