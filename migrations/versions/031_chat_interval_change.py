"""Let a coach answer carry the change it offered (Batch 264).

Revision ID: 031
Revises: 030
Create Date: 2026-09-17

Until now a negotiated plan change existed only as prose. The affordance under
the answer called the ordinary propose endpoint, which builds the IR straight
from the stored plan row, so on 2026-09-08 the coach said it would queue
"2×10 min blocks of 35s work / 25s recovery at 125%" and both taps proposed the
unchanged 40s/20s session. Eight such rows exist across six days; every one is
unadjusted and expired.

``proposed_interval_change`` is where the agreed block now lives: the five
numbers the coach may change, already run through ``validate_interval_block``
against today's live plan row, beside the block they replace. It is also the
record of exactly what Mark was shown before he confirmed, which is the same
reason every other AI interaction in this app is stored rather than transient
(Decision #194's storage fork).

Nullable and additive: every existing turn keeps meaning what it meant, and a
turn that carried no offer carries no change. RLS is already enabled on this
table (migration 019) and adding a column does not change that, so there is no
policy work here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "brief_messages",
        sa.Column("proposed_interval_change", postgresql.JSONB(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("brief_messages", "proposed_interval_change", schema="coach")
