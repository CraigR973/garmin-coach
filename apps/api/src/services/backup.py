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
BACKUP_RETENTION_COUNT = 7

# Per-second sample streams are ~85% of the database and are the one thing here
# that is re-derivable from an upstream source (garmin_history_backfill replays
# them from Garmin). Dumping them nightly cost hundreds of MB of Supabase egress
# per run for data we can always fetch again, so the table's *definition* is
# kept and its rows are left out. Everything Claude wrote or Mark entered —
# analyses, check-ins, plans, profile, chat — is irreplaceable and stays in.
EXCLUDED_TABLE_DATA = ("coach.activity_timeseries",)


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class BackupRestoreResult:
    filename: str
    restored_tables: int
    alembic_version: str
    profile_rows: int
    analysis_rows: int
    excluded_activity_timeseries_rows: int


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


def _safe_filename(filename: str) -> bool:
    """Accept only filenames that look like our own backup files."""
    return bool(re.fullmatch(r"coach_\d{8}_\d{6}\.dump", filename))


def _prepare_backup_dir(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _set_owner_only_file(path: Path) -> None:
    os.chmod(path, 0o600)


def _prune_old_backups(path: Path, keep: int = BACKUP_RETENTION_COUNT) -> None:
    files = sorted(
        (f for f in path.glob("coach_*.dump") if _safe_filename(f.name)),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        old.unlink(missing_ok=True)


async def create_backup(backup_dir: str, database_url: str) -> BackupInfo:
    path = Path(backup_dir)
    _prepare_backup_dir(path)

    now = datetime.now(UTC)
    filename = f"coach_{now.strftime('%Y%m%d_%H%M%S')}.dump"
    filepath = path / filename
    partial = path / f".{filename}.partial"

    env = os.environ.copy()
    password = _pg_password(database_url)
    if password is not None:
        env["PGPASSWORD"] = password

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--no-password",
        # Custom format is compressed on the way out of the server, which is what
        # actually bills as egress, and it restores selectively via pg_restore.
        "--format=custom",
        "--schema=coach",
        *(f"--exclude-table-data={table}" for table in EXCLUDED_TABLE_DATA),
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
    log.info("backup created", filename=filename, size_bytes=size)
    return BackupInfo(filename=filename, size_bytes=size, created_at=now)


def list_backups(backup_dir: str) -> list[BackupInfo]:
    path = Path(backup_dir)
    if not path.exists():
        return []
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        log.warning("backup directory permissions are too broad", backup_dir=backup_dir)
    files = sorted(
        (f for f in path.glob("coach_*.dump") if _safe_filename(f.name)),
        reverse=True,
    )
    return [
        BackupInfo(
            filename=f.name,
            size_bytes=f.stat().st_size,
            created_at=datetime.fromtimestamp(f.stat().st_mtime, tz=UTC),
        )
        for f in files
    ]


def resolve_backup_path(backup_dir: str, filename: str) -> Path:
    if not _safe_filename(filename):
        raise ValueError("Invalid backup filename")
    base = Path(backup_dir).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid backup filename")
    return target


def latest_backup(backup_dir: str) -> BackupInfo | None:
    backups = list_backups(backup_dir)
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
) -> BackupRestoreResult:
    """Restore the newest archive into a disposable DB and assert core invariants."""

    if not restore_database_url:
        raise RuntimeError("BACKUP_RESTORE_DATABASE_URL is not configured")
    if _same_database(source_database_url, restore_database_url):
        raise RuntimeError("Backup restore drill refused to target the source database")

    backup = latest_backup(backup_dir)
    if backup is None:
        raise RuntimeError("No backup archive available to restore")
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

    result = await _validate_restored_backup(restore_database_url, backup.filename)
    log.info(
        "backup restore drill complete",
        filename=result.filename,
        restored_tables=result.restored_tables,
        alembic_version=result.alembic_version,
        profile_rows=result.profile_rows,
        analysis_rows=result.analysis_rows,
        excluded_activity_timeseries_rows=result.excluded_activity_timeseries_rows,
    )
    return result


async def _validate_restored_backup(
    restore_database_url: str,
    filename: str,
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
    if failures:
        raise RuntimeError("Backup restore invariant failed: " + "; ".join(failures))

    return BackupRestoreResult(
        filename=filename,
        restored_tables=int(restored_tables),
        alembic_version=str(alembic_version),
        profile_rows=int(profile_rows),
        analysis_rows=int(analysis_rows),
        excluded_activity_timeseries_rows=int(activity_timeseries_rows),
    )
