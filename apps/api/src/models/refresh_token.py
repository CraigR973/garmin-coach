import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    # Discriminates the token kind: 'refresh' (PIN-login JWT refresh — the
    # original use), 'device' (passwordless long-lived device token), or
    # 'activation' (single-use code exchanged for a device token).
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, server_default="refresh")
    # Set when a single-use activation code is consumed (NULL for other kinds).
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
