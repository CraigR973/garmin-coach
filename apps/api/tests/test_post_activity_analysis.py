from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.coaching import Activity
from src.services.post_activity_analysis import (
    generate_post_activity_read,
    post_activity_kind,
)
from src.services.post_flexibility_analysis import SYSTEM_PROMPT as FLEX_PROMPT
from src.services.post_strength_analysis import SYSTEM_PROMPT as STRENGTH_PROMPT
from src.services.post_walk_analysis import SYSTEM_PROMPT as WALK_PROMPT
from src.services.post_workout_analysis import SYSTEM_PROMPT as RIDE_PROMPT


def _activity(
    activity_type: str,
    name: str,
    *,
    duration_sec: float = 3600,
    distance_m: float = 5_000,
    excluded: bool = False,
) -> MagicMock:
    activity = MagicMock(spec=Activity)
    activity.activity_type = activity_type
    activity.activity_name = name
    activity.duration_sec = duration_sec
    activity.distance_m = distance_m
    activity.exclude_from_recovery = excluded
    return activity


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        (_activity("indoor_cycling", "Indoor ride"), "ride"),
        (_activity("strength_training", "Dumbbells", excluded=True), "strength"),
        (_activity("other", "Morning mobility"), "flexibility"),
        (_activity("walking", "Lunch walk"), "walk"),
    ],
)
def test_post_activity_kind_dispatches_all_four_readers(activity: MagicMock, expected: str) -> None:
    assert post_activity_kind(activity) == expected


@pytest.mark.asyncio
async def test_checkin_dispatch_forces_the_matching_reader_inline() -> None:
    activity = _activity("other", "Morning mobility")
    expected = MagicMock()
    service = MagicMock()
    service.generate_and_store = AsyncMock(return_value=expected)

    with patch(
        "src.services.post_activity_analysis.PostFlexibilityAnalysisService",
        return_value=service,
    ):
        kind, result = await generate_post_activity_read(
            MagicMock(), MagicMock(), activity, force=True
        )

    assert kind == "flexibility"
    assert result is expected
    service.generate_and_store.assert_awaited_once()
    assert service.generate_and_store.await_args.kwargs["force"] is True


def test_every_post_activity_prompt_answers_checkin_questions() -> None:
    for prompt in (RIDE_PROMPT, STRENGTH_PROMPT, FLEX_PROMPT, WALK_PROMPT):
        assert "question" in prompt
        assert "supplied packet" in prompt
