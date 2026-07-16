from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, ManualEntry, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.coaching_state import BLOCK_SEQUENCE
from src.services.executable_coaching import (
    WORKOUT_STATUS_SKIPPED,
    ExecutableCoachingService,
    blocks_red_vo2,
)
from src.services.holiday_pause import HolidayPauseService
from src.services.structured_workout_builder import (
    BuiltCustomBikeWorkout,
    FreeformBikeWorkoutSpec,
    WorkoutWarning,
    build_freeform_bike_workout,
    is_indoor_bike_workout,
)
from src.services.workout_categories import (
    DAY_CATEGORY_CYCLE,
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WEIGHTS,
    DayState,
    day_state_for_workout_types,
)
from src.services.workout_completion import WORKOUT_STATUS_COMPLETED
from src.services.workout_delivery import (
    IntervalsEventClient,
    build_structured_workout_ir,
    expand_structured_steps,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


DONE_ADHERENCE_STATUSES = {"completed", "modified", "done", "did_something_else"}
RESET_WEEK_KEY = "manualResetWeek"
RESET_WEEK_SOURCE = "reset_week"
RESET_WEEK_POWER_PCT = 65


@dataclass(frozen=True)
class WorkoutActionResult:
    """An add/edit result plus any non-blocking authoring warnings (Batch 88).

    Quick-add and non-custom paths carry an empty ``warnings`` list; the free-form
    manual builder can surface power / ramp / Red-VO2 advisories on a successful save.
    """

    workout: PlannedWorkout
    warnings: list[WorkoutWarning]


def _pattern_minutes(value: float) -> str:
    # Matches the plan JSON's authored pattern grammar, e.g. "2min" (Batch 67's
    # ``_expand_pattern`` parses "Nmin" / "Nmin / Mmin @X%" via ``_duration_sec``).
    return f"{value:g}min"


TOTAL_WEEKS = len(BLOCK_SEQUENCE)
PostActivityKind = Literal["ride", "strength", "flexibility", "walk"]

_BLOCK_TYPE_LABELS = {
    "recovery": "Reset",
    "taper": "Taper",
    "consolidation": "Consolidation",
}


@dataclass(frozen=True)
class WeekCharacter:
    """Batch 81: what a day's week is, for the organiser header.

    ``label`` is the human-readable character — "Build n/13" / "Reset" /
    "Taper" / "Consolidation" / "Holiday" — used verbatim by the Week tab.
    A holiday window overrides the underlying block's label because a paused
    week has no training character of its own.
    """

    label: str
    sequence_index: int | None
    block_type: str | None
    is_holiday: bool
    is_reset: bool


def week_character_for_day(
    block: PlanBlock | None, *, is_holiday: bool, is_reset: bool = False
) -> WeekCharacter | None:
    if is_holiday:
        return WeekCharacter(
            label="Holiday",
            sequence_index=block.sequence_index if block else None,
            block_type=block.block_type if block else None,
            is_holiday=True,
            is_reset=False,
        )
    if block is None or block.block_type is None:
        return None
    if is_reset:
        label = "Light reset"
    elif block.block_type == "build":
        label = f"Build {block.sequence_index}/{TOTAL_WEEKS}" if block.sequence_index else "Build"
    else:
        label = _BLOCK_TYPE_LABELS.get(block.block_type, block.block_type.title())
    return WeekCharacter(
        label=label,
        sequence_index=block.sequence_index,
        block_type=block.block_type,
        is_holiday=False,
        is_reset=is_reset,
    )


@dataclass(frozen=True)
class PlanDay:
    date: date
    day_state: DayState
    workouts: list[PlannedWorkout]
    activities: list["PlanActivity"]
    week_character: WeekCharacter | None = None


@dataclass(frozen=True)
class PlanSchedule:
    start_date: date
    days: list[PlanDay]


@dataclass(frozen=True)
class PlanActivity:
    activity: Activity
    activity_kind: PostActivityKind


@dataclass(frozen=True)
class QuickAddOption:
    subtype: str
    label: str
    title: str
    workout_type: str
    intensity_target: str
    default_duration_min: int
    min_duration_min: int
    max_duration_min: int
    warmup_min: int
    cooldown_min: int
    main_target: str
    structured_format: str
    structured_focus: str | None = None
    # Batch 75: real ramp warm-up/cool-down (Batch 67 step grammar) instead of a
    # flat "easy" block. None on both ends preserves the pre-Batch-75 flat shape.
    warmup_ramp_pct: tuple[int, int] | None = None
    cooldown_ramp_pct: tuple[int, int] | None = None
    # Batch 75: authors the main block as an interval pattern (work/recovery
    # repeats) instead of one steady block, e.g. VO2 "with efforts". The chosen
    # duration's main portion is covered by the nearest whole rep count in
    # [min_reps, max_reps], so the delivered duration may differ slightly from
    # the requested one — the returned workout always reports the true total.
    interval_work_min: float | None = None
    interval_recovery_min: float | None = None
    interval_recovery_target: str | None = None
    min_reps: int | None = None
    max_reps: int | None = None


QUICK_ADD_CATALOG: dict[str, list[QuickAddOption]] = {
    DAY_CATEGORY_CYCLE: [
        QuickAddOption(
            subtype="endurance",
            label="Endurance",
            title="Endurance ride",
            workout_type="bike_endurance",
            intensity_target="Zone 2",
            default_duration_min=45,
            min_duration_min=20,
            max_duration_min=90,
            warmup_min=10,
            cooldown_min=5,
            main_target="zone 2",
            structured_format="bike",
        ),
        QuickAddOption(
            subtype="sweet_spot",
            label="Sweet Spot",
            title="Sweet Spot ride",
            workout_type="bike_sweet_spot",
            intensity_target="Sweet Spot ~89% FTP",
            default_duration_min=40,
            min_duration_min=25,
            max_duration_min=75,
            warmup_min=10,
            cooldown_min=5,
            main_target="89%",
            structured_format="bike",
        ),
        QuickAddOption(
            subtype="recovery",
            label="Recovery spin",
            title="Recovery spin",
            workout_type="bike_recovery",
            intensity_target="Recovery ~55% FTP",
            default_duration_min=30,
            min_duration_min=15,
            max_duration_min=45,
            warmup_min=5,
            cooldown_min=5,
            main_target="55%",
            structured_format="bike",
        ),
        QuickAddOption(
            subtype="tempo",
            label="Tempo / Threshold (Z3)",
            title="Tempo / Threshold ride",
            workout_type="bike_tempo",
            intensity_target="Tempo/Threshold ~84% FTP",
            default_duration_min=40,
            min_duration_min=25,
            max_duration_min=65,
            warmup_min=8,
            cooldown_min=5,
            main_target="84%",
            structured_format="bike",
            warmup_ramp_pct=(55, 80),
            cooldown_ramp_pct=(65, 40),
        ),
        QuickAddOption(
            subtype="vo2_efforts",
            label="VO2 (with efforts)",
            title="VO2 with efforts",
            workout_type="bike_vo2",
            intensity_target="VO2 ~118% FTP efforts",
            default_duration_min=38,
            min_duration_min=30,
            max_duration_min=50,
            warmup_min=10,
            cooldown_min=8,
            main_target="118%",
            structured_format="bike",
            warmup_ramp_pct=(55, 80),
            cooldown_ramp_pct=(65, 40),
            interval_work_min=2.0,
            interval_recovery_min=2.0,
            interval_recovery_target="60%",
            min_reps=3,
            max_reps=8,
        ),
    ],
    DAY_CATEGORY_WEIGHTS: [
        QuickAddOption(
            subtype="maintenance",
            label="Strength maintenance",
            title="Strength maintenance",
            workout_type="strength_maintenance",
            intensity_target="maintenance",
            default_duration_min=20,
            min_duration_min=10,
            max_duration_min=40,
            warmup_min=0,
            cooldown_min=0,
            main_target="maintenance",
            structured_format="strength",
            structured_focus="maintenance",
        ),
        QuickAddOption(
            subtype="recovery",
            label="Strength recovery",
            title="Strength recovery",
            workout_type="strength_recovery",
            intensity_target="recovery",
            default_duration_min=15,
            min_duration_min=10,
            max_duration_min=30,
            warmup_min=0,
            cooldown_min=0,
            main_target="recovery",
            structured_format="strength",
            structured_focus="recovery",
        ),
    ],
    DAY_CATEGORY_FLEXIBILITY: [
        QuickAddOption(
            subtype="mobility",
            label="Flexibility",
            title="Flexibility",
            workout_type="mobility",
            intensity_target="easy",
            default_duration_min=16,
            min_duration_min=10,
            max_duration_min=30,
            warmup_min=0,
            cooldown_min=0,
            main_target="easy",
            structured_format="mobility",
        ),
    ],
}


def quick_add_options(category: str) -> list[QuickAddOption]:
    options = QUICK_ADD_CATALOG.get(category)
    if options is None:
        raise HTTPException(status_code=422, detail="Unknown workout category")
    return options


def _quick_add_option(category: str, subtype: str) -> QuickAddOption:
    for option in quick_add_options(category):
        if option.subtype == subtype:
            return option
    raise HTTPException(status_code=422, detail="Unknown workout subtype for category")


def workout_for_selection(
    category: str, *, subtype: str | None, duration_min: int | None
) -> dict[str, Any]:
    options = quick_add_options(category)
    option = _quick_add_option(category, subtype) if subtype else options[0]
    duration = duration_min if duration_min is not None else option.default_duration_min
    if duration < option.min_duration_min or duration > option.max_duration_min:
        raise HTTPException(
            status_code=422,
            detail=(
                f"durationMin for '{option.subtype}' must be between "
                f"{option.min_duration_min} and {option.max_duration_min}"
            ),
        )

    if option.structured_format == "bike":
        if option.warmup_ramp_pct is not None:
            warmup_start, warmup_end = option.warmup_ramp_pct
            warmup_step = {
                "label": "Warm-up ramp",
                "minutes": option.warmup_min,
                "ramp": [warmup_start, warmup_end],
            }
        else:
            warmup_step = {"label": "Warm-up", "minutes": option.warmup_min, "target": "easy"}

        if option.cooldown_ramp_pct is not None:
            cooldown_start, cooldown_end = option.cooldown_ramp_pct
            cooldown_step = {
                "label": "Cool-down ramp",
                "minutes": option.cooldown_min,
                "ramp": [cooldown_start, cooldown_end],
            }
        else:
            cooldown_step = {"label": "Cool-down", "minutes": option.cooldown_min, "target": "easy"}

        if option.interval_work_min is not None:
            assert option.interval_recovery_min is not None
            assert option.min_reps is not None and option.max_reps is not None
            cycle_min = option.interval_work_min + option.interval_recovery_min
            remaining_min = duration - option.warmup_min - option.cooldown_min
            reps = max(option.min_reps, min(option.max_reps, round(remaining_min / cycle_min)))
            main_min = int(round(reps * cycle_min))
            duration = option.warmup_min + main_min + option.cooldown_min
            main_step: dict[str, Any] = {
                "label": option.label,
                "target": option.main_target,
                "pattern": (
                    f"{reps} x {_pattern_minutes(option.interval_work_min)} / "
                    f"{_pattern_minutes(option.interval_recovery_min)} "
                    f"@{option.interval_recovery_target}"
                ),
            }
        else:
            main_min = duration - option.warmup_min - option.cooldown_min
            main_step = {"label": option.label, "minutes": main_min, "target": option.main_target}

        structured_workout: dict[str, Any] = {
            "format": "bike",
            "steps": [warmup_step, main_step, cooldown_step],
        }
    elif option.structured_format == "strength":
        structured_workout = {"format": "strength", "focus": option.structured_focus}
    else:
        structured_workout = {"format": option.structured_format}

    return {
        "title": option.title,
        "workout_type": option.workout_type,
        "planned_duration_min": duration,
        "intensity_target": option.intensity_target,
        "structured_workout": structured_workout,
    }


def default_workout_for_category(category: str) -> dict[str, Any]:
    return workout_for_selection(category, subtype=None, duration_min=None)


def _template_value(template: dict[str, Any] | BuiltCustomBikeWorkout, key: str) -> Any:
    if isinstance(template, BuiltCustomBikeWorkout):
        return getattr(template, key)
    return template[key]


def _reset_info(block: PlanBlock | None) -> dict[str, Any]:
    if block is None or not isinstance(block.goals_json, dict):
        return {}
    raw = block.goals_json.get(RESET_WEEK_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _block_has_active_reset(block: PlanBlock | None) -> bool:
    return _reset_info(block).get("active") is True


def _set_block_reset(
    block: PlanBlock,
    *,
    active: bool,
    week_start: date,
    week_end: date,
    originals: list[dict[str, Any]],
) -> None:
    goals = dict(block.goals_json or {})
    current = dict(goals.get(RESET_WEEK_KEY) or {})
    current.update(
        {
            "active": active,
            "mode": "z2_keep_strength",
            "weekStart": week_start.isoformat(),
            "weekEnd": week_end.isoformat(),
            "powerPct": RESET_WEEK_POWER_PCT,
            "originals": originals,
            "updatedAtUtc": _utcnow().isoformat() + "Z",
        }
    )
    if active and "recordedAtUtc" not in current:
        current["recordedAtUtc"] = current["updatedAtUtc"]
    if not active:
        current["clearedAtUtc"] = current["updatedAtUtc"]
    goals[RESET_WEEK_KEY] = current
    block.goals_json = goals


def _is_mutable_bike_workout(workout: PlannedWorkout) -> bool:
    structured = workout.structured_workout or {}
    return (
        workout.status != WORKOUT_STATUS_COMPLETED
        and workout.source != RESET_WEEK_SOURCE
        and isinstance(structured, dict)
        and structured.get("format") == "bike"
    )


def _reset_title(title: str) -> str:
    return title if title.startswith("Reset Z2:") else f"Reset Z2: {title}"


def _is_reset_structured_workout(workout: PlannedWorkout) -> bool:
    structured = workout.structured_workout or {}
    if not isinstance(structured, dict):
        return False
    raw = structured.get("resetWeek")
    return isinstance(raw, dict) and raw.get("active") is True


def _reset_structured_workout(
    workout: PlannedWorkout, *, week_start: date, week_end: date
) -> dict[str, Any]:
    structured = dict(workout.structured_workout or {})
    expanded = expand_structured_steps(structured, workout.intensity_target)
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(expanded):
        duration_min = int(step.get("durationSec", 0)) / 60
        steps.append(
            {
                "label": f"Reset Z2 {index + 1}",
                "minutes": duration_min,
                "target": f"{RESET_WEEK_POWER_PCT}%",
            }
        )
    reset = {
        "format": "bike",
        "delivery": structured.get("delivery", "indoor"),
        "source": RESET_WEEK_SOURCE,
        "steps": steps,
        "totalDurationMin": round(sum(float(step["minutes"]) for step in steps)),
        "resetWeek": {
            "active": True,
            "mode": "z2_keep_strength",
            "weekStart": week_start.isoformat(),
            "weekEnd": week_end.isoformat(),
            "powerPct": RESET_WEEK_POWER_PCT,
            "originalWorkoutId": str(workout.id),
            "originalVersion": workout.version,
            "originalTitle": workout.title,
        },
    }
    if "cadenceCriticalExpanded" in structured:
        reset["cadenceCriticalExpanded"] = structured["cadenceCriticalExpanded"]
    return reset


def _planned_workout_activity_kind(workout: PlannedWorkout) -> PostActivityKind | None:
    category = day_state_for_workout_types([workout.workout_type]).categories
    if DAY_CATEGORY_CYCLE in category:
        return "ride"
    if DAY_CATEGORY_WEIGHTS in category:
        return "strength"
    if DAY_CATEGORY_FLEXIBILITY in category:
        return "flexibility"
    return None


def _is_flexibility_activity(activity: Activity) -> bool:
    name = (activity.activity_name or "").lower()
    activity_type = (activity.activity_type or "").lower()
    if activity_type == "yoga":
        return False
    return "mobility" in name


def _is_strength_activity(activity: Activity) -> bool:
    return bool(activity.exclude_from_recovery)


def _is_deliberate_walk(activity: Activity) -> bool:
    return (activity.activity_type or "").lower() == "walking" and (
        (activity.duration_sec or 0) >= 30 * 60 or (activity.distance_m or 0) >= 3_000
    )


def _is_ride_activity(activity: Activity) -> bool:
    activity_type = (activity.activity_type or "").lower()
    activity_name = (activity.activity_name or "").lower()
    if activity_type == "virtual_ride" or activity_type.endswith("_ride"):
        return True
    return any(token in activity_type or token in activity_name for token in ("cycling", "bike", "biking"))


def _post_activity_kind(activity: Activity) -> PostActivityKind | None:
    if _is_flexibility_activity(activity):
        return "flexibility"
    if _is_strength_activity(activity):
        return "strength"
    if _is_deliberate_walk(activity):
        return "walk"
    if _is_ride_activity(activity):
        return "ride"
    return None


class PlanActionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
    ) -> None:
        self.session = session
        self.executable = ExecutableCoachingService(session, intervals_client=intervals_client)

    async def schedule(self, player: Profile, *, start_date: date, days: int) -> PlanSchedule:
        end_date = start_date + timedelta(days=max(days, 1) - 1)
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                    )
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        by_date: dict[date, list[PlannedWorkout]] = {}
        for workout in rows:
            by_date.setdefault(workout.workout_date, []).append(workout)
        activities_by_date = await self._activities_by_date(player.id, start_date, end_date)

        # Batch 81: attach each day's PlanBlock character + any active holiday
        # window so the organiser shows where he is in the 13-week slate.
        blocks = (
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == player.id,
                        PlanBlock.start_date <= end_date,
                        PlanBlock.end_date >= start_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        holiday_window = await HolidayPauseService(self.session).get_active_window(player)

        def block_for(day: date) -> PlanBlock | None:
            return next((b for b in blocks if b.start_date <= day <= b.end_date), None)

        def is_holiday(day: date) -> bool:
            return (
                holiday_window is not None
                and holiday_window.start_date <= day <= holiday_window.end_date
            )

        def is_reset(block: PlanBlock | None) -> bool:
            return _block_has_active_reset(block)

        plan_days: list[PlanDay] = []
        for offset in range(max(days, 1)):
            current = start_date + timedelta(days=offset)
            workouts = by_date.get(current, [])
            block = block_for(current)
            plan_days.append(
                PlanDay(
                    date=current,
                    day_state=day_state_for_workout_types([w.workout_type for w in workouts]),
                    workouts=workouts,
                    activities=activities_by_date.get(current, []),
                    week_character=week_character_for_day(
                        block, is_holiday=is_holiday(current), is_reset=is_reset(block)
                    ),
                )
            )
        return PlanSchedule(start_date=start_date, days=plan_days)

    async def _activities_by_date(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[date, list[PlanActivity]]:
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= datetime.combine(start_date, datetime.min.time()),
                        Activity.start_utc < datetime.combine(
                            end_date + timedelta(days=1), datetime.min.time()
                        ),
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )

        workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status == WORKOUT_STATUS_COMPLETED,
                    )
                )
            )
            .scalars()
            .all()
        )
        completed_kinds_by_day: dict[date, set[PostActivityKind]] = {}
        for workout in workouts:
            kind = _planned_workout_activity_kind(workout)
            if kind is None:
                continue
            completed_kinds_by_day.setdefault(workout.workout_date, set()).add(kind)

        by_date: dict[date, list[PlanActivity]] = {}
        for activity in rows:
            kind = _post_activity_kind(activity)
            if kind is None:
                continue
            day = activity.start_utc.date()
            if kind in completed_kinds_by_day.get(day, set()):
                continue
            by_date.setdefault(day, []).append(PlanActivity(activity=activity, activity_kind=kind))
        return by_date

    async def add_workout(
        self,
        player: Profile,
        *,
        workout_date: date,
        category: str,
        subtype: str | None = None,
        duration_min: int | None = None,
        custom_bike: FreeformBikeWorkoutSpec | None = None,
    ) -> WorkoutActionResult:
        template: dict[str, Any] | BuiltCustomBikeWorkout
        warnings: list[WorkoutWarning] = []
        if custom_bike is not None:
            if category != DAY_CATEGORY_CYCLE:
                raise HTTPException(
                    status_code=422,
                    detail="Custom structured workouts are only supported for cycle sessions.",
                )
            # Mark's explicit manual authoring path: gates warn, they don't block.
            template, warnings = build_freeform_bike_workout(custom_bike, soft_gates=True)
        else:
            template = workout_for_selection(category, subtype=subtype, duration_min=duration_min)
        version = await self._next_version(player.id, workout_date)
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=None,
            workout_date=workout_date,
            version=version,
            title=_template_value(template, "title"),
            workout_type=_template_value(template, "workout_type"),
            status="planned",
            is_active=True,
            planned_duration_min=_template_value(template, "planned_duration_min"),
            intensity_target=_template_value(template, "intensity_target"),
            structured_workout=_template_value(template, "structured_workout"),
            source="plan_action_add",
        )
        self.session.add(workout)
        await self.session.flush()
        if custom_bike is not None:
            warnings = await self._append_red_vo2_warning(player, workout, warnings)
        if category == DAY_CATEGORY_CYCLE and is_indoor_bike_workout(workout.structured_workout):
            await self.executable.reconcile_deliveries(
                player, start_date=workout_date, end_date=workout_date
            )
        await self.session.commit()
        await self.session.refresh(workout)
        return WorkoutActionResult(workout=workout, warnings=warnings)

    async def edit_structured_workout(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        custom_bike: FreeformBikeWorkoutSpec,
    ) -> WorkoutActionResult:
        current = await self.executable.rail._planned_workout(player.id, planned_workout_id)
        if current.status == WORKOUT_STATUS_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="This session is already done, so its structure can't be edited.",
            )
        # Mark's explicit manual authoring path: gates warn, they don't block.
        template, warnings = build_freeform_bike_workout(
            custom_bike, title=current.title, soft_gates=True
        )
        live = await self.executable.rail.latest_delivered_for_workout(player.id, current.id)
        if live is None:
            live = await self.executable.rail.latest_delivered_for_date(
                player.id, current.workout_date
            )
        current.is_active = False
        await self.session.flush()
        version = await self._next_version(player.id, current.workout_date)
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=current.plan_block_id,
            workout_date=current.workout_date,
            version=version,
            title=template.title,
            workout_type=template.workout_type,
            status="planned",
            is_active=True,
            planned_duration_min=template.planned_duration_min,
            intensity_target=template.intensity_target,
            structured_workout=template.structured_workout,
            source=current.source or "structured_edit",
        )
        self.session.add(workout)
        await self.session.flush()
        warnings = await self._append_red_vo2_warning(player, workout, warnings)
        if is_indoor_bike_workout(workout.structured_workout):
            await self.executable.reconcile_deliveries(
                player, start_date=workout.workout_date, end_date=workout.workout_date
            )
        elif live is not None:
            await self.executable.rail.delete_event(proposal=live, commit=False)
        await self.session.commit()
        await self.session.refresh(workout)
        return WorkoutActionResult(workout=workout, warnings=warnings)

    async def _append_red_vo2_warning(
        self,
        player: Profile,
        workout: PlannedWorkout,
        warnings: list[WorkoutWarning],
    ) -> list[WorkoutWarning]:
        """Add the Red-never-VO2 advisory when Mark authored VO2 for a Red day.

        The scoped reversal (Decision #161): the delivery gates (``send_today`` /
        ``approve_adjustment``) keep Red-never-VO2 **hard** for coach adjustments,
        but a session Mark explicitly built for himself is delivered with a warning
        rather than blocked. ``blocks_red_vo2`` reuses the exact gate predicate, so
        the threshold never drifts. No stored Red verdict for the date → no warning.
        """
        try:
            ir = build_structured_workout_ir(workout)
        except HTTPException:
            return warnings  # non-bike / non-deliverable — nothing to warn about
        verdict = await self.executable._morning_verdict_for(player.id, workout.workout_date)
        if blocks_red_vo2(verdict, ir):
            return [
                *warnings,
                WorkoutWarning(
                    code="red_vo2",
                    detail=(
                        "This is a VO2 session on a Red-readiness day — sending it "
                        "because you built it, but recovery would be the safer call."
                    ),
                ),
            ]
        return warnings

    async def swap_workout_into_date(
        self, player: Profile, *, planned_workout_id: uuid.UUID, target_date: date
    ) -> PlannedWorkout:
        return await self.executable.swap_day(
            player, planned_workout_id=planned_workout_id, target_date=target_date
        )

    async def skip_day(self, player: Profile, *, workout_date: date) -> list[PlannedWorkout]:
        workouts = await self._active_workouts_on(player.id, workout_date)
        skipped: list[PlannedWorkout] = []
        for workout in workouts:
            skipped.append(
                await self.executable.skip_workout(player, planned_workout_id=workout.id)
            )
        return skipped

    async def mark_reset_week(self, player: Profile, *, week_date: date) -> list[PlannedWorkout]:
        block = await self._block_for_date(player.id, week_date)
        if block is None:
            raise HTTPException(status_code=404, detail="No plan week found for that date.")
        if _block_has_active_reset(block):
            return await self._active_workouts_in_range(player.id, block.start_date, block.end_date)

        workouts = await self._active_workouts_in_range(player.id, block.start_date, block.end_date)
        reset_workouts: list[PlannedWorkout] = []
        originals: list[dict[str, Any]] = []
        changed_dates: set[date] = set()
        for workout in workouts:
            if not _is_mutable_bike_workout(workout):
                continue
            workout.is_active = False
            await self.session.flush()
            version = await self._next_version(player.id, workout.workout_date)
            reset_workout = PlannedWorkout(
                user_id=player.id,
                plan_block_id=workout.plan_block_id,
                workout_date=workout.workout_date,
                version=version,
                title=_reset_title(workout.title),
                workout_type="bike_endurance",
                status="planned",
                is_active=True,
                planned_duration_min=workout.planned_duration_min,
                intensity_target=f"Z2 reset ~{RESET_WEEK_POWER_PCT}% FTP",
                structured_workout=_reset_structured_workout(
                    workout,
                    week_start=block.start_date,
                    week_end=block.end_date,
                ),
                source=RESET_WEEK_SOURCE,
            )
            self.session.add(reset_workout)
            await self.session.flush()
            reset_workouts.append(reset_workout)
            changed_dates.add(reset_workout.workout_date)
            originals.append(
                {
                    "originalWorkoutId": str(workout.id),
                    "originalVersion": workout.version,
                    "resetWorkoutId": str(reset_workout.id),
                    "resetVersion": reset_workout.version,
                    "date": workout.workout_date.isoformat(),
                }
            )

        _set_block_reset(
            block,
            active=True,
            week_start=block.start_date,
            week_end=block.end_date,
            originals=originals,
        )
        for changed_date in sorted(changed_dates):
            await self.executable.reconcile_deliveries(
                player, start_date=changed_date, end_date=changed_date
            )
        await self.session.commit()
        for workout in reset_workouts:
            await self.session.refresh(workout)
        return await self._active_workouts_in_range(player.id, block.start_date, block.end_date)

    async def unset_reset_week(self, player: Profile, *, week_date: date) -> list[PlannedWorkout]:
        block = await self._block_for_date(player.id, week_date)
        if block is None:
            raise HTTPException(status_code=404, detail="No plan week found for that date.")
        if not _block_has_active_reset(block):
            return await self._active_workouts_in_range(player.id, block.start_date, block.end_date)

        reset_info = _reset_info(block)
        original_ids = {
            uuid.UUID(str(item["originalWorkoutId"]))
            for item in reset_info.get("originals", [])
            if isinstance(item, dict) and item.get("originalWorkoutId")
        }
        active_workouts = await self._active_workouts_in_range(
            player.id, block.start_date, block.end_date
        )
        changed_dates: set[date] = set()
        for workout in active_workouts:
            if workout.source == RESET_WEEK_SOURCE or _is_reset_structured_workout(workout):
                workout.is_active = False
                changed_dates.add(workout.workout_date)

        if original_ids:
            originals = (
                (
                    await self.session.execute(
                        select(PlannedWorkout).where(
                            PlannedWorkout.user_id == player.id,
                            PlannedWorkout.id.in_(original_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for workout in originals:
                workout.is_active = True
                changed_dates.add(workout.workout_date)

        _set_block_reset(
            block,
            active=False,
            week_start=block.start_date,
            week_end=block.end_date,
            originals=reset_info.get("originals", []),
        )
        await self.session.flush()
        for changed_date in sorted(changed_dates):
            await self.executable.reconcile_deliveries(
                player, start_date=changed_date, end_date=changed_date
            )
        await self.session.commit()
        return await self._active_workouts_in_range(player.id, block.start_date, block.end_date)

    async def record_actual(
        self,
        player: Profile,
        *,
        workout_date: date,
        label: str,
        notes: str | None,
    ) -> ManualEntry:
        entry = ManualEntry(
            user_id=player.id,
            entry_date=workout_date,
            entry_at_utc=_utcnow(),
            adherence_status="modified",
            actual_workout_json={"label": label, "source": "did_something_else"},
            notes=notes,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def _next_version(self, user_id: uuid.UUID, workout_date: date) -> int:
        current = await self.session.scalar(
            select(func.max(PlannedWorkout.version)).where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.workout_date == workout_date,
            )
        )
        return (current or 0) + 1

    async def _block_for_date(self, user_id: uuid.UUID, target_date: date) -> PlanBlock | None:
        return (
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == user_id,
                        PlanBlock.start_date <= target_date,
                        PlanBlock.end_date >= target_date,
                    )
                )
            )
            .scalars()
            .one_or_none()
        )

    async def _active_workouts_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[PlannedWorkout]:
        return list(
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                    )
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _active_workouts_on(
        self, user_id: uuid.UUID, workout_date: date
    ) -> list[PlannedWorkout]:
        workouts = list(
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                    )
                    .order_by(PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        logged_done_ids = await self._logged_done_workout_ids_on(user_id, workout_date)
        return [
            workout
            for workout in workouts
            if workout.status != WORKOUT_STATUS_COMPLETED and workout.id not in logged_done_ids
        ]

    async def _logged_done_workout_ids_on(
        self, user_id: uuid.UUID, workout_date: date
    ) -> set[uuid.UUID]:
        entries = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == workout_date,
                        ManualEntry.planned_workout_id.is_not(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc(), ManualEntry.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest_by_workout: dict[uuid.UUID, ManualEntry] = {}
        for entry in entries:
            if entry.planned_workout_id is None or entry.planned_workout_id in latest_by_workout:
                continue
            latest_by_workout[entry.planned_workout_id] = entry
        return {
            workout_id
            for workout_id, entry in latest_by_workout.items()
            if (entry.adherence_status or "").strip().lower() in DONE_ADHERENCE_STATUSES
        }
