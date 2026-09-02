from __future__ import annotations

from src.services.morning_output_contract import (
    missing_morning_output_sections,
    morning_output_contract_packet,
    morning_output_contract_prompt,
)


def _september_packet() -> dict[str, object]:
    """The output-relevant shape of the stored 2026-09-01 packet."""

    return {
        "sleep": {
            "durationMin": 462,
            "remSleepMin": 34,
            "deepSleepMin": 130,
            "lightSleepMin": 298,
            "awakeSleepMin": 21,
        },
        "metricsVsBaselines": [{"metricKey": "age_adjusted_sleep_score"}],
        "environment": {"thermalReview": {"indoorPeakC": 18.66}},
        "experimentLoop": {
            "experiments": [
                {
                    "title": "REM intervention rotation",
                    "evaluation": {"recommendation": "inconclusive"},
                }
            ]
        },
        "chronicSuggestions": {
            "items": [
                {
                    "title": "Protect REM consistency",
                    "actions": [
                        "Hold the room cool into the early morning.",
                        "Skip early alarms after a late night.",
                    ],
                }
            ]
        },
        "verdict": {"status": "Green"},
    }


def test_contract_is_derived_from_the_sections_the_packet_carries() -> None:
    contract = morning_output_contract_packet(_september_packet())

    assert [section["id"] for section in contract] == [
        "sleep_and_recovery",
        "metrics_vs_baselines",
        "thermal_environment",
        "experiment_update",
        "chronic_pattern_actions",
        "todays_verdict",
    ]
    sleep_instruction = contract[0]["instruction"]
    assert "REM" in sleep_instruction
    assert "deep sleep" in sleep_instruction
    assert "light sleep" in sleep_instruction
    assert "awake time" in sleep_instruction
    assert "every action" in contract[4]["instruction"]


def test_contract_omits_sections_the_packet_does_not_carry() -> None:
    packet = _september_packet()
    packet["environment"] = {"thermalReview": None}
    packet["experimentLoop"] = {"experiments": []}
    packet["chronicSuggestions"] = {"items": []}

    contract = morning_output_contract_packet(packet)

    assert [section["id"] for section in contract] == [
        "sleep_and_recovery",
        "metrics_vs_baselines",
        "todays_verdict",
    ]


def test_prompt_requires_exact_dynamic_headings_and_the_carried_actions() -> None:
    prompt = morning_output_contract_prompt(_september_packet())

    assert "using each exact `##` heading" in prompt
    assert "`## Experiment update`" in prompt
    assert "`## Chronic pattern actions`" in prompt
    assert "include every action it carries" in prompt


def test_structural_guard_catches_the_sections_sonnet_5_omitted_on_september_first() -> None:
    old_output = """# Tuesday 1 September 2026 — Morning Read

**Sleep summary:** 462 minutes asleep.

## Metrics vs. Baselines
The measurements were near baseline.

## Thermal / Environment Review
The room stayed cool.

## Today's Verdict: 🟢 Green
Proceed with the planned workout.
"""

    assert missing_morning_output_sections(_september_packet(), old_output) == (
        "sleep_and_recovery",
        "experiment_update",
        "chronic_pattern_actions",
    )


def test_structural_guard_passes_a_complete_packet_driven_read() -> None:
    complete_output = """## Sleep and recovery
462 minutes asleep: 34 REM, 130 deep sleep, 298 light sleep, 21 awake.

## Metrics vs baselines
The measurements were near baseline.

## Thermal / environment
The room stayed cool.

## Experiment update
The REM intervention comparison remains inconclusive.

## Chronic pattern actions
Hold the room cool and protect the final sleep cycle.

## Today's verdict: Green
Proceed with the planned workout.
"""

    assert missing_morning_output_sections(_september_packet(), complete_output) == ()
