from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class PlayerRole(StrEnum):
    """Legacy single-league role enum. New code should use :class:`SiteRole`."""

    player = "player"
    admin = "admin"


class SiteRole(StrEnum):
    """Site-wide role introduced in M1 to disambiguate from per-league roles."""

    superadmin = "superadmin"
    user = "user"


class Profile(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "profiles"

    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[PlayerRole] = mapped_column(
        Enum(PlayerRole, name="player_role", create_type=False),
        nullable=False,
        server_default="player",
    )
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, server_default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    site_role: Mapped[SiteRole] = mapped_column(
        Enum(SiteRole, name="site_role", create_type=False),
        nullable=False,
    )
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
