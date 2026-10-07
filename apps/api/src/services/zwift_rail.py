"""Whether Mark's rides reach Zwift, read from his intervals.icu account (Batch 326).

A ride reaches Zwift in two legs: the app writes an event to his intervals.icu calendar,
and intervals.icu's Zwift integration keeps a rolling week of those events in Zwift's
Custom workouts. The app sees only the first leg. On 7 Oct 2026 Mark found the
"Intervals.icu" folder gone while Home said "Already in Zwift, ready to ride.":
intervals.icu had paused his free account on 24 Sep, 90 days after its last website
login, and the app's API key does not count as a login.

The account's state is the one signal intervals.icu gives about the second leg (Zwift
has no API for it). ``run_zwift_rail_check`` reads it three times a day, keeps each
reading as integer counters on its ``job_runs`` row and tells Craig; the day carries
the newest good reading (``current_rail``), so the app claims Zwift only when the rail
says a ride can get there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.operations import JobRun
from src.services.job_runs import JobResult

JOB_NAME: Final = "intervals-rail"
ACTIVE_STATUS: Final = "ACTIVE"
FREE_PLAN: Final = "FREE"
# intervals.icu pauses a free account this long after its last website login.
PAUSE_AFTER: Final = timedelta(days=90)
# Craig hears 14 days before the pause; Mark's Today card reminds him from 7.
ALERT_AHEAD: Final = timedelta(days=14)
REMIND_AHEAD: Final = timedelta(days=7)
# A good reading stands this long, so one failed read does not flip Home; after it
# the rail is unknown.
READING_LIFETIME: Final = timedelta(hours=24)
# How far back the job looks to decide whether Craig has already been told.
HISTORY_WINDOW: Final = timedelta(hours=48)


class RailState(StrEnum):
    ok = "ok"
    login_due = "login_due"
    paused = "paused"
    unlinked = "unlinked"
    unknown = "unknown"


# ``job_runs`` counters are integers, so a reading keeps its state as an ordinal.
STATE_ORDINAL: Final[Mapping[RailState, int]] = {
    RailState.ok: 0,
    RailState.login_due: 1,
    RailState.paused: 2,
    RailState.unlinked: 3,
    RailState.unknown: 4,
}
_STATE_BY_ORDINAL: Final[Mapping[int, RailState]] = {
    ordinal: state for state, ordinal in STATE_ORDINAL.items()
}
REACHES_ZWIFT: Final = frozenset({RailState.ok, RailState.login_due})

FIX: Final[Mapping[RailState, str]] = {
    RailState.login_due: "log in at intervals.icu as Mark before the pause date",
    RailState.paused: "log in at intervals.icu as Mark once, then Mark restarts Zwift",
    RailState.unlinked: "reconnect Zwift in intervals.icu (Settings, Connections)",
    RailState.unknown: (
        "check that intervals.icu is up and that INTERVALS_API_KEY still reads the account"
    ),
}


class RailClient(Protocol):
    async def get_athlete(self) -> dict[str, Any]: ...

    async def get_connections(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RailReading:
    """One read of the account, or the failure to read it."""

    state: RailState
    last_login_utc: datetime | None = None
    free_plan: bool = False
    error: str | None = None

    @property
    def pause_at_utc(self) -> datetime | None:
        return _pause_at(self.last_login_utc, free_plan=self.free_plan)


@dataclass(frozen=True, slots=True)
class StoredReading:
    """A reading as the job kept it, on one ``job_runs`` row."""

    at_utc: datetime
    state: RailState
    last_login_utc: datetime | None
    free_plan: bool
    alerted: bool

    @property
    def pause_at_utc(self) -> datetime | None:
        return _pause_at(self.last_login_utc, free_plan=self.free_plan)


@dataclass(frozen=True, slots=True)
class RailView:
    """What the day says about the rail."""

    state: RailState
    pause_date: date | None
    show_login_reminder: bool
    checked_at_utc: datetime | None


@dataclass(frozen=True, slots=True)
class RailAlert:
    state: RailState
    fields: dict[str, Any]


def classify(
    athlete: Mapping[str, Any], connections: Mapping[str, Any], *, now: datetime
) -> RailReading:
    """Class the account. A field missing from either answer is unknown, never a claim."""

    last_login = _parse_utc(athlete.get("icu_last_seen"))
    free_plan = athlete.get("plan") == FREE_PLAN
    status = athlete.get("status")
    if not isinstance(status, str) or not status:
        return RailReading(RailState.unknown, last_login, free_plan, error="no_status")
    if status != ACTIVE_STATUS:
        return RailReading(RailState.paused, last_login, free_plan)
    connected = connections.get("zwift_connected")
    uploading = athlete.get("zwift_upload_workouts")
    if not isinstance(connected, bool) or not isinstance(uploading, bool):
        return RailReading(RailState.unknown, last_login, free_plan, error="no_zwift_link_fields")
    if not connected or not uploading:
        return RailReading(RailState.unlinked, last_login, free_plan)
    return RailReading(_login_state(last_login, free_plan, now), last_login, free_plan)


async def read_account(client: RailClient, *, now: datetime) -> RailReading:
    """Read the account. Any failure is "could not read", never ok and never paused."""

    try:
        athlete = await client.get_athlete()
        connections = await client.get_connections()
    except Exception as exc:  # noqa: BLE001 - a failed read is a reading, not a crash
        return RailReading(RailState.unknown, error=_error_name(exc))
    return classify(athlete, connections, now=now)


def counters(reading: RailReading, *, alerted: bool) -> dict[str, int]:
    return {
        "rail_state": STATE_ORDINAL[reading.state],
        "last_login_epoch": (
            int(reading.last_login_utc.timestamp()) if reading.last_login_utc else 0
        ),
        "free_plan": int(reading.free_plan),
        "alerted": int(alerted),
    }


def job_result(reading: RailReading, *, alerted: bool) -> JobResult:
    values = counters(reading, alerted=alerted)
    if reading.state in REACHES_ZWIFT:
        return JobResult.succeeded(**values)
    return JobResult.degraded(f"zwift_rail_{reading.state.value}", **values)


async def recent_readings(
    session: AsyncSession, *, now: datetime, within: timedelta = HISTORY_WINDOW
) -> list[StoredReading]:
    """The job's readings, newest first. A skipped run (no key) holds none."""

    since = _naive_utc(now) - within
    rows = (
        await session.execute(
            select(JobRun.started_at_utc, JobRun.counters)
            .where(JobRun.job_name == JOB_NAME, JobRun.started_at_utc >= since)
            .order_by(JobRun.started_at_utc.desc())
        )
    ).all()
    readings = (_stored(started, values) for started, values in rows)
    return [reading for reading in readings if reading is not None]


