from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.vo2_progression import build_vo2_structured_workout, select_vo2_protocol


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _current_cycle_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _profile_content() -> dict[str, Any]:
    return {
        "athleteName": "Mark",
        "age": 57,
        "sex": "male",
        "ftpWatts": 280,
        "vo2max": 54,
        "hrvBandMs": {"low": 43, "high": 57},
        "restingHeartRateBpm": 45,
        "bloodPressure": {"systolic": 108, "diastolic": 68},
        "fitnessAge": 48,
    }


def _data_quality_rules_content() -> dict[str, Any]:
    return {
        "rules": [
            {
                "id": "no_lr_balance",
                "summary": "Ignore left/right power balance.",
                "reason": "Single-sided meter doubles one leg and makes balance unusable.",
            },
            {
                "id": "spo2_hrv_reliable_since",
                "summary": "Treat SpO2 and HRV as reliable only from 2026-06-11 onward.",
                "reason": "Strap-tightening on 11 Jun fixed the noisy overnight readings.",
            },
            {
                "id": "exclude_wrist_hr_strength",
                "summary": "Exclude wrist-HR strength sessions from recovery decisions.",
                "reason": "Strength HR from the wrist is too noisy for recovery interpretation.",
            },
            {
                "id": "ignore_excel_duration",
                "summary": "Ignore the constant Duration column in the historical spreadsheet.",
                "reason": "The export column is known-bad and should never drive analysis.",
            },
        ]
    }


def _age_adjustment_content() -> dict[str, Any]:
    return {
        "sleepScoreDelta": 4,
        "targetRemMinutes": {"low": 65, "high": 90},
        "notes": [
            "Garmin sleep scoring is calibrated around younger athletes.",
            "Use the adjusted sleep score in the morning verdict.",
        ],
    }


def _sleep_protocol_content() -> dict[str, Any]:
    return {
        "preCoolTemperatureC": 17,
        "sealTargetTime": "22:00",
        "thermalDisruptionThresholdC": {"low": 19.5, "high": 20.0},
        "coherenceBreathingTime": "20:00",
        "bedtime": "23:15",
        "latestSnackTime": "21:30",
    }


def _active_hypotheses_content() -> dict[str, Any]:
    return {
        "hypotheses": [
            {
                "title": "Collagen reintroduction",
                "status": "hold",
                "rule": "Do not reintroduce before 7 consecutive nights at 74+ adjusted sleep.",
            },
            {
                "title": "Recovery-week sleep disruption",
                "status": "active",
                "rule": (
                    "Watch for recovery-week pattern changes instead of assuming "
                    "relief weeks always help sleep."
                ),
            },
            {
                "title": "04:00 waking",
                "status": "active",
                "rule": "Track thermal and routine drivers behind the 04:00 wake-up pattern.",
            },
        ]
    }


def _coaching_protocol_content() -> dict[str, Any]:
    return {
        "lowReadinessResponse": {
            "preference": "swap_first",
            "rule": (
                "When readiness is low and a hard session (VO2/Sweet-Spot) is "
                "scheduled, rearrange the week first — move the hard session to a "
                "better day and pull an easier session (Z2/recovery) forward — "
                "rather than softening the prescription. Soften the ride only when "
                "the week can't be rearranged."
            ),
            "source": (
                "Mark's 2026-07-07 feedback: he swapped sessions across the week "
                "when readiness was low and it 'worked perfectly'; he prefers "
                "rearranging over softening any session."
            ),
        },
    }


def _training_plan_content(cycle_start: date) -> dict[str, Any]:
    return {
        "framework": "13-week 2121",
        "cycleStartDate": cycle_start.isoformat(),
        "cycleStructure": [
            "Weeks 1-2 build",
            "Week 3 recovery",
            "Weeks 4-5 build",
            "Week 6 recovery",
            "Weeks 7-8 build",
            "Week 9 recovery",
            "Weeks 10-11 build",
            "Week 12 taper",
            "Week 13 consolidation",
        ],
        "weeklyRhythm": [
            "Monday recovery or mobility strength",
            "Tuesday VO2 focus",
            "Thursday sweet spot or threshold support",
            "Saturday long endurance ride",
            "Sunday light strength or mobility",
        ],
        "vo2Progression": {
            "earlyBlock": "30/30 or 40/20 work",
            "lateBuild": "Ronnestad 30/15 from around Week 7 onward",
            "ergMode": "off",
        },
        "constraints": [
            "Never stack VO2 and sweet spot back-to-back when fatigue is high.",
            "Amber days cut duration 20-30 percent and remove HIT.",
            "Red days substitute recovery or rest and never keep VO2.",
        ],
        "delivery": {
            "rail": "intervals.icu to Zwift",
            "approvalRequired": True,
            "fallback": ".ZWO export",
        },
    }


