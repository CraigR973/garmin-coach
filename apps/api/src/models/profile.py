from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    player = "player"
    admin = "admin"


class SiteRole(StrEnum):
    """Kept for compatibility with auth module — superadmin maps to admin role."""

    superadmin = "superadmin"
    user = "user"


class Profile(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "profiles"

    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="player_role", create_type=False),
        nullable=False,
        server_default="player",
    )
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, server_default="UTC")
    garmin_user_profile_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hive_home_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Bedroom-fan overnight autopilot master switch (Batch 27.3). When false the
    # control loop no-ops and the fan is driven manually. See DECISIONS #96.
    fan_auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
