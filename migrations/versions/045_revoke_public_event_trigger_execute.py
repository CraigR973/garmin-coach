"""Remove inherited Data API execute on the RLS event trigger (Batch 371).

PUBLIC grants also apply to anon/authenticated; the owner/event trigger remains.
The function belongs to the deployed Supabase database, not a plain test Postgres.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
            REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
              REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
              REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM authenticated;
            END IF;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    # Do not re-open an unnecessary public privilege during an app rollback.
    pass
