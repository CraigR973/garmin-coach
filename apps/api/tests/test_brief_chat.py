"""Tests for Batch 119 — follow-up chat on a brief.

Covers the acceptance pillars:
  119.1/119.2 — a follow-up is answered grounded in the read's own record
  119.3 kickoff decisions — storage/threading, the turn cap, and the
        deterministic (never model-decided) propose-adjustment trigger
  119.4 — guardrails hold (no fabrication beyond the data) and history threads

Batch 178 extends the same surface: context is assembled when the question is
asked, it reaches beyond the single read, and the app's internal vocabulary
never reaches Mark.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import (
    Activity,
    Analysis,
    BriefMessage,
    DailyMetric,
    PlannedWorkout,
)
from src.models.profile import Profile, UserRole
from src.services.anthropic_text import AnthropicApiError
from src.services.brief_chat import (
    MAX_USER_TURNS_PER_ANALYSIS,
    NO_PLUMBING_RULE,
    BriefChatClient,
    BriefChatService,
    internal_vocabulary_hits,
)


class FakeBriefChatClient(BriefChatClient):
    def __init__(self, answer: str = "Grounded answer.") -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "prior_messages": prior_messages,
            }
        )
        return self.answer


def _flat(text: object) -> str:
    """Whitespace-normalized prompt text.

    The system prompt is a wrapped literal, so a phrase can straddle a newline
    (the Batch 175 CI lesson). Assert against normalized text.
    """
    return " ".join(str(text).split())


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


async def _make_profile(session: AsyncSession, name: str = "Chat Test") -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _make_analysis(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    context_packet: dict[str, object] | None = None,
    output_markdown: str = "a brief",
    analysis_type: str = "morning",
) -> Analysis:
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        analysis_type=analysis_type,
        subject_date=datetime(2026, 7, 14, 6, 30).date(),
        generated_at_utc=datetime(2026, 7, 14, 6, 30),
        prompt_version="morning-x",
        context_packet=context_packet or {},
        output_markdown=output_markdown,
        raw_response={},
    )
    session.add(analysis)
    await session.commit()
    return analysis


async def _make_planned_workout(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str = "planned",
) -> PlannedWorkout:
    workout = PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id,
        workout_date=datetime(2026, 7, 14).date(),
        title="Sweet spot",
        workout_type="bike_sweet_spot",
        status=status,
        structured_workout={"segments": []},
    )
    session.add(workout)
    await session.commit()
    return workout


# ---------------------------------------------------------------------------
# Service: grounding, history threading, turn cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_grounds_in_packet_and_stores_both_turns(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(
            session, user.id, context_packet={"verdict": {"status": "Green"}}
        )

        client = FakeBriefChatClient("Because your HRV was strong overnight.")
        turn = await BriefChatService(session).ask(
            user, analysis.id, question="Why is today Green?", client=client
        )

    assert turn.user_message.role == "user"
    assert turn.user_message.content == "Why is today Green?"
    assert turn.assistant_message.role == "assistant"
    assert turn.assistant_message.content == "Because your HRV was strong overnight."
    # The packet is embedded in the system prompt so the answer is grounded.
    prompt = _flat(client.calls[0]["system_prompt"])
    assert "Green" in prompt
    assert "You are talking about this morning's brief" in prompt
    assert "live morning read" in prompt
    assert "the app can propose one" in prompt
    assert "Do not cave to reassurance pressure" in prompt
    assert "General principle:" in prompt
    assert "never invent his metrics, plan, history, readiness, or prescription" in prompt
    assert "Mark's information behind that read" in prompt
    # Batch 178.2: current app state travels alongside the read's own record.
    assert "Where things stand right now" in prompt
    assert "anythingChangedSinceRead" in prompt

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BriefMessage)
            .where(BriefMessage.analysis_id == analysis.id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_ask_threads_prior_history_into_the_next_call(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        service = BriefChatService(session)
        client = FakeBriefChatClient()

        await service.ask(user, analysis.id, question="First question?", client=client)
        await service.ask(user, analysis.id, question="Second question?", client=client)

    second_call_prior = client.calls[1]["prior_messages"]
    assert {"role": "user", "content": "First question?"} in second_call_prior
    assert {"role": "assistant", "content": "Grounded answer."} in second_call_prior


@pytest.mark.asyncio
async def test_ask_enforces_the_per_brief_turn_cap(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        service = BriefChatService(session)
        client = FakeBriefChatClient()

        for i in range(MAX_USER_TURNS_PER_ANALYSIS):
            await service.ask(user, analysis.id, question=f"Question {i}?", client=client)

        with pytest.raises(Exception) as excinfo:
            await service.ask(user, analysis.id, question="One too many?", client=client)

    assert getattr(excinfo.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_ask_only_offers_a_proposal_on_a_deterministic_keyword_match(
    db_conn: AsyncConnection,
) -> None:
    """The model's answer never decides whether to attach a proposal — Mark's
    own question does, and only when there's a deliverable ride today."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        workout = await _make_planned_workout(session, user.id)
        packet = {
            "restDay": {"isRestDay": False},
            "plannedWorkouts": [
                {
                    "id": str(workout.id),
                    "workoutType": "bike_sweet_spot",
                    "status": "planned",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)
        service = BriefChatService(session)
        client = FakeBriefChatClient("Sure, want me to ease it?")

        neutral = await service.ask(user, analysis.id, question="How did I sleep?", client=client)
        wants_ease = await service.ask(
            user, analysis.id, question="Can you ease today's ride?", client=client
        )

    assert neutral.assistant_message.proposed_planned_workout_id is None
    assert wants_ease.assistant_message.proposed_planned_workout_id == workout.id


@pytest.mark.asyncio
async def test_general_endurance_science_question_is_allowed_with_a_label(
    db_conn: AsyncConnection,
) -> None:
    """Batch 175: general training-science can be answered even when the
    packet does not contain that background, provided it is labelled and not
    turned into a personal prescription."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(
            session,
            user.id,
            context_packet={"verdict": {"status": "Amber"}},
            output_markdown="Amber today. Keep the ride easier.",
        )
        client = FakeBriefChatClient(
            "General principle: VO2 adaptations usually need work near VO2 intensity, "
            "but this is not a personal prescription."
        )

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="What %FTP could someone drop VO2 intervals to and keep similar benefit?",
            client=client,
        )

    assert turn.assistant_message.content.startswith("General principle:")
    assert turn.assistant_message.proposed_planned_workout_id is None
    system_prompt = _flat(client.calls[0]["system_prompt"])
    assert "You may answer general, non-personalized endurance-training science" in system_prompt
    assert 'Label those answers with "General principle:"' in system_prompt
    assert "turning them into Mark-specific instructions" in system_prompt


@pytest.mark.asyncio
async def test_mark_specific_question_stays_packet_bound(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(
            session,
            user.id,
            context_packet={"verdict": {"status": "Amber"}},
        )
        client = FakeBriefChatClient("I've no record of his VO2 sessions this block here.")

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="What FTP has Mark usually held for VO2 intervals this block?",
            client=client,
        )

    assert "no record of" in turn.assistant_message.content
    system_prompt = _flat(client.calls[0]["system_prompt"])
    assert "never invent his metrics, plan, history, readiness, or prescription" in system_prompt
    assert "say it the way a coach would" in system_prompt


@pytest.mark.asyncio
async def test_plan_change_request_still_uses_propose_confirm_and_red_floor(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        workout = await _make_planned_workout(session, user.id)
        packet = {
            "verdict": {"status": "Red"},
            "restDay": {"isRestDay": False},
            "plannedWorkouts": [
                {
                    "id": str(workout.id),
                    "workoutType": "bike_vo2",
                    "status": "planned",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)
        client = FakeBriefChatClient("The app can propose an easier version for you to confirm.")

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="Can you reduce today's ride?",
            client=client,
        )

    assert turn.assistant_message.proposed_planned_workout_id == workout.id
    system_prompt = _flat(client.calls[0]["system_prompt"])
    assert "Any actual workout change remains confirm-before-apply" in system_prompt
    assert "never recommend VO2 on a Red day" in system_prompt


@pytest.mark.asyncio
async def test_ask_never_offers_a_proposal_on_a_rest_day(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        packet = {
            "restDay": {"isRestDay": True},
            "plannedWorkouts": [
                {
                    "id": str(uuid.uuid4()),
                    "workoutType": "bike_sweet_spot",
                    "status": "skipped",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)
        client = FakeBriefChatClient()

        turn = await BriefChatService(session).ask(
            user, analysis.id, question="Can you ease today's ride?", client=client
        )

    assert turn.assistant_message.proposed_planned_workout_id is None


@pytest.mark.asyncio
async def test_post_workout_read_chat_is_grounded_and_advisory_only(
    db_conn: AsyncConnection,
) -> None:
    """Batch 150: post-workout reads reuse the same threaded chat but never show
    the morning-only proposal affordance, even if Mark asks for an adjustment."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        workout = await _make_planned_workout(session, user.id)
        packet = {
            "packetType": "post_workout_analysis",
            "activity": {"activityName": "Tempo ride"},
            "execution": {"rating": "on_target"},
            # A morning-shaped field here would have triggered the old implicit
            # packet-only proposal path. Batch 150 gates it by analysis_type.
            "restDay": {"isRestDay": False},
            "plannedWorkouts": [
                {
                    "id": str(workout.id),
                    "workoutType": "bike_sweet_spot",
                    "status": "planned",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(
            session,
            user.id,
            context_packet=packet,
            output_markdown="**Recovery:** keep tomorrow easy.",
            analysis_type="post_workout",
        )
        client = FakeBriefChatClient("It means the ride landed as intended.")

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="Can you adjust tomorrow after that ride?",
            client=client,
        )

    assert turn.assistant_message.content == "It means the ride landed as intended."
    assert turn.assistant_message.proposed_planned_workout_id is None
    prompt = _flat(client.calls[0]["system_prompt"])
    assert "You are talking about the read on his completed session" in prompt
    assert "advisory-only" in prompt
    assert "Do not say the app can propose" in prompt
    assert "Tempo ride" in prompt


# ---------------------------------------------------------------------------
# Batch 178: ask-time context, wider app state, and the register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_sees_an_activity_completed_after_the_read_was_written(
    db_conn: AsyncConnection,
) -> None:
    """178.2: the morning packet froze at 06:30; the ride happened at 17:00.

    Before this batch the ride simply was not in the conversation — the exact
    discontinuity behind Mark's "almost disconnected" report.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(
            session, user.id, context_packet={"verdict": {"status": "Green"}}
        )
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=user.id,
                garmin_activity_id=555000111,
                activity_name="Evening sweet spot",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 7, 14, 17, 30),
                duration_sec=3600,
                avg_power_watts=198,
                raw_summary={},
            )
        )
        await session.commit()

        client = FakeBriefChatClient("You rode 198W average this evening.")
        await BriefChatService(session).ask(
            user, analysis.id, question="How did tonight's ride look?", client=client
        )

    prompt = _flat(client.calls[0]["system_prompt"])
    assert "Evening sweet spot" in prompt
    assert "activitiesCompletedSinceRead" in prompt


@pytest.mark.asyncio
async def test_ask_carries_the_wider_app_state_the_questions_need(
    db_conn: AsyncConnection,
) -> None:
    """178.3: a trend question is answerable from the series the app computed."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    today = datetime.now(UTC).date()
    async with session_factory() as session:
        user = await _make_profile(session)
        for day_offset in range(1, 15):
            session.add(
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=today - timedelta(days=day_offset),
                    hrv_last_night_avg_ms=52,
                    readiness_score=64,
                    resting_heart_rate_bpm=51,
                    raw_payload={},
                )
            )
        session.add(
            Analysis(
                id=uuid.uuid4(),
                user_id=user.id,
                analysis_type="weekly_review",
                subject_date=today - timedelta(days=9),
                generated_at_utc=datetime(2026, 7, 14, 5, 0),
                prompt_version="review-x",
                context_packet={},
                output_markdown="Endurance volume held; sleep was the limiter.",
                raw_response={},
            )
        )
        await session.commit()
        analysis = await _make_analysis(session, user.id)

        client = FakeBriefChatClient("Your HRV has been flat around 52ms.")
        await BriefChatService(session).ask(
            user, analysis.id, question="Has my HRV been trending down?", client=client
        )

    prompt = _flat(client.calls[0]["system_prompt"])
    # The measured series, the week ahead, and the review conclusions Mark was
    # already given — all previously invisible to the conversation.
    assert "hrv_ms" in prompt
    assert "recentWindows" in prompt
    assert "week_ahead_from_today" in prompt
    assert "sleep was the limiter" in prompt


@pytest.mark.asyncio
async def test_ask_retires_a_proposal_for_a_ride_closed_after_the_read(
    db_conn: AsyncConnection,
) -> None:
    """Ask-time state can only remove a stale affordance, never add one.

    The proposal gate itself is unchanged (Batch 179.3 re-keys it); this stops
    the frozen packet offering to ease a ride Mark has already ridden.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        workout = await _make_planned_workout(session, user.id, status="completed")
        packet = {
            "restDay": {"isRestDay": False},
            "plannedWorkouts": [
                {
                    # As it stood at 06:30, before he rode it.
                    "id": str(workout.id),
                    "workoutType": "bike_sweet_spot",
                    "status": "planned",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="Can you ease today's ride?",
            client=FakeBriefChatClient("You've already ridden it."),
        )

    assert turn.assistant_message.proposed_planned_workout_id is None


@pytest.mark.asyncio
async def test_ask_never_hands_the_model_the_apps_internal_vocabulary(
    db_conn: AsyncConnection,
) -> None:
    """178.1: outside the rule that forbids them, the nouns are gone.

    The old prompt said "packet" eight times and told the model to say when the
    packet could not answer, which is how "that isn't in the packet" reached
    Mark. The data blocks below the instructions are machine input; the
    instructions themselves no longer contain the wording to copy.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        client = FakeBriefChatClient("I don't have last winter's rides in front of me here.")

        turn = await BriefChatService(session).ask(
            user,
            analysis.id,
            question="How did last winter's rides compare?",
            client=client,
        )

    # The not-known path reads as a coach's sentence, not a schema complaint.
    assert internal_vocabulary_hits(turn.assistant_message.content) == ()
    system_prompt = str(client.calls[0]["system_prompt"])
    instructions = system_prompt.split("What you wrote in that read:")[0]
    assert internal_vocabulary_hits(instructions.replace(NO_PLUMBING_RULE, "")) == ()
    assert NO_PLUMBING_RULE in _flat(system_prompt)


# ---------------------------------------------------------------------------
# Endpoint: user-scoping + envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_unknown_analysis_is_404(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{uuid.uuid4()}/messages", json={"question": "Hi?"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_message_on_another_users_brief_is_403(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        owner = await _make_profile(session, "Owner")
        other = await _make_profile(session, "Other")
        analysis = await _make_analysis(session, owner.id)

    app.dependency_overrides[get_current_user] = lambda: other
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{analysis.id}/messages", json={"question": "Hi?"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403, response.text
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(BriefMessage))
        assert count == 0


@pytest.mark.asyncio
async def test_get_messages_lists_history_in_order(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        await BriefChatService(session).ask(
            user, analysis.id, question="Q1?", client=FakeBriefChatClient("A1")
        )

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/briefs/{analysis.id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert [row["role"] for row in body] == ["user", "assistant"]
    assert body[0]["content"] == "Q1?"
    assert body[1]["content"] == "A1"


@pytest.mark.asyncio
async def test_get_messages_orders_same_timestamp_user_before_assistant(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    same_time = datetime(2026, 7, 14, 8, 0)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        session.add_all(
            [
                BriefMessage(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    analysis_id=analysis.id,
                    role="assistant",
                    content="A1",
                    created_utc=same_time,
                ),
                BriefMessage(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    analysis_id=analysis.id,
                    role="user",
                    content="Q1?",
                    created_utc=same_time,
                ),
            ]
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/briefs/{analysis.id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert [row["role"] for row in body] == ["user", "assistant"]
    assert [row["content"] for row in body] == ["Q1?", "A1"]


@pytest.mark.asyncio
async def test_post_message_anthropic_billing_failure_returns_clean_error_and_alerts(
    db_conn: AsyncConnection,
) -> None:
    """Batch 143: this LLM call runs in-request, so a day-time Anthropic outage
    (the 2026-07-20/21 credit freeze) used to propagate to a bare 500 whose
    plain-text body the web client couldn't parse. It now returns an honest,
    retryable JSON error (503, not 500), persists no half-written turn, and routes
    a billing outage through the same admin alert as the morning brief (141)."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)

    async def _raise_billing(*args: object, **kwargs: object) -> str:
        raise AnthropicApiError("Your credit balance is too low", reason="billing", status_code=400)

    alert = AsyncMock(return_value=True)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        with (
            patch(
                "src.services.brief_chat.AnthropicBriefChatClient.generate",
                _raise_billing,
            ),
            patch(
                "src.routers.brief_chat.NudgeAlertService.notify_admin_generation_failure",
                alert,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/briefs/{analysis.id}/messages",
                    json={"question": "Why is today Green?"},
                )
    finally:
        app.dependency_overrides.clear()

    # Honest, retryable, and JSON — never a bare 500 with a non-JSON body.
    assert response.status_code == 503, response.text
    assert "try again" in response.json()["detail"].lower()
    # The billing outage alerts the operator exactly once (Batch 141 path).
    alert.assert_awaited_once()
    assert alert.await_args.kwargs["reason"] == "billing"
    # No half-written turn is persisted on failure.
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(BriefMessage))
        assert count == 0


@pytest.mark.asyncio
async def test_post_message_rejects_empty_question(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{analysis.id}/messages", json={"question": ""}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
