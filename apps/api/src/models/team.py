import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TournamentStage(StrEnum):
    group = "group"
    r32 = "r32"
    r16 = "r16"
    qf = "qf"
    sf = "sf"
    third_place = "third_place"
    final = "final"
    winner = "winner"


class Team(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(3), nullable=False)
    flag_emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True
    )
    eliminated_at_stage: Mapped[TournamentStage | None] = mapped_column(
        Enum(TournamentStage, name="tournament_stage", create_type=False),
        nullable=True,
    )
    is_host: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    football_data_team_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
