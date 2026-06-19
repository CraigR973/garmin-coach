"""Tests for prediction reminder targeting helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.services.prediction_reminders import (
    active_players_without_submitted_prediction_for_match,
    submitted_prediction_targets_for_window,
    unpredicted_digest_targets_for_window,
)


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(text(sql), params)).scalar_one()


async def _insert_profile(
    conn: AsyncConnection,
    display_name: str,
    *,
    is_active: bool = True,
    deleted: bool = False,
) -> uuid.UUID:
    return await _scalar(
        conn,
        """
        INSERT INTO profiles (
            id, display_name, pin_hash, role, is_active, deleted_at, email,
            first_name, last_name, site_role
        )
        VALUES (
            gen_random_uuid(), :name,
            '$2b$12$0000000000000000000000000000000000000000000000000000',
            CAST('player' AS player_role),
            :is_active,
            CASE WHEN :deleted THEN now() ELSE NULL END,
            :email,
            'Reminder',
            'User',
            CAST('user' AS site_role)
        )
        RETURNING id
        """,
        name=display_name,
        is_active=is_active,
        deleted=deleted,
        email=f"{display_name}@test.invalid",
    )


async def _insert_match(
    conn: AsyncConnection,
    match_number: int,
    kickoff: datetime,
) -> uuid.UUID:
    return await _scalar(
        conn,
        """
        INSERT INTO matches (
            id, stage, match_number, home_team_placeholder, away_team_placeholder,
            kickoff_utc, status
        )
        VALUES (
            gen_random_uuid(), CAST('group' AS tournament_stage), :match_number,
            'England', 'France', :kickoff, CAST('scheduled' AS match_status)
        )
        RETURNING id
        """,
        match_number=match_number,
        kickoff=kickoff,
    )


async def _insert_prediction(
    conn: AsyncConnection,
    player_id: uuid.UUID,
    match_id: uuid.UUID,
    *,
    submitted_at: datetime | None,
) -> uuid.UUID:
    return await _scalar(
        conn,
        """
        INSERT INTO predictions (
            id, player_id, match_id, predicted_home, predicted_away, submitted_at
        )
        VALUES (gen_random_uuid(), :player_id, :match_id, 2, 1, :submitted_at)
        RETURNING id
        """,
        player_id=player_id,
        match_id=match_id,
        submitted_at=submitted_at,
    )


@pytest.mark.asyncio
async def test_active_players_without_submitted_prediction_for_match(
    db_conn: AsyncConnection,
) -> None:
    kickoff = datetime(2026, 6, 14, 18, 0)
    match_id = await _insert_match(db_conn, 901, kickoff)
    no_prediction = await _insert_profile(db_conn, "reminder_no_prediction")
    draft_only = await _insert_profile(db_conn, "reminder_draft_only")
    submitted = await _insert_profile(db_conn, "reminder_submitted")
    inactive = await _insert_profile(db_conn, "reminder_inactive", is_active=False)
    deleted = await _insert_profile(db_conn, "reminder_deleted", deleted=True)

    await _insert_prediction(db_conn, draft_only, match_id, submitted_at=None)
    await _insert_prediction(db_conn, submitted, match_id, submitted_at=kickoff - timedelta(days=1))
    await _insert_prediction(db_conn, inactive, match_id, submitted_at=None)
    await _insert_prediction(db_conn, deleted, match_id, submitted_at=None)

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        players = await active_players_without_submitted_prediction_for_match(session, match_id)
    finally:
        await session.close()

    assert {p.id for p in players} == {no_prediction, draft_only}


@pytest.mark.asyncio
async def test_unpredicted_digest_targets_excludes_fully_predicted_players(
    db_conn: AsyncConnection,
) -> None:
    window_start = datetime(2026, 6, 14, 0, 0)
    match_one = await _insert_match(db_conn, 902, window_start + timedelta(hours=18))
    match_two = await _insert_match(db_conn, 903, window_start + timedelta(hours=21))
    outside_window = await _insert_match(db_conn, 904, window_start + timedelta(days=1, hours=1))

    fully_predicted = await _insert_profile(db_conn, "reminder_fully_predicted")
    partially_predicted = await _insert_profile(db_conn, "reminder_partially_predicted")
    none_predicted = await _insert_profile(db_conn, "reminder_none_predicted")

    submitted_at = window_start - timedelta(hours=1)
    await _insert_prediction(db_conn, fully_predicted, match_one, submitted_at=submitted_at)
    await _insert_prediction(db_conn, fully_predicted, match_two, submitted_at=submitted_at)
    await _insert_prediction(db_conn, partially_predicted, match_one, submitted_at=submitted_at)
    await _insert_prediction(db_conn, none_predicted, outside_window, submitted_at=submitted_at)

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        targets = await unpredicted_digest_targets_for_window(
            session,
            window_start,
            window_start + timedelta(days=1),
        )
    finally:
        await session.close()

    by_player = {target.player.id: [match.id for match in target.matches] for target in targets}
    assert fully_predicted not in by_player
    assert by_player[partially_predicted] == [match_two]
    assert by_player[none_predicted] == [match_one, match_two]


@pytest.mark.asyncio
async def test_submitted_prediction_targets_excludes_drafts_and_unpredicted_players(
    db_conn: AsyncConnection,
) -> None:
    window_start = datetime(2026, 6, 14, 0, 0)
    match_id = await _insert_match(db_conn, 905, window_start + timedelta(hours=18))
    submitted = await _insert_profile(db_conn, "reminder_confirm_submitted")
    draft = await _insert_profile(db_conn, "reminder_confirm_draft")
    await _insert_profile(db_conn, "reminder_confirm_none")

    submitted_at = window_start - timedelta(hours=1)
    await _insert_prediction(db_conn, submitted, match_id, submitted_at=submitted_at)
    await _insert_prediction(db_conn, draft, match_id, submitted_at=None)

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        targets = await submitted_prediction_targets_for_window(
            session,
            window_start,
            window_start + timedelta(days=1),
        )
    finally:
        await session.close()

    assert [target.player.id for target in targets] == [submitted]
    assert targets[0].match.id == match_id
    assert targets[0].prediction.submitted_at == submitted_at
