"""Tests for backup helpers — the password is kept out of the pg_dump argv (P3-6)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import ForeignKey

from src.models.base import Base
from src.services import backup as backup_module
from src.services.backup import (
    _archive_wire_bytes,
    _pg_dsn,
    _pg_password,
    _safe_filename,
    create_backup,
    latest_backup,
    list_backups,
)


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
    assert _safe_filename("coach_full_20261101_030000.dump")
    assert not _safe_filename("coach_weekly_20261101_030000.dump")
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
    # Batch 341 (DS328-05): the nightly leaves out Garmin's replayable tables too.
    assert "--exclude-table-data=coach.sleep" in captured
    assert "--exclude-table-data=coach.daily_metrics" in captured
    assert "--schema=coach" in captured
    assert info.filename.endswith(".dump")
    assert not info.full
    assert (tmp_path / info.filename).exists()
    # P3-6 still holds: the password travels in PGPASSWORD, never in argv.
    assert "s3cr3t" not in " ".join(captured)


def test_excluded_tables_are_recoverable_from_upstream() -> None:
    """Guard the judgement call: only re-derivable data may be excluded.

    Everything else in the coach schema is authored — analyses, check-ins,
    plans, chat — and has no upstream to replay from, so it must stay in.
    """
    assert backup_module.EXCLUDED_TABLE_DATA == ("coach.activity_timeseries",)
    # Batch 341: Garmin can re-supply these, so only the weekly archive keeps them.
    assert backup_module.WEEKLY_ONLY_TABLE_DATA == ("coach.sleep", "coach.daily_metrics")


def test_no_table_points_at_a_weekly_only_table() -> None:
    """A nightly archive restores on its own only if nothing it keeps points at what it drops.

    ``activities`` is replayable too, but analyses and check-ins point at it, so it
    stays nightly (Batch 341). A new foreign key onto a weekly-only table would make
    every nightly archive unrestorable without the weekly one.
    """
    weekly_only = {name.split(".", 1)[1] for name in backup_module.WEEKLY_ONLY_TABLE_DATA}
    pointing = [
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if isinstance(fk, ForeignKey) and fk.column.table.name in weekly_only
    ]
    assert pointing == []


@pytest.mark.asyncio
async def test_the_full_archive_keeps_garmins_tables_and_is_named_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"", b"")

    async def fake_exec(*args: str, **kwargs: Any) -> _Proc:
        if args[0] == "pg_dump":
            captured.extend(args)
            Path(args[args.index("--file") + 1]).write_bytes(b"PGDMP")
        return _Proc()

    async def fake_wire_bytes(archive: Path) -> int:
        return 123

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(backup_module, "_archive_wire_bytes", fake_wire_bytes)

    info = await create_backup(str(tmp_path), "postgresql+asyncpg://coach@db/garmin", full=True)

    assert info.full
    assert info.filename.startswith("coach_full_")
    assert info.wire_bytes == 123
    assert "--exclude-table-data=coach.activity_timeseries" in captured
    assert "--exclude-table-data=coach.sleep" not in captured
    assert "--exclude-table-data=coach.daily_metrics" not in captured


def _archive(path: Path, name: str, mtime: int) -> None:
    (path / name).write_bytes(b"PGDMP")
    os.utime(path / name, (mtime, mtime))


def test_the_two_kinds_sort_together_by_the_time_in_their_names(tmp_path: Path) -> None:
    """By name alone every ``coach_full_*`` would sort above every nightly."""
    _archive(tmp_path, "coach_full_20261101_030000.dump", 1)
    _archive(tmp_path, "coach_20261102_030000.dump", 2)
    _archive(tmp_path, "coach_20261031_030000.dump", 3)

    assert [b.filename for b in list_backups(str(tmp_path))] == [
        "coach_20261102_030000.dump",
        "coach_full_20261101_030000.dump",
        "coach_20261031_030000.dump",
    ]
    newest_full = latest_backup(str(tmp_path), full=True)
    newest_nightly = latest_backup(str(tmp_path), full=False)
    assert newest_full is not None and newest_full.filename == "coach_full_20261101_030000.dump"
    assert newest_nightly is not None and newest_nightly.filename == "coach_20261102_030000.dump"


@pytest.mark.asyncio
async def test_each_kind_keeps_its_own_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for day in range(1, 10):
        _archive(tmp_path, f"coach_202610{day:02d}_030000.dump", day)
    for day in range(10, 16):
        _archive(tmp_path, f"coach_full_202610{day:02d}_030000.dump", day)

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"", b"")

    async def fake_exec(*args: str, **kwargs: Any) -> _Proc:
        Path(args[args.index("--file") + 1]).write_bytes(b"PGDMP")
        return _Proc()

    async def no_wire_bytes(archive: Path) -> None:
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(backup_module, "_archive_wire_bytes", no_wire_bytes)

    await create_backup(str(tmp_path), "postgresql+asyncpg://coach@db/garmin")

    kinds = [b.full for b in list_backups(str(tmp_path))]
    assert kinds.count(False) == backup_module.BACKUP_RETENTION_COUNT
    assert kinds.count(True) == backup_module.FULL_BACKUP_RETENTION_COUNT


class _Stream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


@pytest.mark.asyncio
@pytest.mark.parametrize(("returncode", "expected"), [(0, 3_000_001), (1, None)])
async def test_the_wire_size_is_the_archives_rows_replayed_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, expected: int | None
) -> None:
    calls: list[tuple[str, ...]] = []

    class _Proc:
        stdout = _Stream([b"x" * 1_000_000, b"y" * 2_000_000, b"z"])

        async def wait(self) -> int:
            return returncode

    async def fake_exec(*args: str, **kwargs: Any) -> _Proc:
        calls.append(args)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    assert await _archive_wire_bytes(tmp_path / "coach_20261102_030000.dump") == expected
    # Found by a real run: pg_restore 16 refuses to write to stdout without "--file=-".
    assert calls[0][:3] == ("pg_restore", "--data-only", "--file=-")


@pytest.mark.asyncio
async def test_a_failed_measurement_never_fails_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*args: str, **kwargs: Any) -> None:
        raise FileNotFoundError("pg_restore")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)

    assert await _archive_wire_bytes(tmp_path / "coach_20261102_030000.dump") is None
