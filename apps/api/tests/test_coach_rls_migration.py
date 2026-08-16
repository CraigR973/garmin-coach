"""Batch 89: every coach table must be under Row Level Security.

Migration 001 protected the five auth/notification tables; migration 015 covers
the rest existing at that point. Every coach table added afterwards ships its
own guarded-ENABLE migration in the same style (019 for ``brief_messages``,
Batch 119) — together they must cover every coach model table, guarding
against a future model table shipping with RLS disabled, the exact gap that
left 18 tables flagged by the Supabase advisor after Batches 002-014.

The check is pure (no DB): each RLS migration exposes its own ``RLS_TABLES``
constant, and we assert 001's set plus every later migration's set equals the
coach model tables registered on ``Base.metadata``. CR189-11 (Batch 204) added
a second pure check that runs each migration's real ``upgrade()`` against a
recording mock and asserts the SQL it would send actually enables RLS for
every table it claims to — the ``RLS_TABLES`` constant alone does not prove
that.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from src.models import Base

# The five coach tables migration 001 already placed under RLS.
ALREADY_RLS: frozenset[str] = frozenset(
    {
        "profiles",
        "refresh_tokens",
        "push_subscriptions",
        "notification_preferences",
        "audit_log",
    }
)

# alembic_version is Alembic's own bookkeeping table (not a SQLAlchemy model), so
# it never appears in Base.metadata — excluded from the model-coverage check.
NON_MODEL_TABLES: frozenset[str] = frozenset({"alembic_version"})

# Every migration (after 001) that guards a coach table under RLS, in the order
# they shipped. A new coach table's RLS migration is added here.
RLS_MIGRATION_FILES: tuple[str, ...] = (
    "015_coach_rls.py",
    "019_brief_messages_rls.py",
    "020_brief_generation_status.py",
    "021_conversation_learning_proposals.py",
    "022_post_activity_generation_status.py",
    "024_generation_requests.py",
    "027_job_runs.py",
)


def _load_migration(filename: str) -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "migrations" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_rls_tables() -> set[str]:
    tables: set[str] = set()
    for filename in RLS_MIGRATION_FILES:
        tables |= set(_load_migration(filename).RLS_TABLES)
    return tables


def test_rls_tables_have_no_duplicates() -> None:
    for filename in RLS_MIGRATION_FILES:
        rls_tables = _load_migration(filename).RLS_TABLES
        assert len(rls_tables) == len(set(rls_tables)), filename


def test_rls_migrations_do_not_touch_already_protected_tables() -> None:
    rls_tables = _all_rls_tables()
    assert rls_tables.isdisjoint(ALREADY_RLS)


def test_every_coach_model_table_is_under_rls() -> None:
    """001 + every later RLS migration together must cover every coach model table."""
    rls_tables = _all_rls_tables()
    model_tables = set(Base.metadata.tables.keys())
    covered = (rls_tables - NON_MODEL_TABLES) | ALREADY_RLS
    assert covered == model_tables, {
        "model_tables_missing_rls": sorted(model_tables - covered),
        "rls_table_is_not_a_model": sorted(covered - model_tables),
    }


def test_every_rls_migration_actually_emits_its_enable_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR189-11: the tests above assert a Python constant, never the migration SQL.

    A migration could declare a table in ``RLS_TABLES`` and omit the
    ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` statement and every test
    above would stay green. This runs each migration's real ``upgrade()``
    with ``op`` replaced by a recording mock (the same technique as
    ``test_auth_cutover_migration.py``) and asserts the captured SQL actually
    contains the ENABLE statement for every one of its own ``RLS_TABLES``.

    A live ``pg_class.relrowsecurity`` check was considered instead (and is
    the deployed-state verification ``scripts/check_rls_posture.py`` already
    does against a real Supabase-shaped database via
    ``RLS_POSTURE_DATABASE_URL``). It does not work as a unit test here: every
    RLS migration wraps its ``ALTER TABLE`` in a guard that only fires when an
    ``auth`` schema exists, deliberately no-op on CI's plain
    ``postgres:16`` service so the migration-check and unit-test jobs stay
    green without Supabase's schema — so ``relrowsecurity`` would read
    ``false`` for every table there regardless of whether the statement is
    present, which is not the gap this test exists to catch.
    """

    for filename in RLS_MIGRATION_FILES:
        migration = _load_migration(filename)
        executed: list[str] = []
        mock_op = MagicMock()
        mock_op.execute.side_effect = lambda sql: executed.append(str(sql))
        monkeypatch.setattr(migration, "op", mock_op)

        migration.upgrade()

        combined_sql = " ".join(" ".join(sql.split()) for sql in executed)
        for table in migration.RLS_TABLES:
            expected = f"ALTER TABLE coach.{table} ENABLE ROW LEVEL SECURITY"
            assert expected in combined_sql, (filename, table, combined_sql)
