"""Persist explicit REM-intervention application evidence (Batch 221).

Revision ID: 030
Revises: 029
Create Date: 2026-08-24

The row belongs to the wake date, matching ``sleep_setup_json`` and the sleep
outcome it qualifies.  Application is user-owned evidence: it cannot be inferred
honestly from Garmin, the bedroom setup, or free-text notes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "manual_entries",
        sa.Column(
            "rem_intervention_feedback_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column(
        "manual_entries",
        "rem_intervention_feedback_json",
        schema="coach",
    )
