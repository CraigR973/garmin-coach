"""Database backup service using pg_dump."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)
#: Nightly archives kept.
BACKUP_RETENTION_COUNT = 7
#: Weekly full archives kept: a month of them.
FULL_BACKUP_RETENTION_COUNT = 4
#: The UTC weekday (Sunday) whose 03:00 run takes the full archive instead of the nightly.
FULL_BACKUP_WEEKDAY = 6

# Per-second sample streams are ~85% of the database and are the one thing here
# that is re-derivable from an upstream source (garmin_history_backfill replays
# them from Garmin). Dumping them nightly cost hundreds of MB of Supabase egress
# per run for data we can always fetch again, so the table's *definition* is
# kept and its rows are left out. Everything Claude wrote or Mark entered —
# analyses, check-ins, plans, profile, chat — is irreplaceable and stays in.
EXCLUDED_TABLE_DATA = ("coach.activity_timeseries",)

# Batch 341 (DS328-05): the nightly dump was about 146 MB of egress a night, about
# 4.4 GB of the free plan's 5.5 GB a month, and most of it was Garmin's own data
# that ``garmin_history_backfill`` can fetch again. So the nightly archive leaves
# these tables' rows out too, and one full archive a week (Sunday) keeps them.
# ``activities`` is replayable as well but stays nightly: analyses, check-ins and
# post-activity status rows point at it, so a nightly archive without it could
# not be restored on its own. Room temperatures have no upstream and stay nightly.
WEEKLY_ONLY_TABLE_DATA = ("coach.sleep", "coach.daily_metrics")


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime
    #: A weekly full archive (every table's rows but the per-second samples).
    full: bool = False
    #: The archive's table data as uncompressed COPY text, which is what crossed
    #: the pooler and counts as egress; ``None`` when it could not be measured.
    wire_bytes: int | None = None


@dataclass(frozen=True)
class BackupRestoreResult:
    filename: str
    restored_tables: int
    alembic_version: str
    profile_rows: int
    analysis_rows: int
    excluded_activity_timeseries_rows: int
    #: Rows the weekly-only tables restored: none from a nightly archive (Batch 341).
    weekly_only_rows: int = 0
    full: bool = False


def _pg_dsn(database_url: str) -> str:
    """SQLAlchemy asyncpg URL -> libpq postgresql:// DSN, with the password removed.

    The password is supplied out-of-band via PGPASSWORD (see ``_pg_password``) so
    it never appears in the pg_dump argv, which is visible to ``ps``. (P3-6.)
    """
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}@{host}" if parts.username else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _pg_password(database_url: str) -> str | None:
    """Extract the URL-decoded password from a SQLAlchemy/libpq URL, if present."""
    password = urlsplit(database_url).password
    return unquote(password) if password else None


def _asyncpg_url(database_url: str) -> str:
    """Normalize a libpq/SQLAlchemy URL for SQLAlchemy's asyncpg engine."""

    return re.sub(r"^postgresql://", "postgresql+asyncpg://", database_url)


_ARCHIVE_NAME = re.compile(r"coach_(?P<full>full_)?(?P<stamp>\d{8}_\d{6})\.dump")


def _safe_filename(filename: str) -> bool:
    """Accept only filenames that look like our own backup files."""
    return bool(_ARCHIVE_NAME.fullmatch(filename))


def _is_full(filename: str) -> bool:
    match = _ARCHIVE_NAME.fullmatch(filename)
    return bool(match and match.group("full"))


def _stamp(filename: str) -> str:
    """The ``YYYYMMDD_HHMMSS`` an archive's name carries ("" for any other name)."""
    match = _ARCHIVE_NAME.fullmatch(filename)
    return match.group("stamp") if match else ""


def _archives(path: Path, *, full: bool | None = None) -> list[Path]:
    """Our archives in ``path``, newest first by the time in their names.

    The name, not the file's mtime, so the two kinds sort together: by name alone
    every ``coach_full_*`` would sort after (above) every nightly.
    """
    found = [
        f
        for f in path.glob("coach_*.dump")
        if _safe_filename(f.name) and (full is None or _is_full(f.name) == full)
    ]
    return sorted(
        found,
        key=lambda f: (_stamp(f.name), f.name),
        reverse=True,
    )


