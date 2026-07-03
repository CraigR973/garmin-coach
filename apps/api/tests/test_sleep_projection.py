from __future__ import annotations

from datetime import time

from src.services.sleep_projection import (
    SleepDriverEvidence,
    SleepProjectionInputs,
    TrainingSignal,
    project_sleep,
)


def _driver(driver: str = "prev_day_training_load") -> SleepDriverEvidence:
    return SleepDriverEvidence(
        driver=driver,
        coefficient=-0.62,
        sample_count=14,
        summary="Nights after higher training load average lower sleep scores.",
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


def test_insufficient_driver_history_falls_back() -> None:
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
            sleep_drivers=[SleepDriverEvidence("prev_day_training_load", -0.8, 4)],
        )
    )

    assert result.status == "fallback"
    assert result.tone == "routine"
