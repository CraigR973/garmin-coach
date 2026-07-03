from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

MIN_DRIVER_SAMPLES = 8
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
    driver: str
    coefficient: float
    sample_count: int
    summary: str | None = None


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
    "daytime_stress_avg": "daytime stress",
    "resting_heart_rate_bpm": "resting heart rate",
    "sleep_stress_avg": "sleep stress",
}


def project_sleep(inputs: SleepProjectionInputs) -> SleepProjectionResult:
    protocol = _normalise_protocol(inputs.sleep_protocol)
    measured = [
        driver for driver in inputs.sleep_drivers if driver.sample_count >= MIN_DRIVER_SAMPLES
    ]
    if not inputs.training or not measured:
        return _fallback_result(protocol)

    training = _training_summary(inputs.training)
    warm_room = (
        inputs.latest_bedroom_temperature_c is not None
        and inputs.latest_bedroom_temperature_c >= WARM_ROOM_C
    )
    warm_forecast = (
        inputs.overnight_low_c is not None and inputs.overnight_low_c >= WARM_OVERNIGHT_LOW_C
    )
    risk_drivers = _risk_drivers(measured)
    training_driver = next((d for d in risk_drivers if d.driver == "prev_day_training_load"), None)
    bedroom_driver = next((d for d in risk_drivers if d.driver.startswith("bedroom_")), None)
    weather_driver = next((d for d in risk_drivers if d.driver == "overnight_low_c"), None)

    load_risk = training["late"] or training["high_intensity"] or training["big_load"]
    room_risk = warm_room or (
        warm_forecast and (bedroom_driver is not None or weather_driver is not None)
    )
    protect = load_risk and (training_driver is not None or room_risk)
    watch = load_risk or room_risk

    if protect:
        tone = "protect"
        headline = "Protect tonight's wind-down"
        summary = _protect_summary(training, warm_room=warm_room, warm_forecast=warm_forecast)
    elif watch:
        tone = "watch"
        headline = "Give tonight a little extra margin"
        summary = _watch_summary(training, warm_room=warm_room, warm_forecast=warm_forecast)
    else:
        tone = "routine"
        headline = "Tonight looks like a standard protocol night"
        summary = (
            "Today's training landed early enough and light enough that the usual sleep setup "
            "should be enough."
        )

    evidence = _evidence_lines(
        training,
        measured,
        warm_room=warm_room,
        warm_forecast=warm_forecast,
        latest_bedroom_temperature_c=inputs.latest_bedroom_temperature_c,
        overnight_low_c=inputs.overnight_low_c,
    )
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
        evidence=evidence[:3],
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
            "There is not enough personal signal from today's training and Mark's measured "
            "sleep drivers to change the plan."
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


def _risk_drivers(drivers: list[SleepDriverEvidence]) -> list[SleepDriverEvidence]:
    return [driver for driver in drivers if driver.coefficient < 0]


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


def _evidence_lines(
    training: dict[str, Any],
    drivers: list[SleepDriverEvidence],
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

    strongest = drivers[0]
    label = _DRIVER_LABELS.get(strongest.driver, strongest.driver.replace("_", " "))
    direction = "lower sleep scores" if strongest.coefficient < 0 else "better sleep scores"
    if strongest.summary:
        lines.append(strongest.summary)
    else:
        lines.append(f"Measured driver: {label} has tracked with {direction}.")

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
