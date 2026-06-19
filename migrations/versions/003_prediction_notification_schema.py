"""prediction and notification schema: predictions, knockout_predictions, special_predictions,
leaderboard_snapshots, push_subscriptions, notification_preferences, notification_log, audit_log

Revision ID: 003
Revises: 002
Create Date: 2026-05-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ENUM types ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE special_prediction_type AS ENUM (
                'tournament_winner', 'golden_boot', 'top_scoring_team'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notification_type AS ENUM (
                'deadline_warning', 'match_locked', 'result_detected', 'leaderboard_shift',
                'round_complete', 'match_postponed', 'kickoff_changed', 'invite_accepted',
                'auto_sync_failed', 'special_results'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE delivery_status AS ENUM ('sent', 'failed', 'expired', 'suppressed');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE actor_type AS ENUM ('admin', 'player', 'system');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE action_type AS ENUM (
                'result_auto_fetched', 'result_manual_entered', 'result_overridden',
                'match_postponed', 'match_rescheduled', 'match_cancelled', 'kickoff_changed',
                'predictions_locked', 'player_removed', 'player_pin_reset', 'invite_created',
                'invite_revoked', 'knockout_advanced', 'special_awarded', 'sync_triggered',
                'sync_failed', 'tiebreaker_overridden'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # --- predictions ---
    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("predicted_home", sa.Integer(), nullable=True),
        sa.Column("predicted_away", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("update_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points_awarded", sa.Integer(), nullable=True),
        sa.Column("points_breakdown", JSONB(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "player_id", "match_id", name="uq_predictions_player_match"
        ),
    )
    op.create_index("ix_predictions_player_id", "predictions", ["player_id"])
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])
    op.execute("""
        CREATE TRIGGER predictions_set_updated_at
        BEFORE UPDATE ON predictions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # --- knockout_predictions ---
    op.create_table(
        "knockout_predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "predicted_winner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("update_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points_awarded", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "player_id", "match_id", name="uq_knockout_predictions_player_match"
        ),
    )
    op.create_index(
        "ix_knockout_predictions_player_id", "knockout_predictions", ["player_id"]
    )
    op.create_index(
        "ix_knockout_predictions_match_id", "knockout_predictions", ["match_id"]
    )
    op.execute("""
        CREATE TRIGGER knockout_predictions_set_updated_at
        BEFORE UPDATE ON knockout_predictions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # --- special_predictions ---
    op.create_table(
        "special_predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prediction_type",
            PgENUM(name="special_prediction_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "predicted_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("predicted_player_name", sa.String(100), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("points_awarded", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "player_id", "prediction_type", name="uq_special_predictions_player_type"
        ),
    )
    op.create_index(
        "ix_special_predictions_player_id", "special_predictions", ["player_id"]
    )
    op.execute("""
        CREATE TRIGGER special_predictions_set_updated_at
        BEFORE UPDATE ON special_predictions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # --- leaderboard_snapshots ---
    op.create_table(
        "leaderboard_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("match_points", sa.Integer(), nullable=False),
        sa.Column("knockout_winner_points", sa.Integer(), nullable=False),
        sa.Column("special_points", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "triggered_by_match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_leaderboard_snapshots_snapshot_at_player_id",
        "leaderboard_snapshots",
        ["snapshot_at", "player_id"],
    )
    op.create_index(
        "ix_leaderboard_snapshots_player_id", "leaderboard_snapshots", ["player_id"]
    )

    # --- push_subscriptions ---
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subscription", JSONB(), nullable=False),
        sa.Column("device_hint", sa.String(100), nullable=True),
        sa.Column(
            "failed_send_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        "ix_push_subscriptions_player_id", "push_subscriptions", ["player_id"]
    )

    # --- notification_preferences ---
    op.create_table(
        "notification_preferences",
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "deadline_warning", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("match_locked", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "result_detected", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "leaderboard_shift", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "round_complete", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "match_postponed", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "special_results", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("global_mute", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("""
        CREATE TRIGGER notification_preferences_set_updated_at
        BEFORE UPDATE ON notification_preferences
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # --- notification_log ---
    op.create_table(
        "notification_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "notification_type",
            PgENUM(name="notification_type", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "delivery_status",
            PgENUM(name="delivery_status", create_type=False),
            nullable=False,
        ),
    )
    op.create_index("ix_notification_log_player_id", "notification_log", ["player_id"])
    op.create_index("ix_notification_log_sent_at", "notification_log", ["sent_at"])

    # --- audit_log ---
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_type",
            PgENUM(name="actor_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            PgENUM(name="action_type", create_type=False),
            nullable=False,
        ),
        sa.Column("target_table", sa.String(50), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column("changes", JSONB(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_action_type", "audit_log", ["action_type"])


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS predictions_set_updated_at ON predictions")
    op.execute(
        "DROP TRIGGER IF EXISTS knockout_predictions_set_updated_at ON knockout_predictions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS special_predictions_set_updated_at ON special_predictions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS notification_preferences_set_updated_at ON notification_preferences"
    )

    op.drop_table("audit_log")
    op.drop_table("notification_log")
    op.drop_table("notification_preferences")
    op.drop_table("push_subscriptions")
    op.drop_table("leaderboard_snapshots")
    op.drop_table("special_predictions")
    op.drop_table("knockout_predictions")
    op.drop_table("predictions")

    op.execute("DROP TYPE IF EXISTS action_type")
    op.execute("DROP TYPE IF EXISTS actor_type")
    op.execute("DROP TYPE IF EXISTS delivery_status")
    op.execute("DROP TYPE IF EXISTS notification_type")
    op.execute("DROP TYPE IF EXISTS special_prediction_type")
