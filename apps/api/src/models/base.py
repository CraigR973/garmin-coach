import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), default=_utcnow, nullable=False
    )


def updated_at_column() -> MappedColumn[datetime]:
    """What ``updated_at`` means, on every table that has it (Batch 279).

    **The time of the row's last write by the application, on the application's
    clock** — naive UTC, the clock ``created_at`` uses. An insert stamps it in
    the same flush as ``created_at`` (microseconds apart, where it used to be
    Postgres's transaction-start ``now()`` and read seconds *before* the row was
    created); every UPDATE SQLAlchemy emits for the row stamps it again — an ORM
    flush or an ``update()`` statement — unless the statement sets it itself,
    which the lease and generation-status writers do and which wins.

    Nothing in the database enforces it — ``onupdate`` is written into the
    UPDATE by SQLAlchemy, not declared in the schema — so a write made outside
    the application, by direct SQL, leaves it alone. ``profiles`` is the one
    exception: migration 001's trigger restamps it on any UPDATE, with the
    database's clock.

    **Not backfilled.** Before Batch 279 the column advanced only where a writer
    set it by hand, so on thirteen of the eighteen tables a row last written
    before Batch 279 deployed still carries its insert time; it becomes a write
    time from that row's next write. Stamping the old rows now would record a
    write that never happened.

    The application clock rather than ``func.now()``: a SQL expression cannot
    be known in Python, so SQLAlchemy expires the attribute after every flush,
    and reading it afterwards under the async session is an implicit query that
    fails as ``MissingGreenlet``. A value computed in Python stays loaded.
    """
    return mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class UpdatedAtMixin(TimestampMixin):
    updated_at: Mapped[datetime] = updated_at_column()
