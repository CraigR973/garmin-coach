"""The sections every coach surface needs, in one definition (Batch 256).

Four categories bear on almost any question Mark asks — his own rules, today's
readiness, last night's bedroom, and his personal bands — and until this batch
they existed only inside a generated read's frozen ``context_packet``. So
coverage was uneven in a way nothing surfaced: on his morning brief the coach
held all four; asked from Home it held none of them, and could not answer a
question about his own sleep protocol, his readiness, or his bedroom
temperature. Mark's 2026-09-05 conversation was exactly that shape — he asked
about REM in an explicitly thermal context and the coach had no ``environment``,
no ``dailyMetrics`` and no ``knowledgeBase`` in front of it.

The builders were already written; they just lived inside
:mod:`src.services.morning_analysis`, whose service the chat path has no
business importing. They move here unchanged so **one** definition serves both,
following the same pattern :mod:`src.services.personal_baselines` and
:mod:`src.services.morning_verdict` already set: public names here, private
aliases re-imported there to preserve the established test/import surface.

Two notes that are load-bearing rather than incidental:

* **The chat block builds these from live rows, not from a copy of a read's
  packet** — which is strictly better than the copy, because the knowledge base
  is edited between reads (the seed fills only *missing* sections; production is
  changed by read-modify-write or the wholesale admin PUT), so a packet copy can
  state a rule Mark has since changed.
* **:func:`knowledge_base_section` carries ``learnedContext``**, which is
  confirmed user-authored memory presented as quoted, untrusted data. Every
  prompt that receives it must also carry
  :data:`~src.services.learned_context.LEARNED_CONTEXT_PROMPT_GUARDRAIL`;
  ``test_learning_memory_integrity`` enumerates them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from src.models.coaching import (
    DailyMetric,
    KnowledgeBase,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.services.coach_policy import source_basis
from src.services.learned_context import learned_context_packet
from src.services.personal_baselines import serialize_training_schedule


def _dt(value: datetime | None) -> str | None:
    """Stamp a UTC instant the way every packet in the app stamps one.

    A third copy of the same three lines (``morning_analysis`` and
    ``chat_context`` each hold one). Consolidating them means touching every
    packet builder in the app, so it is left as its own cleanup rather than
    smuggled into this move.
    """
    if value is None:
        return None
    return value.isoformat() + ("" if value.tzinfo is not None else "Z")


def knowledge_base_packet(row: KnowledgeBase) -> dict[str, Any]:
    """One stored section, with a basis Mark can be told (Batch 217).

    ``source`` stays for the app's own consumers, but it is an internal token
    and the coach is forbidden from repeating it. On 2026-08-20 Mark asked what
    the basis of his 23:15 bedtime target was; this row already carried
    ``batch_5_seed`` and the coach answered that it would be speculating. The
    ``basis`` key is that same fact in words it is allowed to say. It is omitted
    rather than guessed when the token is unrecognised.
    """
    packet: dict[str, Any] = {
        "section": row.section,
        "version": row.version,
        "source": row.source,
        "content": row.content,
    }
    basis = source_basis(row.source)
    if basis is not None:
        packet["basis"] = basis
    return packet


def data_quality_guardrails(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules", {})
    rules = section.get("rules") if isinstance(section, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_mapping(value: Any) -> dict[str, Any]:
    """First dict value in a device-keyed map (e.g. latestTrainingStatusData)."""
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, dict):
                return item
    return {}


def coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def training_and_activity_fields(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Surface load + daily-activity context already captured in ``raw_payload``.

    The daily sync stores the full Garmin ``training_status`` and ``stats``
    responses but only promotes a few fields to columns. This reads the rest
    (chronic load + acute:chronic ratio, training-load balance, steps, intensity
    minutes) so the morning packet/prompt can use them. Read-only — no new Garmin
    call, no migration; every field degrades to ``None`` when absent.
    """
    ts = as_mapping(raw_payload.get("training_status"))
    status_node = first_mapping(
        as_mapping(ts.get("mostRecentTrainingStatus")).get("latestTrainingStatusData")
    )
    acute_dto = as_mapping(status_node.get("acuteTrainingLoadDTO"))
    acute = coerce_int(acute_dto.get("dailyTrainingLoadAcute"))
    chronic = coerce_int(acute_dto.get("dailyTrainingLoadChronic"))
    balance_node = first_mapping(
        as_mapping(ts.get("mostRecentTrainingLoadBalance")).get("metricsTrainingLoadBalanceDTOMap")
    )
    balance_phrase = balance_node.get("trainingBalanceFeedbackPhrase")

    stats = as_mapping(raw_payload.get("stats"))
    moderate = coerce_int(stats.get("moderateIntensityMinutes"))
    vigorous = coerce_int(stats.get("vigorousIntensityMinutes"))
    intensity_minutes = (
        (moderate or 0) + (vigorous or 0) if moderate is not None or vigorous is not None else None
    )

    return {
        "chronicTrainingLoad": chronic,
        "acuteChronicLoadRatio": round(acute / chronic, 2) if acute and chronic else None,
        "trainingLoadBalance": balance_phrase if isinstance(balance_phrase, str) else None,
        "steps": coerce_int(stats.get("totalSteps")),
        "intensityMinutes": intensity_minutes,
    }


