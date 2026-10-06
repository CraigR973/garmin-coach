"""Predict 7-20 Oct mornings with the real engine over Mark's real history (read-only).

Loads his real rows (no writes, session rolled back), appends hypothetical nights per
scenario, and runs the real acute rails, grade() and todays_call() for each morning.
"""

import faulthandler

faulthandler.dump_traceback_later(240, exit=True)

import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

from src.database import AsyncSessionLocal  # noqa: E402
from src.models.coaching import (  # noqa: E402
    DailyMetric,
    ManualEntry,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile  # noqa: E402
from src.services.holiday_pause import HolidayPauseService  # noqa: E402
from src.services.morning_verdict import _hrv_rail, _rhr_corroborates, _rhr_rail  # noqa: E402
from src.services.todays_call import todays_call  # noqa: E402
from src.services.verdict_grading import (  # noqa: E402
    build_grading_inputs,
    grade,
    readiness_lower_quartile,
)

START, END = date(2026, 10, 7), date(2026, 10, 20)


async def load():
    async with AsyncSessionLocal() as s:
        p = await s.scalar(
            select(Profile).where(Profile.is_active.is_(True)).order_by(Profile.created_at).limit(1)
        )
        uid = p.id
        dm = (
            await s.execute(
                select(
                    DailyMetric.calendar_date,
                    DailyMetric.hrv_last_night_avg_ms,
                    DailyMetric.resting_heart_rate_bpm,
                ).where(DailyMetric.user_id == uid, DailyMetric.phase == "morning")
            )
        ).all()
        sl = (
            await s.execute(
                select(Sleep.calendar_date, Sleep.score, Sleep.age_adjusted_score, Sleep.duration_sec)
                .where(Sleep.user_id == uid)
            )
        ).all()
        fe = (
            await s.execute(
                select(ManualEntry.entry_date, ManualEntry.subjective_score)
                .where(
                    ManualEntry.user_id == uid,
                    ManualEntry.planned_workout_id.is_(None),
                    ManualEntry.activity_id.is_(None),
                    ManualEntry.subjective_score.is_not(None),
                )
                .order_by(ManualEntry.entry_date, ManualEntry.entry_at_utc)
            )
        ).all()
        bl = {
            b.metric_key: SimpleNamespace(
                metric_key=b.metric_key,
                sample_count=b.sample_count,
                median_value=b.median_value,
                upper_quartile_value=b.upper_quartile_value,
                lower_quartile_value=b.lower_quartile_value,
                window_start_date=b.window_start_date,
                window_end_date=b.window_end_date,
            )
            for b in (
                await s.execute(select(MetricBaseline).where(MetricBaseline.user_id == uid))
            ).scalars()
        }
        blocks = [
            SimpleNamespace(start_date=b.start_date, end_date=b.end_date, block_type=b.block_type)
            for b in (
                await s.execute(select(PlanBlock).where(PlanBlock.user_id == uid))
            ).scalars()
        ]
        pws = (
            await s.execute(
                select(PlannedWorkout).where(
                    PlannedWorkout.user_id == uid,
                    PlannedWorkout.is_active.is_(True),
                    PlannedWorkout.workout_date >= START,
                    PlannedWorkout.workout_date <= END,
                )
            )
        ).scalars().all()
        workouts = {}
        for w in pws:
            workouts.setdefault(w.workout_date, []).append(
                SimpleNamespace(
                    id=w.id,
                    title=w.title,
                    workout_type=w.workout_type,
                    status=w.status,
                    planned_duration_min=w.planned_duration_min,
                    intensity_target=w.intensity_target,
                    structured_workout=w.structured_workout,
                    workout_date=w.workout_date,
                    version=w.version,
                )
            )
        windows = await HolidayPauseService(s).get_windows(p)
        await s.rollback()
    return dm, sl, fe, bl, blocks, workouts, windows


def acwr_model(day):
    # Rough Garmin-like projection from the planned loads (see report); a parameter.
    return {
        7: 0.03, 8: 0.2, 9: 0.5, 10: 0.55, 11: 0.7, 12: 0.85, 13: 0.9,
        14: 1.05, 15: 1.0, 16: 0.8, 17: 0.85, 18: 0.85, 19: 0.7, 20: 0.75,
    }[day.day]


SCEN = {
    # name: per-day dict(hrv, rhr, raw, adj, hours, feel, readiness)
    "A_back_to_normal": lambda i, d: dict(hrv=47, rhr=44, raw=79, adj=83, hours=7.6, feel=7, rdy=70),
    "B_gradual": lambda i, d: dict(
        hrv=[41, 43, 45, 47][min(i, 3)], rhr=44, raw=79, adj=83, hours=7.6, feel=7,
        rdy=[56, 60, 65, 70][min(i, 3)],
    ),
    "C_slow_low_week": lambda i, d: dict(
        hrv=40 if i < 7 else [44, 46, 47][min(i - 7, 2)], rhr=45, raw=74, adj=78, hours=7.4,
        feel=6, rdy=55 if i < 7 else 68,
    ),
    "D_back_but_poor_night_8_Oct": lambda i, d: dict(
        hrv=47, rhr=44, raw=58 if d.day == 8 else 79, adj=62 if d.day == 8 else 83,
        hours=6.2 if d.day == 8 else 7.6, feel=6 if d.day == 8 else 7, rdy=45 if d.day == 8 else 70,
    ),
    "E_fair_night_low_readiness_7_Oct": lambda i, d: dict(
        hrv=[44, 47][min(i, 1)], rhr=44, raw=70 if d.day == 7 else 79, adj=72 if d.day == 7 else 83,
        hours=7.3, feel=7, rdy=50 if d.day == 7 else 68,
    ),
}


def run(data, name, fn, acwr_override=None):
    dm, sl, fe, bl, blocks, workouts, windows = data
    hrv = {r[0]: float(r[1]) for r in dm if r[1] is not None}
    rhr = {r[0]: r[2] for r in dm if r[2] is not None}
    sleep_raw = {r[0]: r[1] for r in sl}
    sleep_adj = {r[0]: r[2] for r in sl}
    sleep_min = {r[0]: r[3] / 60 for r in sl if r[3]}
    feel = {}
    for d, f in fe:
        feel[d] = int(f)
    rows = []
    for i in range((END - START).days + 1):
        d = START + timedelta(days=i)
        v = fn(i, d)
        hrv[d] = float(v["hrv"])
        rhr[d] = v["rhr"]
        sleep_raw[d], sleep_adj[d], sleep_min[d] = v["raw"], v["adj"], v["hours"] * 60
        recent = [
            SimpleNamespace(calendar_date=k, hrv_last_night_avg_ms=val, resting_heart_rate_bpm=rhr.get(k))
            for k, val in sorted(hrv.items())
            if d - timedelta(days=84) <= k < d
        ]
        today = SimpleNamespace(calendar_date=d, hrv_last_night_avg_ms=v["hrv"], resting_heart_rate_bpm=v["rhr"])
        rhr_r = _rhr_rail(today, bl.get("resting_heart_rate_bpm"), recent)
        corr = ["resting_heart_rate"] if _rhr_corroborates(rhr_r) or rhr_r.get("requiresBikeRest") else []
        hrv_r = _hrv_rail(today, recent, corroborated_by=corr)
        acute = {
            "overnightHrv": hrv_r,
            "restingHeartRate": rhr_r,
            "requiresBikeRest": bool(hrv_r["requiresBikeRest"] or rhr_r["requiresBikeRest"]),
            "requiresTrainingRest": False,
            "symptoms": {},
            "dataSufficiency": {"status": "sufficient"},
        }
        day_workouts = workouts.get(d, [])
        in_plan_week = any(b.start_date <= d <= b.end_date for b in blocks)
        live = [w for w in day_workouts if w.status not in ("completed", "skipped")]
        rest_day = in_plan_week and not live
        acwr = acwr_override(d) if acwr_override else acwr_model(d)
        inputs = build_grading_inputs(
            subject_date=d,
            acute=acute,
            last_night_hrv_ms=v["hrv"],
            hrv_history={k: val for k, val in hrv.items() if k < d},
            sleep_score_raw=v["raw"],
            sleep_score_age_adjusted=v["adj"],
            sleep_minutes=v["hours"] * 60,
            sleep_minutes_history={k: val for k, val in sleep_min.items() if k < d},
            acwr=acwr,
            recovery_time_min=0,
            yesterday_load=None,
            feel=v["feel"],
            feel_history={k: val for k, val in feel.items() if k < d},
            readiness_level="MODERATE",
            readiness_score=v["rdy"],
            readiness_lower_quartile=readiness_lower_quartile(bl.get("readiness_score")),
            planned_workouts=day_workouts,
            rest_day=rest_day,
            blocks=blocks,
            holiday_windows=windows,
        )
        gv = grade(inputs)
        feel[d] = v["feel"]
        packet = {
            "verdict": {
                "status": gv.status,
                "engine": "graded",
                "held": gv.held,
                "graded": gv.to_packet(),
                "acutePhysiology": acute,
            },
            "plannedWorkouts": [
                {"id": str(w.id), "workoutType": w.workout_type, "status": w.status} for w in day_workouts
            ],
            "restDay": {
                "isRestDay": rest_day,
                "reason": "planned_rest" if rest_day else None,
                "insidePlanWeek": in_plan_week,
            },
        }
        call = todays_call(packet)
        auto = gv.domain("autonomic")
        sig = max(auto.signals, key=lambda x: {"none": 0, "mild": 1, "marked": 2}[x.rating])
        rows.append(
            {
                "date": d.isoformat(),
                "hrv": v["hrv"],
                "colour": gv.label,
                "domains": {x.domain: x.rating for x in gv.domains},
                "auto_signal": sig.signal,
                "auto_reason": sig.reason,
                "acute_floor": hrv_r.get("acuteFloorMs"),
                "illness_line": hrv_r.get("illnessLineMs"),
                "actions": [(a.title, a.action) for a in gv.actions],
                "call": f"{call.headline} · {call.reading_words}",
                "summary": gv.summary,
            }
        )
    return rows


async def main():
    data = await load()
    out = {}
    for name, fn in SCEN.items():
        out[name] = run(data, name, fn)
    # Sensitivity: the load ratio at 1.35 on 12-15 Oct (Garmin's model is proprietary).
    out["A_with_acwr_1.35_12_15"] = run(
        data, "A", SCEN["A_back_to_normal"],
        acwr_override=lambda d: 1.35 if 12 <= d.day <= 15 else acwr_model(d),
    )
    out["C_with_acwr_1.55_12_15"] = run(
        data, "C", SCEN["C_slow_low_week"],
        acwr_override=lambda d: 1.55 if 12 <= d.day <= 15 else acwr_model(d),
    )
    json.dump(out, open(sys.argv[1], "w"), indent=1, default=str)
    for name, rows in out.items():
        print(f"\n== {name}")
        for r in rows:
            acts = ", ".join(f"{t}:{a}" for t, a in r["actions"]) or "-"
            print(
                f"{r['date'][5:]} hrv {r['hrv']:>4} | {r['colour']:<13} | {r['call']:<45} | "
                f"auto {r['domains']['autonomic']:<6} {r['auto_signal']:<22} | {acts}"
            )


asyncio.run(main())
