"""Batch 283: a profile receives Garmin data only from the account it names.

On 2026-08-24 a ``Craig`` profile with no ``garmin_user_profile_pk`` was synced
with Mark's Garmin session and filled with his history, because the sync keys
off one global token rather than the profile's own Garmin identity. These tests
pin the two rules that close that: a profile naming no account is never synced,
and a document naming another account is never written — while Mark's own sync,
whose documents all name his account, is unchanged.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.garmin_history_backfill import run_backfill
from src.models.coaching import DAILY_METRIC_PHASE_MORNING, Activity, DailyMetric, Sleep
from src.models.profile import Profile, UserRole
from src.seeds import MARK_GARMIN_USER_PROFILE_PK
from src.services.garmin_identity import (
    GarminAccountUnbound,
    GarminIdentityMismatch,
    activity_owner_ids,
    assert_owned_by,
    daily_owner_ids,
    garmin_account,
    sleep_owner_ids,
)
from src.services.garmin_sync import (
    GarminActivityPayloads,
    GarminDailyPayloads,
    GarminSyncService,
)
from src.services.job_runs import JobStatus
from src.services.morning_pipeline import sync_garmin_daily

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"
MARK = MARK_GARMIN_USER_PROFILE_PK
SOMEONE_ELSE = 1234567
DAY = date(2026, 6, 18)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _marks_day() -> GarminDailyPayloads:
    # The committed sleep fixture was trimmed to the fields the parser reads;
    # Garmin sends the owner under ``dailySleepDTO`` (every one of the 458 stored
    # production sleep documents carries it there, measured 2026-09-24).
    sleep = _fixture("sleep.json")
    sleep["dailySleepDTO"]["userProfilePK"] = MARK
    return GarminDailyPayloads(
        training_readiness=_fixture("training_readiness.json"),
        sleep=sleep,
        hrv=_fixture("hrv.json"),
        body_battery=_fixture("body_battery.json"),
        rhr=_fixture("rhr.json"),
        weigh_ins=_fixture("weigh_ins.json"),
        max_metrics_vo2=_fixture("max_metrics_vo2.json"),
        training_status=_fixture("training_status.json"),
        stress=_fixture("stress.json"),
    )


def _marks_activities() -> GarminActivityPayloads:
    # Trimmed the same way; all 1,249 stored production activities carry ``ownerId``.
    summaries = _fixture("activities.json")
    for summary in summaries:
        summary["ownerId"] = MARK
    return GarminActivityPayloads(summaries=summaries)


def _profile(account: int | None) -> Profile:
    profile_id = uuid.uuid4()
    return Profile(
        id=profile_id,
        # Display names are unique, and the database test seeds three at once.
        display_name=f"Identity {profile_id.hex[:8]}",
        role=UserRole.admin,
        timezone="Europe/London",
        garmin_user_profile_pk=account,
        is_active=True,
    )


def _session_holding(profile: Profile | None) -> AsyncMock:
    """A session whose only answer is the profile; any write attempt is visible."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=profile)
    session.add = MagicMock()
    return session


# --- where the id lives, on the real fixture shapes -------------------------


def test_the_owner_is_read_where_garmin_puts_it() -> None:
    """The field map is measured, not assumed.

    Four committed fixtures still carry the id exactly as Garmin sent it. The rest
    were trimmed when committed, so they are stated in the shape measured on the
    real samples (``~/garmin-spike/out``) and on every stored production document.
    """
    for name in ("training_readiness", "hrv", "max_metrics_vo2", "stress"):
        only = GarminDailyPayloads(**{name: _fixture(f"{name}.json")})
        assert daily_owner_ids(only) == {MARK}, name
    assert daily_owner_ids(GarminDailyPayloads(rhr={"userProfileId": MARK})) == {MARK}
    assert daily_owner_ids(GarminDailyPayloads(stats={"userProfileId": MARK})) == {MARK}
    assert daily_owner_ids(GarminDailyPayloads(training_status={"userId": MARK})) == {MARK}
    assert sleep_owner_ids({"dailySleepDTO": {"userProfilePK": MARK}}) == {MARK}
    assert activity_owner_ids([{"ownerId": MARK}, {"ownerId": MARK}]) == {MARK}
    assert daily_owner_ids(_marks_day()) == {MARK}


def test_a_document_without_an_owner_is_no_evidence() -> None:
    assert daily_owner_ids(GarminDailyPayloads(body_battery=_fixture("body_battery.json"))) == set()
    assert daily_owner_ids(GarminDailyPayloads()) == set()
    assert activity_owner_ids([{"activityId": 1}]) == set()
    assert sleep_owner_ids({"dailySleepDTO": {"userProfilePK": None}}) == set()