def daily_metric_packet(
    row: DailyMetric | None,
    *,
    vo2max: float | None = None,
    vo2max_as_of_date: date | None = None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    resolved_vo2max = row.vo2max
    resolved_vo2max_as_of = row.calendar_date if row.vo2max is not None else None
    if resolved_vo2max is None and vo2max is not None:
        resolved_vo2max, resolved_vo2max_as_of = vo2max, vo2max_as_of_date
    packet = {
        "calendarDate": row.calendar_date.isoformat(),
        "recordedAtUtc": _dt(row.recorded_at_utc),
        "readinessScore": row.readiness_score,
        "readinessLevel": row.readiness_level,
        "readinessSleepScore": row.readiness_sleep_score,
        "recoveryTimeMin": row.recovery_time_min,
        "acuteLoad": row.acute_load,
        "trainingStatus": row.training_status,
        "hrvLastNightAvgMs": row.hrv_last_night_avg_ms,
        "hrvWeeklyAvgMs": row.hrv_weekly_avg_ms,
        "hrvStatus": row.hrv_status,
        "hrvBaselineLowMs": row.hrv_baseline_low_ms,
        "hrvBaselineHighMs": row.hrv_baseline_high_ms,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
        "stressAvg": row.stress_avg,
        "bodyBatteryCharged": row.body_battery_charged,
        "bodyBatteryDrained": row.body_battery_drained,
        "bodyBatteryEnd": row.body_battery_end,
        "weightKg": row.weight_kg,
        # Batch 225: this row is the wake observation, and Garmin writes VO2 max
        # only after the day's activity — so its own column is null on every
        # morning brief, which is what left `dailyMetrics.vo2max` null from July
        # onward. Prefer the row's own reading where it has one (true of this
        # date by construction); otherwise carry the resolved live value and say
        # which day it was measured, the convention `athleteProfile` already
        # uses (Batch 177). Never present a carried figure without its date.
        "vo2max": resolved_vo2max,
        "vo2maxAsOfDate": resolved_vo2max_as_of.isoformat() if resolved_vo2max_as_of else None,
    }
    packet.update(training_and_activity_fields(row.raw_payload or {}))
    return packet


def weather_packet(row: WeatherDaily | None) -> dict[str, Any] | None:
    if row is None:
        return None
    # Batch 253 (DS237-09): the second copy of the same coordinates in the same
    # request. The weather is already resolved to numbers the model reads.
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "source": row.source,
        "tempHighC": row.temp_high_c,
        "tempLowC": row.temp_low_c,
        "overnightLowC": row.overnight_low_c,
        "overnightWindMaxMph": row.overnight_wind_max_mph,
        "overnightWindGustMph": row.overnight_wind_gust_mph,
        "overnightWindDirectionDeg": row.overnight_wind_direction_deg,
        "overnightRelativeHumidityMeanPct": row.overnight_relative_humidity_mean_pct,
        "precipitationMm": row.precipitation_mm,
        "sunriseUtc": _dt(row.sunrise_utc),
        "sunsetUtc": _dt(row.sunset_utc),
    }


