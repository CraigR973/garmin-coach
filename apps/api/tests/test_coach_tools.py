"""The lookups the coach can reach for, and the boundaries around them (257.2).

Two kinds of test here. The definition and validation tests are pure and run
everywhere. The query tests need a real Postgres and skip locally (no Postgres
on the dev Mac), so CI is where the *scoping* assertions actually execute —
which is the reason they are written as "a second profile's rows are invisible"
rather than "this profile's rows come back".
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, ManualEntry, Sleep
from src.models.profile import Profile, UserRole
from src.services.chat_context import _FETCHABLE_OMISSIONS, _field_truncations
from src.services.coach_tools import (
    ACTIVITY_TYPES,
    COACH_TOOLS,
    MAX_RESULT_CHARS,
    MAX_ROWS,
    MAX_SPAN_DAYS,
    READABLE_ANALYSIS_TYPES,
    TOOL_NAMES,
    CoachToolbox,
)

TODAY = date(2026, 9, 6)


# ---------------------------------------------------------------------------
# Definitions — pure
# ---------------------------------------------------------------------------


def test_every_tool_is_strict_with_a_closed_schema() -> None:
    """``strict`` is top-level, with ``additionalProperties: false`` + ``required``.

    That is what makes the validation in ``coach_tools`` about *meaning* — is
    that a real date, is the span sane — rather than about shape.
    """
    for tool in COACH_TOOLS:
        assert tool["strict"] is True, tool["name"]
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False, tool["name"]
        assert schema["required"], tool["name"]
        assert set(schema["required"]) <= set(schema["properties"]), tool["name"]


def test_the_tool_list_is_deterministically_ordered() -> None:
    """It renders at position 0, ahead of the cached system prefix.

    A tool set that varied per request, or serialized in a different order, is
    one of only two things that force a full cache rebuild on every question —
    and it would do it silently, showing up as a bill rather than an error.
    """
    names = [tool["name"] for tool in COACH_TOOLS]
    assert names == sorted(names)
    assert tuple(names) == TOOL_NAMES
    assert json.dumps(COACH_TOOLS, sort_keys=True) == json.dumps(COACH_TOOLS, sort_keys=True)


def test_every_tool_description_says_when_to_call_it() -> None:
    """Trigger conditions, not just capability.

    The whole point of this batch is a coach that reaches for a lookup instead of
    apologising, and on recent models the "call this when…" clause is what moves
    the should-call rate.
    """
    for tool in COACH_TOOLS:
        assert "Call this when" in tool["description"] or "Fetch this" in tool["description"], tool[
            "name"
        ]


def test_the_tool_set_is_read_only() -> None:
    """The propose/confirm rail stays the only mutation path (Decision #29).

    Asserted on the names rather than trusted to review: a write reachable from
    here would be a plan change the model could make without Mark confirming it.
    """
    for name in TOOL_NAMES:
        assert name.startswith("get_"), name


def test_every_fetchable_omission_names_a_tool_that_exists() -> None:
    """``omittedForLengthFetchWith`` promises a lookup; the promise must be real.

    Batch 257.5 turned "say it is not in front of you" into "go and get it". A
    label mapped to a tool that does not exist would trade a truthful refusal for
    a failed one — worse than the sentence it replaced.
    """
    assert set(_FETCHABLE_OMISSIONS.values()) <= set(TOOL_NAMES)


def test_the_truncation_that_actually_fires_is_fetchable() -> None:
    """The whole-section drops are the rare case; a field truncation is the real one.

    Measured on Mark's real 2026-09-06 block, ``omittedForLength`` was exactly
    ``['latestReviews.conclusions(truncated)']`` and nothing else — the block was
    inside budget, so no section was dropped, but ``REVIEW_CONCLUSION_MAX_CHARS``
    still cut a review's conclusion at 900 characters. Mapping only the section
    drops would have shipped a fetch-back mechanism that never fired on the one
    case it was built for.
    """
    labels = _field_truncations(
        latest_reviews=[{"conclusions": "a long conclusion..."}],
        plan_changes=[{"summary": "a long summary..."}],
    )

    assert _FETCHABLE_OMISSIONS[labels[0]] == "get_read"
    # And the other one stays honestly unmapped: plan-action audit rows are not
    # reads Mark was ever shown, so no tool returns them.
    assert labels[1] not in _FETCHABLE_OMISSIONS


def test_reads_the_coach_can_quote_are_reads_mark_was_shown() -> None:
    """``driver_correlation`` and friends are machine-facing rows.

    Naming them here would let the coach quote Mark something he has never seen
    as though it were a read he had.
    """
    assert "driver_correlation" not in READABLE_ANALYSIS_TYPES
    assert "state_change_coach" not in READABLE_ANALYSIS_TYPES
    assert "morning" in READABLE_ANALYSIS_TYPES


# ---------------------------------------------------------------------------
# Validation — pure; the session is never reached
# ---------------------------------------------------------------------------


def _offline_toolbox() -> CoachToolbox:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Offline",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    return CoachToolbox(cast(Any, None), player)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"startDate": "not-a-date", "endDate": "2026-08-12"}, "not an ISO date"),
        ({"endDate": "2026-08-12"}, "startDate is required"),
        ({"startDate": "2026-08-12", "endDate": "2026-08-01"}, "before startDate"),
        (
            {"startDate": "2020-01-01", "endDate": "2026-01-01"},
            f"longer than {MAX_SPAN_DAYS} days",
        ),
        ("just a string", "was not an object"),
    ],
)
async def test_a_bad_input_becomes_a_recoverable_error_not_an_exception(
    payload: Any, expected: str
) -> None:
    """A refused lookup must not cost Mark his answer.

    ``strict`` guarantees the shape of a tool input; it does not guarantee that
    "2026-13-45" is a date or that the caller put the earlier one first. Those
    come back as ``is_error`` so the model can correct itself in the next round.
    """
    result = await _offline_toolbox().execute(
        tool_use_id="tu_1", name="get_sleep_nights", payload=payload
    )

    assert result.is_error is True
    assert expected in result.content


@pytest.mark.asyncio
async def test_an_unknown_tool_name_is_refused_rather_than_raised() -> None:
    result = await _offline_toolbox().execute(tool_use_id="tu_1", name="rm_rf", payload={})

    assert result.is_error is True
    assert "No such tool" in result.content


@pytest.mark.asyncio
async def test_an_unreadable_read_type_is_refused() -> None:
    result = await _offline_toolbox().execute(
        tool_use_id="tu_1",
        name="get_read",
        payload={"readType": "driver_correlation", "subjectDate": "2026-09-01"},
    )

    assert result.is_error is True
    assert "readType must be one of" in result.content


@pytest.mark.asyncio
async def test_an_unknown_activity_type_is_refused() -> None:
    result = await _offline_toolbox().execute(
        tool_use_id="tu_1",
        name="get_activities",
        payload={
            "startDate": "2026-08-01",
            "endDate": "2026-08-12",
            "activityType": "dumbbells",
        },
    )

    assert result.is_error is True
    assert "activityType must be one of" in result.content


# ---------------------------------------------------------------------------
# Queries — need Postgres, so these run in CI
# ---------------------------------------------------------------------------


async def _seed_player(session: AsyncSession, name: str) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


async def _seed_night(session: AsyncSession, user_id: uuid.UUID, day: date, rem: int) -> None:
    session.add(
        Sleep(
            id=uuid.uuid4(),
            user_id=user_id,
            calendar_date=day,
            duration_sec=6 * 3600,
            rem_sleep_sec=rem * 60,
            score=70,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_a_night_outside_the_carried_fortnight_can_be_fetched(
    db_conn: AsyncConnection,
) -> None:
    """The question this batch exists for: a specific night, weeks back.

    ``sleepHistory`` carries fourteen nights. Mark asks about August in
    September, and until now the honest answer was that it was not in front of
    the coach.
    """
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Fetcher")
        old_night = TODAY - timedelta(days=25)
        await _seed_night(session, player.id, old_night, rem=104)

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_sleep_nights",
            payload={"startDate": old_night.isoformat(), "endDate": old_night.isoformat()},
        )

    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["rowCount"] == 1
    assert payload["rows"][0]["remSleepMin"] == 104
    assert payload["rows"][0]["calendarDate"] == old_night.isoformat()


@pytest.mark.asyncio
async def test_a_lookup_never_reaches_another_profiles_rows(db_conn: AsyncConnection) -> None:
    """The one assertion that has to hold for every tool.

    The toolbox holds the authenticated profile, so there is no call site that
    could pass a different ``user_id`` — this proves the queries honour it. A
    second profile has appeared in production once already (2026-08-24, origin
    unknown), so "there is only one user" is not the defence.
    """
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        asker = await _seed_player(session, "Asker")
        other = await _seed_player(session, "Other")
        day = TODAY - timedelta(days=30)
        await _seed_night(session, other.id, day, rem=99)
        session.add(
            ManualEntry(
                id=uuid.uuid4(),
                user_id=other.id,
                entry_date=day,
                entry_at_utc=datetime.combine(day, time(9, 0)),
                notes="the other profile's private note",
            )
        )
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=other.id,
                # NOT NULL with no default, and unique per (user, activity) — a
                # fixture that omits it passes locally, where every `db_conn`
                # test skips, and fails on its first ever run in CI.
                garmin_activity_id=987654321,
                activity_name="Their ride",
                activity_type="cycling",
                start_utc=datetime.combine(day, time(10, 0)),
                duration_sec=3600,
            )
        )
        session.add(
            Analysis(
                id=uuid.uuid4(),
                user_id=other.id,
                analysis_type="morning",
                subject_date=day,
                generated_at_utc=datetime.combine(day, time(6, 30)),
                prompt_version="morning-x",
                context_packet={},
                output_markdown="their private brief",
                raw_response={},
            )
        )
        await session.commit()

        toolbox = CoachToolbox(session, asker)
        span = {"startDate": day.isoformat(), "endDate": day.isoformat()}
        results = [
            await toolbox.execute(tool_use_id="t1", name="get_sleep_nights", payload=span),
            await toolbox.execute(tool_use_id="t2", name="get_activities", payload=span),
            await toolbox.execute(tool_use_id="t3", name="get_check_ins", payload=span),
            await toolbox.execute(
                tool_use_id="t4",
                name="get_read",
                payload={"readType": "morning", "subjectDate": day.isoformat()},
            ),
        ]

    for result in results:
        assert result.is_error is False
        assert json.loads(result.content)["rowCount"] == 0
    assert "private note" not in " ".join(r.content for r in results)
    assert "private brief" not in " ".join(r.content for r in results)


@pytest.mark.asyncio
async def test_a_read_lookup_returns_the_prose_and_never_the_packet(
    db_conn: AsyncConnection,
) -> None:
    """What a question about an earlier read needs is what Mark was shown.

    The packet is tens of thousands of characters of the app's own workings — on
    2026-09-06 the morning read's was 72,351 — so returning it would spend more
    context than the whole live block to answer one question.
    """
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Reader")
        day = TODAY - timedelta(days=40)
        session.add(
            Analysis(
                id=uuid.uuid4(),
                user_id=player.id,
                analysis_type="morning",
                subject_date=day,
                generated_at_utc=datetime.combine(day, time(6, 30)),
                prompt_version="morning-x",
                context_packet={"secretPlumbing": "should never be quoted"},
                output_markdown="# Morning Read\n\nAmber today.",
                verdict="Amber",
                raw_response={},
            )
        )
        await session.commit()

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_read",
            payload={"readType": "morning", "subjectDate": day.isoformat()},
        )

    payload = json.loads(result.content)
    assert payload["rows"][0]["whatYouWrote"] == "# Morning Read\n\nAmber today."
    assert payload["rows"][0]["verdict"] == "Amber"
    assert "secretPlumbing" not in result.content


@pytest.mark.asyncio
async def test_an_absent_read_says_none_was_written_not_that_it_is_hidden(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Empty")

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_read",
            payload={"readType": "weekly_review", "subjectDate": "2026-01-05"},
        )

    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["rowCount"] == 0
    assert "none was written" in payload["meaning"]


@pytest.mark.asyncio
async def test_a_result_that_does_not_fit_says_so_rather_than_going_quiet(
    db_conn: AsyncConnection,
) -> None:
    """A truncation that looked like an absence is the failure this whole app
    keeps having to close. A tool result is no different: the coach must be able
    to tell "there are no nights there" from "there are more than fitted"."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Chatty")
        start = TODAY - timedelta(days=MAX_ROWS + 5)
        for offset in range(MAX_ROWS + 5):
            day = start + timedelta(days=offset)
            session.add(
                ManualEntry(
                    id=uuid.uuid4(),
                    user_id=player.id,
                    entry_date=day,
                    entry_at_utc=datetime.combine(day, time(9, 0)),
                    notes="x" * 900,
                )
            )
        await session.commit()

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_check_ins",
            payload={"startDate": start.isoformat(), "endDate": TODAY.isoformat()},
        )

    payload = json.loads(result.content)
    assert len(result.content) <= MAX_RESULT_CHARS
    assert payload["rowCount"] <= MAX_ROWS
    assert "truncated" in payload
    assert "Narrow the window" in payload["truncated"]


