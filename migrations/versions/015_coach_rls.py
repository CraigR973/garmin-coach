"""Enable Row Level Security on the remaining coach.* tables (defense-in-depth).

Revision ID: 015
Revises: 014
Create Date: 2026-07-12

Batch 89 (Decision #162). Migration 001 enabled RLS on the five auth/notification
tables (``profiles``, ``refresh_tokens``, ``push_subscriptions``,
``notification_preferences``, ``audit_log``); every ``coach`` table created since
(002-014) was left with RLS **disabled**, which the Supabase security advisor
flags as a critical ``rls_disabled`` lint. This migration closes that gap by
enabling RLS on the remaining ``coach`` tables.

**No policies are created — and that is correct here.** The FastAPI backend
connects as the ``postgres`` *owner* role, and a table owner bypasses RLS (no
``FORCE ROW LEVEL SECURITY``), so the app is unaffected. RLS with no policy is
deny-all for the Supabase ``anon`` / ``authenticated`` roles — exactly the
posture ``audit_log`` already has. Today those roles hold **no grants** on the
``coach`` schema at all (so nothing is actually reachable via the Data API); this
migration is the belt to that suspenders, so a future stray ``GRANT`` or an
exposed-schema change can never leak Mark's health data.

Like migration 001, the RLS statements are wrapped in an ``IF EXISTS (auth
schema)`` guard so they run **only on Supabase** and are a no-op on plain
Postgres — keeping the CI ``migration-check`` (upgrade head → downgrade base) and
the unit-test Postgres green without an ``auth`` schema.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every coach table that migration 001 did NOT already put under RLS. Kept as a
# module constant so ``tests/test_coach_rls_migration.py`` can assert it covers
# exactly the coach model tables not already protected — a new table added
# without RLS then fails that test. ``alembic_version`` is Alembic's own
# bookkeeping table (not a SQLAlchemy model), included so the advisor goes fully
# clean.
RLS_TABLES: tuple[str, ...] = (
    "daily_metrics",
    "sleep",
    "activities",
    "activity_timeseries",
    "temperature_readings",
    "fan_state_readings",
    "weather_daily",
    "metric_baselines",
    "manual_entries",
    "plan_blocks",
    "planned_workouts",
    "workout_delivery_proposals",
    "garmin_workout_deliveries",
    "analyses",
    "feedback",
    "experiments",
    "knowledge_base",
    "alembic_version",
)


def _rls_block(action: str) -> str:
    """Build the guarded DO block. ``action`` is ENABLE or DISABLE."""
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
