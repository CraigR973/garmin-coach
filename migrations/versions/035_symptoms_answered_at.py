"""Record when Mark answers Home's symptom question (Batch 303).

Revision ID: 035
Revises: 034
Create Date: 2026-10-02

When his check-in note may name a symptom, Home asks "Any symptoms today?" and only his
answer relaxes the floor the note set. Until now "his answer" was any later save of the
check-in: the app compared the check-in's own timestamp with the reading's. None is
preselected on that form, so saving it again for any reason, to add his breakfast say,
counted as answering "None" and dropped the symptom. 9 of his 78 morning check-ins were
saved again later the same day.

The answer now has a time of its own. NULL means he has not answered the question,
which is what every existing row is, so nothing is backfilled.

Additive: one nullable column with no default, so Postgres adds it without rewriting
the table. Craig's go, 2 Oct 2026. The downgrade drops the column and any answers
recorded since; a note's symptom then stands until the note changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "manual_entries",
        sa.Column("symptoms_answered_at_utc", sa.DateTime(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("manual_entries", "symptoms_answered_at_utc", schema="coach")
