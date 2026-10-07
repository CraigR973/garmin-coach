"""Batch 324.4 and 324.5: the coach knows the proposed plan, and can offer a change to it.

While a draft waits, the chat carries a compact view of it (never the raw draft) and a tool
to read any week in full, and an answer may offer one change from the same closed list as
Mark's own taps. The offer is checked against the draft as it stands, stored with the
answer, and applied only by his tap, only at the revision it was made against.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import BriefMessage, KnowledgeBase, Sleep
from src.models.profile import Profile, UserRole
from src.services.block_generator import GENERATED_BLOCK_SECTION, BlockGeneratorService
from src.services.brief_chat import (
    AnthropicSystemPrompt,
    BriefChatClient,
    BriefChatService,
    _build_system_prompt_prefix,
)
from src.services.chat_context import ChatContextService, CoachOrigin
from src.services.coach_tools import CoachToolbox
from src.services.morning_analysis import MorningAnalysisService
from src.services.next_plan import next_plan_draft
from src.services.plan_changes import BY_COACH, BY_MARK, NOT_FOUND_WORDS, apply_change
from src.services.plan_conversation import (
    APPLIED_ALREADY_WORDS,
    COMPACT_CHANGES,
    NO_PLAN_WORDS,
    OFFER_APPLIED,
    OFFER_PROPOSED,
    OFFER_STALE,
    OFFER_UNAVAILABLE,
    PLAN_CHANGE_MARKER_CLOSE,
    PLAN_CHANGE_MARKER_OPEN,
    PLAN_GONE_WORDS,
    STALE_WORDS,
    compact_view,
    extract_plan_change,
    offer_is_current,
    plan_capability_instruction,
    plan_change_offer,
    week_detail,
)

START = date(2026, 10, 19)
TODAY = date(2026, 10, 10)
NOW = datetime(2026, 10, 10, 9, 0)


def _plan() -> dict[str, Any]:
    return next_plan_draft(
        start_date=START,
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 10, 7, 7, 0),
        plan_number=3,
        previous_name="Plan No. 2",
    )


def _marker(payload: dict[str, Any]) -> str:
    return f"{PLAN_CHANGE_MARKER_OPEN}{json.dumps(payload)}{PLAN_CHANGE_MARKER_CLOSE}"


# -- the compact view and the week -----------------------------------------------------------


def test_the_compact_view_is_a_few_thousand_characters_and_never_the_draft() -> None:
    draft = _plan()
    view = compact_view(draft)
    text = json.dumps(view, ensure_ascii=True, sort_keys=True)

    assert len(text) < 8_000
    assert len(json.dumps(draft, ensure_ascii=True)) > 70_000
    assert '"steps"' not in text and "structuredWorkout" not in text
    assert len(view["weeks"]) == 13
    assert view["weeks"][0] == (
        "Week 1 (19–25 Oct, TEST + BUILD, 414 min): Mon s001 Dumbbells A (legs and back) 20 min"
        " · Tue s002 FTP Ramp Test 40 min · Wed s003 Z2 75 min · Thu s004 Sweet Spot (2 × 25 min"
        " @ 89%) 81 min · Sat s005 Z2 + Neuromuscular 58 min · Sat s006 Dumbbells B (upper body)"
        " 20 min · Sun s007 Long Z2 120 min"
    )
    assert view["days"]["vo2"] == "Tuesday"
    assert view["whyThisPlan"] == draft["whyThisPlan"]
    assert view["revision"] == 0 and view["changes"] == []


def test_the_compact_view_lists_his_changes_and_who_made_them() -> None:
    draft = _plan()
    draft = apply_change(
        draft, {"kind": "remove", "session": "s012"}, today=TODAY, by=BY_MARK, at_utc=NOW
    ).draft
    draft = apply_change(
        draft,
        {"kind": "minutes", "session": "s007", "minutes": 150},
        today=TODAY,
        by=BY_COACH,
        at_utc=NOW,
    ).draft

    view = compact_view(draft)

    assert view["revision"] == 2
    assert view["changes"] == [
        "Revision 1 (Mark): Sat 31 Oct, Z2 + Neuromuscular: removed.",
        "Revision 2 (your suggestion, which Mark applied): Sun 25 Oct, Long Z2: 120 min becomes "
        "150 min.",
    ]
    assert "s012" not in view["weeks"][1]


def test_only_the_last_changes_are_listed() -> None:
    draft = _plan()
    for minutes in range(121, 121 + COMPACT_CHANGES + 3):
        draft = apply_change(
            draft,
            {"kind": "minutes", "session": "s007", "minutes": minutes},
            today=TODAY,
            by=BY_MARK,
            at_utc=NOW,
        ).draft
    view = compact_view(draft)
    assert len(view["changes"]) == COMPACT_CHANGES
    assert view["olderChangesNotShown"] == 3


def test_a_week_in_full_carries_targets_and_steps() -> None:
    week = week_detail(_plan(), 2)
    assert week is not None
    vo2 = week["sessions"][1]
    assert (vo2["id"], vo2["date"], vo2["day"], vo2["minutes"]) == (
        "s009",
        "2026-10-27",
        "Tuesday",
        51,
    )
    assert vo2["target"] == "130% FTP in ERG, 30s on / 30s easy"
    assert len(vo2["steps"]) > 3
    assert week_detail(_plan(), 14) is None


# -- the offer -------------------------------------------------------------------------------


def test_the_marker_never_reaches_mark() -> None:
    answer = "Let's drop that Saturday ride.\n" + _marker({"kind": "remove", "session": "s012"})
    cleaned, payload, present = extract_plan_change(answer)
    assert cleaned == "Let's drop that Saturday ride."
    assert json.loads(payload or "") == {"kind": "remove", "session": "s012"}
    assert present is True

    bare, nothing, marked = extract_plan_change("Sure.\n[[PROPOSE_PLAN_CHANGE]]")
    assert (bare, nothing, marked) == ("Sure.", None, True)
    assert extract_plan_change("No offer here.") == ("No offer here.", None, False)


def test_an_offer_is_checked_against_the_draft_as_it_stands() -> None:
    draft = _plan()
    offer = plan_change_offer(
        json.dumps({"kind": "remove", "session": "s012"}), draft, today=TODAY, now=NOW
    )
    assert offer == {
        "status": OFFER_PROPOSED,
        "change": {"kind": "remove", "session": "s012"},
        "summary": "Sat 31 Oct, Z2 + Neuromuscular: removed.",
        "planName": "Plan No. 3",
        "generatedAtUtc": "2026-10-07T07:00:00",
        "revision": 0,
    }
    # Checking it changed nothing.
    assert draft == _plan()


@pytest.mark.parametrize(
    ("payload", "reason", "words"),
    [
        ('{"kind": "remove", "session": "s999"}', "not_found", NOT_FOUND_WORDS),
        ("{not json", "malformed", "That change couldn't be read. Try it again."),
        (None, "malformed", "That change couldn't be read. Try it again."),
        (
            '{"kind": "delete_week", "week": 3}',
            "malformed",
            "That change couldn't be read. Try it again.",
        ),
    ],
)
def test_an_offer_the_draft_cannot_take_is_stored_with_the_words(
    payload: str | None, reason: str, words: str
) -> None:
    offer = plan_change_offer(payload, _plan(), today=TODAY, now=NOW)
    assert offer == {"status": OFFER_UNAVAILABLE, "reason": reason, "words": words}


def test_no_plan_waiting_means_no_offer() -> None:
    offer = plan_change_offer('{"kind": "reset"}', None, today=TODAY, now=NOW)
    assert offer == {"status": OFFER_UNAVAILABLE, "reason": "no_plan", "words": NO_PLAN_WORDS}


def test_an_offer_is_current_only_at_its_revision_of_its_draft() -> None:
    draft = _plan()
    offer = plan_change_offer('{"kind": "remove", "session": "s012"}', draft, today=TODAY, now=NOW)
    assert offer_is_current(offer, draft)
    moved_on = apply_change(
        draft, {"kind": "remove", "session": "s013"}, today=TODAY, by=BY_MARK, at_utc=NOW
    ).draft
    assert not offer_is_current(offer, moved_on)
    regenerated = {**draft, "generatedAtUtc": "2026-10-12T07:00:00"}
    assert not offer_is_current(offer, regenerated)
    assert not offer_is_current(offer, None)


def test_the_capability_states_the_closed_list_only_while_a_plan_waits() -> None:
    assert plan_capability_instruction(None, today=TODAY) is None
    text = plan_capability_instruction(_plan(), today=TODAY) or ""
    for kind in (
        "days",
        "start",
        "intervals",
        "minutes",
        "title",
        "move",
        "remove",
        "add",
        "reset",
    ):
        assert f'"kind": "{kind}"' in text, kind
    assert "a Monday from 2026-10-12 to 2026-12-07" in text
    assert PLAN_CHANGE_MARKER_OPEN in text
    assert "never say you have changed, applied, moved or scheduled anything" in text
    assert "revision" not in text  # in the plan's view, not in the cached prefix


def test_the_coachs_prompt_carries_the_plan_capability_only_with_a_plan() -> None:
    capability = plan_capability_instruction(_plan(), today=TODAY)
    with_plan = _build_system_prompt_prefix(
        analysis=None,
        origin=CoachOrigin(kind="next_plan"),
        local_today=TODAY,
        adjustable_set=None,
        plan_capability=capability,
    )
    without = _build_system_prompt_prefix(
        analysis=None, origin=CoachOrigin(kind="next_plan"), local_today=TODAY, adjustable_set=None
    )
    assert capability is not None and capability in with_plan
    assert PLAN_CHANGE_MARKER_OPEN not in without
    assert "the plan builder, where his proposed next plan is waiting" in with_plan


# -- the tool --------------------------------------------------------------------------------


class _DraftSession:
    def __init__(self, content: dict[str, Any] | None) -> None:
        self.content = content

    async def scalar(self, statement: Any) -> KnowledgeBase | None:
        if self.content is None:
            return None
        return KnowledgeBase(
            user_id=uuid.uuid4(),
            section=GENERATED_BLOCK_SECTION,
            version=1,
            is_active=True,
            source="block_generator",
            content=self.content,
        )


def _player() -> Profile:
    return Profile(
        id=uuid.uuid4(), display_name="Mark", role=UserRole.admin, timezone="Europe/London"
    )


async def test_the_tool_reads_a_week_of_the_waiting_plan() -> None:
    toolbox = CoachToolbox(_DraftSession(_plan()), _player())  # type: ignore[arg-type]
    result = await toolbox.execute(
        tool_use_id="t1", name="get_proposed_plan_week", payload={"weekNumber": 2}
    )
    assert result.is_error is False
    body = json.loads(result.content)
    assert [row["id"] for row in body["rows"]] == [f"s{n:03d}" for n in range(8, 15)]
    assert body["week"]["label"] == "BUILD"
    assert body["planName"] == "Plan No. 3"


@pytest.mark.parametrize(
    ("content", "payload", "message"),
    [
        (None, {"weekNumber": 2}, "There is no proposed plan waiting for Mark."),
        ("plan", {"weekNumber": 14}, "The proposed plan has weeks 1 to 13."),
        ("plan", {"weekNumber": "two"}, "weekNumber must be a whole number, the week of the plan."),
    ],
)
async def test_the_tool_says_plainly_when_it_has_nothing(
    content: str | None, payload: dict[str, Any], message: str
) -> None:
    draft = _plan() if content else None
    toolbox = CoachToolbox(_DraftSession(draft), _player())  # type: ignore[arg-type]
    result = await toolbox.execute(tool_use_id="t1", name="get_proposed_plan_week", payload=payload)
    assert (result.is_error, result.content) == (True, message)


async def test_a_locked_plan_is_not_a_waiting_plan() -> None:
    locked = {**_plan(), "status": "locked"}
    toolbox = CoachToolbox(_DraftSession(locked), _player())  # type: ignore[arg-type]
    result = await toolbox.execute(
        tool_use_id="t1", name="get_proposed_plan_week", payload={"weekNumber": 1}
    )
    assert result.is_error is True


# -- on Postgres: the packets, the answer, and his tap ---------------------------------------

DB_START = date(2026, 6, 1)
DB_ASKED_AT = datetime(2026, 5, 20, 9, 0)


class _ScriptedCoach(BriefChatClient):
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.system_prompts: list[AnthropicSystemPrompt] = []

    async def generate(
        self,
        *,
        system_prompt: AnthropicSystemPrompt,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
        toolbox: CoachToolbox | None = None,
    ) -> str:
        self.system_prompts.append(system_prompt)
        return self.answer


async def _db_player(session: AsyncSession) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Plan Chat",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    session.add(
        Sleep(
            user_id=player.id,
            calendar_date=DB_ASKED_AT.date(),
            sleep_start_utc=datetime(2026, 5, 19, 22, 30),
            sleep_end_utc=datetime(2026, 5, 20, 6, 30),
            score=80,
            raw_payload={},
            factors_json={},
        )
    )
    session.add(
        KnowledgeBase(
            user_id=player.id,
            section="profile",
            version=1,
            is_active=True,
            source="test",
            content={"athleteName": "Mark", "ftpWatts": 280},
            updated_by_profile_id=player.id,
        )
    )
    await session.commit()
    return player


@pytest.mark.asyncio
async def test_on_postgres_no_packet_carries_the_draft_but_the_chat_sees_the_plan(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_player(session)
        await BlockGeneratorService(session).generate(player, start_date=DB_START)

        context = await ChatContextService(session).build(player, None, asked_at_utc=DB_ASKED_AT)
        chat = json.dumps(context.app_state, ensure_ascii=True, default=str)
        morning = json.dumps(
            await MorningAnalysisService(session).assemble_context_packet(
                player, date(2026, 5, 20)
            ),
            ensure_ascii=True,
            default=str,
        )

        sections = [s["section"] for s in context.app_state["knowledgeBase"]["sections"]]
        assert GENERATED_BLOCK_SECTION not in sections
        assert '"steps"' not in json.dumps(context.app_state["proposedPlan"])
        assert context.app_state["proposedPlan"]["weeks"][0].startswith("Week 1 (1–7 Jun")
        assert context.proposed_plan is not None and context.proposed_plan["revision"] == 0
        assert GENERATED_BLOCK_SECTION not in morning
        assert "Week 1 opens with an FTP ramp test" not in morning
        assert len(chat) < 60_000


@pytest.mark.asyncio
async def test_on_postgres_an_offer_is_stored_and_applied_with_one_tap(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_player(session)
        await BlockGeneratorService(session).generate(player, start_date=DB_START)
        coach = _ScriptedCoach(
            "Two dumbbell days and a sprint ride is a lot for one Saturday. Drop the ride?\n"
            + _marker({"kind": "remove", "session": "s012"})
        )
        service = BriefChatService(session)

        turn = await service.ask(
            player,
            question="Is Saturday too much?",
            origin_kind="next_plan",
            client=coach,
            now=DB_ASKED_AT,
        )

        message = turn.assistant_message
        assert message.content.endswith("Drop the ride?")
        assert message.proposed_plan_change is not None
        assert message.proposed_plan_change["status"] == OFFER_PROPOSED
        assert message.proposed_plan_change["revision"] == 0
        prompt = json.dumps(coach.system_prompts[0])
        assert "PROPOSE_PLAN_CHANGE" in prompt and "proposedPlan" in prompt

        applied = await service.apply_plan_change(player, message.id)

        assert applied.proposed_plan_change is not None
        assert applied.proposed_plan_change["status"] == OFFER_APPLIED
        assert applied.proposed_plan_change["appliedRevision"] == 1
        draft = await BlockGeneratorService(session).get_draft(player)
        assert draft is not None and draft["revision"] == 1
        assert draft["changes"][0]["by"] == BY_COACH
        with pytest.raises(HTTPException) as again:
            await service.apply_plan_change(player, message.id)
        assert (again.value.status_code, again.value.detail) == (409, APPLIED_ALREADY_WORDS)


@pytest.mark.asyncio
async def test_on_postgres_an_offer_the_plan_has_moved_past_is_refused_honestly(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_player(session)
        builder = BlockGeneratorService(session)
        await builder.generate(player, start_date=DB_START)
        coach = _ScriptedCoach(
            "Shorter?\n" + _marker({"kind": "minutes", "session": "s007", "minutes": 100})
        )
        service = BriefChatService(session)
        turn = await service.ask(
            player, question="Shorter long ride?", client=coach, now=DB_ASKED_AT
        )
        await builder.change(player, {"kind": "remove", "session": "s012"})  # he moves on

        with pytest.raises(HTTPException) as stale:
            await service.apply_plan_change(player, turn.assistant_message.id)

        assert (stale.value.status_code, stale.value.detail) == (409, STALE_WORDS)
        row = await session.scalar(
            select(BriefMessage).where(BriefMessage.id == turn.assistant_message.id)
        )
        assert row is not None and row.proposed_plan_change is not None
        assert row.proposed_plan_change["status"] == OFFER_STALE
        draft = await builder.get_draft(player)
        assert draft is not None and draft["revision"] == 1  # only his own change

        coach.answer = "Remove it?\n" + _marker({"kind": "remove", "session": "s013"})
        current = await service.ask(player, question="And Saturday?", client=coach, now=DB_ASKED_AT)
        assert current.assistant_message.proposed_plan_change is not None
        assert current.assistant_message.proposed_plan_change["revision"] == 1
        await builder.discard(player)  # he declines the plan before tapping it
        with pytest.raises(HTTPException) as gone:
            await service.apply_plan_change(player, current.assistant_message.id)
        assert (gone.value.status_code, gone.value.detail) == (409, PLAN_GONE_WORDS)

        after = await service.ask(player, question="Anything else?", client=coach, now=DB_ASKED_AT)
        assert after.assistant_message.proposed_plan_change == {
            "status": OFFER_UNAVAILABLE,
            "reason": "no_plan",
            "words": NO_PLAN_WORDS,
        }
