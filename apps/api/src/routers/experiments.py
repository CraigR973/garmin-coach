"""Experiment tracker API (Batch 17.4).

Manage active hypotheses with status/outcomes; the three standing hypotheses seed
on first GET. Every change is audited in ``analyses``.

  GET  /api/v1/experiments                         — list (seeds defaults)
  POST /api/v1/experiments                         — create a new hypothesis
  POST /api/v1/experiments/{id}/status             — pause/resume/conclude
  POST /api/v1/experiments/{id}/observations       — append an observation
  GET  /api/v1/experiments/{id}/evaluate           — preview the evidence read (no write)
  POST /api/v1/experiments/{id}/evaluate/run       — record the evaluation (idempotent)

The evaluation (Batch 22) is advisory: it recommends supported/refuted/inconclusive
but never changes status. Accepting a recommendation flows through the existing
``/status`` conclude path, keeping ``concluded`` human-gated and terminal (#72).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Analysis, Experiment
from src.services.experiment_evaluation import (
    EvaluationResult,
    ExperimentEvaluationService,
)
from src.services.experiment_tracker import ExperimentTrackerService

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class ExperimentOut(BaseModel):
    id: str
    title: str
    hypothesis: str
    status: str
    startDate: str | None
    endDate: str | None
    successCriteria: dict[str, Any]
    observations: dict[str, Any]


class ExperimentListEnvelope(BaseModel):
    data: list[ExperimentOut]
    meta: ApiMeta
    errors: list[ApiError]


class ExperimentEnvelope(BaseModel):
    data: ExperimentOut
    meta: ApiMeta
    errors: list[ApiError]


class CreateInput(BaseModel):
    title: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    successCriteria: dict[str, Any] | None = None
    startDate: str | None = None


class StatusInput(BaseModel):
    status: str
    outcome: str | None = None
    note: str | None = None
    onDate: str | None = None


class ObservationInput(BaseModel):
    note: str = Field(min_length=1)
    onDate: str | None = None
    metrics: dict[str, Any] | None = None


class StoredEvaluation(BaseModel):
    generatedAtUtc: str
    subjectDate: str
    recommendation: str | None
    markdown: str


class EvaluationData(BaseModel):
    experimentId: str
    title: str
    status: str
    slug: str | None
    kind: str
    evaluationStatus: str
    recommendation: str | None
    sampleCount: int
    windowStart: str | None
    windowEnd: str | None
    evidence: dict[str, Any]
    reasons: list[str]
    canConclude: bool
    stored: StoredEvaluation | None


class EvaluationEnvelope(BaseModel):
    data: EvaluationData
    meta: ApiMeta
    errors: list[ApiError]


def _out(experiment: Experiment) -> ExperimentOut:
    return ExperimentOut(
        id=str(experiment.id),
        title=experiment.title,
        hypothesis=experiment.hypothesis,
        status=experiment.status,
        startDate=experiment.start_date.isoformat() if experiment.start_date else None,
        endDate=experiment.end_date.isoformat() if experiment.end_date else None,
        successCriteria=experiment.success_criteria_json or {},
        observations=experiment.observations_json or {},
    )


def _meta() -> ApiMeta:
    return ApiMeta(generatedAtUtc=_generated_at())


@router.get("", response_model=ExperimentListEnvelope)
async def list_experiments(
    player: CurrentUser,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> ExperimentListEnvelope:
    service = ExperimentTrackerService(db)
    experiments = await service.list_experiments(player, status_filter=status)
    return ExperimentListEnvelope(data=[_out(e) for e in experiments], meta=_meta(), errors=[])


@router.post("", response_model=ExperimentEnvelope)
async def create_experiment(
    body: CreateInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ExperimentEnvelope:
    service = ExperimentTrackerService(db)
    experiment = await service.create_experiment(
        player,
        title=body.title,
        hypothesis=body.hypothesis,
        success_criteria=body.successCriteria,
        start_date=date.fromisoformat(body.startDate) if body.startDate else None,
    )
    return ExperimentEnvelope(data=_out(experiment), meta=_meta(), errors=[])


@router.post("/{experiment_id}/status", response_model=ExperimentEnvelope)
async def update_status(
    experiment_id: uuid.UUID,
    body: StatusInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ExperimentEnvelope:
    service = ExperimentTrackerService(db)
    experiment = await service.update_status(
        player,
        experiment_id,
        new_status=body.status,
        outcome=body.outcome,
        note=body.note,
        on_date=date.fromisoformat(body.onDate) if body.onDate else None,
    )
    return ExperimentEnvelope(data=_out(experiment), meta=_meta(), errors=[])


def _stored_evaluation(analysis: Analysis | None) -> StoredEvaluation | None:
    if analysis is None:
        return None
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    return StoredEvaluation(
        generatedAtUtc=analysis.generated_at_utc.isoformat() + "Z",
        subjectDate=analysis.subject_date.isoformat(),
        recommendation=packet.get("recommendation"),
        markdown=analysis.output_markdown,
    )


def _evaluation_data(
    experiment: Experiment,
    result: EvaluationResult,
    stored: Analysis | None,
) -> EvaluationData:
    # Concluding stays terminal & human-gated: only offer it on a non-concluded
    # experiment with an actionable recommendation (#72).
    can_conclude = experiment.status != "concluded" and result.recommendation is not None
    return EvaluationData(
        experimentId=str(experiment.id),
        title=experiment.title,
        status=experiment.status,
        slug=result.slug,
        kind=result.kind,
        evaluationStatus=result.status,
        recommendation=result.recommendation,
        sampleCount=result.sample_count,
        windowStart=result.window_start.isoformat() if result.window_start else None,
        windowEnd=result.window_end.isoformat() if result.window_end else None,
        evidence=result.evidence,
        reasons=result.reasons,
        canConclude=can_conclude,
        stored=_stored_evaluation(stored),
    )


@router.get("/{experiment_id}/evaluate", response_model=EvaluationEnvelope)
async def evaluate_experiment(
    experiment_id: uuid.UUID,
    player: CurrentUser,
    as_of: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> EvaluationEnvelope:
    service = ExperimentEvaluationService(db)
    experiment = await service._get_owned(player, experiment_id)
    result = await service.evaluate(
        player, experiment, as_of=date.fromisoformat(as_of) if as_of else None
    )
    stored = await service.latest_evaluation(player, experiment_id)
    return EvaluationEnvelope(
        data=_evaluation_data(experiment, result, stored), meta=_meta(), errors=[]
    )


@router.post("/{experiment_id}/evaluate/run", response_model=EvaluationEnvelope)
async def run_evaluation(
    experiment_id: uuid.UUID,
    player: CurrentUser,
    as_of: str | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> EvaluationEnvelope:
    service = ExperimentEvaluationService(db)
    result, analysis = await service.run(
        player,
        experiment_id,
        as_of=date.fromisoformat(as_of) if as_of else None,
        force=force,
    )
    experiment = await service._get_owned(player, experiment_id)
    return EvaluationEnvelope(
        data=_evaluation_data(experiment, result, analysis), meta=_meta(), errors=[]
    )


@router.post("/{experiment_id}/observations", response_model=ExperimentEnvelope)
async def add_observation(
    experiment_id: uuid.UUID,
    body: ObservationInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ExperimentEnvelope:
    service = ExperimentTrackerService(db)
    experiment = await service.add_observation(
        player,
        experiment_id,
        note=body.note,
        on_date=date.fromisoformat(body.onDate) if body.onDate else None,
        metrics=body.metrics,
    )
    return ExperimentEnvelope(data=_out(experiment), meta=_meta(), errors=[])
