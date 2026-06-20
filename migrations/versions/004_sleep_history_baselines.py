"""Add persisted metric baselines for sleep-history backfill.

Revision ID: 004
Revises: 003
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_baselines",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(length=80), nullable=False),
        sa.Column("metric_label", sa.String(length=120), nullable=False),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default="sleep_history_xlsx",
        ),
        sa.Column("window_start_date", sa.Date(), nullable=False),
        sa.Column("window_end_date", sa.Date(), nullable=False),
        sa.Column("reliability_start_date", sa.Date(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("excluded_sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_value", sa.Float(), nullable=True),
        sa.Column("median_value", sa.Float(), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("lower_quartile_value", sa.Float(), nullable=True),
        sa.Column("upper_quartile_value", sa.Float(), nullable=True),
        sa.Column("stddev_value", sa.Float(), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "user_id",
            "metric_key",
            "source",
            name="uq_metric_baselines_user_metric_source",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_metric_baselines_user_metric",
        "metric_baselines",
        ["user_id", "metric_key"],
        schema="coach",
    )


def downgrade() -> None:
    op.drop_index("ix_metric_baselines_user_metric", table_name="metric_baselines", schema="coach")
    op.drop_table("metric_baselines", schema="coach")
