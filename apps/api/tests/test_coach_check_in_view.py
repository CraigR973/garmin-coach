"""What the coach sees of a check-in, wherever the chat reads one (21–22 Oct).

The check-in form has saved ``bp_systolic`` and ``bp_diastolic`` since July, and
the morning read has always received them, but the chat's check-in view did
not. On 2026-10-14 the coach told Mark blood pressure was not a check-in field
and that it could not see the reading he had entered about twenty minutes
earlier. The view is shared by today's entries, the since-this-read delta and
the ``get_check_ins`` lookup, so one definition fixes all three. Supplements
joined on 22 Oct by Craig's decision, the same way as food.

The serializer and parity tests are pure. The three path tests need a real
Postgres and skip locally (no Postgres on the dev Mac); CI runs them. The
readings and supplements are invented: none is Mark's.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, ManualEntry
from src.models.profile import Profile, UserRole
from src.services.chat_context import ChatContextService, CoachOrigin
from src.services.coach_sections import check_in_state
from src.services.coach_tools import CoachToolbox
from src.services.morning_analysis import _manual_entry_packet

#: Well in the past, so no seeded default plan can share these dates.
DAY = date(2026, 7, 30)
EARLIER_DAY = date(2026, 7, 28)

#: Fields the morning read receives that the chat's view does not. The parity
#: test fails on any new check-in field until it is added to the chat's view or
#: named here with its reason; that tripwire is what blood pressure lacked.
MORNING_ONLY_FIELDS = {
    # The read's word for the score (Batch 91); the chat carries the score.
    "subjectiveLabel",
    # Deliberately not the bare tap (Craig, 22 Oct): the chat gets the answer
    # that day's call used, with its own symptom rule, in ``todaysSymptomAnswer``
    # (Batch 355). The tap alone can contradict the call, e.g. "None" beside a
    # chest floor set from his note.
    "symptoms",
}

#: Invented, and shaped like the form's object.
MAGNESIUM = {"summary": "Magnesium before bed", "items": ["magnesium"]}


def _entry(
    at_utc: datetime,
    *,
    systolic: int | None = None,
    diastolic: int | None = None,
    feel: str | None = None,
    supplements: dict[str, object] | None = None,
    user_id: uuid.UUID | None = None,
) -> ManualEntry:
    return ManualEntry(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        entry_date=at_utc.date(),
        entry_at_utc=at_utc,
        bp_systolic=systolic,
        bp_diastolic=diastolic,
        subjective_score=7,
        feel=feel,
        actual_workout_json={},
        supplements_json=supplements or {},
    )


# ---------------------------------------------------------------------------
# The shared view: pure
# ---------------------------------------------------------------------------


def test_the_chat_check_in_view_carries_blood_pressure() -> None:
    view = check_in_state(
        _entry(datetime.combine(DAY, time(8, 38)), systolic=128, diastolic=82),
    )

    assert view["bpSystolic"] == 128
    assert view["bpDiastolic"] == 82


def test_a_check_in_without_a_reading_says_null_rather_than_dropping_the_field() -> None:
    """A missing key would read as "the coach is not given blood pressure",
    which is the defect; null reads as "no reading on this check-in"."""
    view = check_in_state(_entry(datetime.combine(DAY, time(8, 59)), feel="Legs heavy"))

    assert "bpSystolic" in view
    assert "bpDiastolic" in view
    assert view["bpSystolic"] is None
    assert view["bpDiastolic"] is None


def test_the_chat_check_in_view_carries_what_he_logged_taking() -> None:
    view = check_in_state(_entry(datetime.combine(DAY, time(8, 38)), supplements=MAGNESIUM))

    assert view["supplements"] == MAGNESIUM


def test_a_check_in_with_no_supplements_says_null_as_food_does() -> None:
    view = check_in_state(_entry(datetime.combine(DAY, time(8, 59)), feel="Legs heavy"))

    assert "supplements" in view
    assert view["supplements"] is None
    assert view["food"] is None


def test_the_chat_view_keeps_every_morning_read_field_or_names_why_not() -> None:
    row = _entry(
        datetime.combine(DAY, time(8, 38)), systolic=128, diastolic=82, supplements=MAGNESIUM
    )
    morning = set(_manual_entry_packet(row))
    chat = set(check_in_state(row))

    assert morning - chat == MORNING_ONLY_FIELDS
    # The chat's one addition: his words are data, never instructions.
    assert chat - morning == {"contentRole"}


# ---------------------------------------------------------------------------
# Every path the chat reads a check-in through: Postgres (CI)
# ---------------------------------------------------------------------------


async def _profile(session: AsyncSession, name: str) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


@pytest.mark.asyncio
async def test_todays_reading_reaches_the_coach_beside_a_later_check_in(
    db_conn: AsyncConnection,
) -> None:
    """The 14 Oct shape: a morning check-in with a reading, then a later one
    without, and a question from Home a few minutes after both."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session, "Blood pressure today")
        morning = _entry(
            datetime.combine(DAY, time(8, 38)),
            systolic=128,
            diastolic=82,
            supplements=MAGNESIUM,
            user_id=player.id,
        )
        later = _entry(datetime.combine(DAY, time(8, 59)), feel="Legs heavy", user_id=player.id)
        session.add_all([morning, later])
        await session.commit()

        context = await ChatContextService(session).build(
            player,
            None,
            asked_at_utc=datetime.combine(DAY, time(9, 1)),
            origin=CoachOrigin(kind="home", subject_date=DAY),
        )

    entries = context.app_state["todayCheckIns"]["entries"]
    assert [entry["entryAtUtc"] for entry in entries] == [
        "2026-07-30T08:59:00Z",
        "2026-07-30T08:38:00Z",
    ]
    assert (entries[0]["bpSystolic"], entries[0]["bpDiastolic"]) == (None, None)
    assert (entries[1]["bpSystolic"], entries[1]["bpDiastolic"]) == (128, 82)
    assert entries[0]["supplements"] is None
    assert entries[1]["supplements"] == MAGNESIUM


