"""Database backup service using pg_dump."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime


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


def _safe_filename(filename: str) -> bool:
    """Accept only filenames that look like our own backup files."""
    return bool(re.fullmatch(r"coach_\d{8}_\d{6}\.sql", filename))


async def create_backup(backup_dir: str, database_url: str) -> BackupInfo:
    path = Path(backup_dir)
    path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = f"coach_{now.strftime('%Y%m%d_%H%M%S')}.sql"
    filepath = path / filename

    env = os.environ.copy()
    password = _pg_password(database_url)
    if password is not None:
        env["PGPASSWORD"] = password

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--no-password",
        "--format=plain",
        "--file",
        str(filepath),
        _pg_dsn(database_url),
        env=env,
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
