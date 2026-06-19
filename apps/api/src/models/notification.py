import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPrimaryKeyMixin


class NotificationType(StrEnum):
    deadline_warning = "deadline_warning"
    predict_reminder = "predict_reminder"
    pick_confirmation = "pick_confirmation"
    match_locked = "match_locked"
    result_detected = "result_detected"
    leaderboard_shift = "leaderboard_shift"
    round_complete = "round_complete"
    match_postponed = "match_postponed"
    kickoff_changed = "kickoff_changed"
    invite_accepted = "invite_accepted"
    member_joined = "member_joined"
    auto_sync_failed = "auto_sync_failed"
    special_results = "special_results"
    specials_revealed = "specials_revealed"


class DeliveryStatus(StrEnum):
    sent = "sent"
    failed = "failed"
    expired = "expired"
    suppressed = "suppressed"


class ActorType(StrEnum):
    admin = "admin"
    player = "player"
    system = "system"


class ActionType(StrEnum):
    result_auto_fetched = "result_auto_fetched"
    result_manual_entered = "result_manual_entered"
    result_overridden = "result_overridden"
    match_postponed = "match_postponed"
    match_rescheduled = "match_rescheduled"
    match_cancelled = "match_cancelled"
    match_locked = "match_locked"
    kickoff_changed = "kickoff_changed"
    predictions_locked = "predictions_locked"
    player_removed = "player_removed"
    player_pin_reset = "player_pin_reset"
    invite_created = "invite_created"
    invite_revoked = "invite_revoked"
    knockout_advanced = "knockout_advanced"
    special_awarded = "special_awarded"
    sync_triggered = "sync_triggered"
    sync_failed = "sync_failed"
    tiebreaker_overridden = "tiebreaker_overridden"
    backup_failed = "backup_failed"
    backup_downloaded = "backup_downloaded"
    # M3 — league lifecycle
    league_created = "league_created"
    league_updated = "league_updated"
    league_privacy_changed = "league_privacy_changed"
    league_deleted = "league_deleted"
    # M3 — membership
    member_joined = "member_joined"
    member_left = "member_left"
    member_removed = "member_removed"
    member_promoted = "member_promoted"
    member_demoted = "member_demoted"
    # M3 — join requests
    join_request_created = "join_request_created"
    join_request_approved = "join_request_approved"
    join_request_rejected = "join_request_rejected"
    # M3 — per-league invites
    league_invite_created = "league_invite_created"
    league_invite_revoked = "league_invite_revoked"
    # M3 — per-league PIN reset
    league_member_pin_reset = "league_member_pin_reset"
    # U12 — join code rotation
    league_join_code_rotated = "league_join_code_rotated"


class NotificationLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "notification_log"
    __table_args__ = (
        Index("ix_notification_log_player_id", "player_id"),
        Index("ix_notification_log_sent_at", "sent_at"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", create_type=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status", create_type=False),
        nullable=False,
    )


class AuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor_id", "actor_id"),
        Index("ix_audit_log_timestamp", "timestamp"),
        Index("ix_audit_log_action_type", "action_type"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type", create_type=False),
        nullable=False,
    )
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, name="action_type", create_type=False),
        nullable=False,
    )
    target_table: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default="now()", nullable=False
    )
