"""Batch 352: the morning brief gives every figure in plain words.

The weekly review stopped showing Mark quartiles, "n=" counts and field names in Batch
347 (Decision #432), but the graded brief never had such a rule. Of the 20 briefs written
at v58 (7–26 Oct 2026), 9 gave him quartiles, 5 standard deviations and all 20 a median.
This batch gives the brief the review's plain words (Decision #440).

The briefs quoted below are made up for the tests. Mark's own words and numbers never
enter this public repository.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import MetricBaseline
from src.services import morning_analysis as morning_analysis_module
from src.services.age_norms import REM_FRAMING_RULE
from src.services.coach_policy import (
    LADDER_MORNING_FLOORS,
    READ_PROMPT_FLOORS,
    missing_floors,
)
from src.services.metric_statements import METRIC_STATEMENT_RULE
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_PROMPT_VERSION,
    LADDER_SYSTEM_PROMPT,
    MORNING_PLAIN_WORDS_RULE,
    MorningAnalysisService,
    _baseline_comparison,
    brief_wording_leaks,
)
from tests.test_batch_296_graded_colour import _seed_one_poor_night
from tests.test_batch_302_stored_morning import (
    DAY,
    _RecordingClient,
    _stored,
    _writing_service,
)
from tests.test_batch_347_recorded_disruptions import _player
from tests.test_morning_pipeline import _profile


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_graded_brief_carries_the_rule_once_and_the_ladder_is_untouched() -> None:
    assert GRADED_SYSTEM_PROMPT.count(MORNING_PLAIN_WORDS_RULE) == 1
    assert MORNING_PLAIN_WORDS_RULE not in LADDER_SYSTEM_PROMPT
    assert GRADED_PROMPT_VERSION == "morning-analysis-v60-2026-10-26"
    assert LADDER_PROMPT_VERSION == "morning-analysis-v50-2026-09-28"


def test_the_rule_names_the_fields_the_baselines_carry() -> None:
    """The metrics table and the whole-day cost share one comparison (Batch 226)."""

    baseline = MetricBaseline(
        user_id=uuid.uuid4(),
        metric_key="sleep_score",
        metric_label="Sleep score",
        window_start_date=date(2026, 8, 1),
        window_end_date=date(2026, 10, 24),
        sample_count=84,
        mean_value=57.6,
        median_value=58.0,
        lower_quartile_value=52.0,
        upper_quartile_value=64.0,
    )
    comparison = _baseline_comparison(baseline, 62)
    for field in ("baselineMedian", "lowerQuartile", "upperQuartile"):
        assert field in comparison
        assert field in MORNING_PLAIN_WORDS_RULE


def test_statistics_words_are_for_the_reasoning_never_for_mark() -> None:
    rule = _flat(MORNING_PLAIN_WORDS_RULE)
    assert "A baselineMedian is his usual" in rule
    assert "the span from a lowerQuartile to its upperQuartile is his usual range" in rule
    assert (
        "Quartile, percentile, median and standard deviation are words for your reasoning, "
        "never for Mark: never write them in the read"
    ) in rule
    # The packet writes its own bases and reasons in these words, and REM's framing rule
    # (shared verbatim with Trends) reasons in medians and quartiles.
    assert "even where a rule above or a basis, reason or warning in the packet uses them" in rule
    assert "rather than how it was calculated" in rule
    assert 'never "n=" or "samples"' in rule


def test_the_rule_comes_after_the_rules_that_frame_his_baselines() -> None:
    at = GRADED_SYSTEM_PROMPT.index(MORNING_PLAIN_WORDS_RULE)
    assert GRADED_SYSTEM_PROMPT.index(REM_FRAMING_RULE) < at
    assert GRADED_SYSTEM_PROMPT.index(METRIC_STATEMENT_RULE) < at
    assert GRADED_SYSTEM_PROMPT.count(REM_FRAMING_RULE) == 1  # shared, so never edited here


def test_no_sentence_asks_for_a_median_in_his_words() -> None:
    graded = _flat(GRADED_SYSTEM_PROMPT)
    assert '"yesterday drained 66, dead on your usual 67"' in graded
    assert "dead on your 67 median" not in graded
    assert "his usual readiness over the last six weeks has fallen below the six weeks" in graded
    assert "readiness median has declined" not in graded
    # The ladder, kept for the one-setting rollback, still reads as it did.
    ladder = _flat(LADDER_SYSTEM_PROMPT)
    assert "dead on your 67 median" in ladder
    assert "readiness median has declined" in ladder
    # Both prompts keep every floor they state, the readiness warning's among them.
    assert missing_floors(GRADED_SYSTEM_PROMPT, READ_PROMPT_FLOORS["morning_analysis"]) == ()
    assert missing_floors(LADDER_SYSTEM_PROMPT, LADDER_MORNING_FLOORS) == ()


# -- the logged wording check ----------------------------------------------------------


def test_the_wording_check_finds_what_the_briefs_showed() -> None:
    leaky = (
        "## Metrics vs baselines\n"
        "- **Sleep score**: 62 vs your median of 58, upper quartile 64.\n"
        "- **REM**: below your own usual range (your personal quartiles are 8.0–12.0%).\n"
        "- **HRV**: your floor is your median minus 1.5 standard deviations (n=84).\n"
    )
    assert brief_wording_leaks(leaky) == (
        "quartile_or_percentile",
        "median",
        "standard_deviation",
        "sample_count",
    )
    assert brief_wording_leaks("Your REM sits in the 30th percentile, over 12 samples.") == (
        "quartile_or_percentile",
        "sample_count",
    )


def test_the_wording_check_passes_plain_words() -> None:
    clean = (
        "## Today's call\n**Green light** — **Recovered**.\n\n"
        "## Metrics vs baselines\n"
        "- **Sleep score**: 62 against your usual 58, inside your usual range of 52–64.\n"
        "- **HRV**: 44 ms, under your usual but above your own floor of 41 ms, set from "
        "your recent nights.\n"
        "- **Yesterday**: drained 66, dead on your usual 67, over 84 nights of baseline.\n"
    )
    assert brief_wording_leaks(clean) == ()


@pytest.mark.asyncio
async def test_a_brief_that_slips_is_logged_and_still_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log)
    stored = _stored()
    service, _session, _claims = _writing_service(monkeypatch, stored)
    slipped = "**Sleep:** 62 vs your median of 58, upper quartile 64."

    result = await service.write_brief(_profile(), DAY, client=_RecordingClient(slipped))

    assert result.generated is True
    assert stored.output_markdown == slipped  # logged for Craig, never withheld from Mark
    leak_calls = [
        call
        for call in log.warning.call_args_list
        if call.args[0] == "morning_analysis_wording_leaks"
    ]
    assert len(leak_calls) == 1
    assert leak_calls[0].kwargs["leaks"] == ["quartile_or_percentile", "median"]
    assert leak_calls[0].kwargs["subject_date"] == DAY.isoformat()
    assert leak_calls[0].kwargs["prompt_version"] == GRADED_PROMPT_VERSION


@pytest.mark.asyncio
async def test_a_plain_brief_logs_no_wording_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log)
    stored = _stored()
    service, _session, _claims = _writing_service(monkeypatch, stored)

    await service.write_brief(
        _profile(), DAY, client=_RecordingClient("**Sleep:** 62 against your usual 58.")
    )

    assert all(
        call.args[0] != "morning_analysis_wording_leaks" for call in log.warning.call_args_list
    )


# -- on Postgres: the stamp a stored brief carries ---------------------------------------


@pytest.mark.asyncio
async def test_the_morning_packet_stamps_the_rule(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    day = date(2026, 10, 9)
    async with session_factory() as session:
        player = await _player(session, "Plain Words Morning")
        await _seed_one_poor_night(session, player.id, day)
        await session.commit()
        packet = await MorningAnalysisService(session).assemble_context_packet(player, day)

    rules = packet["prompt"]["outputRules"]
    assert "give_every_figure_in_plain_words" in rules
    assert rules.index("give_recorded_disruption_first_as_likely_cause") < rules.index(
        "give_every_figure_in_plain_words"
    )
    assert packet["prompt"]["version"] == GRADED_PROMPT_VERSION
