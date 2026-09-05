"""Ask-time chat context assembly (Batch 178).

Brief chat used to see exactly one thing: the ``context_packet`` frozen onto a
read when it was generated, plus that read's own markdown. Everything else the
app computes — the week ahead, the trend series, the latest review's
conclusions, a session completed after the read was written — was invisible, so
a question whose answer is rendered one tab away got an honest refusal. Mark
reported the effect on 2026-07-30: the conversation feels "almost disconnected"
from the app.

Kickoff decisions (Batch 178.2 / 178.3, ``/batch-start``):

* **The stored packet stays the read's own record; it is not rebuilt.** The
  read's markdown was written *from* that packet, so rebuilding it at ask-time
  would let the chat contradict the very text it is explaining (and would re-run
  the whole morning assembly on every question). A freshly assembled
  :data:`APP_STATE_KEY` block is layered *alongside* it instead, and every
  figure in that block is labelled as true-now rather than as what the read saw.
* **One notion of "current".** Whether the read still reflects Mark's latest
  check-in is decided with Batch 159's :func:`manual_entry_input_version`
  compared against the check-in version the packet itself recorded — not a
  second staleness rule invented here.
* **Deterministic pre-assembly, not tool-use.** ``generate_anthropic_text`` has
  no tool support, so retrieval would mean extending the client and paying a
  round-trip per lookup. The app's builders are already deterministic, cheap and
  unit-tested, so chat pre-assembles a compact block from them
  (``TrainingWeekService.build_window``, ``TrendsService.windows`` +
  ``compute_year_on_year``, stored review rows). Revisit tool-use only if the
  block proves too coarse for the questions Mark actually asks.
* **Latest review = the conclusions Mark was already given.** The stored
  ``weekly_review`` / ``monthly_review`` rows are used rather than re-running
  ``ReviewService.preview``, which would recompute a rollup (plus strength brief
  and insights) on every question to reproduce a narrative the app has already
  written and shown him.
* **Token budget.** The block is capped at :data:`APP_STATE_CHAR_BUDGET`
  serialized characters. ``sinceThisRead``'s lists give way first, then whole
  sections in :data:`_DROP_ORDER`, then the trend series oldest-first, and
  anything dropped is *named* in ``omittedForLength`` — a truncation must never
  be able to read as "no such data", which is the failure mode this batch exists
  to remove. Batch 255 re-sized the cap after measuring that every real question
  overflowed the old one, so the naming was carrying weight it was never meant
  to: the honest "not in front of me" answer had become the normal answer.

Batch 179 opened the same assembly up to a conversation with no read at all.
An unanchored question ("just ask the coach", or a question from Sleep, which
has no ``Analysis`` of its own) gets the identical app-state block with no
frozen packet beside it and no ``sinceThisRead`` delta — there is no read for
anything to be *since* — plus an ``origin`` note saying which surface Mark asked
from, which seeds the conversation without fencing it. The same pass also
resolves today's adjustable workout from live plan rows rather than from a
frozen packet, so the propose affordance can be keyed on plan state (179.3).

The block is explanatory context only. It cannot move the deterministic
Green/Amber/Red ladder or any floor, and a plan change still goes through the
propose/confirm rail (Decision #29).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from src.services.analysis_currentness import manual_entry_input_version
from src.services.bedroom_overnight import night_window
from src.services.body_metrics import resolve_effective_vo2max, resolve_effective_weight_kg
from src.services.bulk_history_reads import temperature_series_columns, without_sleep_raw_payload
from src.services.coach_sections import (
    daily_metric_packet,
    environment_section,
    knowledge_base_section,
    thermal_review,
)
from src.services.daily_metric_phase import morning_first_order
from src.services.holiday_pause import HolidayPauseService, holiday_windows_covering_date
from src.services.personal_baselines import baseline_band_packet
from src.services.reviews import ANALYSIS_TYPE_MONTHLY, ANALYSIS_TYPE_WEEKLY
from src.services.training_week import ACTION_AUDIT_TYPES, TrainingWeekService
from src.services.trends import (
    BUCKET_MONTH,
    DEFAULT_LOOKBACK_DAYS,
    TrendsService,
    compute_year_on_year,
    window_json,
    window_key,
    year_on_year_json,
)
from src.services.workout_categories import is_bike_workout_type

APP_STATE_KEY = "appState"
APP_STATE_VERSION = 2

#: Serialized-character ceiling for the whole app-state block, ~13.75k tokens.
#:
#: Measured, twice now, against Mark's real data rather than estimated. Batch
#: 255 found the previous comment ("a full block measures ~22k characters, so
#: trimming is a safety valve rather than routine") to be a false claim doing
#: load-bearing work: every real question overflowed 30,000, so the drop order
#: ran on every single answer, which is how he came to ask about his REM and be
#: told the nights were not in front of the coach.
#:
#: Batch 256 adds ``knowledgeBase``, ``dailyMetrics``, ``environment`` and
#: ``personalBaselines`` — **10,879 characters** built from live rows — and
#: re-measured rather than trusting arithmetic. Against 2026-09-05 production,
#: untrimmed with those four present: **48,315 on the morning brief, 46,865
#: unanchored, 57,093 on a twelve-day-stale weekly anchor.** At the old 45,000
#: the two ordinary anchors would have lost ``recentActivities`` and
#: ``latestReviews`` on every question, and the stale one ``sleepHistory`` as
#: well — reinstating, by growth, exactly the eviction Batch 255 removed.
#:
#: 55,000 is chosen so both ordinary anchors sit untrimmed with real headroom
#: (6,685 on the morning brief, 8,135 unanchored — the block drifted ~740
#: characters upward over a few hours of one day, and ``todayCheckIns`` is
#: unbounded, so headroom is not decoration). The stale anchor is *deliberately*
#: left to the trimmer: at 55,000 it lands on 54,242 by shedding two of its own
#: oldest delta entries and keeps ``sleepHistory``, ``recentActivities`` and
#: ``latestReviews`` intact. That is precisely the behaviour Batch 255 built
#: :data:`_SINCE_READ_TRIM_ORDER` to produce, and sizing above 57,093 to spare a
#: state 255.1 already made self-releasing would turn that order into dead code.
APP_STATE_CHAR_BUDGET = 55_000

WEEK_AHEAD_DAYS = 7
TREND_BUCKET = BUCKET_MONTH
TREND_WINDOW_COUNT = 6
RECENT_ACTIVITY_DAYS = 21
RECENT_ACTIVITY_LIMIT = 10
SLEEP_HISTORY_NIGHTS = 14
REVIEW_CONCLUSION_MAX_CHARS = 900
SINCE_READ_EVENT_LIMIT = 10
TRUNCATED_SUFFIX = "..."

logger = logging.getLogger(__name__)

TRENDS_MEANING = (
    "Deterministic per-window means/medians over the metric history the Trends tab "
    "renders. These are series measured and stored by the app; a direction stated "
    "here is the app's recorded trend, not independent proof of what Mark's body or "
    "own device showed."
)

#: Batch 256. Four categories bear on almost any question Mark asks and, until
#: this batch, existed only inside a generated read's frozen packet — so the same
#: question answered from Home and from the morning brief got two different
#: coaches. Each is built from live rows at ask time, which is strictly better
#: than the packet copy it replaces: the knowledge base is edited *between*
#: reads (the seed fills only missing sections; production is changed by
#: read-modify-write or the wholesale admin PUT), so a copy can state a rule
#: Mark has since changed.

KNOWLEDGE_BASE_MEANING = (
    "Mark's own profile, rules, protocols and confirmed learned context, read from "
    "his live record when he asked rather than copied from an earlier read - so a "
    "rule he has changed since reads as changed. When he asks what one of his own "
    "targets is, or why it is what it is, the answer is here. `basis` says, in "
    "words you may use with him, how a rule was arrived at; the `source` beside it "
    "is an internal label, so give him the basis and never the label."
)

DAILY_METRICS_MEANING = (
    "Today's Garmin wake observation as it stands now - readiness, HRV, resting "
    "heart rate, body battery and training load. `today` is null when Garmin has "
    "not written one for today yet, which is not the same as a reading of zero."
)

ENVIRONMENT_MEANING = (
    "Last night's bedroom climate and the overnight weather around it, from the "
    "live temperature record. `thermalReview` is null while Mark is away on a "
    "holiday, because the bedroom is not being slept in - not because the app has "
    "no readings for it."
)

#: The four bands the morning read compares against, so the conversation and the
#: brief argue from the same numbers rather than two different subsets.
_BASELINE_BAND_KEYS = frozenset(
    {
        "age_adjusted_sleep_score",
        "sleep_score",
        "hrv_7_day_avg_ms",
        "resting_heart_rate_bpm",
    }
)

PERSONAL_BASELINES_MEANING = (
    "His own measured bands over the app's baseline window - what is normal for "
    "Mark, not for a population. Check a figure against his own band before "
    "calling it high or low."
)

#: Read types that hold a conversation today; a newer one of the same type
#: supersedes the read being discussed.
_READ_TYPES = ("morning", "post_workout", "post_walk", "post_strength", "post_flexibility")

#: Statuses that mean a planned workout is no longer live to adjust.
_CLOSED_WORKOUT_STATUSES = frozenset({"completed", "skipped"})

#: Surfaces the coach can be opened from, and how the prompt names each one.
#: Batch 179.4: the origin *seeds* the conversation — "we're talking about last
#: night's sleep" — without fencing it to that subject. The client sends a kind,
#: never a sentence: an unrecognised value falls back to
#: :data:`DEFAULT_ORIGIN_KIND` and the raw string is never interpolated into the
#: prompt, so this field cannot become an injection route (Decision #243's rule
#: that Mark's words are data, applied to the app's own controls).
ORIGIN_KINDS: dict[str, str] = {
    "general": "no particular page - he just opened the coach",
    "home": "his home screen",
    "morning_brief": "this morning's brief",
    "sleep": "his sleep page",
    "week": "his week and delivery page",
    "workout": "a workout's detail sheet",
    "trends": "his trends page",
    "reviews": "his weekly and monthly reviews",
    "weekly_review": "the weekly review the coach sent him",
    "state_change": "a change the coach noticed for him",
    "environment": "his bedroom climate page",
    "breathwork": "his breathwork brief",
    "strength": "his strength brief",
    "walking": "his walking brief",
    "check_in": "his check-in",
}
DEFAULT_ORIGIN_KIND = "general"


def normalize_origin_kind(kind: str | None) -> str:
    """Coerce a client-supplied origin to one this module knows how to describe."""
    if kind is not None and kind in ORIGIN_KINDS:
        return kind
    return DEFAULT_ORIGIN_KIND


@dataclass(frozen=True)
class CoachOrigin:
    """Where Mark opened the conversation from, for an unanchored question."""

    kind: str = DEFAULT_ORIGIN_KIND
    subject_date: date | None = None

    @property
    def label(self) -> str:
        return ORIGIN_KINDS[normalize_origin_kind(self.kind)]


#: Dropped in this order when the block exceeds the budget: recent sessions and
#: review prose first (largest, and most reconstructable from the rest), sleep
#: history next, and ``knowledgeBase`` last of all. ``weekAhead``, ``today`` and
#: ``todayCheckIns`` are small and load-bearing, so they are never dropped; the
#: trend series is trimmed oldest-first only after everything above has gone.
#:
#: Batch 256 adds ``knowledgeBase`` at the end because it is the only one of the
#: four new sections large enough to buy anything back — 8,442 characters
#: against 677, 767 and 993. Dropping today's readiness, last night's bedroom or
#: his own bands would cost a load-bearing fact for a rounding error, so those
#: three are undroppable for the same reason ``today`` is.
_DROP_ORDER = ("recentActivities", "latestReviews", "sleepHistory", "knowledgeBase")

#: ``sinceThisRead``'s unbounded lists, trimmed oldest-first *before* any whole
#: section drops (Batch 255).
#:
#: The old comment called ``sinceThisRead`` "small and load-bearing" and exempted
#: it from trimming entirely. It is load-bearing; it is not small. It is the one
#: section that grows with the *staleness of the anchor* rather than with Mark's
#: data — 960 characters against a nine-minute-old brief and **8,835** against a
#: six-day-old review, three ``SINCE_READ_EVENT_LIMIT`` lists all at their cap.
#: Being exempt, it evicted ``sleepHistory`` (3,145) to protect itself (8,835),
#: so the freshest anchor kept the most context and the stalest kept the least —
#: exactly backwards. A delta's oldest entries are its least useful, so these
#: give way first, and never below :data:`SINCE_READ_TRIM_FLOOR` so the section
#: can still answer "has anything changed since".
_SINCE_READ_TRIM_ORDER = (
    "activitiesIngestedSinceRead",
    "newerReadsSinceRead",
    "checkInsSinceRead",
)
SINCE_READ_TRIM_FLOOR = 2

#: Headroom held back from :data:`APP_STATE_CHAR_BUDGET` while trimming.
#:
#: A pre-existing off-by-a-few that Batch 255 found by measuring rather than by
#: reading: ``omittedForLengthMeaning``, the ``omittedForLength`` labels and the
#: ``charBudget`` marker are all written into the block *after* the trim loops
#: finish, so trimming to exactly the budget produced a block a few hundred
#: characters over it — and a correctly-trimmed block then reported itself as
#: ``best_effort_over_budget``. Whole-section drops overshot far enough to hide
#: it; trimming a list to the boundary does not.
_BUDGET_METADATA_RESERVE = 700


@dataclass(frozen=True)
class ChatContext:
    """Everything the coach knows beyond the read itself, assembled at ask-time."""

    app_state: dict[str, Any]
    #: Batch 179.3: today's one live, deliverable bike workout, resolved from the
    #: plan itself rather than from a frozen packet, so the propose affordance is
    #: keyed on what is actually adjustable right now — from any entry point, and
    #: absent when the day is rest, holiday, or already closed out. This replaces
    #: Batch 178's subject-date liveness set, which could only ever *retire* an
    #: affordance the packet had already offered.
    adjustable_workout_id: uuid.UUID | None = None


class ChatContextService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        player: Profile,
        analysis: Analysis | None,
        *,
        asked_at_utc: datetime,
        origin: CoachOrigin | None = None,
    ) -> ChatContext:
        """Assemble the conversation's context.

        ``analysis`` is the read the question was asked from, when there is one.
        Batch 179 made it optional: an unanchored question gets the identical
        app-state block with no ``sinceThisRead`` delta — there is no read for
        anything to be *since* — and an ``origin`` note instead.
        """
        local_today = local_date(asked_at_utc, player.timezone)
        origin = origin or CoachOrigin()
        subject_date = (
            analysis.subject_date if analysis is not None else (origin.subject_date or local_today)
        )

        subject_workouts = await self._planned_workouts_on(player.id, subject_date)
        today_workouts = (
            subject_workouts
            if subject_date == local_today
            else await self._planned_workouts_on(player.id, local_today)
        )
        # One holiday lookup answers two questions: whether a proposal has
        # anything to act on, and whether there is a bedroom to review at all.
        holiday_windows = await HolidayPauseService(self.session).get_windows(player)
        inside_holiday = bool(holiday_windows_covering_date(holiday_windows, local_today))
        adjustable_workout_id = self._adjustable_workout_id(
            today_workouts, inside_holiday=inside_holiday
        )

        week_ahead = await TrainingWeekService(self.session).build_window(
            player,
            start_date=local_today,
            end_date=local_today + timedelta(days=WEEK_AHEAD_DAYS - 1),
            subject_date=local_today,
            window_kind="week_ahead_from_today",
        )
        today_check_ins = await self._check_ins_on(player.id, local_today)
        trends = await self._trends(player, local_today)
        reviews = await self._latest_reviews(player.id)
        activities = await self._recent_activities(player.id, local_today, player.timezone)
        sleep_rows = await self._sleep_history(player.id, local_today)
        weight_kg, weight_as_of_date = await resolve_effective_weight_kg(
            self.session, player.id, local_today
        )
        vo2max, vo2max_as_of_date = await resolve_effective_vo2max(
            self.session, player.id, local_today
        )
        # One knowledge-base read serves both sections that need it: the
        # thermal thresholds live in ``sleep_protocol``.
        kb_rows = await self._active_knowledge_base(player.id)
        daily_metrics = await self._daily_metrics(
            player, local_today, vo2max=vo2max, vo2max_as_of_date=vo2max_as_of_date
        )
        environment = await self._environment(
            player,
            local_today,
            knowledge_base={row.section: row.content for row in kb_rows},
            last_night=_night_for(sleep_rows, local_today),
            inside_holiday=inside_holiday,
        )
        personal_baselines = await self._personal_baselines(player)

        state: dict[str, Any] = {
            "version": APP_STATE_VERSION,
            "assembledAtUtc": _dt(asked_at_utc),
            "meaning": _state_meaning(anchored=analysis is not None),
            "todayLocalDate": local_today.isoformat(),
            "conversationOpenedFrom": {
                "surface": origin.label,
                "subjectDate": subject_date.isoformat(),
                "meaning": (
                    "Where Mark opened the conversation. Start there if his question is "
                    "open-ended, but the conversation is not limited to it - answer "
                    "whatever he actually asks from anything below."
                ),
            },
            "today": {
                "localDate": local_today.isoformat(),
                "plannedWorkouts": [_planned_workout_state(row) for row in today_workouts],
                "bodyMetrics": {
                    "weightKg": weight_kg,
                    "weightAsOfDate": (
                        weight_as_of_date.isoformat() if weight_as_of_date is not None else None
                    ),
                    "weightOnFile": weight_kg is not None,
                    "vo2max": vo2max,
                    "vo2maxAsOfDate": (
                        vo2max_as_of_date.isoformat() if vo2max_as_of_date is not None else None
                    ),
                    "vo2maxOnFile": vo2max is not None,
                    "meaning": (
                        "Effective Garmin body metrics resolved at ask-time using the "
                        "same carry-forward windows as generated reads. As-of dates "
                        "state the source day; missing means no current reading is on file."
                    ),
                },
            },
            "todayCheckIns": {
                "entries": [_check_in_state(row) for row in today_check_ins],
                "meaning": (
                    "Everything Mark logged himself today, newest first, present on "
                    "every question rather than only as a delta against a read. An "
                    "empty list means he has not checked in yet today - not that he "
                    "wrote nothing."
                ),
            },
            "weekAhead": week_ahead,
            "trends": trends,
            "latestReviews": reviews,
            "recentActivities": activities,
            "sleepHistory": [_sleep_state(row) for row in sleep_rows],
            # Batch 256: the four the frozen packet used to hold alone. On an
            # anchored question a read's packet may carry its own copy of these
            # under the same names; ``meaning`` on the block already says which
            # record is which, so the duplication reads as current-versus-earlier
            # rather than as a contradiction.
            "knowledgeBase": {
                **knowledge_base_section(kb_rows),
                "meaning": KNOWLEDGE_BASE_MEANING,
            },
            "dailyMetrics": daily_metrics,
            "environment": environment,
            "personalBaselines": personal_baselines,
            "omittedForLength": _field_truncations(latest_reviews=reviews, plan_changes=[]),
        }
        if analysis is not None:
            state["readSubjectDate"] = subject_date.isoformat()
            state["sinceThisRead"] = await self._since_read(
                player,
                analysis,
                subject_workouts=subject_workouts,
                read_generated_at=analysis.generated_at_utc,
            )
            state["omittedForLength"] = _field_truncations(
                latest_reviews=reviews,
                plan_changes=state["sinceThisRead"]["planChangesSinceRead"],
            )
        _apply_char_budget(state)
        return ChatContext(app_state=state, adjustable_workout_id=adjustable_workout_id)

    # -- sections -----------------------------------------------------------

    def _adjustable_workout_id(
        self,
        today_workouts: Sequence[PlannedWorkout],
        *,
        inside_holiday: bool,
    ) -> uuid.UUID | None:
        """Today's one workout a proposal could act on, from live plan rows.

        Batch 179.3: the pre-179 gate asked ``analysis_type == "morning"`` as a
        proxy for "there is a live adjustable ride", and read the candidate out
        of a frozen packet. Both are answered properly here — the plan itself
        says whether anything is open, deliverable and a bike session, so the
        affordance appears from any entry point exactly when it can do
        something, and never on a rest day, inside a holiday, or once the ride
        is completed or skipped.

        Batch 256 moved the holiday lookup up to :meth:`build`, which needs the
        same answer for the bedroom review. An explicit holiday window stays
        authoritative even when a stale plan row was never re-versioned, so it
        is still checked against the window rather than inferred from statuses
        (``morning_analysis._rest_day_context``).
        """
        if inside_holiday or not today_workouts:
            return None
        candidates = [
            row
            for row in today_workouts
            if row.status not in _CLOSED_WORKOUT_STATUSES
            and row.structured_workout
            and is_bike_workout_type(row.workout_type)
        ]
        if not candidates:
            return None
        return candidates[0].id

    # -- Batch 256: the four sections every question needs ------------------

    async def _daily_metrics(
        self,
        player: Profile,
        local_today: date,
        *,
        vo2max: float | None,
        vo2max_as_of_date: date | None,
    ) -> dict[str, Any]:
        row = await self._daily_metric_on(player.id, local_today)
        return {
            "today": daily_metric_packet(row, vo2max=vo2max, vo2max_as_of_date=vo2max_as_of_date),
            "meaning": DAILY_METRICS_MEANING,
        }

    async def _environment(
        self,
        player: Profile,
        local_today: date,
        *,
        knowledge_base: Mapping[str, Any],
        last_night: Sleep | None,
        inside_holiday: bool,
    ) -> dict[str, Any]:
        """Last night's bedroom, on the same holiday rule the morning read uses.

        Batch 113 (#186): a holiday is "away" for thermal purposes — the bedroom
        is not being slept in, so there is nothing to review. The weather still
        travels, exactly as it does in the morning packet, because it is true
        wherever he is.
        """
        weather = await self._weather_on(player.id, local_today)
        review: dict[str, Any] | None = None
        if not inside_holiday:
            review = thermal_review(
                await self._overnight_temperature_rows(player.id, local_today, player.timezone),
                weather,
                knowledge_base,
                sleep=last_night,
            )
        return {
            **environment_section(thermal_review=review, weather=weather),
            "meaning": ENVIRONMENT_MEANING,
        }

    async def _personal_baselines(self, player: Profile) -> dict[str, Any]:
        rows = await self._metric_baselines(player.id)
        return {
            "bands": baseline_band_packet(rows, keys=set(_BASELINE_BAND_KEYS)),
            "meaning": PERSONAL_BASELINES_MEANING,
        }

    async def _since_read(
        self,
        player: Profile,
        analysis: Analysis,
        *,
        subject_workouts: Sequence[PlannedWorkout],
        read_generated_at: datetime,
    ) -> dict[str, Any]:
        """What has happened since the read was written.

        This is the half of Mark's report that no wording change could fix: a
        ride completed after the morning brief simply was not in that brief's
        packet, so the chat over it could not see the ride at all.
        """
        activities = await self._activities_ingested_since(player.id, read_generated_at)
        check_ins = await self._check_ins_since(player.id, read_generated_at)
        plan_changes = await self._plan_changes_since(player.id, read_generated_at)
        newer_reads = await self._newer_reads(player.id, analysis)
        latest_check_in = await self._latest_check_in_on(player.id, analysis.subject_date)
        packet_check_in_versions = _packet_check_in_versions(analysis.context_packet)
        live_check_in_version = manual_entry_input_version(latest_check_in)
        # Batch 159's notion of which check-in a read reflects, reused rather
        # than restated: the version string is built the same way the
        # regeneration paths build it.
        check_in_newer_than_read = (
            live_check_in_version is not None
            and live_check_in_version not in packet_check_in_versions
        )
        current_closed_subject_workouts = [
            {
                "plannedWorkoutId": str(row.id),
                "title": row.title,
                "workoutType": row.workout_type,
                "status": row.status,
                "meaning": (
                    "Current status of a planned workout on the read's subject date. "
                    "This app state has no workout status-change timestamp, so this "
                    "field is not evidence that the status changed after the read."
                ),
            }
            for row in subject_workouts
            if row.status in _CLOSED_WORKOUT_STATUSES
        ]
        events = (
            bool(activities)
            or bool(check_ins)
            or bool(plan_changes)
            or bool(newer_reads)
            or check_in_newer_than_read
        )
        return {
            "readGeneratedAtUtc": _dt(read_generated_at),
            "readReflectsLatestCheckIn": not check_in_newer_than_read,
            "anythingChangedSinceRead": events,
            "activitiesIngestedSinceRead": activities,
            "checkInsSinceRead": check_ins,
            "planChangesSinceRead": plan_changes,
            "newerReadsSinceRead": newer_reads,
            "subjectDateClosedWorkoutsCurrent": current_closed_subject_workouts,
        }

    async def _trends(self, player: Profile, as_of: date) -> dict[str, Any]:
        windows = await TrendsService(self.session).windows(
            player,
            bucket=TREND_BUCKET,
            as_of=as_of,
            lookback_days=DEFAULT_LOOKBACK_DAYS,
        )
        comparison = compute_year_on_year(
            windows,
            bucket=TREND_BUCKET,
            target_key=window_key(TREND_BUCKET, as_of),
        )
        return {
            "bucket": TREND_BUCKET,
            "meaning": TRENDS_MEANING,
            "recentWindows": [window_json(window) for window in windows[-TREND_WINDOW_COUNT:]],
            "windowsAvailable": len(windows),
            "yearOnYear": year_on_year_json(comparison),
        }

    async def _latest_reviews(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        for analysis_type, period in (
            (ANALYSIS_TYPE_WEEKLY, "weekly"),
            (ANALYSIS_TYPE_MONTHLY, "monthly"),
        ):
            row = await self.session.scalar(
                select(Analysis)
                .where(Analysis.user_id == user_id, Analysis.analysis_type == analysis_type)
                .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                .limit(1)
            )
            if row is None:
                continue
            reviews.append(
                {
                    "period": period,
                    "periodStartDate": row.subject_date.isoformat(),
                    "generatedAtUtc": _dt(row.generated_at_utc),
                    "conclusions": _truncate(row.output_markdown, REVIEW_CONCLUSION_MAX_CHARS),
                }
            )
        return reviews

    async def _recent_activities(
        self,
        user_id: uuid.UUID,
        as_of: date,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        start_utc = day_start_utc(as_of - timedelta(days=RECENT_ACTIVITY_DAYS - 1), timezone_name)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(Activity.user_id == user_id, Activity.start_utc >= start_utc)
                    .order_by(desc(Activity.start_utc))
                    .limit(RECENT_ACTIVITY_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [_activity_state(row, timezone_name) for row in rows]

    async def _sleep_history(self, user_id: uuid.UUID, as_of: date) -> list[Sleep]:
        """The fortnight of nights, newest first.

        Batch 256 returns rows rather than rendered dicts: the same newest row
        is the sleep window ``thermal_review`` needs, and a second query for the
        night the block is already holding would be a query for nothing.
        """
        rows = (
            (
                await self.session.execute(
                    select(Sleep)
                    .options(without_sleep_raw_payload())
                    .where(
                        Sleep.user_id == user_id,
                        Sleep.calendar_date <= as_of,
                        Sleep.calendar_date > as_of - timedelta(days=SLEEP_HISTORY_NIGHTS),
                    )
                    .order_by(desc(Sleep.calendar_date))
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    # -- row loaders --------------------------------------------------------

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

    async def _daily_metric_on(self, user_id: uuid.UUID, day: date) -> DailyMetric | None:
        """The wake observation for a day, preferring the morning row.

        The same ordering the morning read uses (Batch 205): a day can carry a
        morning row and a settled one, and readiness/HRV are wake figures.
        """
        row: DailyMetric | None = await self.session.scalar(
            select(DailyMetric)
            .where(DailyMetric.user_id == user_id, DailyMetric.calendar_date == day)
            .order_by(morning_first_order())
            .limit(1)
        )
        return row

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

    async def _weather_on(self, user_id: uuid.UUID, day: date) -> WeatherDaily | None:
        row: WeatherDaily | None = await self.session.scalar(
            select(WeatherDaily)
            .where(WeatherDaily.user_id == user_id, WeatherDaily.calendar_date == day)
            .order_by(desc(WeatherDaily.updated_at))
            .limit(1)
        )
        return row

    async def _overnight_temperature_rows(
        self,
        user_id: uuid.UUID,
        day: date,
        timezone_name: str,
    ) -> list[TemperatureReading]:
        # ``day`` is the wake date; the shared bedroom helper takes the date the
        # night *starts* on (Batch 92 #165).
        start_utc, end_utc = night_window(day - timedelta(days=1), _timezone(timezone_name))
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

    async def _planned_workouts_on(
        self,
        user_id: uuid.UUID,
        workout_date: date,
    ) -> list[PlannedWorkout]:
        """Active rows on one date, in plan order.

        A date can carry more than one row — a split day writes the cycle and
        the strength session as ascending versions (`plan_import`, guarded by
        the `(user_id, workout_date, version)` unique constraint) — so these are
        siblings rather than revisions of each other, and ascending version is
        the order Mark's plan actually reads in.
        """
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date == workout_date,
                    )
                    .order_by(PlannedWorkout.version.asc(), PlannedWorkout.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _activities_ingested_since(
        self,
        user_id: uuid.UUID,
        since_utc: datetime,
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(Activity.user_id == user_id, Activity.created_at > since_utc)
                    .order_by(desc(Activity.created_at))
                    .limit(SINCE_READ_EVENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "activityId": str(row.id),
                "title": row.activity_name,
                "activityType": row.activity_type,
                "startUtc": _dt(row.start_utc),
                "ingestedAtUtc": _dt(row.created_at),
                "durationMin": _minutes(row.duration_sec),
                "avgPowerWatts": row.avg_power_watts,
                "normalizedPowerWatts": row.normalized_power_watts,
                "trainingLoad": row.training_load,
            }
            for row in rows
        ]

    async def _check_ins_since(
        self,
        user_id: uuid.UUID,
        since_utc: datetime,
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(ManualEntry.user_id == user_id, ManualEntry.entry_at_utc > since_utc)
                    .order_by(desc(ManualEntry.entry_at_utc))
                    .limit(SINCE_READ_EVENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [_check_in_state(row) for row in rows]

    async def _plan_changes_since(
        self,
        user_id: uuid.UUID,
        since_utc: datetime,
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type.in_(tuple(ACTION_AUDIT_TYPES)),
                        Analysis.generated_at_utc > since_utc,
                    )
                    .order_by(desc(Analysis.generated_at_utc))
                    .limit(SINCE_READ_EVENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "action": row.analysis_type.removeprefix("workout_"),
                "subjectDate": row.subject_date.isoformat(),
                "generatedAtUtc": _dt(row.generated_at_utc),
                "summary": _truncate(row.output_markdown, 200),
            }
            for row in rows
        ]

    async def _newer_reads(self, user_id: uuid.UUID, analysis: Analysis) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type.in_(_READ_TYPES),
                        Analysis.generated_at_utc > analysis.generated_at_utc,
                        Analysis.id != analysis.id,
                    )
                    .order_by(desc(Analysis.generated_at_utc))
                    .limit(SINCE_READ_EVENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "readType": row.analysis_type,
                "subjectDate": row.subject_date.isoformat(),
                "generatedAtUtc": _dt(row.generated_at_utc),
                "verdict": row.verdict,
                "supersedesThisRead": (
                    row.analysis_type == analysis.analysis_type
                    and row.subject_date == analysis.subject_date
                ),
            }
            for row in rows
        ]

    async def _check_ins_on(
        self,
        user_id: uuid.UUID,
        entry_date: date,
    ) -> list[ManualEntry]:
        """Every check-in Mark filed on one day, newest first.

        Not ``_latest_check_in_on``, and Batch 255 shipped that mistake first and
        caught it against production. He files several a day and they carry
        different things: on 2026-09-05 his 09:38 morning check-in held the
        sleep-onset correction, the snack and the bedroom setup, and his 09:43
        workout check-in held a bare "feel". Taking the latest returned the
        emptier of the two and dropped everything the question was about — and
        the earlier one also predates that morning's brief, so the
        ``sinceThisRead`` delta could not have supplied it either.
        """
        rows = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(ManualEntry.user_id == user_id, ManualEntry.entry_date == entry_date)
                    .order_by(desc(ManualEntry.entry_at_utc))
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _latest_check_in_on(
        self,
        user_id: uuid.UUID,
        entry_date: date,
    ) -> ManualEntry | None:
        entry: ManualEntry | None = await self.session.scalar(
            select(ManualEntry)
            .where(ManualEntry.user_id == user_id, ManualEntry.entry_date == entry_date)
            .order_by(desc(ManualEntry.entry_at_utc))
            .limit(1)
        )
        return entry


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _apply_char_budget(state: dict[str, Any]) -> None:
    """Shrink the block to :data:`APP_STATE_CHAR_BUDGET`, naming what went.

    An omission that looked like an absence would recreate exactly the failure
    this batch removes, so every drop is recorded in ``omittedForLength``.

    Order matters, and Batch 255 changed it. ``sinceThisRead``'s lists go first
    because they are the only part of the block sized by *how stale the anchor
    is* rather than by how much Mark has done — so leaving them exempt meant a
    stale anchor bought its own bulk by evicting the sleep, session and review
    history the question was usually about.
    """
    omitted: list[str] = list(state.get("omittedForLength", []))
    target = APP_STATE_CHAR_BUDGET - _BUDGET_METADATA_RESERVE

    # Batch 255: the staleness-driven section gives way before the data-driven
    # ones. Lists arrive newest-first, so the oldest entry is the last.
    since_read = state.get("sinceThisRead") or {}
    for field in _SINCE_READ_TRIM_ORDER:
        entries = since_read.get(field)
        if not isinstance(entries, list):
            continue
        while app_state_length(state) > target and len(entries) > SINCE_READ_TRIM_FLOOR:
            entries.pop()
            label = f"sinceThisRead.{field}(oldest)"
            if label not in omitted:
                omitted.append(label)

    for section in _DROP_ORDER:
        if app_state_length(state) <= target:
            break
        if not state.get(section):
            continue
        # Emptied, never deleted: an absent key would read as "no such data",
        # which is the failure this whole mechanism exists to prevent. Batch 256
        # put a dict section (``knowledgeBase``) in this list, so the empty
        # container has to match the shape that was there.
        state[section] = [] if isinstance(state[section], list) else {}
        omitted.append(section)
    trend_windows = state.get("trends", {}).get("recentWindows", [])
    while app_state_length(state) > target and len(trend_windows) > 1:
        trend_windows.pop(0)
        if "trends.recentWindows(oldest)" not in omitted:
            omitted.append("trends.recentWindows(oldest)")
    if omitted:
        state["omittedForLength"] = omitted
        state["omittedForLengthMeaning"] = (
            "Trimmed to fit the prompt, not absent from the app. If a question needs "
            "one of these, say it is not in front of you here rather than that it does "
            "not exist."
        )
    if app_state_length(state) > APP_STATE_CHAR_BUDGET:
        state["charBudget"] = {
            "budgetChars": APP_STATE_CHAR_BUDGET,
            "actualChars": app_state_length(state),
            "status": "best_effort_over_budget",
            "meaning": (
                "The app-state block is still over its target after all safe trims. "
                "Treat the budget as best-effort and trust named omissions over absence."
            ),
        }
        logger.warning(
            "chat app-state exceeded char budget after trims",
            extra={
                "budget_chars": APP_STATE_CHAR_BUDGET,
                "actual_chars": app_state_length(state),
                "omitted_for_length": omitted,
            },
        )


def _state_meaning(*, anchored: bool) -> str:
    base = "State of the app right now, assembled when this question was asked. "
    if anchored:
        return base + (
            "The read alongside it is the app's frozen earlier record; where the two "
            "differ, this block is the app's latest record. Neither is independent "
            "proof of what Mark's body or own device showed."
        )
    return base + (
        "There is no earlier read behind this question, so this block is everything "
        "you have and all of it is current."
    )


def app_state_length(state: dict[str, Any]) -> int:
    return len(app_state_json(state))


def app_state_json(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=True, sort_keys=True, default=str)


def _packet_check_in_versions(context_packet: Any) -> frozenset[str]:
    """Check-in versions a read's packet already reflects.

    The morning packet carries a ``manualEntries`` list; the post-session
    packets carry a single ``postRideCheckIn``-style node. Both stamp
    ``entryAtUtc`` in the same format
    :func:`analysis_currentness.manual_entry_input_version` produces, so one
    comparison covers every read type.
    """
    if not isinstance(context_packet, dict):
        return frozenset()
    versions: set[str] = set()
    for value in context_packet.values():
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict):
                entry_at = candidate.get("entryAtUtc")
                if isinstance(entry_at, str):
                    versions.add(entry_at)
    return frozenset(versions)


def _night_for(sleep_rows: Sequence[Sleep], day: date) -> Sleep | None:
    """Last night's sleep row, or ``None`` when Garmin has not written one.

    The history is newest-first, so this is a check on the head rather than a
    scan — and it must be a check: without it a two-day-old night would be
    handed to ``thermal_review`` as though it were the window last night's
    readings fell in.
    """
    if sleep_rows and sleep_rows[0].calendar_date == day:
        return sleep_rows[0]
    return None


def _planned_workout_state(row: PlannedWorkout) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workoutDate": row.workout_date.isoformat(),
        "title": row.title,
        "workoutType": row.workout_type,
        "status": row.status,
        "plannedDurationMin": row.planned_duration_min,
        "intensityTarget": row.intensity_target,
        "isLive": row.status not in _CLOSED_WORKOUT_STATUSES,
    }


def _activity_state(row: Activity, timezone_name: str) -> dict[str, Any]:
    return {
        "activityId": str(row.id),
        "localDate": local_date(row.start_utc, timezone_name).isoformat(),
        "title": row.activity_name,
        "activityType": row.activity_type,
        "durationMin": _minutes(row.duration_sec),
        "distanceKm": round(row.distance_m / 1000, 2) if row.distance_m is not None else None,
        "avgHeartRateBpm": row.avg_heart_rate_bpm,
        "avgPowerWatts": row.avg_power_watts,
        "normalizedPowerWatts": row.normalized_power_watts,
        "trainingLoad": row.training_load,
        "aerobicTrainingEffect": row.aerobic_training_effect,
    }


def _check_in_state(row: ManualEntry) -> dict[str, Any]:
    """One check-in as the coach sees it.

    Batch 255 added ``food`` and ``sleepSetup``. They were the only structured
    things Mark writes in a check-in that the chat did not forward, and on
    2026-09-05 that produced the failure this batch exists to remove: he asked
    about his evening snack, the coach truthfully answered that it had no such
    note, and he replied **"not sure why you can't read them"**. The text was in
    ``food_json`` the whole time — ``morning_analysis`` and ``daily_loop``
    already send both fields, so the morning brief could see the snack and the
    conversation *about* that brief could not.

    ``sleep_setup_json`` travels for the same reason and one more: his notes
    routinely refer to it deictically — "window openings noted below are for
    overnight not pre cool" — so without it the prose he does send is
    unresolvable.
    """
    return {
        "entryDate": row.entry_date.isoformat(),
        "entryAtUtc": _dt(row.entry_at_utc),
        "subjectiveScore": row.subjective_score,
        "rpe": row.rpe,
        "feel": row.feel,
        # Mark's own words are data, never instructions (Decision #243).
        "notes": row.notes,
        "food": row.food_json or None,
        "sleepSetup": row.sleep_setup_json or None,
        "contentRole": "untrusted_user_data",
    }


def _sleep_state(row: Sleep) -> dict[str, Any]:
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "score": row.score,
        "ageAdjustedScore": row.age_adjusted_score,
        "qualifier": row.qualifier,
        "timeAsleepMin": _minutes(row.duration_sec),
        "deepSleepMin": _minutes(row.deep_sleep_sec),
        "remSleepMin": _minutes(row.rem_sleep_sec),
        "awakeSleepMin": _minutes(row.awake_sleep_sec),
        "avgOvernightHrvMs": row.avg_overnight_hrv_ms,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
    }


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + TRUNCATED_SUFFIX


def _field_truncations(
    *,
    latest_reviews: Sequence[Mapping[str, Any]],
    plan_changes: Sequence[Mapping[str, Any]],
) -> list[str]:
    omitted: list[str] = []
    if any(_is_truncated(row.get("conclusions")) for row in latest_reviews):
        omitted.append("latestReviews.conclusions(truncated)")
    if any(_is_truncated(row.get("summary")) for row in plan_changes):
        omitted.append("sinceThisRead.planChangesSinceRead.summary(truncated)")
    return omitted


def _is_truncated(value: Any) -> bool:
    return isinstance(value, str) and value.endswith(TRUNCATED_SUFFIX)


def _minutes(seconds: float | int | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("" if value.tzinfo is not None else "Z")


def local_date(value: datetime, timezone_name: str) -> date:
    return value.replace(tzinfo=UTC).astimezone(_timezone(timezone_name)).date()


def day_start_utc(day: date, timezone_name: str) -> datetime:
    return (
        datetime.combine(day, time.min, tzinfo=_timezone(timezone_name))
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


def _timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
