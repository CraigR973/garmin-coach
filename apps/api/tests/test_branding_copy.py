from __future__ import annotations

from src.services import (
    brief_chat,
    handover,
    morning_analysis,
    post_flexibility_analysis,
    post_strength_analysis,
    post_walk_analysis,
    post_workout_analysis,
    reviews,
    trends,
)
from src.services.garmin_workout_export import build_garmin_workout
from src.services.workout_delivery import build_zwo_xml


def _ir() -> dict[str, object]:
    return {
        "name": "Tempo ride",
        "ftpWatts": 280,
        "totalDurationSec": 600,
        "steps": [
            {
                "label": "Tempo",
                "phase": "interval",
                "kind": "steady",
                "durationSec": 600,
                "powerStartPct": 90,
                "powerEndPct": 90,
            }
        ],
    }


def test_user_facing_prompts_use_checkmark_brand() -> None:
    prompts = (
        morning_analysis.SYSTEM_PROMPT,
        post_workout_analysis.SYSTEM_PROMPT,
        post_flexibility_analysis.SYSTEM_PROMPT,
        post_strength_analysis.SYSTEM_PROMPT,
        post_walk_analysis.SYSTEM_PROMPT,
        brief_chat.SYSTEM_PROMPT,
        reviews.SYSTEM_PROMPT,
        trends.TREND_SYSTEM_PROMPT,
        handover.HANDOVER_SYSTEM_PROMPT,
    )
    for prompt in prompts:
        assert "CheckMark" in prompt
        assert "Garmin Coach" not in prompt


def test_export_labels_use_checkmark_brand() -> None:
    garmin = build_garmin_workout(_ir())
    assert garmin["description"] == "CheckMark outdoor ride"

    zwo = build_zwo_xml(_ir())
    assert "<author>CheckMark</author>" in zwo
