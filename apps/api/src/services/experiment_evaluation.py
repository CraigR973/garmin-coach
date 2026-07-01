"""Hypothesis evaluation (Batch 22).

Closes the loop on Mark's standing hypotheses (collagen, recovery-week
disruption, 04:00 waking): for each experiment in the Batch 17 tracker (#72) it
gathers the relevant evidence window and computes a *deterministic* before/after
or correlation read — reusing the Batch 17 insights math (``_slope`` / ``pearson``
/ ``compute_drivers``) — then **recommends** a conclusion (``supported`` /
``refuted`` / ``inconclusive``) with its evidence surfaced.

The recommendation is advisory only. Concluding an experiment stays the
human-gated, terminal ``POST /…/status`` action (#72): this engine *never* changes
experiment status. When the evidence window is too thin to judge, the evaluation
skips with an explicit reason (the #71 sample-size gates), never inventing a read.

Three evaluation *kinds*, dispatched by the experiment's ``slug``:

  * **gate** (collagen) — counts the current run of consecutive nights meeting the
    age-adjusted sleep floor; the gate being met is the readiness condition the
    protocol set, so a met gate recommends ``supported``.
  * **correlation** (early_waking_0400) — Pearson-ranks the *measured* candidate
    drivers against an overnight-disruption proxy; a strong correlation recommends
    ``supported`` (an identifiable trigger), no correlation among the measured
    candidates recommends ``refuted``.
  * **group_compare** (recovery_week_disruption) — compares mean age-adjusted sleep
    on recovery-week nights vs build-week nights (labelled from ``plan_blocks``);
    recovery being meaningfully worse recommends ``supported``, better ``refuted``.

User-created experiments without a recognised slug fall back to the correlation
evaluator when they declare ``candidateDrivers``, else report that no automatic
evaluator applies.

Audited in ``analyses`` under ``analysis_type='experiment_evaluation'``, idempotent
per (experiment, subject date). No migration — reuses ``experiments`` / ``analyses``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Analysis,
    Experiment,
    PlanBlock,
    Sleep,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.insights import (
    BEDROOM_DRIVER_KEYS,
    _mean,
    _slope,
    bedroom_driver_values_by_date,
    compute_drivers,
)

PROMPT_VERSION = "experiment-eval:v1"
AUDIT_TYPE_EVALUATION = "experiment_evaluation"

# Recommendations (mirror the tracker's outcome vocabulary, #72).
RECOMMEND_SUPPORTED = "supported"
RECOMMEND_REFUTED = "refuted"
RECOMMEND_INCONCLUSIVE = "inconclusive"

# Evaluation status.
STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_history"
STATUS_NO_EVALUATOR = "no_evaluator"

# Evaluation kinds.
KIND_GATE = "gate"
KIND_CORRELATION = "correlation"
KIND_GROUP_COMPARE = "group_compare"
KIND_NONE = "none"

# Standing-hypothesis slugs (from the Batch 17 tracker).
SLUG_COLLAGEN = "collagen"
SLUG_RECOVERY_WEEK = "recovery_week_disruption"
SLUG_EARLY_WAKING = "early_waking_0400"

# --- gate (collagen) ----------------------------------------------------------
GATE_DEFAULT_NIGHTS = 7
GATE_DEFAULT_FLOOR = 74
GATE_LOOKBACK_DAYS = 60
GATE_MIN_SAMPLES = 5

# --- correlation (early waking) -----------------------------------------------
CORRELATION_LOOKBACK_DAYS = 120
CORRELATION_MIN_SAMPLES = 8
CORRELATION_STRONG_R = 0.5
CORRELATION_MODERATE_R = 0.3
EARLY_WAKING_OUTCOME = "overnight_awake_min"
# Candidate drivers we can actually measure from synced data. The hypothesis also
# names alcohol / late-snack triggers, which are not captured — surfaced as a gap.
EARLY_WAKING_DRIVERS = ("overnight_low_c", "sleep_stress_avg", *BEDROOM_DRIVER_KEYS)
EARLY_WAKING_UNMEASURED = ("alcohol", "late_snack")

# --- group compare (recovery-week disruption) ---------------------------------
GROUP_LOOKBACK_DAYS = 120
GROUP_MIN_PER_GROUP = 4
GROUP_THRESHOLD = 3.0  # age-adjusted sleep points = a meaningful gap


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class EvaluationResult:
    """A deterministic, advisory read of one experiment's evidence window."""

    slug: str | None
    kind: str
    status: str  # ok | insufficient_history | no_evaluator
    recommendation: str | None  # supported | refuted | inconclusive (None unless ok)
    sample_count: int
    window_start: date | None
    window_end: date | None
    evidence: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure evaluators (DB-free, unit-testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SleepNight:
    day: date
    score: float | None


def _qualifying_nights(nights: Sequence[SleepNight]) -> list[SleepNight]:
    return sorted((n for n in nights if n.score is not None), key=lambda n: n.day)


def evaluate_gate_streak(
    nights: Sequence[SleepNight],
    *,
    slug: str | None = SLUG_COLLAGEN,
    gate_nights: int = GATE_DEFAULT_NIGHTS,
    floor: float = GATE_DEFAULT_FLOOR,
    min_samples: int = GATE_MIN_SAMPLES,
) -> EvaluationResult:
    """Collagen: is the consecutive-clean-nights gate currently satisfied?

    The hypothesis gates reintroduction behind ``gate_nights`` consecutive nights at
    or above the age-adjusted ``floor``. The current trailing streak of
    calendar-consecutive qualifying nights is the evidence; a met gate is the
    readiness condition the protocol set, so it recommends ``supported``. The recent
    slope is surfaced so a building (or fading) trend is visible.
    """
    valid = _qualifying_nights(nights)
    if len(valid) < min_samples:
        return EvaluationResult(
            slug=slug,
            kind=KIND_GATE,
            status=STATUS_INSUFFICIENT,
            recommendation=None,
            sample_count=len(valid),
            window_start=valid[0].day if valid else None,
            window_end=valid[-1].day if valid else None,
            reasons=[
                f"Only {len(valid)} scored nights; need ≥{min_samples} to judge the gate.",
            ],
        )

    # Trailing run of consecutive-day nights at/above the floor.
    streak = 0
    prev_day: date | None = None
    for night in reversed(valid):
        if night.score is None or night.score < floor:
            break
        if prev_day is not None and (prev_day - night.day).days != 1:
            break
        streak += 1
        prev_day = night.day

    recent_scores = [n.score for n in valid[-gate_nights:] if n.score is not None]
    slope = _slope(recent_scores)
    gate_met = streak >= gate_nights

    if gate_met:
        recommendation = RECOMMEND_SUPPORTED
        reasons = [
            f"{streak} consecutive nights at or above the age-adjusted floor "
            f"of {floor:g} (gate: {gate_nights}) — the gate is met.",
        ]
    else:
        recommendation = RECOMMEND_INCONCLUSIVE
        reasons = [
            f"Current clean-night streak is {streak} of the {gate_nights} required "
            f"at the {floor:g} floor — gate not yet met.",
        ]
    if slope is not None:
        trend = "rising" if slope > 0 else "falling" if slope < 0 else "flat"
        reasons.append(f"Recent age-adjusted sleep trend is {trend} ({slope:.2f}/night).")

    return EvaluationResult(
        slug=slug,
        kind=KIND_GATE,
        status=STATUS_OK,
        recommendation=recommendation,
        sample_count=len(valid),
        window_start=valid[0].day,
        window_end=valid[-1].day,
        evidence={
            "currentStreak": streak,
            "gateNights": gate_nights,
            "floor": floor,
            "gateMet": gate_met,
            "latestScore": valid[-1].score,
            "recentSlope": round(slope, 4) if slope is not None else None,
        },
        reasons=reasons,
    )


def evaluate_correlation(
    records: Sequence[dict[str, float | None]],
    *,
    outcome_key: str,
    driver_keys: Sequence[str],
    slug: str | None = SLUG_EARLY_WAKING,
    min_samples: int = CORRELATION_MIN_SAMPLES,
    strong_r: float = CORRELATION_STRONG_R,
    moderate_r: float = CORRELATION_MODERATE_R,
    unmeasured: Sequence[str] = (),
) -> EvaluationResult:
    """Early waking: does any *measured* candidate driver track the disruption proxy?

    Reuses ``compute_drivers`` to Pearson-rank the candidate drivers against the
    overnight-disruption outcome over the window. A strong correlation recommends
    ``supported`` (an identifiable trigger); a moderate one is ``inconclusive``; no
    correlation among the measured candidates (with enough pairs) recommends
    ``refuted``. Drivers the hypothesis names but we cannot measure are surfaced as a
    coverage gap rather than silently dropped.
    """
    correlations = compute_drivers(
        records, outcome_key=outcome_key, driver_keys=driver_keys, min_samples=min_samples
    )
    reasons: list[str] = []
    if unmeasured:
        reasons.append(
            "Not measured from synced data: " + ", ".join(unmeasured) + ".",
        )

    if not correlations:
        # No driver cleared the min-sample gate.
        usable = max(
            (
                sum(
                    1
                    for r in records
                    if r.get(driver) is not None and r.get(outcome_key) is not None
                )
                for driver in driver_keys
            ),
            default=0,
        )
        reasons.insert(
            0,
            f"Only {usable} paired nights for the strongest candidate; "
            f"need ≥{min_samples} to correlate.",
        )
        return EvaluationResult(
            slug=slug,
            kind=KIND_CORRELATION,
            status=STATUS_INSUFFICIENT,
            recommendation=None,
            sample_count=usable,
            window_start=None,
            window_end=None,
            evidence={"correlations": []},
            reasons=reasons,
        )

    top = correlations[0]
    abs_r = abs(top.coefficient)
    if abs_r >= strong_r:
        recommendation = RECOMMEND_SUPPORTED
        reasons.insert(
            0,
            f"Strongest measured driver is {top.driver} "
            f"({top.direction}, r={top.coefficient}) — an identifiable trigger.",
        )
    elif abs_r >= moderate_r:
        recommendation = RECOMMEND_INCONCLUSIVE
        reasons.insert(
            0,
            f"Strongest measured driver is {top.driver} (r={top.coefficient}) — "
            f"a weak signal, not conclusive.",
        )
    else:
        recommendation = RECOMMEND_REFUTED
        reasons.insert(
            0,
            f"No measured candidate correlates with overnight disruption "
            f"(strongest r={top.coefficient}) — no identifiable trigger among them.",
        )
    if top.summary:
        reasons.append(top.summary)

    return EvaluationResult(
        slug=slug,
        kind=KIND_CORRELATION,
        status=STATUS_OK,
        recommendation=recommendation,
        sample_count=top.sample_count,
        window_start=None,
        window_end=None,
        evidence={
            "outcome": outcome_key,
            "strongestDriver": top.driver,
            "correlations": [
                {
                    "driver": c.driver,
                    "coefficient": c.coefficient,
                    "direction": c.direction,
                    "sampleCount": c.sample_count,
                    "summary": c.summary,
                }
                for c in correlations
            ],
            "unmeasuredDrivers": list(unmeasured),
        },
        reasons=reasons,
    )


@dataclass(frozen=True)
class LabeledNight:
    day: date
    value: float | None
    group: str  # "recovery" | "build"


def evaluate_group_compare(
    nights: Sequence[LabeledNight],
    *,
    slug: str | None = SLUG_RECOVERY_WEEK,
    min_per_group: int = GROUP_MIN_PER_GROUP,
    threshold: float = GROUP_THRESHOLD,
) -> EvaluationResult:
    """Recovery-week disruption: is sleep worse on recovery-week nights?

    Before/after-style comparison of mean age-adjusted sleep on recovery-week vs
    build-week nights (labelled from ``plan_blocks``). Recovery being meaningfully
    lower than build (by ``threshold`` points) recommends ``supported``; meaningfully
    higher recommends ``refuted``; a gap inside the threshold is ``inconclusive``.
    """
    recovery = [n.value for n in nights if n.group == "recovery" and n.value is not None]
    build = [n.value for n in nights if n.group == "build" and n.value is not None]
    if len(recovery) < min_per_group or len(build) < min_per_group:
        return EvaluationResult(
            slug=slug,
            kind=KIND_GROUP_COMPARE,
            status=STATUS_INSUFFICIENT,
            recommendation=None,
            sample_count=len(recovery) + len(build),
            window_start=None,
            window_end=None,
            evidence={"recoveryNights": len(recovery), "buildNights": len(build)},
            reasons=[
                f"Need ≥{min_per_group} nights in each group; have "
                f"{len(recovery)} recovery / {len(build)} build.",
            ],
        )

    recovery_mean = _mean(recovery)
    build_mean = _mean(build)
    delta = recovery_mean - build_mean  # negative ⇒ recovery weeks worse

    if delta <= -threshold:
        recommendation = RECOMMEND_SUPPORTED
        reasons = [
            f"Recovery-week sleep averages {recovery_mean:.1f} vs {build_mean:.1f} on "
            f"build weeks ({delta:+.1f}) — recovery weeks sleep worse.",
        ]
    elif delta >= threshold:
        recommendation = RECOMMEND_REFUTED
        reasons = [
            f"Recovery-week sleep averages {recovery_mean:.1f} vs {build_mean:.1f} on "
            f"build weeks ({delta:+.1f}) — recovery weeks sleep better, not worse.",
        ]
    else:
        recommendation = RECOMMEND_INCONCLUSIVE
        reasons = [
            f"Recovery vs build sleep differ by only {delta:+.1f} points "
            f"(<{threshold:g}) — no meaningful disruption either way.",
        ]

    return EvaluationResult(
        slug=slug,
        kind=KIND_GROUP_COMPARE,
        status=STATUS_OK,
        recommendation=recommendation,
        sample_count=len(recovery) + len(build),
        window_start=None,
        window_end=None,
        evidence={
            "recoveryMean": round(recovery_mean, 2),
            "buildMean": round(build_mean, 2),
            "delta": round(delta, 2),
            "recoveryNights": len(recovery),
            "buildNights": len(build),
        },
        reasons=reasons,
    )


def _no_evaluator(slug: str | None) -> EvaluationResult:
    return EvaluationResult(
        slug=slug,
        kind=KIND_NONE,
        status=STATUS_NO_EVALUATOR,
        recommendation=None,
        sample_count=0,
        window_start=None,
        window_end=None,
        reasons=[
            "No automatic evaluator applies to this experiment — "
            "conclude it manually from your own observations.",
        ],
    )


# ---------------------------------------------------------------------------
# DB service
# ---------------------------------------------------------------------------


class ExperimentEvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_owned(self, player: Profile, experiment_id: uuid.UUID) -> Experiment:
        from fastapi import HTTPException, status

        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None or experiment.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment not found",
            )
        return experiment

    @staticmethod
    def _slug(experiment: Experiment) -> str | None:
        criteria = experiment.success_criteria_json
        if isinstance(criteria, dict):
            slug = criteria.get("slug")
            if isinstance(slug, str):
                return slug
        return None

    async def evaluate(
        self,
        player: Profile,
        experiment: Experiment,
        *,
        as_of: date | None = None,
    ) -> EvaluationResult:
        """Dispatch to the right deterministic evaluator for ``experiment``."""
        end = as_of or date.today()
        slug = self._slug(experiment)
        criteria = (
            experiment.success_criteria_json
            if isinstance(experiment.success_criteria_json, dict)
            else {}
        )

        if slug == SLUG_COLLAGEN:
            return await self._evaluate_collagen(player, criteria, end=end)
        if slug == SLUG_EARLY_WAKING:
            return await self._evaluate_early_waking(player, end=end)
        if slug == SLUG_RECOVERY_WEEK:
            return await self._evaluate_recovery_week(player, end=end)
        if criteria.get("candidateDrivers"):
            # Generic user-created correlation experiment.
            return await self._evaluate_early_waking(player, end=end, slug=slug)
        return _no_evaluator(slug)

    async def _evaluate_collagen(
        self, player: Profile, criteria: dict[str, Any], *, end: date
    ) -> EvaluationResult:
        start = end - timedelta(days=GATE_LOOKBACK_DAYS)
        rows = await self._sleep_rows(player, start=start, end=end)
        nights = [
            SleepNight(
                day=row.calendar_date,
                score=_age_adjusted(row),
            )
            for row in rows
        ]
        gate_nights = _as_int(criteria.get("gateNights"), GATE_DEFAULT_NIGHTS)
        floor = _as_float(criteria.get("ageAdjustedSleepFloor"), GATE_DEFAULT_FLOOR)
        return evaluate_gate_streak(nights, gate_nights=gate_nights, floor=floor)

    async def _evaluate_early_waking(
        self, player: Profile, *, end: date, slug: str | None = SLUG_EARLY_WAKING
    ) -> EvaluationResult:
        start = end - timedelta(days=CORRELATION_LOOKBACK_DAYS)
        sleeps = await self._sleep_rows(player, start=start, end=end)
        weather = (
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
        weather_by_date = {w.calendar_date: w for w in weather}
        bedroom_by_date = await bedroom_driver_values_by_date(
            self.session, player, start=start, end=end
        )
        records: list[dict[str, float | None]] = []
        for sleep in sleeps:
            weather_row = weather_by_date.get(sleep.calendar_date)
            bedroom = bedroom_by_date.get(sleep.calendar_date)
            records.append(
                {
                    EARLY_WAKING_OUTCOME: (
                        sleep.awake_sleep_sec / 60.0 if sleep.awake_sleep_sec is not None else None
                    ),
                    "overnight_low_c": float(weather_row.overnight_low_c)
                    if weather_row and weather_row.overnight_low_c is not None
                    else None,
                    "sleep_stress_avg": float(sleep.avg_sleep_stress)
                    if sleep.avg_sleep_stress is not None
                    else None,
                    "bedroom_warning_minutes": bedroom.warning_minutes if bedroom else None,
                    "bedroom_critical_minutes": bedroom.critical_minutes if bedroom else None,
                    "bedroom_fan_ran_minutes": bedroom.fan_ran_minutes if bedroom else None,
                    "bedroom_peak_fan_speed": bedroom.peak_fan_speed if bedroom else None,
                }
            )
        return evaluate_correlation(
            records,
            outcome_key=EARLY_WAKING_OUTCOME,
            driver_keys=EARLY_WAKING_DRIVERS,
            slug=slug,
            unmeasured=EARLY_WAKING_UNMEASURED,
        )

    async def _evaluate_recovery_week(self, player: Profile, *, end: date) -> EvaluationResult:
        start = end - timedelta(days=GROUP_LOOKBACK_DAYS)
        sleeps = await self._sleep_rows(player, start=start, end=end)
        blocks = (
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
        nights: list[LabeledNight] = []
        for sleep in sleeps:
            group = _week_group(sleep.calendar_date, blocks)
            if group is None:
                continue
            nights.append(
                LabeledNight(day=sleep.calendar_date, value=_age_adjusted(sleep), group=group)
            )
        return evaluate_group_compare(nights)

    async def _sleep_rows(self, player: Profile, *, start: date, end: date) -> list[Sleep]:
        return list(
            (
                await self.session.execute(
                    select(Sleep)
                    .where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                    .order_by(Sleep.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _existing_evaluation(
        self, player: Profile, experiment_id: uuid.UUID, subject_date: date
    ) -> Analysis | None:
        rows = (
            (
                await self.session.execute(
                    select(Analysis).where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
                        Analysis.subject_date == subject_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        target = str(experiment_id)
        for row in rows:
            packet = row.context_packet
            if isinstance(packet, dict) and packet.get("experimentId") == target:
                return row
        return None

    async def latest_evaluation(self, player: Profile, experiment_id: uuid.UUID) -> Analysis | None:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
                    )
                    .order_by(Analysis.generated_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )
        target = str(experiment_id)
        for row in rows:
            packet = row.context_packet
            if isinstance(packet, dict) and packet.get("experimentId") == target:
                return row
        return None

    async def run(
        self,
        player: Profile,
        experiment_id: uuid.UUID,
        *,
        as_of: date | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> tuple[EvaluationResult, Analysis]:
        """Evaluate an experiment and record the audit, idempotent per subject date.

        Never changes the experiment's status — concluding stays the human-gated,
        terminal ``POST /…/status`` action (#72).
        """
        experiment = await self._get_owned(player, experiment_id)
        subject_date = as_of or date.today()
        existing = await self._existing_evaluation(player, experiment_id, subject_date)
        if existing is not None and not force:
            result = await self.evaluate(player, experiment, as_of=subject_date)
            return result, existing

        result = await self.evaluate(player, experiment, as_of=subject_date)
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=AUDIT_TYPE_EVALUATION,
            subject_date=subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=None,
            verdict=None,
            context_packet=evaluation_packet(experiment, result),
            output_markdown=evaluation_markdown(experiment, result),
            raw_response={},
        )
        self.session.add(analysis)
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        return result, analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _age_adjusted(row: Sleep) -> float | None:
    """Age-adjusted sleep score, falling back to the raw score."""
    if row.age_adjusted_score is not None:
        return float(row.age_adjusted_score)
    if row.score is not None:
        return float(row.score)
    return None


def _week_group(day: date, blocks: Sequence[PlanBlock]) -> str | None:
    """Label a night recovery vs build from the containing plan block, if any."""
    for block in blocks:
        if block.start_date <= day <= block.end_date:
            block_type = (block.block_type or "").lower()
            if "recovery" in block_type or "rest" in block_type or "taper" in block_type:
                return "recovery"
            if "build" in block_type or "base" in block_type:
                return "build"
            return None
    return None


def evaluation_packet(experiment: Experiment, result: EvaluationResult) -> dict[str, Any]:
    return {
        "experimentId": str(experiment.id),
        "title": experiment.title,
        "slug": result.slug,
        "kind": result.kind,
        "status": result.status,
        "recommendation": result.recommendation,
        "sampleCount": result.sample_count,
        "windowStart": result.window_start.isoformat() if result.window_start else None,
        "windowEnd": result.window_end.isoformat() if result.window_end else None,
        "evidence": result.evidence,
        "reasons": result.reasons,
    }


def evaluation_markdown(experiment: Experiment, result: EvaluationResult) -> str:
    head = f"[{experiment.title}] "
    if result.status == STATUS_OK and result.recommendation:
        head += f"recommendation: {result.recommendation}"
    else:
        head += result.status
    body = "\n".join(f"- {reason}" for reason in result.reasons)
    return f"{head}\n{body}" if body else head
