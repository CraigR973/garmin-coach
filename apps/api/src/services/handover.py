"""Auto-generated handover-doc export (Batch 23 — the v3 capstone).

Fulfils the product thesis (#13): Mark used to *hand-write* a "handover doc" to
brief an AI on the context it keeps forgetting. This batch makes the app generate
that doc from the living state it already holds, so he never writes one by hand
again. It is the integrative capstone — it summarises the output of every batch
before it.

Following the v3 boundary rule (DECISIONS #81/#82) it splits into a
*deterministic* half and an *optional narrative* half:

  * **23.1 Deterministic assembler.** ``build_handover_packet`` composes the full
    retained state — knowledge base (profile, data-quality rules, age-adjustment,
    sleep protocol, hypotheses, plan context), current plan/block, baselines,
    recent reviews (Batch 20), seasonal/YoY trends (Batch 21), experiments + their
    evaluations (Batch 22), and the strength brief (Batch 19) — into one
    inspectable packet. It is a pure function over plain values, so the assembly is
    reproducible and unit-testable without a database.

  * **23.3 / 23.4 Portable, faithful export.** ``render_handover_markdown`` renders
    that packet into a portable markdown handover doc *deterministically* — no
    model, no API key — so the export always works and faithfully reflects current
    retained state (the round-trip guarantee). This is what the PWA downloads.

  * **23.2 Optional narrative.** ``HandoverService.run`` polishes the doc through
    the thin Anthropic Messages boundary reused from Batch 20 (#47) — ``prompt_version``
    / ``model_name`` / raw response + markdown stored in ``analyses`` under
    ``analysis_type='handover_export'``. The boundary is fakeable in tests without
    ``ANTHROPIC_API_KEY``; when no key is configured the deterministic export still
    stands on its own.

Following #71 the engine is human/API-triggered: ``preview`` assembles the packet
and never writes; ``run`` generates the narrative and records it, idempotent per
day. The data-quality guardrails (no L/R balance, SpO2/HRV reliability window,
wrist-HR strength excluded from recovery, ignore the broken Duration column) are
carried in the packet and reinforced in the system prompt. No new migration —
outputs land in the existing ``analyses`` table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Analysis,
    KnowledgeBase,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
)
from src.models.profile import Profile
from src.services.experiment_evaluation import ExperimentEvaluationService
from src.services.experiment_tracker import ExperimentTrackerService
from src.services.reviews import (
    ANALYSIS_TYPE_MONTHLY,
    ANALYSIS_TYPE_WEEKLY,
    AnthropicReviewClient,
    ReviewClient,
    ReviewError,
)
from src.services.strength_brief import StrengthBriefResult, StrengthBriefService
from src.services.trends import (
    BUCKET_SEASON,
    TrendsService,
    year_on_year_json,
)

PROMPT_VERSION = "handover-v1-2026-06-23"
PACKET_VERSION = 1
ANALYSIS_TYPE_HANDOVER = "handover_export"

# Knowledge-base sections that make up the living handover context, in the order
# Mark's hand-written doc presented them (ARCHITECTURE §3).
HANDOVER_KB_SECTIONS: tuple[str, ...] = (
    "profile",
    "data_quality_rules",
    "age_adjustment",
    "sleep_protocol",
    "training_plan",
    "active_hypotheses",
)

# How far ahead to summarise the active plan slate.
PLAN_LOOKAHEAD_DAYS = 21

HANDOVER_SYSTEM_PROMPT = """You are Garmin Coach, writing the portable "handover \
document" Mark used to hand-write to brief another AI coach.
Use ONLY the supplied deterministic handover packet — it is the single source of \
truth for his retained state. Reproduce his context faithfully: the athlete \
profile, the data-quality rules the AI MUST obey, age-adjustment, the sleep \
protocol and thresholds, the current training block and plan, the metric \
baselines, recent reviews, seasonal/year-on-year trends, the tracked hypotheses \
and their latest evaluations, and the strength watching-brief. Write clean, \
well-structured markdown a fresh AI could read cold and immediately coach from. \
Never mention left/right power balance. Treat SpO2/HRV before the reliability \
cutoff and wrist-HR strength (excluded from recovery) per the rules. Do not \
invent numbers that are not in the packet; where data is missing, say so plainly."""


class HandoverError(RuntimeError):
    """Raised when a handover narrative cannot be generated."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Plain inputs (no DB dependency → pure-testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanSummary:
    block_name: str | None
    block_type: str | None
    block_start: date | None
    block_end: date | None
    sequence_index: int | None
    upcoming_count: int
    upcoming: list[dict[str, Any]]


