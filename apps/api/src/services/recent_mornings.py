"""What each recent morning read did to its day's sessions, for the coach (Batch 289).

Asked from Home at 11:34 BST on 24 Sep 2026, the coach told Mark there was "no
live cutting pattern" this week and that today's sweet spot was "still standing
as prescribed, unmodified". The morning read had cut it from 94 minutes to 47
with the hardest interval at 60% FTP, and Mark had approved that at 09:00; the
day before, 75 minutes of Zone 2 had become 52. An unanchored question sees the
plan as imported and the week ahead, but the adjustment lives only in the stored
morning packet (``verdict.verdictAdjustment``), which such a question never
loads. The coach corrected itself only after Mark insisted — and then blamed
``cumulativeEscalation``, which had not fired on any day that week.

This module hands the coach, for today and the six days before it, each session
as the morning left it: the session as planned, what the morning did to it, the
cut's own figures, whether the cut ever reached his device, and the rules that
fired, in the app's words.

**A cut is only an offer until Mark approves it.** ``regenerate_for_verdict``
proposes an adjusted session; ``approve_adjustment`` uploads it and records a
``workout_pushed`` audit tagged ``approve:<workout>:v<n>``. On 19 Sep a Red
morning cut an easy ride from 90 minutes to 63 and he never approved it, so the
planned ride stayed on his device. Reporting the morning's figure alone would
tell him a cut he never took — the mirror image of the 24 Sep error.

**A morning that rules out riding carries no adjustment.** When an acute signal
sets ``requiresBikeRest`` the morning packet leaves ``verdictAdjustment`` empty
and advises no bike at all, so those sessions read ``no_bike_advised``, never
``unchanged``. When a reported symptom rules out training of any kind
(``requiresTrainingRest``, Batch 294), every session that day reads
``no_training_advised``, not only the rides.

**The symptom answer the call used** (Batch 355). Until chat v29 the coach saw a
symptom only as a floor's reason line here, and only on a question from the brief the
whole answer. :func:`todays_symptom_answer` gives it, on every question, the answer
today's latest stored morning used — his tap, a symptom his note named, or "Still
there" on Home, whichever is most serious — with what it set, in the app's words and
never its codes. Not the bare tap: "None" beside a chest floor set from his note would
give two accounts of one morning (Craig, 22 Oct 2026). A floor's reason reaches the
coach without its colour (:func:`~src.services.symptom_check.plain_floor_reason`).

Everything here is read from rows the app already wrote and is explanatory only:
it cannot move a verdict, a floor or a plan (Decision #29).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis
from src.services.bulk_history_reads import select_morning_calls
from src.services.symptom_check import (
    EASING_KINDS,
    FOLLOW_UP_ANSWER_LABELS,
    FOLLOW_UP_STILL_THERE,
    SYMPTOM_FLOORS,
    SYMPTOM_LABELS,
    SYMPTOMS_CHEST_HEART,
    plain_floor_reason,
)
from src.services.workout_categories import is_bike_workout_type

RECENT_MORNINGS_DAYS = 7

MORNING_CALL_UNCHANGED = "unchanged"
MORNING_CALL_ADJUSTED = "adjusted"
#: Batch 298: the session stood, ridden with its targets held.
MORNING_CALL_HELD = "held"
MORNING_CALL_NO_BIKE = "no_bike_advised"
MORNING_CALL_NO_TRAINING = "no_training_advised"

ON_DEVICE_APPROVED = "approved_and_uploaded"
ON_DEVICE_OFFERED_NOT_APPROVED = "offered_not_approved"
ON_DEVICE_NOT_OFFERED = "not_offered"

#: The two delivery audits that say whether a morning's cut reached his device.
AUDIT_PROPOSED = "workout_proposed"
AUDIT_PUSHED = "workout_pushed"
_REGEN_TAG_PREFIXES = ("amber-regen:", "red-regen:")
_APPROVE_TAG_PREFIX = "approve:"

RECENT_MORNINGS_MEANING = (
    "What each morning read of the last seven days decided about that day's sessions, "
    "from the stored reads, newest first. `planned` is a session as it stood in his plan "
    "that morning. `morningCall` is what the morning did to it: `unchanged`; `adjusted`, "
    "the app's own Amber/Red cut, with its figures in `adjusted` (`hardestIntervalPctFtp` "
    "is the hardest interval's %FTP, not the main set's); `no_bike_advised`, when an "
    "acute signal ruled out riding that day; or `no_training_advised`, when a symptom he "
    "reported ruled out training of any kind. A cut is only an offer until Mark approves it: "
    "`onHisDevice` says whether he approved it and the adjusted version was uploaded, "
    "whether it was offered and not approved (so the planned version stayed on his "
    "device), or whether no adjusted version was offered at all. `reasons` are the rules "
    "that fired that morning, in the app's words: quote them, and never name a rule that is "
    "not listed. `morningRead` false means no morning read was written that day, so "
    "nothing was adjusted. Check here before telling Mark a session was unchanged. "
    "`held` true on a day means the morning was Green with the targets held (one thing a "
    "little off): never call it plain Green. A session's `gradedAction` is what the graded "
    "verdict did to it; `morningCall` `held` means it stood with its targets held, a mild "
    "concern or a planned light week, never just `unchanged`."
)

#: The graded actions that keep a session as planned with its targets held.
_HELD_ACTIONS = frozenset({"hold_targets", "move_or_hold"})


@dataclass(frozen=True, slots=True)
class MorningCall:
    """One stored morning read, projected by :func:`select_morning_calls`."""

    subject_date: date
    generated_at_utc: datetime
    verdict: str | None
    reasons: Any
    verdict_adjustment: Any
    requires_bike_rest: Any
    rest_day: Any
    planned_workouts: Any
    # Batch 294: absent on reads stored before it, which never ruled out training.
    requires_training_rest: Any = None
    # Batch 298: absent on reads stored before the graded verdict set the colour.
    held: Any = None
    graded_actions: Any = None
    # Batch 355: absent on reads stored before Batch 294 asked the question.
    symptoms: Any = None
    graded_easing: Any = None


@dataclass(frozen=True, slots=True)
class DeliveryAudit:
    """A proposal or an approval the delivery rail recorded for a day."""

    subject_date: date
    analysis_type: str
    generated_at_utc: datetime
    tag: str | None


def build_recent_mornings(
    *,
    today: date,
    mornings: Sequence[MorningCall],
    audits: Sequence[DeliveryAudit],
) -> dict[str, Any]:
    """Today and the six days before it, newest first, as the mornings left them."""

    latest: dict[date, MorningCall] = {}
    for call in sorted(mornings, key=lambda row: row.generated_at_utc, reverse=True):
        latest.setdefault(call.subject_date, call)
    days: list[dict[str, Any]] = []
    for offset in range(RECENT_MORNINGS_DAYS):
        day = today - timedelta(days=offset)
        read = latest.get(day)
        if read is None:
            days.append({"date": day.isoformat(), "morningRead": False})
            continue
        day_audits = [audit for audit in audits if audit.subject_date == day]
        days.append(_day(read, day_audits))
    return {"days": days, "meaning": RECENT_MORNINGS_MEANING}


SYMPTOM_ANSWER_MEANING = (
    "The symptom answer this morning's call used, and what it set: his answer to the "
    'check-in\'s symptom question, a symptom his note named, or his "Still there" to '
    "Home's chest or heart question, whichever is most serious. `answer` null means he has "
    'not answered today, which never means he is well; "None" is preselected on the '
    "form. `whatItMeans` and `planLine` are the app's own words for what it set or what "
    "follows an earlier symptom; `easedTodaysHardSession` says whether that changed a "
    "session today. `notice` is the notice he reads on Home. `chestFollowUp` is the chest or "
    "heart question Home asks each morning after a report, until he answers that the "
    "symptoms have gone and he has spoken to his GP or 111. `morningOf` null means no "
    "morning call has been made today yet."
)


def todays_symptom_answer(*, today: date, mornings: Sequence[MorningCall]) -> dict[str, Any]:
    """The symptom answer today's latest stored morning used, in the app's words.

    Labels and the app's own sentences only, never a stored code (``chest_heart``,
    ``no_training_see_doctor``): the coach must not repeat a code, and its answer guard
    rejects one. A morning stored before Batch 294 carries no symptom record and reads
    as unanswered.
    """

    todays = [call for call in mornings if call.subject_date == today]
    if not todays:
        return {"morningOf": None, "meaning": SYMPTOM_ANSWER_MEANING}
    call = max(todays, key=lambda row: row.generated_at_utc)
    symptoms = call.symptoms if isinstance(call.symptoms, Mapping) else {}
    answer = _str(symptoms.get("answer"))
    floor = SYMPTOM_FLOORS.get(answer) if answer is not None else None
    follow_up = symptoms.get("chestFollowUp")
    follow_up = follow_up if isinstance(follow_up, Mapping) else None
    record: dict[str, Any] = {
        "morningOf": call.subject_date.isoformat(),
        "answer": SYMPTOM_LABELS.get(answer) if answer is not None else None,
        "answeredWith": _answered_with(answer, symptoms, follow_up),
    }
    if answer is not None and symptoms.get("source") == "notes":
        record["hisWords"] = _str(symptoms.get("words"))
    if floor is not None and symptoms.get("triggered") is True:
        record["whatItMeans"] = plain_floor_reason(floor.reason)
        record["planLine"] = floor.plan_line
        record["notice"] = floor.notice
    else:
        easing = symptoms.get("easing")
        if isinstance(easing, Mapping) and easing.get("kind") in EASING_KINDS:
            record["whatItMeans"] = _str(easing.get("reason"))
            record["planLine"] = _str(easing.get("planLine"))
            record["notice"] = _str(easing.get("notice"))
            record["easedTodaysHardSession"] = _str(call.graded_easing) == easing.get("kind")
    if follow_up is not None:
        reported_on = _str(follow_up.get("reportedOn"))
        his_answer = _str(follow_up.get("answer"))
        record["chestFollowUp"] = {
            "reportedOn": reported_on,
            "hisAnswerToday": FOLLOW_UP_ANSWER_LABELS.get(his_answer) if his_answer else None,
            "stillOpen": follow_up.get("open") is True,
        }
    record["meaning"] = SYMPTOM_ANSWER_MEANING
    return record


def _answered_with(
    answer: str | None, symptoms: Mapping[str, Any], follow_up: Mapping[str, Any] | None
) -> str | None:
    if answer is None:
        return None
    if symptoms.get("source") == "notes":
        return "his check-in note"
    if (
        answer == SYMPTOMS_CHEST_HEART
        and follow_up is not None
        and follow_up.get("answer") == FOLLOW_UP_STILL_THERE
    ):
        return "his answer to Home's chest or heart question"
    return "his answer to the check-in's symptom question"


def _day(call: MorningCall, audits: Sequence[DeliveryAudit]) -> dict[str, Any]:
    rest_day = call.rest_day if isinstance(call.rest_day, Mapping) else {}
    no_bike = call.requires_bike_rest is True
    no_training = call.requires_training_rest is True
    entry: dict[str, Any] = {
        "date": call.subject_date.isoformat(),
        "morningRead": True,
        "verdict": call.verdict,
        "reasons": [
            plain_floor_reason(reason) for reason in _list(call.reasons) if isinstance(reason, str)
        ],
    }
    if no_bike:
        entry["noBikeAdvised"] = True
    if no_training:
        entry["noTrainingAdvised"] = True
    if call.held is True:
        entry["held"] = True
    if rest_day.get("isRestDay") is True:
        entry["restDay"] = True
        if isinstance(rest_day.get("reason"), str):
            entry["restDayReason"] = rest_day["reason"]
    if rest_day.get("insideHolidayWindow") is True:
        entry["onHoliday"] = True
    adjustment = call.verdict_adjustment if isinstance(call.verdict_adjustment, Mapping) else None
    graded_actions = {
        str(item["plannedWorkoutId"]): str(item["action"])
        for item in _list(call.graded_actions)
        if isinstance(item, Mapping)
        and isinstance(item.get("plannedWorkoutId"), str)
        and isinstance(item.get("action"), str)
    }
    entry["sessions"] = [
        _session(
            workout,
            adjustment=adjustment,
            no_bike=no_bike,
            no_training=no_training,
            audits=audits,
            graded_action=graded_actions.get(str(workout.get("id"))),
        )
        for workout in _list(call.planned_workouts)
        if isinstance(workout, Mapping)
    ]
    return entry


def _session(
    workout: Mapping[str, Any],
    *,
    adjustment: Mapping[str, Any] | None,
    no_bike: bool,
    audits: Sequence[DeliveryAudit],
    no_training: bool = False,
    graded_action: str | None = None,
) -> dict[str, Any]:
    workout_id = workout.get("id")
    session: dict[str, Any] = {
        "title": workout.get("title"),
        "workoutType": workout.get("workoutType"),
        "basis": workout.get("basis"),
        "planned": {
            "durationMin": workout.get("plannedDurationMin"),
            "intensity": workout.get("intensityTarget"),
        },
    }
    if (
        adjustment is not None
        and adjustment.get("changed") is True
        and isinstance(workout_id, str)
        and adjustment.get("plannedWorkoutId") == workout_id
    ):
        session["morningCall"] = MORNING_CALL_ADJUSTED
        if session["planned"]["durationMin"] is None:
            session["planned"]["durationMin"] = adjustment.get("plannedDurationMin")
        session["planned"]["hardestIntervalPctFtp"] = adjustment.get("plannedWorkPowerPct")
        adjusted: dict[str, Any] = {
            "durationMin": adjustment.get("adjustedDurationMin"),
            "hardestIntervalPctFtp": adjustment.get("adjustedWorkPowerPct"),
        }
        if adjustment.get("removedHit") is True:
            adjusted["hardIntervalsRemoved"] = True
        session["adjusted"] = adjusted
        session.update(_on_his_device(workout_id, audits))
    elif no_training or (no_bike and is_bike_workout_type(_str(workout.get("workoutType")))):
        session["morningCall"] = MORNING_CALL_NO_TRAINING if no_training else MORNING_CALL_NO_BIKE
        # The delivery rail does not read the acute signal, so it can still offer
        # an eased version of a ride the morning ruled out. Say so if it did.
        if isinstance(workout_id, str) and _offered_at(workout_id, audits) is not None:
            session["easedVersionOffered"] = True
            session.update(_on_his_device(workout_id, audits))
    elif graded_action in _HELD_ACTIONS:
        session["morningCall"] = MORNING_CALL_HELD
    else:
        session["morningCall"] = MORNING_CALL_UNCHANGED
    if graded_action is not None:
        session["gradedAction"] = graded_action
    return session


def _on_his_device(workout_id: str, audits: Sequence[DeliveryAudit]) -> dict[str, Any]:
    offered_at = _offered_at(workout_id, audits)
    if offered_at is None:
        return {"onHisDevice": ON_DEVICE_NOT_OFFERED}
    approvals = sorted(
        audit.generated_at_utc
        for audit in audits
        if audit.analysis_type == AUDIT_PUSHED
        and (audit.tag or "").startswith(f"{_APPROVE_TAG_PREFIX}{workout_id}:")
        and audit.generated_at_utc >= offered_at
    )
    if not approvals:
        return {"onHisDevice": ON_DEVICE_OFFERED_NOT_APPROVED}
    approved_at = approvals[0].replace(microsecond=0)
    return {"onHisDevice": ON_DEVICE_APPROVED, "approvedAtUtc": approved_at.isoformat() + "Z"}


def _offered_at(workout_id: str, audits: Sequence[DeliveryAudit]) -> datetime | None:
    offers = [
        audit.generated_at_utc
        for audit in audits
        if audit.analysis_type == AUDIT_PROPOSED
        and any(
            (audit.tag or "").startswith(f"{prefix}{workout_id}:") for prefix in _REGEN_TAG_PREFIXES
        )
    ]
    return min(offers) if offers else None


async def load_recent_mornings(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    today: date,
    as_of_utc: datetime,
) -> dict[str, Any]:
    """The section, from projected rows only — no whole morning packet is loaded."""

    mornings, audits = await load_morning_calls(session, user_id, today=today, as_of_utc=as_of_utc)
    return build_recent_mornings(today=today, mornings=mornings, audits=audits)


async def load_morning_calls(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    today: date,
    as_of_utc: datetime,
) -> tuple[list[MorningCall], list[DeliveryAudit]]:
    """The last seven days' stored mornings and delivery audits, projected.

    ``as_of_utc`` bounds both reads, so a replay of an earlier question sees
    exactly what that question could have seen. Batch 355: one read serves both
    :func:`build_recent_mornings` and :func:`todays_symptom_answer`.
    """

    as_of = as_of_utc.astimezone(UTC).replace(tzinfo=None) if as_of_utc.tzinfo else as_of_utc
    start = today - timedelta(days=RECENT_MORNINGS_DAYS - 1)
    morning_rows = (
        await session.execute(
            select_morning_calls().where(
                Analysis.user_id == user_id,
                Analysis.subject_date >= start,
                Analysis.subject_date <= today,
                Analysis.generated_at_utc <= as_of,
            )
        )
    ).all()
    audit_rows = (
        await session.execute(
            select(
                Analysis.subject_date,
                Analysis.analysis_type,
                Analysis.generated_at_utc,
                Analysis.context_packet["tag"].astext.label("tag"),
            ).where(
                Analysis.user_id == user_id,
                Analysis.analysis_type.in_((AUDIT_PROPOSED, AUDIT_PUSHED)),
                Analysis.subject_date >= start,
                Analysis.subject_date <= today,
                Analysis.generated_at_utc <= as_of,
            )
        )
    ).all()
    return (
        [
            MorningCall(
                subject_date=row.subject_date,
                generated_at_utc=row.generated_at_utc,
                verdict=row.verdict,
                reasons=row.reasons,
                verdict_adjustment=row.verdict_adjustment,
                requires_bike_rest=row.requires_bike_rest,
                requires_training_rest=row.requires_training_rest,
                rest_day=row.rest_day,
                planned_workouts=row.planned_workouts,
                held=row.held,
                graded_actions=row.graded_actions,
                symptoms=row.symptoms,
                graded_easing=row.graded_easing,
            )
            for row in morning_rows
        ],
        [
            DeliveryAudit(
                subject_date=row.subject_date,
                analysis_type=row.analysis_type,
                generated_at_utc=row.generated_at_utc,
                tag=row.tag,
            )
            for row in audit_rows
        ],
    )


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
