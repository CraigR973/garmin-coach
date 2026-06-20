"""core schema: profiles, refresh_tokens, push_subscriptions, notification_preferences, audit_log

Revision ID: 001
Revises:
Create Date: 2026-06-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure the coach schema exists and is the active search path for this migration.
    # All objects created below land in coach.*; the public schema is untouched.
    op.execute("CREATE SCHEMA IF NOT EXISTS coach")
    op.execute("SET search_path TO coach, public")

    # --- ENUM types ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE coach.player_role AS ENUM ('player', 'admin');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE coach.actor_type AS ENUM ('admin', 'player', 'system');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE coach.action_type AS ENUM ('backup_failed', 'backup_downloaded', 'player_pin_reset');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # --- profiles ---
    op.create_table(
        "profiles",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("pin_hash", sa.String(60), nullable=False),
        sa.Column(
            "role",
            PgENUM(name="player_role", schema="coach", create_type=False),
            nullable=False,
            server_default="player",
        ),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("display_name", name="uq_profiles_display_name"),
    )

    # --- refresh_tokens ---
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("device_hint", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- push_subscriptions ---
    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subscription", JSONB, nullable=False),
        sa.Column("device_hint", sa.String(100), nullable=True),
        sa.Column("failed_send_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- notification_preferences ---
    op.create_table(
        "notification_preferences",
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("global_mute", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quiet_hours_start", sa.DateTime(), nullable=True),
        sa.Column("quiet_hours_end", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- audit_log ---
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_type",
            PgENUM(name="actor_type", schema="coach", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            PgENUM(name="action_type", schema="coach", create_type=False),
            nullable=False,
        ),
        sa.Column("target_table", sa.String(50), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column("changes", JSONB, nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_action_type", "audit_log", ["action_type"])

    # --- updated_at trigger (profiles) ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER profiles_set_updated_at
        BEFORE UPDATE ON profiles
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- RLS policies (Supabase only — skipped on plain Postgres) ---
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
                ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
                ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
                ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
                ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

                -- profiles: own row read/update; service role bypasses RLS
                CREATE POLICY "profiles_select_own"
                    ON profiles FOR SELECT USING (auth.uid() = id);
                CREATE POLICY "profiles_update_own"
                    ON profiles FOR UPDATE USING (auth.uid() = id);

                -- refresh_tokens: own tokens only
                CREATE POLICY "refresh_tokens_select_own"
                    ON refresh_tokens FOR SELECT USING (auth.uid() = player_id);
                CREATE POLICY "refresh_tokens_insert_own"
                    ON refresh_tokens FOR INSERT WITH CHECK (auth.uid() = player_id);
                CREATE POLICY "refresh_tokens_delete_own"
                    ON refresh_tokens FOR DELETE USING (auth.uid() = player_id);

                -- push_subscriptions: own only
                CREATE POLICY "push_subscriptions_select_own"
                    ON push_subscriptions FOR SELECT USING (auth.uid() = player_id);
                CREATE POLICY "push_subscriptions_insert_own"
                    ON push_subscriptions FOR INSERT WITH CHECK (auth.uid() = player_id);

                -- notification_preferences: own only
                CREATE POLICY "notification_preferences_select_own"
                    ON notification_preferences FOR SELECT USING (auth.uid() = player_id);
                CREATE POLICY "notification_preferences_update_own"
                    ON notification_preferences FOR UPDATE USING (auth.uid() = player_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_table("audit_log", schema="coach")
    op.drop_table("notification_preferences", schema="coach")
    op.drop_table("push_subscriptions", schema="coach")
    op.drop_table("refresh_tokens", schema="coach")
    op.drop_table("profiles", schema="coach")
    op.execute("DROP FUNCTION IF EXISTS coach.set_updated_at() CASCADE")
    op.execute("DROP TYPE IF EXISTS coach.action_type")
    op.execute("DROP TYPE IF EXISTS coach.actor_type")
    op.execute("DROP TYPE IF EXISTS coach.player_role")
