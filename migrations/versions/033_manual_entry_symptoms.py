"""Store Mark's answer to the check-in's symptom question (Batch 294).

Revision ID: 033
Revises: 032
Create Date: 2026-09-28

The morning colour never asked about symptoms. The check-in now asks "Any symptoms
today?" with four answers, and three of them set a medical floor in the verdict
(``services.symptom_check``). NULL means he was not asked or did not answer, which
the verdict never reads as "none", so existing rows keep NULL and nothing is
backfilled.

Additive: a nullable column and a check constraint, with no default, so Postgres
adds it without rewriting the table. Craig's go, 28 Sep 2026. The downgrade drops
the column and any answers recorded since.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "manual_entries",
        sa.Column("symptoms", sa.String(16), nullable=True),
        schema="coach",
    )
    op.create_check_constraint(
        "ck_manual_entries_symptoms",
        "manual_entries",
        "symptoms IS NULL OR symptoms IN ('none', 'head_cold', 'fever_aches', 'chest_heart')",
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_constraint(
        "ck_manual_entries_symptoms",
        "manual_entries",
        type_="check",
        schema="coach",
    )
    op.drop_column("manual_entries", "symptoms", schema="coach")