def alert_for(
    reading: RailReading, history: Sequence[StoredReading], *, now: datetime
) -> RailAlert | None:
    """Whether this reading tells Craig: once when the login falls due, and once a UTC
    day while the rail is paused, unlinked, or unread for a whole reading lifetime."""

    today = _aware_utc(now).date()
    told_today = {
        stored.state for stored in history if stored.alerted and stored.at_utc.date() == today
    }
    last_good = _newest_good(history)
    if reading.state is RailState.login_due:
        if last_good is not None and last_good.state is RailState.login_due:
            return None
        return _alert(reading, now)
    if reading.state in (RailState.paused, RailState.unlinked):
        return None if reading.state in told_today else _alert(reading, now)
    if reading.state is RailState.unknown:
        if last_good is not None and _aware_utc(now) - last_good.at_utc < READING_LIFETIME:
            return None
        return None if RailState.unknown in told_today else _alert(reading, now)
    return None


async def current_rail(session: AsyncSession, *, now: datetime, timezone_name: str) -> RailView:
    """The day's view: the newest good reading inside its lifetime, else unknown."""

    readings = await recent_readings(session, now=now, within=READING_LIFETIME)
    good = _newest_good(readings)
    if good is None:
        return RailView(
            RailState.unknown,
            None,
            show_login_reminder=False,
            checked_at_utc=readings[0].at_utc if readings else None,
        )
    state = good.state
    if state in REACHES_ZWIFT:
        # ok and login due turn on the clock, not on the account, so the day reads
        # them afresh from the stored login rather than from when the job last ran.
        state = _login_state(good.last_login_utc, good.free_plan, now)
    pause_at = good.pause_at_utc
    return RailView(
        state,
        pause_at.astimezone(_zone(timezone_name)).date() if pause_at else None,
        show_login_reminder=(
            state is RailState.login_due
            and pause_at is not None
            and _aware_utc(now) >= pause_at - REMIND_AHEAD
        ),
        checked_at_utc=good.at_utc,
    )


def _login_state(last_login: datetime | None, free_plan: bool, now: datetime) -> RailState:
    pause_at = _pause_at(last_login, free_plan=free_plan)
    if pause_at is not None and _aware_utc(now) >= pause_at - ALERT_AHEAD:
        return RailState.login_due
    return RailState.ok


def _pause_at(last_login: datetime | None, *, free_plan: bool) -> datetime | None:
    # A Supporter's account is never paused, so it has no pause date.
    if not free_plan or last_login is None:
        return None
    return last_login + PAUSE_AFTER


def _alert(reading: RailReading, now: datetime) -> RailAlert:
    pause_at = reading.pause_at_utc
    last_login = reading.last_login_utc
    return RailAlert(
        reading.state,
        {
            "state": reading.state.value,
            "fix": FIX[reading.state],
            "days_since_login": (
                (_aware_utc(now) - last_login).days if last_login is not None else None
            ),
            "pause_date": (
                pause_at.astimezone(_zone("Europe/London")).date().isoformat() if pause_at else None
            ),
            "error": reading.error,
        },
    )


def _newest_good(readings: Sequence[StoredReading]) -> StoredReading | None:
    return next((r for r in readings if r.state is not RailState.unknown), None)


def _stored(started_at: datetime, values: Any) -> StoredReading | None:
    if not isinstance(values, Mapping):
        return None
    ordinal = values.get("rail_state")
    state = _STATE_BY_ORDINAL.get(ordinal) if isinstance(ordinal, int) else None
    if state is None:
        return None
    epoch = values.get("last_login_epoch")
    return StoredReading(
        at_utc=_aware_utc(started_at),
        state=state,
        last_login_utc=(
            datetime.fromtimestamp(epoch, tz=UTC) if isinstance(epoch, int) and epoch > 0 else None
        ),
        free_plan=values.get("free_plan") == 1,
        alerted=values.get("alerted") == 1,
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _aware_utc(parsed)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/London")


def _aware_utc(moment: datetime) -> datetime:
    # ``job_runs`` keeps naive UTC; everything here compares aware UTC.
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _naive_utc(moment: datetime) -> datetime:
    return _aware_utc(moment).replace(tzinfo=None)


def _error_name(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    return f"{type(exc).__name__}: {detail}" if isinstance(detail, str) else type(exc).__name__
