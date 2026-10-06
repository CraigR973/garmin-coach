"""The symptom question at check-in, and the medical floors it sets (Batch 294).

Until this batch the colour never asked about symptoms and never read what Mark
wrote. In 75 morning notes he has never reported one, so the app could not tell
whether he had been well or simply would not think to write it. For a 57-year-old
endurance athlete the warnings that matter most are symptoms, not numbers: chest
pain, palpitations, feeling faint, and illness "below the neck".

The check-in therefore asks one question with four answers, and three of them set
a floor that no other signal can override. A floor is for harm, not performance
(the 28 Sep review, MD-1), so there are exactly three and each is the sports-medicine
"neck check":

* chest pain, a racing or irregular heartbeat, or feeling faint: Red, no training of
  any kind, and a doctor the same day;
* fever, aches or a chest infection: Red, no training until the symptoms have gone;
* a head cold, above the neck: Red on the easy path, easy riding at most.

A morning with no check-in has no answer, and no answer is never read as "None".

Batch 303 adds what follows a symptom, so a floor does not quietly lapse. The two
mornings after a fever-or-aches floor are easy days back, and a note that may mean a
chest or heart symptom eases the hard session until he answers: on both, the day is
not Red, and a hard session becomes an easy ride (:func:`fever_return_easing`,
:func:`chest_question_easing`). "Chest or heart" also covers unusual breathlessness.

Batch 315 follows a chest or heart report itself: from the next morning, until he says
the symptoms have gone and that he has spoken to his GP or 111, a hard session is an
easy ride and Home asks him each morning (:func:`chest_follow_up`,
:func:`chest_follow_up_easing`). "Still there" sets the chest-or-heart floor again.

This module is pure: callers pass rows already loaded. The Mark-facing notices were
signed off by Craig on Mark's behalf on 28 Sep 2026
(``docs/drafts/2026-09-28-batch-294-wording.md``) and, for Batch 303, on 2 Oct 2026
(``docs/drafts/2026-10-02-batch-303-wording.md``), with no clinician check (Craig).
Batch 315's lines were signed off under Craig's delegation of 6 Oct 2026
(``docs/drafts/2026-10-06-batch-315-wording.md``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Protocol

SYMPTOMS_NONE: Final = "none"
SYMPTOMS_HEAD_COLD: Final = "head_cold"
SYMPTOMS_FEVER_ACHES: Final = "fever_aches"
SYMPTOMS_CHEST_HEART: Final = "chest_heart"

#: Every value the check-in may store, in the order the question shows them.
#: Migration 033's check constraint lists the same four.
SYMPTOM_ANSWERS: Final[tuple[str, ...]] = (
    SYMPTOMS_NONE,
    SYMPTOMS_HEAD_COLD,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_CHEST_HEART,
)

#: Answers that count as the ``illness`` cause for the two-Reds-in-a-week rule, so a
#: Red a cold explains is qualified by Batch 194's exclusion like a written one.
ILLNESS_SYMPTOM_ANSWERS: Final = frozenset({SYMPTOMS_HEAD_COLD, SYMPTOMS_FEVER_ACHES})

#: How each answer is named to the coach and in the packet.
SYMPTOM_LABELS: Final[dict[str, str]] = {
    SYMPTOMS_NONE: "None",
    SYMPTOMS_HEAD_COLD: "A head cold, above the neck",
    SYMPTOMS_FEVER_ACHES: "Fever, aches or a chest infection",
    SYMPTOMS_CHEST_HEART: (
        "Chest pain, a racing or irregular heartbeat, feeling faint, or unusual breathlessness"
    ),
}

FLOOR_NO_TRAINING_SEE_DOCTOR: Final = "no_training_see_doctor"
FLOOR_NO_TRAINING_UNTIL_CLEAR: Final = "no_training_until_clear"
FLOOR_EASY_RIDING_ONLY: Final = "easy_riding_only"


@dataclass(frozen=True, slots=True)
class SymptomFloor:
    """What one answer does to the day."""

    answer: str
    floor: str
    #: No training of any kind: every session type, not only the bike.
    requires_training_rest: bool
    #: The verdict reason, in the app's words. The coach quotes reasons when asked.
    reason: str
    #: The day's plan line, or ``None`` when the ordinary Red lines apply.
    plan_line: str | None
    #: The notice Mark reads on Home and the brief.
    notice: str
    #: How the overnight-HRV notice names this answer when the two coincide.
    corroboration: str


SYMPTOM_FLOORS: Final[dict[str, SymptomFloor]] = {
    SYMPTOMS_CHEST_HEART: SymptomFloor(
        answer=SYMPTOMS_CHEST_HEART,
        floor=FLOOR_NO_TRAINING_SEE_DOCTOR,
        requires_training_rest=True,
        reason=(
            "Reported chest pain, a racing or irregular heartbeat, faintness or unusual "
            "breathlessness sets a Red floor: no training of any kind today."
        ),
        plan_line="No training of any kind today — not the bike, strength or mobility work.",
        notice=(
            "You've told me about chest pain, a racing or irregular heartbeat, feeling "
            "faint, or unusual breathlessness. That needs a doctor's view before any "
            "training, so no training of any kind today. Speak to your GP or call 111 "
            "today. If you have chest pain or are struggling to breathe right now, call 999."
        ),
        corroboration="you've told me about chest or heart symptoms",
    ),
    SYMPTOMS_FEVER_ACHES: SymptomFloor(
        answer=SYMPTOMS_FEVER_ACHES,
        floor=FLOOR_NO_TRAINING_UNTIL_CLEAR,
        requires_training_rest=True,
        reason=(
            "Reported fever, aches or a chest infection sets a Red floor: no training of any "
            "kind until the symptoms have gone."
        ),
        plan_line=(
            "No training of any kind until the symptoms have gone, then build back gradually."
        ),
        notice=(
            "You've told me about a fever, aches or a chest infection. Training through that "
            "adds strain your body doesn't need and usually makes it last longer, so no "
            "training of any kind until the symptoms have gone. When you're clear, build "
            "back gradually: a few easy days before anything hard."
        ),
        corroboration="you've told me about a fever, aches or a chest infection",
    ),
    SYMPTOMS_HEAD_COLD: SymptomFloor(
        answer=SYMPTOMS_HEAD_COLD,
        floor=FLOOR_EASY_RIDING_ONLY,
        requires_training_rest=False,
        reason=(
            "A reported head cold sets a Red floor: easy riding at most, with nothing hard "
            "and no VO2."
        ),
        plan_line=None,
        notice=(
            "You've told me you have a head cold — symptoms above the neck. Easy riding at "
            "most today, and only if you feel up to it: nothing hard, no intervals and no "
            "VO₂. If it moves below the neck — a fever, aches or a chesty cough — stop "
            "training until you're clear."
        ),
        corroboration="you've told me you have a head cold",
    ),
}


#: How serious each answer is, for choosing between his tap and his note (Batch 297).
SYMPTOM_SEVERITY: Final[dict[str, int]] = {
    SYMPTOMS_NONE: 0,
    SYMPTOMS_HEAD_COLD: 1,
    SYMPTOMS_FEVER_ACHES: 2,
    SYMPTOMS_CHEST_HEART: 3,
}


def more_severe_symptom(first: str | None, second: str | None) -> str | None:
    """The more serious of two answers; an answer outranks none at all."""

    candidates = [answer for answer in (first, second) if answer in SYMPTOM_SEVERITY]
    if not candidates:
        return None
    return max(candidates, key=lambda answer: SYMPTOM_SEVERITY[answer])


class _HasSymptoms(Protocol):
    symptoms: str | None


def latest_symptom_answer(manual_entries: Sequence[_HasSymptoms]) -> str | None:
    """The answer from the newest check-in that gave one.

    Callers pass entries newest first, as they already do for the feel score. An
    unrecognised value is treated as no answer rather than guessed at; the column's
    check constraint means one cannot be stored.
    """

    for entry in manual_entries:
        answer = entry.symptoms
        if answer in SYMPTOM_ANSWERS:
            return answer
    return None


# -- Batch 303: what follows a symptom ----------------------------------------------------

#: The mornings after the last fever-or-aches floor on which hard work stays easy
#: (Craig, 2 Oct 2026). The fever notice has said "a few easy days before anything
#: hard" since Batch 294, and nothing made it so.
ILLNESS_RETURN_MORNINGS: Final = 2

#: Why today's hard session is an easy ride although nothing sets a floor today.
EASING_FEVER_RETURN: Final = "fever_return"
EASING_CHEST_QUESTION: Final = "chest_question"
#: Batch 315: after a chest or heart report, until he says he has been checked.
EASING_CHEST_FOLLOW_UP: Final = "chest_follow_up"
EASING_KINDS: Final = frozenset(
    {EASING_FEVER_RETURN, EASING_CHEST_QUESTION, EASING_CHEST_FOLLOW_UP}
)

#: The plan line for a hard session on such a morning (signed off 2 Oct 2026).
EASY_RIDING_PLAN_LINE: Final = "Easy riding only today: swap the hard session for an easy spin."

_ORDINALS: Final = ("first", "second", "third")
_COUNTS: Final = ("one", "two", "three")


@dataclass(frozen=True, slots=True)
class IllnessReturn:
    """Where this morning sits in the easy days back after a fever-or-aches floor."""

    reported_on: date
    #: 1 on the morning after the last floor, 2 on the one after that.
    day: int
    of: int = ILLNESS_RETURN_MORNINGS


def illness_return(
    subject_date: date, floor_answers: Mapping[date, str | None]
) -> IllnessReturn | None:
    """The easy days back this morning falls in, or ``None``.

    ``floor_answers`` is the symptom answer that set each recent day's floor, read from
    that day's latest stored morning: a fever named only in his note counts, and an
    answer he corrected the same day does not. The nearest fever day decides, so the
    count restarts after each one. A day with no stored morning has no answer.
    """

    for offset in range(1, ILLNESS_RETURN_MORNINGS + 1):
        day = subject_date - timedelta(days=offset)
        if floor_answers.get(day) == SYMPTOMS_FEVER_ACHES:
            return IllnessReturn(reported_on=day, day=offset)
    return None


def fever_return_easing(window: IllnessReturn) -> dict[str, Any]:
    """The packet's record of an easy day back after a fever. The day is always named."""

    weekday = window.reported_on.strftime("%A")
    return {
        "kind": EASING_FEVER_RETURN,
        "reportedOn": window.reported_on.isoformat(),
        "day": window.day,
        "of": window.of,
        "words": None,
        "reason": (
            f"Easing back after the fever you reported on {weekday}: easy riding only, "
            f"day {window.day} of {window.of}."
        ),
        "planLine": EASY_RIDING_PLAN_LINE,
        "notice": (
            f"You told me about a fever, aches or a chest infection on {weekday}. This is "
            f"the {_ORDINALS[window.day - 1]} of {_COUNTS[window.of - 1]} easy days back: "
            "easy riding at most, nothing hard. If any of it comes back, tell me in your "
            "check-in and rest."
        ),
    }


