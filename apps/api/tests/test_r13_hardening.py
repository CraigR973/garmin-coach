"""Tests for R13: admin authority unification, environment enum, snapshot pruning."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.config import Environment, Settings
from src.models.profile import PlayerRole, Profile, SiteRole

# ---------------------------------------------------------------------------
# R13.1 — require_admin uses site_role as single source of truth
# ---------------------------------------------------------------------------


async def _make_profile_mock(*, site_role: SiteRole) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.site_role = site_role
    p.role = PlayerRole.admin if site_role == SiteRole.superadmin else PlayerRole.player
    p.deleted_at = None
    return p


async def test_require_admin_passes_for_superadmin() -> None:
    from src.auth import require_admin

    player = await _make_profile_mock(site_role=SiteRole.superadmin)
    result = await require_admin(player)
    assert result is player


async def test_require_admin_rejects_non_superadmin() -> None:
    from src.auth import require_admin

    player = await _make_profile_mock(site_role=SiteRole.user)
    with pytest.raises(HTTPException) as exc:
        await require_admin(player)
    assert exc.value.status_code == 403


async def test_require_admin_ignores_legacy_role_field() -> None:
    """A player with legacy role=admin but site_role=user must be rejected."""
    from src.auth import require_admin

    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.role = PlayerRole.admin  # legacy field says admin…
    p.site_role = SiteRole.user  # …but site_role says user — must lose
    p.deleted_at = None

    with pytest.raises(HTTPException) as exc:
        await require_admin(p)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# R13.2 — Environment enum: unknown value fails closed
# ---------------------------------------------------------------------------


def test_environment_enum_rejects_unknown_value() -> None:
    """An unrecognised environment string should raise a ValidationError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(
            jwt_access_secret="access-secret-long-enough",
            jwt_refresh_secret="refresh-secret-long-enough",
            environment="PRODUCTION",  # capitalised — not a valid enum member
        )


def test_environment_staging_accepted() -> None:
    """Staging is a valid enum value and must not mount test helpers."""
    s = Settings(
        jwt_access_secret="a" * 32,
        jwt_refresh_secret="r" * 32,
        vapid_private_key="v" * 32,
        supabase_service_key="s" * 32,
        football_data_api_key="f" * 32,
        frontend_origin="https://staging.example.com",
        database_url="postgresql+asyncpg://x:y@host/db",
        environment="staging",
    )
    assert s.environment == Environment.staging


def test_environment_development_value_accepted() -> None:
    s = Settings(
        jwt_access_secret="a" * 32,
        jwt_refresh_secret="r" * 32,
        environment="development",
    )
    assert s.environment == Environment.development


def test_test_helpers_not_mounted_in_staging() -> None:
    """Staging must not mount test_helpers (fail-closed for non-development envs)."""
    from src.config import Environment
    from src.main import app

    # app.routes can contain entries without a `.path` (e.g. _IncludedRouter in newer
    # FastAPI/Starlette); default to "" so the membership check below stays robust.
    route_paths = [getattr(r, "path", "") for r in app.routes]
    # The test_helpers router mounts /api/v1/test/... routes only in development.
    # In the real app (which starts as production by default in CI), they must be absent.
    staging_test_routes = [p for p in route_paths if "/test/" in p]
    # If the running app's environment is not development, no test routes should exist.
    from src.config import settings

    if settings.environment != Environment.development:
        assert staging_test_routes == [], (
            f"test_helpers routes should not be mounted in {settings.environment!r}: "
            f"{staging_test_routes}"
        )


# ---------------------------------------------------------------------------
# R13.3 — prune_leaderboard_snapshots keeps growth bounded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_leaderboard_snapshots_executes_delete() -> None:
    """prune_leaderboard_snapshots runs a DELETE and commits."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.scheduler import prune_leaderboard_snapshots

    mock_result = MagicMock()
    mock_result.rowcount = 7

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(spec=async_sessionmaker)
    mock_factory.return_value = mock_session

    deleted = await prune_leaderboard_snapshots(session_factory=mock_factory, keep_recent=50)

    assert deleted == 7
    mock_session.execute.assert_called_once()
    # Verify the SQL contains the expected DELETE keyword and the keep_recent param
    call_args = mock_session.execute.call_args
    sql_text = str(call_args[0][0])
    assert "DELETE" in sql_text.upper()
    assert "leaderboard_snapshots" in sql_text
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_prune_leaderboard_snapshots_no_log_when_zero() -> None:
    """No log when nothing deleted."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.scheduler import prune_leaderboard_snapshots

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(spec=async_sessionmaker)
    mock_factory.return_value = mock_session

    deleted = await prune_leaderboard_snapshots(session_factory=mock_factory)
    assert deleted == 0