def _prepare_backup_dir(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _set_owner_only_file(path: Path) -> None:
    os.chmod(path, 0o600)


def _prune_old_backups(path: Path) -> None:
    for full, keep in ((False, BACKUP_RETENTION_COUNT), (True, FULL_BACKUP_RETENTION_COUNT)):
        files = sorted(
            (f for f in path.glob("coach_*.dump") if _safe_filename(f.name)),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in [f for f in files if _is_full(f.name) == full][keep:]:
            old.unlink(missing_ok=True)


async def _archive_wire_bytes(archive: Path) -> int | None:
    """The archive's rows as uncompressed COPY text: what the dump pulled over the wire.

    Batch 341 (DS328-05): ``pg_dump --format=custom`` compresses inside pg_dump, after
    the rows have crossed the pooler as plain COPY text, so the archive's size (what
    the egress meter booked) was about a tenth of the egress. Replaying the archive's
    data to a byte count measures it locally, at no egress. A failure here never fails
    the backup.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_restore",
            "--data-only",
            # Since PostgreSQL 12 pg_restore needs -f or -d; "-" is stdout.
            "--file=-",
            str(archive),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if proc.stdout is None:
            return None
        total = 0
        while chunk := await proc.stdout.read(1 << 20):
            total += len(chunk)
        if await proc.wait() != 0:
            return None
        return total
    except Exception:  # noqa: BLE001 — a measurement, never a reason to lose the archive
        log.warning("backup wire size not measured", archive=archive.name, exc_info=True)
        return None


async def create_backup(backup_dir: str, database_url: str, *, full: bool = False) -> BackupInfo:
    """One archive: the nightly by default, or the weekly ``full`` one (Batch 341)."""
    path = Path(backup_dir)
    _prepare_backup_dir(path)

    now = datetime.now(UTC)
    kind = "full_" if full else ""
    filename = f"coach_{kind}{now.strftime('%Y%m%d_%H%M%S')}.dump"
    excluded = EXCLUDED_TABLE_DATA if full else EXCLUDED_TABLE_DATA + WEEKLY_ONLY_TABLE_DATA
    filepath = path / filename
    partial = path / f".{filename}.partial"

    env = os.environ.copy()
    password = _pg_password(database_url)
    if password is not None:
        env["PGPASSWORD"] = password

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--no-password",
        # Custom format restores selectively via pg_restore and is small on the volume.
        # It is compressed inside pg_dump, after the rows have crossed the pooler, so it
        # saves disk, not egress (Batch 341: the old comment here said the opposite).
        "--format=custom",
        "--schema=coach",
        *(f"--exclude-table-data={table}" for table in excluded),
        "--file",
        str(partial),
        _pg_dsn(database_url),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {stderr.decode().strip()}")

    _set_owner_only_file(partial)
    os.replace(partial, filepath)
    _set_owner_only_file(filepath)
    _prune_old_backups(path)

    size = filepath.stat().st_size
    wire_bytes = await _archive_wire_bytes(filepath)
    log.info("backup created", filename=filename, size_bytes=size, wire_bytes=wire_bytes, full=full)
    return BackupInfo(
        filename=filename, size_bytes=size, created_at=now, full=full, wire_bytes=wire_bytes
    )


def list_backups(backup_dir: str) -> list[BackupInfo]:
    path = Path(backup_dir)
    if not path.exists():
        return []
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        log.warning("backup directory permissions are too broad", backup_dir=backup_dir)
    return [
        BackupInfo(
            filename=f.name,
            size_bytes=f.stat().st_size,
            created_at=datetime.fromtimestamp(f.stat().st_mtime, tz=UTC),
            full=_is_full(f.name),
        )
        for f in _archives(path)
    ]


def resolve_backup_path(backup_dir: str, filename: str) -> Path:
    if not _safe_filename(filename):
        raise ValueError("Invalid backup filename")
    base = Path(backup_dir).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid backup filename")
    return target


def latest_backup(backup_dir: str, *, full: bool | None = None) -> BackupInfo | None:
    """The newest archive, or the newest of one kind."""
    backups = [b for b in list_backups(backup_dir) if full is None or b.full == full]
    return backups[0] if backups else None


def _same_database(left_url: str, right_url: str) -> bool:
    left = urlsplit(_pg_dsn(left_url))
    right = urlsplit(_pg_dsn(right_url))
    return (
        left.hostname,
        left.port,
        left.username,
        left.path,
    ) == (
        right.hostname,
        right.port,
        right.username,
        right.path,
    )


async def restore_latest_backup(
    backup_dir: str,
    source_database_url: str,
    restore_database_url: str,
) -> list[BackupRestoreResult]:
    """Restore the newest archive of each kind into a disposable DB and assert invariants.

    Batch 341: the weekly full archive first, then the newest nightly, so each kind is
    proved restorable on its own; the nightly goes last and leaves the freshest state.
    """

    if not restore_database_url:
        raise RuntimeError("BACKUP_RESTORE_DATABASE_URL is not configured")
    if _same_database(source_database_url, restore_database_url):
        raise RuntimeError("Backup restore drill refused to target the source database")

    archives = [
        backup
        for backup in (
            latest_backup(backup_dir, full=True),
            latest_backup(backup_dir, full=False),
        )
        if backup is not None
    ]
    if not archives:
        raise RuntimeError("No backup archive available to restore")
    return [await _restore_one(backup_dir, backup, restore_database_url) for backup in archives]


async def _restore_one(
    backup_dir: str, backup: BackupInfo, restore_database_url: str
) -> BackupRestoreResult:
    archive = resolve_backup_path(backup_dir, backup.filename)

    env = os.environ.copy()
    password = _pg_password(restore_database_url)
    if password is not None:
        env["PGPASSWORD"] = password

    proc = await asyncio.create_subprocess_exec(
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--dbname",
        _pg_dsn(restore_database_url),
        str(archive),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pg_restore failed: {stderr.decode().strip()}")

    result = await _validate_restored_backup(
        restore_database_url, backup.filename, full=backup.full
    )
    log.info(
        "backup restore drill complete",
        filename=result.filename,
        full=result.full,
        restored_tables=result.restored_tables,
        alembic_version=result.alembic_version,
        profile_rows=result.profile_rows,
        analysis_rows=result.analysis_rows,
        excluded_activity_timeseries_rows=result.excluded_activity_timeseries_rows,
        weekly_only_rows=result.weekly_only_rows,
    )
    return result


async def _validate_restored_backup(
    restore_database_url: str,
    filename: str,
    *,
    full: bool = False,
) -> BackupRestoreResult:
    engine = create_async_engine(
        _asyncpg_url(restore_database_url),
        pool_pre_ping=True,
        connect_args={
            "server_settings": {"search_path": "coach,public"},
            "prepared_statement_cache_size": 0,
        },
    )
    try:
        async with engine.connect() as conn:
            restored_tables = (
                await conn.execute(
                    text(
                        """
                        select count(*)
                        from information_schema.tables
                        where table_schema = 'coach'
                          and table_type = 'BASE TABLE'
                        """
                    )
                )
            ).scalar_one()
            alembic_version = (
                await conn.execute(
                    text(
                        """
                        select version_num
                        from coach.alembic_version
                        order by version_num desc
                        limit 1
                        """
                    )
                )
            ).scalar_one_or_none()
            profile_rows = (
                await conn.execute(text("select count(*) from coach.profiles"))
            ).scalar_one()
            analysis_rows = (
                await conn.execute(text("select count(*) from coach.analyses"))
            ).scalar_one()
            activity_timeseries_rows = (
                await conn.execute(text("select count(*) from coach.activity_timeseries"))
            ).scalar_one()
            weekly_only_sql = "select " + " + ".join(
                f"(select count(*) from {table})" for table in WEEKLY_ONLY_TABLE_DATA
            )
            weekly_only_rows = (await conn.execute(text(weekly_only_sql))).scalar_one()
    finally:
        await engine.dispose()

    failures: list[str] = []
    if restored_tables < 20:
        failures.append(f"expected at least 20 coach tables, restored {restored_tables}")
    if not alembic_version:
        failures.append("coach.alembic_version is empty")
    if profile_rows < 1:
        failures.append("coach.profiles restored zero rows")
    if analysis_rows < 1:
        failures.append("coach.analyses restored zero rows")
    if activity_timeseries_rows != 0:
        failures.append(
            "coach.activity_timeseries should restore its definition only, "
            f"found {activity_timeseries_rows} rows"
        )
    if full and weekly_only_rows < 1:
        failures.append("the full archive restored no sleep or daily-metrics rows")
    if not full and weekly_only_rows != 0:
        failures.append(
            "a nightly archive should restore the weekly-only tables' definitions only, "
            f"found {weekly_only_rows} rows"
        )
    if failures:
        raise RuntimeError("Backup restore invariant failed: " + "; ".join(failures))

    return BackupRestoreResult(
        filename=filename,
        restored_tables=int(restored_tables),
        alembic_version=str(alembic_version),
        profile_rows=int(profile_rows),
        analysis_rows=int(analysis_rows),
        excluded_activity_timeseries_rows=int(activity_timeseries_rows),
        weekly_only_rows=int(weekly_only_rows),
        full=full,
    )
