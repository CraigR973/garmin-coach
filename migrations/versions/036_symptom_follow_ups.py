"""Record Mark's answer to Home's chest or heart follow-up (Batch 315).

Revision ID: 036
Revises: 035
Create Date: 2026-10-06

After a chest or heart report the next morning was an ordinary day, VO2 included. From
Batch 315, until he says the symptoms have gone and that he has spoken to his GP or 111,
a hard session is an easy ride and Home asks him each morning, in one tap. His answer is
kept here, one row per morning he answers: "cleared" ends the follow-up, "not_seen"
keeps it, and "still_there" sets the chest-or-heart floor again that day.

It is not a column on the check-in, because the follow-up can be answered on a morning
he has not checked in, and a check-in row is what "he has checked in" means on Home and
the Sleep page.

Additive and nullable (the G8 run's rule, 6 Oct 2026): a new table, every column but the
key nullable, nothing existing altered. RLS is enabled where Supabase's ``auth`` schema
exists, the same guard every coach table since 015 uses. The downgrade drops the table
and his answers; the follow-up then asks again until he answers.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("symptom_follow_ups",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "symptom_follow_ups",
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
            nullable=True,
        ),
        sa.Column("subject_date", sa.Date(), nullable=True),
        sa.Column("reported_on", sa.Date(), nullable=True),
        sa.Column("answer", sa.String(16), nullable=True),
        sa.Column("answered_at_utc", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "user_id", "subject_date", name="uq_symptom_follow_ups_user_day"
        ),
        sa.CheckConstraint(
            "answer IN ('cleared', 'not_seen', 'still_there')",
            name="ck_symptom_follow_ups_answer",
        ),
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.symptom_follow_ups ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_table("symptom_follow_ups", schema="coach")