def thermal_review(
    temperature_rows: Sequence[TemperatureReading],
    weather: WeatherDaily | None,
    knowledge_base: Mapping[str, Any],
    *,
    sleep: Sleep | None = None,
) -> dict[str, Any]:
    sleep_protocol = knowledge_base.get("sleep_protocol", {})
    threshold_low = 19.5
    threshold_high = 20.0
    target_precool = 17.0
    if isinstance(sleep_protocol, dict):
        threshold = sleep_protocol.get("thermalDisruptionThresholdC")
        if isinstance(threshold, dict):
            low = threshold.get("low")
            high = threshold.get("high")
            if isinstance(low, int | float):
                threshold_low = float(low)
            if isinstance(high, int | float):
                threshold_high = float(high)
        precool = sleep_protocol.get("preCoolTemperatureC")
        if isinstance(precool, int | float):
            target_precool = float(precool)

    all_rows = sorted(temperature_rows, key=lambda row: row.captured_at_utc)
    sleep_start = sleep.sleep_start_utc if sleep is not None else None
    sleep_end = sleep.sleep_end_utc if sleep is not None else None
    has_sleep_window = sleep_start is not None and sleep_end is not None and sleep_end > sleep_start
    if sleep_start is not None and sleep_end is not None and sleep_end > sleep_start:
        asleep_rows = [row for row in all_rows if sleep_start <= row.captured_at_utc <= sleep_end]
        pre_cool_rows = [row for row in all_rows if row.captured_at_utc <= sleep_start]
    else:
        asleep_rows = all_rows
        pre_cool_rows = []
    values = [float(row.temperature_c) for row in asleep_rows if row.temperature_c is not None]
    peak = max(values) if values else None
    low = min(values) if values else None
    last = values[-1] if values else None

    pre_cool_values = [
        float(row.temperature_c) for row in pre_cool_rows if row.temperature_c is not None
    ]
    if pre_cool_values:
        pre_cool_low = min(pre_cool_values)
        sleep_onset = pre_cool_values[-1]
        pre_cool_drop = max(0.0, pre_cool_values[0] - pre_cool_low)
    else:
        pre_cool_low = None
        sleep_onset = None
        pre_cool_drop = None
    # Credit either a material observed drop or a pre-bed low already below the
    # disruption threshold. The latter matters when the shared 21:30 chart
    # window begins after the largest part of an earlier-evening cool-down.
    pre_cool_credited = (pre_cool_low is not None and pre_cool_low <= threshold_low) or (
        pre_cool_drop is not None and pre_cool_drop >= 1.0
    )
    flags: list[str] = []
    if peak is not None and peak >= threshold_high:
        flags.append("thermal_disruption_likely")
    elif peak is not None and peak >= threshold_low:
        flags.append("thermal_disruption_watch")
    if pre_cool_credited:
        flags.append("precool_credited")
    elif pre_cool_low is not None and pre_cool_low > target_precool + 1.0:
        flags.append("precool_target_missed")
    if weather and weather.overnight_wind_gust_mph and weather.overnight_wind_gust_mph >= 30:
        flags.append("wind_disruption_watch")

    return {
        "sampleCount": len(values),
        "windowSource": "sleep" if has_sleep_window else "night_fallback",
        "indoorPeakC": peak,
        "indoorLowC": low,
        "indoorLastC": last,
        "preCoolLowC": pre_cool_low,
        "sleepOnsetC": sleep_onset,
        "preCoolDropC": pre_cool_drop,
        "targetPreCoolC": target_precool,
        "disruptionThresholdC": {"low": threshold_low, "high": threshold_high},
        "overnightWeatherLowC": weather.overnight_low_c if weather else None,
        "overnightWindMaxMph": weather.overnight_wind_max_mph if weather else None,
        "overnightWindGustMph": weather.overnight_wind_gust_mph if weather else None,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Composed sections (Batch 256) — the shape both the morning packet and the
# chat block use, so the two cannot drift apart.
# ---------------------------------------------------------------------------


def knowledge_base_section(rows: Sequence[KnowledgeBase]) -> dict[str, Any]:
    """Mark's profile, rules and learned context as the coach is given them.

    ``sections`` is every active row verbatim; the named nodes beside it are the
    ones prompts and output contracts reference by name, so they are resolved
    once here rather than at each call site.
    """
    knowledge_base = {row.section: row.content for row in rows}
    return {
        "sections": [knowledge_base_packet(row) for row in rows],
        "dataQualityGuardrails": data_quality_guardrails(knowledge_base),
        "sleepProtocol": knowledge_base.get("sleep_protocol", {}),
        "trainingSchedule": serialize_training_schedule(knowledge_base),
        "activeHypotheses": knowledge_base.get("active_hypotheses", {}),
        "learnedContext": learned_context_packet(knowledge_base),
    }


def environment_section(
    *,
    thermal_review: Mapping[str, Any] | None,
    weather: WeatherDaily | None,
) -> dict[str, Any]:
    """Last night's bedroom and the overnight weather it happened in.

    ``thermal_review`` is passed in rather than computed because whether there
    *is* one is a caller's decision: inside a holiday window the bedroom is not
    being slept in, so there is nothing to review (Batch 113, #186).
    """
    return {
        "thermalReview": dict(thermal_review) if thermal_review is not None else None,
        "weather": weather_packet(weather),
    }
