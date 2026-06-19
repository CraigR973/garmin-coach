"""week-1 survey: anonymous responses + per-player completion gate.

Two tables backing the in-app "Week 1 pulse" survey (a snooze-able nag):

  survey_completions — one row per (player, survey_key); records THAT a player
      finished so the client can stop prompting. Never joined to the answers.
  survey_responses   — the de-identified answers + auto-tagged league ids.
      ``contact_player_id`` is NULL unless the player ticked "happy to be
      contacted", which is the only link from a response back to a person
      (the hybrid storage model).

Both tables are locked down to match the R11 posture (migration 015): the
FastAPI backend connects as the postgres owner (owner-bypass), while the
Supabase ``anon`` / ``authenticated`` roles — which Supabase auto-grants on new
``public`` tables — are stripped of writes and denied every row via
RLS-with-no-policy. Without this the feedback (and the contact opt-in id) would
be readable through the publicly-shipped anon key, re-opening the C1 vector.

Revision ID: 033
Revises: 032
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ("survey_completions", "survey_responses")
_WRITE_PRIVS = "INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER"

# Portable on bare Postgres (CI / local) where the Supabase roles don't exist.
_ENSURE_ROLES = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        "survey_completions",
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
        sa.Column("survey_key", sa.String(64), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "player_id", "survey_key", name="uq_survey_completions_player_survey"
        ),
    )

    op.create_table(
        "survey_responses",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("survey_key", sa.String(64), nullable=False),
        sa.Column(
            "league_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("answers", JSONB(), nullable=False),
        sa.Column(
            "contact_player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.execute(
        "CREATE INDEX ix_survey_responses_survey_key ON survey_responses (survey_key)"
    )

    # --- R11 parity: lock the new tables down for the Supabase anon roles ---
    op.execute(_ENSURE_ROLES)
    for table in _NEW_TABLES:
        op.execute(f"REVOKE {_WRITE_PRIVS} ON TABLE {table} FROM anon, authenticated")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_survey_responses_survey_key")
    op.drop_table("survey_responses")
    op.drop_table("survey_completions")
