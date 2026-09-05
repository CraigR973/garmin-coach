"""Morning packet assembly and Claude boundary.

The deterministic decision policy lives in ``services.morning_verdict``. The
private aliases imported below preserve the established test/import surface
while callers migrate to the named module.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from src.config import settings
from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
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
from src.services.age_norms import (
    REM_FRAMING_RULE,
    SLEEP_STAGE_MINUTES_RULE,
    SLEEP_STAGE_PCT_BASIS,
    build_age_comparison,
    rem_sleep_pct_for_row,
)
from src.services.anthropic_text import (
    configured_effort,
    configured_thinking,
    generate_anthropic_text,
)
from src.services.bedroom_overnight import night_window
from src.services.body_metrics import resolve_effective_vo2max, resolve_effective_weight_kg
from src.services.breathwork_brief import BreathworkBriefResult, BreathworkBriefService
from src.services.bulk_history_reads import temperature_series_columns
from src.services.chronic_patterns import (
    CHRONIC_DELOAD_WINDOW_DAYS,
    ChronicPatternSuggestionService,
)
from src.services.coach_policy import (
    PACKET_FIELD_NAMES_RULE,
    RECORDED_DATA_HONESTY_RULE,
    source_basis,
)
from src.services.coach_sections import (
    as_mapping as _as_mapping,
)
from src.services.coach_sections import (
    coerce_float as _coerce_float,
)
from src.services.coach_sections import (
    coerce_int as _coerce_int,
)
from src.services.coach_sections import (
    daily_metric_packet as _daily_metric_packet,
)
from src.services.coach_sections import (
    environment_section,
    knowledge_base_section,
)
from src.services.coach_sections import (
    thermal_review as _thermal_review,
)
from src.services.coaching_state import CoachingStateService
from src.services.daily_metric_coverage import (
    complete_body_battery_charged,
    complete_body_battery_drained,
    complete_body_battery_end,
    complete_stress_avg,
    coverage_packet,
    daily_aggregate_coverage,
    morning_body_battery_charged,
)
from src.services.daily_metric_phase import (
    morning_first_order,
    prefer_morning,
    settled_first_order,
)
from src.services.experiment_loop import ExperimentLoopService, rotation_from_assignment
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
from src.services.insights import InsightsService
from src.services.learned_context import (
    LEARNED_CONTEXT_PROMPT_GUARDRAIL,
)
from src.services.morning_inputs import (
    morning_input_presence,
    morning_packet_input_presence,
)
from src.services.morning_output_contract import (
    missing_morning_output_sections,
    morning_output_contract_packet,
    morning_output_contract_prompt,
)
from src.services.morning_verdict import (  # noqa: F401 — compatibility re-exports
    ACWR_AMBER_CAP_THRESHOLD,
    ACWR_LOAD_DRIVEN_MAX,
    RECOVERY_TIME_AMBER_CAP_MIN,
    _plan_adjustments,
    _todays_bike_workout,
    _verdict_adjustment_packet,
    should_recommend_breathwork,
    subjective_score_label,
)
from src.services.morning_verdict import (
    morning_verdict as _morning_verdict,
)
from src.services.personal_baselines import (
    SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,  # noqa: F401 — compatibility re-export
    baseline_band_packet,
    baseline_lookup,
    readiness_baseline_trend,
)
from src.services.post_walk_analysis import active_recovery_walk_context
from src.services.prompt_metadata import prompt_system_hash
from src.services.sleep_scoring import (
    age_adjusted_sleep_score as compute_age_adjusted_sleep_score,
)
from src.services.standing_habits import SECTION as STANDING_HABITS_SECTION
from src.services.training_week import TrainingWeekService
from src.services.verdict_scaling import AMBER_POWER_CAP_PCT, ENDURANCE_PRESCRIPTION_PCT
from src.services.workload_budget import workload_slot

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

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
# Batch 244: the four-section prose list had become a deletion instruction once
# experiments and chronic actions joined the packet. The output contract is now
# packet-derived and structurally checked, so existing reads must regenerate.
# Batch 243: verdict-adjustment geometry, companion-load scaling, and deterministic
# session-specific instructions changed. Generation identity does not hash the
# packet, so the version must move or today's pre-fix verdict remains current.
# Batch 252: the same rule applies again. verdict.verdictAdjustment gained
# keptAsEndurance/endurancePrescriptionPct, intensityHeldAtEndurance narrowed to
# mean "the number did not move", the Zone-2 prescription anchor moved the
# adjusted %FTP a 68-75% ride resolves to, and verdict.chronicAction gained the
# training-debt exclusion bounds. The packet and these instructions both changed,
# so v43 would otherwise be served as current on the day this ships.
# Batch 250: and again, for both halves at once. REM_FRAMING_RULE — embedded
# verbatim in this prompt — now requires the read to state that the REM figure is
# a wrist-device estimate whose early-night component is probably under-counted,
# which is an instruction v44 never carried; and ageComparison gained
# sleepBandBasis and remMeasurementBasis, so the packet changed underneath it too.
# A v44 brief was written under neither.
PROMPT_VERSION = "morning-analysis-v46-2026-09-04"
ANALYSIS_TYPE = "morning"
# Batch 231: the packet used to hand the model a sentence calling the twelfth
# of thirteen drivers "the strongest measured lever". The packet no longer says
# that, and this rule stops the model reintroducing the claim from its own
# reading of a coefficient.
CHRONIC_DRIVER_RULE = """chronicSuggestions.items[].driver is a correlation
measured in the user's own history, never a demonstrated cause. Describe it with
the strength the object actually carries and restate any confounds entry in your
own plain words. Never call it the strongest lever, the cause, or a proven fix,
and never name a driver the packet did not select — when driver is absent, say
the data does not yet point at a single lever rather than nominating one
yourself."""

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
{RECORDED_DATA_HONESTY_RULE}
Refer to Mark's daily check-in by its word — verdict.subjectiveLabel /
manualEntries[].subjectiveLabel (e.g. "you said you felt OK") — and never surface
the raw subjectiveScore number or a "6/10"-style term for how he felt.
Return concise markdown that follows the packet-derived required output contract
in the user prompt. Include every required section under its exact heading; never
silently drop a section because the packet has grown since an earlier prompt.
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
verdict.acutePhysiology is deterministic and authoritative. Never soften or
argue down an RHR/HRV Amber cap, the missing-data floor, or an oxygen/respiration
surveillance escalation. When requiresBikeRest is true, do not recommend an
eased ride, a substitute ride, or training through the signal. The app renders
acutePhysiology.standingLine and acutePhysiology.escalations outside your prose,
so do not repeat or paraphrase either; explain only the measured evidence when
it belongs in a required section, and never diagnose a condition from wearable
data.
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
"Deep 17% is within the healthy 50-59 range; Garmin only flags it against a younger
target"). Every sleepRows percentage is a share of the same denominator, stated in
ageComparison.sleepStagePctBasis: say what that total is, in your own plain words,
on **every** stage percentage you give, not once per read — a percentage without
its denominator is the figure Mark cannot reconcile against his watch. {PACKET_FIELD_NAMES_RULE}
{SLEEP_STAGE_MINUTES_RULE}
{REM_FRAMING_RULE}
{CHRONIC_DRIVER_RULE}
Read REM against metricsVsBaselines.rem_sleep_pct, whose own basis field says
which total it is a percentage of, and whose ageFrame carries the band; the two
frames describe one night, so never present them as two measurements of it.
knowledgeBase.trainingSchedule describes the user's usual routine only;
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
session. wholeDayCost.baselines holds Mark's own distribution for those figures,
keyed by the same field names. Where an entry carries baselineMedian, state the
figure together with that median and deltaVsBaseline — "yesterday drained 66,
dead on your 67 median" — and never also state the same figure bare: the compared
form replaces it, it is not an addition to it. Where an entry carries
unavailableReason instead, say plainly that the app has no personal baseline for
that figure rather than describing it as normal, high, or low. A figure with no
entry at all has no value this morning and must not be discussed.
experimentLoop.experiments carries the app's current deterministic evaluation of
each active experiment. Report a supported or refuted result when relevant; for
an inconclusive or insufficient result, state the first supplied reason and the
coverage still needed rather than inventing a direction. Never auto-conclude an
experiment: every conclusion is human-gated. The app already derives REM minutes,
REM percentage and awake minutes from the hypnogram and records them in nightly
observations, so never ask Mark to notice, remember or manually track whether those
sleep outcomes occurred. The only evidence the app cannot derive is whether he
actually applied an issued REM intervention; it is acceptable to ask him to record
that in the check-in. Unknown application is unknown, never "not applied".
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
or duration. When verdictAdjustment.keptAsEndurance is true the ride stays a
Zone 2 endurance ride. This holds on Red as well as Amber: the day is a shortened
Zone 2, not a recovery substitution, so do not describe the session as substituted,
replaced or dropped to recovery, and do not tell him to swap it for rest. Sustained
easy work builds sleep pressure without the arousal harder work produces, which is
why Red keeps it; the hard work is still gone. Within that,
verdictAdjustment.intensityHeldAtEndurance says whether the intensity itself moved:
when true the ride is only shortened, not dropped in intensity — say so rather than
implying a zone drop; when false it was eased to the plan's
{ENDURANCE_PRESCRIPTION_PCT}% FTP Zone 2 anchor, a small
reduction inside Zone 2 that is still not a recovery substitution.
When verdictAdjustment.companionSession is true the day already holds another
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
dailyMetrics.vo2max and the ageComparison VO2 max row carry that same reading and
the same rule: dailyMetrics.vo2maxAsOfDate states the day it was measured, so
treat all three as one figure rather than as separate readings to compare.
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
restate them as a duplicated checklist or a generic "Actions" header. Follow the
packet-derived section order; reference a Today action in prose only where the
reasoning needs it."""
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
        self.thinking = configured_thinking()
        self.effort = configured_effort()

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
            thinking=self.thinking,
            effort=self.effort,
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
        recent_daily_metrics, recent_sleeps = await self._acute_physiology_history(
            player.id, subject_date
        )
        # Batch 226: the stored baselines are already loaded above, and this is the
        # one packet holding a *finished* day's cost — so it is the only place the
        # comparison Mark asked for can honestly be made.
        yesterday_load = await self._yesterday_load(
            player.id, subject_date, player.timezone, baselines
        )
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
        age_comparison = _age_comparison(
            daily_metric, sleep, knowledge_base, vo2max=effective_vo2max
        )
        # Batch 230: the age comparison is computed first now because the metrics
        # table needs REM's population frame, and `yesterday_load` (already built
        # above) supplies the closed-day drain the table used to withhold. Both
        # are reads of values these callers have; nothing new is queried.
        metrics_table = _metrics_vs_baselines(
            daily_metric,
            sleep,
            baselines,
            age_adjusted_sleep_score,
            day_aggregates=day_aggregate_metric,
            age_comparison=age_comparison,
            closed_day_cost=yesterday_load.get("wholeDayCost"),
        )
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
        daily_metric_packet = _daily_metric_packet(
            daily_metric, vo2max=effective_vo2max, vo2max_as_of_date=vo2max_as_of_date
        )
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
            recent_daily_metrics=recent_daily_metrics,
            recent_sleeps=recent_sleeps,
            enforce_data_sufficiency=True,
        )
        # Batch 221: persist the exact REM library selection before it is shown,
        # then reuse that immutable weekly assignment on every surface. The
        # current cached driver report is the same evidence Daily Loop uses.
        experiment_loop = ExperimentLoopService(self.session)
        current_rem_assignment = await experiment_loop.current_assignment(
            player.id,
            as_of=subject_date,
        )
        rem_rotation = rotation_from_assignment(current_rem_assignment)
        drivers_report = await InsightsService(self.session).cached_drivers(
            player,
            as_of=subject_date,
        )
        # Batch 171: keep the chronic card's existing advisory copy, but derive a
        # separate deterministic structural-action signal from protected
        # recovery-marker misses or a qualified Red-morning cluster. The current
        # verdict is supplied explicitly because it has not been persisted yet.
        chronic_result = await ChronicPatternSuggestionService(self.session).suggestions(
            player,
            as_of=subject_date,
            driver_outcomes=drivers_report.outcomes,
            sleep_protocol=knowledge_base.get("sleep_protocol", {}),
            standing_habits=knowledge_base.get(STANDING_HABITS_SECTION, {}),
            current_verdict=str(verdict.get("status") or ""),
            rem_rotation=rem_rotation,
        )
        local_today = datetime.now(ZoneInfo(player.timezone)).date()
        if current_rem_assignment is None and subject_date == local_today:
            selected_rotation = next(
                (
                    item.rotation
                    for item in chronic_result.items
                    if item.metric_key == "rem_sleep_pct" and item.rotation is not None
                ),
                None,
            )
            if selected_rotation is not None:
                current_rem_assignment = await experiment_loop.ensure_assignment(
                    player,
                    as_of=subject_date,
                    actions=list(selected_rotation.actions),
                    rotation=selected_rotation,
                    commit=False,
                )
        await experiment_loop.record_nightly_observations(
            player,
            subject_date=subject_date,
            commit=False,
        )
        experiment_loop_packet = await experiment_loop.packet(
            player,
            subject_date=subject_date,
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
        acute_physiology = verdict.get("acutePhysiology")
        requires_bike_rest = bool(
            isinstance(acute_physiology, Mapping)
            and acute_physiology.get("requiresBikeRest") is True
        )
        actionable_workouts = (
            [] if rest_day["isRestDay"] or requires_bike_rest else planned_workouts
        )
        verdict["verdictAdjustment"] = _verdict_adjustment_packet(
            str(verdict.get("status") or ""),
            actionable_workouts,
        )
        verdict["todayActions"] = build_today_actions(
            verdict=verdict,
            planned_workouts=actionable_workouts,
            thermal_review=thermal_review_for_output or {},
            recommend_breathwork=recommend_breathwork,
        )

        prompt_packet: dict[str, Any] = {
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
                    "respect_deterministic_acute_physiology_rail",
                ]
                # Batch 113 (#186): holiday away means no bedroom thermal review.
                if rule != "include_thermal_environment_review"
                or not rest_day["insideHolidayWindow"]
            ],
        }
        packet: dict[str, Any] = {
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
            "knowledgeBase": knowledge_base_section(kb_rows),
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
            "chronicSuggestions": chronic_result.to_dict(),
            "experimentLoop": experiment_loop_packet,
            "environment": environment_section(
                thermal_review=thermal_review_for_output,
                weather=weather,
            ),
            "verdict": verdict,
            "prompt": prompt_packet,
        }
        prompt_packet["requiredOutputSections"] = morning_output_contract_packet(packet)
        return packet

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
        input_presence = await morning_input_presence(
            self.session,
            user_id=player.id,
            subject_date=subject_date,
        )
        input_version = manual_entry_generation_version(
            manual_entries[0] if manual_entries else None
        )
        request_identity = morning_generation_identity(
            user_id=player.id,
            subject_date=subject_date,
            input_version=input_version,
            input_completeness_version=input_presence.version,
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
                exact_generation = (
                    claim.existing_analysis.prompt_version == PROMPT_VERSION
                    and isinstance(packet, dict)
                    and packet.get("generationIdentity") == request_identity
                )
                # A non-forced scheduler read may deliberately alias a current
                # analysis into the new completeness-aware request identity. Its
                # packet keeps the identity it was actually generated under, so
                # accept that alias only while its proven presence still matches.
                compatible_existing = (
                    not force
                    and claim.existing_analysis.prompt_version == PROMPT_VERSION
                    and isinstance(packet, dict)
                    and morning_packet_input_presence(packet) == input_presence
                )
                if exact_generation or compatible_existing:
                    return MorningAnalysisResult(
                        analysis=claim.existing_analysis,
                        generated=False,
                    )
                claim.restart()

            if not force:
                existing = await self.latest_analysis(player.id, subject_date)
                existing_packet = existing.context_packet if existing is not None else None
                if (
                    existing is not None
                    and existing.prompt_version == PROMPT_VERSION
                    and isinstance(existing_packet, dict)
                    and morning_packet_input_presence(existing_packet) == input_presence
                ):
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
                input_completeness_version=input_presence.version,
            )
            user_prompt = build_morning_user_prompt(context_packet)
            analysis_client = client or AnthropicMorningAnalysisClient()
            async with workload_slot(workload="anthropic", user_id=player.id):
                generation = await analysis_client.generate(
                    context_packet=context_packet,
                    user_prompt=user_prompt,
                )
            missing_sections = missing_morning_output_sections(
                context_packet, generation.output_markdown
            )
            if missing_sections:
                log.warning(
                    "morning_analysis_missing_required_sections",
                    user_id=str(player.id),
                    subject_date=subject_date.isoformat(),
                    prompt_version=PROMPT_VERSION,
                    missing_sections=list(missing_sections),
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
                    DailyMetric.phase == DAILY_METRIC_PHASE_SETTLED,
                )
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
        baselines: Sequence[MetricBaseline] = (),
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
            return _yesterday_load_packet([], [], daily_metric, baselines)

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
        return _yesterday_load_packet(activities, analyses, daily_metric, baselines)

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
                    .options(
                        load_only(
                            DailyMetric.calendar_date,
                            DailyMetric.phase,
                            DailyMetric.readiness_score,
                            raiseload=True,
                        )
                    )
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

    async def _acute_physiology_history(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> tuple[list[DailyMetric], list[Sleep]]:
        """Projected trailing evidence for the DB-free Batch 246 policy.

        The current day is excluded so a reading cannot dilute the distribution
        used to judge itself. Eighty-four prior calendar days also covers the
        exact previous-day and 3-night continuity checks. ``raiseload`` makes an
        accidental future read of either model's large JSON payload fail here
        rather than silently restore a Batch 235-class pooler transfer.
        """

        window_start = subject_date - timedelta(days=84)
        daily_metrics = list(
            (
                await self.session.execute(
                    select(DailyMetric)
                    .options(
                        load_only(
                            DailyMetric.calendar_date,
                            DailyMetric.hrv_last_night_avg_ms,
                            DailyMetric.resting_heart_rate_bpm,
                            raiseload=True,
                        )
                    )
                    .where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.phase == DAILY_METRIC_PHASE_MORNING,
                        DailyMetric.calendar_date >= window_start,
                        DailyMetric.calendar_date < subject_date,
                    )
                    .order_by(DailyMetric.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )
        sleeps = list(
            (
                await self.session.execute(
                    select(Sleep)
                    .options(
                        load_only(
                            Sleep.calendar_date,
                            Sleep.average_respiration,
                            Sleep.average_spo2_pct,
                            Sleep.lowest_spo2_pct,
                            raiseload=True,
                        )
                    )
                    .where(
                        Sleep.user_id == user_id,
                        Sleep.calendar_date >= window_start,
                        Sleep.calendar_date < subject_date,
                    )
                    .order_by(Sleep.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )
        return daily_metrics, sleeps

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
                    .options(temperature_series_columns())
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
        f"{morning_output_contract_prompt(context_packet)}\n\n"
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
    # Batch 253 (DS237-09): ``userId``, ``latitude`` and ``longitude`` are gone.
    # No system prompt referenced any of them and the weather is already resolved
    # into ``environment.weather`` before the packet is built, so every morning
    # brief was sending a third party Mark's precise home location — twice, see
    # ``_weather_packet`` — plus a stable cross-request correlator, attached to his
    # sleep times, HRV and body weight. The packet is also stored in
    # ``analyses.context_packet``, so it was in every archive and every export.
    # ``displayName`` stays: the coach addresses him by name.
    return {
        "displayName": player.display_name,
        "timezone": player.timezone,
        "athleteProfile": athlete_profile,
        "vo2maxAsOfDate": vo2max_as_of_date.isoformat() if vo2max_as_of_date else None,
        "weightKg": weight_kg,
        "weightAsOfDate": weight_as_of_date.isoformat() if weight_as_of_date else None,
        "weightOnFile": weight_kg is not None,
    }


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


def _baseline_comparison(baseline: MetricBaseline, current: float | int | None) -> dict[str, Any]:
    """The median/quartile/delta frame behind every "is this normal for him?" read.

    Batch 226: the metrics table and the closed-day whole-day-cost packet ask the
    same question of the same stored rows, so they share one definition of what a
    comparison *is* rather than each rounding its own delta. ``median`` is the
    centre wherever one exists — a skewed 84-night window makes the mean the
    weaker anchor — and falls back to it only when no median was computed.
    """
    center = _first_not_none(baseline.median_value, baseline.mean_value)
    return {
        "baselineMedian": baseline.median_value,
        "baselineMean": baseline.mean_value,
        "deltaVsBaseline": (
            None if current is None or center is None else round(float(current) - float(center), 2)
        ),
        "lowerQuartile": baseline.lower_quartile_value,
        "upperQuartile": baseline.upper_quartile_value,
        "sampleCount": baseline.sample_count,
    }


def _rem_age_frame(age_comparison: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """REM's population frame, taken from the row the stage table already renders.

    Batch 230 restores the age frame the metrics table lost. Batch 227 left REM
    out of ``AGE_TO_BASELINE_KEY`` on purpose — its age row lives in ``sleepRows``
    and renders in ``SleepStageAgeTable`` — but that table appears only on
    ``/sleep``, so on the morning brief and on Home REM was the one age-normed
    metric shown with no population frame at all: "✓ in range" and nothing else,
    on the metric Mark has now raised in three separate feedback waves.

    It reads the *same computed row* rather than re-deriving a band, so the two
    tables cannot drift about one night. On ``/sleep``, where both render, this
    repeats the band once — the accepted trade, because the frame's job is to stop
    the personal comparison reading as the whole story, and that job exists on
    every surface.
    """
    if age_comparison is None:
        return None
    sleep_rows = age_comparison.get("sleepRows")
    if not isinstance(sleep_rows, list):
        return None
    row = next(
        (
            entry
            for entry in sleep_rows
            if isinstance(entry, Mapping) and entry.get("metricKey") == "rem_sleep_pct"
        ),
        None,
    )
    if row is None:
        return None
    band_low, band_high = row.get("bandLow"), row.get("bandHigh")
    if band_low is None or band_high is None:
        return None
    return {
        "ageBand": row.get("ageBand"),
        "bandLow": band_low,
        "bandHigh": band_high,
        "unit": row.get("unit", ""),
        "tone": row.get("tone"),
        "descriptor": row.get("descriptor"),
    }


def _metrics_vs_baselines(
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    baselines: Sequence[MetricBaseline],
    age_adjusted_sleep_score: int | None,
    day_aggregates: DailyMetric | None = None,
    age_comparison: Mapping[str, Any] | None = None,
    closed_day_cost: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Batch 216/224: recovery reads (readiness, RHR, HRV) stay on the morning
    # row. Closed-day Body Battery charge/drain still come from the settled row.
    # Before that row exists, the partial morning window has one deliberately
    # asymmetric meaning: charge is the overnight recharge accumulated since
    # midnight, while drain is a part-day total that must not be compared with
    # a full-day baseline.
    settled_battery_source = (
        day_aggregates
        if day_aggregates is not None and day_aggregates.phase == DAILY_METRIC_PHASE_SETTLED
        else None
    )
    morning_battery_source = (
        daily_metric
        if settled_battery_source is None
        and daily_metric is not None
        and daily_metric.phase == DAILY_METRIC_PHASE_MORNING
        else None
    )
    morning_charge = (
        morning_body_battery_charged(morning_battery_source)
        if morning_battery_source is not None
        else None
    )
    # Batch 230: Mark's ask. The drain row rendered an em dash plus a two-line
    # "wait until the day closes" note — the tallest row in a table headed "Last
    # night's metrics", carrying no value, and describing *today*. Batch 226.2's
    # constraint is real (the subject date's settled row does not exist at wake,
    # so today's drain is structurally uncomparable) but it applies only to
    # today: yesterday's settled row does exist, and `_yesterday_load_packet` has
    # already computed its drain. Reusing that value rather than re-deriving one
    # is what stops the table and the prose quoting different numbers for one day.
    closed_day_drain = (
        closed_day_cost.get("bodyBatteryDrained") if closed_day_cost is not None else None
    )
    closed_day_date = _parse_iso_date(
        closed_day_cost.get("calendarDate") if closed_day_cost is not None else None
    )
    current_values = {
        "sleep_score": sleep.score if sleep else None,
        "age_adjusted_sleep_score": age_adjusted_sleep_score,
        "readiness_score": daily_metric.readiness_score if daily_metric else None,
        "resting_heart_rate_bpm": _first_not_none(
            daily_metric.resting_heart_rate_bpm if daily_metric else None,
            sleep.resting_heart_rate_bpm if sleep else None,
        ),
        "body_battery_charge": (
            complete_body_battery_charged(settled_battery_source)
            if settled_battery_source is not None
            else morning_charge
        ),
        "body_battery_drain": (
            complete_body_battery_drained(settled_battery_source)
            if settled_battery_source is not None
            else closed_day_drain
        ),
        "average_spo2_pct": sleep.average_spo2_pct if sleep else None,
        "average_respiration": sleep.average_respiration if sleep else None,
        "hrv_7_day_avg_ms": daily_metric.hrv_weekly_avg_ms if daily_metric else None,
        # Batch 227: mirrors `metric_baselines.sample_values` exactly, so the
        # live value and the stored quartiles are the same measurement.
        "rem_sleep_pct": rem_sleep_pct_for_row(sleep),
    }
    rows: list[dict[str, Any]] = []
    for baseline in baselines:
        current = current_values.get(baseline.metric_key)
        row = {
            "metricKey": baseline.metric_key,
            "label": baseline.metric_label,
            "currentValue": current,
            **_baseline_comparison(baseline, current),
            "excludedSampleCount": baseline.excluded_sample_count,
            "reliabilityStartDate": (
                baseline.reliability_start_date.isoformat()
                if baseline.reliability_start_date
                else None
            ),
        }
        if baseline.metric_key == "rem_sleep_pct":
            # Batch 230: the denominator, in words, beside the number it divides
            # by — Batch 217's convention, and the half of 227.3 that never
            # shipped. The percentage is a share of measured sleep including time
            # awake, which is why it will never equal what Mark's own watch shows.
            row["basis"] = SLEEP_STAGE_PCT_BASIS
            age_frame = _rem_age_frame(age_comparison)
            if age_frame is not None:
                row["ageFrame"] = age_frame
        if morning_battery_source is not None and baseline.metric_key == "body_battery_charge":
            if morning_charge is not None:
                row["basis"] = (
                    "Garmin's overnight charge accumulated from midnight to this morning's sync."
                )
            else:
                row["unavailableReason"] = (
                    "Garmin did not provide a usable overnight charge window for this "
                    "morning's sync."
                )
        if baseline.metric_key == "body_battery_drain" and settled_battery_source is None:
            if closed_day_drain is not None:
                row["basis"] = (
                    "Your last finished day"
                    + (f" ({_friendly_day(closed_day_date)})" if closed_day_date else "")
                    + " — drain is a whole-day figure, so it is shown once the day has closed."
                )
            elif morning_battery_source is not None:
                # Batch 224's withhold, unchanged, for the case it was written
                # for: no closed day to fall back to, so the only drain available
                # is a part-day total that must not meet a full-day baseline.
                row["unavailableReason"] = (
                    "This drain is still a part-day value at the morning sync; compare it with "
                    "your full-day baseline after the day closes."
                )
        rows.append(row)
    return rows


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _friendly_day(value: date) -> str:
    """``2026-08-26`` as ``26 Aug`` — no leading zero, no platform-specific format."""
    return f"{value.day} {value.strftime('%b')}"


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
    *,
    vo2max: float | None = None,
) -> dict[str, Any]:
    """Build the "vs the average for your age" packet (services/age_norms.py).

    Batch 225: ``vo2max`` is passed in rather than read off ``daily_metric``.
    The wake row never carries one (Garmin writes it after the day's activity),
    so reading the column dropped the VO2 max row out of ``ageComparison``
    entirely from July onward — silently, because ``build_age_comparison``
    drops a row for any metric it is given as ``None``. The frontend has had a
    dedicated code path for that row the whole time (``MetricComparisonTable``
    calls it out by name); it was simply never given anything to render.
    """
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
        vo2max=_first_not_none(vo2max, daily_metric.vo2max if daily_metric else None),
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


# prose. Assembled from signals the packet already computes and frozen in
# verdict["todayActions"] — the same transport as swapSuggestion/weeklyMix — then
# rendered by the frontend TodayActions block. A workout action carries the real
# plannedWorkoutId so the frontend approves it through the existing rail; the approve
# affordance itself is gated live on delivery state in the UI (structured data
# durable, layout swappable).
_THERMAL_WARM_FLAGS = frozenset(
    {"thermal_disruption_likely", "thermal_disruption_watch", "precool_target_missed"}
)


def _eased_ride_detail(status: str, adjustment: Mapping[str, Any] | None = None) -> str:
    if isinstance(adjustment, Mapping):
        adjusted_min = adjustment.get("adjustedDurationMin")
        adjusted_power = adjustment.get("adjustedWorkPowerPct")
        if isinstance(adjusted_min, int) and isinstance(adjusted_power, int):
            if adjustment.get("keptAsEndurance"):
                # Batch 215: on Red this is now reachable too — an already-Zone-2
                # ride keeps its intensity, so the copy must stop calling it a
                # recovery substitution. Batch 252.4: this reads the endurance
                # path, not the narrower held-intensity flag, so a 68-75% ride
                # eased to the 67% anchor is still described as a shortened Zone 2.
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


# Batch 226: the whole-day-cost figures, mapped to the stored baseline that
# describes each one. Drain is the only one of the three Mark has a personal
# distribution for; stress and end-of-day level are named here anyway so the
# packet can say *why* they are uncompared instead of leaving a bare number to
# be read as normal or abnormal at the model's discretion.
_WHOLE_DAY_COST_BASELINE_KEYS: tuple[tuple[str, str], ...] = (
    ("bodyBatteryDrained", "body_battery_drain"),
    ("allDayStressAvg", "stress_avg"),
    ("bodyBatteryEnd", "body_battery_end"),
)


def _whole_day_cost_baselines(
    values: Mapping[str, float | int | None],
    baselines: Sequence[MetricBaseline],
) -> dict[str, dict[str, Any]]:
    """Join each finished-day figure to the stored baseline that describes it.

    Batch 226 closes the gap Mark reported: the figure reaches the read while the
    comparison never does. The metrics table cannot supply it — it renders from a
    packet built at wake, when the subject date's settled row does not exist yet,
    so its drain row is structurally uncomparable (Batch 224). This packet is the
    one place a *finished* day's cost is already known.

    A figure with no value is omitted entirely rather than carrying an empty
    comparison: an incomplete or unknown Garmin window already gates the value to
    ``None`` upstream, and a comparison of nothing is worse than silence. A figure
    with a value but no stored baseline says so, so the read can state the absence
    rather than implying the number is unremarkable.
    """
    by_key = {baseline.metric_key: baseline for baseline in baselines}
    out: dict[str, dict[str, Any]] = {}
    for packet_key, metric_key in _WHOLE_DAY_COST_BASELINE_KEYS:
        current = values.get(packet_key)
        if current is None:
            continue
        baseline = by_key.get(metric_key)
        if baseline is None:
            out[packet_key] = {
                "metricKey": metric_key,
                "unavailableReason": (
                    "The app has not computed a personal baseline for this figure, so there is "
                    "nothing to compare it against."
                ),
            }
            continue
        out[packet_key] = {
            "metricKey": metric_key,
            "label": baseline.metric_label,
            **_baseline_comparison(baseline, current),
        }
    return out


def _yesterday_load_packet(
    activities: Sequence[Activity],
    analyses: Sequence[Analysis],
    daily_metric: DailyMetric | None = None,
    baselines: Sequence[MetricBaseline] = (),
) -> dict[str, Any]:
    coverage = (
        daily_aggregate_coverage(daily_metric.calendar_date, daily_metric.raw_payload)
        if daily_metric is not None
        else None
    )
    cost_values: dict[str, float | int | None] = {
        "allDayStressAvg": (
            complete_stress_avg(daily_metric) if daily_metric is not None else None
        ),
        "bodyBatteryDrained": (
            complete_body_battery_drained(daily_metric) if daily_metric is not None else None
        ),
        "bodyBatteryEnd": (
            complete_body_battery_end(daily_metric) if daily_metric is not None else None
        ),
    }
    whole_day_cost: dict[str, Any] = {
        "calendarDate": (
            daily_metric.calendar_date.isoformat() if daily_metric is not None else None
        ),
        "allDayStressAvg": cost_values["allDayStressAvg"],
        "bodyBatteryDrained": cost_values["bodyBatteryDrained"],
        "bodyBatteryEnd": cost_values["bodyBatteryEnd"],
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
    whole_day_cost["baselines"] = _whole_day_cost_baselines(cost_values, baselines)
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
