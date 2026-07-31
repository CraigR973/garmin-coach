"""Let a coach conversation exist without a document (Batch 179).

Revision ID: 026
Revises: 025
Create Date: 2026-07-31

``brief_messages.analysis_id`` was ``NOT NULL`` with an FK to ``analyses``
(migration 018), which made the schema assert that a conversation cannot exist
without a read. That is why chat could only ever hang off a generated document:
the Sleep page has no ``Analysis`` of its own (it borrows the morning read) and
the breathwork/strength/walking briefs are computed results rather than
``analyses`` rows at all, so none of them could host a conversation without
inventing a row purely as an anchor.

Batch 179 kickoff decision (`/batch-start`): **one rolling per-user thread with
a nullable anchor**, rather than a ``conversations``/``conversation_messages``
pair. The messages themselves already are the thread — ordered, user-scoped,
RLS-enabled — so the smaller change buys the continuity Mark asked for without
a second table, a backfill, or a rewrite of the learning-source queries. The
analysis a question was asked from becomes a *context seed* rather than a fence,
and existing per-read history stays readable in place because the old
``analysis_id`` filter still selects exactly the rows it always did.

``origin_kind``/``origin_date`` carry the seed for the surfaces that have no
analysis row, so "we're talking about last night's sleep" survives a page
reload. Both are nullable: existing rows are anchored reads and need neither.

RLS is already enabled on this table (migration 019), and altering a column
does not change that, so there is no policy work here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.alter_column(
        "brief_messages",
        "analysis_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
        schema="coach",
    )
    op.add_column(
        "brief_messages",
        sa.Column("origin_kind", sa.String(32), nullable=True),
        schema="coach",
    )
    op.add_column(
        "brief_messages",
        sa.Column("origin_date", sa.Date(), nullable=True),
        schema="coach",
    )
    # The thread is now read per user rather than per analysis, so the read path
    # that matters most needs its own index; 018's analysis index stays because
    # the per-read history view still uses it.
    op.create_index(
        "ix_brief_messages_user_created",
        "brief_messages",
        ["user_id", "created_utc"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_brief_messages_user_created",
        table_name="brief_messages",
        schema="coach",
        if_exists=True,
    )
    op.drop_column("brief_messages", "origin_date", schema="coach")
    op.drop_column("brief_messages", "origin_kind", schema="coach")
    # Unanchored messages cannot survive the column becoming NOT NULL again;
    # they are conversation turns that never had a document, so dropping them is
    # the only honest reversal.
    op.execute("DELETE FROM coach.brief_messages WHERE analysis_id IS NULL")
    op.alter_column(
        "brief_messages",
        "analysis_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
        schema="coach",
    )
