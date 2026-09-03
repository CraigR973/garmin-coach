"""Rotating REM-intervention library (Batch 72).

Mark's REM has run low since he got the watch, so the Batch 59 chronic-pattern
card surfaces a REM flag most weeks — but it only ever showed the same two static
lines. This module gives a persistent REM miss a *broader* set of grounded
interventions and hands out only **one or two at a time**, rotated
deterministically week to week so the advice stays focused rather than a static
list he has already read.

It is pure and stateless: the rotation is seeded from the calendar week, so a
given week always yields the same pair (stable within the week, advancing across
weeks) with no persisted cursor and no migration. A measured sleep driver can
bias the week's selection toward the intervention it implicates, keeping the set
responsive to his real data rather than a blind cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, Literal

REM_ROTATION_WINDOW = 2


# Batch 250 (HS240-10): the library mixed A-grade physiology with folk mechanisms
# in one voice, and the rotation treated all twelve as interchangeable — so about a
# third of the advice Mark read in any week taught him a mechanism about his own
# body that is not true. The grade is the review's, per lever, on the *stated REM
# mechanism* rather than on whether the action is sensible: several C and D levers
# are perfectly good sleep hygiene and none is deleted.
EvidenceGrade = Literal["A", "B", "C", "D"]

# A and B levers lead. The weaker ones still appear — the rotation walks the whole
# library — but they no longer out-rank a lever whose mechanism is established.
STRONG_GRADES: frozenset[str] = frozenset({"A", "B"})


@dataclass(frozen=True)
class RemIntervention:
    """One grounded REM lever. ``template`` may reference sleep-protocol values."""

    id: str
    template: str
    driver_affinity: frozenset[str] = frozenset()
    # Batch 250: how good the evidence for this lever's REM claim actually is.
    # Defaulting to "C" rather than "A" means a lever added without grading it is
    # treated as weak, which is the safe direction for a library whose whole
    # defect was unearned confidence.
    evidence_grade: EvidenceGrade = "C"
    # Why the grade is what it is, in one line, so a future reader does not have to
    # re-derive it from the literature.
    grade_note: str = ""


@dataclass(frozen=True)
class RemRotation:
    """How the week's focused set sits inside the wider rotating library."""

    period_label: str
    shown: int
    total: int
    intervention_ids: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    evidence_grades: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "periodLabel": self.period_label,
            "shown": self.shown,
            "total": self.total,
            "interventionIds": list(self.intervention_ids),
            # Batch 250: what each issued lever's REM mechanism is actually worth,
            # so the packet can no longer present all twelve in one voice.
            "evidenceGrades": dict(self.evidence_grades),
        }