def test_ids_are_read_as_integers_and_nothing_else() -> None:
    assert activity_owner_ids([{"ownerId": str(MARK)}]) == {MARK}
    assert activity_owner_ids([{"ownerId": True}, {"ownerId": "abc"}, {"ownerId": 1.5}]) == set()


def test_garmin_account_reads_the_profile_column() -> None:
    assert garmin_account(_profile(MARK)) == MARK
    assert garmin_account(_profile(None)) is None
    assert garmin_account(None) is None


def test_the_rule_refuses_unbound_and_foreign_data_and_nothing_else() -> None:
    assert_owned_by(MARK, {MARK}, source="daily")
    assert_owned_by(MARK, set(), source="daily")
    with pytest.raises(GarminAccountUnbound):
        assert_owned_by(None, set(), source="daily")
    with pytest.raises(GarminIdentityMismatch) as exc:
        assert_owned_by(SOMEONE_ELSE, {MARK}, source="daily")
    assert exc.value.expected == SOMEONE_ELSE
    assert exc.value.found == {MARK}


# --- the write layer ---------------------------------------------------------


async def test_marks_day_is_refused_for_a_profile_that_names_another_account() -> None:
    session = _session_holding(_profile(SOMEONE_ELSE))
    with pytest.raises(GarminIdentityMismatch):
        await GarminSyncService(session).sync_daily(
            uuid.uuid4(), DAY, _marks_day(), phase=DAILY_METRIC_PHASE_MORNING, commit=False
        )
    session.execute.assert_not_awaited()
    session.add.assert_not_called()


async def test_nothing_is_synced_into_a_profile_that_names_no_account() -> None:
    session = _session_holding(_profile(None))
    with pytest.raises(GarminAccountUnbound):
        await GarminSyncService(session).sync_daily(
            uuid.uuid4(), DAY, _marks_day(), phase=DAILY_METRIC_PHASE_MORNING, commit=False
        )
    with pytest.raises(GarminAccountUnbound):
        await GarminSyncService(session).sync_activities(
            uuid.uuid4(), _marks_activities(), commit=False
        )
    session.execute.assert_not_awaited()
    session.add.assert_not_called()


async def test_marks_activities_are_refused_before_the_first_write() -> None:
    session = _session_holding(_profile(SOMEONE_ELSE))
    with pytest.raises(GarminIdentityMismatch):
        await GarminSyncService(session).sync_activities(
            uuid.uuid4(), _marks_activities(), commit=False
        )
    session.execute.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


# --- the jobs ---------------------------------------------------------------


def _job_profile(account: int | None) -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    profile.garmin_user_profile_pk = account
    return profile


async def test_the_morning_sync_never_calls_garmin_for_an_unbound_profile() -> None:
    unbound, mark = _job_profile(None), _job_profile(MARK)
    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")
    service = MagicMock()
    service.sync_daily = AsyncMock(return_value=MagicMock(daily_metrics_synced=1, sleep_synced=1))

    with (
        patch("src.services.morning_pipeline.GarminSyncService", return_value=service),
        patch("src.services.morning_pipeline.profile_today", return_value=date(2026, 9, 24)),
    ):
        result = await sync_garmin_daily(AsyncMock(), [unbound, mark], client=client)

    assert result.garmin_unbound == 1
    assert result.failures == 0
    # Only Mark's four dates were fetched and written.
    assert client.fetch_daily_payloads.call_count == 4
    assert {call.args[0] for call in service.sync_daily.await_args_list} == {mark.id}
    assert (result.daily_metrics, result.sleep) == (4, 4)


async def test_a_mismatch_fails_that_profile_once_and_the_others_still_sync() -> None:
    wrong, mark = _job_profile(SOMEONE_ELSE), _job_profile(MARK)
    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")
    service = MagicMock()

    async def sync_daily(user_id: uuid.UUID, *_a: object, **_k: object) -> MagicMock:
        if user_id == wrong.id:
            raise GarminIdentityMismatch(source="daily", expected=SOMEONE_ELSE, found={MARK})
        return MagicMock(daily_metrics_synced=1, sleep_synced=1)

    service.sync_daily = AsyncMock(side_effect=sync_daily)
    session = AsyncMock()
    with (
        patch("src.services.morning_pipeline.GarminSyncService", return_value=service),
        patch("src.services.morning_pipeline.profile_today", return_value=date(2026, 9, 24)),
    ):
        result = await sync_garmin_daily(session, [wrong, mark], client=client)

    assert result.garmin_identity_mismatch == 1
    assert result.failures == 1
    # The wrong account is fetched once, not four times; Mark's four dates still land.
    assert client.fetch_daily_payloads.call_count == 1 + 4
    assert (result.daily_metrics, result.sleep) == (4, 4)