def chest_question_line(words: str | None) -> str:
    """Home's line while a possible chest or heart mention eases the hard session.

    The web shows the same sentence on the question's card
    (``apps/web/src/lib/notesAsk.ts``); a test pins the two together.
    """

    quoted = (words or "").strip()
    lead = (
        f"Your note mentions \u201c{quoted}\u201d."
        if quoted
        else "Something in your note might be a symptom."
    )
    return f"{lead} Until you answer, today\u2019s hard session is an easy ride."


def chest_question_easing(words: str | None) -> dict[str, Any]:
    """The packet's record of a possible chest or heart mention he has not yet answered.

    It eases a hard session and nothing else: with none planned the day is unchanged
    and Home only asks. There is no notice; the question's own card says it.
    """

    return {
        "kind": EASING_CHEST_QUESTION,
        "reportedOn": None,
        "day": None,
        "of": None,
        "words": (words or "").strip() or None,
        "reason": chest_question_line(words),
        "planLine": EASY_RIDING_PLAN_LINE,
        "notice": None,
    }


# -- Batch 315: after a chest or heart report, ask before hard work -------------------------

#: His one-tap answers to Home's follow-up (``symptom_follow_ups.answer``; migration 036's
#: check constraint lists the same three). Only "cleared" ends the follow-up: the guidance
#: is that chest symptoms are assessed before vigorous exercise resumes (Pelliccia 2021;
#: Schwellnus 2022), and the chest-or-heart notice already tells him so.
FOLLOW_UP_CLEARED: Final = "cleared"
FOLLOW_UP_NOT_SEEN: Final = "not_seen"
FOLLOW_UP_STILL_THERE: Final = "still_there"
FOLLOW_UP_ANSWERS: Final[tuple[str, ...]] = (
    FOLLOW_UP_CLEARED,
    FOLLOW_UP_NOT_SEEN,
    FOLLOW_UP_STILL_THERE,
)


