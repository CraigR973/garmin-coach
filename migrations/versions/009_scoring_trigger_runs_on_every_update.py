"""scoring trigger: drop WHEN clause so any update to scores re-fires.

Until this migration, the AFTER UPDATE trigger ``matches_score_results``
only fired when the result transitioned from NULL → not-NULL. That forced
callers wanting to rescore (e.g. an admin override) to null the scores
first and then set them again — a two-step hack that worked but was easy
to get wrong.

This migration recreates the trigger without the WHEN clause. Any update
that touches ``actual_home_score`` or ``actual_away_score`` now re-fires
the cascade naturally. The ``OF actual_home_score, actual_away_score``
clause still keeps unrelated column updates (e.g. venue) from triggering
the cascade.

The BEFORE trigger ``matches_set_result_entered_at`` keeps its WHEN
clause so ``result_entered_at`` continues to mean "first entry time"
rather than "most recent override".

Revision ID: 009
Revises: 008
Create Date: 2026-05-19

"""

from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS matches_score_results ON matches")
    op.execute("""
        CREATE TRIGGER matches_score_results
        AFTER UPDATE OF actual_home_score, actual_away_score ON matches
        FOR EACH ROW
        EXECUTE FUNCTION matches_score_results();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS matches_score_results ON matches")
    op.execute("""
        CREATE TRIGGER matches_score_results
        AFTER UPDATE OF actual_home_score, actual_away_score ON matches
        FOR EACH ROW
        WHEN (
            (OLD.actual_home_score IS NULL OR OLD.actual_away_score IS NULL)
            AND NEW.actual_home_score IS NOT NULL
            AND NEW.actual_away_score IS NOT NULL
        )
        EXECUTE FUNCTION matches_score_results();
    """)
