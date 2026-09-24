"""Batch 281: ``activities.raw_summary`` stays in the database unless a reader needs it.

The summary is ~4.6 KB of Garmin JSON a row, and over the 92 days
``pg_stat_statements`` covered on 2026-09-23 every one of 58,000 activity reads
shipped it — ~7.3 GB — although exactly two code paths read it:

* ``garmin_sync`` carries ``activitySplits`` forward when it upserts a row it
  has just loaded by ``garmin_activity_id``;
* the ride read (``post_workout_analysis``) grades intervals on
  ``activitySplits.lapDTOs`` — off the ``Activity`` object it is *handed*.

So the classification is per loader, not per model, and it is written down
here as a test: every ``select(Activity)`` in ``src`` either defers the summary
with ``bulk_history_reads.without_activity_raw_summary()`` or is one of the
three loaders that must keep it, each with its reason. A new bare
``select(Activity)`` fails this file rather than an egress bill; deferring one
of the three fails it too, before it fails a ride read.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity
from src.models.profile import Profile, UserRole
from src.services.bulk_history_reads import without_activity_raw_summary

SRC = Path(__file__).resolve().parents[1] / "src"

#: The loaders that keep the whole row, and why. Everything else defers it.
WHOLE_ROW_LOADERS = {
    "services/post_workout_analysis.py:PostWorkoutAnalysisService.pending_ride_activities": (
        "hands each ride to the ride read, which grades intervals on "
        "raw_summary['activitySplits']['lapDTOs']"
    ),
    "services/daily_loop.py:DailyLoopService._activity": (
        "the check-in route's session.get(Activity, ...) receives this object from "
        "the identity map and hands it to the ride read"
    ),
    "services/garmin_sync.py:GarminSyncService.sync_activities": (
        "carries raw_summary['activitySplits'] forward when an optional splits fetch is missing"
    ),
}


def _activity_loaders() -> dict[str, bool]:
    """``{"file:Class.function": defers_the_summary}`` for every ``select(Activity)``."""
    found: dict[str, bool] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "select"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "Activity"
            ):
                continue
            key = f"{path.relative_to(SRC).as_posix()}:{_qualified_scope(node, parents)}"
            assert key not in found, f"two select(Activity) in one function: {key}"
            found[key] = _defers_summary(node, parents)
    return found


def _qualified_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(names))


def _defers_summary(select_call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when ``select(Activity)`` is directly ``.options(without_activity_raw_summary())``."""
    attribute = parents.get(select_call)
    if not (isinstance(attribute, ast.Attribute) and attribute.attr == "options"):
        return False
    call = parents.get(attribute)
    return isinstance(call, ast.Call) and any(
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id == "without_activity_raw_summary"
        for arg in call.args
    )


def test_every_activity_loader_is_classified() -> None:
    """281.2 in writing: each loader defers the summary or is a named whole-row loader."""
    loaders = _activity_loaders()
    whole = {key for key, defers in loaders.items() if not defers}

    unexpected = sorted(whole - set(WHOLE_ROW_LOADERS))
    missing = sorted(set(WHOLE_ROW_LOADERS) - whole)
    assert not unexpected and not missing, (
        "A select(Activity) either defers the summary with "
        "without_activity_raw_summary() or is added to WHOLE_ROW_LOADERS with the "
        f"reason it reads raw_summary. Unexpected whole rows: {unexpected}; "
        f"expected whole but deferred: {missing}"
    )
    # Not vacuous: the scan sees the deferred loaders too (23, plus the 3 whole, at Batch 281).
    assert sum(loaders.values()) >= 20


def test_the_ride_read_still_reads_the_whole_summary() -> None:
    """281.4: ``post_workout_analysis`` is unchanged, and this says why.

    The ride read takes lap boundaries from ``raw_summary['activitySplits']``
    on the object it is given, so the loaders that give it one — its own
    pending-ride query and the check-in route's ``_activity`` — keep the column.
    """
    source = (SRC / "services" / "post_workout_analysis.py").read_text(encoding="utf-8")
    assert 'activity.raw_summary.get("activitySplits")' in source
    assert "without_activity_raw_summary" not in source


