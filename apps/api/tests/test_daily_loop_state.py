"""Batch 48 — pure tests for the explicit daily/block loop-state model."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from src.services.daily_loop_state import (
    LoopState,
    derive_block_phase,
    derive_day_phase,
    describe_loop_state,
    is_block_boundary,
    is_evening,
    next_action,
)


class TestDayPhase:
    def test_pre_training_when_planned_work_not_done(self) -> None:
        assert (
            derive_day_phase(has_post_analysis=False, has_planned_workout=True, is_evening=False)
            == "pre_training"
        )

    def test_rest_day_when_nothing_planned(self) -> None:
        assert (
            derive_day_phase(has_post_analysis=False, has_planned_workout=False, is_evening=False)
            == "rest_day"
        )

    def test_post_training_off_any_completed_read(self) -> None:
        # `has_post_analysis` is the OR of ride/strength/flexibility/walk — a
        # strength-only day advances just like a ride day (the Batch 48 fix).
        assert (
            derive_day_phase(has_post_analysis=True, has_planned_workout=True, is_evening=False)
            == "post_training"
        )

    def test_post_training_without_a_planned_workout(self) -> None:
        # An unplanned session still advances the day past pre_training.
        assert (
            derive_day_phase(has_post_analysis=True, has_planned_workout=False, is_evening=False)
            == "post_training"
        )

    @pytest.mark.parametrize("has_post", [True, False])
    @pytest.mark.parametrize("has_planned", [True, False])
    def test_evening_wins_as_wind_down(self, has_post: bool, has_planned: bool) -> None:
        assert (
            derive_day_phase(
                has_post_analysis=has_post,
                has_planned_workout=has_planned,
                is_evening=True,
            )
            == "wind_down"
        )


class TestIsEvening:
    def test_boundary_at_evening_hour(self) -> None:
        assert is_evening(time(19, 59)) is False
        assert is_evening(time(20, 0)) is True
        assert is_evening(time(23, 30)) is True
        assert is_evening(time(6, 0)) is False

    def test_accepts_a_datetime(self) -> None:
        assert is_evening(datetime(2026, 6, 20, 20, 30)) is True
        assert is_evening(datetime(2026, 6, 20, 7, 0)) is False


class TestBlockPhase:
    @pytest.mark.parametrize(
        ("block_type", "block_name", "expected"),
        [
            ("build", None, "build"),
            (None, "Week 5 Build 2", "build"),
            (None, "Base progression", "build"),
            ("recovery", None, "recovery"),
            (None, "Week 3 Recovery", "recovery"),
            (None, "Deload week", "recovery"),
            (None, "Week 12 Taper", "taper"),
            (None, "Week 13 Consolidation", "consolidation"),
            ("transition", None, "transition"),
            (None, "Off-season transition", "transition"),
        ],
    )
    def test_classifies_from_type_or_name(
        self, block_type: str | None, block_name: str | None, expected: str
    ) -> None:
        assert derive_block_phase(block_type=block_type, block_name=block_name) == expected

    def test_unknown_or_absent_block_is_none(self) -> None:
        assert derive_block_phase(block_type=None, block_name=None) is None
        assert derive_block_phase(block_type="", block_name="   ") is None
        assert derive_block_phase(block_type=None, block_name="Mystery block") is None


class TestBlockBoundary:
    def test_consolidation_is_the_boundary(self) -> None:
        assert is_block_boundary("consolidation") is True

    @pytest.mark.parametrize("phase", ["build", "recovery", "taper", "transition", None])
    def test_other_phases_are_not(self, phase: str | None) -> None:
        assert is_block_boundary(phase) is False  # type: ignore[arg-type]


class TestNextAction:
    @pytest.mark.parametrize(
        ("day_phase", "expected"),
        [
            ("wind_down", "wind_down"),
            ("post_training", "review_session"),
            ("rest_day", "rest"),
            ("pre_training", "await_training"),
        ],
    )
    def test_maps_day_phase_to_next_action(self, day_phase: str, expected: str) -> None:
        assert next_action(day_phase) == expected  # type: ignore[arg-type]


class TestDescribeLoopState:
    def test_strength_only_day_advances_and_asks_for_a_review(self) -> None:
        state = describe_loop_state(
            has_post_analysis=True,
            has_planned_workout=True,
            is_evening=False,
            block_type=None,
            block_name="Week 5 Build 2",
        )
        assert state == LoopState(
            day_phase="post_training",
            block_phase="build",
            next_action="review_session",
            at_block_boundary=False,
        )

    def test_consolidation_week_flags_the_block_boundary(self) -> None:
        state = describe_loop_state(
            has_post_analysis=False,
            has_planned_workout=True,
            is_evening=False,
            block_name="Week 13 Consolidation",
        )
        assert state.block_phase == "consolidation"
        assert state.at_block_boundary is True
        assert state.day_phase == "pre_training"

    def test_to_dict_is_camel_case(self) -> None:
        state = describe_loop_state(
            has_post_analysis=True,
            has_planned_workout=False,
            is_evening=True,
            block_name="Week 3 Recovery",
        )
        assert state.to_dict() == {
            "dayPhase": "wind_down",
            "blockPhase": "recovery",
            "nextAction": "wind_down",
            "atBlockBoundary": False,
        }
