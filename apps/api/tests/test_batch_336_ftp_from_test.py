"""Batch 336.1 — the ramp test sets his FTP (CI330-02).

After a ramp test Home offers the new FTP (three-quarters of Garmin's best minute) in one
tap, or Zwift's own number if it differs; the profile's ``ftpWatts`` changes, and with it
every grade. A decided test is never offered again: the profile version's ``source``
records the decision (``ramp_test_2026_10_20``, the convention of Craig's 20 Oct write).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Activity,
    KnowledgeBase,
    PlannedWorkout,
    PostActivityGenerationStatus,
)
from src.models.profile import Profile
from src.services.daily_loop_envelope import _ftp_test
from src.services.ftp_test import (
    FtpTestService,
    decision_source,
    ftp_from_best_minute,
    own_number_range,
)
from src.services.post_workout_analysis import _ftp_watts
from src.services.ride_intervals import _adherence
from tests.test_executable_coaching import _seed_profile

TEST_DAY = date(2026, 10, 20)


def test_the_rule_is_three_quarters_of_the_best_minute() -> None:
    """His 20 Oct test: Garmin's best minute 353 W gives 265 W (Zwift said 267 W)."""
    assert ftp_from_best_minute(353) == 265
    assert ftp_from_best_minute(356) == 267
    assert ftp_from_best_minute(354) == 266  # 265.5 rounds up
    assert own_number_range(265) == (239, 291)


async def _seed(
    db_conn: AsyncConnection,
    *,
    best_minute: Any = 353,
    ftp: int = 280,
    test_status: str = "completed",
    linked: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    workout_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="profile",
                version=1,
                is_active=True,
                source="batch_5_seed",
                content={"ftpWatts": ftp, "weightKg": 74},
            )
        )
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=TEST_DAY,
                version=1,
                title="FTP Ramp Test",
                workout_type="bike_threshold",
                status=test_status,
                is_active=True,
                planned_duration_min=40,
                structured_workout={"format": "bike", "test": "ramp", "steps": []},
                source="block_generator_lock",
            )
        )
        session.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                garmin_activity_id=abs(hash(activity_id)) % 10**12,
                activity_name="Ramp test",
                activity_type="virtual_ride",
                start_utc=datetime(2026, 10, 20, 11, 52),
                raw_summary={"maxAvgPower_60": best_minute} if best_minute is not None else {},
            )
        )
        await session.flush()
        if linked:
            session.add(
                PostActivityGenerationStatus(
                    user_id=user_id,
                    activity_id=activity_id,
                    planned_workout_id=workout_id,
                    subject_date=TEST_DAY,
                    analysis_type="post_workout",
                    status="succeeded",
                )
            )
        await session.commit()
    return user_id, workout_id


async def _profile(session: AsyncSession, user_id: uuid.UUID) -> KnowledgeBase:
    row = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.section == "profile",
            KnowledgeBase.is_active.is_(True),
        )
    )
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_home_offers_the_new_ftp_after_the_test(db_conn: AsyncConnection) -> None:
    user_id, workout_id = await _seed(db_conn)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for today in (TEST_DAY, TEST_DAY + timedelta(days=6)):
            offer = await FtpTestService(session).offer(user_id, today)
            assert offer is not None
            assert (offer.planned_workout_id, offer.best_minute_watts, offer.ftp_watts) == (
                workout_id,
                353,
                265,
            )
            assert offer.current_ftp_watts == 280
        # The offer stands 7 days, and never before the test.
        assert await FtpTestService(session).offer(user_id, TEST_DAY + timedelta(days=7)) is None
        assert await FtpTestService(session).offer(user_id, TEST_DAY - timedelta(days=1)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seed",
    [
        {"test_status": "planned"},  # not ridden yet
        {"test_status": "skipped"},
        {"linked": False},  # no ride linked to the test
        {"best_minute": None},  # no power
        {"best_minute": "n/a"},
    ],
)
async def test_no_offer_without_a_ridden_test_with_power(
    db_conn: AsyncConnection, seed: dict[str, Any]
) -> None:
    user_id, _ = await _seed(db_conn, **seed)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        assert await FtpTestService(session).offer(user_id, TEST_DAY) is None


