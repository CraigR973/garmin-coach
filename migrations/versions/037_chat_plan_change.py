"""Let a coach answer carry a change to his proposed plan (Batch 324).

Revision ID: 037
Revises: 036
Create Date: 2026-10-07

Craig, 7 Oct 2026: Mark should be able to talk his proposed next plan through with the
coach, and the coach may offer a change he applies with one tap. The offer is checked
against the draft as it stands when the answer is written (``plan_conversation``), and is
kept with the answer: the change, the words it was shown in, and the revision of the draft
it was made against, so a tap on an offer the plan has moved past is refused rather than
applied to a plan he was not looking at. It is also the record of what he was shown and
whether he applied it, which is why it is stored rather than rebuilt (Decision #194's
storage fork, as ``proposed_interval_change`` in migration 031).

Additive and nullable (the G8 run's rule, 6 Oct 2026): every existing turn keeps meaning
what it meant, and a turn that offered no plan change carries none. RLS is already enabled
on this table (migration 019) and adding a column does not change that. The downgrade
drops the column and the offers in it; the answers themselves are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "brief_messages",
        sa.Column("proposed_plan_change", postgresql.JSONB(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("brief_messages", "proposed_plan_change", schema="coach")
