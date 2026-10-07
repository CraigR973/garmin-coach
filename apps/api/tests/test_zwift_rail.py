"""Batch 326 — the app says when rides stop reaching Zwift.

On 7 Oct 2026 Mark found the "Intervals.icu" folder gone from Zwift while Home said
"Already in Zwift, ready to ride.": intervals.icu had paused his free account on 24 Sep,
90 days after its last website login. The app now reads the account three times a day,
keeps each reading on its ``job_runs`` row, tells Craig, and the day says what is true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

import src.scheduler as scheduler
from src.config import settings
from src.services import workout_delivery
from src.services.admin_alerts import KIND_DELIVERY_RAIL
from src.services.daily_loop_envelope import _zwift_rail
from src.services.job_runs import JobStatus, scheduled_window
from src.services.workout_delivery import IntervalsIcuClient
from src.services.zwift_rail import (
    JOB_NAME,
    STATE_ORDINAL,
    RailReading,
    RailState,
    StoredReading,
    alert_for,
    classify,
    counters,
    current_rail,
    job_result,
    read_account,
)

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)

# Cut from the production answers of 7 Oct 2026, keeping only the fields the rail reads
# (the repo is public, so nothing else of his account is copied here).
DORMANT_ATHLETE = {
    "status": "DORMANT",
    "status_updated": "2026-09-24T17:34:05.407+00:00",
    "icu_last_seen": "2026-06-26T17:22:01.340+00:00",
    "plan": "FREE",
    "zwift_upload_workouts": True,
}
ACTIVE_ATHLETE = {
    "status": "ACTIVE",
    "status_updated": "2026-10-07T17:43:15.031+00:00",
    "icu_last_seen": "2026-10-07T17:42:47.801+00:00",
    "plan": "FREE",
    "zwift_upload_workouts": True,
}
CONNECTED = {"zwift_connected": True, "strava_connected": False}


def _athlete(**changes: Any) -> dict[str, Any]:
    return {**ACTIVE_ATHLETE, **changes}


def _seen(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _stored(
    state: RailState,
    *,
    hours_ago: float,
    alerted: bool = False,
    last_login: datetime | None = None,
    free_plan: bool = True,
) -> StoredReading:
    return StoredReading(
        at_utc=NOW - timedelta(hours=hours_ago),
        state=state,
        last_login_utc=last_login,
        free_plan=free_plan,
        alerted=alerted,
    )


# -- classing the account ------------------------------------------------------------------


def test_the_7_oct_dormant_account_is_paused() -> None:
    reading = classify(DORMANT_ATHLETE, CONNECTED, now=NOW)

    assert reading.state is RailState.paused
    assert reading.last_login_utc == datetime(2026, 6, 26, 17, 22, 1, 340000, tzinfo=UTC)
    # 90 days after the last login: the hour intervals.icu paused it.
    assert reading.pause_at_utc == datetime(2026, 9, 24, 17, 22, 1, 340000, tzinfo=UTC)


def test_the_account_after_craigs_login_is_ok() -> None:
    reading = classify(ACTIVE_ATHLETE, CONNECTED, now=NOW)

    assert reading.state is RailState.ok
    assert reading.pause_at_utc is not None
    assert reading.pause_at_utc.date() == date(2027, 1, 5)


def test_a_free_account_14_days_from_its_pause_has_its_login_due() -> None:
    assert classify(_athlete(icu_last_seen=_seen(75.9)), CONNECTED, now=NOW).state is RailState.ok
    assert (
        classify(_athlete(icu_last_seen=_seen(76)), CONNECTED, now=NOW).state is RailState.login_due
    )
    # Past 90 days but not yet paused by intervals.icu: still due, never ok.
    assert (
        classify(_athlete(icu_last_seen=_seen(95)), CONNECTED, now=NOW).state is RailState.login_due
    )


def test_a_supporter_account_is_never_due_and_has_no_pause_date() -> None:
    reading = classify(_athlete(plan="SUPPORTER", icu_last_seen=_seen(200)), CONNECTED, now=NOW)

    assert reading.state is RailState.ok
    assert reading.pause_at_utc is None


@pytest.mark.parametrize(
    ("athlete", "connections"),
    [
        (ACTIVE_ATHLETE, {"zwift_connected": False}),
        (_athlete(zwift_upload_workouts=False), CONNECTED),
    ],
)
def test_a_lost_zwift_link_is_unlinked(
    athlete: dict[str, Any], connections: dict[str, Any]
) -> None:
    assert classify(athlete, connections, now=NOW).state is RailState.unlinked


def test_paused_wins_over_a_lost_link() -> None:
    reading = classify(DORMANT_ATHLETE, {"zwift_connected": False}, now=NOW)

    assert reading.state is RailState.paused


@pytest.mark.parametrize(
    ("athlete", "connections", "error"),
    [
        ({**ACTIVE_ATHLETE, "status": None}, CONNECTED, "no_status"),
        (ACTIVE_ATHLETE, {}, "no_zwift_link_fields"),
        (
            {k: v for k, v in ACTIVE_ATHLETE.items() if k != "zwift_upload_workouts"},
            CONNECTED,
            "no_zwift_link_fields",
        ),
    ],
)
def test_a_missing_field_is_unknown_never_a_claim(
    athlete: dict[str, Any], connections: dict[str, Any], error: str
) -> None:
    reading = classify(athlete, connections, now=NOW)

    assert reading.state is RailState.unknown
    assert reading.error == error


class _Client:
    def __init__(self, athlete: Any = ACTIVE_ATHLETE, connections: Any = CONNECTED) -> None:
        self.athlete = athlete
        self.connections = connections
        self.calls: list[str] = []

    async def get_athlete(self) -> dict[str, Any]:
        self.calls.append("athlete")
        if isinstance(self.athlete, Exception):
            raise self.athlete
        return dict(self.athlete)

    async def get_connections(self) -> dict[str, Any]:
        self.calls.append("connections")
        if isinstance(self.connections, Exception):
            raise self.connections
        return dict(self.connections)


@pytest.mark.asyncio
async def test_a_failed_read_is_unknown() -> None:
    client = _Client(athlete=HTTPException(502, "intervals.icu read failed with HTTP 503"))

    reading = await read_account(client, now=NOW)

    assert reading.state is RailState.unknown
    assert reading.error == "HTTPException: intervals.icu read failed with HTTP 503"


@pytest.mark.asyncio
async def test_a_read_makes_the_two_gets() -> None:
    client = _Client()

    reading = await read_account(client, now=NOW)

    assert reading.state is RailState.ok
    assert client.calls == ["athlete", "connections"]


# -- what each reading keeps ---------------------------------------------------------------


def test_a_reading_is_kept_as_integer_counters() -> None:
    reading = classify(DORMANT_ATHLETE, CONNECTED, now=NOW)

    values = counters(reading, alerted=True)

    assert values == {
        "rail_state": STATE_ORDINAL[RailState.paused],
        "last_login_epoch": int(datetime(2026, 6, 26, 17, 22, 1, tzinfo=UTC).timestamp()),
        "free_plan": 1,
        "alerted": 1,
    }
    assert all(isinstance(value, int) for value in values.values())


def test_only_a_rail_that_reaches_zwift_is_a_clean_run() -> None:
    ok = job_result(RailReading(RailState.ok), alerted=False)
    due = job_result(RailReading(RailState.login_due), alerted=True)
    paused = job_result(RailReading(RailState.paused), alerted=True)
    unknown = job_result(RailReading(RailState.unknown, error="boom"), alerted=False)

    assert ok.status is JobStatus.succeeded
    assert due.status is JobStatus.succeeded
    assert (paused.status, paused.reason) == (JobStatus.degraded, "zwift_rail_paused")
    assert (unknown.status, unknown.reason) == (JobStatus.degraded, "zwift_rail_unknown")


def test_the_check_has_six_hour_windows_like_the_autopush() -> None:
    start, end = scheduled_window(JOB_NAME, datetime(2026, 10, 7, 12, 5))

    assert end - start == timedelta(hours=6)


# -- when Craig hears ----------------------------------------------------------------------


def test_craig_hears_once_when_the_login_falls_due() -> None:
    due = RailReading(RailState.login_due, NOW - timedelta(days=76), free_plan=True)

    first = alert_for(due, [_stored(RailState.ok, hours_ago=6)], now=NOW)
    again = alert_for(due, [_stored(RailState.login_due, hours_ago=6, alerted=True)], now=NOW)
    after_a_failed_read = alert_for(
        due,
        [
            _stored(RailState.unknown, hours_ago=6),
            _stored(RailState.login_due, hours_ago=12, alerted=True),
        ],
        now=NOW,
    )

    assert first is not None
    assert first.fields["state"] == "login_due"
    assert first.fields["days_since_login"] == 76
    assert first.fields["pause_date"] == "2026-10-21"
    assert "log in at intervals.icu" in first.fields["fix"]
    assert again is None
    assert after_a_failed_read is None


def test_craig_hears_once_a_day_while_paused() -> None:
    paused = classify(DORMANT_ATHLETE, CONNECTED, now=NOW)

    first_today = alert_for(
        paused, [_stored(RailState.paused, hours_ago=20, alerted=True)], now=NOW
    )
    told_today = alert_for(paused, [_stored(RailState.paused, hours_ago=5, alerted=True)], now=NOW)

    # 20 hours before 18:00 UTC on 7 Oct is 6 Oct: yesterday's alert does not count.
    assert first_today is not None
    assert first_today.fields["state"] == "paused"
    assert told_today is None


def test_craig_hears_once_a_day_while_unlinked() -> None:
    unlinked = RailReading(RailState.unlinked)

    assert alert_for(unlinked, [], now=NOW) is not None
    told = [_stored(RailState.unlinked, hours_ago=1, alerted=True)]
    assert alert_for(unlinked, told, now=NOW) is None


def test_one_failed_read_is_not_an_alert_but_a_day_of_them_is() -> None:
    unknown = RailReading(RailState.unknown, error="ConnectTimeout")

    blip = alert_for(unknown, [_stored(RailState.ok, hours_ago=6)], now=NOW)
    a_day = alert_for(
        unknown,
        [_stored(RailState.unknown, hours_ago=6), _stored(RailState.ok, hours_ago=25)],
        now=NOW,
    )
    told = alert_for(
        unknown,
        [
            _stored(RailState.unknown, hours_ago=6, alerted=True),
            _stored(RailState.ok, hours_ago=30),
        ],
        now=NOW,
    )
    never_read = alert_for(unknown, [], now=NOW)

    assert blip is None
    assert a_day is not None
    assert a_day.fields["error"] == "ConnectTimeout"
    assert told is None
    assert never_read is not None


def test_an_ok_reading_is_never_an_alert() -> None:
    assert alert_for(RailReading(RailState.ok), [], now=NOW) is None


# -- what the day says ---------------------------------------------------------------------


def _session(rows: list[tuple[datetime, dict[str, int]]]) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    return session


def _row(
    state: RailState,
    *,
    hours_ago: float,
    login_days_ago: float | None = None,
    free_plan: bool = True,
) -> tuple[datetime, dict[str, int]]:
    login = NOW - timedelta(days=login_days_ago) if login_days_ago is not None else None
    reading = RailReading(state, login, free_plan=free_plan)
    started = (NOW - timedelta(hours=hours_ago)).replace(tzinfo=None)
    return started, counters(reading, alerted=False)


@pytest.mark.asyncio
async def test_with_no_reading_the_day_cannot_say() -> None:
    view = await current_rail(_session([]), now=NOW, timezone_name="Europe/London")

    assert view.state is RailState.unknown
    assert view.checked_at_utc is None
    assert view.show_login_reminder is False


@pytest.mark.asyncio
async def test_a_failed_read_keeps_the_last_good_reading() -> None:
    rows = [
        _row(RailState.unknown, hours_ago=1),
        _row(RailState.ok, hours_ago=7, login_days_ago=1),
    ]

    view = await current_rail(_session(rows), now=NOW, timezone_name="Europe/London")

    assert view.state is RailState.ok
    assert view.checked_at_utc == NOW - timedelta(hours=7)


@pytest.mark.asyncio
async def test_only_failed_reads_leave_the_day_unknown() -> None:
    rows = [_row(RailState.unknown, hours_ago=1), _row(RailState.unknown, hours_ago=7)]

    view = await current_rail(_session(rows), now=NOW, timezone_name="Europe/London")

    assert view.state is RailState.unknown
    assert view.checked_at_utc == NOW - timedelta(hours=1)


@pytest.mark.asyncio
async def test_the_day_shows_the_pause_as_it_was_read() -> None:
    rows = [_row(RailState.paused, hours_ago=2, login_days_ago=103)]

    view = await current_rail(_session(rows), now=NOW, timezone_name="Europe/London")

    assert view.state is RailState.paused
    assert view.show_login_reminder is False


@pytest.mark.asyncio
async def test_mark_is_reminded_only_in_the_last_seven_days() -> None:
    fortnight = [_row(RailState.ok, hours_ago=2, login_days_ago=78)]
    week = [_row(RailState.ok, hours_ago=2, login_days_ago=84)]

    due = await current_rail(_session(fortnight), now=NOW, timezone_name="Europe/London")
    remind = await current_rail(_session(week), now=NOW, timezone_name="Europe/London")

    # A stored "ok" turns due on the clock, without waiting for the next read.
    assert due.state is RailState.login_due
    assert due.show_login_reminder is False
    assert due.pause_date == date(2026, 10, 19)
    assert remind.state is RailState.login_due
    assert remind.show_login_reminder is True
    assert remind.pause_date == date(2026, 10, 13)


@pytest.mark.asyncio
async def test_a_supporter_is_never_reminded() -> None:
    rows = [_row(RailState.ok, hours_ago=2, login_days_ago=200, free_plan=False)]

    view = await current_rail(_session(rows), now=NOW, timezone_name="Europe/London")

    assert view.state is RailState.ok
    assert view.pause_date is None
    assert view.show_login_reminder is False


@pytest.mark.asyncio
async def test_the_day_carries_the_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row(RailState.ok, hours_ago=2, login_days_ago=84)]
    monkeypatch.setattr(
        "src.services.daily_loop_envelope.datetime",
        MagicMock(now=MagicMock(return_value=NOW)),
    )

    out = await _zwift_rail(_session(rows), "Europe/London")

    assert out.model_dump() == {
        "state": "login_due",
        "pauseDate": "2026-10-13",
        "showLoginReminder": True,
        "checkedAtUtc": "2026-10-07T16:00:00Z",
    }


# -- the job -------------------------------------------------------------------------------


@pytest.fixture
def job(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The job with its database history, its client and its alert route faked."""
    state: dict[str, Any] = {"rows": [], "client": _Client(), "alerts": []}

    @asynccontextmanager
    async def session_local() -> AsyncIterator[AsyncMock]:
        yield _session(state["rows"])

    def alert(_logger: Any, event: str, *, kind: str, **fields: Any) -> None:
        state["alerts"].append((event, kind, fields))

    monkeypatch.setattr(settings, "intervals_api_key", "test-key")
    monkeypatch.setattr(settings, "intervals_athlete_id", "i0")
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_local)
    monkeypatch.setattr(scheduler, "IntervalsIcuClient", lambda: state["client"])
    monkeypatch.setattr(scheduler, "admin_alert", alert)
    return state


