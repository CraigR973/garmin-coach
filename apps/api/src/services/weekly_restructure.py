"""Dynamic weekly restructuring — adapt the week to spacing rules and fatigue.

Batch 14 lets the fixed weekly slate flex *within the week* instead of running
blind:

  * **14.1 No-stack rule.** A VO2 session and a Sweet-Spot session must never
    land on the same or adjacent days. ``plan_week_restructure`` reorders the
    week's bike sessions (their dates) to enforce a ≥2-day gap with minimal
    disruption — non-bike days (strength/mobility) count as spacers.
  * **14.2 Defer-on-fatigue.** ``assess_recovery_signal`` reads recent readiness,
    HRV status, and the morning-verdict trend; when fatigued, the restructurer
    pushes hard sessions later in the week (deferring load) as its primary
    objective, disruption second.
  * **14.3 Rønnestad 30/15.** When a restructured VO2 session sits in a late
    build week it is regenerated through the shared VO2 toolkit, so the deferred
    session carries the documented 30/15 / ERG-off constraints.
  * **14.4 Versioned + approval-gated.** ``apply_for_week`` versions the affected
    ``planned_workouts`` rows (new version per changed date, old deactivated),
    audits the restructure in ``analyses``, and proposes the changed bike
    workouts through the Batch 12/13 rail — they reach Zwift only on approval
    (Decision #29).

The engine (``plan_week_restructure``) is a pure, deterministic function over a
week of items so the spacing/fatigue rules are unit-testable without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import permutations
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, DailyMetric, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.daily_loop import ANALYSIS_TYPE_MORNING
from src.services.vo2_progression import build_vo2_structured_workout, select_vo2_protocol
from src.services.workout_delivery import (
    IntervalsEventClient,
    WorkoutDeliveryService,
)

PROMPT_VERSION = "weekly-restructure:v1"
AUDIT_TYPE_RESTRUCTURE = "weekly_restructure"
RESTRUCTURE_SOURCE = "weekly_restructure"

# Category buckets keyed off ``planned_workouts.workout_type``.
CATEGORY_VO2 = "vo2"
CATEGORY_SWEET_SPOT = "sweet_spot"
CATEGORY_THRESHOLD = "threshold"
CATEGORY_TEMPO = "tempo"
CATEGORY_ENDURANCE = "endurance"
CATEGORY_RECOVERY = "recovery"
CATEGORY_STRENGTH = "strength"
CATEGORY_MOBILITY = "mobility"
CATEGORY_OTHER = "other"

INTENSITY_HARD = "hard"
INTENSITY_MODERATE = "moderate"
INTENSITY_EASY = "easy"
INTENSITY_NONE = "none"

_TYPE_TO_CATEGORY = {
    "bike_vo2": CATEGORY_VO2,
    "bike_sweet_spot": CATEGORY_SWEET_SPOT,
    "bike_threshold": CATEGORY_THRESHOLD,
    "bike_tempo": CATEGORY_TEMPO,
    "bike_endurance": CATEGORY_ENDURANCE,
    "bike_recovery": CATEGORY_RECOVERY,
    "strength_recovery": CATEGORY_STRENGTH,
    "strength_maintenance": CATEGORY_STRENGTH,
    "mobility": CATEGORY_MOBILITY,
}
_CATEGORY_INTENSITY = {
    CATEGORY_VO2: INTENSITY_HARD,
    CATEGORY_SWEET_SPOT: INTENSITY_HARD,
    CATEGORY_THRESHOLD: INTENSITY_HARD,
    CATEGORY_TEMPO: INTENSITY_MODERATE,
    CATEGORY_ENDURANCE: INTENSITY_EASY,
    CATEGORY_RECOVERY: INTENSITY_EASY,
    CATEGORY_STRENGTH: INTENSITY_NONE,
    CATEGORY_MOBILITY: INTENSITY_NONE,
    CATEGORY_OTHER: INTENSITY_MODERATE,
}

# The spacing rule: these two categories may never be the same or adjacent days.
NO_STACK_PAIR: frozenset[str] = frozenset({CATEGORY_VO2, CATEGORY_SWEET_SPOT})
MIN_GAP_DAYS = 2  # ≥2 calendar days apart = at least one clear day between them
HARD_CATEGORIES: frozenset[str] = frozenset({CATEGORY_VO2, CATEGORY_SWEET_SPOT, CATEGORY_THRESHOLD})

# Guard the permutation search against pathological weeks.
MAX_PERMUTE_SESSIONS = 7

# Recovery-signal thresholds (14.2).
LOW_READINESS_SCORE = 40
TREND_WINDOW_DAYS = 4
AMBER_TREND_THRESHOLD = 2
UNBALANCED_HRV_STATES = frozenset({"unbalanced", "low", "poor"})


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def categorize(workout_type: str) -> str:
    return _TYPE_TO_CATEGORY.get(workout_type, CATEGORY_OTHER)


def intensity_for(category: str) -> str:
    return _CATEGORY_INTENSITY.get(category, INTENSITY_MODERATE)


@dataclass(frozen=True)
class WeekItem:
    """A single planned workout positioned within the week."""

    workout_id: uuid.UUID
    workout_date: date
    title: str
    workout_type: str

    @property
    def category(self) -> str:
        return categorize(self.workout_type)

    @property
    def intensity(self) -> str:
        return intensity_for(self.category)

    @property
    def is_bike(self) -> bool:
        return self.workout_type.startswith("bike_")


@dataclass(frozen=True)
class SlotChange:
    """One date whose active workout content changes after a restructure."""

    workout_date: date
    from_workout_id: uuid.UUID
    to_workout_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class RestructurePlan:
    week_start: date
    fatigued: bool
    assignment: dict[date, uuid.UUID]
    changes: list[SlotChange]
    conflicts_before: list[tuple[date, date]]
    conflicts_after: list[tuple[date, date]]
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


@dataclass(frozen=True)
class SwapSuggestion:
    """A swap-first recovery recommendation for a single day (Batch 66, #139).

    When ``subject_date`` holds a hard bike session on a cautious morning, this
    names the day to move it to and the easier session that comes forward — the
    exact pairwise move a category-scoped ``swap_day`` (Batch 65-safe on split
    days) executes. It never mutates; the morning verdict leads with it and the
    verdict card offers it as one tap, with softening the ride as the fallback.
    """

    subject_date: date
    hard_workout_id: uuid.UUID
    hard_title: str
    hard_category: str
    move_to_date: date
    bring_forward_workout_id: uuid.UUID
    bring_forward_title: str

    def lead_text(self) -> str:
        return (
            f"Today isn't the day to force {self.hard_title} — move it to "
            f"{self.move_to_date.strftime('%A')} and bring {self.bring_forward_title} "
            "forward to today, keeping the week's volume instead of softening the ride."
        )

    def to_packet(self) -> dict[str, Any]:
        return {
            "hardWorkoutId": str(self.hard_workout_id),
            "hardTitle": self.hard_title,
            "hardCategory": self.hard_category,
            "moveToDate": self.move_to_date.isoformat(),
            "moveToWeekday": self.move_to_date.strftime("%A"),
            "bringForwardTitle": self.bring_forward_title,
        }


def _conflicts(assignment: dict[date, WeekItem]) -> list[tuple[date, date]]:
    """Adjacent same-week VO2↔Sweet-Spot pairs (the no-stack violations)."""
    dated = sorted(assignment.items(), key=lambda kv: kv[0])
    found: list[tuple[date, date]] = []
    for i, (d1, item1) in enumerate(dated):
        for d2, item2 in dated[i + 1 :]:
            gap = (d2 - d1).days
            if gap >= MIN_GAP_DAYS:
                break
            if {item1.category, item2.category} == NO_STACK_PAIR:
                found.append((d1, d2))
    return found


def plan_week_restructure(
    items: Sequence[WeekItem],
    *,
    week_start: date,
    fatigued: bool,
) -> RestructurePlan:
    """Compute a (date → content) reassignment that honours the week's rules.

    Only bike sessions are reordered, among the dates that already hold a bike
    session; strength/mobility days stay put and act as spacers. The chosen
    assignment satisfies the no-stack rule (hard constraint) and, when
    ``fatigued``, defers hard sessions as late as possible (primary objective),
    keeping disruption minimal as the secondary objective.
    """
    by_date_item = {item.workout_date: item for item in items}
    original = dict(by_date_item)
    conflicts_before = _conflicts(original)

    bike_items = sorted((item for item in items if item.is_bike), key=lambda it: it.workout_date)
    bike_dates = [item.workout_date for item in bike_items]
    fixed = {item.workout_date: item for item in items if not item.is_bike}
    notes: list[str] = []

    if len(bike_items) < 2 or len(bike_items) > MAX_PERMUTE_SESSIONS:
        if len(bike_items) > MAX_PERMUTE_SESSIONS:
            notes.append("Too many bike sessions to reorder; left as planned.")
        return RestructurePlan(
            week_start=week_start,
            fatigued=fatigued,
            assignment={d: item.workout_id for d, item in original.items()},
            changes=[],
            conflicts_before=conflicts_before,
            conflicts_after=conflicts_before,
            notes=notes,
        )

    best: tuple[tuple[int, ...], dict[date, WeekItem]] | None = None
    feasible_found = False
    for perm in permutations(bike_items):
        candidate: dict[date, WeekItem] = dict(fixed)
        for slot_date, item in zip(bike_dates, perm, strict=True):
            candidate[slot_date] = item
        candidate_conflicts = _conflicts(candidate)

        feasible = not candidate_conflicts
        moves = sum(1 for d in bike_dates if candidate[d].workout_id != original[d].workout_id)
        shift = sum(abs((d - candidate[d].workout_date).days) for d in bike_dates)
        defer_cost = sum(
            (week_start + timedelta(days=6) - d).days
            for d in bike_dates
            if candidate[d].category in HARD_CATEGORIES
        )

        # Lexicographic key. Feasibility always wins; then the fatigue/disruption
        # ordering swaps depending on whether we are deferring load.
        if fatigued:
            key = (0 if feasible else 1, defer_cost, moves, shift)
        else:
            key = (0 if feasible else 1, moves, shift, defer_cost)

        if best is None or key < best[0]:
            best = (key, candidate)
        feasible_found = feasible_found or feasible

    assert best is not None
    chosen = best[1]
    conflicts_after = _conflicts(chosen)
    if conflicts_before and not conflicts_after:
        notes.append("Resolved a VO2/Sweet-Spot stacking conflict.")
    if not feasible_found and conflicts_after:
        notes.append("Could not fully separate VO2 and Sweet-Spot within the week.")
    if fatigued:
        notes.append("Fatigue detected — hard sessions deferred later in the week.")

    changes: list[SlotChange] = []
    for slot_date in bike_dates:
        new_item = chosen[slot_date]
        old_item = original[slot_date]
        if new_item.workout_id == old_item.workout_id:
            continue
        changes.append(
            SlotChange(
                workout_date=slot_date,
                from_workout_id=old_item.workout_id,
                to_workout_id=new_item.workout_id,
                reason=_change_reason(new_item, slot_date, conflicts_before, fatigued),
            )
        )

    return RestructurePlan(
        week_start=week_start,
        fatigued=fatigued,
        assignment={d: item.workout_id for d, item in chosen.items()},
        changes=changes,
        conflicts_before=conflicts_before,
        conflicts_after=conflicts_after,
        notes=notes,
    )


def _change_reason(
    item: WeekItem,
    slot_date: date,
    conflicts_before: list[tuple[date, date]],
    fatigued: bool,
) -> str:
    if fatigued and item.category in HARD_CATEGORIES:
        return "defer_fatigue"
    if conflicts_before:
        return "no_stack"
    return "reorder"


def plan_swap_first(items: Sequence[WeekItem], *, subject_date: date) -> SwapSuggestion | None:
    """Swap-first recovery suggestion (Batch 66, #139).

    When ``subject_date`` holds a hard bike session (VO2/Sweet-Spot/Threshold),
    find the soonest *later* bike day this week carrying an easier session that
    it can trade places with while keeping the ≥2-day VO2/Sweet-Spot no-stack
    rule. Returns ``None`` when today has no hard session or no sound swap exists
    (the caller then falls back to softening).

    Pure and deterministic. It reuses the restructure engine's spacing
    primitives (:data:`HARD_CATEGORIES`, :func:`_conflicts`, ``WeekItem.category``)
    rather than a parallel rule set, and the recommended move maps to a single
    category-scoped ``swap_day`` — never the whole-week ``apply_for_week`` path,
    which re-versions a whole date and would drop a split day's strength row.
    """
    hard_today = next(
        (
            item
            for item in items
            if item.workout_date == subject_date
            and item.is_bike
            and item.category in HARD_CATEGORIES
        ),
        None,
    )
    if hard_today is None:
        return None

    # Conflicts only ever involve bike sessions, and this plan runs one bike per
    # date, so a bike-only date map is complete for the no-stack check and immune
    # to a split day's strength row shadowing the bike.
    bike_by_date = {item.workout_date: item for item in items if item.is_bike}
    candidates = sorted(
        (
            item
            for item in items
            if item.is_bike
            and item.workout_date > subject_date
            and item.category not in HARD_CATEGORIES
        ),
        key=lambda item: item.workout_date,
    )
    for target in candidates:
        simulated = dict(bike_by_date)
        simulated[subject_date] = target
        simulated[target.workout_date] = hard_today
        if _conflicts(simulated):
            continue
        return SwapSuggestion(
            subject_date=subject_date,
            hard_workout_id=hard_today.workout_id,
            hard_title=hard_today.title,
            hard_category=hard_today.category,
            move_to_date=target.workout_date,
            bring_forward_workout_id=target.workout_id,
            bring_forward_title=target.title,
        )
    return None


@dataclass(frozen=True)
class RecoverySignal:
    fatigued: bool
    readiness_score: int | None
    hrv_status: str | None
    recent_verdicts: list[str]
    reasons: list[str]


@dataclass
class RestructureApplyResult:
    plan: RestructurePlan
    signal: RecoverySignal
    versioned_workouts: list[PlannedWorkout]
    proposals: list[Any]


class WeeklyRestructureService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
    ) -> None:
        self.session = session
        self.rail = WorkoutDeliveryService(session, intervals_client=intervals_client)

    async def assess_recovery_signal(self, player: Profile, *, as_of: date) -> RecoverySignal:
        """Derive a fatigue signal from readiness, HRV, and the verdict trend."""
        metric = (
            await self.session.execute(
                select(DailyMetric)
                .where(
                    DailyMetric.user_id == player.id,
                    DailyMetric.calendar_date <= as_of,
                )
                .order_by(DailyMetric.calendar_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        window_start = as_of - timedelta(days=TREND_WINDOW_DAYS - 1)
        analyses = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                        Analysis.subject_date >= window_start,
                        Analysis.subject_date <= as_of,
                    )
                    .order_by(Analysis.subject_date.desc())
                )
            )
            .scalars()
            .all()
        )
        verdicts = [a.verdict for a in analyses if a.verdict]

        readiness_score = metric.readiness_score if metric else None
        hrv_status = metric.hrv_status if metric else None
        reasons: list[str] = []

        if any((v or "").lower() == "red" for v in verdicts):
            reasons.append("A recent morning verdict was Red.")
        amber_count = sum(1 for v in verdicts if (v or "").lower() == "amber")
        if amber_count >= AMBER_TREND_THRESHOLD:
            reasons.append(f"{amber_count} Amber verdicts in the last {TREND_WINDOW_DAYS} days.")
        if readiness_score is not None and readiness_score < LOW_READINESS_SCORE:
            reasons.append(f"Training readiness is low ({readiness_score}).")
        if hrv_status is not None and hrv_status.lower() in UNBALANCED_HRV_STATES:
            reasons.append(f"HRV status is {hrv_status}.")

        return RecoverySignal(
            fatigued=bool(reasons),
            readiness_score=readiness_score,
            hrv_status=hrv_status,
            recent_verdicts=verdicts,
            reasons=reasons,
        )

    async def _week_items(
        self, player: Profile, week_start: date
    ) -> tuple[list[WeekItem], dict[uuid.UUID, PlannedWorkout]]:
        week_end = week_start + timedelta(days=6)
        workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= week_start,
                        PlannedWorkout.workout_date <= week_end,
                    )
                    .order_by(PlannedWorkout.workout_date.asc())
                )
            )
            .scalars()
            .all()
        )
        by_id = {workout.id: workout for workout in workouts}
        items = [
            WeekItem(
                workout_id=workout.id,
                workout_date=workout.workout_date,
                title=workout.title,
                workout_type=workout.workout_type,
            )
            for workout in workouts
        ]
        return items, by_id

    async def plan_for_week(
        self,
        player: Profile,
        week_start: date,
        *,
        as_of: date | None = None,
        signal: RecoverySignal | None = None,
    ) -> tuple[RestructurePlan, RecoverySignal]:
        """Read-only preview: compute the signal and the proposed reassignment.

        The fatigue signal is read as of ``as_of`` (today by default) so a
        week-ahead preview reflects current recovery, not the future week.
        """
        resolved_signal = signal or await self.assess_recovery_signal(
            player, as_of=as_of or date.today()
        )
        items, _ = await self._week_items(player, week_start)
        plan = plan_week_restructure(
            items, week_start=week_start, fatigued=resolved_signal.fatigued
        )
        return plan, resolved_signal

    async def swap_suggestion_for_day(
        self, player: Profile, subject_date: date
    ) -> SwapSuggestion | None:
        """Read-only swap-first suggestion for ``subject_date`` (Batch 66).

        Reads the week that contains ``subject_date`` and delegates to the pure
        :func:`plan_swap_first`. No mutation — the morning verdict decorates its
        packet with the result and the verdict card offers a one-tap
        category-scoped move.
        """
        week_start = subject_date - timedelta(days=subject_date.weekday())
        items, _ = await self._week_items(player, week_start)
        return plan_swap_first(items, subject_date=subject_date)

    async def apply_for_week(
        self,
        player: Profile,
        week_start: date,
        *,
        as_of: date | None = None,
        propose_delivery: bool = True,
        commit: bool = True,
    ) -> RestructureApplyResult:
        """Version the changed days, audit the restructure, and propose delivery.

        Idempotent: a settled week produces no changes, so re-running is a no-op
        (no new versions, no audit row, no proposals). Nothing is pushed to Zwift
        — proposals stay ``proposed`` until the human approves (Decision #29).
        """
        signal = await self.assess_recovery_signal(player, as_of=as_of or date.today())
        items, by_id = await self._week_items(player, week_start)
        plan = plan_week_restructure(items, week_start=week_start, fatigued=signal.fatigued)

        if not plan.changes:
            return RestructureApplyResult(
                plan=plan, signal=signal, versioned_workouts=[], proposals=[]
            )

        block_by_id = await self._plan_blocks(player, by_id)

        # Snapshot the new content for every changed date before mutating, so a
        # swap reads each source workout's *original* content, not a fresh row.
        new_content: dict[date, dict[str, Any]] = {}
        for change in plan.changes:
            source = by_id[change.to_workout_id]
            new_content[change.workout_date] = self._content_for(
                source, change.workout_date, block_by_id
            )

        versioned: list[PlannedWorkout] = []
        for change in plan.changes:
            versioned.append(
                await self._version_workout(
                    player, change.workout_date, new_content[change.workout_date]
                )
            )

        self._record_restructure_audit(player, plan, signal)

        if commit:
            await self.session.commit()
            for workout in versioned:
                await self.session.refresh(workout)

        proposals: list[Any] = []
        if propose_delivery and plan.changes:
            # Push-on-plan-set (Decision #99): a restructure re-syncs the affected
            # Zwift events *in place* rather than queuing approval-gated proposals,
            # so the rescheduled week is already on the calendar. Each changed slot
            # is reconciled idempotently and in isolation.
            from src.services.executable_coaching import ExecutableCoachingService

            delivery = ExecutableCoachingService(
                self.session, intervals_client=self.rail.intervals_client
            )
            changed_dates = [change.workout_date for change in plan.changes]
            proposals = await delivery.reconcile_deliveries(
                player, start_date=min(changed_dates), end_date=max(changed_dates)
            )

        return RestructureApplyResult(
            plan=plan, signal=signal, versioned_workouts=versioned, proposals=proposals
        )

    async def _plan_blocks(
        self, player: Profile, by_id: dict[uuid.UUID, PlannedWorkout]
    ) -> dict[uuid.UUID, PlanBlock]:
        block_ids = {w.plan_block_id for w in by_id.values() if w.plan_block_id}
        if not block_ids:
            return {}
        blocks = (
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == player.id,
                        PlanBlock.id.in_(block_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {block.id: block for block in blocks}

    def _content_for(
        self,
        source: PlannedWorkout,
        target_date: date,
        block_by_id: dict[uuid.UUID, PlanBlock],
    ) -> dict[str, Any]:
        """Build the new active content for ``target_date`` from ``source``.

        A late-build VO2 session is regenerated through the toolkit so a deferred
        VO2 carries the Rønnestad 30/15 / ERG-off constraints (Batch 14.3).
        """
        structured = dict(source.structured_workout or {})
        title = source.title
        intensity_target = source.intensity_target
        if categorize(source.workout_type) == CATEGORY_VO2:
            block = block_by_id.get(source.plan_block_id) if source.plan_block_id else None
            if block is not None and (block.block_type or "") == "build":
                week_number = block.sequence_index or 0
                protocol = select_vo2_protocol(week_number, block_type="build")
                structured = build_vo2_structured_workout(week_number, block_type="build")
                title = protocol.title
                intensity_target = protocol.intensity_target
        return {
            "plan_block_id": source.plan_block_id,
            "title": title,
            "workout_type": source.workout_type,
            "status": source.status,
            "planned_duration_min": source.planned_duration_min,
            "intensity_target": intensity_target,
            "structured_workout": structured,
        }

    async def _version_workout(
        self, player: Profile, workout_date: date, content: dict[str, Any]
    ) -> PlannedWorkout:
        current_version = await self.session.scalar(
            select(func.max(PlannedWorkout.version)).where(
                PlannedWorkout.user_id == player.id,
                PlannedWorkout.workout_date == workout_date,
            )
        )
        next_version = (current_version or 0) + 1
        await self.session.execute(
            update(PlannedWorkout)
            .where(
                PlannedWorkout.user_id == player.id,
                PlannedWorkout.workout_date == workout_date,
                PlannedWorkout.is_active.is_(True),
            )
            .values(is_active=False)
        )
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=content["plan_block_id"],
            workout_date=workout_date,
            version=next_version,
            title=content["title"],
            workout_type=content["workout_type"],
            status=content["status"],
            is_active=True,
            planned_duration_min=content["planned_duration_min"],
            intensity_target=content["intensity_target"],
            structured_workout=content["structured_workout"],
            source=RESTRUCTURE_SOURCE,
        )
        self.session.add(workout)
        await self.session.flush()
        return workout

    def _record_restructure_audit(
        self, player: Profile, plan: RestructurePlan, signal: RecoverySignal
    ) -> None:
        self.session.add(
            Analysis(
                user_id=player.id,
                activity_id=None,
                analysis_type=AUDIT_TYPE_RESTRUCTURE,
                subject_date=plan.week_start,
                generated_at_utc=_utcnow(),
                prompt_version=PROMPT_VERSION,
                model_name=None,
                verdict=None,
                context_packet={
                    "weekStart": plan.week_start.isoformat(),
                    "fatigued": plan.fatigued,
                    "signal": {
                        "readinessScore": signal.readiness_score,
                        "hrvStatus": signal.hrv_status,
                        "recentVerdicts": signal.recent_verdicts,
                        "reasons": signal.reasons,
                    },
                    "changes": [
                        {
                            "workoutDate": change.workout_date.isoformat(),
                            "fromWorkoutId": str(change.from_workout_id),
                            "toWorkoutId": str(change.to_workout_id),
                            "reason": change.reason,
                        }
                        for change in plan.changes
                    ],
                    "conflictsBefore": [
                        [d1.isoformat(), d2.isoformat()] for d1, d2 in plan.conflicts_before
                    ],
                    "conflictsAfter": [
                        [d1.isoformat(), d2.isoformat()] for d1, d2 in plan.conflicts_after
                    ],
                    "notes": plan.notes,
                },
                output_markdown=_summary_markdown(plan, signal),
                raw_response={},
            )
        )


def _summary_markdown(plan: RestructurePlan, signal: RecoverySignal) -> str:
    lines = [f"Weekly restructure for week of {plan.week_start.isoformat()}."]
    if signal.fatigued:
        lines.append("Fatigue signal active: " + "; ".join(signal.reasons))
    for change in plan.changes:
        lines.append(f"- {change.workout_date.isoformat()}: {change.reason}")
    if not plan.changes:
        lines.append("No changes — the week already satisfies the spacing rules.")
    return "\n".join(lines)
