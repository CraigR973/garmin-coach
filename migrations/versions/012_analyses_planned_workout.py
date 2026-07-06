"""Link post-session analyses to the planned workout they completed.

Revision ID: 012
Revises: 011
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "analyses",
        sa.Column("planned_workout_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="coach",
    )
    op.create_foreign_key(
        "fk_analyses_planned_workout_id_planned_workouts",
        "analyses",
        "planned_workouts",
        ["planned_workout_id"],
        ["id"],
        source_schema="coach",
        referent_schema="coach",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_analyses_planned_workout",
        "analyses",
        ["planned_workout_id"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_analyses_planned_workout",
        table_name="analyses",
        schema="coach",
        if_exists=True,
    )
    op.drop_constraint(
        "fk_analyses_planned_workout_id_planned_workouts",
        "analyses",
        schema="coach",
        type_="foreignkey",
    )
    op.drop_column("analyses", "planned_workout_id", schema="coach")
