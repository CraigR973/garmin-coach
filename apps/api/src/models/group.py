from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Group(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("name", name="uq_groups_name"),)

    name: Mapped[str] = mapped_column(String(1), nullable=False)
    standings_override: Mapped[Any] = mapped_column(JSONB, nullable=True, default=None)
