"""Tests for the bootstrap_admin CLI script.

Exercises both modes (create + --promote) and every refusal path against
a mocked AsyncSession — no Postgres required, hermetic by default.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.bootstrap_admin import (
    MAX_PLAYERS,
    BootstrapError,
    create_admin,
    promote_existing,
)
from src.models.prediction import NotificationPreferences
from src.models.profile import PlayerRole, Profile


def _scalar_result(value: object) -> MagicMock:
    """Mimic Result.scalar_one_or_none() / .scalar() returning ``value``."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar.return_value = value
    return r


def _session_with(execute_results: list[object]) -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.execute = AsyncMock(side_effect=[_scalar_result(v) for v in execute_results])
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


def _existing(display_name: str, role: PlayerRole = PlayerRole.player) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = display_name
    p.role = role
    p.deleted_at = None
    return p


# ---------------------------------------------------------------------------
# create_admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_admin_inserts_profile_and_prefs() -> None:
    # 1st execute: name lookup -> not found. 2nd: count -> 0.
    session = _session_with([None, 0])

    profile = await create_admin(
        session,
        display_name="Craig",
        pin="1234",
        timezone="Europe/London",
    )

    assert profile.display_name == "Craig"
    assert profile.role == PlayerRole.admin
    assert profile.timezone == "Europe/London"
    assert profile.pin_hash != "1234"  # hashed, not stored plain
    assert profile.pin_hash.startswith("$2")  # bcrypt prefix

    # Both rows added: profile + notification prefs
    added_types = [type(call.args[0]) for call in session.add.call_args_list]
    assert Profile in added_types
    assert NotificationPreferences in added_types

    # prefs row references the new profile
    prefs_arg = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], NotificationPreferences)
    )
    assert prefs_arg.player_id == profile.id


@pytest.mark.asyncio
async def test_create_admin_refuses_when_pin_empty() -> None:
    session = _session_with([])

    with pytest.raises(BootstrapError, match="PIN is required"):
        await create_admin(session, display_name="Craig", pin="", timezone="UTC")

    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_create_admin_refuses_on_duplicate_name() -> None:
    session = _session_with([_existing("Craig")])

    with pytest.raises(BootstrapError, match="already exists"):
        await create_admin(session, display_name="Craig", pin="1234", timezone="UTC")

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_admin_refuses_when_league_full() -> None:
    session = _session_with([None, MAX_PLAYERS])

    with pytest.raises(BootstrapError, match="League is full"):
        await create_admin(session, display_name="Craig", pin="1234", timezone="UTC")

    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# promote_existing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_flips_existing_player_to_admin() -> None:
    existing = _existing("Craig", role=PlayerRole.player)
    session = _session_with([existing])

    result = await promote_existing(session, display_name="Craig")

    assert result is existing
    assert existing.role == PlayerRole.admin
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_promote_refuses_when_player_missing() -> None:
    session = _session_with([None])

    with pytest.raises(BootstrapError, match="No active player"):
        await promote_existing(session, display_name="Ghost")

    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_promote_refuses_when_already_admin() -> None:
    existing = _existing("Craig", role=PlayerRole.admin)
    session = _session_with([existing])

    with pytest.raises(BootstrapError, match="already an admin"):
        await promote_existing(session, display_name="Craig")

    session.flush.assert_not_called()
    # Role unchanged
    assert existing.role == PlayerRole.admin