@pytest.mark.asyncio
async def test_the_job_reads_the_account_and_tells_craig_it_is_paused(
    job: dict[str, Any],
) -> None:
    job["client"] = _Client(athlete=DORMANT_ATHLETE)

    result = await scheduler.run_zwift_rail_check()

    assert result.status is JobStatus.degraded
    assert result.reason == "zwift_rail_paused"
    assert result.counters["rail_state"] == STATE_ORDINAL[RailState.paused]
    assert result.counters["alerted"] == 1
    [(event, kind, fields)] = job["alerts"]
    assert (event, kind, fields["state"]) == ("zwift rail alert", KIND_DELIVERY_RAIL, "paused")
    # Reads only: the client the job holds has no way to write.
    assert job["client"].calls == ["athlete", "connections"]


@pytest.mark.asyncio
async def test_the_job_on_a_healthy_account_is_quiet(job: dict[str, Any]) -> None:
    result = await scheduler.run_zwift_rail_check()

    assert result.status is JobStatus.succeeded
    assert result.counters["alerted"] == 0
    assert job["alerts"] == []


@pytest.mark.asyncio
async def test_the_job_without_a_key_skips(
    job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "intervals_api_key", "")

    result = await scheduler.run_zwift_rail_check()

    assert (result.status, result.reason) == (JobStatus.skipped, "intervals_not_configured")
    assert job["client"].calls == []


