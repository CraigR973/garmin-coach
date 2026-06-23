"""Tests for Batch 23 auto-generated handover-doc export (the v3 capstone).

Covers the four acceptance pillars:
  23.1 — deterministic packet assembly composes the full retained state (pure)
  23.2 — Claude narrative boundary, fakeable without ``ANTHROPIC_API_KEY``
  23.3/23.4 — portable markdown render faithfully reflects retained state (pure)
  23.4 — human/API-triggered: previews never write, ``run`` is idempotent (#71)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Analysis,
    DailyMetric,
    KnowledgeBase,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services.handover import (
    ANALYSIS_TYPE_HANDOVER,
    BaselineSummary,
    ExperimentSummary,
    HandoverService,
    PlanSummary,
    ReviewSummary,
    build_handover_packet,
    render_handover_markdown,
)
from src.services.reviews import ClaudeReviewResult

AS_OF = date(2026, 6, 23)
GENERATED = datetime(2026, 6, 23, 8, 0, tzinfo=UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pure: packet assembly (23.1)
# ---------------------------------------------------------------------------


def _kb() -> dict[str, Any]:
    return {
        "profile": {"athleteName": "Mark", "age": 57, "ftpWatts": 280},
        "data_quality_rules": {
            "rules": [
                {
                    "id": "no_lr_balance",
                    "summary": "Ignore left/right power balance.",
                    "reason": "x",
                }
            ]
        },
        "age_adjustment": {"sleepScoreDelta": 4},
        "sleep_protocol": {"bedtime": "23:15"},
        "training_plan": {"framework": "13-week 2121"},
        "active_hypotheses": {"hypotheses": [{"title": "Collagen", "status": "hold", "rule": "y"}]},
        "unrelated_section": {"should": "not appear"},
    }


def _plan() -> PlanSummary:
    return PlanSummary(
        block_name="Build 1",
        block_type="build",
        block_start=date(2026, 6, 22),
        block_end=date(2026, 6, 28),
        sequence_index=1,
        upcoming_count=1,
        upcoming=[{"date": "2026-06-24", "title": "VO2", "workoutType": "vo2"}],
    )


def _packet(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        display_name="Mark",
        user_id="user-1",
        timezone="Europe/London",
        generated_at=GENERATED,
        knowledge_base=_kb(),
        plan=_plan(),
        baselines=[
            BaselineSummary(
                metric_key="sleep_score",
                metric_label="Sleep score",
                sample_count=84,
                excluded_sample_count=0,
                mean=72.0,
                median=73.0,
                minimum=55.0,
                maximum=88.0,
            )
        ],
        reviews=[
            ReviewSummary(
                analysis_type="weekly_review",
                subject_date=date(2026, 6, 15),
                generated_at_utc=GENERATED,
                model_name="fake",
                excerpt="Sleep improving.",
            )
        ],
        trends={
            "bucket": "season",
            "yearOnYear": {"status": "insufficient_history", "reasons": []},
        },
        experiments=[
            ExperimentSummary(
                title="Collagen reintroduction",
                hypothesis="Gate behind 7 clean nights.",
                status="active",
                slug="collagen",
                evaluation_status="ok",
                recommendation="supported",
                reasons=["Gate met."],
            )
        ],
        strength={
            "trend": "stable",
            "trendReason": "flat",
            "sessions4w": 4,
            "sessionsPerWeek4w": 1.0,
            "sessions12w": 12,
        },
    )
    kwargs.update(overrides)
    return build_handover_packet(**kwargs)


def test_packet_includes_only_known_kb_sections() -> None:
    packet = _packet()
    kb = packet["knowledgeBase"]
    assert "profile" in kb
    assert "active_hypotheses" in kb
    # An arbitrary section is dropped — the packet shape is deterministic.
    assert "unrelated_section" not in kb


def test_packet_echoes_data_quality_guardrails() -> None:
    packet = _packet()
    guardrails = packet["dataQualityGuardrails"]
    assert len(guardrails) == 1
    assert guardrails[0]["id"] == "no_lr_balance"


def test_packet_composes_every_batch_output() -> None:
    packet = _packet()
    # The capstone summarises every prior batch's surface.
    assert packet["plan"]["blockName"] == "Build 1"
    assert packet["baselines"][0]["metricKey"] == "sleep_score"
    assert packet["recentReviews"][0]["type"] == "weekly_review"
    assert packet["trends"]["yearOnYear"]["status"] == "insufficient_history"
    assert packet["experiments"][0]["recommendation"] == "supported"
    assert packet["strengthBrief"]["sessions12w"] == 12
    assert packet["prompt"]["version"].startswith("handover-")


# ---------------------------------------------------------------------------
# Pure: deterministic markdown render (23.3/23.4 — faithful round-trip)
# ---------------------------------------------------------------------------


def test_render_reflects_retained_state_faithfully() -> None:
    md = render_handover_markdown(_packet())
    assert "# Garmin Coach — Handover Document" in md
    # Profile, rules, plan, baselines, hypotheses, reviews, strength all present.
    assert "Mark" in md
    assert "Ignore left/right power balance." in md
    assert "Build 1" in md
    assert "Sleep score" in md
    assert "Collagen" in md
    assert "weekly review" in md
    assert "Strength watching-brief" in md
    # The data-driven evaluation recommendation is layered onto the hypothesis.
    assert "supported" in md


def test_render_handles_empty_state_without_crashing() -> None:
    packet = build_handover_packet(
        display_name="Mark",
        user_id="u",
        timezone="Europe/London",
        generated_at=GENERATED,
        knowledge_base={},
        plan=PlanSummary(None, None, None, None, None, 0, []),
        baselines=[],
        reviews=[],
        trends={},
        experiments=[],
        strength={},
    )
    md = render_handover_markdown(packet)
    assert "No data-quality rules on record." in md
    assert "No baselines computed yet." in md
    assert "No reviews generated yet." in md


def test_render_never_mentions_lr_balance_unless_in_rules() -> None:
    # The render only surfaces L/R balance as a *rule to obey*, never as advice.
    md = render_handover_markdown(_packet())
    # It appears exactly once — inside the data-quality rules section.
    assert md.count("left/right power balance") == 1


# ---------------------------------------------------------------------------
# Claude narrative boundary fake (no ANTHROPIC_API_KEY needed)
# ---------------------------------------------------------------------------


class FakeReviewClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeReviewResult:
        self.calls.append({"packet": context_packet, "prompt": user_prompt})
        return ClaudeReviewResult(
            output_markdown="# Handover\n\nMark is a 57-year-old endurance athlete.",
            raw_response={"id": "fake", "model": "fake-model"},
            model_name="fake-model",
        )


# ---------------------------------------------------------------------------
# DB-backed service tests
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Handover Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


async def _seed_state(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="profile",
                version=1,
                is_active=True,
                content={"athleteName": "Mark", "age": 57, "ftpWatts": 280},
            )
        )
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="data_quality_rules",
                version=1,
                is_active=True,
                content={
                    "rules": [
                        {"id": "no_lr_balance", "summary": "Ignore L/R balance.", "reason": "x"}
                    ]
                },
            )
        )
        session.add(
            PlanBlock(
                user_id=user_id,
                name="Build 1",
                version=1,
                sequence_index=1,
                block_type="build",
                start_date=date(2026, 6, 22),
                end_date=date(2026, 6, 28),
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=AS_OF + timedelta(days=1),
                version=1,
                title="VO2",
                workout_type="vo2",
                is_active=True,
            )
        )
        session.add(
            MetricBaseline(
                user_id=user_id,
                metric_key="sleep_score",
                metric_label="Sleep score",
                window_start_date=date(2026, 3, 24),
                window_end_date=date(2026, 6, 15),
                sample_count=84,
                excluded_sample_count=0,
                mean_value=72.0,
                median_value=73.0,
                min_value=55.0,
                max_value=88.0,
            )
        )
        # Enough sleep history for the evaluators not to crash (they just skip).
        for i in range(10):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=AS_OF - timedelta(days=i),
                    score=75,
                    age_adjusted_score=79,
                    duration_sec=27000,
                )
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=AS_OF - timedelta(days=i),
                    readiness_score=65,
                    hrv_last_night_avg_ms=52,
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_preview_assembles_packet_and_never_writes(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_state(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        before = await session.scalar(select(func.count()).select_from(Analysis))

        service = HandoverService(session)
        preview = await service.preview(user, as_of=AS_OF)

        assert preview.subject_date == AS_OF
        assert "knowledgeBase" in preview.packet
        assert preview.packet["plan"]["blockName"] == "Build 1"
        assert preview.packet["baselines"][0]["metricKey"] == "sleep_score"
        assert "# Garmin Coach — Handover Document" in preview.markdown
        assert preview.latest_export is None

        # GET preview must not write an analyses row (#71) — incl. no experiment seed.
        after = await session.scalar(select(func.count()).select_from(Analysis))
        assert after == before


@pytest.mark.asyncio
async def test_run_generates_and_stores_handover(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_state(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HandoverService(session)
        client = FakeReviewClient()
        result = await service.run(user, as_of=AS_OF, client=client)

        assert result.generated is True
        assert result.export.analysis_type == ANALYSIS_TYPE_HANDOVER
        assert result.export.subject_date == AS_OF
        assert result.export.model_name == "fake-model"
        assert "endurance athlete" in result.export.output_markdown
        assert len(client.calls) == 1

        stored = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == ANALYSIS_TYPE_HANDOVER)
                )
            )
            .scalars()
            .all()
        )
        assert len(stored) == 1


@pytest.mark.asyncio
async def test_run_is_idempotent_per_day(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_state(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HandoverService(session)
        client = FakeReviewClient()

        first = await service.run(user, as_of=AS_OF, client=client)
        second = await service.run(user, as_of=AS_OF, client=client)

        assert first.generated is True
        assert second.generated is False
        assert len(client.calls) == 1  # the second call short-circuits

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_HANDOVER)
        )
        assert count == 1
