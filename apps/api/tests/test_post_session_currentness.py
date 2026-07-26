"""Batch 159: prompt + input currentness for non-ride post-session reads."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pytest

from src.config import settings
from src.models.coaching import Analysis, ManualEntry, PostActivityGenerationStatus
from src.services.post_activity_state import effective_generation_state
from src.services.post_flexibility_analysis import (
    PROMPT_VERSION as FLEXIBILITY_PROMPT_VERSION,
)
from src.services.post_flexibility_analysis import (
    _analysis_covers_activity_checkin as flexibility_is_current,
)
from src.services.post_strength_analysis import PROMPT_VERSION as STRENGTH_PROMPT_VERSION
from src.services.post_strength_analysis import (
    _analysis_covers_activity_checkin as strength_is_current,
)
from src.services.post_walk_analysis import PROMPT_VERSION as WALK_PROMPT_VERSION
from src.services.post_walk_analysis import (
    _analysis_covers_activity_checkin as walk_is_current,
)

CurrentnessCheck = Callable[[Analysis, ManualEntry | None], bool]


def _analysis(*, prompt_version: str, entry_at_utc: datetime | None) -> Analysis:
    return Analysis(
        user_id=uuid.uuid4(),
        activity_id=uuid.uuid4(),
        analysis_type="post_test",
        subject_date=date(2026, 7, 26),
        generated_at_utc=datetime(2026, 7, 26, 10, 0),
        prompt_version=prompt_version,
        context_packet={
            "activityCheckIn": (
                {"entryAtUtc": entry_at_utc.isoformat() + "Z"} if entry_at_utc is not None else None
            )
        },
        output_markdown="Read.",
        raw_response={},
    )


def _checkin(entry_at_utc: datetime) -> ManualEntry:
    return ManualEntry(
        user_id=uuid.uuid4(),
        activity_id=uuid.uuid4(),
        entry_date=entry_at_utc.date(),
        entry_at_utc=entry_at_utc,
    )


@pytest.mark.parametrize(
    ("is_current", "prompt_version"),
    [
        (strength_is_current, STRENGTH_PROMPT_VERSION),
        (flexibility_is_current, FLEXIBILITY_PROMPT_VERSION),
        (walk_is_current, WALK_PROMPT_VERSION),
    ],
)
def test_non_ride_currentness_requires_live_prompt_and_latest_checkin(
    is_current: CurrentnessCheck,
    prompt_version: str,
) -> None:
    first_time = datetime(2026, 7, 26, 9, 0)
    changed_time = datetime(2026, 7, 26, 9, 5)
    stored = _analysis(prompt_version=prompt_version, entry_at_utc=first_time)

    assert is_current(stored, _checkin(first_time)) is True
    assert is_current(stored, _checkin(changed_time)) is False

    stored.prompt_version = "old-prompt-version"
    assert is_current(stored, _checkin(first_time)) is False


def test_orphaned_post_activity_generation_derives_failed_without_a_write() -> None:
    now = datetime(2026, 7, 26, 10, 0)
    row = PostActivityGenerationStatus(
        user_id=uuid.uuid4(),
        activity_id=uuid.uuid4(),
        subject_date=date(2026, 7, 26),
        analysis_type="post_strength",
        status="generating",
        updated_at=now
        - timedelta(minutes=settings.post_activity_generation_stale_after_minutes + 1),
    )

    assert effective_generation_state(row, now=now) == ("failed", "stale")
