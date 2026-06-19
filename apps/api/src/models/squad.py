"""SquadPlayer — WC 2026 footballer roster (48 teams × ~26 players)."""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.base import Base


class SquadPosition(StrEnum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class SquadPlayer(Base):
    __tablename__ = "squad_players"
    __table_args__ = (Index("ix_squad_players_team_id", "team_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    known_as: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[SquadPosition] = mapped_column(
        Enum(SquadPosition, name="squad_position", create_type=False), nullable=False
    )
    shirt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
