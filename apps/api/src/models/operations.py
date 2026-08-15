from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPrimaryKeyMixin


class JobRun(Base, UUIDPrimaryKeyMixin):
    """Durable operator evidence for one scheduled-job invocation."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'skipped', 'degraded', 'failed')",
            name="ck_job_runs_status",
        ),
        CheckConstraint(
            "scheduled_window_end_utc > scheduled_window_start_utc",
            name="ck_job_runs_window",
        ),
        CheckConstraint(
            "finished_at_utc >= started_at_utc",
            name="ck_job_runs_duration",
        ),
        Index("ix_job_runs_job_started", "job_name", "started_at_utc"),
        Index("ix_job_runs_status_started", "status", "started_at_utc"),
    )

    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_window_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    scheduled_window_end_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    finished_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    counters: Mapped[dict[str, int]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