# Ordered so consecutive weeks walk through the whole library before repeating.
# Each entry is REM-specific: REM concentrates in the last cycles of the night
# and is fragile to short sleep, alcohol, warmth, late stimulation, and circadian
# drift — the levers below all target one of those.
REM_LIBRARY: tuple[RemIntervention, ...] = (
    RemIntervention(
        id="wake_time_anchor",
        template=(
            "Hold your wake time steady (±30 min) all week — REM loads into the last "
            "cycles, so a fixed wake time protects it most."
        ),
        evidence_grade="A",
        grade_note=(
            "REM is back-loaded, and sleep regularity independently predicts outcomes "
            "(Windred et al. 2024, Sleep). Mark's own 212 nights confirm the back-loading: "
            "half his REM falls in the final quarter."
        ),
    ),
    RemIntervention(
        id="protect_last_cycle",
        template=(
            "Skip early alarms after a late night; the final 90-minute cycle is the "
            "most REM-rich, so it is the first thing an early wake-up cuts."
        ),
        evidence_grade="A",
        grade_note=(
            "Truncating the night selectively removes REM, and Batch 250 measured the "
            "mechanism directly in his data: Q4 carries 50.9% of his REM. His wake time "
            "varies by only 47 minutes SD, so this is a lever he already keeps."
        ),
    ),
    RemIntervention(
        id="bedtime_hard_stop",
        template=(
            "Treat {bedtime} as a hard lights-out this week, not a target — REM sits in the "
            "last cycles, so a night that ends early never reaches most of it."
        ),
        evidence_grade="B",
        grade_note=(
            "Extending sleep opportunity does increase absolute REM, but 'rebounds when the "
            "night is long enough' conflates opportunity with homeostatic rebound, and a "
            "hard lights-out is the inverse of CBT-I stimulus control if sleep-maintenance "
            "insomnia ever appears."
        ),
    ),
    RemIntervention(
        id="alcohol_free_evenings",
        template=(
            "Keep the evening alcohol-free before priority nights; more than a drink or two "
            "suppresses first-half REM and fragments the rest."
        ),
        evidence_grade="B",
        grade_note=(
            "Ebrahim et al. 2013 (Alcohol Clin Exp Res): moderate-to-high doses suppress "
            "first-half REM and fragment the second half. Low-dose REM effects are "
            "inconsistent, so 'even one drink' overstated the dose."
        ),
    ),
    RemIntervention(
        id="caffeine_cutoff",
        template=(
            "Pull your last caffeine back to early afternoon — its long half-life costs you "
            "total sleep and deep sleep, and a shorter night has less room for REM."
        ),
        evidence_grade="C",
        grade_note=(
            "Caffeine robustly reduces total sleep time, efficiency and deep sleep and "
            "raises time awake (Gardiner et al. 2023 meta-analysis; Drake et al. 2013), but "
            "pooled analyses do not show a significant REM reduction. Good sleep advice, "
            "wrong mechanism for this library."
        ),
    ),
    RemIntervention(
        id="room_cool_late_cycles",
        template=(
            "Hold the room cool into the early morning (pre-cool to {preCoolTemperatureC}°C, "
            "seal by {sealTargetTime}) — warmth in the back half of the night is when "
            "REM gets disrupted."
        ),
        driver_affinity=frozenset(
            {
                "bedroom_mean_temp_c",
                "bedroom_min_temp_c",
                "bedroom_max_temp_c",
                "bedroom_warning_minutes",
                "bedroom_critical_minutes",
                "bedroom_fan_ran_minutes",
                "bedroom_peak_fan_speed",
                "overnight_low_c",
            }
        ),
        evidence_grade="A",
        grade_note=(
            "REM poikilothermia is real: thermoregulation is suspended during REM, so "
            "warmth reaches it first (Okamoto-Mizuno & Mizuno 2012). The threshold numbers "
            "are a separate problem - HS240-08 has them sitting at Mark's own median."
        ),
    ),
    RemIntervention(
        id="evening_light_down",
        template=(
            "Dim screens and overhead lights in the last hour before bed; late bright light "
            "delays your body clock, which pushes the REM-rich end of the night later."
        ),
        evidence_grade="C",
        grade_note=(
            "Evening light suppresses melatonin and delays circadian phase (Chang et al. "
            "2015, PNAS), which shifts REM propensity later. 'Shallower' REM was invented - "
            "REM has no depth dimension - and ordinary room light is far below the studies' "
            "doses."
        ),
    ),
    RemIntervention(
        id="wind_down_consistency",
        template=(
            "Run the same wind-down every night (coherence breathing at "
            "{coherenceBreathingTime}) — some people settle faster on a fixed routine, "
            "though its effect on REM specifically is untested."
        ),
        driver_affinity=frozenset({"prev_day_stress_avg"}),
        evidence_grade="C",
        grade_note=(
            "Slow-paced breathing acutely raises HRV (Lehrer & Gevirtz 2014). There is no "
            "evidence it changes REM, and 'REM responds to a steady routine more than to "
            "any single trick' was invented outright."
        ),
    ),
    RemIntervention(
        id="late_meal_timing",
        template=(
            "Finish the last real food by {latestSnackTime}; some people sleep less well on "
            "a full stomach, though the link to REM specifically is not established."
        ),
        evidence_grade="D",
        grade_note=(
            "Diet-induced thermogenesis from an evening meal is small and largely "
            "dissipated within 3-4 hours, so it cannot warm the core through the early "
            "morning. The evidence linking late eating to sleep architecture is thin and "
            "mixed."
        ),
    ),
    RemIntervention(
        id="stress_offload",
        template=(
            "On busy days, write tomorrow's list down before bed — it helps people fall "
            "asleep faster, which gives the night more room."
        ),
        driver_affinity=frozenset({"prev_day_stress_avg"}),
        evidence_grade="D",
        grade_note=(
            "The write-the-list RCT (Scullin et al. 2018) measured sleep-onset latency, not "
            "REM. Acute stress and low mood are classically associated with SHORTENED REM "
            "latency and increased REM density, so 'stress eats REM' is at best contested "
            "and may be backwards."
        ),
    ),
    RemIntervention(
        id="rem_rebound_recovery",
        template=(
            "After a short or broken night, protect the next full night rather than "
            "catching up early; REM rebounds when you give it the back end of a normal "
            "sleep."
        ),
        evidence_grade="A",
        grade_note=(
            "REM rebound after REM deprivation is among the best-replicated findings in "
            "sleep physiology."
        ),
    ),
    RemIntervention(
        id="late_training_guard",
        template=(
            "If a hard ride finishes within an hour of bed, leave a longer gap - later "
            "training is otherwise fine for sleep, and often helps."
        ),
        driver_affinity=frozenset({"prev_day_training_load"}),
        evidence_grade="D",
        grade_note=(
            "Contradicts the weight of the evidence: meta-analyses (Stutz et al. 2019, "
            "Sports Med; Frimpong et al. 2021, Sleep Med Rev) find evening exercise does "
            "not harm sleep and often improves it, except for vigorous work ending under an "
            "hour before bed. Asking a cyclist to move training is a real cost for a "
            "marginal mechanism."
        ),
    ),
)

