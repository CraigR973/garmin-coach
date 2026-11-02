"""Home's follow-up question asks about a fever too (Batch 364).

Revision ID: 042
Revises: 041
Create Date: 2026-11-02

``symptom_follow_ups`` held only the chest or heart follow-up (Batch 315). From the
morning after a fever, aches or a chest infection, Home now asks whether it has gone too
(HS361-02), so each row says which follow-up it answers: ``kind`` is ``chest_heart`` or
``fever_aches``. Every existing row is a chest or heart answer and is backfilled so. One
answer per kind a morning, so the unique key gains ``kind``. Nullable, as every column but
the key is on this table; the service always writes it. RLS is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "symptom_follow_ups",
        sa.Column("kind", sa.String(length=16), nullable=True),
        schema="coach",
    )
    op.execute("UPDATE coach.symptom_follow_ups SET kind = 'chest_heart' WHERE kind IS NULL")
    op.create_check_constraint(
        "ck_symptom_follow_ups_kind",
        "symptom_follow_ups",
        "kind IN ('chest_heart', 'fever_aches')",
        schema="coach",
    )
    op.drop_constraint(
        "uq_symptom_follow_ups_user_day", "symptom_follow_ups", schema="coach", type_="unique"
    )
    op.create_unique_constraint(
        "uq_symptom_follow_ups_user_day_kind",
        "symptom_follow_ups",
        ["user_id", "subject_date", "kind"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("DELETE FROM coach.symptom_follow_ups WHERE kind = 'fever_aches'")
    op.drop_constraint(
        "uq_symptom_follow_ups_user_day_kind",
        "symptom_follow_ups",
        schema="coach",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_symptom_follow_ups_user_day",
        "symptom_follow_ups",
        ["user_id", "subject_date"],
        schema="coach",
    )
    op.drop_constraint(
        "ck_symptom_follow_ups_kind", "symptom_follow_ups", schema="coach", type_="check"
    )
    op.drop_column("symptom_follow_ups", "kind", schema="coach")
