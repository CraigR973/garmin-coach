"""Batch 89: every coach table must be under Row Level Security.

Migration 001 protected the five auth/notification tables; migration 015 covers
the rest. Together they must cover every coach model table — this guards against
a future model table shipping with RLS disabled, the exact gap that left 18
tables flagged by the Supabase advisor after Batches 002-014.

The check is pure (no DB): migration 015 exposes its ``RLS_TABLES`` constant, and
we assert 001's set plus 015's set equals the coach model tables registered on
``Base.metadata``.
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


def _load_migration_015() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "migrations" / "versions" / "015_coach_rls.py"
    spec = importlib.util.spec_from_file_location("migration_015_coach_rls", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rls_tables_have_no_duplicates() -> None:
    rls_tables = _load_migration_015().RLS_TABLES
    assert len(rls_tables) == len(set(rls_tables))


def test_migration_015_does_not_touch_already_protected_tables() -> None:
    rls_tables = set(_load_migration_015().RLS_TABLES)
    assert rls_tables.isdisjoint(ALREADY_RLS)


def test_every_coach_model_table_is_under_rls() -> None:
    """001 + 015 together must cover every coach model table — no gaps."""
    rls_tables = set(_load_migration_015().RLS_TABLES)
    model_tables = set(Base.metadata.tables.keys())
    covered = (rls_tables - NON_MODEL_TABLES) | ALREADY_RLS
    assert covered == model_tables, {
        "model_tables_missing_rls": sorted(model_tables - covered),
        "rls_table_is_not_a_model": sorted(covered - model_tables),
    }