def _training_schedule_content() -> dict[str, Any]:
    return {
        "restDays": ["Monday", "Friday"],
        "regularTrainingDays": {
            "Tuesday": "VO2 or higher-intensity bike focus",
            "Wednesday": "Endurance or supporting bike session",
            "Thursday": "Sweet spot, threshold, or supporting bike session",
            "Saturday": "Long endurance ride",
            "Sunday": "Light strength, mobility, or endurance support",
        },
        "longRideDay": "Saturday",
        "notes": [
            (
                "Respect Monday and Friday as Mark's normal recovery/rest days "
                "before suggesting an extra recovery day."
            ),
            (
                "If the imported plan contains an exception, describe it as an "
                "exception instead of rewriting the routine."
            ),
        ],
    }


KB_SECTION_BUILDERS: dict[str, Any] = {
    "profile": _profile_content,
    "data_quality_rules": _data_quality_rules_content,
    "age_adjustment": _age_adjustment_content,
    "sleep_protocol": _sleep_protocol_content,
    "training_plan": _training_plan_content,
    "training_schedule": _training_schedule_content,
    "active_hypotheses": _active_hypotheses_content,
    "coaching_protocol": _coaching_protocol_content,
}


@dataclass(frozen=True)
class WorkoutTemplate:
    day_offset: int
    title: str
    workout_type: str
    planned_duration_min: int
    intensity_target: str
    structured_workout: dict[str, Any]


def _build_templates(week_number: int) -> list[WorkoutTemplate]:
    # The VO2 progression (incl. Rønnestad 30/15 from ~Week 7) is owned by the
    # shared toolkit so the seed and the dynamic restructurer agree (Batch 14.3).
    vo2_protocol = select_vo2_protocol(week_number, block_type="build")
    vo2_label = vo2_protocol.title
    vo2_structured = build_vo2_structured_workout(week_number, block_type="build")

    return [
        WorkoutTemplate(
            day_offset=0,
            title="Recovery Strength + Mobility",
            workout_type="strength_recovery",
            planned_duration_min=35,
            intensity_target="Easy mobility and light strength",
            structured_workout={
                "format": "strength",
                "steps": [
                    {"label": "Mobility prep", "minutes": 10},
                    {
                        "label": "Strength circuit",
                        "minutes": 20,
                        "notes": "Keep it crisp, not draining.",
                    },
                    {"label": "Breathing reset", "minutes": 5},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=1,
            title=vo2_label,
            workout_type="bike_vo2",
            planned_duration_min=60,
            intensity_target=vo2_protocol.intensity_target,
            structured_workout=vo2_structured,
        ),
        WorkoutTemplate(
            day_offset=3,
            title="Sweet Spot Builder",
            workout_type="bike_sweet_spot",
            planned_duration_min=75,
            intensity_target="88-94% FTP",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
                    {
                        "label": "Main set",
                        "repeats": 3,
                        "pattern": "8 min on / 4 min easy",
                        "target": "88-94% FTP",
                    },
                    {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=5,
            title="Long Endurance Ride",
            workout_type="bike_endurance",
            planned_duration_min=150,
            intensity_target="Zone 2 steady ride",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Settle in", "minutes": 20, "target": "upper Zone 1"},
                    {"label": "Main ride", "minutes": 110, "target": "Zone 2"},
                    {"label": "Cool-down", "minutes": 20, "target": "easy spin"},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=6,
            title="Strength Maintenance",
            workout_type="strength_maintenance",
            planned_duration_min=40,
            intensity_target="Moderate full-body strength",
            structured_workout={
                "format": "strength",
                "steps": [
                    {"label": "Warm-up", "minutes": 10},
                    {"label": "Primary lifts", "minutes": 20},
                    {"label": "Mobility finish", "minutes": 10},
                ],
            },
        ),
    ]


def _recovery_templates() -> list[WorkoutTemplate]:
    return [
        WorkoutTemplate(
            day_offset=1,
            title="Recovery Openers",
            workout_type="bike_recovery",
            planned_duration_min=45,
            intensity_target="Easy spin with a few leg-openers",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Easy spin", "minutes": 35, "target": "Zone 1-2"},
                    {"label": "Openers", "repeats": 4, "pattern": "20s spin-up / 2 min easy"},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=3,
            title="Tempo Reset",
            workout_type="bike_tempo",
            planned_duration_min=60,
            intensity_target="Comfortable tempo",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 15},
                    {
                        "label": "Main set",
                        "repeats": 2,
                        "pattern": "10 min tempo / 5 min easy",
                        "target": "76-84% FTP",
                    },
                    {"label": "Cool-down", "minutes": 10},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=5,
            title="Short Endurance Ride",
            workout_type="bike_endurance",
            planned_duration_min=90,
            intensity_target="Low Zone 2",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Main ride", "minutes": 90, "target": "Low Zone 2"},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=6,
            title="Mobility Reset",
            workout_type="mobility",
            planned_duration_min=30,
            intensity_target="Easy mobility only",
            structured_workout={
                "format": "mobility",
                "steps": [{"label": "Mobility flow", "minutes": 30}],
            },
        ),
    ]


def _taper_templates() -> list[WorkoutTemplate]:
    return [
        WorkoutTemplate(
            day_offset=1,
            title="VO2 Sharpeners",
            workout_type="bike_vo2",
            planned_duration_min=45,
            intensity_target="Short, sharp but low volume",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 15},
                    {
                        "label": "Main set",
                        "repeats": 6,
                        "pattern": "1 min on / 2 min easy",
                        "target": "110% FTP",
                    },
                    {"label": "Cool-down", "minutes": 10},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=3,
            title="Endurance with Bursts",
            workout_type="bike_endurance",
            planned_duration_min=50,
            intensity_target="Endurance with neuromuscular bursts",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Main ride", "minutes": 50, "target": "Zone 2 with 5x 15s spin-ups"},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=5,
            title="Event Prep Spin",
            workout_type="bike_endurance",
            planned_duration_min=60,
            intensity_target="Keep it fresh",
            structured_workout={
                "format": "bike",
                "steps": [{"label": "Ride", "minutes": 60, "target": "Easy endurance"}],
            },
        ),
    ]


def _consolidation_templates() -> list[WorkoutTemplate]:
    return [
        WorkoutTemplate(
            day_offset=1,
            title="Threshold Touches",
            workout_type="bike_threshold",
            planned_duration_min=55,
            intensity_target="Controlled threshold",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 15},
                    {
                        "label": "Main set",
                        "repeats": 2,
                        "pattern": "8 min on / 4 min easy",
                        "target": "95-100% FTP",
                    },
                    {"label": "Cool-down", "minutes": 8},
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=3,
            title="Sweet Spot Maintenance",
            workout_type="bike_sweet_spot",
            planned_duration_min=60,
            intensity_target="88-92% FTP",
            structured_workout={
                "format": "bike",
                "steps": [
                    {
                        "label": "Main set",
                        "repeats": 2,
                        "pattern": "12 min on / 5 min easy",
                        "target": "88-92% FTP",
                    }
                ],
            },
        ),
        WorkoutTemplate(
            day_offset=5,
            title="Consolidation Endurance",
            workout_type="bike_endurance",
            planned_duration_min=120,
            intensity_target="Steady Zone 2",
            structured_workout={
                "format": "bike",
                "steps": [{"label": "Main ride", "minutes": 120, "target": "Zone 2"}],
            },
        ),
    ]


