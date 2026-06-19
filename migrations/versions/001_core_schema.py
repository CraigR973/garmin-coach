"""core schema: groups, profiles, teams, refresh_tokens, invites

Revision ID: 001
Revises:
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ENUM types ---
    # Wrapped in DO blocks so re-running is idempotent (Alembic 1.18+ may emit
    # an extra CREATE TYPE despite create_type=False on the column definition).
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE player_role AS ENUM ('player', 'admin');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tournament_stage AS ENUM
                ('group', 'r32', 'r16', 'qf', 'sf', 'third_place', 'final', 'winner');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # --- groups ---
    op.create_table(
        "groups",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(1), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("name", name="uq_groups_name"),
    )

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
            PgENUM(name="player_role", create_type=False),
            nullable=False,
            server_default="player",
        ),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column(
            "failed_login_count", sa.Integer(), nullable=False, server_default="0"
        ),
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

    # --- teams ---
    op.create_table(
        "teams",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("flag_emoji", sa.String(10), nullable=False),
        sa.Column(
            "group_id", UUID(as_uuid=True), sa.ForeignKey("groups.id"), nullable=True
        ),
        sa.Column(
            "eliminated_at_stage",
            PgENUM(name="tournament_stage", create_type=False),
            nullable=True,
        ),
        sa.Column("is_host", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("football_data_team_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
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

    # --- invites ---
    op.create_table(
        "invites",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("display_name_hint", sa.String(100), nullable=True),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "claimed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=True,
        ),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("token", name="uq_invites_token"),
    )

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
                ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
                ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
                ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
                ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
                ALTER TABLE invites ENABLE ROW LEVEL SECURITY;

                -- groups / teams: public read
                CREATE POLICY "groups_select_all"
                    ON groups FOR SELECT USING (true);
                CREATE POLICY "teams_select_all"
                    ON teams FOR SELECT USING (true);

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

                -- invites: authenticated users can read; insert handled by service role
                CREATE POLICY "invites_select_authenticated"
                    ON invites FOR SELECT TO authenticated USING (true);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("refresh_tokens")
    op.drop_table("teams")
    op.drop_table("profiles")
    op.drop_table("groups")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")
    op.execute("DROP TYPE IF EXISTS tournament_stage")
    op.execute("DROP TYPE IF EXISTS player_role")
