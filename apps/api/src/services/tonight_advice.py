"""Tonight's advice, from the reason today was cautious, and whether it helped (Batch 320).

On 5 Oct Home's Tonight card offered a generic wind-down whatever the morning had found,
and nothing recorded whether any advice was followed. The morning now picks one thing for
tonight from the domain that made it cautious, says how strong the evidence is, and asks
the next morning, in one tap, whether he did it. The weekly review reports the next
morning's change, labelled weak evidence.

The advice follows the engine's own domains (``verdict_grading``), most off first:

* autonomic (his HRV this week or last night, or resting heart rate): alcohol, a late
  meal and a busy evening are the common causes, so the advice avoids all three;
* sleep (the score or total sleep): the sleep window and the room;
* load (the load ratio, recovery time, yesterday's load): food and an earlier night;
* how he feels: an easy evening and an earlier night.

A morning with nothing off has no advice: the usual protocol stands. Pure: callers pass
the stored packet. Words are a draft for Craig's sign-off
(``docs/drafts/2026-10-29-batch-320-wording.md``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Any, Final

ADVICE_HRV: Final = "hrv_recovery"
ADVICE_SLEEP: Final = "sleep_window"
ADVICE_LOAD: Final = "load_refuel"
ADVICE_FEEL: Final = "easy_evening"

FOLLOWED: Final = "followed"
NOT_FOLLOWED: Final = "not_followed"
FOLLOW_ANSWERS: Final = (FOLLOWED, NOT_FOLLOWED)

#: Which domain leads when two are equally off: the order the engine lists them.
_DOMAIN_ADVICE: Final[tuple[tuple[str, str], ...]] = (
    ("autonomic", ADVICE_HRV),
    ("sleep", ADVICE_SLEEP),
    ("load", ADVICE_LOAD),
    ("subjective", ADVICE_FEEL),
)

#: The words, by advice. ``line`` is the thing to do; ``evidence`` says how strong the
#: evidence is, plainly. Draft for Craig's sign-off.
ADVICE_WORDS: Final[dict[str, dict[str, str]]] = {
    ADVICE_HRV: {
        "reason": "Your heart readings are down",
        "line": (
            "Tonight: no alcohol, finish eating about three hours before bed, and a quiet "
            "last hour without screens."
        ),
        "evidence": (
            "Alcohol and late meals lower overnight HRV in studies of other people; the app "
            "hasn't measured them for you."
        ),
    },
    ADVICE_SLEEP: {
        "reason": "Last night's sleep let you down",
        "line": (
            "Tonight: protect your sleep window. In bed at your usual time, the room cool "
            "and dark, and the alarm left where it is."
        ),
        "evidence": (
            "A regular, protected sleep window is standard sleep advice; the app hasn't "
            "measured it for you yet."
        ),
    },
    ADVICE_LOAD: {
        "reason": "Your training load is high",
        "line": (
            "Tonight: a proper meal with carbohydrate and protein, and bed half an hour "
            "earlier than usual."
        ),
        "evidence": (
            "Food and sleep are how hard training turns into fitness; this is general "
            "advice, not something the app has measured for you."
        ),
    },
    ADVICE_FEEL: {
        "reason": "You're feeling flat",
        "line": "Tonight: an easy evening and an earlier night.",
        "evidence": "General advice; the app hasn't measured it for you.",
    },
}

#: The one-tap question at the next morning's check-in (draft for Craig's sign-off).
FOLLOW_QUESTION: Final = "Last night's advice: did you manage it?"
FOLLOW_LABELS: Final[dict[str, str]] = {FOLLOWED: "Yes, I did", NOT_FOLLOWED: "Not this time"}

#: The weekly review reports a difference only with this many nights on each side.
MIN_NIGHTS_EACH: Final = 2


@dataclass(frozen=True, slots=True)
class TonightAdvice:
    key: str
    domain: str
    rating: str
    reason: str
    line: str
    evidence: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "domain": self.domain,
            "rating": self.rating,
            "reason": self.reason,
            "line": self.line,
            "evidence": self.evidence,
            "evidenceStrength": "general",
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def tonight_advice(verdict: Mapping[str, Any]) -> TonightAdvice | None:
    """Tonight's advice for a graded morning, or ``None`` when nothing was off."""

    graded = _mapping(verdict.get("graded"))
    ratings = {
        str(item.get("domain")): str(item.get("rating"))
        for item in graded.get("domains") or []
        if isinstance(item, Mapping)
    }
    for wanted in ("marked", "mild"):
        for domain, key in _DOMAIN_ADVICE:
            if ratings.get(domain) == wanted:
                words = ADVICE_WORDS[key]
                return TonightAdvice(
                    key=key,
                    domain=domain,
                    rating=wanted,
                    reason=words["reason"],
                    line=words["line"],
                    evidence=words["evidence"],
                )
    return None


@dataclass(frozen=True, slots=True)
class AdviceNight:
    """One night's advice, his answer the next morning, and that morning's change."""

    given_on: date
    key: str
    answer: str | None
    #: Next morning minus the morning the advice was given.
    sleep_score_change: float | None
    hrv_change_ms: float | None


def _mean_or_none(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(mean(present), 1) if present else None


def review_summary(nights: Sequence[AdviceNight]) -> dict[str, Any]:
    """The weekly review's record: what was advised, what he did, and the next morning.

    Followed and not-followed nights are compared only inside the one week, so the season
    cannot stand in for the advice (HS332-02's confound), and only with
    :data:`MIN_NIGHTS_EACH` nights on each side. Always labelled weak evidence.
    """

    answered = [night for night in nights if night.answer in FOLLOW_ANSWERS]
    followed = [night for night in answered if night.answer == FOLLOWED]
    skipped = [night for night in answered if night.answer == NOT_FOLLOWED]
    comparable = len(followed) >= MIN_NIGHTS_EACH and len(skipped) >= MIN_NIGHTS_EACH
    return {
        "nightsAdvised": len(nights),
        "nightsAnswered": len(answered),
        "nightsFollowed": len(followed),
        "evidence": "weak",
        "meaning": (
            "Weak evidence: a handful of nights in one week, his own answer, and many other "
            "things change night to night. Report it as what happened, never as proof the "
            "advice works or does not."
        ),
        "comparable": comparable,
        "followed": {
            "sleepScoreChange": _mean_or_none([n.sleep_score_change for n in followed]),
            "hrvChangeMs": _mean_or_none([n.hrv_change_ms for n in followed]),
        }
        if comparable
        else None,
        "notFollowed": {
            "sleepScoreChange": _mean_or_none([n.sleep_score_change for n in skipped]),
            "hrvChangeMs": _mean_or_none([n.hrv_change_ms for n in skipped]),
        }
        if comparable
        else None,
        "byAdvice": sorted({night.key for night in nights}),
    }
