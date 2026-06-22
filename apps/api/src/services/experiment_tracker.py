"""Experiment tracker (Batch 17.4).

Manages Mark's active hypotheses as first-class, lifecycle-tracked records in the
existing ``experiments`` table, with every change audited in ``analyses`` — no
migration needed (both tables exist from Batch 1).

The three standing hypotheses from the knowledge base (ARCHITECTURE §3) seed
automatically on first read:

  * **collagen** — don't reintroduce before 7 consecutive 74+ nights.
  * **recovery_week_disruption** — recovery weeks disrupt sleep.
  * **early_waking_0400** — the 04:00 waking pattern.

Lifecycle: ``active`` ⇄ ``paused`` → ``concluded`` (terminal). Concluding records
an outcome (``supported`` / ``refuted`` / ``inconclusive``). Status changes and
observations are deterministic, validated transitions so the tracker can't land
in an illegal state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, Experiment
from src.models.profile import Profile

PROMPT_VERSION = "experiment-tracker:v1"
AUDIT_TYPE_EXPERIMENT = "experiment_update"

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_CONCLUDED = "concluded"
VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_PAUSED, STATUS_CONCLUDED})

OUTCOME_SUPPORTED = "supported"
OUTCOME_REFUTED = "refuted"
OUTCOME_INCONCLUSIVE = "inconclusive"
VALID_OUTCOMES = frozenset({OUTCOME_SUPPORTED, OUTCOME_REFUTED, OUTCOME_INCONCLUSIVE})

# Allowed status transitions. ``concluded`` is terminal.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_ACTIVE: frozenset({STATUS_PAUSED, STATUS_CONCLUDED}),
    STATUS_PAUSED: frozenset({STATUS_ACTIVE, STATUS_CONCLUDED}),
    STATUS_CONCLUDED: frozenset(),
}


@dataclass(frozen=True)
class DefaultExperiment:
    slug: str
    title: str
    hypothesis: str
    success_criteria: dict[str, Any]


DEFAULT_EXPERIMENTS: tuple[DefaultExperiment, ...] = (
    DefaultExperiment(
        slug="collagen",
        title="Collagen reintroduction",
        hypothesis=(
            "Reintroducing collagen disrupts sleep; only retry after 7 consecutive "
            "74+ (age-adjusted) nights."
        ),
        success_criteria={
            "gateNights": 7,
            "ageAdjustedSleepFloor": 74,
            "note": "Do not reintroduce before the gate is met.",
        },
    ),
    DefaultExperiment(
        slug="recovery_week_disruption",
        title="Recovery-week sleep disruption",
        hypothesis=(
            "Recovery weeks (lower training load) coincide with worse sleep/recovery "
            "rather than better."
        ),
        success_criteria={
            "compare": "recovery_week_vs_build_week",
            "metric": "age_adjusted_sleep_score",
        },
    ),
    DefaultExperiment(
        slug="early_waking_0400",
        title="04:00 waking pattern",
        hypothesis=(
            "Waking around 04:00 is driven by an identifiable trigger (thermal, "
            "alcohol, late snack, or stress)."
        ),
        success_criteria={
            "track": "wake_time",
            "candidateDrivers": ["overnight_temp", "alcohol", "late_snack", "stress"],
        },
    ),
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def can_transition(from_status: str, to_status: str) -> bool:
    """Whether a status change is allowed (a no-op stays allowed)."""
    if to_status not in VALID_STATUSES:
        return False
    if from_status == to_status:
        return True
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


class ExperimentTrackerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_experiments(
        self, player: Profile, *, status_filter: str | None = None, seed: bool = True
    ) -> list[Experiment]:
        if seed:
            await self.seed_defaults(player)
        query = select(Experiment).where(Experiment.user_id == player.id)
        if status_filter:
            query = query.where(Experiment.status == status_filter)
        query = query.order_by(Experiment.created_at.asc())
        return list((await self.session.execute(query)).scalars().all())

    async def seed_defaults(self, player: Profile, *, commit: bool = True) -> list[Experiment]:
        """Idempotently create the three standing hypotheses, keyed by slug."""
        existing = (
            (await self.session.execute(select(Experiment).where(Experiment.user_id == player.id)))
            .scalars()
            .all()
        )
        existing_slugs = {
            e.success_criteria_json.get("slug")
            for e in existing
            if isinstance(e.success_criteria_json, dict)
        }
        created: list[Experiment] = []
        for default in DEFAULT_EXPERIMENTS:
            if default.slug in existing_slugs:
                continue
            experiment = Experiment(
                user_id=player.id,
                title=default.title,
                hypothesis=default.hypothesis,
                status=STATUS_ACTIVE,
                start_date=None,
                end_date=None,
                success_criteria_json={"slug": default.slug, **default.success_criteria},
                observations_json={"entries": []},
            )
            self.session.add(experiment)
            created.append(experiment)
        if created:
            self._record_audit(
                player,
                created[0],
                "seed",
                f"Seeded {len(created)} standing hypotheses.",
                {"slugs": [e.success_criteria_json.get("slug") for e in created]},
            )
            if commit:
                await self.session.commit()
                for experiment in created:
                    await self.session.refresh(experiment)
        return created

    async def _get_owned(self, player: Profile, experiment_id: uuid.UUID) -> Experiment:
        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None or experiment.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment not found",
            )
        return experiment

    async def create_experiment(
        self,
        player: Profile,
        *,
        title: str,
        hypothesis: str,
        success_criteria: dict[str, Any] | None = None,
        start_date: date | None = None,
        commit: bool = True,
    ) -> Experiment:
        experiment = Experiment(
            user_id=player.id,
            title=title,
            hypothesis=hypothesis,
            status=STATUS_ACTIVE,
            start_date=start_date,
            end_date=None,
            success_criteria_json=success_criteria or {},
            observations_json={"entries": []},
        )
        self.session.add(experiment)
        await self.session.flush()
        self._record_audit(player, experiment, "create", f"Created experiment: {title}.", {})
        if commit:
            await self.session.commit()
            await self.session.refresh(experiment)
        return experiment

    async def update_status(
        self,
        player: Profile,
        experiment_id: uuid.UUID,
        *,
        new_status: str,
        outcome: str | None = None,
        note: str | None = None,
        on_date: date | None = None,
        commit: bool = True,
    ) -> Experiment:
        experiment = await self._get_owned(player, experiment_id)
        if not can_transition(experiment.status, new_status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot move experiment from {experiment.status} to {new_status}.",
            )
        if new_status == STATUS_CONCLUDED:
            if outcome not in VALID_OUTCOMES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Concluding requires an outcome in {sorted(VALID_OUTCOMES)}.",
                )
            observations = dict(experiment.observations_json or {})
            observations["outcome"] = outcome
            observations["concludedAt"] = _utcnow().isoformat()
            if note:
                observations["conclusionNote"] = note
            experiment.observations_json = observations
            experiment.end_date = on_date or date.today()

        previous = experiment.status
        experiment.status = new_status
        self._record_audit(
            player,
            experiment,
            "status",
            f"{previous} → {new_status}" + (f" ({outcome})" if outcome else ""),
            {"from": previous, "to": new_status, "outcome": outcome, "note": note},
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(experiment)
        return experiment

    async def add_observation(
        self,
        player: Profile,
        experiment_id: uuid.UUID,
        *,
        note: str,
        on_date: date | None = None,
        metrics: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> Experiment:
        experiment = await self._get_owned(player, experiment_id)
        if experiment.status == STATUS_CONCLUDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot add observations to a concluded experiment.",
            )
        observations = dict(experiment.observations_json or {})
        entries = list(observations.get("entries", []))
        entry = {
            "date": (on_date or date.today()).isoformat(),
            "note": note,
            "metrics": metrics or {},
        }
        entries.append(entry)
        observations["entries"] = entries
        experiment.observations_json = observations
        # JSONB mutation tracking: reassign to ensure the change is flushed.
        self._record_audit(player, experiment, "observation", f"Observation: {note}", entry)
        if commit:
            await self.session.commit()
            await self.session.refresh(experiment)
        return experiment

    def _record_audit(
        self,
        player: Profile,
        experiment: Experiment,
        action: str,
        summary: str,
        detail: dict[str, Any],
    ) -> None:
        self.session.add(
            Analysis(
                user_id=player.id,
                activity_id=None,
                analysis_type=AUDIT_TYPE_EXPERIMENT,
                subject_date=date.today(),
                generated_at_utc=_utcnow(),
                prompt_version=PROMPT_VERSION,
                model_name=None,
                verdict=None,
                context_packet={
                    "experimentId": str(experiment.id),
                    "title": experiment.title,
                    "action": action,
                    "status": experiment.status,
                    "detail": detail,
                },
                output_markdown=f"[{experiment.title}] {summary}",
                raw_response={},
            )
        )
