"""Tonight's sleep read, from today's training and the room he is about to sleep in.

**Batch 249 (HS240-11) removed a second, looser copy of a judgement the app had
already made carefully once.** Batch 231 built one gate for naming a measured
driver — actionable, enough nights, strong enough, unfavourable — and put it
behind the chronic-suggestion card. This module kept its own: *any* driver with a
negative coefficient and eight nights qualified, and the strongest by raw ``|r|``
was printed as **"Measured driver: X has tracked with lower sleep scores"** on
Home, on ``/sleep`` and in the evening push. On 2026-09-03 the driver it named in
production was ``sleep_stress_avg`` — a measurement taken *during* the night it
was being correlated against, and one of exactly two keys
``driver_levers.CONCURRENT_DRIVERS`` exists to forbid. The looser claim won on
exposure.

The gate now arrives pre-applied: :func:`driver_levers.select_levers` decides
what may be named, and this module reports what it is handed. When nothing
clears the bar — the usual answer, and the honest one — the projection names no
driver at all and stands on what it directly observed instead.

**What deliberately did *not* move behind the gate.** A late, hard session is a
fact about today; a bedroom at 20.5C is a thermometer reading; a warm overnight
low is a forecast. None of them needs a correlation's permission, and the old
code requiring one meant a genuine thermometer reading could only be acted on if
some coefficient happened to be negative. Direct observation was never the
unreliable part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

LATE_SESSION_HOUR = 17
HIGH_TRAINING_LOAD = 120.0
LONG_SESSION_MIN = 90
HIGH_AEROBIC_EFFECT = 3.5
HIGH_ANAEROBIC_EFFECT = 2.0
WARM_ROOM_C = 19.5
WARM_OVERNIGHT_LOW_C = 14.0


@dataclass(frozen=True)
class TrainingSignal:
    name: str
    activity_type: str
    local_start: time | None = None
    duration_min: float | None = None
    training_load: float | None = None
    aerobic_training_effect: float | None = None
    anaerobic_training_effect: float | None = None


@dataclass(frozen=True)
class SleepDriverEvidence:
    """A driver that has already passed ``driver_levers``' gate (Batch 249).

    Nothing in this module re-judges it. ``evidence_sentence`` carries the
    interval and the sample the gate stood on, ``confounds`` the reasons the
    number may not mean what it looks like.
    """

    driver: str
    coefficient: float
    sample_count: int
    summary: str | None = None
    evidence_sentence: str | None = None
    confounds: tuple[str, ...] = ()


@dataclass(frozen=True)
class SleepProjectionInputs:
    training: list[TrainingSignal]
    sleep_drivers: list[SleepDriverEvidence]
    sleep_protocol: dict[str, Any] = field(default_factory=dict)
    latest_bedroom_temperature_c: float | None = None
    overnight_low_c: float | None = None
    overnight_wind_max_mph: float | None = None
    fan_auto_enabled: bool = True


@dataclass(frozen=True)
class SleepProjectionResult:
    status: str  # personalized | fallback
    tone: str  # routine | protect | watch
    headline: str
    summary: str
    evidence: list[str]
    prep_actions: list[str]
    protocol: dict[str, Any]


_DRIVER_LABELS = {
    "prev_day_training_load": "training load",
    "overnight_low_c": "warm overnight weather",
    "overnight_wind_max_mph": "overnight wind",
    "bedroom_warning_minutes": "time above 19.5C",
    "bedroom_critical_minutes": "time above 20C",
    "bedroom_fan_ran_minutes": "fan runtime",
    "bedroom_peak_fan_speed": "fan speed",
    "prev_day_stress_avg": "the previous day's stress",
    "resting_heart_rate_bpm": "resting heart rate",
    "sleep_stress_avg": "sleep stress",
}


def project_sleep(inputs: SleepProjectionInputs) -> SleepProjectionResult:
    protocol = _normalise_protocol(inputs.sleep_protocol)
    measured = list(inputs.sleep_drivers)
    # Batch 249: the fallback is now about today's training, not about whether a
    # correlation survived. Requiring a named driver here would have sent almost
    # every night to the generic protocol once the gate was applied, which is a
    # worse read than the one today's session supports on its own.
    if not inputs.training:
        return _fallback_result(protocol)

    training = _training_summary(inputs.training)
    warm_room = (
        inputs.latest_bedroom_temperature_c is not None
        and inputs.latest_bedroom_temperature_c >= WARM_ROOM_C
    )
    warm_forecast = (
        inputs.overnight_low_c is not None and inputs.overnight_low_c >= WARM_OVERNIGHT_LOW_C
    )
    training_driver = next((d for d in measured if d.driver == "prev_day_training_load"), None)

    load_risk = training["late"] or training["high_intensity"] or training["big_load"]
    # Batch 249: a warm forecast is a forecast. It used to need a negative
    # coefficient on a bedroom or weather driver before the app would act on it,
    # which made a measured number wait on an unmeasured one.
    forecast_risk = warm_forecast
    room_risk = warm_room or forecast_risk
    protect = load_risk and (training_driver is not None or room_risk)
    watch = load_risk or room_risk

    if protect:
        tone = "protect"
        headline = _risk_headline(
            "Protect tonight after",
            training,
            warm_room=warm_room,
            warm_forecast=forecast_risk,
        )
        summary = _protect_summary(training, warm_room=warm_room, warm_forecast=forecast_risk)
    elif watch:
        tone = "watch"
        headline = _risk_headline(
            "Give tonight extra margin for",
            training,
            warm_room=warm_room,
            warm_forecast=forecast_risk,
        )
        summary = _watch_summary(training, warm_room=warm_room, warm_forecast=forecast_risk)
    else:
        tone = "routine"
        headline = "Tonight looks like a standard protocol night"
        summary = (
            "Today's training landed early enough and light enough that the usual sleep setup "
            "should be enough."
        )

    evidence = _evidence_lines(
        training,
        warm_room=warm_room,
        warm_forecast=forecast_risk,
        latest_bedroom_temperature_c=inputs.latest_bedroom_temperature_c,
        overnight_low_c=inputs.overnight_low_c,
    )[:3]
    # Batch 249: the named driver's interval and confounds travel on the far side
    # of the cap, for the same reason Batch 231 put the chronic card's confounds
    # there — a caveat that loses a truncation race is a caveat Mark never reads.
    evidence.extend(_driver_lines(measured))
    actions = _prep_actions(
        protocol,
        load_risk=load_risk,
        room_risk=room_risk,
        fan_auto_enabled=inputs.fan_auto_enabled,
    )
    return SleepProjectionResult(
        status="personalized",
        tone=tone,
        headline=headline,
        summary=summary,
        evidence=evidence,
        prep_actions=actions[:2],
        protocol=protocol,
    )


def _normalise_protocol(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "preCoolTemperatureC": raw.get("preCoolTemperatureC", 17),
        "coherenceBreathingTime": raw.get("coherenceBreathingTime", "20:00"),
        "latestSnackTime": raw.get("latestSnackTime", "21:30"),
        "sealTargetTime": raw.get("sealTargetTime", "22:00"),
        "bedtime": raw.get("bedtime", "23:15"),
    }


def _fallback_result(protocol: dict[str, Any]) -> SleepProjectionResult:
    return SleepProjectionResult(
        status="fallback",
        tone="routine",
        headline="Use the usual sleep protocol",
        summary=(
            "There is no training logged today to shape tonight's read, so the usual "
            "sleep protocol stands."
        ),
        evidence=[],
        prep_actions=_default_protocol_actions(protocol),
        protocol=protocol,
    )


def _default_protocol_actions(protocol: dict[str, Any]) -> list[str]:
    return [
        f"Pre-cool the bedroom toward {protocol['preCoolTemperatureC']}C.",
        (
            f"Breathing at {protocol['coherenceBreathingTime']}, snack by "
            f"{protocol['latestSnackTime']}, seal near {protocol['sealTargetTime']}, "
            f"bed {protocol['bedtime']}."
        ),
    ]


def _training_summary(training: list[TrainingSignal]) -> dict[str, Any]:
    total_load = sum(signal.training_load or 0.0 for signal in training)
    total_duration = sum(signal.duration_min or 0.0 for signal in training)
    latest_start = max(
        (signal.local_start for signal in training if signal.local_start), default=None
    )
    max_aerobic = max((signal.aerobic_training_effect or 0.0 for signal in training), default=0.0)
    max_anaerobic = max(
        (signal.anaerobic_training_effect or 0.0 for signal in training), default=0.0
    )
    late = latest_start is not None and latest_start.hour >= LATE_SESSION_HOUR
    high_intensity = max_aerobic >= HIGH_AEROBIC_EFFECT or max_anaerobic >= HIGH_ANAEROBIC_EFFECT
    big_load = total_load >= HIGH_TRAINING_LOAD or total_duration >= LONG_SESSION_MIN
    return {
        "count": len(training),
        "total_load": total_load,
        "total_duration": total_duration,
        "latest_start": latest_start,
        "late": late,
        "high_intensity": high_intensity,
        "big_load": big_load,
    }


def _risk_headline(
    prefix: str,
    training: dict[str, Any],
    *,
    warm_room: bool,
    warm_forecast: bool,
) -> str:
    drivers: list[str] = []
    if training["late"]:
        drivers.append("a late session")
    if training["high_intensity"]:
        drivers.append("a hard session")
    elif training["big_load"]:
        drivers.append("a bigger training load")
    if warm_room:
        drivers.append("a warm bedroom")
    elif warm_forecast:
        drivers.append("a warm overnight low")
    if not drivers:
        return prefix
    if len(drivers) == 1:
        joined = drivers[0]
    else:
        joined = f"{', '.join(drivers[:-1])} and {drivers[-1]}"
    return f"{prefix} {joined}"


def _protect_summary(training: dict[str, Any], *, warm_room: bool, warm_forecast: bool) -> str:
    bits: list[str] = []
    if training["late"]:
        bits.append("a late session")
    if training["high_intensity"]:
        bits.append("high intensity")
    if training["big_load"]:
        bits.append("a bigger load")
    if warm_room:
        bits.append("a warm room")
    elif warm_forecast:
        bits.append("a mild overnight forecast")
    joined = " + ".join(bits) if bits else "today's load"
    return f"{joined.capitalize()} may make sleep more fragile, so tonight is about reducing drift."


def _watch_summary(training: dict[str, Any], *, warm_room: bool, warm_forecast: bool) -> str:
    if warm_room:
        return "The bedroom is already near the disruption line, so keep the evening routine tight."
    if warm_forecast:
        return "The overnight forecast gives the room less natural cooling, so keep the setup tidy."
    if training["late"]:
        return "The session landed late enough that the wind-down deserves a little extra space."
    if training["high_intensity"] or training["big_load"]:
        return (
            "The training stimulus was meaningful, so protect recovery with a clean "
            "bedtime routine."
        )
    return "A small watch flag is present, but the standard routine should carry most of the load."


def _driver_lines(drivers: list[SleepDriverEvidence]) -> list[str]:
    """What the shared gate allows the app to say about a measured driver.

    An empty list is the common answer and prints nothing, rather than promoting
    the strongest of a weak field (Batch 249 / HS240-11).
    """
    if not drivers:
        return []
    strongest = drivers[0]
    label = _DRIVER_LABELS.get(strongest.driver, strongest.driver.replace("_", " "))
    lines = [
        strongest.summary
        or (
            f"Measured driver: {label} has tracked with lower sleep scores — "
            "an association in your own data, not a proven cause."
        )
    ]
    if strongest.evidence_sentence:
        lines.append(strongest.evidence_sentence)
    lines.extend(strongest.confounds)
    return lines


def _evidence_lines(
    training: dict[str, Any],
    *,
    warm_room: bool,
    warm_forecast: bool,
    latest_bedroom_temperature_c: float | None,
    overnight_low_c: float | None,
) -> list[str]:
    lines: list[str] = []
    training_bits: list[str] = []
    if training["late"] and isinstance(training["latest_start"], time):
        training_bits.append(f"latest session started {training['latest_start'].strftime('%H:%M')}")
    if training["big_load"]:
        training_bits.append("today's load/duration is above the evening margin")
    if training["high_intensity"]:
        training_bits.append("Training Effect points to a hard stimulus")
    if training_bits:
        lines.append("; ".join(training_bits) + ".")
    else:
        lines.append("Training landed early/light enough to avoid a load flag.")

    if warm_room and latest_bedroom_temperature_c is not None:
        lines.append(f"Bedroom is currently {latest_bedroom_temperature_c:.1f}C.")
    elif warm_forecast and overnight_low_c is not None:
        lines.append(f"Forecast overnight low is {overnight_low_c:.1f}C, so cooling may be slower.")
    return lines


def _prep_actions(
    protocol: dict[str, Any],
    *,
    load_risk: bool,
    room_risk: bool,
    fan_auto_enabled: bool,
) -> list[str]:
    actions: list[str] = []
    if room_risk and fan_auto_enabled:
        actions.append(
            "Let Auto manage the pre-cool; check Bedroom if the room is still warm near "
            f"{protocol['sealTargetTime']}."
        )
    elif room_risk:
        actions.append(
            f"Start the pre-cool earlier and seal the room by {protocol['sealTargetTime']}."
        )

    if load_risk:
        actions.append(
            f"Bring the wind-down forward: breathing at {protocol['coherenceBreathingTime']} "
            f"and snack finished by {protocol['latestSnackTime']}."
        )

    if not actions:
        actions.extend(_default_protocol_actions(protocol))
    return actions
