"""Add confirm-before-apply conversation learning proposals (Batch 151).

Revision ID: 021
Revises: 020
Create Date: 2026-07-24

Conversation distillation never writes straight into the knowledge base. Each
candidate first lands here with its user-authored evidence and remains pending
until Mark or Craig accepts (optionally editing) or rejects it. Accepted content
is copied into the versioned ``knowledge_base`` ``learned_context`` section.

The table is user-scoped and RLS-enabled in the same guarded posture as the
other coach tables. The backend connects as the owning role and bypasses RLS;
the guard keeps plain Postgres/CI compatible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("conversation_learning_proposals",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "conversation_learning_proposals",
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
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column(
            "destination",
            sa.String(80),
            nullable=False,
            server_default="learned_context",
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "evidence_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_statement", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at_utc", sa.DateTime(), nullable=True),
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
            "user_id",
            "fingerprint",
            name="uq_conversation_learning_user_fingerprint",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_conversation_learning_user_status",
        "conversation_learning_proposals",
        ["user_id", "status", "created_at"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.conversation_learning_proposals
                    ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_conversation_learning_user_status",
        table_name="conversation_learning_proposals",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("conversation_learning_proposals", schema="coach")
