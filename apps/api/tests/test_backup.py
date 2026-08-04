"""Tests for backup helpers — the password is kept out of the pg_dump argv (P3-6)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.services import backup as backup_module
from src.services.backup import _pg_dsn, _pg_password, _safe_filename, create_backup


def test_pg_dsn_strips_password_and_converts_scheme() -> None:
    dsn = _pg_dsn("postgresql+asyncpg://coach:s3cr3t@db.example.com:5432/garmin")
    assert dsn == "postgresql://coach@db.example.com:5432/garmin"
    assert "s3cr3t" not in dsn


def test_pg_dsn_preserves_query_params() -> None:
    dsn = _pg_dsn("postgresql+asyncpg://coach:pw@db:5432/garmin?sslmode=require")
    assert dsn == "postgresql://coach@db:5432/garmin?sslmode=require"
    assert "pw" not in dsn


def test_pg_password_extracts_and_url_decodes() -> None:
    # %40 -> @, %3A -> : : the env var must carry the decoded password.
    url = "postgresql+asyncpg://coach:p%40ss%3Aword@db.example.com:5432/garmin"
    assert _pg_password(url) == "p@ss:word"


def test_pg_helpers_handle_missing_password() -> None:
    url = "postgresql+asyncpg://coach@localhost/garmin"
    assert _pg_password(url) is None
    assert _pg_dsn(url) == "postgresql://coach@localhost/garmin"


def test_safe_filename_accepts_custom_format_dumps_only() -> None:
    assert _safe_filename("coach_20260803_030000.dump")
    # The plain-text era is over: those names must no longer round-trip, or a
    # stale .sql file would be served as if it were a restorable archive.
    assert not _safe_filename("coach_20260803_030000.sql")
    assert not _safe_filename("../../etc/passwd")


@pytest.mark.asyncio
async def test_create_backup_argv_is_compressed_and_skips_timeseries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly dump must not ship the sample stream, and must compress.

    Those two together are what took a ~300MB nightly pull down to single-digit
    MB after the run blew the Supabase egress quota.
    """
    captured: list[str] = []

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"", b"")

    async def fake_exec(*args: str, **kwargs: Any) -> _Proc:
        captured.extend(args)
        # Stand in for pg_dump actually writing the archive so the rename,
        # chmod and stat in create_backup all run for real.
        Path(args[args.index("--file") + 1]).write_bytes(b"PGDMP")
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    info = await create_backup(
        str(tmp_path), "postgresql+asyncpg://coach:s3cr3t@db.example.com:5432/garmin"
    )

    assert "--format=custom" in captured
    assert "--exclude-table-data=coach.activity_timeseries" in captured
    assert "--schema=coach" in captured
    assert info.filename.endswith(".dump")
    assert (tmp_path / info.filename).exists()
    # P3-6 still holds: the password travels in PGPASSWORD, never in argv.
    assert "s3cr3t" not in " ".join(captured)


def test_excluded_tables_are_recoverable_from_upstream() -> None:
    """Guard the judgement call: only re-derivable data may be excluded.

    Everything else in the coach schema is authored — analyses, check-ins,
    plans, chat — and has no upstream to replay from, so it must stay in.
    """
    assert backup_module.EXCLUDED_TABLE_DATA == ("coach.activity_timeseries",)
