import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class SpecialPredictionType(StrEnum):
    tournament_winner = "tournament_winner"
    golden_boot = "golden_boot"
    top_scoring_team = "top_scoring_team"
    player_of_tournament = "player_of_tournament"
    young_player_of_tournament = "young_player_of_tournament"
    golden_glove = "golden_glove"


class Prediction(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("player_id", "match_id", name="uq_predictions_player_match"),
        Index("ix_predictions_player_id", "player_id"),
        Index("ix_predictions_match_id", "match_id"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    predicted_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_away: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    update_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    points_awarded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class KnockoutPrediction(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "knockout_predictions"
    __table_args__ = (
        UniqueConstraint("player_id", "match_id", name="uq_knockout_predictions_player_match"),
        Index("ix_knockout_predictions_player_id", "player_id"),
        Index("ix_knockout_predictions_match_id", "match_id"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    predicted_winner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    update_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    points_awarded: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SpecialPrediction(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "special_predictions"
    __table_args__ = (
        UniqueConstraint("player_id", "prediction_type", name="uq_special_predictions_player_type"),
        Index("ix_special_predictions_player_id", "player_id"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    prediction_type: Mapped[SpecialPredictionType] = mapped_column(
        Enum(SpecialPredictionType, name="special_prediction_type", create_type=False),
        nullable=False,
    )
    predicted_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    predicted_player_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    predicted_player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("squad_players.id", ondelete="SET NULL"),
        nullable=True,
    )
    winner_player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("squad_players.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    points_awarded: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LeaderboardSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "leaderboard_snapshots"
    __table_args__ = (
        Index(
            "ix_leaderboard_snapshots_snapshot_at_player_id",
            "snapshot_at",
            "player_id",
        ),
        Index("ix_leaderboard_snapshots_player_id", "player_id"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    league_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leagues.id"), nullable=False
    )
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    match_points: Mapped[int] = mapped_column(Integer, nullable=False)
    knockout_winner_points: Mapped[int] = mapped_column(Integer, nullable=False)
    special_points: Mapped[int] = mapped_column(Integer, nullable=False)
    # U38 tiebreak counts — the merit cascade that orders players level on
    # total_points. Computed atomically with rank by the scoring trigger /
    # recompute helper (migration 026), so the stored rank and the counts that
    # justify it always agree.
    exact_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    correct_result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    correct_goals_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    specials_correct_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ko_winner_correct_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    triggered_by_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="SET NULL"), nullable=True
    )


class LeaderboardTiebreakOverride(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    """Admin manual tiebreak order for a genuine all-axis tie (U38.4).

    Normally empty. The merit cascade resolves every realistic tie; when
    two players are level on *every* axis (essentially never), the cascade
    leaves them sharing a rank, flagged for admin settlement. The admin
    writes a row here so a prize can still be settled in-app without any
    arbitrary (timing / alphabetical / random) rule. ``manual_order`` is
    the final ORDER BY key (ascending, lower = higher rank, NULLS LAST),
    so it only ever decides an otherwise-exact tie.
    """

    __tablename__ = "leaderboard_tiebreak_overrides"
    __table_args__ = (
        UniqueConstraint("league_id", "player_id", name="uq_tiebreak_override_league_player"),
    )

    league_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    manual_order: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PushSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("ix_push_subscriptions_player_id", "player_id"),)

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    subscription: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    device_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failed_send_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class NotificationPreferences(Base, UpdatedAtMixin):
    __tablename__ = "notification_preferences"

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deadline_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    predict_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    pick_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    match_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    result_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    leaderboard_shift: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    round_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    match_postponed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    special_results: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    global_mute: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    quiet_hours_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    quiet_hours_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