@dataclass(frozen=True, slots=True)
class ChestFollowUp:
    """The chest or heart follow-up this morning is in."""

    #: The day whose latest stored morning carried the chest-or-heart floor.
    reported_on: date
    #: His answer on this morning, or ``None`` while Home is still asking.
    answer: str | None = None

    @property
    def open(self) -> bool:
        """Still asking, and still easing hard work: until he says he has been checked."""

        return self.answer != FOLLOW_UP_CLEARED

    def to_packet(self) -> dict[str, Any]:
        return {
            "reportedOn": self.reported_on.isoformat(),
            "answer": self.answer,
            "open": self.open,
        }


def chest_follow_up(
    previous_day: date | None,
    previous_symptoms: Mapping[str, Any] | None,
    answer: str | None = None,
) -> ChestFollowUp | None:
    """The follow-up this morning is in, read from the latest stored morning before it.

    ``previous_symptoms`` is ``verdict.acutePhysiology.symptoms`` of the latest stored
    morning of the most recent day before this one, dated ``previous_day``. A chest or
    heart floor there starts a follow-up dated that day; a follow-up it carried, still
    open, continues with its own date. Each graded morning stores the follow-up it was
    in (``symptoms.chestFollowUp``) whether or not today's floor outranks its easing, so
    a day of a stricter floor does not end it. A day without a stored morning is
    skipped over, because the most recent stored morning is read, not yesterday's.
    ``answer`` is his answer on this morning, if he has given one.
    """

    if previous_day is None or not isinstance(previous_symptoms, Mapping):
        return None
    if (
        previous_symptoms.get("triggered") is True
        and previous_symptoms.get("answer") == SYMPTOMS_CHEST_HEART
    ):
        reported_on = previous_day
    else:
        carried = previous_symptoms.get("chestFollowUp")
        if not isinstance(carried, Mapping) or carried.get("open") is not True:
            return None
        try:
            reported_on = date.fromisoformat(str(carried.get("reportedOn")))
        except ValueError:
            return None
    return ChestFollowUp(
        reported_on=reported_on,
        answer=answer if answer in FOLLOW_UP_ANSWERS else None,
    )