@pytest.mark.asyncio
async def test_a_test_already_decided_by_hand_is_not_offered(db_conn: AsyncConnection) -> None:
    """20 Oct: Craig wrote 267 W as profile v4, source ``ramp_test_2026_10_20``."""
    user_id, _ = await _seed(db_conn)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        row = await _profile(session, user_id)
        row.is_active = False
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="profile",
                version=2,
                is_active=True,
                source="ramp_test_2026_10_20",
                content={**row.content, "ftpWatts": 267},
            )
        )
        await session.commit()
        assert await FtpTestService(session).offer(user_id, TEST_DAY) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("new_ftp", "before"), [(260, "under"), (300, "over")])
async def test_one_tap_sets_the_ftp_and_every_grade_follows(
    db_conn: AsyncConnection, new_ftp: int, before: str
) -> None:
    """A ±7% change: an ERG-perfect interval read under or over at 280 W, and on after."""
    best = (new_ftp - 0.4) / 0.75
    user_id, workout_id = await _seed(db_conn, best_minute=best)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None

        def graded(target_pct: int) -> str | None:
            ftp = _ftp_watts({"profile": profile.content})
            assert ftp is not None
            # ERG holds the target at Zwift's FTP, which he set to the new number.
            return _adherence(target_pct * new_ftp / ftp, target_pct, target_pct)

        profile = await _profile(session, user_id)
        assert {graded(89), graded(120)} == {before}

        decision = await FtpTestService(session).decide(
            player, planned_workout_id=workout_id, choice="set", today=TEST_DAY
        )
        assert (decision.ftp_watts, decision.previous_ftp_watts) == (new_ftp, 280)
        profile = await _profile(session, user_id)
        assert profile.content == {"ftpWatts": new_ftp, "weightKg": 74}
        assert profile.version == 2
        assert profile.source == decision_source(TEST_DAY) == "ramp_test_2026_10_20"
        assert {graded(89), graded(120), graded(65)} == {"on"}
        # Decided: never offered again.
        assert await FtpTestService(session).offer(user_id, TEST_DAY) is None


@pytest.mark.asyncio
async def test_he_can_set_zwifts_own_number_instead(db_conn: AsyncConnection) -> None:
    user_id, workout_id = await _seed(db_conn)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        with pytest.raises(HTTPException) as refused:
            await FtpTestService(session).decide(
                player,
                planned_workout_id=workout_id,
                choice="set",
                today=TEST_DAY,
                ftp_watts=300,
            )
        assert refused.value.status_code == 422
        assert refused.value.detail == "Enter an FTP between 239 and 291 W."
        await FtpTestService(session).decide(
            player, planned_workout_id=workout_id, choice="set", today=TEST_DAY, ftp_watts=267
        )
        assert (await _profile(session, user_id)).content["ftpWatts"] == 267


@pytest.mark.asyncio
async def test_keeping_his_ftp_is_recorded_and_changes_nothing(db_conn: AsyncConnection) -> None:
    user_id, workout_id = await _seed(db_conn)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        decision = await FtpTestService(session).decide(
            player, planned_workout_id=workout_id, choice="keep", today=TEST_DAY
        )
        assert decision.ftp_watts == 280
        profile = await _profile(session, user_id)
        assert profile.content["ftpWatts"] == 280
        assert profile.source == "ramp_test_2026_10_20_kept"
        assert await FtpTestService(session).offer(user_id, TEST_DAY) is None
        # A second decision on the same test is refused.
        with pytest.raises(HTTPException) as refused:
            await FtpTestService(session).decide(
                player, planned_workout_id=workout_id, choice="set", today=TEST_DAY
            )
        assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_the_daily_loop_carries_the_offer(db_conn: AsyncConnection) -> None:
    user_id, workout_id = await _seed(db_conn)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        out = await _ftp_test(session, user_id, TEST_DAY)
        assert out is not None
        assert out.model_dump() == {
            "plannedWorkoutId": str(workout_id),
            "testDate": "2026-10-20",
            "bestMinuteWatts": 353,
            "ftpWatts": 265,
            "currentFtpWatts": 280,
            "ownNumberMin": 239,
            "ownNumberMax": 291,
        }
        assert await _ftp_test(session, user_id, TEST_DAY + timedelta(days=7)) is None
