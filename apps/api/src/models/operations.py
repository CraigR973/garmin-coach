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


class ProviderToken(Base):
    """The newest login a provider renewed, kept encrypted (Batch 365.3, Decision #462).

    garminconnect refreshes Garmin's token on its own, and the app threw each new one away:
    every poll logged in again from the deployed ``GARMIN_TOKENSTORE_B64`` (21 Jun's token,
    132 days later). One row per provider. ``ciphertext`` is Fernet, keyed from the deployed
    variable itself, and ``source_fingerprint`` names that variable, so a re-minted variable
    makes the stored token unreadable and the new variable wins. The variable stays the
    fallback whenever this row cannot be used.
    """

    __tablename__ = "provider_tokens"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
