"""Add durable paid-generation request identities and leases (Batch 161).

Revision ID: 024
Revises: 023
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("generation_requests",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "generation_requests",
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
        sa.Column("request_identity", sa.String(64), nullable=False),
        sa.Column("generation_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.String(40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "request_identity",
            name="uq_generation_requests_identity",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_generation_requests_user_status",
        "generation_requests",
        ["user_id", "status"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.generation_requests ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_generation_requests_user_status",
        table_name="generation_requests",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("generation_requests", schema="coach")
