"""019 — squad_players table + RLS lockdown (U14).

Creates the ``squad_players`` table (WC 2026 footballer roster) and applies
the same RLS pattern as migration 015 (R11):
  • ENABLE ROW LEVEL SECURITY
  • REVOKE INSERT/UPDATE/DELETE/TRUNCATE from anon + authenticated
  • CREATE SELECT policy for anon + authenticated (squad list is non-secret)

Revision ID: 019
Revises: 018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

_TABLE = "squad_players"

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

_WRITE_PRIVS = "INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("known_as", sa.String(100), nullable=False),
        sa.Column(
            "position",
            sa.Enum("GK", "DEF", "MID", "FWD", name="squad_position", create_type=True),
            nullable=False,
        ),
        sa.Column("shirt_number", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Name-search index — trigram would be ideal, but requires pg_trgm extension.
    # A plain btree on lower(full_name) / lower(known_as) covers prefix queries cheaply.
    op.create_index(
        "ix_squad_players_full_name_lower",
        _TABLE,
        [sa.text("lower(full_name)")],
        postgresql_using="btree",
    )
    op.create_index(
        "ix_squad_players_known_as_lower",
        _TABLE,
        [sa.text("lower(known_as)")],
        postgresql_using="btree",
    )
    op.create_index("ix_squad_players_team_id", _TABLE, ["team_id"])

    # RLS — same pattern as 015 (R11)
    op.execute(_ENSURE_ROLES)
    op.execute(f"REVOKE {_WRITE_PRIVS} ON TABLE {_TABLE} FROM anon, authenticated")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT ON TABLE {_TABLE} TO anon, authenticated")
    op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_anon_read" ON {_TABLE}')
    op.execute(
        f'CREATE POLICY "{_TABLE}_anon_read" ON {_TABLE} '
        "FOR SELECT TO anon, authenticated USING (true)"
    )


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_anon_read" ON {_TABLE}')
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_squad_players_team_id", table_name=_TABLE)
    op.drop_index("ix_squad_players_known_as_lower", table_name=_TABLE)
    op.drop_index("ix_squad_players_full_name_lower", table_name=_TABLE)
    op.drop_table(_TABLE)
    op.execute("DROP TYPE IF EXISTS squad_position")
