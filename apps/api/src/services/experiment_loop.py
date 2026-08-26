"""Nightly experiment evidence and persisted REM assignments (Batch 221).

The existing experiment evaluators remain the source of recommendations.  This
module supplies the missing evidence journal and the packet/read surfaces:

* one immutable weekly REM assignment records exactly what Mark was shown;
* one source-keyed observation per wake date updates each standing experiment;
* explicit check-in application responses are joined to Garmin REM/awake data;
* current evaluations are recomputed read-only for the morning packet.

Historical nights are not backfilled on the first run because the app did not
record whether an intervention was issued or applied then.  Once the loop starts,
gaps caused by downtime are filled from genuine stored nights.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, Experiment, ManualEntry, PlanBlock, Sleep, WeatherDaily
from src.models.profile import Profile
from src.services.age_norms import rem_sleep_pct_for_row
from src.services.experiment_evaluation import (
    ExperimentEvaluationService,
    evaluation_packet,
)
from src.services.experiment_tracker import (
    SLUG_REM_INTERVENTION,
    STATUS_CONCLUDED,
    ExperimentTrackerService,
)
from src.services.insights import bedroom_driver_values_by_date
from src.services.rem_interventions import REM_LIBRARY, RemRotation, intervention_by_id

ANALYSIS_TYPE_REM_ASSIGNMENT = "rem_intervention_assignment"
PROMPT_VERSION = "experiment-loop:v1-2026-08-24"
SOURCE_NIGHTLY = "nightly_experiment_snapshot"
SOURCE_REM_NIGHT = "rem_intervention_night"

ORIGINAL_STANDING_SLUGS = frozenset({"collagen", "recovery_week_disruption", "early_waking_0400"})
NIGHTLY_SLUGS = frozenset({*ORIGINAL_STANDING_SLUGS, SLUG_REM_INTERVENTION})
RECENT_REPAIR_DAYS = 3


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _week_bounds(as_of: date) -> tuple[date, date]:
    monday = as_of - timedelta(days=as_of.weekday())
    return monday, monday + timedelta(days=6)


def _week_label(as_of: date) -> str:
    iso = as_of.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _assignment_lock_key(user_id: uuid.UUID, period_label: str) -> int:
    """Stable transaction lock for the one immutable assignment per user/week."""
    digest = hashlib.sha256(f"rem-assignment:{user_id}:{period_label}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


@dataclass(frozen=True)
class RemAssignment:
    analysis_id: uuid.UUID
    period_label: str
    window_start: date
    window_end: date
    interventions: tuple[dict[str, str], ...]

    def to_packet(self) -> dict[str, Any]:
        return {
            "assignmentId": str(self.analysis_id),
            "periodLabel": self.period_label,
            "windowStart": self.window_start.isoformat(),
            "windowEnd": self.window_end.isoformat(),
            "interventions": [dict(item) for item in self.interventions],
        }


def rotation_from_assignment(assignment: RemAssignment | None) -> RemRotation | None:
    if assignment is None:
        return None
    return RemRotation(
        period_label=assignment.period_label,
        shown=len(assignment.interventions),
        total=len(REM_LIBRARY),
        intervention_ids=tuple(item["id"] for item in assignment.interventions),
        actions=tuple(item["action"] for item in assignment.interventions),
    )


def _assignment_from_analysis(row: Analysis) -> RemAssignment | None:
    packet = row.context_packet if isinstance(row.context_packet, dict) else {}
    period_label = packet.get("periodLabel")
    raw_start = packet.get("windowStart")
    raw_end = packet.get("windowEnd")
    raw_interventions = packet.get("interventions")
    if (
        not isinstance(period_label, str)
        or not isinstance(raw_start, str)
        or not isinstance(raw_end, str)
    ):
        return None
    if not isinstance(raw_interventions, list):
        return None
    interventions: list[dict[str, str]] = []
    for raw in raw_interventions:
        if not isinstance(raw, dict):
            return None
        intervention_id = raw.get("id")
        action = raw.get("action")
        if not isinstance(intervention_id, str) or not isinstance(action, str):
            return None
        interventions.append({"id": intervention_id, "action": action})
    try:
        return RemAssignment(
            analysis_id=row.id,
            period_label=period_label,
            window_start=date.fromisoformat(raw_start),
            window_end=date.fromisoformat(raw_end),
            interventions=tuple(interventions),
        )
    except ValueError:
        return None


class ExperimentLoopService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_assignment(
        self,
        player: Profile,
        *,
        as_of: date,
        actions: list[str],
        rotation: RemRotation,
        commit: bool = False,
    ) -> RemAssignment | None:
        """Persist the first assignment for a calendar week and never rewrite it."""
        if not actions or len(actions) != len(rotation.intervention_ids):
            return None
        await self.session.scalar(
            select(
                func.pg_advisory_xact_lock(_assignment_lock_key(player.id, rotation.period_label))
            )
        )
        existing = await self.assignment_for_period(player.id, rotation.period_label)
        if existing is not None:
            return existing
        interventions: list[dict[str, str]] = []
        for intervention_id, action in zip(rotation.intervention_ids, actions, strict=True):
            if intervention_by_id(intervention_id) is None:
                return None
            interventions.append({"id": intervention_id, "action": action})
        _, window_end = _week_bounds(as_of)
        # The first assignment in a week only applies from the day it was
        # actually issued. A midweek deploy/open must not ask about an action
        # Mark had not seen before the preceding night.
        window_start = as_of
        packet = {
            "periodLabel": rotation.period_label,
            "windowStart": window_start.isoformat(),
            "windowEnd": window_end.isoformat(),
            "interventions": interventions,
            "issuedFor": "nights_starting_in_window",
            "issuedAtLocalDate": as_of.isoformat(),
            "applicationEvidence": "explicit_next_morning_check_in",
        }
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=ANALYSIS_TYPE_REM_ASSIGNMENT,
            subject_date=window_start,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=None,
            verdict=None,
            context_packet=packet,
            output_markdown=(
                f"REM focus {rotation.period_label}: "
                + "; ".join(item["action"] for item in interventions)
            ),
            raw_response={},
        )
        self.session.add(analysis)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        return _assignment_from_analysis(analysis)

    async def assignment_for_period(
        self,
        user_id: uuid.UUID,
        period_label: str,
    ) -> RemAssignment | None:
        rows = list(
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_REM_ASSIGNMENT,
                        Analysis.context_packet.op("->>")("periodLabel") == period_label,
                    )
                    .order_by(Analysis.generated_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return _assignment_from_analysis(rows[0]) if rows else None

    async def assignment_for_night(
        self,
        user_id: uuid.UUID,
        *,
        wake_date: date,
    ) -> RemAssignment | None:
        """Assignment covering the night before ``wake_date``.

        This explicit night-start calculation is the Monday-boundary guard: a
        Monday check-in reads Sunday's prior assignment, not Monday's new one.
        """
        night_start = wake_date - timedelta(days=1)
        rows = list(
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_REM_ASSIGNMENT,
                        Analysis.subject_date <= night_start,
                    )
                    .order_by(desc(Analysis.subject_date), Analysis.generated_at_utc.asc())
                    .limit(4)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            assignment = _assignment_from_analysis(row)
            if (
                assignment is not None
                and assignment.window_start <= night_start <= assignment.window_end
            ):
                return assignment
        return None

    async def current_assignment(
        self,
        user_id: uuid.UUID,
        *,
        as_of: date,
    ) -> RemAssignment | None:
        return await self.assignment_for_period(user_id, _week_label(as_of))

    async def rem_check_in_packet(
        self,
        player: Profile,
        *,
        wake_date: date,
        manual_entry: ManualEntry | None,
    ) -> dict[str, Any] | None:
        assignment = await self.assignment_for_night(player.id, wake_date=wake_date)
        if assignment is None:
            return None
        feedback = (
            manual_entry.rem_intervention_feedback_json
            if manual_entry is not None
            and isinstance(manual_entry.rem_intervention_feedback_json, dict)
            else {}
        )
        responses = (
            feedback.get("responses")
            if feedback.get("periodLabel") == assignment.period_label
            else []
        )
        response_by_id = (
            {
                response.get("interventionId"): response.get("status")
                for response in responses
                if isinstance(response, dict)
                and isinstance(response.get("interventionId"), str)
                and response.get("status") in {"applied", "not_applied", "unknown"}
            }
            if isinstance(responses, list)
            else {}
        )
        packet = assignment.to_packet()
        packet.update(
            {
                "wakeDate": wake_date.isoformat(),
                "interventions": [
                    {
                        **item,
                        "status": response_by_id.get(item["id"], "unknown"),
                    }
                    for item in packet["interventions"]
                ],
            }
        )
        return packet

    async def record_nightly_observations(
        self,
        player: Profile,
        *,
        subject_date: date,
        commit: bool = False,
    ) -> int:
        tracker = ExperimentTrackerService(self.session)
        await tracker.seed_defaults(player, commit=False)
        await self.session.flush()
        experiments = await tracker.list_experiments(player, seed=False)
        targets: dict[str, Experiment] = {}
        for experiment in experiments:
            criteria = experiment.success_criteria_json
            slug = criteria.get("slug") if isinstance(criteria, dict) else None
            if (
                isinstance(slug, str)
                and slug in NIGHTLY_SLUGS
                and experiment.status != STATUS_CONCLUDED
            ):
                targets[slug] = experiment
        candidate_dates: dict[str, list[date]] = {}
        for slug, experiment in targets.items():
            candidate_dates[slug] = self._candidate_dates(experiment, subject_date=subject_date)
        all_dates = sorted({day for days in candidate_dates.values() for day in days})
        contexts = await self._night_contexts(player, all_dates)
        writes = 0
        for slug, experiment in targets.items():
            observations = dict(experiment.observations_json or {})
            if "nightlyStartedAt" not in observations:
                observations["nightlyStartedAt"] = subject_date.isoformat()
                experiment.observations_json = observations
            for day in candidate_dates[slug]:
                context = contexts.get(day)
                if context is None or context["sleep"] is None:
                    continue
                note, metrics = self._observation(slug, day=day, context=context)
                before = self._entry_for_key(experiment, f"{SOURCE_NIGHTLY}:{slug}:{day}")
                await tracker.upsert_observation(
                    player,
                    experiment.id,
                    observation_key=f"{SOURCE_NIGHTLY}:{slug}:{day}",
                    note=note,
                    on_date=day,
                    metrics=metrics,
                    commit=False,
                )
                after = self._entry_for_key(experiment, f"{SOURCE_NIGHTLY}:{slug}:{day}")
                writes += int(before != after)
        if commit:
            await self.session.commit()
        return writes

    def _candidate_dates(self, experiment: Experiment, *, subject_date: date) -> list[date]:
        observations = (
            experiment.observations_json if isinstance(experiment.observations_json, dict) else {}
        )
        entries = observations.get("entries")
        nightly_dates: list[date] = []
        if isinstance(entries, list):
            for entry in entries:
                metrics = entry.get("metrics") if isinstance(entry, dict) else None
                raw_date = entry.get("date") if isinstance(entry, dict) else None
                if not isinstance(metrics, dict) or metrics.get("source") not in {
                    SOURCE_NIGHTLY,
                    SOURCE_REM_NIGHT,
                }:
                    continue
                if isinstance(raw_date, str):
                    try:
                        nightly_dates.append(date.fromisoformat(raw_date))
                    except ValueError:
                        pass
        raw_started_at = observations.get("nightlyStartedAt")
        try:
            started_at = (
                date.fromisoformat(raw_started_at)
                if isinstance(raw_started_at, str)
                else subject_date
            )
        except ValueError:
            started_at = subject_date
        if not nightly_dates:
            return _dates(started_at, subject_date) if started_at <= subject_date else []
        latest = max(nightly_dates)
        start = latest + timedelta(days=1)
        gap_dates = _dates(start, subject_date) if start <= subject_date else []
        repair_start = max(started_at, subject_date - timedelta(days=RECENT_REPAIR_DAYS))
        return sorted(set(gap_dates + _dates(repair_start, subject_date)))

    async def _night_contexts(
        self,
        player: Profile,
        days: list[date],
    ) -> dict[date, dict[str, Any]]:
        if not days:
            return {}
        start, end = min(days), max(days)
        sleeps = list(
            (
                await self.session.execute(
                    select(Sleep).where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        manuals = list(
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == player.id,
                        ManualEntry.entry_date >= start,
                        ManualEntry.entry_date <= end,
                        ManualEntry.planned_workout_id.is_(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_date, desc(ManualEntry.entry_at_utc))
                )
            )
            .scalars()
            .all()
        )
        blocks = list(
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == player.id,
                        PlanBlock.start_date <= end,
                        PlanBlock.end_date >= start,
                    )
                )
            )
            .scalars()
            .all()
        )
        weather_rows = list(
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == player.id,
                        WeatherDaily.calendar_date >= start,
                        WeatherDaily.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        bedroom = await bedroom_driver_values_by_date(
            self.session,
            player,
            start=start,
            end=end,
        )
        sleep_by_date = {row.calendar_date: row for row in sleeps}
        manual_by_date: dict[date, ManualEntry] = {}
        for row in manuals:
            manual_by_date.setdefault(row.entry_date, row)
        weather_by_date = {row.calendar_date: row for row in weather_rows}
        contexts: dict[date, dict[str, Any]] = {}
        for day in days:
            contexts[day] = {
                "sleep": sleep_by_date.get(day),
                "manual": manual_by_date.get(day),
                "planGroup": _plan_group(day, blocks),
                "weather": weather_by_date.get(day),
                "bedroom": bedroom.get(day),
                "assignment": await self.assignment_for_night(player.id, wake_date=day),
            }
        return contexts

    def _observation(
        self,
        slug: str,
        *,
        day: date,
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        sleep: Sleep = context["sleep"]
        manual: ManualEntry | None = context["manual"]
        age_score = (
            sleep.age_adjusted_score if sleep.age_adjusted_score is not None else sleep.score
        )
        rem_min = sleep.rem_sleep_sec / 60 if sleep.rem_sleep_sec is not None else None
        awake_min = sleep.awake_sleep_sec / 60 if sleep.awake_sleep_sec is not None else None
        # Batch 227: was `rem_sleep_sec / duration_sec`, which made the same
        # night read 16.41% here and 15.55% in the age table — one above the
        # 50–59 band floor and one below it. One definition now, shared with the
        # age comparison and the personal baseline it is read against.
        rem_pct = rem_sleep_pct_for_row(sleep)
        common: dict[str, Any] = {
            "source": SOURCE_NIGHTLY,
            "wakeDate": day.isoformat(),
            "sleepScore": sleep.score,
            "ageAdjustedSleepScore": age_score,
            "remMin": round(rem_min, 1) if rem_min is not None else None,
            "remSleepPct": round(rem_pct, 2) if rem_pct is not None else None,
            "awakeMin": round(awake_min, 1) if awake_min is not None else None,
        }
        if slug == "collagen":
            supplements = manual.supplements_json if manual is not None else {}
            return (
                f"Age-adjusted sleep {age_score if age_score is not None else 'not measured'}.",
                {
                    **common,
                    "gateFloor": 74,
                    "meetsGateFloor": age_score is not None and age_score >= 74,
                    "supplementsReported": supplements,
                },
            )
        if slug == "recovery_week_disruption":
            group = context["planGroup"]
            return (
                f"{group or 'Unclassified'} block night; age-adjusted sleep "
                f"{age_score if age_score is not None else 'not measured'}.",
                {**common, "planBlockGroup": group},
            )
        if slug == "early_waking_0400":
            weather: WeatherDaily | None = context["weather"]
            bedroom = context["bedroom"]
            setup = manual.sleep_setup_json if manual is not None else {}
            return (
                "Overnight awake time "
                f"{round(awake_min, 1) if awake_min is not None else 'not measured'} min.",
                {
                    **common,
                    "sleepStressAvg": sleep.avg_sleep_stress,
                    "overnightLowC": weather.overnight_low_c if weather is not None else None,
                    "bedroomMeanTempC": bedroom.mean_temp_c if bedroom is not None else None,
                    "bedroomMinTempC": bedroom.min_temp_c if bedroom is not None else None,
                    "bedroomMaxTempC": bedroom.max_temp_c if bedroom is not None else None,
                    "sleepSetup": setup,
                },
            )
        assignment: RemAssignment | None = context["assignment"]
        feedback = (
            manual.rem_intervention_feedback_json
            if manual is not None and isinstance(manual.rem_intervention_feedback_json, dict)
            else {}
        )
        responses = _validated_responses(feedback, assignment)
        common["source"] = SOURCE_REM_NIGHT
        common.update(
            {
                "assignmentId": str(assignment.analysis_id) if assignment is not None else None,
                "periodLabel": assignment.period_label if assignment is not None else None,
                "issuedInterventions": (
                    [dict(item) for item in assignment.interventions]
                    if assignment is not None
                    else []
                ),
                "responses": responses,
            }
        )
        return (
            f"REM {round(rem_pct, 1) if rem_pct is not None else 'not measured'}%; "
            f"{len([row for row in responses if row['status'] != 'unknown'])} application "
            "responses recorded.",
            common,
        )

    @staticmethod
    def _entry_for_key(experiment: Experiment, observation_key: str) -> dict[str, Any] | None:
        observations = (
            experiment.observations_json if isinstance(experiment.observations_json, dict) else {}
        )
        entries = observations.get("entries")
        if not isinstance(entries, list):
            return None
        return next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict)
                and isinstance(entry.get("metrics"), dict)
                and entry["metrics"].get("observationKey") == observation_key
            ),
            None,
        )

    async def packet(self, player: Profile, *, subject_date: date) -> dict[str, Any]:
        tracker = ExperimentTrackerService(self.session)
        experiments = await tracker.list_experiments(player, seed=False)
        evaluator = ExperimentEvaluationService(self.session)
        rows: list[dict[str, Any]] = []
        for experiment in experiments:
            result = await evaluator.evaluate(player, experiment, as_of=subject_date)
            stored = await evaluator.latest_evaluation(player, experiment.id)
            observations = (
                experiment.observations_json
                if isinstance(experiment.observations_json, dict)
                else {}
            )
            raw_entries = observations.get("entries")
            entries = raw_entries if isinstance(raw_entries, list) else []
            rows.append(
                {
                    "id": str(experiment.id),
                    "title": experiment.title,
                    "hypothesis": experiment.hypothesis,
                    "status": experiment.status,
                    "outcome": observations.get("outcome"),
                    "observationCount": len(entries),
                    "latestObservation": entries[-1] if entries else None,
                    "evaluation": evaluation_packet(experiment, result),
                    "latestStoredEvaluation": (
                        {
                            "analysisId": str(stored.id),
                            "subjectDate": stored.subject_date.isoformat(),
                            "generatedAtUtc": stored.generated_at_utc.isoformat() + "Z",
                        }
                        if stored is not None
                        else None
                    ),
                    "conclusion": "human_gated_terminal",
                }
            )
        current = await self.current_assignment(player.id, as_of=subject_date)
        return {
            "asOfDate": subject_date.isoformat(),
            "experiments": rows,
            "currentRemAssignment": current.to_packet() if current is not None else None,
            "rules": {
                "autoConclude": False,
                "unknownApplicationMeansNotApplied": False,
                "derivableSleepOutcomesNeedUserObservation": False,
            },
        }


def _plan_group(day: date, blocks: list[PlanBlock]) -> str | None:
    for block in blocks:
        if block.start_date <= day <= block.end_date:
            block_type = (block.block_type or "").lower()
            if any(token in block_type for token in ("recovery", "rest", "taper")):
                return "recovery"
            if any(token in block_type for token in ("build", "base")):
                return "build"
            return None
    return None


def _validated_responses(
    feedback: dict[str, Any],
    assignment: RemAssignment | None,
) -> list[dict[str, str]]:
    if assignment is None or feedback.get("periodLabel") != assignment.period_label:
        return []
    allowed = {item["id"] for item in assignment.interventions}
    raw_responses = feedback.get("responses")
    if not isinstance(raw_responses, list):
        return []
    by_id: dict[str, str] = {}
    for raw in raw_responses:
        if not isinstance(raw, dict):
            continue
        intervention_id = raw.get("interventionId")
        status = raw.get("status")
        if intervention_id in allowed and status in {"applied", "not_applied", "unknown"}:
            by_id[str(intervention_id)] = str(status)
    return [
        {"interventionId": item["id"], "status": by_id.get(item["id"], "unknown")}
        for item in assignment.interventions
    ]
