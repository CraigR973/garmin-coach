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
  serialized characters. Sections drop whole in :data:`_DROP_ORDER` and
  oldest-first for the trend series, and anything dropped is *named* in
  ``omittedForLength`` — a truncation must never be able to read as "no such
  data", which is the failure mode this batch exists to remove.

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
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, Analysis, ManualEntry, PlannedWorkout, Sleep
from src.models.profile import Profile
from src.services.analysis_currentness import manual_entry_input_version
from src.services.holiday_pause import HolidayPauseService, holiday_windows_covering_date
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
APP_STATE_VERSION = 1

#: Serialized-character ceiling for the whole app-state block, ~7.5k tokens. A
#: full block measures ~22k characters (week ahead, six monthly trend windows
#: plus the year-on-year comparison, two review conclusions, ten sessions, a
#: fortnight of nights), so trimming is a safety valve rather than routine —
#: which matters because a trim costs the conversation real context. The read
#: packet remains the larger input and both sit well inside the model's window.
APP_STATE_CHAR_BUDGET = 30_000

WEEK_AHEAD_DAYS = 7
TREND_BUCKET = BUCKET_MONTH
TREND_WINDOW_COUNT = 6
RECENT_ACTIVITY_DAYS = 21
RECENT_ACTIVITY_LIMIT = 10
SLEEP_HISTORY_NIGHTS = 14
REVIEW_CONCLUSION_MAX_CHARS = 900
SINCE_READ_EVENT_LIMIT = 10

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
#: history next. ``weekAhead``, ``today`` and ``sinceThisRead`` are small and
#: load-bearing, so they are never dropped; the trend series is trimmed
#: oldest-first only after everything above has gone.
_DROP_ORDER = ("recentActivities", "latestReviews", "sleepHistory")


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
        adjustable_workout_id = await self._adjustable_workout_id(
            player, local_today, today_workouts
        )

        week_ahead = await TrainingWeekService(self.session).build_window(
            player,
            start_date=local_today,
            end_date=local_today + timedelta(days=WEEK_AHEAD_DAYS - 1),
            subject_date=local_today,
            window_kind="week_ahead_from_today",
        )
        trends = await self._trends(player, local_today)
        reviews = await self._latest_reviews(player.id)
        activities = await self._recent_activities(player.id, local_today, player.timezone)
        sleep_nights = await self._sleep_history(player.id, local_today)

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
            },
            "weekAhead": week_ahead,
            "trends": trends,
            "latestReviews": reviews,
            "recentActivities": activities,
            "sleepHistory": sleep_nights,
            "omittedForLength": [],
        }
        if analysis is not None:
            state["readSubjectDate"] = subject_date.isoformat()
            state["sinceThisRead"] = await self._since_read(
                player,
                analysis,
                subject_workouts=subject_workouts,
                read_generated_at=analysis.generated_at_utc,
            )
        _apply_char_budget(state)
        return ChatContext(app_state=state, adjustable_workout_id=adjustable_workout_id)

    # -- sections -----------------------------------------------------------

    async def _adjustable_workout_id(
        self,
        player: Profile,
        local_today: date,
        today_workouts: Sequence[PlannedWorkout],
    ) -> uuid.UUID | None:
        """Today's one workout a proposal could act on, from live plan rows.

        Batch 179.3: the pre-179 gate asked ``analysis_type == "morning"`` as a
        proxy for "there is a live adjustable ride", and read the candidate out
        of a frozen packet. Both are answered properly here — the plan itself
        says whether anything is open, deliverable and a bike session, so the
        affordance appears from any entry point exactly when it can do
        something, and never on a rest day, inside a holiday, or once the ride
        is completed or skipped.
        """
        if not today_workouts:
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
        # An explicit holiday window is authoritative even when a stale plan row
        # was never re-versioned, so it is checked against the window rather than
        # inferred from statuses (``morning_analysis._rest_day_context``).
        windows = await HolidayPauseService(self.session).get_windows(player)
        if holiday_windows_covering_date(windows, local_today):
            return None
        return candidates[0].id

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
        activities = await self._activities_since(player.id, read_generated_at)
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
        closed_since = [
            {
                "plannedWorkoutId": str(row.id),
                "title": row.title,
                "workoutType": row.workout_type,
                "status": row.status,
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
            or bool(closed_since)
        )
        return {
            "readGeneratedAtUtc": _dt(read_generated_at),
            "readReflectsLatestCheckIn": not check_in_newer_than_read,
            "anythingChangedSinceRead": events,
            "activitiesCompletedSinceRead": activities,
            "checkInsSinceRead": check_ins,
            "planChangesSinceRead": plan_changes,
            "newerReadsSinceRead": newer_reads,
            "subjectDateWorkoutsClosedSinceRead": closed_since,
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
            "meaning": (
                "Deterministic per-window means/medians over the metric history the "
                "Trends tab renders. Real measured series — a direction stated here is "
                "evidence, not a guess."
            ),
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

    async def _sleep_history(self, user_id: uuid.UUID, as_of: date) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Sleep)
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
        return [_sleep_state(row) for row in rows]

    # -- row loaders --------------------------------------------------------

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

    async def _activities_since(
        self,
        user_id: uuid.UUID,
        since_utc: datetime,
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(Activity.user_id == user_id, Activity.start_utc >= since_utc)
                    .order_by(desc(Activity.start_utc))
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
        return [
            {
                "entryDate": row.entry_date.isoformat(),
                "entryAtUtc": _dt(row.entry_at_utc),
                "subjectiveScore": row.subjective_score,
                "rpe": row.rpe,
                "feel": row.feel,
                # Mark's own words are data, never instructions (Decision #243).
                "notes": row.notes,
                "contentRole": "untrusted_user_data",
            }
            for row in rows
        ]

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
    """
    omitted: list[str] = []
    for section in _DROP_ORDER:
        if app_state_length(state) <= APP_STATE_CHAR_BUDGET:
            break
        if not state.get(section):
            continue
        state[section] = []
        omitted.append(section)
    trend_windows = state.get("trends", {}).get("recentWindows", [])
    while app_state_length(state) > APP_STATE_CHAR_BUDGET and len(trend_windows) > 1:
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


def _state_meaning(*, anchored: bool) -> str:
    base = "State of the app right now, assembled when this question was asked. "
    if anchored:
        return base + (
            "The read alongside it is the frozen record of what that read was written "
            "from; where the two differ, this block is the current truth."
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
    return value[:limit].rstrip() + "..."


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
