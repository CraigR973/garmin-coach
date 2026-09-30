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

This module is pure: callers pass rows already loaded. The Mark-facing notices were
signed off by Craig on Mark's behalf on 28 Sep 2026
(``docs/drafts/2026-09-28-batch-294-wording.md``), with no clinician check (Craig).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    SYMPTOMS_CHEST_HEART: "Chest pain, a racing or irregular heartbeat, or feeling faint",
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
            "Reported chest pain, a racing or irregular heartbeat, or faintness sets a Red "
            "floor: no training of any kind today."
        ),
        plan_line="No training of any kind today — not the bike, strength or mobility work.",
        notice=(
            "You've told me about chest pain, a racing or irregular heartbeat, or feeling "
            "faint. That needs a doctor's view before any training, so no training of any "
            "kind today. Speak to your GP or call 111 today. If you have chest pain right "
            "now, call 999."
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


def symptom_signal(answer: str | None) -> dict[str, Any]:
    """The packet's record of today's answer and the floor it set, if any."""

    floor = SYMPTOM_FLOORS.get(answer) if answer is not None else None
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
    }


def reports_symptoms(answer: str | None) -> bool:
    """Did he report any symptom at all (not "None", and not unanswered)?"""

    return answer in SYMPTOM_FLOORS