@pytest.mark.asyncio
async def test_a_sql_row_cap_is_named_even_when_small_rows_fit(
    db_conn: AsyncConnection,
) -> None:
    """This is the case the old character-cap test could never exercise.

    Before Batch 259 the SQL query returned only 40 of these 90 short notes and
    ``_result`` had no way to know the other 50 existed, so this assertion fails
    on the old query even though the serialized result is well below 12k chars.
    """
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Many short notes")
        start = TODAY - timedelta(days=89)
        for offset in range(90):
            day = start + timedelta(days=offset)
            session.add(
                ManualEntry(
                    id=uuid.uuid4(),
                    user_id=player.id,
                    entry_date=day,
                    entry_at_utc=datetime.combine(day, time(9, 0)),
                    notes="short note",
                )
            )
        await session.commit()

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_check_ins",
            payload={"startDate": start.isoformat(), "endDate": TODAY.isoformat()},
        )

    payload = json.loads(result.content)
    assert len(result.content) < MAX_RESULT_CHARS
    assert payload["rowCount"] == MAX_ROWS
    assert "more matching rows exist" in payload["truncated"]


@pytest.mark.asyncio
async def test_an_activity_type_filter_returns_strength_sessions_from_a_mixed_range(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed_player(session, "Strength lookup")
        start = TODAY - timedelta(days=89)
        for offset in range(90):
            day = start + timedelta(days=offset)
            activity_type = "strength_training" if offset % 3 == 0 else "indoor_cycling"
            session.add(
                Activity(
                    id=uuid.uuid4(),
                    user_id=player.id,
                    garmin_activity_id=800_000 + offset,
                    activity_name=(
                        "Strength work" if activity_type == "strength_training" else "Ride"
                    ),
                    activity_type=activity_type,
                    start_utc=datetime.combine(day, time(10, 0)),
                    duration_sec=3600,
                )
            )
        await session.commit()

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_1",
            name="get_activities",
            payload={
                "startDate": start.isoformat(),
                "endDate": TODAY.isoformat(),
                "activityType": "strength_training",
            },
        )

    payload = json.loads(result.content)
    assert payload["requestedActivityType"] == "strength_training"
    assert payload["rowCount"] == 30
    assert {row["activityType"] for row in payload["rows"]} == {"strength_training"}


def test_activity_type_schema_matches_the_validated_production_types() -> None:
    activities = next(tool for tool in COACH_TOOLS if tool["name"] == "get_activities")
    schema = activities["input_schema"]

    assert schema["required"] == ["startDate", "endDate"]
    assert schema["properties"]["activityType"]["enum"] == list(ACTIVITY_TYPES)
