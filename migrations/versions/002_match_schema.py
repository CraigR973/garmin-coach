"""match schema: matches table with status/result_source ENUMs and indexes

Revision ID: 002
Revises: 001
Create Date: 2026-05-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ENUM types ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE match_status AS ENUM (
                'scheduled', 'locked', 'live', 'completed', 'postponed', 'cancelled'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE result_source AS ENUM ('auto', 'manual', 'override');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # --- matches table ---
    op.create_table(
        "matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "stage",
            PgENUM(name="tournament_stage", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("match_number", sa.Integer(), nullable=False),
        sa.Column(
            "home_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "away_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("home_team_placeholder", sa.String(50), nullable=True),
        sa.Column("away_team_placeholder", sa.String(50), nullable=True),
        sa.Column("kickoff_utc", sa.DateTime(timezone=False), nullable=False),
        sa.Column("original_kickoff_utc", sa.DateTime(timezone=False), nullable=True),
        sa.Column("venue", sa.String(255), nullable=True),
        sa.Column(
            "status",
            PgENUM(name="match_status", create_type=False),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("actual_home_score", sa.Integer(), nullable=True),
        sa.Column("actual_away_score", sa.Integer(), nullable=True),
        sa.Column("extra_time", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("penalties", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "penalty_winner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "result_source",
            PgENUM(name="result_source", create_type=False),
            nullable=True,
        ),
        sa.Column("football_data_match_id", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("result_entered_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "result_entered_by",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("postponed_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("match_number", name="uq_matches_match_number"),
        sa.UniqueConstraint(
            "football_data_match_id", name="uq_matches_football_data_match_id"
        ),
    )

    # --- indexes ---
    op.create_index("ix_matches_kickoff_utc", "matches", ["kickoff_utc"])
    op.create_index("ix_matches_stage_status", "matches", ["stage", "status"])
    op.create_index(
        "ix_matches_football_data_match_id", "matches", ["football_data_match_id"]
    )

    # --- updated_at trigger ---
    op.execute("""
        CREATE TRIGGER matches_set_updated_at
        BEFORE UPDATE ON matches
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS matches_set_updated_at ON matches")
    op.drop_table("matches")
    op.execute("DROP TYPE IF EXISTS result_source")
    op.execute("DROP TYPE IF EXISTS match_status")
