import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class ImprovementItem(Base, UUIDPrimaryKeyMixin):
    """One finding for the self-improving loop (Batch 390, G14, Decision #507).

    Every alert, degraded or failed job, written correction, coach pass-on and figure
    dispute also lands here, and later the daily reviewer's findings and Mark's
    suggestions. A stable ``fingerprint`` folds repeats into the one open row
    (``occurrences``). ``words`` is the only free text (Mark's words, the coach's
    summary) and is wiped 90 days after the row closes; ``summary`` and ``detail``
    carry codes and dates only.
    """

    __tablename__ = "improvement_items"
    __table_args__ = (
        CheckConstraint(
            "source IN ('alert', 'job_outcome', 'correction', 'pass_on', 'dispute', "
            "'review', 'suggestion')",
            name="ck_improvement_items_source",
        ),
        CheckConstraint(
            "state IN ('new', 'triaged', 'proposed', 'with_mark', 'approved', 'building', "
            "'shipped', 'verified', 'undone', 'escalated', 'dismissed')",
            name="ck_improvement_items_state",
        ),
        CheckConstraint(
            "lane IS NULL OR lane IN ('fix_alone', 'mark', 'evidence', 'craig')",
            name="ck_improvement_items_lane",
        ),
        CheckConstraint("occurrences >= 1", name="ck_improvement_items_occurrences"),
        Index(
            "uq_improvement_items_open_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("closed_utc IS NULL"),
        ),
        Index("ix_improvement_items_state_seen", "state", "last_seen_utc"),
        Index("ix_improvement_items_closed", "closed_utc"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="new")
    lane: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # ``none_as_null``: Python ``None`` is SQL NULL, not the JSON literal ``null``, so a
    # repeat with no words keeps the ones already held (COALESCE) and the wipe empties.
    words: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    source_refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_seen_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    last_seen_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    closed_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