async def test_the_activity_poll_skips_the_unbound_refuses_the_foreign_and_keeps_mark() -> None:
    from src.scheduler import run_garmin_activity_poll

    unbound, wrong, mark = _job_profile(None), _job_profile(SOMEONE_ELSE), _job_profile(MARK)
    session = AsyncMock()
    profile_rows = MagicMock()
    profile_rows.scalars.return_value.all.return_value = [unbound, wrong, mark]
    session.execute = AsyncMock(return_value=profile_rows)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    fetched_for: list[str] = []
    client = MagicMock()

    def fetch(*_a: object, **_k: object) -> GarminActivityPayloads:
        fetched_for.append("fetch")
        return _marks_activities()

    client.fetch_activity_payloads = MagicMock(side_effect=fetch)
    sync_service = MagicMock()

    async def sync_activities(user_id: uuid.UUID, *_a: object, **_k: object) -> MagicMock:
        if user_id == wrong.id:
            raise GarminIdentityMismatch(source="activities", expected=SOMEONE_ELSE, found={MARK})
        return MagicMock(activities_synced=2, timeseries_samples_synced=0)

    sync_service.sync_activities = AsyncMock(side_effect=sync_activities)
    pending = MagicMock()
    for method in (
        "pending_ride_activities",
        "pending_flexibility_activities",
        "pending_strength_activities",
        "pending_walk_activities",
    ):
        setattr(pending, method, AsyncMock(return_value=[]))

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler.GarminSyncService", return_value=sync_service),
        patch("src.scheduler.PostWorkoutAnalysisService", return_value=pending),
        patch("src.scheduler.PostFlexibilityAnalysisService", return_value=pending),
        patch("src.scheduler.PostStrengthAnalysisService", return_value=pending),
        patch("src.scheduler.PostWalkAnalysisService", return_value=pending),
        patch("src.scheduler.NudgeAlertService", return_value=MagicMock()),
    ):
        result = await run_garmin_activity_poll()

    assert result.status is JobStatus.degraded
    assert result.reason == "garmin_identity_mismatch"
    assert result.counters["garmin_unbound"] == 1
    assert result.counters["garmin_identity_mismatch"] == 1
    assert result.counters["activities"] == 2  # Mark's, and only Mark's
    assert len(fetched_for) == 2  # the unbound profile was never fetched for
    session.commit.assert_awaited_once()


async def test_the_backfill_refuses_an_unbound_profile_before_any_garmin_call() -> None:
    client = MagicMock()
    with pytest.raises(GarminAccountUnbound):
        await run_backfill(
            AsyncMock(), _profile(None), client=client, start=DAY, end=DAY, log_fn=lambda _m: None
        )
    client.fetch_daily_payloads.assert_not_called()
    client.fetch_activity_payloads.assert_not_called()


# --- the real database (CI) --------------------------------------------------


@pytest.mark.asyncio
async def test_only_the_owning_profile_receives_marks_data(db_conn: AsyncConnection) -> None:
    """The 2026-08-24 shape end to end: Mark syncs; the other two receive nothing."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    mark, other, unbound = _profile(MARK), _profile(SOMEONE_ELSE), _profile(None)

    async with session_factory() as session:
        session.add_all([mark, other, unbound])
        await session.flush()
        service = GarminSyncService(session)

        daily = await service.sync_daily(
            mark.id, DAY, _marks_day(), phase=DAILY_METRIC_PHASE_MORNING, commit=False
        )
        activities = await service.sync_activities(mark.id, _marks_activities(), commit=False)
        for profile, error in ((other, GarminIdentityMismatch), (unbound, GarminAccountUnbound)):
            with pytest.raises(error):
                await service.sync_daily(
                    profile.id, DAY, _marks_day(), phase=DAILY_METRIC_PHASE_MORNING, commit=False
                )
            with pytest.raises(error):
                await service.sync_activities(profile.id, _marks_activities(), commit=False)

        async def rows(model: Any, user_id: uuid.UUID) -> int:
            return int(
                await session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )
                or 0
            )

        assert (daily.daily_metrics_synced, daily.sleep_synced) == (1, 1)
        assert activities.activities_synced == 1
        assert await rows(DailyMetric, mark.id) == 1
        assert await rows(Sleep, mark.id) == 1
        assert await rows(Activity, mark.id) == 1
        for profile in (other, unbound):
            for model in (DailyMetric, Sleep, Activity):
                assert await rows(model, profile.id) == 0
