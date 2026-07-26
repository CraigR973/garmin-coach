"""Batch 160 schema/config cutover invariants."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.config import Settings
from src.models.profile import Profile
from src.models.refresh_token import RefreshToken


def _load_migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "versions"
        / "023_device_token_only_auth.py"
    )
    spec = importlib.util.spec_from_file_location("migration_023", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_models_and_config_have_no_pin_or_jwt_fields() -> None:
    assert {"pin_hash", "failed_login_count", "locked_until"}.isdisjoint(
        Profile.__table__.columns.keys()
    )
    assert {"jwt_access_secret", "jwt_refresh_secret"}.isdisjoint(Settings.model_fields)
    assert RefreshToken.__table__.c.purpose.server_default is None


def test_migration_gates_cutover_revokes_refresh_tokens_and_drops_pin_columns(
    monkeypatch,
) -> None:
    migration = _load_migration()
    executed: list[str] = []
    dropped: list[str] = []
    monkeypatch.setattr(migration.op, "execute", lambda sql: executed.append(str(sql)))
    monkeypatch.setattr(migration.op, "alter_column", MagicMock())
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda _table, column, **_kwargs: dropped.append(column),
    )

    migration.upgrade()

    combined_sql = "\n".join(executed)
    assert "lacks device or activation token" in combined_sql
    assert "purpose = 'refresh'" in combined_sql
    assert "SET revoked_at = NOW()" in combined_sql
    assert dropped == ["locked_until", "failed_login_count", "pin_hash"]


async def test_head_schema_has_removed_auth_columns(db_conn: AsyncConnection) -> None:
    rows = (
        await db_conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'coach'
                  AND table_name = 'profiles'
                  AND column_name IN ('pin_hash', 'failed_login_count', 'locked_until')
                """
            )
        )
    ).all()
    assert rows == []
