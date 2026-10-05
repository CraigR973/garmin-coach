"""Batch 282 — one metric, one statement, however many surfaces show it.

On 26 Aug 2026 the brief called REM a chronic pattern while the Trends read, the same
day on the same data, called it "not a deficit". Batch 230 pinned both prompts to one
framing rule; this pins both packets to one *conclusion*, built by one function.
The REM test Batch 230 added (``test_the_morning_and_trends_prompts_cannot_disagree_
about_rem``) is untouched and still passes.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase, MetricBaseline, Sleep
from src.models.profile import Profile, UserRole
from src.services import metric_statements
from src.services.age_norms import rem_sleep_pct_for_row, sleep_stage_band
from src.services.metric_statements import (
    COVERED_METRIC_STATEMENTS,
    DEFERRED_CLAIM_KEYS,
    METRIC_STATEMENT_RULE,
    missing_statements,
    sleep_stage_statement,
)
from src.services.morning_analysis import PROMPT_VERSION as MORNING_PROMPT_VERSION
from src.services.morning_analysis import SYSTEM_PROMPT as MORNING_SYSTEM_PROMPT
from src.services.morning_analysis import _metric_statements as morning_statements
from src.services.trends import (
    BUCKET_MONTH,
    PROMPT_VERSION_BY_BUCKET,
    TREND_SYSTEM_PROMPT,
    MetricSummary,
    TrendsService,
    TrendWindow,
    _window_metric_statements,
)


def _rem_baseline(user_id: uuid.UUID | None = None) -> MetricBaseline:
    # Production's own REM baseline on 26 Sep 2026.
    return MetricBaseline(
        user_id=user_id or uuid.uuid4(),
        metric_key="rem_sleep_pct",
        metric_label="REM sleep",
        source="db_history",
        window_start_date=date(2026, 7, 5),
        window_end_date=date(2026, 9, 26),
        sample_count=84,
        excluded_sample_count=0,
        median_value=10.1063829787234,
        lower_quartile_value=8.16350872410033,
        upper_quartile_value=13.3807317133504,
    )


def _night() -> Sleep:
    # 26 Sep 2026: 118 deep, 285 light, 47 REM, 25 awake — REM 9.9% of 475 minutes.
    return Sleep(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 9, 26),
        deep_sleep_sec=118 * 60,
        light_sleep_sec=285 * 60,
        rem_sleep_sec=47 * 60,
        awake_sleep_sec=25 * 60,
        raw_payload={},
    )


def _month(rem_mean: float | None) -> TrendWindow:
    return TrendWindow(
        bucket=BUCKET_MONTH,
        key="2026-09",
        label="September 2026",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        sample_days=26,
        metrics={
            "rem_sleep_pct": MetricSummary(
                metric_key="rem_sleep_pct",
                sample_count=26,
                excluded_count=0,
                mean=rem_mean,
                median=rem_mean,
                min=rem_mean,
                max=rem_mean,
            )
        },
    )


def test_the_26_aug_shape_gets_both_halves_in_one_sentence() -> None:
    statement = sleep_stage_statement(
        "rem_sleep_pct", value=9.894, age=57, sex=None, baseline=_rem_baseline()
    )
    assert statement is not None
    assert statement["bandPosition"] == "below"
    assert statement["personalPosition"] == "within"
    assert statement["statement"] == (
        "REM 9.9% is below the healthy range for your age (50–59 band: 15–23%), "
        "but within your own usual range (8.2–13.4%)."
    )


def test_two_surfaces_state_the_same_figure_identically() -> None:
    """The brief and Trends build their statements through the one function, so the
    same figure, band and history cannot come out as two conclusions."""
    night = _night()
    value = rem_sleep_pct_for_row(night)
    assert value is not None
    brief = morning_statements(night, {"profile": {"age": 57}}, [_rem_baseline()])
    trends = _window_metric_statements(
        [_month(value)], "2026-09", age=57, sex=None, baselines=[_rem_baseline()]
    )
    assert brief == trends
    assert missing_statements(brief) == set()
    assert missing_statements(trends) == set()


def test_a_metric_added_to_the_covered_set_without_a_statement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract the two surfaces are held to: every covered metric is stated.

    A metric added to the set that no surface feeds shows up as missing from both.
    """
    monkeypatch.setitem(metric_statements.COVERED_METRIC_STATEMENTS, "deep_sleep_pct", "Deep")
    brief = morning_statements(_night(), {"profile": {"age": 57}}, [_rem_baseline()])
    trends = _window_metric_statements(
        [_month(9.9)], "2026-09", age=57, sex=None, baselines=[_rem_baseline()]
    )
    assert missing_statements(brief) == {"deep_sleep_pct"}
    assert missing_statements(trends) == {"deep_sleep_pct"}


def test_every_covered_metric_has_a_band_to_be_stated_against() -> None:
    for metric_key in COVERED_METRIC_STATEMENTS:
        assert sleep_stage_band(metric_key, 57, "male") is not None


def test_both_prompts_carry_the_one_rule_and_moved_their_versions() -> None:
    assert METRIC_STATEMENT_RULE in MORNING_SYSTEM_PROMPT
    assert METRIC_STATEMENT_RULE in TREND_SYSTEM_PROMPT
    # The wording each model is given changed, so no stored read written without it
    # is served as current: the brief self-heals, Trends is regenerated at close-out.
    # (Batch 269 moved the brief on again, to v48; Batch 272 to v49 and Trends to v12;
    # Batch 294 to v50; Batch 296 to v51.)
    assert MORNING_PROMPT_VERSION == "morning-analysis-v57-2026-10-05"
    assert PROMPT_VERSION_BY_BUCKET[BUCKET_MONTH] == "trends-month-v12-2026-09-27"
    assert PROMPT_VERSION_BY_BUCKET["season"] == "trends-season-v12-2026-09-27"


def test_each_deferred_claim_key_says_why() -> None:
    assert set(DEFERRED_CLAIM_KEYS) == {
        "trend / trendReason",
        "delta / pctChange",
        "status",
        "deep, light and awake stage bands",
    }
    for reason in DEFERRED_CLAIM_KEYS.values():
        assert len(reason) > 40


def test_no_figure_means_no_statement() -> None:
    assert (
        sleep_stage_statement("rem_sleep_pct", value=None, age=57, sex=None, baseline=None) is None
    )
    assert (
        _window_metric_statements([_month(None)], "2026-09", age=57, sex=None, baselines=[]) == []
    )


@pytest.mark.asyncio
async def test_the_trends_packet_carries_the_statement(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Statement Test",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()
        session.add(
            KnowledgeBase(
                user_id=user_id, section="profile", version=1, is_active=True, content={"age": 57}
            )
        )
        session.add(_rem_baseline(user_id))
        for day in range(1, 8):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=date(2026, 9, day),
                    score=78,
                    duration_sec=475 * 60,
                    deep_sleep_sec=118 * 60,
                    light_sleep_sec=285 * 60,
                    rem_sleep_sec=47 * 60,
                    awake_sleep_sec=25 * 60,
                    raw_payload={},
                )
            )
        await session.commit()

        user = await session.get(Profile, user_id)
        assert user is not None
        preview = await TrendsService(session).narrative_preview(
            user, bucket=BUCKET_MONTH, as_of=date(2026, 9, 27)
        )

    [statement] = preview.packet["metricStatements"]
    assert statement["metricKey"] == "rem_sleep_pct"
    assert statement["bandPosition"] == "below"
    assert statement["personalPosition"] == "within"
