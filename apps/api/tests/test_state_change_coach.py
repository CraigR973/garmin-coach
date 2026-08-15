"""Batch 187: proactive coach turns only when meaningful state changes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile, UserRole
from src.services.state_change_coach import (
    ANALYSIS_TYPE_STATE_CHANGE,
    ORIGIN_KIND_STATE_CHANGE,
    StateChangeCandidate,
    StateChangeCoachService,
    StateChangeResult,
    StateSnapshot,
    _chronic_snapshot,
    choose_ranked_candidate,
    transition_candidate,
)

TODAY = date(2026, 8, 5)


def _snapshot(
    kind: str,
    *,
    key: str | None = None,
    value: str = "active",
) -> StateSnapshot:
    return StateSnapshot(
        kind=kind,  # type: ignore[arg-type]
        state_key=key or kind,
        state_value=value,
        title=f"{kind} changed",
        message=f"**Something changed:** {kind}",
        evidence={"kind": kind},
    )


def _morning_analysis(
    user_id: uuid.UUID,
    *,
    subject_date: date,
    chronic_triggered: bool,
) -> Analysis:
    chronic_action = {
        "triggered": chronic_triggered,
        "kind": "deload_proposal",
        "suppressedByPlan": False,
        "triggerSources": ["sustained_recovery_marker"],
        "reasons": ["Two qualified Red mornings now sit in the rolling window."],
    }
    return Analysis(
        user_id=user_id,
        activity_id=None,
        analysis_type="morning",
        subject_date=subject_date,
        generated_at_utc=datetime.combine(subject_date, datetime.min.time()).replace(hour=7),
        prompt_version="morning-test",
        model_name="test",
        verdict="Red" if chronic_triggered else "Green",
        context_packet={"verdict": {"chronicAction": chronic_action}},
        output_markdown="Morning test packet",
        raw_response={},
    )


def test_standing_state_is_not_a_new_transition() -> None:
    current = _snapshot("chronic_action", value="deload_proposal:sustained_recovery_marker")

    assert transition_candidate(current, "deload_proposal:sustained_recovery_marker") is None

    flipped = transition_candidate(current, "clear")
    assert flipped is not None
    assert flipped.snapshot is current
    assert flipped.previous_value == "clear"


def test_ranked_collision_sends_the_stronger_message() -> None:
    weekly = StateChangeCandidate(_snapshot("weekly_mix", key="weekly_mix:vo2"), None)
    experiment = StateChangeCandidate(_snapshot("experiment_outcome", key="experiment:x"), None)
    chronic = StateChangeCandidate(_snapshot("chronic_action"), None)

    chosen = choose_ranked_candidate([weekly, experiment, chronic])

    assert chosen is chronic


def test_plan_suppressed_chronic_action_is_silent() -> None:
    action = {
        "triggered": False,
        "kind": "rearrange_proposal",
        "suppressedByPlan": True,
        "scheduledRecoveryBlocks": [
            {"name": "Recovery week", "blockType": "recovery"},
        ],
    }

    assert _chronic_snapshot(action) is None


class FakeStateChangeCoachService(StateChangeCoachService):
    def __init__(
        self,
        session: AsyncSession,
        candidates: list[StateChangeCandidate],
    ) -> None:
        super().__init__(session)
        self._fake_candidates = candidates

    async def _candidates(  # type: ignore[override]
        self, player: Profile, *, as_of: date
    ) -> list[StateChangeCandidate]:
        return self._fake_candidates


@pytest.mark.asyncio
async def test_transition_writes_one_replyable_assistant_turn(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    sent_at = datetime(2026, 8, 5, 10, 45, tzinfo=UTC)
    snapshot = _snapshot(
        "weekly_mix",
        key="weekly_mix:vo2",
        value="at_risk",
    )
    candidate = StateChangeCandidate(snapshot=snapshot, previous_value=None)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="State Change Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

        service = FakeStateChangeCoachService(session, [candidate])
        first = await service.run(player, as_of=TODAY, now_utc=sent_at)
        second = await service.run(player, as_of=TODAY, now_utc=sent_at)

        analysis_count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == ANALYSIS_TYPE_STATE_CHANGE,
            )
        )
        messages = (
            (await session.execute(select(BriefMessage).where(BriefMessage.user_id == user_id)))
            .scalars()
            .all()
        )

    assert first.message_created is True
    assert first.analysis is not None
    assert first.message is not None
    assert first.message.role == "assistant"
    assert first.message.analysis_id == first.analysis.id
    assert first.message.origin_kind == ORIGIN_KIND_STATE_CHANGE
    assert first.message.origin_date == TODAY
    assert first.analysis.context_packet["stateKey"] == "weekly_mix:vo2"
    assert first.analysis.context_packet["budgetSpend"] == "initial"
    assert first.analysis.context_packet["preemptedAnalysisId"] is None
    assert first.analysis.context_packet["verdictImpact"] == "none"
    assert first.analysis.context_packet["planMutation"] == "none"
    assert second.message_created is False
    assert second.reason == "budget_spent"
    assert analysis_count == 1
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_ranked_budget_allows_only_one_stronger_preemption(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    weekly = StateChangeCandidate(
        _snapshot("weekly_mix", key="weekly_mix:endurance", value="at_risk"),
        None,
    )
    experiment = StateChangeCandidate(
        _snapshot("experiment_outcome", key="experiment:collagen", value="supported"),
        None,
    )
    chronic = StateChangeCandidate(
        _snapshot("chronic_action", value="deload_proposal:sustained_recovery_marker"),
        None,
    )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Ranked Budget Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

        first = await FakeStateChangeCoachService(session, [weekly]).run(
            player,
            as_of=TODAY,
            now_utc=datetime(2026, 8, 5, 10, 45, tzinfo=UTC),
        )
        second = await FakeStateChangeCoachService(session, [experiment]).run(
            player,
            as_of=date(2026, 8, 6),
            now_utc=datetime(2026, 8, 6, 10, 45, tzinfo=UTC),
        )
        third = await FakeStateChangeCoachService(session, [chronic]).run(
            player,
            as_of=date(2026, 8, 7),
            now_utc=datetime(2026, 8, 7, 10, 45, tzinfo=UTC),
        )

        rows = list(
            (
                await session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_STATE_CHANGE,
                    )
                    .order_by(Analysis.subject_date)
                )
            )
            .scalars()
            .all()
        )

    assert first.message_created is True
    assert first.analysis is not None
    assert second.message_created is True
    assert second.analysis is not None
    assert second.analysis.context_packet["budgetSpend"] == "preemption"
    assert second.analysis.context_packet["preemptedAnalysisId"] == str(first.analysis.id)
    assert third.message_created is False
    assert third.reason == "budget_spent"
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_chronic_transition_preempts_a_weekly_mix_spend(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    weekly = StateChangeCandidate(
        _snapshot("weekly_mix", key="weekly_mix:endurance", value="at_risk"),
        None,
    )
    chronic = StateChangeCandidate(
        _snapshot("chronic_action", value="deload_proposal:sustained_recovery_marker"),
        None,
    )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Chronic Preemption Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

        first = await FakeStateChangeCoachService(session, [weekly]).run(
            player,
            as_of=TODAY,
            now_utc=datetime(2026, 8, 5, 10, 45, tzinfo=UTC),
        )
        second = await FakeStateChangeCoachService(session, [chronic]).run(
            player,
            as_of=date(2026, 8, 6),
            now_utc=datetime(2026, 8, 6, 10, 45, tzinfo=UTC),
        )

    assert first.analysis is not None
    assert second.message_created is True
    assert second.analysis is not None
    assert second.analysis.context_packet["transitionKind"] == "chronic_action"
    assert second.analysis.context_packet["budgetSpend"] == "preemption"
    assert second.analysis.context_packet["preemptedAnalysisId"] == str(first.analysis.id)


async def _run_real_morning_transition(
    db_conn: AsyncConnection,
    *,
    previous_triggered: bool | None,
) -> StateChangeResult:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Stored Morning Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()
        if previous_triggered is not None:
            session.add(
                _morning_analysis(
                    user_id,
                    subject_date=TODAY - timedelta(days=1),
                    chronic_triggered=previous_triggered,
                )
            )
        session.add(
            _morning_analysis(
                user_id,
                subject_date=TODAY,
                chronic_triggered=True,
            )
        )
        await session.commit()

        return await StateChangeCoachService(session).run(
            player,
            as_of=TODAY,
            now_utc=datetime(2026, 8, 5, 10, 45, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_unstubbed_standing_morning_state_is_silent(db_conn: AsyncConnection) -> None:
    result = await _run_real_morning_transition(db_conn, previous_triggered=True)

    assert result.message_created is False
    assert result.reason == "no_transition"
    assert result.candidates_seen == 0


@pytest.mark.asyncio
async def test_unstubbed_genuine_morning_flip_creates_message(db_conn: AsyncConnection) -> None:
    result = await _run_real_morning_transition(db_conn, previous_triggered=False)

    assert result.message_created is True
    assert result.reason == "delivered"
    assert result.candidates_seen == 1
    assert result.analysis is not None
    assert result.analysis.context_packet["transitionKind"] == "chronic_action"
    assert result.analysis.context_packet["stateValue"] == (
        "deload_proposal:sustained_recovery_marker"
    )


@pytest.mark.asyncio
async def test_unstubbed_missing_previous_morning_is_unknown_and_silent(
    db_conn: AsyncConnection,
) -> None:
    result = await _run_real_morning_transition(db_conn, previous_triggered=None)

    assert result.message_created is False
    assert result.reason == "no_transition"
    assert result.candidates_seen == 0