def _block_templates(block_type: str, week_number: int) -> list[WorkoutTemplate]:
    if block_type == "recovery":
        return _recovery_templates()
    if block_type == "taper":
        return _taper_templates()
    if block_type == "consolidation":
        return _consolidation_templates()
    return _build_templates(week_number)


def _block_name(week_number: int, block_type: str) -> str:
    label_map = {
        "build": "Build",
        "recovery": "Recovery",
        "taper": "Taper",
        "consolidation": "Consolidation",
    }
    return f"Week {week_number:02d} {label_map[block_type]}"


BLOCK_SEQUENCE = [
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "taper",
    "consolidation",
]


@dataclass
class CoachingStateSnapshot:
    knowledge_base_sections: list[KnowledgeBase]
    plan_blocks: list[PlanBlock]
    planned_workouts: list[PlannedWorkout]
    seeded: bool


class CoachingStateService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_seeded(self, player: Profile, *, commit: bool = True) -> bool:
        seeded = False
        cycle_start = _current_cycle_start(date.today())

        existing_sections = set(
            (
                await self.session.execute(
                    select(KnowledgeBase.section).where(KnowledgeBase.user_id == player.id)
                )
            )
            .scalars()
            .all()
        )
        missing_sections = [
            section for section in KB_SECTION_BUILDERS if section not in existing_sections
        ]
        for section in missing_sections:
            builder = KB_SECTION_BUILDERS[section]
            content = builder(cycle_start) if section == "training_plan" else builder()
            self.session.add(
                KnowledgeBase(
                    user_id=player.id,
                    section=section,
                    version=1,
                    is_active=True,
                    source="batch_5_seed" if not existing_sections else "batch_56_seed",
                    content=content,
                    updated_by_profile_id=player.id,
                )
            )
            seeded = True

        existing_blocks = (
            (await self.session.execute(select(PlanBlock.id).where(PlanBlock.user_id == player.id)))
            .scalars()
            .all()
        )
        if not existing_blocks:
            seeded = True
            await self._seed_training_plan(player.id, cycle_start)

        if seeded and commit:
            await self.session.commit()

        return seeded

    async def _seed_training_plan(self, player_id: uuid.UUID, cycle_start: date) -> None:
        for index, block_type in enumerate(BLOCK_SEQUENCE, start=1):
            start_date = cycle_start + timedelta(days=(index - 1) * 7)
            end_date = start_date + timedelta(days=6)
            plan_block = PlanBlock(
                user_id=player_id,
                name=_block_name(index, block_type),
                version=1,
                sequence_index=index,
                block_type=block_type,
                start_date=start_date,
                end_date=end_date,
                goals_json={
                    "focus": {
                        "build": "Progress aerobic capacity and quality bike work.",
                        "recovery": "Absorb load and protect sleep quality.",
                        "taper": "Sharpen without carrying fatigue.",
                        "consolidation": "Stabilize gains and set up the next cycle.",
                    }[block_type],
                    "weekNumber": index,
                },
                raw_plan={"cycle": "2121", "weekNumber": index, "blockType": block_type},
            )
            self.session.add(plan_block)
            await self.session.flush()

            for template in _block_templates(block_type, index):
                workout_date = start_date + timedelta(days=template.day_offset)
                self.session.add(
                    PlannedWorkout(
                        user_id=player_id,
                        plan_block_id=plan_block.id,
                        workout_date=workout_date,
                        version=1,
                        title=template.title,
                        workout_type=template.workout_type,
                        status="planned",
                        is_active=True,
                        planned_duration_min=template.planned_duration_min,
                        intensity_target=template.intensity_target,
                        structured_workout=template.structured_workout,
                        source="batch_5_seed",
                    )
                )

    async def get_snapshot(self, player: Profile) -> CoachingStateSnapshot:
        seeded = await self.ensure_seeded(player)
        knowledge_base_sections = (
            (
                await self.session.execute(
                    select(KnowledgeBase)
                    .where(KnowledgeBase.user_id == player.id)
                    .order_by(KnowledgeBase.section.asc(), KnowledgeBase.version.desc())
                )
            )
            .scalars()
            .all()
        )
        plan_blocks = (
            (
                await self.session.execute(
                    select(PlanBlock)
                    .where(PlanBlock.user_id == player.id)
                    .order_by(PlanBlock.start_date.asc(), PlanBlock.version.desc())
                )
            )
            .scalars()
            .all()
        )
        planned_workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == player.id)
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )

        return CoachingStateSnapshot(
            knowledge_base_sections=list(knowledge_base_sections),
            plan_blocks=list(plan_blocks),
            planned_workouts=list(planned_workouts),
            seeded=seeded,
        )

    async def update_knowledge_base_section(
        self,
        *,
        player: Profile,
        section: str,
        content: dict[str, Any],
        source: str | None,
    ) -> KnowledgeBase:
        if section not in KB_SECTION_BUILDERS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Unknown knowledge-base section",
            )

        await self.ensure_seeded(player, commit=False)

        current_version = await self.session.scalar(
            select(func.max(KnowledgeBase.version)).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == section,
            )
        )
        next_version = (current_version or 0) + 1

        await self.session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.user_id == player.id, KnowledgeBase.section == section)
            .values(is_active=False)
        )

        record = KnowledgeBase(
            user_id=player.id,
            section=section,
            version=next_version,
            is_active=True,
            source=source or "manual_edit",
            content=content,
            updated_by_profile_id=player.id,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def override_planned_workout(
        self,
        *,
        player: Profile,
        workout_date: date,
        title: str,
        workout_type: str,
        status_value: str,
        planned_duration_min: int | None,
        intensity_target: str | None,
        structured_workout: dict[str, Any],
        source: str | None,
        plan_block_id: uuid.UUID | None,
    ) -> PlannedWorkout:
        await self.ensure_seeded(player, commit=False)

        if plan_block_id is not None:
            plan_block = await self.session.scalar(
                select(PlanBlock).where(
                    PlanBlock.id == plan_block_id,
                    PlanBlock.user_id == player.id,
                )
            )
            if plan_block is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Plan block not found for player",
                )

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
            plan_block_id=plan_block_id,
            workout_date=workout_date,
            version=next_version,
            title=title,
            workout_type=workout_type,
            status=status_value,
            is_active=True,
            planned_duration_min=planned_duration_min,
            intensity_target=intensity_target,
            structured_workout=structured_workout,
            source=source or "manual_override",
        )
        self.session.add(workout)
        await self.session.commit()
        await self.session.refresh(workout)
        return workout