def _compiled(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_the_option_drops_only_the_summary() -> None:
    sql = _compiled(select(Activity).options(without_activity_raw_summary()))
    assert "raw_summary" not in sql
    for column in (
        "activities.start_utc",
        "activities.activity_type",
        "activities.training_load",
        "activities.duration_sec",
        "activities.normalized_power_watts",
        "activities.exclude_from_recovery",
    ):
        assert column in sql, column


class _RecordingSession:
    """Captures statements; returns nothing."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        self.statements.append(statement)
        return self

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> None:
        self.statements.append(statement)
        return None

    def scalars(self) -> _RecordingSession:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def unique(self) -> _RecordingSession:
        return self

    def activity_sql(self) -> list[str]:
        return [
            _compiled(statement)
            for statement in self.statements
            if "FROM activities" in _compiled(statement)
        ]


def _player() -> Profile:
    return Profile(
        id=uuid.uuid4(), display_name="Mark", timezone="Europe/London", role=UserRole.admin
    )


async def test_the_largest_readers_leave_the_summary_behind() -> None:
    """281.3: by rows returned, not by calls — these four shapes were 1.55M of 1.65M rows.

    The 120-night driver read (864,586 rows), the walking and breathwork briefs
    (the ``activity_type`` shape, 553,279) and the strength brief (68,352).
    """
    from src.services.breathwork_brief import BreathworkBriefService
    from src.services.insights import InsightsService
    from src.services.strength_brief import StrengthBriefService
    from src.services.walking_brief import WalkingBriefService

    session = _RecordingSession()
    player = _player()
    await InsightsService(session)._driver_records(  # type: ignore[arg-type]
        player, start=date(2026, 5, 26), end=date(2026, 9, 22)
    )
    await WalkingBriefService(session).brief(player, as_of=date(2026, 9, 22))  # type: ignore[arg-type]
    await BreathworkBriefService(session).brief(player, as_of=date(2026, 9, 22))  # type: ignore[arg-type]
    await StrengthBriefService(session).brief(player, as_of=date(2026, 9, 22))  # type: ignore[arg-type]

    sql = session.activity_sql()
    assert len(sql) >= 4
    for statement in sql:
        assert "activities.raw_summary" not in statement, statement


async def test_the_pending_ride_query_still_ships_the_summary() -> None:
    from src.services.post_workout_analysis import PostWorkoutAnalysisService

    session = _RecordingSession()
    await PostWorkoutAnalysisService(session).pending_ride_activities(  # type: ignore[arg-type]
        uuid.uuid4(), since=datetime(2026, 9, 20)
    )
    assert any("activities.raw_summary" in sql for sql in session.activity_sql())


@pytest.mark.asyncio
async def test_the_check_in_route_hands_the_ride_read_a_whole_row(
    db_conn: AsyncConnection,
) -> None:
    """The identity-map path the classification relies on, against real Postgres.

    A day's activities are loaded with the summary deferred and held, as the
    daily loop does; the check-in route then loads the ride through
    ``DailyLoopService._activity`` and fetches it with ``session.get`` — the
    object the ride read is handed must carry its lap boundaries. Without the
    whole-row ``_activity`` in between, the same ``get`` raises: ``raiseload``
    fails at the attribute rather than handing on a silent ``None``.
    """
    from src.services.daily_loop import DailyLoopService
    from src.services.day_context_loaders import load_activities

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    started = datetime(2026, 9, 22, 7, 30, tzinfo=UTC).replace(tzinfo=None)
    splits = {"lapDTOs": [{"startTimeGMT": "2026-09-22T07:30:00.0", "duration": 600.0}]}
    async with session_factory() as seed:
        seed.add(
            Profile(
                id=user_id,
                display_name="Batch 281 identity",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await seed.flush()
        seed.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                garmin_activity_id=281_000_001,
                activity_name="Indoor Cycling",
                activity_type="indoor_cycling",
                start_utc=started,
                duration_sec=3600.0,
                raw_summary={"activitySplits": splits},
            )
        )
        await seed.flush()

    async with session_factory() as session:
        held = await load_activities(session, user_id, date(2026, 9, 22), "Europe/London")
        assert [row.id for row in held] == [activity_id]
        with pytest.raises(InvalidRequestError):
            _ = held[0].raw_summary

        whole = await DailyLoopService(session)._activity(
            user_id, activity_id, date(2026, 9, 22), "Europe/London"
        )
        assert whole is held[0]
        fetched = await session.get(Activity, activity_id)
        assert fetched is not None
        assert fetched.raw_summary["activitySplits"] == splits