@dataclass(frozen=True)
class BaselineSummary:
    metric_key: str
    metric_label: str
    sample_count: int
    excluded_sample_count: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True)
class ReviewSummary:
    analysis_type: str
    subject_date: date
    generated_at_utc: datetime
    model_name: str | None
    excerpt: str


@dataclass(frozen=True)
class ExperimentSummary:
    title: str
    hypothesis: str
    status: str
    slug: str | None
    evaluation_status: str
    recommendation: str | None
    reasons: list[str]


# ---------------------------------------------------------------------------
# 23.1 — Deterministic packet assembler (pure)
# ---------------------------------------------------------------------------


def build_handover_packet(
    *,
    display_name: str,
    user_id: str,
    timezone: str,
    generated_at: datetime,
    knowledge_base: Mapping[str, Any],
    plan: PlanSummary,
    baselines: Sequence[BaselineSummary],
    reviews: Sequence[ReviewSummary],
    trends: Mapping[str, Any],
    experiments: Sequence[ExperimentSummary],
    strength: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose the full retained state into one inspectable handover packet.

    Pure function over plain values — no DB, no LLM — so the assembly is
    reproducible and unit-testable. The data-quality rules ride in
    ``knowledgeBase.data_quality_rules`` and are echoed under
    ``dataQualityGuardrails`` so a consumer cannot miss them.
    """
    kb = {
        section: knowledge_base[section]
        for section in HANDOVER_KB_SECTIONS
        if section in knowledge_base
    }
    guardrails = _guardrails_from_kb(knowledge_base)
    return {
        "packetType": "handover_export",
        "packetVersion": PACKET_VERSION,
        "generatedAtUtc": generated_at.replace(microsecond=0).isoformat() + "Z",
        "profile": {
            "userId": user_id,
            "displayName": display_name,
            "timezone": timezone,
        },
        "knowledgeBase": kb,
        "dataQualityGuardrails": guardrails,
        "plan": {
            "blockName": plan.block_name,
            "blockType": plan.block_type,
            "blockStart": plan.block_start.isoformat() if plan.block_start else None,
            "blockEnd": plan.block_end.isoformat() if plan.block_end else None,
            "sequenceIndex": plan.sequence_index,
            "upcomingCount": plan.upcoming_count,
            "upcoming": list(plan.upcoming),
        },
        "baselines": [
            {
                "metricKey": b.metric_key,
                "metricLabel": b.metric_label,
                "sampleCount": b.sample_count,
                "excludedSampleCount": b.excluded_sample_count,
                "mean": b.mean,
                "median": b.median,
                "min": b.minimum,
                "max": b.maximum,
            }
            for b in baselines
        ],
        "recentReviews": [
            {
                "type": r.analysis_type,
                "subjectDate": r.subject_date.isoformat(),
                "generatedAtUtc": r.generated_at_utc.replace(microsecond=0).isoformat() + "Z",
                "modelName": r.model_name,
                "excerpt": r.excerpt,
            }
            for r in reviews
        ],
        "trends": dict(trends),
        "experiments": [
            {
                "title": e.title,
                "hypothesis": e.hypothesis,
                "status": e.status,
                "slug": e.slug,
                "evaluationStatus": e.evaluation_status,
                "recommendation": e.recommendation,
                "reasons": list(e.reasons),
            }
            for e in experiments
        ],
        "strengthBrief": dict(strength),
        "prompt": {
            "version": PROMPT_VERSION,
            "system": HANDOVER_SYSTEM_PROMPT,
            "outputRules": [
                "reproduce_retained_state_faithfully",
                "carry_every_data_quality_rule",
                "never_reference_left_right_power_balance",
                "exclude_pre_cutoff_spo2_and_hrv",
                "exclude_wrist_hr_strength_from_recovery",
                "ignore_broken_sleep_duration_column",
                "do_not_invent_missing_numbers",
            ],
        },
    }


def _guardrails_from_kb(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules")
    if isinstance(section, dict):
        rules = section.get("rules")
        if isinstance(rules, list):
            return [rule for rule in rules if isinstance(rule, dict)]
    return []


# ---------------------------------------------------------------------------
# 23.3 / 23.4 — Deterministic markdown render (pure, faithful, no model)
# ---------------------------------------------------------------------------


def render_handover_markdown(packet: Mapping[str, Any]) -> str:
    """Render the assembled packet into a portable markdown handover doc.

    Deterministic — no model, no API key — so the export always works and
    faithfully reflects the packet (the #13 round-trip guarantee). The narrative
    ``run`` is an optional polish on top; this render is the floor.
    """
    profile = packet.get("profile", {})
    lines: list[str] = []
    lines.append("# Garmin Coach — Handover Document")
    name = profile.get("displayName", "Athlete")
    generated = packet.get("generatedAtUtc", "")
    lines.append("")
    lines.append(f"_Auto-generated retained-state briefing for **{name}** — {generated}._")
    lines.append("")
    lines.append(
        "This document is the living context the coach holds, exported so it can "
        "brief another AI without rewriting it by hand."
    )

    kb = packet.get("knowledgeBase", {})

    _render_profile(lines, kb.get("profile"))
    _render_data_quality(lines, packet.get("dataQualityGuardrails", []))
    _render_age_adjustment(lines, kb.get("age_adjustment"))
    _render_sleep_protocol(lines, kb.get("sleep_protocol"))
    _render_plan(lines, packet.get("plan", {}), kb.get("training_plan"))
    _render_baselines(lines, packet.get("baselines", []))
    _render_hypotheses(lines, kb.get("active_hypotheses"), packet.get("experiments", []))
    _render_reviews(lines, packet.get("recentReviews", []))
    _render_trends(lines, packet.get("trends", {}))
    _render_strength(lines, packet.get("strengthBrief", {}))

    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _heading(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def _render_profile(lines: list[str], profile: Any) -> None:
    _heading(lines, "Athlete profile")
    if not isinstance(profile, dict) or not profile:
        lines.append("_No profile on record._")
        return
    label_map = {
        "athleteName": "Name",
        "age": "Age",
        "ftpWatts": "FTP (W)",
        "vo2max": "VO2 max",
        "restingHeartRateBpm": "Resting HR (bpm)",
        "fitnessAge": "Fitness age",
    }
    for key, label in label_map.items():
        if key in profile:
            lines.append(f"- **{label}:** {profile[key]}")
    band = profile.get("hrvBandMs")
    if isinstance(band, dict) and "low" in band and "high" in band:
        lines.append(f"- **HRV band (ms):** {band['low']}–{band['high']}")
    bp = profile.get("bloodPressure")
    if isinstance(bp, dict) and "systolic" in bp and "diastolic" in bp:
        lines.append(f"- **Blood pressure:** {bp['systolic']}/{bp['diastolic']}")


def _render_data_quality(lines: list[str], rules: Any) -> None:
    _heading(lines, "Data-quality rules (the AI MUST obey)")
    if not isinstance(rules, list) or not rules:
        lines.append("_No data-quality rules on record._")
        return
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        summary = rule.get("summary", "")
        reason = rule.get("reason")
        line = f"- **{summary}**"
        if reason:
            line += f" — {reason}"
        lines.append(line)


def _render_age_adjustment(lines: list[str], content: Any) -> None:
    _heading(lines, "Age-adjustment")
    if not isinstance(content, dict) or not content:
        lines.append("_No age-adjustment on record._")
        return
    delta = content.get("sleepScoreDelta")
    if delta is not None:
        lines.append(f"- **Sleep-score delta:** +{delta}")
    rem = content.get("targetRemMinutes")
    if isinstance(rem, dict) and "low" in rem and "high" in rem:
        lines.append(f"- **Age-appropriate REM (min):** {rem['low']}–{rem['high']}")
    for note in content.get("notes", []) or []:
        lines.append(f"- {note}")


def _render_sleep_protocol(lines: list[str], content: Any) -> None:
    _heading(lines, "Sleep protocol & thresholds")
    if not isinstance(content, dict) or not content:
        lines.append("_No sleep protocol on record._")
        return
    rows = {
        "preCoolTemperatureC": "Pre-cool to (°C)",
        "sealTargetTime": "Seal by",
        "coherenceBreathingTime": "Coherence breathing",
        "bedtime": "Bedtime",
        "latestSnackTime": "Latest snack",
    }
    for key, label in rows.items():
        if key in content:
            lines.append(f"- **{label}:** {content[key]}")
    threshold = content.get("thermalDisruptionThresholdC")
    if isinstance(threshold, dict) and "low" in threshold and "high" in threshold:
        lines.append(f"- **Thermal-disruption peak (°C):** {threshold['low']}–{threshold['high']}")


def _render_plan(lines: list[str], plan: Mapping[str, Any], training_plan: Any) -> None:
    _heading(lines, "Current training plan")
    block_name = plan.get("blockName")
    if block_name:
        block_type = plan.get("blockType")
        suffix = f" ({block_type})" if block_type else ""
        lines.append(f"- **Active block:** {block_name}{suffix}")
        start = plan.get("blockStart")
        end = plan.get("blockEnd")
        if start and end:
            lines.append(f"- **Block window:** {start} → {end}")
    else:
        lines.append("- **Active block:** _none recorded_")
    if isinstance(training_plan, dict):
        framework = training_plan.get("framework")
        if framework:
            lines.append(f"- **Framework:** {framework}")
    upcoming = plan.get("upcoming") or []
    lines.append(f"- **Upcoming sessions ({plan.get('upcomingCount', 0)}):**")
    if upcoming:
        for item in upcoming:
            if not isinstance(item, dict):
                continue
            lines.append(f"  - {item.get('date')}: {item.get('title')} ({item.get('workoutType')})")
    else:
        lines.append("  - _none scheduled in the lookahead window_")


def _render_baselines(lines: list[str], baselines: Any) -> None:
    _heading(lines, "Metric baselines")
    if not isinstance(baselines, list) or not baselines:
        lines.append("_No baselines computed yet._")
        return
    lines.append("| Metric | Mean | Median | Min | Max | n |")
    lines.append("|---|---|---|---|---|---|")
    for b in baselines:
        if not isinstance(b, dict):
            continue
        lines.append(
            f"| {b.get('metricLabel', b.get('metricKey'))} "
            f"| {_num(b.get('mean'))} | {_num(b.get('median'))} "
            f"| {_num(b.get('min'))} | {_num(b.get('max'))} "
            f"| {b.get('sampleCount', 0)} |"
        )


def _render_hypotheses(lines: list[str], kb_hypotheses: Any, experiments: Any) -> None:
    _heading(lines, "Active hypotheses")
    rendered_any = False
    if isinstance(kb_hypotheses, dict):
        for hyp in kb_hypotheses.get("hypotheses", []) or []:
            if not isinstance(hyp, dict):
                continue
            rendered_any = True
            title = hyp.get("title", "Hypothesis")
            status = hyp.get("status")
            rule = hyp.get("rule")
            line = f"- **{title}**"
            if status:
                line += f" _(status: {status})_"
            if rule:
                line += f" — {rule}"
            lines.append(line)
    # Layer in the data-driven evaluation recommendations (Batch 22).
    if isinstance(experiments, list):
        for exp in experiments:
            if not isinstance(exp, dict):
                continue
            rec = exp.get("recommendation")
            eval_status = exp.get("evaluationStatus")
            if rec:
                rendered_any = True
                lines.append(
                    f"  - _Latest evaluation of '{exp.get('title')}': **{rec}** ({eval_status})_"
                )
            elif eval_status and eval_status not in ("no_evaluator",):
                rendered_any = True
                lines.append(f"  - _Latest evaluation of '{exp.get('title')}': {eval_status}_")
    if not rendered_any:
        lines.append("_No hypotheses on record._")


def _render_reviews(lines: list[str], reviews: Any) -> None:
    _heading(lines, "Recent reviews")
    if not isinstance(reviews, list) or not reviews:
        lines.append("_No reviews generated yet._")
        return
    for r in reviews:
        if not isinstance(r, dict):
            continue
        kind = r.get("type", "").replace("_", " ")
        lines.append(f"- **{kind}** ({r.get('subjectDate')})")
        excerpt = r.get("excerpt")
        if excerpt:
            lines.append(f"  - {excerpt}")


def _render_trends(lines: list[str], trends: Mapping[str, Any]) -> None:
    _heading(lines, "Seasonal & year-on-year")
    yoy = trends.get("yearOnYear") if isinstance(trends, dict) else None
    if isinstance(yoy, dict):
        status = yoy.get("status")
        lines.append(f"- **Year-on-year status:** {status}")
        for reason in yoy.get("reasons", []) or []:
            lines.append(f"  - {reason}")
        for metric in yoy.get("metrics", []) or []:
            if isinstance(metric, dict) and metric.get("status") == "ok":
                lines.append(
                    f"  - {metric.get('label')}: {metric.get('currentMean')} "
                    f"vs {metric.get('priorMean')} ({_signed(metric.get('delta'))})"
                )
    else:
        lines.append("_No trend data yet._")


def _render_strength(lines: list[str], strength: Mapping[str, Any]) -> None:
    _heading(lines, "Strength watching-brief")
    if not strength:
        lines.append("_No strength data yet._")
        return
    lines.append(f"- **Trend:** {strength.get('trend', 'unknown')}")
    reason = strength.get("trendReason")
    if reason:
        lines.append(f"  - {reason}")
    lines.append(
        f"- **Sessions:** {strength.get('sessions4w', 0)} in last 4w "
        f"({strength.get('sessionsPerWeek4w', 0)}/wk), "
        f"{strength.get('sessions12w', 0)} in last 12w"
    )
    lines.append(
        "- _Advisory only — wrist-HR strength stays excluded from recovery/verdict "
        "decisions (#49)._"
    )


def _num(value: Any) -> str:
    return "—" if value is None else f"{value}"


def _signed(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:+g}" if isinstance(value, (int, float)) else f"{value}"


# ---------------------------------------------------------------------------
# Service result wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoverPreview:
    subject_date: date
    packet: dict[str, Any]
    markdown: str
    latest_export: Analysis | None


@dataclass(frozen=True)
class HandoverRunResult:
    preview: HandoverPreview
    export: Analysis
    generated: bool


# ---------------------------------------------------------------------------
# DB service
# ---------------------------------------------------------------------------


class HandoverService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def preview(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
    ) -> HandoverPreview:
        """Assemble the deterministic packet + markdown. Never writes (#71)."""
        subject_date = as_of or date.today()

        knowledge_base = await self._knowledge_base(player.id)
        plan = await self._plan_summary(player.id, subject_date)
        baselines = await self._baselines(player.id)
        reviews = await self._recent_reviews(player.id)
        trends = await self._trends(player, as_of=subject_date)
        experiments = await self._experiments(player, as_of=subject_date)
        strength = await self._strength(player, as_of=subject_date)

        packet = build_handover_packet(
            display_name=player.display_name,
            user_id=str(player.id),
            timezone=player.timezone,
            generated_at=_utcnow(),
            knowledge_base=knowledge_base,
            plan=plan,
            baselines=baselines,
            reviews=reviews,
            trends=trends,
            experiments=experiments,
            strength=strength,
        )
        markdown = render_handover_markdown(packet)
        latest = await self.latest_export(player.id, subject_date)
        return HandoverPreview(
            subject_date=subject_date,
            packet=packet,
            markdown=markdown,
            latest_export=latest,
        )

    async def run(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        client: ReviewClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> HandoverRunResult:
        """Generate the narrative handover and store it. Idempotent per day (#71)."""
        preview = await self.preview(player, as_of=as_of)
        if not force and preview.latest_export is not None:
            return HandoverRunResult(preview=preview, export=preview.latest_export, generated=False)

        user_prompt = build_handover_user_prompt(preview.packet)
        review_client = client or AnthropicReviewClient(system_prompt=HANDOVER_SYSTEM_PROMPT)
        try:
            generation = await review_client.generate(
                context_packet=preview.packet,
                user_prompt=user_prompt,
            )
        except ReviewError as exc:  # re-surface under the batch's own error type
            raise HandoverError(str(exc)) from exc

        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=ANALYSIS_TYPE_HANDOVER,
            subject_date=preview.subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=generation.model_name,
            verdict=None,
            context_packet=preview.packet,
            output_markdown=generation.output_markdown,
            raw_response=generation.raw_response,
        )
        self.session.add(analysis)
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        else:
            await self.session.flush()
        return HandoverRunResult(preview=preview, export=analysis, generated=True)

    async def latest_export(self, user_id: uuid.UUID, subject_date: date) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == ANALYSIS_TYPE_HANDOVER,
                    Analysis.subject_date == subject_date,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    # -- state gathering ----------------------------------------------------

    async def _knowledge_base(self, user_id: uuid.UUID) -> dict[str, Any]:
        rows = (
            (
                await self.session.execute(
                    select(KnowledgeBase).where(
                        KnowledgeBase.user_id == user_id,
                        KnowledgeBase.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.section: row.content for row in rows if isinstance(row.content, dict)}

    async def _plan_summary(self, user_id: uuid.UUID, as_of: date) -> PlanSummary:
        block = await self.session.scalar(
            select(PlanBlock)
            .where(
                PlanBlock.user_id == user_id,
                PlanBlock.start_date <= as_of,
                PlanBlock.end_date >= as_of,
            )
            .order_by(desc(PlanBlock.version))
            .limit(1)
        )
        lookahead_end = as_of + timedelta(days=PLAN_LOOKAHEAD_DAYS)
        workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= as_of,
                        PlannedWorkout.workout_date <= lookahead_end,
                    )
                    .order_by(PlannedWorkout.workout_date.asc())
                )
            )
            .scalars()
            .all()
        )
        upcoming = [
            {
                "date": w.workout_date.isoformat(),
                "title": w.title,
                "workoutType": w.workout_type,
            }
            for w in workouts
        ]
        return PlanSummary(
            block_name=block.name if block else None,
            block_type=block.block_type if block else None,
            block_start=block.start_date if block else None,
            block_end=block.end_date if block else None,
            sequence_index=block.sequence_index if block else None,
            upcoming_count=len(upcoming),
            upcoming=upcoming[:10],
        )

    async def _baselines(self, user_id: uuid.UUID) -> list[BaselineSummary]:
        rows = (
            (
                await self.session.execute(
                    select(MetricBaseline)
                    .where(MetricBaseline.user_id == user_id)
                    .order_by(MetricBaseline.metric_key.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            BaselineSummary(
                metric_key=row.metric_key,
                metric_label=row.metric_label,
                sample_count=row.sample_count,
                excluded_sample_count=row.excluded_sample_count,
                mean=row.mean_value,
                median=row.median_value,
                minimum=row.min_value,
                maximum=row.max_value,
            )
            for row in rows
        ]

    async def _recent_reviews(self, user_id: uuid.UUID) -> list[ReviewSummary]:
        summaries: list[ReviewSummary] = []
        for analysis_type in (ANALYSIS_TYPE_WEEKLY, ANALYSIS_TYPE_MONTHLY):
            row = await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == analysis_type,
                )
                .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                .limit(1)
            )
            if row is not None:
                summaries.append(
                    ReviewSummary(
                        analysis_type=row.analysis_type,
                        subject_date=row.subject_date,
                        generated_at_utc=row.generated_at_utc,
                        model_name=row.model_name,
                        excerpt=_excerpt(row.output_markdown),
                    )
                )
        return summaries

    async def _trends(self, player: Profile, *, as_of: date) -> dict[str, Any]:
        service = TrendsService(self.session)
        comparison = await service.year_on_year(player, bucket=BUCKET_SEASON, as_of=as_of)
        return {"bucket": BUCKET_SEASON, "yearOnYear": year_on_year_json(comparison)}

    async def _experiments(self, player: Profile, *, as_of: date) -> list[ExperimentSummary]:
        # seed=False: a GET-side preview must not write (#71). The standing
        # hypotheses also ride in the KB ``active_hypotheses`` section, so the
        # handover stays faithful even before the experiment tracker is seeded.
        tracker = ExperimentTrackerService(self.session)
        experiments = await tracker.list_experiments(player, seed=False)
        evaluator = ExperimentEvaluationService(self.session)
        summaries: list[ExperimentSummary] = []
        for experiment in experiments:
            result = await evaluator.evaluate(player, experiment, as_of=as_of)
            slug = (
                experiment.success_criteria_json.get("slug")
                if isinstance(experiment.success_criteria_json, dict)
                else None
            )
            summaries.append(
                ExperimentSummary(
                    title=experiment.title,
                    hypothesis=experiment.hypothesis,
                    status=experiment.status,
                    slug=slug if isinstance(slug, str) else None,
                    evaluation_status=result.status,
                    recommendation=result.recommendation,
                    reasons=result.reasons,
                )
            )
        return summaries

    async def _strength(self, player: Profile, *, as_of: date) -> dict[str, Any]:
        brief = await StrengthBriefService(self.session).brief(player, as_of=as_of)
        return _strength_packet(brief)


# ---------------------------------------------------------------------------
# Packet helpers
# ---------------------------------------------------------------------------


def _strength_packet(strength: StrengthBriefResult) -> dict[str, Any]:
    return {
        "trend": strength.trend,
        "trendReason": strength.trend_reason,
        "sessions4w": strength.window_4w.session_count,
        "sessionsPerWeek4w": strength.window_4w.sessions_per_week,
        "sessions12w": strength.window_12w.session_count,
    }


def _excerpt(markdown: str, *, limit: int = 280) -> str:
    text = " ".join(markdown.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_handover_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Write Mark's portable handover document from this deterministic packet of "
        "his retained state.\n\n"
        "Handover packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )
