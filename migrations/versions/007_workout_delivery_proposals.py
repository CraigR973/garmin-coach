"""Add approval-gated workout delivery proposals.

Revision ID: 007
Revises: 006
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "workout_delivery_proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planned_workout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("planned_workout_version", sa.Integer(), nullable=False),
        sa.Column("workout_date", sa.Date(), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=50),
            server_default="intervals_icu",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=50), server_default="proposed", nullable=False
        ),
        sa.Column("proposed_at_utc", sa.DateTime(timezone=False), nullable=False),
        sa.Column("approved_at_utc", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "approved_by_profile_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("pushed_at_utc", sa.DateTime(timezone=False), nullable=True),
        sa.Column("intervals_event_id", sa.String(length=120), nullable=True),
        sa.Column(
            "structured_workout_ir",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "intervals_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("zwo_xml", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_by_profile_id"], ["profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["planned_workout_id"], ["planned_workouts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="coach",
    )
    op.create_index(
        "ix_workout_delivery_planned_workout",
        "workout_delivery_proposals",
        ["planned_workout_id"],
        schema="coach",
    )
    op.create_index(
        "ix_workout_delivery_user_status",
        "workout_delivery_proposals",
        ["user_id", "status"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_workout_delivery_user_status",
        table_name="workout_delivery_proposals",
        schema="coach",
        if_exists=True,
    )
    op.drop_index(
        "ix_workout_delivery_planned_workout",
        table_name="workout_delivery_proposals",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("workout_delivery_proposals", schema="coach")
