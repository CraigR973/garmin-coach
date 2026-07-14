"""Enable Row Level Security on brief_messages (Batch 119).

Revision ID: 019
Revises: 018
Create Date: 2026-07-14

Migration 015 (Decision #162) put every existing ``coach`` table under RLS as
defense-in-depth; ``brief_messages`` (018) is the first new coach table since,
so it needs the same guarded ENABLE — ``test_every_coach_model_table_is_under_rls``
would otherwise fail. Same posture as 015: no policies (the backend connects as
the owning role and bypasses RLS), guarded by the ``auth`` schema existence
check so this is a no-op on plain Postgres/CI.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The one coach table this migration adds under RLS. Kept as a module constant,
# same shape as migration 015's ``RLS_TABLES``, so
# ``tests/test_coach_rls_migration.py`` can assert full coverage across both.
RLS_TABLES: tuple[str, ...] = ("brief_messages",)


def _rls_block(action: str) -> str:
    statements = "\n".join(
        f"                ALTER TABLE coach.{table} {action} ROW LEVEL SECURITY;"
        for table in RLS_TABLES
    )
    return f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
{statements}
            END IF;
        END $$;
        """


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.execute(_rls_block("ENABLE"))


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.execute(_rls_block("DISABLE"))
