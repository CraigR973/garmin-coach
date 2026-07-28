from __future__ import annotations

import asyncio
import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from src.services import backup

ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str) -> ModuleType:
    return _load_file(ROOT / "scripts" / name)


def _load_migration(name: str) -> ModuleType:
    return _load_file(ROOT / "migrations" / "versions" / name)


def _load_file(path: Path) -> ModuleType:
    name = path.name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name.removesuffix(".py")] = module
    spec.loader.exec_module(module)
    return module


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_secret_file_writer_creates_owner_only_file(tmp_path: Path) -> None:
    secure_artifacts = _load_script("secure_artifacts.py")
    target = tmp_path / "nested" / "tokens.env"

    secure_artifacts.write_secret_file(target, "TOKEN=secret\n")

    assert target.read_text(encoding="utf-8") == "TOKEN=secret\n"
    assert _mode(target) == 0o600
    assert _mode(target.parent) == 0o700


def test_secret_file_writer_refuses_unsafe_existing_file(tmp_path: Path) -> None:
    secure_artifacts = _load_script("secure_artifacts.py")
    target = tmp_path / "tokens.env"
    target.write_text("TOKEN=old\n", encoding="utf-8")
    os.chmod(target, 0o644)

    with pytest.raises(SystemExit):
        secure_artifacts.write_secret_file(target, "TOKEN=new\n")

    assert target.read_text(encoding="utf-8") == "TOKEN=old\n"


class _FakeProc:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


@pytest.mark.asyncio
async def test_create_backup_scopes_schema_permissions_and_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    for index in range(8):
        old = tmp_path / f"coach_20260727_03000{index}.sql"
        old.write_text("old\n", encoding="utf-8")
        os.utime(old, (index, index))

    async def fake_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        calls.append(args)
        output_path = Path(args[args.index("--file") + 1])
        output_path.write_text("dump\n", encoding="utf-8")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)

    info = await backup.create_backup(
        str(tmp_path),
        "postgresql+asyncpg://coach:p%40ss@db.example.com:5432/garmin",
    )

    assert info.filename.startswith("coach_")
    argv = calls[0]
    assert "--schema=coach" in argv
    assert "--file" in argv
    assert Path(argv[argv.index("--file") + 1]).name.startswith(".coach_")
    assert _mode(tmp_path) == 0o700
    assert _mode(tmp_path / info.filename) == 0o600
    assert len(list(tmp_path.glob("coach_*.sql"))) == backup.BACKUP_RETENTION_COUNT


@pytest.mark.asyncio
async def test_create_backup_removes_failed_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        output_path = Path(args[args.index("--file") + 1])
        output_path.write_text("partial\n", encoding="utf-8")
        return _FakeProc(returncode=1, stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)

    with pytest.raises(RuntimeError, match="boom"):
        await backup.create_backup(str(tmp_path), "postgresql+asyncpg://coach@db/garmin")

    assert list(tmp_path.glob("*.partial")) == []
    assert list(tmp_path.glob("coach_*.sql")) == []


def test_rls_posture_evaluator_fails_simulated_regressions() -> None:
    check_rls = _load_script("check_rls_posture.py")

    failures = check_rls.evaluate_posture(
        check_rls.PostureSnapshot(
            tables_without_rls=("analyses",),
            data_api_schema_grants=("authenticated:USAGE",),
            data_api_table_grants=("anon:profiles:SELECT",),
            exposed_schemas=("public", "graphql_public", "coach"),
            policies_without_authenticated=("profiles.profiles_select_own",),
            update_policies_without_check=("profiles.profiles_update_own",),
            public_executable_functions=("coach.set_updated_at()",),
            functions_with_mutable_search_path=("coach.set_updated_at()",),
        )
    )

    assert len(failures) == 8
    assert any("tables without RLS" in failure for failure in failures)
    assert any("unexpected exposed schemas" in failure for failure in failures)


def test_rls_posture_evaluator_accepts_expected_posture() -> None:
    check_rls = _load_script("check_rls_posture.py")

    failures = check_rls.evaluate_posture(
        check_rls.PostureSnapshot(
            tables_without_rls=(),
            data_api_schema_grants=(),
            data_api_table_grants=(),
            exposed_schemas=("public", "graphql_public"),
            policies_without_authenticated=(),
            update_policies_without_check=(),
            public_executable_functions=(),
            functions_with_mutable_search_path=(),
        )
    )

    assert failures == []


def test_security_ops_migration_lists_hardened_policies() -> None:
    migration = _load_migration("025_security_ops_rls_hardening.py")

    assert "profiles_update_own" in migration.HARDENED_POLICIES
    assert "notification_preferences_update_own" in migration.HARDENED_POLICIES
    assert len(migration.HARDENED_POLICIES) == 9
