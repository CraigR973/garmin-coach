"""security: set explicit search_path on scoring trigger functions.

Supabase security advisor (WARN) flags trigger functions without an explicit
``search_path`` as mutable: a malicious schema placed earlier on
``search_path`` can shadow ``public`` tables/types and hijack function logic.

Affected functions created or replaced by earlier migrations (004, 005, 001,
026) without a locked ``search_path``:

  * ``calculate_match_points``    (004)
  * ``matches_set_result_entered_at`` (005)
  * ``matches_score_results``     (026)
  * ``set_updated_at``            (001)

Using ``ALTER FUNCTION ... SET search_path = public`` is non-destructive —
the function bodies and triggers are left untouched; only the config option
is stamped on the catalog entry.  Downgrade resets the option back to the
PostgreSQL default (empty / inherited from session).

Revision ID: 028
Revises: 027
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision: str = "028"
down_revision: str = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER FUNCTION calculate_match_points(INT, INT, INT, INT, tournament_stage) "
        "SET search_path = public"
    )
    op.execute(
        "ALTER FUNCTION matches_set_result_entered_at() SET search_path = public"
    )
    op.execute("ALTER FUNCTION matches_score_results() SET search_path = public")
    op.execute("ALTER FUNCTION set_updated_at() SET search_path = public")


def downgrade() -> None:
    op.execute(
        "ALTER FUNCTION calculate_match_points(INT, INT, INT, INT, tournament_stage) "
        "RESET search_path"
    )
    op.execute("ALTER FUNCTION matches_set_result_entered_at() RESET search_path")
    op.execute("ALTER FUNCTION matches_score_results() RESET search_path")
    op.execute("ALTER FUNCTION set_updated_at() RESET search_path")