def test_the_job_runs_at_five_past_the_autopush_hours() -> None:
    job = scheduler.create_scheduler().get_job("zwift_rail_check")

    assert job is not None
    assert "hour='7,13,19', minute='5'" in str(job.trigger)


# -- the client's reads --------------------------------------------------------------------


def _transport(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    real = httpx.AsyncClient
    monkeypatch.setattr(
        workout_delivery.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    return seen


@pytest.mark.asyncio
async def test_the_client_reads_the_athlete_and_its_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _transport(monkeypatch, httpx.Response(200, json={"status": "ACTIVE"}))
    client = IntervalsIcuClient(api_key="k", athlete_id="i0", base_url="https://icu.test/api/v1")

    athlete = await client.get_athlete()
    connections = await client.get_connections()

    assert athlete == connections == {"status": "ACTIVE"}
    assert [(request.method, str(request.url)) for request in seen] == [
        ("GET", "https://icu.test/api/v1/athlete/i0"),
        ("GET", "https://icu.test/api/v1/athlete/i0/connections"),
    ]
    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)


@pytest.mark.asyncio
async def test_a_failed_client_read_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _transport(monkeypatch, httpx.Response(403, json={"error": "nope"}))
    client = IntervalsIcuClient(api_key="k", athlete_id="i0", base_url="https://icu.test/api/v1")

    with pytest.raises(HTTPException) as raised:
        await client.get_athlete()

    assert raised.value.detail == "intervals.icu read failed with HTTP 403"
