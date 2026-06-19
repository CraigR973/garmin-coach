"""Database backup service using pg_dump."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime


def _pg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy asyncpg URL to a standard postgresql:// DSN."""
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


def _safe_filename(filename: str) -> bool:
    """Accept only filenames that look like our own backup files."""
    return bool(re.fullmatch(r"coach_\d{8}_\d{6}\.sql", filename))


async def create_backup(backup_dir: str, database_url: str) -> BackupInfo:
    path = Path(backup_dir)
    path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = f"coach_{now.strftime('%Y%m%d_%H%M%S')}.sql"
    filepath = path / filename

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--no-password",
        "--format=plain",
        "--file",
        str(filepath),
        _pg_dsn(database_url),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        if filepath.exists():
            filepath.unlink()
        raise RuntimeError(f"pg_dump failed: {stderr.decode().strip()}")

    size = filepath.stat().st_size
    log.info("backup created", filename=filename, size_bytes=size)
    return BackupInfo(filename=filename, size_bytes=size, created_at=now)


def list_backups(backup_dir: str) -> list[BackupInfo]:
    path = Path(backup_dir)
    if not path.exists():
        return []
    files = sorted(
        (f for f in path.glob("coach_*.sql") if _safe_filename(f.name)),
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