@pytest.mark.asyncio
async def test_a_reading_logged_after_the_read_reaches_the_conversation_about_it(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session, "Blood pressure since the read")
        analysis = Analysis(
            id=uuid.uuid4(),
            user_id=player.id,
            analysis_type="morning",
            subject_date=DAY,
            generated_at_utc=datetime.combine(DAY, time(6, 30)),
            prompt_version="morning-x",
            verdict="Green",
            context_packet={},
            output_markdown="A full session today.",
            raw_response={},
        )
        session.add(analysis)
        session.add(
            _entry(
                datetime.combine(DAY, time(7, 45)), systolic=117, diastolic=76, user_id=player.id
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(
            player, analysis, asked_at_utc=datetime.combine(DAY, time(9, 0))
        )

    since = context.app_state["sinceThisRead"]["checkInsSinceRead"]
    assert (since[0]["bpSystolic"], since[0]["bpDiastolic"]) == (117, 76)


@pytest.mark.asyncio
async def test_the_check_in_lookup_returns_past_readings(db_conn: AsyncConnection) -> None:
    """What the coach offered on 14 Oct: fetch a dated check-in to see the reading."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session, "Blood pressure history")
        session.add_all(
            [
                _entry(
                    datetime.combine(EARLIER_DAY, time(8, 20)),
                    systolic=131,
                    diastolic=84,
                    supplements=MAGNESIUM,
                    user_id=player.id,
                ),
                _entry(datetime.combine(DAY, time(8, 40)), feel="Fine", user_id=player.id),
            ]
        )
        await session.commit()

        result = await CoachToolbox(session, player).execute(
            tool_use_id="tu_bp",
            name="get_check_ins",
            payload={"startDate": EARLIER_DAY.isoformat(), "endDate": DAY.isoformat()},
        )

    assert result.is_error is False
    rows = json.loads(result.content)["rows"]
    assert [(row["entryDate"], row["bpSystolic"], row["bpDiastolic"]) for row in rows] == [
        (DAY.isoformat(), None, None),
        (EARLIER_DAY.isoformat(), 131, 84),
    ]
    assert [row["supplements"] for row in rows] == [None, MAGNESIUM]
