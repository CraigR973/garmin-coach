"""Add hosted read-aloud voice consent flag to profiles.

Revision ID: 016
Revises: 015
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "profiles",
        sa.Column(
            "hosted_tts_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("profiles", "hosted_tts_consent", schema="coach")
