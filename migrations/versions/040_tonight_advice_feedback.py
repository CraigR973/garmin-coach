"""Record whether Mark followed last night's advice (Batch 320).

Revision ID: 040
Revises: 039
Create Date: 2026-10-29

One nullable JSONB column on ``manual_entries``: the morning check-in's one-tap answer to
"Last night's advice: did you manage it?", with the advice it answers
(``{"givenOn": "2026-10-28", "key": "sleep_window", "answer": "followed"}``). Null means
he was not asked or did not answer. Existing rows stay null; RLS on the table is unchanged.
Additive and nullable: drafted overnight 29 Oct and tested on a throwaway Postgres only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "040"
down_revision: str | None = "039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "manual_entries",
        sa.Column("tonight_advice_feedback_json", postgresql.JSONB(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.drop_column("manual_entries", "tonight_advice_feedback_json", schema="coach")
