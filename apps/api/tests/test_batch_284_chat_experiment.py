"""Batch 284 — something Mark says in passing becomes a question with a comparator.

On 19 Sep 2026 Mark said his HRV drops in recovery weeks, and the coach could only
decline to call it established. Batch 275 gave the app a comparator that can answer
him. This batch lets the conversation-learning extractor turn such an observation
into a **proposed experiment**: already bound to that comparator, inert until Mark
decides, and created the moment he accepts (Craig, 25 Sep). An observation that
binds to nothing is discarded at extraction rather than stored — the rule 275.3
applies at creation, not re-admitted through a friendlier door.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    ConversationLearningProposal,
    Experiment,
    KnowledgeBase,
    ManualEntry,
)
from src.models.profile import Profile, UserRole
from src.services.anthropic_text import anthropic_schema
from src.services.conversation_learning import (
    EXPERIMENTS_DESTINATION,
    KIND_EXPERIMENT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ConversationLearningClient,
    ConversationLearningService,
    ExtractionEnvelope,
    LearningSource,
    filter_candidates,
)
from src.services.experiment_evaluation import GROUP_MIN_PER_GROUP, binds_to_an_evaluator
from src.services.experiment_metrics import COMPARABLE_METRICS

HRV_QUOTE = "my HRV drops in recovery weeks"


def _source(source_id: str, text: str) -> LearningSource:
    return LearningSource(
        source_id=source_id,
        source_type="chat",
        source_date=date(2026, 9, 19),
        text=text,
        occurred_at_utc=datetime(2026, 9, 19, 9, 0),
    )


def _candidate(
    *,
    kind: str = KIND_EXPERIMENT,
    destination: str = EXPERIMENTS_DESTINATION,
    experiment: dict[str, Any] | None = None,
    statement: str = "Mark's overnight HRV drops in his recovery weeks.",
    source_id: str = "chat:hrv",
    quote: str = HRV_QUOTE,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "statement": statement,
        "destination": destination,
        "experiment": experiment,
        "evidence": [{"source_id": source_id, "quote": quote}],
    }


HRV_BINDING = {"compare": "recovery_week_vs_build_week", "metric": "hrv_last_night_avg_ms"}
SOURCES = [_source("chat:hrv", "I think my HRV drops in recovery weeks, every cycle.")]


def _kept(*candidates: dict[str, Any]) -> list[Any]:
    return filter_candidates(
        ExtractionEnvelope.model_validate({"candidates": list(candidates)}),
        sources=SOURCES,
        existing_statements=[],
    )


# -- extraction ---------------------------------------------------------------


def test_an_observation_bound_to_a_metric_and_a_comparison_is_kept() -> None:
    kept = _kept(_candidate(experiment=HRV_BINDING))
    assert len(kept) == 1
    assert kept[0].kind == KIND_EXPERIMENT
    assert kept[0].destination == EXPERIMENTS_DESTINATION
    assert kept[0].experiment is not None
    assert kept[0].experiment.metric == "hrv_last_night_avg_ms"


@pytest.mark.parametrize(
    "candidate",
    [
        # No binding at all.
        _candidate(experiment=None),
        # A metric the app cannot read.
        _candidate(experiment={"compare": "recovery_week_vs_build_week", "metric": "vibes"}),
        # An experiment routed to memory, and memory routed to experiments.
        _candidate(destination="learned_context", experiment=HRV_BINDING),
    ],
)
def test_an_observation_that_binds_to_nothing_is_discarded(candidate: dict[str, Any]) -> None:
    assert _kept(candidate) == []


def test_a_comparison_the_app_cannot_run_is_refused_by_the_schema() -> None:
    with pytest.raises(Exception):
        ExtractionEnvelope.model_validate(
            {
                "candidates": [
                    _candidate(experiment={"compare": "morning_vs_evening", "metric": "awake_min"})
                ]
            }
        )


def test_the_four_memory_kinds_keep_their_one_destination() -> None:
    memory = _candidate(
        kind="recurring_theme",
        destination="learned_context",
        statement="Mark's HRV always drops in his recovery weeks.",
    )
    assert len(_kept(memory)) == 1
    # A memory that tries to carry a binding, or to leave learned_context, is dropped.
    assert _kept({**memory, "experiment": HRV_BINDING}) == []
    assert _kept({**memory, "destination": EXPERIMENTS_DESTINATION}) == []


def test_the_prompt_offers_the_new_kind_with_every_metric_it_can_test() -> None:
    assert PROMPT_VERSION == "conversation-learning-v3-2026-09-27"
    assert "experiment" in SYSTEM_PROMPT
    for key in COMPARABLE_METRICS:
        assert key in SYSTEM_PROMPT


def test_the_structured_output_schema_only_allows_metrics_it_can_read() -> None:
    schema = json.dumps(anthropic_schema(ExtractionEnvelope))
    for key in COMPARABLE_METRICS:
        assert f'"{key}"' in schema
    assert '"recovery_week_vs_build_week"' in schema


# -- the service --------------------------------------------------------------


class FakeLearningClient(ConversationLearningClient):
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output

    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str:
        return json.dumps(self.output)


async def _mark_with_a_note(session: AsyncSession, note: str) -> tuple[Profile, ManualEntry]:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Experiment Test",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    entry = ManualEntry(
        user_id=player.id,
        entry_date=date(2026, 9, 19),
        entry_at_utc=datetime(2026, 9, 19, 8, 0),
        notes=note,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return player, entry


def _hrv_output(entry: ManualEntry) -> dict[str, object]:
    return {
        "candidates": [
            _candidate(
                experiment=HRV_BINDING,
                source_id=f"checkin:{entry.id}",
                quote=HRV_QUOTE,
            )
        ]
    }


NOTE = "Third cycle running: my HRV drops in recovery weeks, every time."
NOW = datetime(2026, 9, 20, 9, 0)


@pytest.mark.asyncio
async def test_a_bound_observation_waits_for_a_decision_and_changes_nothing(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player, entry = await _mark_with_a_note(session, NOTE)
        created = await ConversationLearningService(session).distill(
            player, client=FakeLearningClient(_hrv_output(entry)), now=NOW
        )
        experiments = (
            (await session.execute(select(Experiment).where(Experiment.user_id == player.id)))
            .scalars()
            .all()
        )
        memory = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id, KnowledgeBase.section == "learned_context"
            )
        )

    assert len(created) == 1
    proposal = created[0]
    assert proposal.status == "pending"
    assert proposal.kind == KIND_EXPERIMENT
    assert proposal.destination == EXPERIMENTS_DESTINATION
    assert {item["experiment"]["metric"] for item in proposal.evidence_json} == {
        "hrv_last_night_avg_ms"
    }
    assert {item["promptVersion"] for item in proposal.evidence_json} == {PROMPT_VERSION}
    assert experiments == []
    assert memory is None


@pytest.mark.asyncio
async def test_a_question_already_under_test_is_not_proposed_again(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player, entry = await _mark_with_a_note(session, NOTE)
        session.add(
            Experiment(
                user_id=player.id,
                title="Already running",
                hypothesis="HRV in recovery weeks",
                status="active",
                success_criteria_json=dict(HRV_BINDING),
                observations_json={"entries": []},
            )
        )
        await session.commit()
        created = await ConversationLearningService(session).distill(
            player, client=FakeLearningClient(_hrv_output(entry)), now=NOW
        )

    assert created == []


@pytest.mark.asyncio
async def test_accepting_creates_an_experiment_that_binds_and_cannot_be_decided_twice(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player, entry = await _mark_with_a_note(session, NOTE)
        service = ConversationLearningService(session)
        [proposal] = await service.distill(
            player, client=FakeLearningClient(_hrv_output(entry)), now=NOW
        )

        reviewed = await service.review(player, proposal.id, decision="accept")
        assert reviewed.status == "accepted"

        [experiment] = (
            (await session.execute(select(Experiment).where(Experiment.user_id == player.id)))
            .scalars()
            .all()
        )
        assert experiment.status == "active"
        assert experiment.hypothesis == proposal.statement
        assert binds_to_an_evaluator(experiment.success_criteria_json)
        assert experiment.success_criteria_json["metric"] == "hrv_last_night_avg_ms"
        assert experiment.success_criteria_json["proposalId"] == str(proposal.id)

        memory = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id, KnowledgeBase.section == "learned_context"
            )
        )
        assert memory is None

        with pytest.raises(HTTPException) as twice:
            await service.review(player, proposal.id, decision="accept")
        assert twice.value.status_code == 409


@pytest.mark.asyncio
async def test_rejecting_an_experiment_proposal_creates_nothing(db_conn: AsyncConnection) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player, entry = await _mark_with_a_note(session, NOTE)
        service = ConversationLearningService(session)
        [proposal] = await service.distill(
            player, client=FakeLearningClient(_hrv_output(entry)), now=NOW
        )
        rejected = await service.review(player, proposal.id, decision="reject")
        experiments = (
            (await session.execute(select(Experiment).where(Experiment.user_id == player.id)))
            .scalars()
            .all()
        )
        stored = await session.get(ConversationLearningProposal, proposal.id)

    assert rejected.status == "rejected"
    assert experiments == []
    assert stored is not None and stored.status == "rejected"


def test_the_card_states_the_comparison_and_the_nights_it_needs() -> None:
    """The coaching-state API describes the binding for the proposal card."""
    from src.routers.coaching_state import _serialize_learning_proposal

    row = ConversationLearningProposal(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=KIND_EXPERIMENT,
        destination=EXPERIMENTS_DESTINATION,
        statement="Mark's overnight HRV drops in his recovery weeks.",
        evidence_json=[
            {
                "sourceId": "checkin:x",
                "sourceType": "checkin_note",
                "sourceDate": "2026-09-19",
                "analysisId": None,
                "analysisType": None,
                "promptVersion": PROMPT_VERSION,
                "quote": HRV_QUOTE,
                "experiment": dict(HRV_BINDING),
            }
        ],
        fingerprint="f" * 64,
        status="pending",
        created_at=datetime(2026, 9, 20, 9, 0),
    )
    out = _serialize_learning_proposal(row)
    assert out.experiment is not None
    assert out.experiment.metric == "hrv_last_night_avg_ms"
    assert out.experiment.metricLabel == COMPARABLE_METRICS["hrv_last_night_avg_ms"].label
    assert out.experiment.nightsPerGroup == GROUP_MIN_PER_GROUP == 7
    assert out.experiment.evidenceCount == 1
