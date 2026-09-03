from __future__ import annotations

from datetime import time

from src.services.sleep_projection import (
    SleepDriverEvidence,
    SleepProjectionInputs,
    TrainingSignal,
    project_sleep,
)


def _driver(driver: str = "prev_day_training_load") -> SleepDriverEvidence:
    """A driver that has *already* passed ``driver_levers``' gate (Batch 249).

    This module no longer judges drivers at all — the context service hands it
    only what the shared gate allowed — so a fixture here means "one survived",
    and an empty list means the usual answer: none did.
    """
    return SleepDriverEvidence(
        driver=driver,
        coefficient=-0.62,
        sample_count=14,
        summary="Nights after higher training load average lower sleep scores.",
        evidence_sentence=(
            "Measured over 14 nights: the link is 0.62 on a 0-1 scale, and the range "
            "the data still allows (0.19 to 0.86) stays on one side of no effect."
        ),
    )


def test_hard_late_warm_day_projects_protective_wind_down() -> None:
    result = project_sleep(
        SleepProjectionInputs(
            training=[
                TrainingSignal(
                    name="VO2 ride",
                    activity_type="indoor_cycling",
                    local_start=time(18, 5),
                    duration_min=72,
                    training_load=145,
                    aerobic_training_effect=4.2,
                    anaerobic_training_effect=2.3,
                )
            ],
            sleep_drivers=[_driver(), _driver("bedroom_warning_minutes")],
            latest_bedroom_temperature_c=20.1,
            overnight_low_c=15.0,
            fan_auto_enabled=True,
        )
    )

    assert result.status == "personalized"
    assert result.tone == "protect"
    assert "late session" in result.headline
    assert "hard session" in result.headline
    assert "warm bedroom" in result.headline
    assert "score prediction" not in f"{result.headline} {result.summary}".lower()
    assert any("Auto manage" in action for action in result.prep_actions)
    assert any("breathing" in action for action in result.prep_actions)
    assert any("18:05" in line for line in result.evidence)


def test_easy_early_training_with_drivers_stays_routine() -> None:
    result = project_sleep(
        SleepProjectionInputs(
            training=[
                TrainingSignal(
                    name="Easy spin",
                    activity_type="indoor_cycling",
                    local_start=time(9, 0),
                    duration_min=35,
                    training_load=28,
                    aerobic_training_effect=1.6,
                )
            ],
            sleep_drivers=[_driver()],
            latest_bedroom_temperature_c=17.8,
            overnight_low_c=9.0,
            fan_auto_enabled=True,
        )
    )

    assert result.status == "personalized"
    assert result.tone == "routine"
    assert result.prep_actions[0].startswith("Pre-cool")
    assert any("early/light" in line for line in result.evidence)


def test_a_warm_forecast_no_longer_waits_for_a_correlation_to_permit_it() -> None:
    """Batch 249 reversed this test, deliberately.

    It used to assert that a 15C overnight low went unmentioned unless some
    bedroom or weather driver happened to carry a negative coefficient. That made
    a measured forecast wait on an unmeasured association, and once the shared
    gate is applied almost nothing carries one — so the app would have gone quiet
    about the room on exactly the nights it should speak. Direct observation was
    never the unreliable part.
    """
    result = project_sleep(
        SleepProjectionInputs(
            training=[
                TrainingSignal(
                    name="Hard ride",
                    activity_type="indoor_cycling",
                    local_start=time(17, 30),
                    duration_min=70,
                    training_load=140,
                    aerobic_training_effect=4.0,
                )
            ],
            sleep_drivers=[],
            latest_bedroom_temperature_c=17.8,
            overnight_low_c=15.0,
        )
    )

    assert result.tone == "protect"
    assert "warm overnight low" in result.headline
    assert any("15.0C" in line for line in result.evidence)
    # And with no driver through the gate, no measured driver is claimed.
    assert not any("Measured driver" in line for line in result.evidence)


def test_rest_day_falls_back_to_static_protocol() -> None:
    result = project_sleep(
        SleepProjectionInputs(
            training=[],
            sleep_drivers=[_driver()],
            sleep_protocol={"preCoolTemperatureC": 16.5, "bedtime": "23:00"},
        )
    )

    assert result.status == "fallback"
    assert result.evidence == []
    assert result.prep_actions == [
        "Pre-cool the bedroom toward 16.5C.",
        "Breathing at 20:00, snack by 21:30, seal near 22:00, bed 23:00.",
    ]


def test_no_driver_through_the_gate_still_reads_today_training() -> None:
    """Batch 249: the fallback is about training, not about a surviving correlation.

    Requiring a named driver here would have sent almost every night to the
    generic protocol once the shared gate was applied, which is a worse read than
    the one a late, hard session supports on its own.
    """
    result = project_sleep(
        SleepProjectionInputs(
            training=[
                TrainingSignal(
                    name="Late ride",
                    activity_type="indoor_cycling",
                    local_start=time(18, 0),
                    training_load=150,
                    aerobic_training_effect=4.0,
                )
            ],
            sleep_drivers=[],
        )
    )

    assert result.status == "personalized"
    assert result.tone == "watch"
    assert not any("Measured driver" in line for line in result.evidence)
    assert any("18:00" in line for line in result.evidence)


def test_a_gated_driver_brings_its_interval_and_confounds_past_the_cap() -> None:
    """The caveat must not lose a truncation race (Batch 231's rule, Batch 249's numbers)."""
    result = project_sleep(
        SleepProjectionInputs(
            training=[
                TrainingSignal(
                    name="Late hard ride",
                    activity_type="indoor_cycling",
                    local_start=time(18, 0),
                    duration_min=95,
                    training_load=150,
                    aerobic_training_effect=4.0,
                )
            ],
            sleep_drivers=[
                SleepDriverEvidence(
                    driver="bedroom_fan_ran_minutes",
                    coefficient=-0.41,
                    sample_count=55,
                    summary="Nights the fan ran average 10.1 min lower REM sleep.",
                    evidence_sentence="Measured over 55 nights: the link is 0.41 on a 0-1 scale.",
                    confounds=("The fan runs because the room is already warm.",),
                )
            ],
            latest_bedroom_temperature_c=20.4,
            overnight_low_c=15.0,
        )
    )

    assert any("55 nights" in line for line in result.evidence)
    assert any("already warm" in line for line in result.evidence)


def test_a_rest_day_is_the_only_fallback() -> None:
    result = project_sleep(SleepProjectionInputs(training=[], sleep_drivers=[]))
    assert result.status == "fallback"
    assert result.tone == "routine"
    assert "no training logged today" in result.summary
