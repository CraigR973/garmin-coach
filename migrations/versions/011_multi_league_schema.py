"""multi-league schema foundations: leagues, memberships, join requests; profile additive cols; drop display_name UNIQUE

Revision ID: 011
Revises: 010
Create Date: 2026-05-27

Phase M1 of the multi-league rollout. Additive only — the existing
``profiles.role`` column and ``player_role`` enum are left untouched so
v1 application code continues to work. The new ``site_role`` column is
populated by ``scripts/backfill_multi_league.py``. The old ``role``
column is removed in a later phase (M8).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import UUID

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- new ENUM types (idempotent, matching v1 pattern from 001) ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE league_privacy AS ENUM
                ('private', 'public_request', 'public_open');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE league_member_role AS ENUM ('admin', 'player');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE join_request_status AS ENUM
                ('pending', 'approved', 'rejected', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE site_role AS ENUM ('superadmin', 'user');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # --- leagues ---
    op.create_table(
        "leagues",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "privacy",
            PgENUM(name="league_privacy", create_type=False),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "max_members",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=False,
        ),
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
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_leagues_slug"),
        sa.CheckConstraint(
            "max_members BETWEEN 2 AND 50",
            name="ck_leagues_max_members_range",
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_leagues_privacy_active
            ON leagues (privacy)
            WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TRIGGER leagues_set_updated_at
        BEFORE UPDATE ON leagues
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- league_memberships ---
    op.create_table(
        "league_memberships",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "league_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leagues.id"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            PgENUM(name="league_member_role", create_type=False),
            nullable=False,
            server_default="player",
        ),
        sa.Column("display_name_override", sa.String(100), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
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
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "league_id", "player_id", name="uq_league_memberships_league_player"
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_league_memberships_player_active
            ON league_memberships (player_id)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_league_memberships_league_role_active
            ON league_memberships (league_id, role)
            WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TRIGGER league_memberships_set_updated_at
        BEFORE UPDATE ON league_memberships
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- league_join_requests ---
    op.create_table(
        "league_join_requests",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "league_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leagues.id"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            PgENUM(name="join_request_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column(
            "decided_by",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id"),
            nullable=True,
        ),
        sa.Column("decision_note", sa.Text(), nullable=True),
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
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_league_join_requests_one_pending
            ON league_join_requests (league_id, player_id)
            WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_league_join_requests_league_pending
            ON league_join_requests (league_id)
            WHERE status = 'pending'
        """
    )

    op.execute(
        """
        CREATE TRIGGER league_join_requests_set_updated_at
        BEFORE UPDATE ON league_join_requests
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- profiles: additive identity columns ---
    # All nullable for the M1 backfill; M8 marks them NOT NULL after the
    # backfill script has populated every row.
    op.add_column("profiles", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("profiles", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("profiles", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column(
        "profiles",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "profiles",
        sa.Column(
            "site_role",
            PgENUM(name="site_role", create_type=False),
            nullable=True,
        ),
    )
    # Case-insensitive uniqueness for email; partial because column is NULLABLE
    # in M1 and unverified/duplicate rows would otherwise collide.
    op.execute(
        """
        CREATE UNIQUE INDEX ix_profiles_email_unique_lower
            ON profiles (LOWER(email))
            WHERE email IS NOT NULL
        """
    )

    # --- drop UNIQUE constraint on display_name (per MD-11) ---
    op.drop_constraint("uq_profiles_display_name", "profiles", type_="unique")

    # --- inline backfill (replaces the manual backfill_multi_league.py step) ---
    # Idempotent: all statements are guarded by WHERE / IF NOT EXISTS / ON CONFLICT.
    # On staging the steele-spreadsheet league already existed before this migration
    # ran, so the INSERT is a no-op there. On fresh prod deployments where the
    # backfill script was never run, this ensures 012 and 014 can succeed.

    # 1. Backfill profile identity columns from display_name for any rows still NULL.
    op.execute(
        """
        UPDATE profiles SET
            email      = CONCAT('pending+',
                                LOWER(REGEXP_REPLACE(display_name, '[^a-z0-9]+', '-', 'ig')),
                                '@steele.invalid'),
            first_name = SPLIT_PART(display_name, ' ', 1),
            last_name  = CASE
                           WHEN STRPOS(display_name, ' ') > 0
                           THEN SUBSTRING(display_name FROM STRPOS(display_name, ' ') + 1)
                           ELSE ''
                         END,
            site_role  = CASE WHEN role = 'admin'
                              THEN CAST('superadmin' AS site_role)
                              ELSE CAST('user' AS site_role)
                         END,
            email_verified_at = CASE
                                  WHEN role = 'admin' AND email_verified_at IS NULL
                                  THEN NOW()
                                  ELSE email_verified_at
                                END
        WHERE deleted_at IS NULL
          AND (email IS NULL OR first_name IS NULL OR last_name IS NULL OR site_role IS NULL)
        """
    )

    # 2. Create the Steele Spreadsheet league if it doesn't exist.
    #    Guarded on an admin profile existing: ``leagues.created_by`` is NOT
    #    NULL, so on a fresh DB with no profiles (CI, or a brand-new prod that
    #    migrates before bootstrap_admin runs) this is a clean no-op rather than
    #    an INSERT of a NULL created_by. Mirrors 012's tolerance of a missing
    #    Steele league.
    op.execute(
        """
        INSERT INTO leagues
            (id, slug, name, description, privacy, max_members,
             created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            'steele-spreadsheet',
            'The Steele Spreadsheet',
            'The original.',
            CAST('private' AS league_privacy),
            15,
            (SELECT id FROM profiles WHERE role = 'admin' AND deleted_at IS NULL
             ORDER BY created_at LIMIT 1),
            NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM leagues WHERE slug = 'steele-spreadsheet')
          AND EXISTS (
              SELECT 1 FROM profiles WHERE role = 'admin' AND deleted_at IS NULL
          )
        """
    )

    # 3. Create league_memberships for all active profiles that don't have one yet.
    op.execute(
        """
        INSERT INTO league_memberships
            (id, league_id, player_id, role, joined_at, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            (SELECT id FROM leagues WHERE slug = 'steele-spreadsheet'),
            p.id,
            CASE WHEN p.role = 'admin'
                 THEN CAST('admin' AS league_member_role)
                 ELSE CAST('player' AS league_member_role)
            END,
            NOW(), NOW(), NOW()
        FROM profiles p
        WHERE p.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM leagues WHERE slug = 'steele-spreadsheet')
          AND NOT EXISTS (
              SELECT 1 FROM league_memberships lm
              WHERE lm.league_id = (SELECT id FROM leagues WHERE slug = 'steele-spreadsheet')
                AND lm.player_id = p.id
          )
        """
    )


def downgrade() -> None:
    # Safety: refuse to restore the display_name UNIQUE if duplicates exist.
    op.execute(
        """
        DO $$
        DECLARE dup_count INT;
        BEGIN
            SELECT COUNT(*) INTO dup_count FROM (
                SELECT display_name FROM profiles
                WHERE display_name IS NOT NULL
                GROUP BY display_name
                HAVING COUNT(*) > 1
            ) d;
            IF dup_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot restore uq_profiles_display_name: % duplicate display_name groups exist',
                    dup_count;
            END IF;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_profiles_display_name", "profiles", ["display_name"]
    )

    op.execute("DROP INDEX IF EXISTS ix_profiles_email_unique_lower")
    op.drop_column("profiles", "site_role")
    op.drop_column("profiles", "email_verified_at")
    op.drop_column("profiles", "last_name")
    op.drop_column("profiles", "first_name")
    op.drop_column("profiles", "email")

    op.execute(
        "DROP TRIGGER IF EXISTS league_join_requests_set_updated_at "
        "ON league_join_requests"
    )
    op.drop_table("league_join_requests")

    op.execute(
        "DROP TRIGGER IF EXISTS league_memberships_set_updated_at ON league_memberships"
    )
    op.drop_table("league_memberships")

    op.execute("DROP TRIGGER IF EXISTS leagues_set_updated_at ON leagues")
    op.drop_table("leagues")

    op.execute("DROP TYPE IF EXISTS site_role")
    op.execute("DROP TYPE IF EXISTS join_request_status")
    op.execute("DROP TYPE IF EXISTS league_member_role")
    op.execute("DROP TYPE IF EXISTS league_privacy")
