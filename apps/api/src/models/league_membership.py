import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class LeagueMemberRole(StrEnum):
    admin = "admin"
    player = "player"


class LeagueMembership(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "league_memberships"
    __table_args__ = (
        UniqueConstraint("league_id", "player_id", name="uq_league_memberships_league_player"),
    )

    league_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leagues.id"), nullable=False
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    role: Mapped[LeagueMemberRole] = mapped_column(
        Enum(LeagueMemberRole, name="league_member_role", create_type=False),
        nullable=False,
        server_default="player",
    )
    display_name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
