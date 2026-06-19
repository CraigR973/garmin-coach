"""Add M3 league/membership/join-request/invite values to action_type enum.

The per-league management endpoints (M3) write audit_log rows with new
``action_type`` values, but the Postgres enum was never extended — the M3/M4
tests mock the DB, so the gap only surfaced when M5's full-stack smoke test
created a league invite against real Postgres
(``invalid input value for enum action_type: "league_invite_created"``).

Mirrors migration 010: ``ADD VALUE IF NOT EXISTS`` is idempotent, and Postgres
cannot remove enum values so the downgrade is a no-op.

Revision ID: 013
Revises: 012
"""

from __future__ import annotations

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

# Every action_type the M3 league routers emit (leagues.py,
# league_memberships.py, league_join_requests.py) plus the invite-claim path.
_LEAGUE_ACTION_TYPES = (
    "league_created",
    "league_updated",
    "league_privacy_changed",
    "league_deleted",
    "member_joined",
    "member_left",
    "member_removed",
    "member_promoted",
    "member_demoted",
    "join_request_created",
    "join_request_approved",
    "join_request_rejected",
    "league_invite_created",
    "league_invite_revoked",
    "league_member_pin_reset",
)


def upgrade() -> None:
    for value in _LEAGUE_ACTION_TYPES:
        op.execute(f"ALTER TYPE action_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres does not support removing enum values; downgrade is a no-op.
    pass
