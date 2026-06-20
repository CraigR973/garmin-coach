"""Add adherence fields to manual entries for the daily loop.

Revision ID: 005
Revises: 004
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "manual_entries",
        sa.Column(
            "planned_workout_id",
            UUID(as_uuid=True),
            sa.ForeignKey("coach.planned_workouts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="coach",
    )
    op.add_column(
        "manual_entries",
        sa.Column("planned_workout_version", sa.Integer(), nullable=True),
        schema="coach",
    )
    op.add_column(
        "manual_entries",
        sa.Column("adherence_status", sa.String(length=40), nullable=True),
        schema="coach",
    )
    op.add_column(
        "manual_entries",
        sa.Column("actual_workout_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="coach",
    )
    op.create_index(
        "ix_manual_entries_planned_workout",
        "manual_entries",
        ["planned_workout_id"],
        schema="coach",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manual_entries_planned_workout",
        table_name="manual_entries",
        schema="coach",
    )
    op.drop_column("manual_entries", "actual_workout_json", schema="coach")
    op.drop_column("manual_entries", "adherence_status", schema="coach")
    op.drop_column("manual_entries", "planned_workout_version", schema="coach")
    op.drop_column("manual_entries", "planned_workout_id", schema="coach")
