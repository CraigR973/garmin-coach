"""Batch 89: every coach table must be under Row Level Security.

Migration 001 protected the five auth/notification tables; migration 015 covers
the rest existing at that point. Every coach table added afterwards ships its
own guarded-ENABLE migration in the same style (019 for ``brief_messages``,
Batch 119) — together they must cover every coach model table, guarding
against a future model table shipping with RLS disabled, the exact gap that
left 18 tables flagged by the Supabase advisor after Batches 002-014.

The check is pure (no DB): each RLS migration exposes its own ``RLS_TABLES``
constant, and we assert 001's set plus every later migration's set equals the
coach model tables registered on ``Base.metadata``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