def follow_up_symptom_answer(answer: str | None) -> str | None:
    """The symptom answer a follow-up answer gives today: "Still there" is chest or heart."""

    return SYMPTOMS_CHEST_HEART if answer == FOLLOW_UP_STILL_THERE else None


def chest_follow_up_line(reported_on: date) -> str:
    """The reason under today's call while the follow-up eases a hard session."""

    weekday = reported_on.strftime("%A")
    return (
        f"Easing off after the chest or heart symptoms you reported on {weekday}: easy "
        "riding only until you've spoken to your GP or 111."
    )


def chest_follow_up_easing(follow_up: ChestFollowUp) -> dict[str, Any]:
    """The packet's record of an open chest or heart follow-up.

    It eases a hard session and nothing else, as the chest question does: with none
    planned the day is unchanged and Home only asks. There is no notice; the follow-up's
    own card on Home says it.
    """

    return {
        "kind": EASING_CHEST_FOLLOW_UP,
        "reportedOn": follow_up.reported_on.isoformat(),
        "day": None,
        "of": None,
        "words": None,
        "reason": chest_follow_up_line(follow_up.reported_on),
        "planLine": EASY_RIDING_PLAN_LINE,
        "notice": None,
    }


def morning_easing(
    *,
    illness: IllnessReturn | None,
    follow_up: ChestFollowUp | None,
    chest_question: bool,
    chest_question_words: str | None = None,
) -> dict[str, Any] | None:
    """The one easing a morning reads, of everything that may follow a symptom.

    Each eases a hard session, so the morning reads one: the easy days back after a fever
    first, because they carry a notice and hold whatever is planned (Batch 303); then an
    open chest or heart follow-up (Batch 315); then a possible chest or heart mention in
    today's note he has not answered (Batch 303). The follow-up is recorded on the
    morning whichever reads, so Home still asks.
    """

    if illness is not None:
        return fever_return_easing(illness)
    if follow_up is not None and follow_up.open:
        return chest_follow_up_easing(follow_up)
    if chest_question:
        return chest_question_easing(chest_question_words)
    return None


def symptom_signal(
    answer: str | None,
    *,
    easing: Mapping[str, Any] | None = None,
    follow_up: ChestFollowUp | None = None,
) -> dict[str, Any]:
    """The packet's record of today's answer and the floor it set, if any.

    ``easing`` (Batch 303) is what follows a symptom on a morning with no floor of its
    own. A floor set today outranks it, so it is dropped when one is. ``follow_up``
    (Batch 315) is kept whatever today's floor is, so the next morning can read it.
    """

    floor = SYMPTOM_FLOORS.get(answer) if answer is not None else None
    kept_easing = (
        dict(easing)
        if floor is None and easing is not None and easing.get("kind") in EASING_KINDS
        else None
    )
    return {
        "answer": answer,
        "answered": answer is not None,
        "label": SYMPTOM_LABELS.get(answer) if answer is not None else None,
        "triggered": floor is not None,
        "floor": floor.floor if floor else None,
        "verdictImpact": "red_floor" if floor else "none",
        "requiresBikeRest": bool(floor and floor.requires_training_rest),
        "requiresTrainingRest": bool(floor and floor.requires_training_rest),
        "reason": floor.reason if floor else None,
        "planLine": floor.plan_line if floor else None,
        "escalation": floor.notice if floor else None,
        "easing": kept_easing,
        "chestFollowUp": follow_up.to_packet() if follow_up is not None else None,
    }


def reports_symptoms(answer: str | None) -> bool:
    """Did he report any symptom at all (not "None", and not unanswered)?"""

    return answer in SYMPTOM_FLOORS
