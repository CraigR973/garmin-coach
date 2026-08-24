"""Morning analysis context assembly, verdict rules, and Claude boundary."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.age_norms import build_age_comparison
from src.services.anthropic_text import generate_anthropic_text
from src.services.bedroom_overnight import night_window
from src.services.body_metrics import resolve_effective_vo2max, resolve_effective_weight_kg
from src.services.breathwork_brief import BreathworkBriefResult, BreathworkBriefService
from src.services.chronic_patterns import (
    CHRONIC_DELOAD_WINDOW_DAYS,
    ChronicPatternSuggestionService,
)
from src.services.coach_policy import source_basis
from src.services.coaching_state import CoachingStateService
from src.services.daily_metric_coverage import (
    complete_body_battery_charged,
    complete_body_battery_drained,
    complete_body_battery_end,
    complete_stress_avg,
    coverage_packet,
    daily_aggregate_coverage,
)
from src.services.daily_metric_phase import (
    morning_first_order,
    prefer_morning,
    settled_first_order,
)
from src.services.feedback import FeedbackService
from src.services.generation_requests import (
    claim_generation_request,
    manual_entry_generation_version,
    morning_generation_identity,
    stamp_generation_identity,
)
from src.services.holiday_pause import (
    HolidayPauseService,
    HolidayWindow,
    holiday_windows_covering_date,
)
from src.services.learned_context import (
    LEARNED_CONTEXT_PROMPT_GUARDRAIL,
    learned_context_packet,
)
from src.services.personal_baselines import (
    SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
    baseline_band_packet,
    baseline_center,
    baseline_lookup,
    effective_readiness_floor,
    metric_within_baseline_band,
    readiness_baseline_trend,
    serialize_training_schedule,
)
from src.services.post_walk_analysis import active_recovery_walk_context
from src.services.prompt_metadata import prompt_system_hash
from src.services.sleep_scoring import (
    age_adjusted_sleep_score as compute_age_adjusted_sleep_score,
)
from src.services.training_week import TrainingWeekService
from src.services.verdict_scaling import (
    AMBER_POWER_CAP_PCT,
    companion_session_present,
    ir_has_vo2,
    summarize_verdict_adjustment,
)
from src.services.workload_budget import workload_slot
from src.services.workout_categories import is_bike_workout_type
from src.services.workout_delivery import build_structured_workout_ir

# Batch 64 (#137): the packet now carries the user's most recent corrections so
# the read can acknowledge/adjust when Mark has told it it was wrong.
# Batch 66 (#139): on a cautious morning with a hard session scheduled, the
# verdict leads with a week swap (move the hard session, pull an easier one
# forward) before offering to soften — so the prompt version bumps.
# Batch 70 (#143): the packet now carries verdict.weeklyMix — the week's
# done/due/at-risk quality mix and, when today's hard session is eased, whether
# it is re-patched or explicitly not made up this week — so the version bumps
# again to regenerate stale reads.
# Batch 85 (#158): the check-in is now the primary generate trigger, so the read
# must answer a question Mark leaves in his check-in notes (grounded in the packet)
# — the prompt gains that instruction, so the version bumps again.
# Batch 86 (#159): the brief now leads with a deterministic "Today" action block
# (workout adjustment first-class + tappable-to-approve, plus swap/sleep/thermal),
# assembled next to the prose like swapSuggestion/weeklyMix. The prose becomes the
# reasoning/"why" behind those actions and must not repeat them as a checklist, so
# the version bumps again.
# Batch 91 (#164): read fidelity — the packet now carries local wall-clock bed/wake
# (sleepStartLocal/sleepEndLocal), an authoritative subjectDateLabel, and the
# check-in word (subjectiveLabel). The prompt bans printing *Utc timestamps,
# re-deriving the date, and surfacing the raw subjectiveScore number, so the version
# bumps again.
# Batch 92 (#165): thermal review separates the sleep-period room curve from
# the pre-bed cool-down inside the shared bedroom night window. The prompt must
# credit an observed pre-cool instead of narrating it as a failed target.
# Batch 98 (#171): the packet now names a holiday/all-skipped day as rest and
# the prompt must not narrate a paused workout as today's live training choice.
# Batch 142: the sleep packet now carries an explicit timeInBedMin (bed->wake
# window) and timeAsleepMin alongside durationMin, and the prompt states each
# figure as given — never re-subtracting awake from the asleep total to invent an
# "actual sleep" number — so the version bumps again.
# Batch 148: trainingWeekSoFar is the factual planned -> changed -> executed
# calendar-week record. The nominal trainingSchedule is no longer evidence of
# what happened on any weekday, so the version bumps again.
# Batch 167: the deterministic verdict now carries a high-load Amber cap and the
# prompt must explain that final classification without treating load as a
# model-controlled override, so the version bumps again.
# Batch 168: the soft-sleep readiness floor now has an absolute anchor and the
# prompt must surface a sustained 84-day baseline-decline warning without
# treating that warning as a model-controlled verdict change.
# Batch 169: recent corrections now decay and the prompt explicitly keeps them
# subordinate to measured facts, so stale reads should regenerate.
# Batch 170: the deterministic verdict ladder now hardens credited-sleep Green
# crossings, Poor-readiness stacking, and missing-HRV evidence.
# Batch 171: sustained recovery-marker evidence can queue a seven-day deload
# proposal without changing the light.
# Batch 174: yesterdayLoad now includes the prior DailyMetric's all-day stress
# and Body Battery cost even when no exercise was recorded. Narrative context
# only; the deterministic verdict inputs are unchanged.
# Batch 177: profile.athleteProfile.vo2max is now the live daily Garmin value
# (falling back to the stored baseline only when no live reading is on file
# within the lookback window), with profile.vo2maxAsOfDate stating which day
# it's from. Explanatory only — VO2max never touches the verdict ladder.
# Batch 180: yesterday's stress / Body Battery figures now require a completed
# raw Garmin local-day window; the prompt must not reconstruct omitted partials.
# Batch 182: Red mornings are qualified by same-day physiology/check-in context,
# short clusters can only rearrange the week, and a planned recovery-class block
# suppresses a redundant deload.
# Batch 201: raw-Red sleep credit cannot reach Green, Low readiness can relax only
# on proved-benign load, and the shared Amber transform caps at Sweet Spot.
# Batch 215: a Red morning no longer means one thing — an already-Zone-2 ride holds
# its intensity and takes a light duration cut, so verdict.verdictAdjustment and the
# plan-adjustment instruction can now describe a shortened Zone 2 rather than a
# recovery substitution. The bump is load-bearing, not a label: the regeneration
# identity is (user, date, checkInVersion, promptVersion) and does *not* hash the
# packet, so without it an already-generated pre-fix brief would be served as
# current on the day this ships.
PROMPT_VERSION = "morning-analysis-v33-2026-08-23"
ANALYSIS_TYPE = "morning"
# Batch 167 (#248): load can only harden the deterministic light. ACWR at 1.50
# signals a fast ramp; more than 24 hours left on Garmin's recovery timer means
# the user will not be ready for another hard session within the coming day.
ACWR_AMBER_CAP_THRESHOLD = 1.5
RECOVERY_TIME_AMBER_CAP_MIN = 24 * 60
# A Low-readiness exception is discretionary and therefore needs affirmative
# evidence that accumulated load is inside the app's balanced range. Missing
# ACWR is unknown, not benign; a >24h recovery clock conflicts with the escape.
ACWR_LOAD_DRIVEN_MAX = 1.3
SYSTEM_PROMPT = f"""You are CheckMark, a private daily endurance and sleep coach.
Use only the supplied context packet. Follow every data-quality guardrail.
Use `subjectWeekday` as the authoritative weekday and `subjectDateLabel` as the
authoritative calendar date; never derive or reformat the date or weekday from
`subjectDate` yourself. State bed and wake times using sleep.sleepStartLocal and
sleep.sleepEndLocal, which are already the user's local clock time; never print a
`*Utc` timestamp (e.g. sleepStartUtc/sleepEndUtc) or convert one yourself.
State time in bed from sleep.timeInBedMin and time asleep from sleep.timeAsleepMin
(equivalently sleep.durationMin). timeAsleepMin is already time asleep with
sleep.awakeSleepMin excluded, so never subtract awake time from it to compute an
"actual sleep" figure; time in bed equals time asleep plus awake plus any brief
unmeasurable time. State each figure as given — do not re-derive either.
Treat every figure in the supplied context as what the app recorded, not as
independently verified truth about Mark. If Mark says his own device shows a
different observed value, acknowledge the discrepancy, use his device reading
as the better evidence, and treat it as a data-quality problem. This applies to
observed data only: never let a correction change a deterministic verdict,
safety floor, or propose/confirm decision.
Refer to Mark's daily check-in by its word — verdict.subjectiveLabel /
manualEntries[].subjectiveLabel (e.g. "you said you felt OK") — and never surface
the raw subjectiveScore number or a "6/10"-style term for how he felt.
Return concise markdown with a sleep summary line, a metrics-vs-baselines read,
a thermal/environment review, and a Green/Amber/Red workout verdict for today.
In the thermal review, indoorPeakC/indoorLowC/indoorLastC describe only the
sleep period when sleep times are available. Treat preCoolLowC, sleepOnsetC, and
preCoolDropC as the distinct pre-bed cool-down: when flags contains
`precool_credited`, explicitly credit that cooling and do not call the pre-cool
a miss merely because it stopped above targetPreCoolC.
Bold each bullet headline. Never mention left/right power balance. Never keep
VO2 work on a Red verdict. When Garmin readiness is Low, call it load-driven only
if the packet explicitly says recovery signals justify that interpretation; when
readiness is Poor, keep the day cautious.
Use acuteChronicLoadRatio (acute:chronic training load; ~0.8-1.3 is balanced,
>=1.5 triggers the deterministic high-load cap), chronicTrainingLoad,
trainingLoadBalance, recoveryTimeMin, and intensityMinutes to explain the load
read alongside the recovery signals. When verdict.trainingLoadCap applies,
explain its deterministic Amber ceiling and never soften or argue it down; load
is not a model-controlled override of the verdict.
When verdict.readinessBaselineTrend triggers, state plainly that the recent
readiness median has declined versus the prior half-window and never hide, soften,
or argue down that deterministic warning. It does not set the colour itself or
grant permission to train. verdict.readinessEffectiveFloor applies the absolute
readiness anchor to any soft-sleep recovery override.
When the packet marks a soft-sleep recovery override, explain that measured
HRV/RHR/readiness plus the current check-in held a mediocre sleep night without
pretending the sleep was good. Explain verdict.sleepCreditCeiling and never soften
or argue down its deterministic Red/Green ceiling. It records both boundary
crossings caused by age credit. A raw Garmin score below 60
may be lifted to Amber by age adjustment but can never reach Green; a raw score
below 74 that reaches the Green line needs the complete recorded recovery and
check-in bundle. Explain the frozen result. The model is not the judge. When
verdict.cumulativeEscalation
applies, state plainly that Poor readiness
plus another negative recovery signal makes the day Red and never soften or argue
down that deterministic escalation. Missing HRV and absent
subjective check-ins are neutral only: never describe absent data as proof that
recovery is clean.
verdict.chronicAction is a deterministic structural-action signal, not a colour
rule, so explain its recorded qualification and never soften or argue it down.
When chronicAction.triggered is false and no Red morning in
redMorningQualifications was excluded, it is internal bookkeeping with nothing to
report: do not mention chronicAction, the recorded training context log, human
approval, or verdictImpact anywhere in the read. Mark is never told about a
structural signal that is not doing anything; every instruction below applies
only when it is. When a recordedTrainingContext row does need describing, its
matchedText is the phrase from Mark's own check-in that produced the tag — quote
it if he questions the tag, and if the matched phrase plainly meant something
else, say so as a recording error of ours rather than defending the tag.
Its redMorningQualifications state which Red mornings count and which were
excluded. A training-load or deliberate-rest check-in is endogenous evidence and
always counts; an acute alcohol/illness/travel explanation is bounded by the
packet's age/cap fields and cannot override strained HRV or resting HR. Heavy
recovery debt excludes a Red only when HRV/RHR are intact. When kind is
`rearrange_proposal`, explain
the offered hard-for-easy swap and never call it a deload. When kind is
`deload_proposal`, state that the listed sustained marker evidence — not merely a
pair of Reds — caused the seven-day proposal. When suppressedByPlan is true,
state that the scheduled recovery/taper/consolidation block already handles the
horizon and that no extra structural change was proposed. Every form remains
human-approved and has verdictImpact `none`: never claim it changed, softened,
or set today's Green/Amber/Red result.
stage in ageComparison.sleepRows sits inside its healthy age band, describe it as
healthy for the user's age rather than repeating Garmin's young-adult flag (e.g.
"REM 16% is within the healthy 50-59 range; Garmin only flags it against a younger
target"). knowledgeBase.trainingSchedule describes the user's usual routine only;
never use it as evidence that a session happened this week or assign a completed
session to one of its nominal weekdays. Ground every claim about what was planned,
changed, completed, skipped, or accumulated this calendar week strictly in
trainingWeekSoFar: planned is the final active schedule, changes is the explicit
action audit, and executed Garmin activities are the only completion truth. Never
credit a moved-away, skipped, removed, or merely planned session as executed. Where
it helps, acknowledge the move recorded in changes. Respect the usual routine's
rest-day preference only when making a future recommendation, not when narrating
history. `yesterdayLoad.status` and its training totals describe exercise only;
never equate a low/absent training load with a low-cost whole day. Use
`yesterdayLoad.wholeDayCost` independently: when allDayStressAvg,
bodyBatteryDrained, or bodyBatteryEnd is present, describe that non-exercise
cost even when activityCount is zero. wholeDayCost.classificationImpact is
`none`, so this context explains the read but never changes the deterministic
Green/Amber/Red verdict. Each figure is populated only when its Garmin source
window covers the closed local day. If wholeDayCost.coverage is incomplete or
unknown, do not infer, reconstruct, or describe the missing figures as finished-
day totals. Use the exercise fields to explain any eased ride after a hard prior
session.
When restDay.isRestDay is true, frame today's verdict as a rest day. Do not
recommend, soften, rearrange, or relitigate a planned workout whose status is
skipped, and do not narrate a session inside the holiday window as a live
training decision. Recovery signals may still determine Green/Amber/Red, but
that colour describes recovery on a rest day rather than permission to train.
When restDay.insideHolidayWindow is true, environment.thermalReview is null
because the bedroom isn't being slept in while away — omit the thermal/
environment review entirely rather than writing one from stale or absent data.
When recentCorrections is non-empty, treat each as a user-reported correction
about a past read (e.g. "my watch showed 28, not 12"). A conflicting own-device
observation is better evidence for what that device displayed: acknowledge the
discrepancy and name the app record as a data-quality problem instead of
defending it. The correction still never overrides the Red floor, the soft-sleep
rule, Poor-readiness caution, Red-never-VO2, the recorded plan/completion state,
or the deterministic verdict — it is observed-data evidence, not an instruction
to obey.
When verdict.swapSuggestion is present, lead the plan guidance with the swap —
move the hard session from hardWeekday to the suggested day and pull the easier
session forward to hardWeekday — matching Mark's preference to rearrange the week
rather than soften. Offer softening the ride only as the fallback for when the
week can't be rearranged.
When verdict.verdictAdjustment is present it is the app's own deterministic easing of
today's ride — planned vs adjusted duration and the resulting %FTP. If you describe
the softened session, quote those exact figures; never invent a different percentage
or duration. When verdictAdjustment.intensityHeldAtEndurance is true the ride is
already Zone 2, so it is only shortened, not dropped in intensity — say so rather
than implying a zone drop. This is now reachable on Red as well as Amber: when it is
true on a Red morning the day is a shortened Zone 2, not a recovery substitution, so
do not describe the session as substituted, replaced or dropped to recovery, and do
not tell him to swap it for rest. Sustained easy work builds sleep pressure without
the arousal harder work produces, which is why Red keeps it; the hard work is still
gone. When verdictAdjustment.companionSession is true the day already holds another
session, so the combined load is what the adjustment is protecting — say that rather
than presenting the deeper cut as being about the ride alone. When former HIT/VO2
work is capped at
{AMBER_POWER_CAP_PCT}% FTP, describe
it as converted to Sweet Spot at that recorded intensity, not as removed altogether.
When verdict.weeklyMix.shortfall is present, today's hard session is being eased:
if shortfall.repatched is true, reassure him the quality work isn't lost — it moves
to shortfall.moveToWeekday and the week keeps its mix; if it is false, state plainly
that there is no such session this week and that this is the right call on his
recovery, not a gap to force. The mix is a protected target, but readiness always
gets the veto — never push a hard session onto a poor-recovery day to hit a quota,
and never onto a Monday or Friday.
When manualEntries carries a question from Mark (in his notes or feel — e.g. "why am
I so tired?", "should I still ride today?", "is my overnight HRV normal?"), answer it
directly and briefly, grounded only in this packet (his sleep, recovery, thermal /
overnight-temperature, load, and plan). Put the answer under a short
"**Your question**" heading near the top of the read. If the packet does not hold
what is needed to answer, say so plainly rather than guessing. Answering a question
never overrides the Red floor, the soft-sleep rule, the Poor-readiness caution, or
Red-never-VO2.
profile.athleteProfile.vo2max is Garmin's live measured value as of
profile.vo2maxAsOfDate, not a fixed baseline — it may differ from a number you
recall stating in a previous read, and that difference is real, not an error.
State it as his current VO2max; if vo2maxAsOfDate is not today, say the reading
is from that date rather than implying it was measured today. Only remark on a
change if you are comparing against a figure explicitly given elsewhere in this
same packet — never invent a trend from memory or from a single reading alone.
This is explanatory context only and never moves the Green/Amber/Red verdict.
When Mark questions where a figure came from, answer from the basis the app
states and never invent a mechanism for how the app reached it - quote that basis
in his own terms, and where a figure carries none, say plainly that the app does
not record how that number was reached rather than offering a sensor, setting or
calculation that merely sounds right. Do not carry such a guess forward into a
later answer. verdict.weeklyMix.buckets[].basis says how that bucket's target and
completed count were reached: the target is a count of the sessions his own plan
carries this week, never a standing weekly quota, so quote it if he challenges the
number instead of conceding it is probably wrong. A plannedWorkouts[].basis and a
knowledgeBase.sections[].basis each say how that item came to exist; where one is
absent the app does not record it, and that is the honest answer.
The app renders a short "Today" action list above your read (the eased ride to
approve, any week swap, and sleep/thermal nudges), assembled separately from your
prose. Write the read as the reasoning and the "why" behind those actions — do not
restate them as a duplicated checklist or an "Actions" header. Keep leading with the
sleep summary, the metrics-vs-baselines read, the thermal review, and the verdict as
before; reference an action in prose only where the reasoning needs it."""
SYSTEM_PROMPT = "\n\n".join((SYSTEM_PROMPT, LEARNED_CONTEXT_PROMPT_GUARDRAIL))


class MorningAnalysisError(RuntimeError):
    """Raised when morning analysis cannot be generated."""


@dataclass(frozen=True)
class ClaudeGenerationResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str | None


class MorningAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled morning packet."""


class AnthropicMorningAnalysisClient:
    """Small HTTP boundary for Anthropic Messages without adding an SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        if not self.api_key:
            raise MorningAnalysisError("ANTHROPIC_API_KEY is not configured.")
        result = await generate_anthropic_text(
            api_key=self.api_key,
            model_name=self.model_name,
            max_tokens=self.max_tokens,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            error_cls=MorningAnalysisError,
        )
        return ClaudeGenerationResult(
            output_markdown=result.output_markdown,
            raw_response=result.raw_response,
            model_name=result.model_name,
        )


@dataclass(frozen=True)
class MorningAnalysisResult:
    analysis: Analysis
    generated: bool


class MorningAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assemble_context_packet(self, player: Profile, subject_date: date) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        daily_metric = await self._daily_metric(player.id, subject_date)
        day_aggregate_metric = await self._day_aggregate_metric(player.id, subject_date)
        sleep = await self._sleep(player.id, subject_date)
        manual_entries = await self._manual_entries(player.id, subject_date)
        recent_corrections = await FeedbackService(self.session).recent_corrections(player.id)
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        training_week = await TrainingWeekService(self.session).build(
            player,
            as_of=subject_date,
        )
        holiday_windows = await HolidayPauseService(self.session).get_windows(player)
        rest_day = _rest_day_context(
            planned_workouts,
            holiday_windows,
            subject_date=subject_date,
        )
        recent_walks = await self._recent_walks(player.id, subject_date)
        breathwork_brief = await BreathworkBriefService(self.session).brief(
            player,
            as_of=subject_date,
        )
        baselines = await self._metric_baselines(player.id)
        baseline_rows = baseline_lookup(baselines)
        readiness_trend = readiness_baseline_trend(
            await self._readiness_history(player.id, subject_date),
            as_of=subject_date,
        )
        yesterday_load = await self._yesterday_load(player.id, subject_date, player.timezone)
        weather = await self._weather(player.id, subject_date)
        temperature_rows = await self._overnight_temperature_rows(
            player.id,
            subject_date,
            player.timezone,
        )
        effective_vo2max, vo2max_as_of_date = await resolve_effective_vo2max(
            self.session, player.id, subject_date
        )
        weight_kg, weight_as_of_date = await resolve_effective_weight_kg(
            self.session, player.id, subject_date
        )

        age_adjusted_sleep_score = _age_adjusted_sleep_score(sleep, knowledge_base)
        # Persist the recomputed score back to the row so the column-reading
        # history surfaces (baselines, reviews, sleep history, chronic patterns)
        # catch up forward-only as each day's analysis runs — no migration, no
        # re-sync (Batch 61 #135). Mirrors the commit=False seeding above: the
        # write only lands when the caller commits (a read-only assemble rolls
        # it back), so this stays side-effect-free for pure packet reads.
        if (
            sleep is not None
            and age_adjusted_sleep_score is not None
            and sleep.age_adjusted_score != age_adjusted_sleep_score
        ):
            sleep.age_adjusted_score = age_adjusted_sleep_score
        metrics_table = _metrics_vs_baselines(
            daily_metric,
            sleep,
            baselines,
            age_adjusted_sleep_score,
            day_aggregates=day_aggregate_metric,
        )
        age_comparison = _age_comparison(daily_metric, sleep, knowledge_base)
        thermal_review = _thermal_review(
            temperature_rows,
            weather,
            knowledge_base,
            sleep=sleep,
        )
        # Batch 113 (#186): a holiday is "away" for thermal purposes too — the
        # bedroom isn't being slept in, so neither the packet/prompt review nor
        # the pre-cool action should surface. Outside a holiday window (including
        # an all-skipped rest day, which still happens at home) the review stands.
        thermal_review_for_output = None if rest_day["insideHolidayWindow"] else thermal_review
        daily_metric_packet = _daily_metric_packet(daily_metric)
        verdict = _morning_verdict(
            daily_metric=daily_metric,
            sleep=sleep,
            age_adjusted_sleep_score=age_adjusted_sleep_score,
            manual_entries=manual_entries,
            planned_workouts=planned_workouts,
            baselines=baseline_rows,
            yesterday_load=yesterday_load,
            training_load=_training_load_signal(daily_metric_packet),
            readiness_baseline_trend=readiness_trend,
            breathwork_brief=breathwork_brief,
            rest_day=rest_day,
        )
        # Batch 171: keep the chronic card's existing advisory copy, but derive a
        # separate deterministic structural-action signal from protected
        # recovery-marker misses or a qualified Red-morning cluster. The current
        # verdict is supplied explicitly because it has not been persisted yet.
        chronic_result = await ChronicPatternSuggestionService(self.session).suggestions(
            player,
            as_of=subject_date,
            sleep_drivers=[],
            sleep_protocol=knowledge_base.get("sleep_protocol", {}),
            current_verdict=str(verdict.get("status") or ""),
        )
        verdict["chronicAction"] = chronic_result.action_signal.to_packet()
        # Batch 66 (#139): on a cautious morning with a hard session scheduled,
        # lead with a week swap (move the hard session to a better day, pull an
        # easier one forward) — Mark's own instinct — before offering to soften.
        # Batch 182 extends that same read-only rail to a qualifying short Red
        # cluster: find the first upcoming hard↔easy swap inside the action horizon
        # even when today itself is rest/easy. Mark's Apply tap remains the write.
        # Computed read-only from the restructure engine's spacing rules; the
        # action the verdict card offers is a category-scoped swap_day (Batch
        # 65-safe on split days), not the whole-week apply. Lazy import keeps the
        # module graph acyclic (weekly_restructure pulls in daily_loop).
        swap = None
        chronic_action = verdict.get("chronicAction")
        acute_swap = verdict.get("status") in {"Amber", "Red"} and not rest_day["isRestDay"]
        cluster_swap = (
            isinstance(chronic_action, Mapping)
            and chronic_action.get("triggered") is True
            and chronic_action.get("kind") == "rearrange_proposal"
        )
        if acute_swap or cluster_swap:
            from src.services.weekly_restructure import (
                PROTECTED_WEEKDAYS,
                WeeklyRestructureService,
            )

            restructure = WeeklyRestructureService(self.session)
            if acute_swap:
                swap = await restructure.swap_suggestion_for_day(
                    player, subject_date, protected_weekdays=PROTECTED_WEEKDAYS
                )
            if swap is None and cluster_swap:
                swap = await restructure.swap_suggestion_in_horizon(
                    player,
                    subject_date,
                    end_date=subject_date + timedelta(days=CHRONIC_DELOAD_WINDOW_DAYS - 1),
                    protected_weekdays=PROTECTED_WEEKDAYS,
                )
            if swap is not None:
                verdict["swapSuggestion"] = swap.to_packet()
                verdict["planAdjustments"] = [
                    swap.lead_text(),
                    *verdict.get("planAdjustments", []),
                ]
        # Batch 70 (#143): weekly-mix maintenance. Always report the week's
        # done/due/at-risk mix (so the week view can show it even on a Green day);
        # when a cautious morning eases today's hard bike session, either confirm
        # the re-patch (the swap above) or say plainly it won't be made up this
        # week — advisory accounting, never an auto-schedule. Read-only.
        from src.services.weekly_mix import WeeklyMixService

        weekly_mix = await WeeklyMixService(self.session).summarize_for_verdict(
            player,
            subject_date,
            verdict_status=str(verdict.get("status") or ""),
            swap=swap if swap is not None and swap.subject_date == subject_date else None,
            suppress_today_easing=bool(rest_day["isRestDay"]),
        )
        verdict["weeklyMix"] = weekly_mix.to_packet()
        existing_adjustments = verdict.get("planAdjustments", [])
        for message in weekly_mix.plan_adjustments():
            if message not in existing_adjustments:
                existing_adjustments.append(message)
        verdict["planAdjustments"] = existing_adjustments
        # Batch 86 (#159): assemble the deterministic "Today" action block now that
        # the verdict (status, swapSuggestion, weeklyMix, planAdjustments) is final.
        # Reuse the exact breathwork gate the adjustment text already uses so the
        # sleep action and the prose stay in lockstep.
        recommend_breathwork = should_recommend_breathwork(
            {
                "status": verdict.get("status"),
                "readinessLevel": verdict.get("readinessLevel"),
                "readinessInterpretation": verdict.get("readinessInterpretation"),
                "hrvStatus": verdict.get("hrvStatus"),
                "hrvBelowBaseline": verdict.get("hrvBelowBaseline"),
            }
        )
        # Batch 173.3: surface the deterministic Amber/Red adjustment numbers (the
        # same transform the delivery rail and editor use) so the narrative and
        # brief-chat quote the app's own figures instead of guessing. Explanatory
        # only — it cannot set the verdict or the numbers.
        verdict["verdictAdjustment"] = _verdict_adjustment_packet(
            str(verdict.get("status") or ""),
            [] if rest_day["isRestDay"] else planned_workouts,
        )
        verdict["todayActions"] = build_today_actions(
            verdict=verdict,
            planned_workouts=[] if rest_day["isRestDay"] else planned_workouts,
            thermal_review=thermal_review_for_output or {},
            recommend_breathwork=recommend_breathwork,
        )
        training_schedule = serialize_training_schedule(knowledge_base)

        return {
            "packetType": "morning_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "subjectWeekday": subject_date.strftime("%A"),
            "subjectDateLabel": _date_label(subject_date),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": _profile_packet(
                player,
                knowledge_base,
                effective_vo2max,
                vo2max_as_of_date,
                weight_kg,
                weight_as_of_date,
            ),
            "knowledgeBase": {
                "sections": [_knowledge_base_packet(row) for row in kb_rows],
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "sleepProtocol": knowledge_base.get("sleep_protocol", {}),
                "trainingSchedule": training_schedule,
                "activeHypotheses": knowledge_base.get("active_hypotheses", {}),
                "learnedContext": learned_context_packet(knowledge_base),
            },
            "dailyMetrics": daily_metric_packet,
            "sleep": _sleep_packet(sleep, age_adjusted_sleep_score, player.timezone),
            "manualEntries": [_manual_entry_packet(entry) for entry in manual_entries],
            "recentCorrections": [c.to_packet() for c in recent_corrections],
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
            "trainingWeekSoFar": training_week,
            "restDay": rest_day,
            "activeRecovery": {
                "deliberateWalkVolume": active_recovery_walk_context(
                    recent_walks,
                    as_of_date=subject_date,
                ),
                "classificationImpact": "none",
            },
            "breathworkBrief": _breathwork_brief_packet(breathwork_brief, subject_date),
            "personalBaselines": baseline_band_packet(
                baselines,
                keys={
                    "age_adjusted_sleep_score",
                    "sleep_score",
                    "hrv_7_day_avg_ms",
                    "resting_heart_rate_bpm",
                },
            ),
            "yesterdayLoad": yesterday_load,
            "metricsVsBaselines": metrics_table,
            "ageComparison": age_comparison,
            "environment": {
                "thermalReview": thermal_review_for_output,
                "weather": _weather_packet(weather),
            },
            "verdict": verdict,
            "prompt": {
                "version": PROMPT_VERSION,
                "systemHash": prompt_system_hash(SYSTEM_PROMPT),
                "outputRules": [
                    rule
                    for rule in [
                        "bold_each_bullet_headline",
                        "include_sleep_summary_line",
                        "include_metrics_vs_baselines_table",
                        "include_thermal_environment_review",
                        "credit_observed_precool_separately_from_sleep_peak",
                        "include_plan_aware_workout_verdict",
                        "never_reference_left_right_power_balance",
                        "never_recommend_vo2_on_red",
                        "acknowledge_recent_user_corrections_when_relevant",
                        "lead_with_week_swap_when_offered",
                        "maintain_weekly_quality_mix_readiness_gated",
                        "reasoning_prose_not_duplicated_action_checklist",
                        "state_local_clock_times_never_utc",
                        "use_authoritative_date_label_never_rederive",
                        "refer_to_checkin_by_word_not_number",
                        "frame_holiday_or_all_skipped_day_as_rest",
                        "never_treat_skipped_workout_as_live_training",
                        "ground_week_history_in_training_week_so_far",
                        "include_yesterday_whole_day_cost_when_present",
                        "surface_readiness_baseline_decline_warning",
                        "qualify_reds_before_structural_action",
                        "rearrange_short_cluster_deload_only_sustained_marker",
                        "respect_scheduled_recovery_block",
                        "treat_training_schedule_as_nominal_only",
                    ]
                    # Batch 113 (#186): holiday away means no bedroom thermal review.
                    if rule != "include_thermal_environment_review"
                    or not rest_day["insideHolidayWindow"]
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        subject_date: date,
        *,
        client: MorningAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> MorningAnalysisResult:
        manual_entries = await self._manual_entries(player.id, subject_date)
        input_version = manual_entry_generation_version(
            manual_entries[0] if manual_entries else None
        )
        request_identity = morning_generation_identity(
            user_id=player.id,
            subject_date=subject_date,
            input_version=input_version,
            prompt_version=PROMPT_VERSION,
        )
        async with claim_generation_request(
            self.session,
            user_id=player.id,
            request_identity=request_identity,
            generation_kind=ANALYSIS_TYPE,
            lease_scope=f"morning:{player.id}:{subject_date.isoformat()}",
        ) as claim:
            if claim.existing_analysis is not None:
                packet = claim.existing_analysis.context_packet
                if (
                    claim.existing_analysis.prompt_version == PROMPT_VERSION
                    and isinstance(packet, dict)
                    and packet.get("generationIdentity") == request_identity
                ):
                    return MorningAnalysisResult(
                        analysis=claim.existing_analysis,
                        generated=False,
                    )
                claim.restart()

            if not force:
                existing = await self.latest_analysis(player.id, subject_date)
                if existing is not None and existing.prompt_version == PROMPT_VERSION:
                    claim.mark_completed(existing)
                    if commit:
                        await self.session.commit()
                    else:
                        await self.session.flush()
                    return MorningAnalysisResult(analysis=existing, generated=False)

            context_packet = await self.assemble_context_packet(player, subject_date)
            stamp_generation_identity(
                context_packet,
                request_identity=request_identity,
                input_version=input_version,
            )
            user_prompt = build_morning_user_prompt(context_packet)
            analysis_client = client or AnthropicMorningAnalysisClient()
            async with workload_slot(workload="anthropic", user_id=player.id):
                generation = await analysis_client.generate(
                    context_packet=context_packet,
                    user_prompt=user_prompt,
                )
            verdict = context_packet.get("verdict", {}).get("status")
            analysis = Analysis(
                user_id=player.id,
                activity_id=None,
                analysis_type=ANALYSIS_TYPE,
                subject_date=subject_date,
                generated_at_utc=_utcnow(),
                prompt_version=PROMPT_VERSION,
                model_name=generation.model_name,
                verdict=verdict if isinstance(verdict, str) else None,
                context_packet=context_packet,
                output_markdown=generation.output_markdown,
                raw_response=generation.raw_response,
            )
            self.session.add(analysis)
            await self.session.flush()
            claim.mark_completed(analysis)
            if commit:
                await self.session.commit()
                await self.session.refresh(analysis)
            else:
                await self.session.flush()
            return MorningAnalysisResult(analysis=analysis, generated=True)

    async def latest_analysis(self, user_id: uuid.UUID, subject_date: date) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == ANALYSIS_TYPE,
                    Analysis.subject_date == subject_date,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    async def _active_knowledge_base(self, user_id: uuid.UUID) -> list[KnowledgeBase]:
        rows = (
            (
                await self.session.execute(
                    select(KnowledgeBase)
                    .where(KnowledgeBase.user_id == user_id, KnowledgeBase.is_active.is_(True))
                    .order_by(KnowledgeBase.section.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _daily_metric(self, user_id: uuid.UUID, subject_date: date) -> DailyMetric | None:
        """The wake observation — this packet *is* the morning read (Batch 205)."""
        return cast(
            DailyMetric | None,
            await self.session.scalar(
                select(DailyMetric)
                .where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date == subject_date,
                )
                .order_by(morning_first_order())
                .limit(1)
            ),
        )

    async def _day_aggregate_metric(
        self, user_id: uuid.UUID, subject_date: date
    ) -> DailyMetric | None:
        """The settled observation for ``subject_date``, if one exists yet.

        Batch 216: Body Battery charge/drain and stress are running local-day
        totals, not point-in-time readings — a morning wake row can never carry
        a complete one (``daily_metric_coverage``). Mirrors the ``day_aggregates``
        parameter ``sample_values`` already uses for the same reason.
        """
        return cast(
            DailyMetric | None,
            await self.session.scalar(
                select(DailyMetric)
                .where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date == subject_date,
                )
                .order_by(settled_first_order())
                .limit(1)
            ),
        )

    async def _sleep(self, user_id: uuid.UUID, subject_date: date) -> Sleep | None:
        return cast(
            Sleep | None,
            await self.session.scalar(
                select(Sleep).where(Sleep.user_id == user_id, Sleep.calendar_date == subject_date)
            ),
        )

    async def _manual_entries(self, user_id: uuid.UUID, subject_date: date) -> list[ManualEntry]:
        rows = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.planned_workout_id.is_(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(desc(ManualEntry.entry_at_utc))
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _planned_workouts(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == subject_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _recent_walks(self, user_id: uuid.UUID, subject_date: date) -> list[Activity]:
        start_date = subject_date - timedelta(days=7)
        lower_bound = datetime(start_date.year, start_date.month, start_date.day)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.activity_type == "walking",
                        Activity.start_utc >= lower_bound,
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return [row for row in rows if row.start_utc.date() <= subject_date]

    async def _yesterday_load(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> dict[str, Any]:
        yesterday = subject_date - timedelta(days=1)
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("UTC")
        lower_bound = (
            datetime.combine(yesterday, time.min, tzinfo=timezone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        upper_bound = (
            datetime.combine(subject_date, time.min, tzinfo=timezone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        activities = list(
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= lower_bound,
                        Activity.start_utc < upper_bound,
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        # Deliberately settled, not morning (Batch 205): this packet answers
        # "what did yesterday cost", which is a whole-day question. Yesterday's
        # wake reading predates yesterday's session entirely, so it is the one
        # place the closed-day observation is the honest input.
        daily_metric = cast(
            DailyMetric | None,
            await self.session.scalar(
                select(DailyMetric)
                .where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date == yesterday,
                )
                .order_by(settled_first_order())
                .limit(1)
            ),
        )
        if not activities:
            return _yesterday_load_packet([], [], daily_metric)

        activity_ids = [activity.id for activity in activities]
        analyses = list(
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.activity_id.in_(activity_ids),
                    )
                    .order_by(desc(Analysis.generated_at_utc))
                )
            )
            .scalars()
            .all()
        )
        return _yesterday_load_packet(activities, analyses, daily_metric)

    async def _metric_baselines(self, user_id: uuid.UUID) -> list[MetricBaseline]:
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
        return list(rows)

    async def _readiness_history(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> list[tuple[date, int | None]]:
        window_start = subject_date - timedelta(days=83)
        rows = (
            (
                await self.session.execute(
                    select(DailyMetric)
                    .where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.calendar_date >= window_start,
                        DailyMetric.calendar_date <= subject_date,
                    )
                    .order_by(DailyMetric.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )
        # CI191-02 consequence 2: this history is compared against a morning
        # reading, so it has to be built from morning readings. Built from the
        # settled rows it was an apples-to-oranges comparison biased toward a
        # lower floor.
        return [(row.calendar_date, row.readiness_score) for row in prefer_morning(rows)]

    async def _weather(self, user_id: uuid.UUID, subject_date: date) -> WeatherDaily | None:
        return cast(
            WeatherDaily | None,
            await self.session.scalar(
                select(WeatherDaily)
                .where(
                    WeatherDaily.user_id == user_id,
                    WeatherDaily.calendar_date == subject_date,
                )
                .order_by(desc(WeatherDaily.updated_at))
                .limit(1)
            ),
        )

    async def _overnight_temperature_rows(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> list[TemperatureReading]:
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("UTC")
        # The morning subject date is Garmin's wake date; the shared bedroom
        # helper accepts the date on which the night starts (Batch 92 #165).
        start_utc, end_utc = night_window(subject_date - timedelta(days=1), timezone)
        rows = (
            (
                await self.session.execute(
                    select(TemperatureReading)
                    .where(
                        TemperatureReading.user_id == user_id,
                        TemperatureReading.captured_at_utc >= start_utc,
                        TemperatureReading.captured_at_utc < end_utc,
                    )
                    .order_by(TemperatureReading.captured_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


def build_morning_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate today's morning CheckMark analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _profile_packet(
    player: Profile,
    knowledge_base: Mapping[str, Any],
    effective_vo2max: float | None,
    vo2max_as_of_date: date | None,
    weight_kg: float | None,
    weight_as_of_date: date | None,
) -> dict[str, Any]:
    # Batch 177 (#257): overlay the live daily VO2max onto the static KB profile
    # number so the packet carries the real current value, not a hardcoded one.
    profile = knowledge_base.get("profile", {})
    athlete_profile = dict(profile) if isinstance(profile, Mapping) else {}
    if effective_vo2max is not None:
        athlete_profile["vo2max"] = effective_vo2max
    return {
        "userId": str(player.id),
        "displayName": player.display_name,
        "timezone": player.timezone,
        "latitude": player.latitude,
        "longitude": player.longitude,
        "athleteProfile": athlete_profile,
        "vo2maxAsOfDate": vo2max_as_of_date.isoformat() if vo2max_as_of_date else None,
        "weightKg": weight_kg,
        "weightAsOfDate": weight_as_of_date.isoformat() if weight_as_of_date else None,
        "weightOnFile": weight_kg is not None,
    }


def _knowledge_base_packet(row: KnowledgeBase) -> dict[str, Any]:
    """One stored section, with a basis Mark can be told (Batch 217).

    ``source`` stays for the app's own consumers, but it is an internal token
    and the coach is forbidden from repeating it. On 2026-08-20 Mark asked what
    the basis of his 23:15 bedtime target was; this row already carried
    ``batch_5_seed`` and the coach answered that it would be speculating. The
    ``basis`` key is that same fact in words it is allowed to say. It is omitted
    rather than guessed when the token is unrecognised.
    """
    packet: dict[str, Any] = {
        "section": row.section,
        "version": row.version,
        "source": row.source,
        "content": row.content,
    }
    basis = source_basis(row.source)
    if basis is not None:
        packet["basis"] = basis
    return packet


def _data_quality_guardrails(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules", {})
    rules = section.get("rules") if isinstance(section, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_mapping(value: Any) -> dict[str, Any]:
    """First dict value in a device-keyed map (e.g. latestTrainingStatusData)."""
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, dict):
                return item
    return {}


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _training_and_activity_fields(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Surface load + daily-activity context already captured in ``raw_payload``.

    The daily sync stores the full Garmin ``training_status`` and ``stats``
    responses but only promotes a few fields to columns. This reads the rest
    (chronic load + acute:chronic ratio, training-load balance, steps, intensity
    minutes) so the morning packet/prompt can use them. Read-only — no new Garmin
    call, no migration; every field degrades to ``None`` when absent.
    """
    ts = _as_mapping(raw_payload.get("training_status"))
    status_node = _first_mapping(
        _as_mapping(ts.get("mostRecentTrainingStatus")).get("latestTrainingStatusData")
    )
    acute_dto = _as_mapping(status_node.get("acuteTrainingLoadDTO"))
    acute = _coerce_int(acute_dto.get("dailyTrainingLoadAcute"))
    chronic = _coerce_int(acute_dto.get("dailyTrainingLoadChronic"))
    balance_node = _first_mapping(
        _as_mapping(ts.get("mostRecentTrainingLoadBalance")).get("metricsTrainingLoadBalanceDTOMap")
    )
    balance_phrase = balance_node.get("trainingBalanceFeedbackPhrase")

    stats = _as_mapping(raw_payload.get("stats"))
    moderate = _coerce_int(stats.get("moderateIntensityMinutes"))
    vigorous = _coerce_int(stats.get("vigorousIntensityMinutes"))
    intensity_minutes = (
        (moderate or 0) + (vigorous or 0) if moderate is not None or vigorous is not None else None
    )

    return {
        "chronicTrainingLoad": chronic,
        "acuteChronicLoadRatio": round(acute / chronic, 2) if acute and chronic else None,
        "trainingLoadBalance": balance_phrase if isinstance(balance_phrase, str) else None,
        "steps": _coerce_int(stats.get("totalSteps")),
        "intensityMinutes": intensity_minutes,
    }


def _daily_metric_packet(row: DailyMetric | None) -> dict[str, Any] | None:
    if row is None:
        return None
    packet = {
        "calendarDate": row.calendar_date.isoformat(),
        "recordedAtUtc": _dt(row.recorded_at_utc),
        "readinessScore": row.readiness_score,
        "readinessLevel": row.readiness_level,
        "readinessSleepScore": row.readiness_sleep_score,
        "recoveryTimeMin": row.recovery_time_min,
        "acuteLoad": row.acute_load,
        "trainingStatus": row.training_status,
        "hrvLastNightAvgMs": row.hrv_last_night_avg_ms,
        "hrvWeeklyAvgMs": row.hrv_weekly_avg_ms,
        "hrvStatus": row.hrv_status,
        "hrvBaselineLowMs": row.hrv_baseline_low_ms,
        "hrvBaselineHighMs": row.hrv_baseline_high_ms,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
        "stressAvg": row.stress_avg,
        "bodyBatteryCharged": row.body_battery_charged,
        "bodyBatteryDrained": row.body_battery_drained,
        "bodyBatteryEnd": row.body_battery_end,
        "weightKg": row.weight_kg,
        "vo2max": row.vo2max,
    }
    packet.update(_training_and_activity_fields(row.raw_payload or {}))
    return packet


def _training_load_signal(
    daily_metric_packet: Mapping[str, Any] | None,
) -> dict[str, float | int | None]:
    """Extract only the load inputs allowed to harden the verdict."""
    packet = daily_metric_packet or {}
    return {
        "acuteChronicLoadRatio": _coerce_float(packet.get("acuteChronicLoadRatio")),
        "recoveryTimeMin": _coerce_int(packet.get("recoveryTimeMin")),
    }


def _sleep_packet(
    row: Sleep | None,
    age_adjusted_sleep_score: int | None,
    timezone_name: str,
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "sleepStartUtc": _dt(row.sleep_start_utc),
        "sleepEndUtc": _dt(row.sleep_end_utc),
        # Batch 91 (#164): local wall-clock bed/wake for the read to state verbatim,
        # alongside the *Utc fields — so BST 00:17Z renders 01:17, never raw UTC.
        "sleepStartLocal": _local_clock(row.sleep_start_utc, timezone_name),
        "sleepEndLocal": _local_clock(row.sleep_end_utc, timezone_name),
        "score": row.score,
        "ageAdjustedScore": age_adjusted_sleep_score,
        "qualifier": row.qualifier,
        "durationMin": _minutes(row.duration_sec),
        # Batch 142: name the two totals unambiguously. durationMin / timeAsleepMin
        # is Garmin sleepTimeSeconds — time *asleep*, already excluding
        # awakeSleepMin — while timeInBedMin is the bed->wake window. The model
        # previously mislabelled durationMin as "in bed" and then re-subtracted the
        # awake time to invent a bogus "actual sleep" figure; surfacing both totals,
        # explicitly labelled, removes that ambiguity (the prompt states each as given).
        "timeAsleepMin": _minutes(row.duration_sec),
        "timeInBedMin": _time_in_bed_min(row),
        "deepSleepMin": _minutes(row.deep_sleep_sec),
        "lightSleepMin": _minutes(row.light_sleep_sec),
        "remSleepMin": _minutes(row.rem_sleep_sec),
        "awakeSleepMin": _minutes(row.awake_sleep_sec),
        "averageSpo2Pct": row.average_spo2_pct,
        "lowestSpo2Pct": row.lowest_spo2_pct,
        "averageRespiration": row.average_respiration,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
        "avgOvernightHrvMs": row.avg_overnight_hrv_ms,
        "hrvStatus": row.hrv_status,
        "avgSleepStress": row.avg_sleep_stress,
        "restlessMomentsCount": row.restless_moments_count,
        "bodyBatteryChange": row.body_battery_change,
    }


def _manual_entry_packet(row: ManualEntry) -> dict[str, Any]:
    return {
        "entryDate": row.entry_date.isoformat(),
        "entryAtUtc": _dt(row.entry_at_utc),
        "bpSystolic": row.bp_systolic,
        "bpDiastolic": row.bp_diastolic,
        "subjectiveScore": row.subjective_score,
        "subjectiveLabel": subjective_score_label(row.subjective_score),
        "rpe": row.rpe,
        "feel": row.feel,
        "supplements": row.supplements_json,
        "food": row.food_json,
        "sleepSetup": row.sleep_setup_json,
        "notes": row.notes,
    }


def _planned_workout_packet(row: PlannedWorkout) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "id": str(row.id),
        "planBlockId": str(row.plan_block_id) if row.plan_block_id else None,
        "workoutDate": row.workout_date.isoformat(),
        "version": row.version,
        "title": row.title,
        "workoutType": row.workout_type,
        "status": row.status,
        "plannedDurationMin": row.planned_duration_min,
        "intensityTarget": row.intensity_target,
        "structuredWorkout": row.structured_workout,
        "source": row.source,
    }
    # Batch 217: how this session came to be on the calendar, in words rather
    # than in the app's own vocabulary. Omitted when the token is unrecognised —
    # ``source`` is not always a code constant (an imported plan supplies its
    # own), and silence is safer than a guess.
    basis = source_basis(row.source)
    if basis is not None:
        packet["basis"] = basis
    return packet


def _rest_day_context(
    planned_workouts: Sequence[PlannedWorkout],
    holiday_windows: Sequence[HolidayWindow],
    *,
    subject_date: date,
) -> dict[str, Any]:
    """Describe whether today's plan is intentionally paused/resting.

    An explicit holiday window is authoritative even if a stale plan row was not
    versioned correctly. Outside a holiday, a non-empty day whose every active row
    is already ``skipped`` is also rest. An empty plan remains ``unknown`` rather
    than being silently promoted to an intended rest day, preserving the existing
    conservative missing-plan behaviour.
    """
    matching_windows = holiday_windows_covering_date(holiday_windows, subject_date)
    inside_holiday = bool(matching_windows)
    all_skipped = bool(planned_workouts) and all(
        workout.status == "skipped" for workout in planned_workouts
    )
    reason = "holiday" if inside_holiday else "all_skipped" if all_skipped else None
    return {
        "isRestDay": reason is not None,
        "reason": reason,
        "insideHolidayWindow": inside_holiday,
        "allPlannedWorkoutsSkipped": all_skipped,
        "holidayWindows": [
            {
                "startDate": window.start_date.isoformat(),
                "endDate": window.end_date.isoformat(),
                "isActive": window.is_active,
            }
            for window in matching_windows
        ],
    }


def _weather_packet(row: WeatherDaily | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "source": row.source,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "tempHighC": row.temp_high_c,
        "tempLowC": row.temp_low_c,
        "overnightLowC": row.overnight_low_c,
        "overnightWindMaxMph": row.overnight_wind_max_mph,
        "overnightWindGustMph": row.overnight_wind_gust_mph,
        "overnightWindDirectionDeg": row.overnight_wind_direction_deg,
        "overnightRelativeHumidityMeanPct": row.overnight_relative_humidity_mean_pct,
        "precipitationMm": row.precipitation_mm,
        "sunriseUtc": _dt(row.sunrise_utc),
        "sunsetUtc": _dt(row.sunset_utc),
    }


def _breathwork_brief_packet(
    result: BreathworkBriefResult,
    subject_date: date,
) -> dict[str, Any]:
    week_start = subject_date - timedelta(days=6)
    sessions_this_week = sum(
        1 for session in result.recent_sessions if session.session_date >= week_start
    )
    return {
        "asOfDate": result.as_of_date.isoformat(),
        "sessions7d": sessions_this_week,
        "sessions4w": result.window_4w.session_count,
        "sessionsPerWeek4w": result.window_4w.sessions_per_week,
        "sessions12w": result.window_12w.session_count,
        "trend": result.trend,
        "trendReason": result.trend_reason,
        "advisoryOnly": True,
        "classificationInput": False,
    }


def _age_adjusted_sleep_score(
    sleep: Sleep | None,
    knowledge_base: Mapping[str, Any],
) -> int | None:
    """Age-adjusted sleep score, recomputed live from stored inputs.

    Batch 61 (#135): a real recompute against age bands via
    ``services/sleep_scoring`` replaces the flat Garmin "+4". Computed here at
    analysis time (never read back from the stored column) so the verdict always
    reflects the current logic + profile, even before the column is rewritten.
    """
    if sleep is None:
        return None
    profile = knowledge_base.get("profile", {})
    profile = profile if isinstance(profile, Mapping) else {}
    age = profile.get("age")
    sex = profile.get("sex")
    return compute_age_adjusted_sleep_score(
        garmin_score=sleep.score,
        factors_json=sleep.factors_json,
        deep_sleep_sec=sleep.deep_sleep_sec,
        light_sleep_sec=sleep.light_sleep_sec,
        rem_sleep_sec=sleep.rem_sleep_sec,
        awake_sleep_sec=sleep.awake_sleep_sec,
        age=int(age) if isinstance(age, int | float) else None,
        sex=sex if isinstance(sex, str) else None,
    )


def _metrics_vs_baselines(
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    baselines: Sequence[MetricBaseline],
    age_adjusted_sleep_score: int | None,
    day_aggregates: DailyMetric | None = None,
) -> list[dict[str, Any]]:
    # Batch 216: recovery reads (readiness, RHR, HRV) stay on the morning row —
    # that split is Batch 205's whole point. Body Battery charge/drain are
    # running local-day totals and need the settled row's completed window
    # (`daily_metric_coverage`), which `daily_metric` alone can never satisfy on
    # a live morning. Falls back to `daily_metric` when no settled row exists
    # yet, matching `metric_baselines.sample_values`.
    battery_source = day_aggregates if day_aggregates is not None else daily_metric
    current_values = {
        "sleep_score": sleep.score if sleep else None,
        "age_adjusted_sleep_score": age_adjusted_sleep_score,
        "readiness_score": daily_metric.readiness_score if daily_metric else None,
        "resting_heart_rate_bpm": _first_not_none(
            daily_metric.resting_heart_rate_bpm if daily_metric else None,
            sleep.resting_heart_rate_bpm if sleep else None,
        ),
        "body_battery_charge": (
            complete_body_battery_charged(battery_source) if battery_source is not None else None
        ),
        "body_battery_drain": (
            complete_body_battery_drained(battery_source) if battery_source is not None else None
        ),
        "average_spo2_pct": sleep.average_spo2_pct if sleep else None,
        "average_respiration": sleep.average_respiration if sleep else None,
        "hrv_7_day_avg_ms": daily_metric.hrv_weekly_avg_ms if daily_metric else None,
    }
    rows: list[dict[str, Any]] = []
    for baseline in baselines:
        current = current_values.get(baseline.metric_key)
        center = _first_not_none(baseline.median_value, baseline.mean_value)
        delta = (
            None if current is None or center is None else round(float(current) - float(center), 2)
        )
        rows.append(
            {
                "metricKey": baseline.metric_key,
                "label": baseline.metric_label,
                "currentValue": current,
                "baselineMedian": baseline.median_value,
                "baselineMean": baseline.mean_value,
                "deltaVsBaseline": delta,
                "lowerQuartile": baseline.lower_quartile_value,
                "upperQuartile": baseline.upper_quartile_value,
                "sampleCount": baseline.sample_count,
                "excludedSampleCount": baseline.excluded_sample_count,
                "reliabilityStartDate": (
                    baseline.reliability_start_date.isoformat()
                    if baseline.reliability_start_date
                    else None
                ),
            }
        )
    return rows


def _extract_fitness_age(raw_payload: Mapping[str, Any] | None) -> int | None:
    """Garmin's VO2max-derived fitness age, read from the stored daily payload.

    Lives in ``daily_metrics.raw_payload['max_metrics_vo2'][0].generic.fitnessAge``
    (the same payload ``garmin_sync`` already persists for VO2max), so no extra
    column or sync is needed. Defensive against missing/odd shapes.
    """
    if not isinstance(raw_payload, Mapping):
        return None
    payload = raw_payload.get("max_metrics_vo2")
    item = payload[0] if isinstance(payload, list) and payload else payload
    generic = _as_mapping(_as_mapping(item).get("generic"))
    value = generic.get("fitnessAge")
    return int(value) if isinstance(value, int | float) else None


def _age_comparison(
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    knowledge_base: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the "vs the average for your age" packet (services/age_norms.py)."""
    profile = knowledge_base.get("profile", {})
    profile = profile if isinstance(profile, Mapping) else {}
    age = profile.get("age")
    sex = profile.get("sex")

    resting_hr = _first_not_none(
        daily_metric.resting_heart_rate_bpm if daily_metric else None,
        sleep.resting_heart_rate_bpm if sleep else None,
    )
    hrv = _first_not_none(
        daily_metric.hrv_weekly_avg_ms if daily_metric else None,
        daily_metric.hrv_last_night_avg_ms if daily_metric else None,
    )
    return build_age_comparison(
        age=int(age) if isinstance(age, int | float) else None,
        sex=sex if isinstance(sex, str) else None,
        vo2max=daily_metric.vo2max if daily_metric else None,
        resting_heart_rate_bpm=resting_hr,
        hrv_overnight_ms=hrv,
        fitness_age=_extract_fitness_age(daily_metric.raw_payload if daily_metric else None),
        duration_sec=sleep.duration_sec if sleep else None,
        deep_sleep_sec=sleep.deep_sleep_sec if sleep else None,
        light_sleep_sec=sleep.light_sleep_sec if sleep else None,
        rem_sleep_sec=sleep.rem_sleep_sec if sleep else None,
        awake_sleep_sec=sleep.awake_sleep_sec if sleep else None,
        restless_moments_count=sleep.restless_moments_count if sleep else None,
    ).to_dict()


def _thermal_review(
    temperature_rows: Sequence[TemperatureReading],
    weather: WeatherDaily | None,
    knowledge_base: Mapping[str, Any],
    *,
    sleep: Sleep | None = None,
) -> dict[str, Any]:
    sleep_protocol = knowledge_base.get("sleep_protocol", {})
    threshold_low = 19.5
    threshold_high = 20.0
    target_precool = 17.0
    if isinstance(sleep_protocol, dict):
        threshold = sleep_protocol.get("thermalDisruptionThresholdC")
        if isinstance(threshold, dict):
            low = threshold.get("low")
            high = threshold.get("high")
            if isinstance(low, int | float):
                threshold_low = float(low)
            if isinstance(high, int | float):
                threshold_high = float(high)
        precool = sleep_protocol.get("preCoolTemperatureC")
        if isinstance(precool, int | float):
            target_precool = float(precool)

    all_rows = sorted(temperature_rows, key=lambda row: row.captured_at_utc)
    sleep_start = sleep.sleep_start_utc if sleep is not None else None
    sleep_end = sleep.sleep_end_utc if sleep is not None else None
    has_sleep_window = sleep_start is not None and sleep_end is not None and sleep_end > sleep_start
    if sleep_start is not None and sleep_end is not None and sleep_end > sleep_start:
        asleep_rows = [row for row in all_rows if sleep_start <= row.captured_at_utc <= sleep_end]
        pre_cool_rows = [row for row in all_rows if row.captured_at_utc <= sleep_start]
    else:
        asleep_rows = all_rows
        pre_cool_rows = []
    values = [float(row.temperature_c) for row in asleep_rows if row.temperature_c is not None]
    peak = max(values) if values else None
    low = min(values) if values else None
    last = values[-1] if values else None

    pre_cool_values = [
        float(row.temperature_c) for row in pre_cool_rows if row.temperature_c is not None
    ]
    if pre_cool_values:
        pre_cool_low = min(pre_cool_values)
        sleep_onset = pre_cool_values[-1]
        pre_cool_drop = max(0.0, pre_cool_values[0] - pre_cool_low)
    else:
        pre_cool_low = None
        sleep_onset = None
        pre_cool_drop = None
    # Credit either a material observed drop or a pre-bed low already below the
    # disruption threshold. The latter matters when the shared 21:30 chart
    # window begins after the largest part of an earlier-evening cool-down.
    pre_cool_credited = (pre_cool_low is not None and pre_cool_low <= threshold_low) or (
        pre_cool_drop is not None and pre_cool_drop >= 1.0
    )
    flags: list[str] = []
    if peak is not None and peak >= threshold_high:
        flags.append("thermal_disruption_likely")
    elif peak is not None and peak >= threshold_low:
        flags.append("thermal_disruption_watch")
    if pre_cool_credited:
        flags.append("precool_credited")
    elif pre_cool_low is not None and pre_cool_low > target_precool + 1.0:
        flags.append("precool_target_missed")
    if weather and weather.overnight_wind_gust_mph and weather.overnight_wind_gust_mph >= 30:
        flags.append("wind_disruption_watch")

    return {
        "sampleCount": len(values),
        "windowSource": "sleep" if has_sleep_window else "night_fallback",
        "indoorPeakC": peak,
        "indoorLowC": low,
        "indoorLastC": last,
        "preCoolLowC": pre_cool_low,
        "sleepOnsetC": sleep_onset,
        "preCoolDropC": pre_cool_drop,
        "targetPreCoolC": target_precool,
        "disruptionThresholdC": {"low": threshold_low, "high": threshold_high},
        "overnightWeatherLowC": weather.overnight_low_c if weather else None,
        "overnightWindMaxMph": weather.overnight_wind_max_mph if weather else None,
        "overnightWindGustMph": weather.overnight_wind_gust_mph if weather else None,
        "flags": flags,
    }


# Batch 86 (#159): the deterministic "Today" action list surfaced above the brief
# prose. Assembled from signals the packet already computes and frozen in
# verdict["todayActions"] — the same transport as swapSuggestion/weeklyMix — then
# rendered by the frontend TodayActions block. A workout action carries the real
# plannedWorkoutId so the frontend approves it through the existing rail; the approve
# affordance itself is gated live on delivery state in the UI (structured data
# durable, layout swappable).
_THERMAL_WARM_FLAGS = frozenset(
    {"thermal_disruption_likely", "thermal_disruption_watch", "precool_target_missed"}
)


def _todays_bike_workout(planned_workouts: Sequence[PlannedWorkout]) -> PlannedWorkout | None:
    for workout in planned_workouts:
        if workout.status in {"completed", "skipped"}:
            continue
        if is_bike_workout_type(workout.workout_type):
            return workout
    return None


def _verdict_adjustment_packet(
    status: str, planned_workouts: Sequence[PlannedWorkout]
) -> dict[str, Any] | None:
    """The deterministic Amber/Red adjustment for today's ride, for the packet.

    Batch 173.3: built from the *same* ``adjust_ir_for_verdict`` transform the
    delivery rail and the interval editor use, so the narrative and brief-chat can
    quote the app's own duration/%FTP figures. Explanatory only — returns ``None``
    on Green, a rest/no-ride day, or a malformed ride, and never influences the
    verdict or the numbers.

    Batch 215.5: the day's other sessions are resolved here, from the planned
    workouts already in hand, so the figure the brief quotes carries the same
    combined-load gate the delivery rail applies.
    """
    if status not in {"Amber", "Red"}:
        return None
    ride = _todays_bike_workout(planned_workouts)
    if ride is None:
        return None
    try:
        base_ir = build_structured_workout_ir(ride)
    except HTTPException:
        return None
    companion = companion_session_present(
        workout.status for workout in planned_workouts if workout.id != ride.id
    )
    summary = summarize_verdict_adjustment(base_ir, status, companion_session=companion)
    if summary is None:
        return None
    return {**summary, "plannedWorkoutId": str(ride.id)}


def _eased_ride_detail(status: str, adjustment: Mapping[str, Any] | None = None) -> str:
    if isinstance(adjustment, Mapping):
        adjusted_min = adjustment.get("adjustedDurationMin")
        adjusted_power = adjustment.get("adjustedWorkPowerPct")
        if isinstance(adjusted_min, int) and isinstance(adjusted_power, int):
            if adjustment.get("intensityHeldAtEndurance"):
                # Batch 215: on Red this is now reachable too — an already-Zone-2
                # ride keeps its intensity, so the copy must stop calling it a
                # recovery substitution.
                return (
                    f"Hold Zone 2 (~{adjusted_power}% FTP) but cut to {adjusted_min} min "
                    "— shorter, not harder."
                )
            if status == "Red":
                return (
                    f"Substitute recovery — no intervals, ~{adjusted_power}% FTP "
                    f"for {adjusted_min} min."
                )
            return f"Ease to ~{adjusted_power}% FTP and cut to {adjusted_min} min — no HIT/VO2."
    if status == "Red":
        return "Substitute recovery, mobility, or rest — no intervals."
    return "Cut duration 20-30%, ease hard intervals a zone, hold Zone 2, no HIT/VO2."


def _thermal_action(thermal_review: Mapping[str, Any]) -> dict[str, Any] | None:
    flags = thermal_review.get("flags")
    if not isinstance(flags, list) or not any(flag in _THERMAL_WARM_FLAGS for flag in flags):
        return None
    peak = thermal_review.get("indoorPeakC")
    target = thermal_review.get("targetPreCoolC")
    detail: str | None = None
    if isinstance(peak, int | float) and not isinstance(peak, bool):
        detail = f"Bedroom peaked at {peak:.1f}°C overnight"
        detail += (
            f" (pre-cool target {target:.0f}°C)."
            if isinstance(target, int | float) and not isinstance(target, bool)
            else "."
        )
    return {
        "kind": "thermal",
        "title": "Pre-cool the bedroom tonight",
        "detail": detail,
        "plannedWorkoutId": None,
        "targetDate": None,
        "href": "/environment",
    }


def build_today_actions(
    *,
    verdict: Mapping[str, Any],
    planned_workouts: Sequence[PlannedWorkout],
    thermal_review: Mapping[str, Any],
    recommend_breathwork: bool,
    max_actions: int = 4,
) -> list[dict[str, Any]]:
    """Assemble the deterministic "Today" action list for the morning brief.

    Ordering follows the coaching priority: lead with the week swap (Mark's
    rearrange-first instinct, #139), then the eased-ride approval, then the sleep
    and thermal nudges. Every entry is scannable on its own and, where it references
    a workout, tappable through the rail the frontend already uses.
    """
    actions: list[dict[str, Any]] = []
    status = str(verdict.get("status") or "")

    swap = verdict.get("swapSuggestion")
    if isinstance(swap, dict) and swap.get("hardWorkoutId"):
        hard_day = swap.get("hardWeekday") or "the planned day"
        move_to = swap.get("moveToWeekday") or swap.get("moveToDate")
        bring_forward = swap.get("bringForwardTitle")
        actions.append(
            {
                "kind": "apply_swap",
                "title": (
                    f"Move {swap.get('hardTitle', 'the hard session')} from {hard_day} to {move_to}"
                ),
                "detail": (
                    f"Pull {bring_forward} forward to {hard_day}." if bring_forward else None
                ),
                "plannedWorkoutId": swap.get("hardWorkoutId"),
                "targetDate": swap.get("moveToDate"),
                "href": None,
            }
        )

    chronic_action = verdict.get("chronicAction")
    chronic_deload = (
        isinstance(chronic_action, Mapping)
        and chronic_action.get("triggered") is True
        and chronic_action.get("kind") == "deload_proposal"
    )
    if status in {"Amber", "Red"} or chronic_deload:
        ride = _todays_bike_workout(planned_workouts)
        if ride is not None:
            actions.append(
                {
                    "kind": "approve_ride",
                    "title": (
                        "Approve today's eased ride"
                        if status in {"Amber", "Red"}
                        else "Approve today's deload ride"
                    ),
                    "detail": (
                        _eased_ride_detail(status, verdict.get("verdictAdjustment"))
                        if status in {"Amber", "Red"}
                        else "Sustained recovery strain: cut duration 25%, drop a zone, no HIT/VO2."
                    ),
                    "plannedWorkoutId": str(ride.id),
                    "targetDate": None,
                    "href": None,
                }
            )

    if recommend_breathwork:
        actions.append(
            {
                "kind": "sleep",
                "title": "Add a wind-down breathwork session tonight",
                "detail": "Helps down-regulate the recovery signal before bed.",
                "plannedWorkoutId": None,
                "targetDate": None,
                "href": "/sleep",
            }
        )

    thermal = _thermal_action(thermal_review)
    if thermal is not None:
        actions.append(thermal)

    return actions[:max_actions]


def _yesterday_load_packet(
    activities: Sequence[Activity],
    analyses: Sequence[Analysis],
    daily_metric: DailyMetric | None = None,
) -> dict[str, Any]:
    coverage = (
        daily_aggregate_coverage(daily_metric.calendar_date, daily_metric.raw_payload)
        if daily_metric is not None
        else None
    )
    whole_day_cost = {
        "calendarDate": (
            daily_metric.calendar_date.isoformat() if daily_metric is not None else None
        ),
        "allDayStressAvg": (
            complete_stress_avg(daily_metric) if daily_metric is not None else None
        ),
        "bodyBatteryDrained": (
            complete_body_battery_drained(daily_metric) if daily_metric is not None else None
        ),
        "bodyBatteryEnd": (
            complete_body_battery_end(daily_metric) if daily_metric is not None else None
        ),
        "coverage": (
            coverage_packet(coverage)
            if coverage is not None
            else {
                "status": "unknown",
                "stressStatus": "unknown",
                "bodyBatteryStatus": "unknown",
                "asOfLocal": None,
            }
        ),
        "classificationImpact": "none",
    }
    if not activities:
        return {
            "activityCount": 0,
            "status": "none",
            "statusScope": "exercise_only",
            "totalTrainingLoad": 0,
            "totalDurationMin": 0,
            "hardestActivity": None,
            "postSessionAnalyses": [],
            "wholeDayCost": whole_day_cost,
        }

    def load_score(activity: Activity) -> float:
        return max(
            float(activity.training_load or 0),
            float(activity.aerobic_training_effect or 0) * 40,
            float(activity.anaerobic_training_effect or 0) * 45,
            float(activity.intensity_factor or 0) * 160,
        )

    total_load = round(sum(float(activity.training_load or 0) for activity in activities), 1)
    total_duration_min = round(
        sum(float(activity.duration_sec or 0) for activity in activities) / 60
    )
    max_aerobic_te = _max_optional(activity.aerobic_training_effect for activity in activities)
    max_anaerobic_te = _max_optional(activity.anaerobic_training_effect for activity in activities)
    max_intensity_factor = _max_optional(activity.intensity_factor for activity in activities)
    hardest = max(activities, key=load_score)
    status = _yesterday_load_status(
        total_training_load=total_load,
        max_aerobic_te=max_aerobic_te,
        max_anaerobic_te=max_anaerobic_te,
        max_intensity_factor=max_intensity_factor,
        total_duration_min=total_duration_min,
    )
    analyses_by_activity: dict[uuid.UUID, Analysis] = {}
    for analysis in analyses:
        if analysis.activity_id is not None and analysis.activity_id not in analyses_by_activity:
            analyses_by_activity[analysis.activity_id] = analysis

    return {
        "activityCount": len(activities),
        "status": status,
        "statusScope": "exercise_only",
        "totalTrainingLoad": total_load,
        "totalDurationMin": total_duration_min,
        "maxAerobicTrainingEffect": max_aerobic_te,
        "maxAnaerobicTrainingEffect": max_anaerobic_te,
        "maxIntensityFactor": max_intensity_factor,
        "hardestActivity": {
            "activityId": str(hardest.id),
            "name": hardest.activity_name,
            "type": hardest.activity_type,
            "durationMin": round(float(hardest.duration_sec or 0) / 60),
            "trainingLoad": hardest.training_load,
            "aerobicTrainingEffect": hardest.aerobic_training_effect,
            "anaerobicTrainingEffect": hardest.anaerobic_training_effect,
            "intensityFactor": hardest.intensity_factor,
        },
        "postSessionAnalyses": [
            {
                "activityId": str(activity.id),
                "analysisType": analyses_by_activity[activity.id].analysis_type,
                "summary": _analysis_summary(analyses_by_activity[activity.id]),
            }
            for activity in activities
            if activity.id in analyses_by_activity
        ],
        "wholeDayCost": whole_day_cost,
    }


def _yesterday_load_status(
    *,
    total_training_load: float,
    max_aerobic_te: float | None,
    max_anaerobic_te: float | None,
    max_intensity_factor: float | None,
    total_duration_min: int,
) -> str:
    if (
        total_training_load >= 150
        or (max_aerobic_te is not None and max_aerobic_te >= 3.5)
        or (max_anaerobic_te is not None and max_anaerobic_te >= 2.0)
        or (
            max_intensity_factor is not None
            and max_intensity_factor >= 0.85
            and total_duration_min >= 45
        )
    ):
        return "hard"
    if total_training_load >= 75 or total_duration_min >= 60:
        return "moderate"
    return "easy"


def _max_optional(values: Iterable[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return max(present) if present else None


def _analysis_summary(analysis: Analysis) -> str:
    text = " ".join(analysis.output_markdown.split())
    return text[:500]


def _training_load_cap(
    training_load: Mapping[str, Any] | None,
) -> dict[str, Any]:
    signal = training_load or {}
    acwr = _coerce_float(signal.get("acuteChronicLoadRatio"))
    recovery_time_min = _coerce_int(signal.get("recoveryTimeMin"))
    sources: list[str] = []
    reasons: list[str] = []

    if acwr is not None and acwr >= ACWR_AMBER_CAP_THRESHOLD:
        sources.append("acute_chronic_load_ratio")
        reasons.append(
            "Training load sets an Amber ceiling: acute:chronic load ratio "
            f"{acwr:.2f} is at or above {ACWR_AMBER_CAP_THRESHOLD:.2f}."
        )
    if recovery_time_min is not None and recovery_time_min > RECOVERY_TIME_AMBER_CAP_MIN:
        sources.append("recovery_time")
        recovery_hours = recovery_time_min / 60
        reasons.append(
            "Training load sets an Amber ceiling: Garmin recovery time "
            f"{recovery_hours:.1f} hours is beyond 24 hours."
        )

    return {
        "triggered": bool(sources),
        "applied": False,
        "sources": sources,
        "acuteChronicLoadRatio": acwr,
        "recoveryTimeMin": recovery_time_min,
        "thresholds": {
            "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD,
            "recoveryTimeMinExclusive": RECOVERY_TIME_AMBER_CAP_MIN,
        },
        "reasons": reasons,
    }


def _load_driven_eligibility(
    training_load: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Whether load is affirmative evidence for relaxing a Low readiness.

    The exception is intentionally narrower than the one-way Amber cap: ACWR
    must be present and inside the app's balanced range, while a recovery clock
    beyond the cap boundary vetoes the escape. Missing evidence is unknown.
    """
    signal = training_load or {}
    acwr = _coerce_float(signal.get("acuteChronicLoadRatio"))
    recovery_time_min = _coerce_int(signal.get("recoveryTimeMin"))
    acwr_benign = acwr is not None and acwr <= ACWR_LOAD_DRIVEN_MAX
    recovery_time_benign = (
        recovery_time_min is None or recovery_time_min <= RECOVERY_TIME_AMBER_CAP_MIN
    )
    return {
        "eligible": acwr_benign and recovery_time_benign,
        "acuteChronicLoadRatio": acwr,
        "recoveryTimeMin": recovery_time_min,
        "acuteChronicLoadRatioBenign": acwr_benign,
        "recoveryTimeBenign": recovery_time_benign,
        "thresholds": {
            "acuteChronicLoadRatioMaxInclusive": ACWR_LOAD_DRIVEN_MAX,
            "recoveryTimeMinMaxInclusive": RECOVERY_TIME_AMBER_CAP_MIN,
        },
    }


def _has_hrv_measurement(daily_metric: DailyMetric | None, sleep: Sleep | None) -> bool:
    return any(
        value is not None
        for value in (
            daily_metric.hrv_weekly_avg_ms if daily_metric else None,
            daily_metric.hrv_last_night_avg_ms if daily_metric else None,
            sleep.avg_overnight_hrv_ms if sleep else None,
        )
    )


def _positive_hrv_evidence(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    hrv_status: str | None,
    hrv_below_baseline: bool,
) -> bool:
    return (
        _has_hrv_measurement(daily_metric, sleep)
        and not hrv_below_baseline
        and hrv_status in {"balanced", "stable", "optimal", "normal"}
    )


def _readiness_score_ok(
    daily_metric: DailyMetric | None,
    *,
    readiness_floor: float,
) -> bool:
    if daily_metric is None:
        return False
    readiness_level = _lower(daily_metric.readiness_level)
    readiness_score = daily_metric.readiness_score
    return readiness_level not in {"low", "poor"} and (
        readiness_score is not None and readiness_score >= readiness_floor
    )


def _resting_hr_elevated(
    daily_metric: DailyMetric | None,
    baseline: MetricBaseline | None,
) -> bool:
    resting_hr = daily_metric.resting_heart_rate_bpm if daily_metric else None
    ceiling = baseline.upper_quartile_value if baseline else None
    return resting_hr is not None and ceiling is not None and float(resting_hr) > float(ceiling)


def _sleep_credit_ceiling(
    *,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    positive_hrv_evidence: bool,
    resting_hr_in_band: bool,
    readiness_ok: bool,
    positive_subjective_evidence: bool,
) -> dict[str, Any]:
    raw_sleep_score = sleep.score if sleep is not None else None
    crossed_red = (
        raw_sleep_score is not None
        and raw_sleep_score < 60
        and age_adjusted_sleep_score is not None
        and age_adjusted_sleep_score >= 60
    )
    crossed_green = (
        raw_sleep_score is not None
        and raw_sleep_score < 74
        and age_adjusted_sleep_score is not None
        and age_adjusted_sleep_score >= 74
    )
    objective_recovery_corroborated = positive_hrv_evidence and resting_hr_in_band and readiness_ok
    exception_evidence_complete = objective_recovery_corroborated and positive_subjective_evidence
    # Age scoring may move a raw-Red night into Amber, but never all the way to
    # Green. A crossing of only the Green line keeps Batch 170's complete-
    # corroboration exception.
    allowed_green = not crossed_red and ((not crossed_green) or exception_evidence_complete)
    reason = None
    if crossed_red:
        reason = (
            "The raw Garmin sleep score is below 60; age adjustment may lift the "
            "night to Amber but cannot carry it to Green."
        )
    elif crossed_green and not allowed_green:
        reason = (
            "Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score "
            "is below 74 without complete measured recovery and check-in evidence."
        )
    return {
        "rawSleepScore": raw_sleep_score,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "crossedRedThreshold": crossed_red,
        "crossedGreenThreshold": crossed_green,
        "maximumStatus": "Amber" if crossed_red else None,
        "corroboratedByObjectiveRecovery": objective_recovery_corroborated,
        "positiveSubjectiveEvidence": positive_subjective_evidence,
        "exceptionEvidenceComplete": exception_evidence_complete,
        "allowedGreen": allowed_green,
        "applied": False,
        "reason": reason,
    }


def _morning_verdict(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    manual_entries: Sequence[ManualEntry],
    planned_workouts: Sequence[PlannedWorkout],
    baselines: Mapping[str, MetricBaseline] | None = None,
    yesterday_load: Mapping[str, Any] | None = None,
    training_load: Mapping[str, Any] | None = None,
    readiness_baseline_trend: Mapping[str, Any] | None = None,
    breathwork_brief: BreathworkBriefResult | None = None,
    rest_day: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    subjective_score = _latest_subjective_score(manual_entries)
    hrv_status = _lower(daily_metric.hrv_status if daily_metric else None) or _lower(
        sleep.hrv_status if sleep else None
    )
    hrv_low = _hrv_below_baseline(daily_metric)
    readiness_level = _lower(daily_metric.readiness_level if daily_metric else None)
    baselines = baselines or {}
    resting_hr_baseline = baselines.get("resting_heart_rate_bpm")
    resting_hr_in_band = metric_within_baseline_band(
        daily_metric.resting_heart_rate_bpm if daily_metric else None,
        resting_hr_baseline,
        lower_is_better=True,
    )
    resting_hr_elevated = _resting_hr_elevated(daily_metric, resting_hr_baseline)
    readiness_center = baseline_center(baselines.get("readiness_score"))
    readiness_floor = effective_readiness_floor(readiness_center)
    readiness_trend = dict(
        readiness_baseline_trend
        or {
            "metricKey": "readiness_score",
            "status": "not_evaluated",
            "triggered": False,
            "verdictImpact": "warning_only",
            "reason": None,
        }
    )
    rest_day = rest_day or {}
    is_rest_day = bool(rest_day.get("isRestDay"))
    has_vo2 = not is_rest_day and any(
        _workout_has_vo2_intensity(workout)
        for workout in planned_workouts
        if workout.status not in {"completed", "skipped"}
    )
    positive_hrv_evidence = _positive_hrv_evidence(
        daily_metric=daily_metric,
        sleep=sleep,
        hrv_status=hrv_status,
        hrv_below_baseline=hrv_low,
    )
    readiness_ok_for_override = _readiness_score_ok(
        daily_metric,
        readiness_floor=readiness_floor,
    )
    positive_subjective_evidence = subjective_score is not None and subjective_score >= 5
    recovery_signals_good = (
        (age_adjusted_sleep_score is not None and age_adjusted_sleep_score >= 74)
        and positive_hrv_evidence
        and positive_subjective_evidence
    )
    soft_sleep_override = _soft_sleep_recovery_override(
        age_adjusted_sleep_score=age_adjusted_sleep_score,
        subjective_score=subjective_score,
        hrv_status=hrv_status,
        hrv_below_baseline=hrv_low,
        positive_hrv_evidence=positive_hrv_evidence,
        resting_hr_in_band=resting_hr_in_band,
        readiness_ok=readiness_ok_for_override,
    )
    yesterday_hard = (yesterday_load or {}).get("status") == "hard"
    training_load_cap = _training_load_cap(training_load)
    load_driven_eligibility = _load_driven_eligibility(training_load)
    sleep_credit_ceiling = _sleep_credit_ceiling(
        sleep=sleep,
        age_adjusted_sleep_score=age_adjusted_sleep_score,
        positive_hrv_evidence=positive_hrv_evidence,
        resting_hr_in_band=resting_hr_in_band,
        readiness_ok=readiness_ok_for_override,
        positive_subjective_evidence=positive_subjective_evidence,
    )

    reasons: list[str] = []
    readiness_interpretation = None
    if readiness_level == "poor":
        reasons.append("Garmin readiness is Poor; keep the day cautious.")
    elif readiness_level == "low":
        if recovery_signals_good and load_driven_eligibility["eligible"]:
            readiness_interpretation = "load_driven"
            reasons.append(
                "Garmin readiness is Low, measured recovery is clean, and ACWR is "
                "inside the benign load-driven range."
            )
        else:
            reasons.append(
                "Garmin readiness is Low without complete recovery evidence and a "
                "proved-benign load signal to downplay it."
            )

    if age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 60:
        status = "Red"
        reasons.append("Age-adjusted sleep is below 60.")
    elif hrv_low and hrv_status in {"unbalanced", "low"}:
        status = "Red"
        reasons.append("HRV is below baseline and marked low/unbalanced.")
    elif readiness_level == "poor":
        status = "Amber"
    elif readiness_level == "low" and readiness_interpretation != "load_driven":
        status = "Amber"
    elif soft_sleep_override:
        status = "Green"
        reasons.append(
            "Age-adjusted sleep is soft, but measured HRV, resting HR, readiness, "
            "and the current check-in hold the day Green."
        )
    elif age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 74:
        status = "Amber"
        reasons.append("Age-adjusted sleep is below the 74+ green target.")
    elif hrv_status in {"unbalanced", "low", "poor"} or hrv_low:
        status = "Amber"
        reasons.append("HRV is not cleanly in range.")
    elif subjective_score is not None and subjective_score < 5:
        status = "Amber"
        reasons.append("Subjective score is below 5.")
    else:
        status = "Green"
        if positive_hrv_evidence and positive_subjective_evidence:
            reasons.append(
                "Sleep, measured HRV, and the current subjective signal clear the green rule."
            )
        elif positive_hrv_evidence:
            reasons.append(
                "Sleep and measured HRV clear the green rule; no current subjective "
                "check-in was used as positive evidence."
            )
        elif positive_subjective_evidence:
            reasons.append(
                "Sleep clears the green rule and the current check-in is positive; "
                "missing HRV is neutral, not positive evidence."
            )
        else:
            reasons.append(
                "Sleep clears the green rule; missing HRV/check-in data is neutral "
                "and did not provide positive evidence."
            )

    cumulative_escalation: dict[str, Any] = {
        "triggered": False,
        "applied": False,
        "readinessLevel": readiness_level,
        "negativeSignals": [],
        "reason": None,
    }
    if readiness_level == "poor":
        negative_signals: list[str] = []
        if age_adjusted_sleep_score is not None and 60 <= age_adjusted_sleep_score < 74:
            negative_signals.append("soft_sleep")
        if subjective_score is not None and subjective_score < 5:
            negative_signals.append("low_subjective")
        if yesterday_hard:
            negative_signals.append("hard_yesterday")
        if resting_hr_elevated:
            negative_signals.append("elevated_resting_heart_rate")
        cumulative_escalation["negativeSignals"] = negative_signals
        cumulative_escalation["triggered"] = bool(negative_signals)
        if status == "Amber" and negative_signals:
            status = "Red"
            cumulative_escalation["applied"] = True
            cumulative_escalation["reason"] = (
                "Garmin readiness is Poor and a second recovery signal is negative."
            )
            reasons.append(str(cumulative_escalation["reason"]))

    if status == "Green" and not sleep_credit_ceiling["allowedGreen"]:
        status = "Amber"
        sleep_credit_ceiling["applied"] = True
        reason = sleep_credit_ceiling.get("reason")
        if isinstance(reason, str):
            reasons.append(reason)

    status_before_load_cap = status
    if training_load_cap["triggered"]:
        if status == "Green":
            status = "Amber"
            training_load_cap["applied"] = True
        reasons.extend(training_load_cap["reasons"])
    training_load_cap["statusBeforeCap"] = status_before_load_cap
    baseline_trend_reason = readiness_trend.get("reason")
    if readiness_trend.get("triggered") and isinstance(baseline_trend_reason, str):
        reasons.append(baseline_trend_reason)

    plan_adjustments = _plan_adjustments(
        status,
        planned_workouts,
        is_rest_day=is_rest_day,
    )
    if status != "Green" and yesterday_hard and not is_rest_day:
        plan_adjustments.append(
            "Treat yesterday's hard session as extra context for easing today's work."
        )
    if status == "Red" and has_vo2:
        plan_adjustments.append("Replace VO2 with rest, mobility, or a very easy spin.")
    breathwork_signal = {
        "status": status,
        "readinessLevel": readiness_level,
        "readinessInterpretation": readiness_interpretation,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
    }
    if should_recommend_breathwork(breathwork_signal):
        plan_adjustments.append(
            _breathwork_recommendation(breathwork_brief, age_adjusted_sleep_score)
        )

    safety_rules = ["red_never_vo2"] if status == "Red" and has_vo2 else []
    if training_load_cap["triggered"]:
        safety_rules.append("training_load_amber_cap")
    if sleep_credit_ceiling["applied"]:
        safety_rules.append(
            "sleep_credit_red_ceiling"
            if sleep_credit_ceiling["crossedRedThreshold"]
            else "sleep_credit_green_ceiling"
        )
    if cumulative_escalation["applied"]:
        safety_rules.append("poor_readiness_cumulative_red")

    return {
        "status": status,
        "reasons": reasons,
        "readinessLevel": daily_metric.readiness_level if daily_metric else None,
        "readinessInterpretation": readiness_interpretation,
        "loadDrivenEligibility": load_driven_eligibility,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "subjectiveScore": subjective_score,
        "subjectiveLabel": subjective_score_label(subjective_score),
        "positiveSubjectiveEvidence": positive_subjective_evidence,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
        "positiveHrvEvidence": positive_hrv_evidence,
        "restingHeartRateWithinBaseline": resting_hr_in_band,
        "restingHeartRateElevated": resting_hr_elevated,
        "readinessBaselineCenter": readiness_center,
        "readinessAbsoluteFloor": SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
        "readinessEffectiveFloor": readiness_floor,
        "readinessBaselineTrend": readiness_trend,
        "softSleepRecoveryOverride": soft_sleep_override,
        "sleepCreditCeiling": sleep_credit_ceiling,
        "cumulativeEscalation": cumulative_escalation,
        "yesterdayLoadStatus": (yesterday_load or {}).get("status"),
        "trainingLoadCap": training_load_cap,
        "dayType": "rest" if is_rest_day else "training",
        "isRestDay": is_rest_day,
        "restDayReason": rest_day.get("reason"),
        "hasVo2WorkoutToday": has_vo2,
        "planAdjustments": plan_adjustments,
        "safetyRulesApplied": safety_rules,
    }


def should_recommend_breathwork(signal: Mapping[str, Any]) -> bool:
    status = str(signal.get("status") or "").lower()
    readiness_level = str(signal.get("readinessLevel") or "").lower()
    readiness_interpretation = signal.get("readinessInterpretation")
    hrv_status = str(signal.get("hrvStatus") or "").lower()
    hrv_below_baseline = bool(signal.get("hrvBelowBaseline"))
    readiness_is_recovery_low = (
        readiness_level in {"low", "poor"} and readiness_interpretation != "load_driven"
    )
    return (
        status == "red"
        or readiness_is_recovery_low
        or hrv_status in {"unbalanced", "low", "poor"}
        or hrv_below_baseline
    )


def _workout_has_vo2_intensity(workout: PlannedWorkout) -> bool:
    try:
        return ir_has_vo2(build_structured_workout_ir(workout))
    except HTTPException:
        return "vo2" in (workout.workout_type or "").lower()


def _breathwork_recommendation(
    breathwork_brief: BreathworkBriefResult | None,
    age_adjusted_sleep_score: int | None,
) -> str:
    context = ""
    if breathwork_brief is not None:
        week_start = breathwork_brief.as_of_date - timedelta(days=6)
        sessions_this_week = sum(
            1 for session in breathwork_brief.recent_sessions if session.session_date >= week_start
        )
        context = f" You've logged {sessions_this_week} breathwork session(s) in the last 7 days."
    sleep_context = (
        f" Age-adjusted sleep is {age_adjusted_sleep_score}."
        if age_adjusted_sleep_score is not None
        else ""
    )
    return (
        "Add a short breathwork session today to help down-regulate the recovery signal."
        f"{context}{sleep_context}"
    )


def _plan_adjustments(
    status: str,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    is_rest_day: bool = False,
) -> list[str]:
    live_workouts = [
        workout for workout in planned_workouts if workout.status not in {"completed", "skipped"}
    ]
    reset_week = any(_is_reset_week_workout(workout) for workout in live_workouts)
    if is_rest_day:
        adjustments = ["Today is an intentional rest day; keep paused or skipped sessions paused."]
    elif not planned_workouts:
        adjustments = ["No active planned workout found for today; keep advice conservative."]
    elif not live_workouts:
        adjustments = [
            "No live workout remains today; do not revive completed or skipped sessions."
        ]
    elif status == "Green":
        adjustments = ["Proceed with the planned workout if warm-up confirms readiness."]
    elif status == "Amber":
        adjustments = [
            "Cut duration 25%; hold Zone 2, ease harder intervals by a zone, and "
            f"convert former HIT/VO2 work to no more than {AMBER_POWER_CAP_PCT}% FTP "
            "(Sweet Spot)."
        ]
    else:
        # Batch 215: Red no longer means one thing. An already-Zone-2 ride keeps its
        # intensity and takes a light duration cut, so the instruction has to follow
        # the transform rather than assert a substitution that did not happen.
        adjustment = _verdict_adjustment_packet(status, planned_workouts)
        if isinstance(adjustment, Mapping) and adjustment.get("intensityHeldAtEndurance"):
            adjustments = [
                f"Hold Zone 2 (~{adjustment.get('adjustedWorkPowerPct')}% FTP) and cut to "
                f"{adjustment.get('adjustedDurationMin')} min; no intervals and no HIT/VO2. "
                "Sustained easy work builds sleep pressure — keep it, do not delete it."
            ]
        else:
            adjustments = ["Substitute recovery, mobility, or rest."]
    if reset_week:
        adjustments.insert(
            0,
            (
                "This week is an intended light reset; judge the reduced cycling load "
                "as planned deload, not missed load."
            ),
        )
    return adjustments


def _is_reset_week_workout(workout: PlannedWorkout) -> bool:
    structured = workout.structured_workout or {}
    if not isinstance(structured, dict):
        return False
    reset = structured.get("resetWeek")
    return isinstance(reset, dict) and reset.get("active") is True


def _latest_subjective_score(manual_entries: Sequence[ManualEntry]) -> int | None:
    for entry in manual_entries:
        if entry.subjective_score is not None:
            return entry.subjective_score
    return None


def _soft_sleep_recovery_override(
    *,
    age_adjusted_sleep_score: int | None,
    subjective_score: int | None,
    hrv_status: str | None,
    hrv_below_baseline: bool,
    positive_hrv_evidence: bool,
    resting_hr_in_band: bool,
    readiness_ok: bool,
) -> bool:
    if age_adjusted_sleep_score is None or not 60 <= age_adjusted_sleep_score < 74:
        return False
    # ``readiness_ok`` applies Mark's personal median anchored at 60 and requires
    # a measured score outside Garmin's Low/Poor categories. Missing HRV,
    # readiness, or check-in data is neutral and cannot satisfy this exception.
    return (
        not hrv_below_baseline
        and hrv_status in {"balanced", "stable", "optimal", "normal"}
        and positive_hrv_evidence
        and resting_hr_in_band
        and readiness_ok
        and subjective_score is not None
        and subjective_score >= 5
    )


def _hrv_below_baseline(daily_metric: DailyMetric | None) -> bool:
    if daily_metric is None:
        return False
    value = daily_metric.hrv_weekly_avg_ms or daily_metric.hrv_last_night_avg_ms
    low = daily_metric.hrv_baseline_low_ms
    return value is not None and low is not None and value < low


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _local_clock(value: datetime | None, timezone_name: str) -> str | None:
    """Render a naive-UTC timestamp as the user's local wall-clock time ("01:17").

    Bed/wake times are stored naive-UTC; DST is handled by ZoneInfo so a BST night
    (00:17Z) reads 01:17 and a GMT night (07:31Z) reads 07:31. Batch 91 (#164)."""
    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return value.replace(tzinfo=UTC).astimezone(timezone).strftime("%H:%M")


def _date_label(value: date) -> str:
    """Authoritative human header date, e.g. "Sunday 12 July 2026".

    Avoids the platform-specific %-d directive so it is portable. Batch 91 (#164)."""
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B %Y')}"


def subjective_score_label(score: int | None) -> str | None:
    """Map the numeric check-in score to the nearest word anchor.

    Source of truth for the anchors is the frontend feel scale
    (apps/web/src/lib/subjectiveFeel.ts): 2=Rough, 4=Meh, 6=OK, 8=Good,
    10=Great. The read always speaks his word, never the raw 0-10 number.
    Batch 91 (#164), extended to the full 0-10 input in Batch 146."""
    if score is None:
        return None
    if score <= 3:
        return "Rough"
    if score <= 5:
        return "Meh"
    if score <= 7:
        return "OK"
    if score <= 9:
        return "Good"
    return "Great"


def _minutes(seconds: int | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None


def _time_in_bed_min(row: Sleep) -> int | None:
    """Total time in bed (the bed->wake window), in minutes. Batch 142.

    Garmin's ``duration_sec`` (sleepTimeSeconds) is time *asleep* — it already
    excludes the awake window — so it must never be presented as time in bed.
    Prefer the actual bed->wake span; when a bed/wake timestamp is missing (or is
    non-sensical), fall back to summing asleep + awake + brief unmeasurable time so
    the model still gets a labelled in-bed total. Returns None only when neither a
    valid window nor any component total is available."""
    start = row.sleep_start_utc
    end = row.sleep_end_utc
    if start is not None and end is not None:
        window_sec = (end - start).total_seconds()
        if window_sec >= 0:
            return round(window_sec / 60)
    components = (row.duration_sec, row.awake_sleep_sec, row.unmeasurable_sleep_sec)
    if all(value is None for value in components):
        return None
    return round(sum(value or 0 for value in components) / 60)


def _first_not_none[T](*values: T | None) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def _lower(value: str | None) -> str | None:
    return value.lower() if value else None
