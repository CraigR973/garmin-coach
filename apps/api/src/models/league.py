import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class LeaguePrivacy(StrEnum):
    private = "private"
    public_request = "public_request"
    public_open = "public_open"


class League(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "leagues"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_leagues_slug"),
        CheckConstraint(
            "max_members BETWEEN 2 AND 50",
            name="ck_leagues_max_members_range",
        ),
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy: Mapped[LeaguePrivacy] = mapped_column(
        Enum(LeaguePrivacy, name="league_privacy", create_type=False),
        nullable=False,
        server_default="private",
    )
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, server_default="15")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    join_code: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        unique=True,
        server_default=sa.text("upper(substr(md5(random()::text), 1, 6))"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