_DEFAULT_PARAMS: dict[str, str] = {
    "bedtime": "23:15",
    "sealTargetTime": "22:00",
    "coherenceBreathingTime": "20:00",
    "latestSnackTime": "21:30",
    "preCoolTemperatureC": "17",
}


def _params(protocol: Mapping[str, Any] | None) -> dict[str, str]:
    params = dict(_DEFAULT_PARAMS)
    if protocol:
        for key in params:
            value = protocol.get(key)
            if isinstance(value, str | int | float):
                params[key] = str(value)
    return params


def render(intervention: RemIntervention, params: Mapping[str, str]) -> str:
    return intervention.template.format(**params)


def _week_period(as_of: date) -> tuple[int, date]:
    """Monotonic week index + the ISO Monday, so a whole Mon–Sun week is stable."""
    monday = as_of - timedelta(days=as_of.weekday())
    return monday.toordinal() // 7, monday


def select_rem_interventions(
    *,
    as_of: date,
    protocol: Mapping[str, Any] | None = None,
    driver_key: str | None = None,
    window: int = REM_ROTATION_WINDOW,
    library: tuple[RemIntervention, ...] = REM_LIBRARY,
    complied_intervention_ids: frozenset[str] = frozenset(),
) -> tuple[list[str], RemRotation]:
    """Pick the week's focused REM set, rotated deterministically over ``library``.

    The rotation walks ``window`` fresh interventions each week, cycling through the
    whole library before repeating. A measured ``driver_key`` biases the week toward
    the lever it implicates (pinned first, keeping the window size), so a thermal or
    load signal surfaces its REM intervention even if the blind rotation had not
    reached it this week.

    Batch 231: ``complied_intervention_ids`` — the recorded standing habits — are
    removed from the library *before* the rotation is computed, so a lever he
    already keeps is never issued, never asked about, and never counted toward a
    comparison it could not complete. ``total`` reports what is actually
    available, so "2 of 10 levers this week" stays true on the card.
    """
    if complied_intervention_ids:
        library = tuple(item for item in library if item.id not in complied_intervention_ids)
    total = len(library)
    if total == 0:
        _, monday = _week_period(as_of)
        return [], RemRotation(
            period_label=_period_label(monday),
            shown=0,
            total=0,
            intervention_ids=(),
            actions=(),
        )
    window = max(1, min(window, total))
    period, monday = _week_period(as_of)

    # Batch 250 (HS240-10): the rotation was blind, so a week could hand Mark two
    # levers whose REM mechanisms are both invented — and roughly a third of the
    # library is in that category. Strong and weak levers now rotate on separate
    # cursors and the week is filled strong-first, which guarantees **every week
    # carries at least one lever whose mechanism is established** while still
    # walking the weak ones through rather than deleting them. Several of the weak
    # levers are good sleep hygiene; only their REM claims were wrong, and those
    # have been rewritten rather than dropped.
    strong = [item for item in library if item.evidence_grade in STRONG_GRADES]
    weak = [item for item in library if item.evidence_grade not in STRONG_GRADES]
    chosen: list[RemIntervention] = []
    if strong and weak:
        strong_slots = (window + 1) // 2
        weak_slots = window - strong_slots
        chosen = [
            strong[(period * strong_slots + offset) % len(strong)] for offset in range(strong_slots)
        ]
        chosen += [weak[(period * weak_slots + offset) % len(weak)] for offset in range(weak_slots)]
    else:
        start = (period * window) % total
        chosen = [library[(start + offset) % total] for offset in range(window)]

    if driver_key is not None:
        affine = next(
            (item for item in library if driver_key in item.driver_affinity),
            None,
        )
        if affine is not None and affine.id not in {item.id for item in chosen}:
            chosen = [affine, *chosen][:window]

    params = _params(protocol)
    actions = [render(item, params) for item in chosen]
    return actions, RemRotation(
        period_label=_period_label(monday),
        shown=len(actions),
        total=total,
        intervention_ids=tuple(item.id for item in chosen),
        actions=tuple(actions),
        evidence_grades=MappingProxyType({item.id: item.evidence_grade for item in chosen}),
    )


def intervention_by_id(intervention_id: str) -> RemIntervention | None:
    """Return one stable library item without exposing the ordered tuple as a map."""
    return next((item for item in REM_LIBRARY if item.id == intervention_id), None)


def _period_label(monday: date) -> str:
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
