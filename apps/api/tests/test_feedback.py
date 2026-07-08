"""Tests for Batch 64 — rate & correct any summary (feedback primitive, #137).

Covers the acceptance pillars:
  64.1 — feedback table/model (exercised through every DB-backed case below)
  64.2 — PUT endpoint upsert + user-scoping (404/403) + envelope
  64.4 — recent corrections feed the next read's context packet
Plus rating-axis validation and the daily-loop feedback-surfacing helper.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import Analysis, Feedback
from src.models.profile import Profile, UserRole
from src.services.feedback import FeedbackService


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


async def _make_profile(session: AsyncSession, name: str = "Feedback Test") -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name=name,
        pin_hash="x" * 60,
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
    analysis_type: str = "morning",
    generated_at: datetime | None = None,
) -> Analysis:
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        analysis_type=analysis_type,
        subject_date=(generated_at or datetime(2026, 7, 8, 6, 30)).date(),
        generated_at_utc=generated_at or datetime(2026, 7, 8, 6, 30),
        prompt_version="morning-x",
        context_packet={},
        output_markdown="a read",
        raw_response={},
    )
    session.add(analysis)
    await session.commit()
    return analysis


# ---------------------------------------------------------------------------
# Endpoint: upsert + user-scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_feedback_creates_then_upserts_single_row(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.put(
                f"/api/v1/analyses/{analysis.id}/feedback",
                json={"kind": "summary", "rating": "a_bit_off", "correctionText": "slept fine"},
            )
            second = await client.put(
                f"/api/v1/analyses/{analysis.id}/feedback",
                json={"kind": "summary", "rating": "spot_on", "correctionText": None},
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["errors"] == []
    assert body["data"]["rating"] == "a_bit_off"
    assert body["data"]["correctionText"] == "slept fine"
    assert body["data"]["analysisId"] == str(analysis.id)

    assert second.status_code == 200, second.text
    assert second.json()["data"]["rating"] == "spot_on"
    # The correction is cleared on the re-rate, and there is exactly one row.
    assert second.json()["data"]["correctionText"] is None

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.analysis_id == analysis.id)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_put_feedback_unknown_analysis_is_404(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/analyses/{uuid.uuid4()}/feedback",
                json={"kind": "summary", "rating": "spot_on"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_put_feedback_on_another_users_analysis_is_403(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        owner = await _make_profile(session, "Owner")
        other = await _make_profile(session, "Other")
        analysis = await _make_analysis(session, owner.id)

    # Authenticate as `other`, who does not own the analysis.
    app.dependency_overrides[get_current_user] = lambda: other
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/analyses/{analysis.id}/feedback",
                json={"kind": "summary", "rating": "spot_on"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403, response.text
    # No row was written for the non-owner.
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Feedback))
        assert count == 0


@pytest.mark.asyncio
async def test_put_feedback_rejects_rating_that_does_not_match_kind(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 'agree' is a suggestion rating, not valid for a summary.
            response = await client.put(
                f"/api/v1/analyses/{analysis.id}/feedback",
                json={"kind": "summary", "rating": "agree"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Service: recent corrections + feedback surfacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_corrections_are_newest_first_and_text_only(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        old = await _make_analysis(session, user.id, generated_at=datetime(2026, 7, 1, 6, 30))
        new = await _make_analysis(session, user.id, generated_at=datetime(2026, 7, 5, 6, 30))
        rated_only = await _make_analysis(
            session, user.id, generated_at=datetime(2026, 7, 6, 6, 30)
        )
        service = FeedbackService(session)
        await service.upsert(
            user, old.id, kind="summary", rating="way_off", correction_text="old note"
        )
        await service.upsert(
            user, new.id, kind="summary", rating="a_bit_off", correction_text="new note"
        )
        # A bare rating with no correction must not appear in the fed-forward list.
        await service.upsert(
            user, rated_only.id, kind="summary", rating="spot_on", correction_text=None
        )

        corrections = await service.recent_corrections(user.id)

    assert [c.correction_text for c in corrections] == ["new note", "old note"]
    assert all(c.correction_text for c in corrections)
    assert corrections[0].analysis_type == "morning"


@pytest.mark.asyncio
async def test_feedback_for_analyses_is_scoped_and_keyed(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session, "A")
        other = await _make_profile(session, "B")
        mine = await _make_analysis(session, user.id)
        theirs = await _make_analysis(session, other.id)
        service = FeedbackService(session)
        await service.upsert(user, mine.id, kind="summary", rating="spot_on", correction_text=None)
        await service.upsert(
            other, theirs.id, kind="summary", rating="way_off", correction_text="x"
        )

        mapping = await service.feedback_for_analyses(user.id, [mine.id, theirs.id])

    # Only the caller's own analysis feedback is returned.
    assert set(mapping.keys()) == {mine.id}
    assert mapping[mine.id].rating == "spot_on"


# ---------------------------------------------------------------------------
# 64.4 — corrections reach the morning context packet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_morning_packet_includes_recent_corrections(db_conn: AsyncConnection) -> None:
    from src.services.morning_analysis import MorningAnalysisService

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    subject_date = datetime(2026, 7, 8, 6, 30).date()
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id, generated_at=datetime(2026, 7, 7, 6, 30))
        await FeedbackService(session).upsert(
            user,
            analysis.id,
            kind="summary",
            rating="way_off",
            correction_text="my watch missed my 03:00 wake",
        )

    async with session_factory() as session:
        fresh_user = await session.get(Profile, user.id)
        assert fresh_user is not None
        packet = await MorningAnalysisService(session).assemble_context_packet(
            fresh_user, subject_date
        )

    corrections = packet["recentCorrections"]
    assert any(c["correction"] == "my watch missed my 03:00 wake" for c in corrections)
    assert "acknowledge_recent_user_corrections_when_relevant" in packet["prompt"]["outputRules"]
