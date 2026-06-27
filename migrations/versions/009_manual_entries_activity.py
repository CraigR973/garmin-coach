"""Link post-ride manual entries to activities.

Revision ID: 009
Revises: 008
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "manual_entries",
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="coach",
    )
    op.create_foreign_key(
        "fk_manual_entries_activity_id_activities",
        "manual_entries",
        "activities",
        ["activity_id"],
        ["id"],
        source_schema="coach",
        referent_schema="coach",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_manual_entries_activity",
        "manual_entries",
        ["activity_id"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_manual_entries_activity",
        table_name="manual_entries",
        schema="coach",
        if_exists=True,
    )
    op.drop_constraint(
        "fk_manual_entries_activity_id_activities",
        "manual_entries",
        schema="coach",
        type_="foreignkey",
    )
    op.drop_column("manual_entries", "activity_id", schema="coach")
