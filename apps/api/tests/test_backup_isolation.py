"""Batch 371: real crypto, remote corruption and restore target boundaries."""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src import backup_drill
from src.services import backup
from src.services.backup_crypto import decrypt_archive, encrypt_archive
from src.services.backup_offsite import BackupBucket, RemoteArchive
from src.services.backup_proof import proof_counters

TARGET = "postgresql://coach_restore:secret@127.0.0.1:55432/coach_restore?sslmode=disable"
NOW = datetime(2026, 11, 8, 4, 17, tzinfo=UTC)


@pytest.fixture
def cluster_directories(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Observe cleanup without granting the restore login server-settings access."""
    original = backup_drill.tempfile.TemporaryDirectory
    paths: list[Path] = []

    def track(*args: Any, **kwargs: Any) -> Any:
        directory = original(*args, **kwargs)
        if kwargs.get("prefix") == "coach-restore-db-":
            paths.append(Path(directory.name) / "data")
        return directory

    monkeypatch.setattr(backup_drill.tempfile, "TemporaryDirectory", track)
    return paths


@pytest.fixture
def age_keys(tmp_path: Path) -> tuple[Path, str]:
    key = tmp_path / "identity"
    subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
    recipient = subprocess.run(
        ["age-keygen", "-y", str(key)], check=True, capture_output=True, text=True
    ).stdout.strip()
    return key, recipient


@pytest.mark.asyncio
async def test_real_age_round_trip_and_tamper_cleanup(
    tmp_path: Path, age_keys: tuple[Path, str]
) -> None:
    key, recipient = age_keys
    plain, cipher, restored = (tmp_path / n for n in ("plain", "cipher", "restored"))
    plain.write_bytes(b"PGDMP synthetic authored data")
    await encrypt_archive(plain, cipher, recipient)
    assert cipher.read_bytes().startswith(b"age-encryption.org/v1\n")
    assert b"synthetic" not in cipher.read_bytes()
    assert cipher.stat().st_mode & 0o777 == 0o600
    await decrypt_archive(cipher, restored, key)
    assert restored.read_bytes() == plain.read_bytes()
    restored.unlink()
    data = bytearray(cipher.read_bytes())
    data[-1] ^= 1
    cipher.write_bytes(data)
    with pytest.raises(RuntimeError, match="backup_age_failed"):
        await decrypt_archive(cipher, restored, key)
    assert not restored.exists()


@pytest.mark.asyncio
async def test_missing_public_key_fails_before_dump_or_files(tmp_path: Path) -> None:
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as proc:
        with pytest.raises(RuntimeError, match="recipient_invalid_or_unset"):
            await backup.create_backup(str(tmp_path), "postgresql://unused", recipient="")
    proc.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_failed_integrity_retains_no_cipher_or_plain_on_volume(
    tmp_path: Path, age_keys: tuple[Path, str]
) -> None:
    class Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def dump(*args: str, **kwargs: Any) -> Proc:
        path = Path(args[args.index("--file") + 1])
        assert tmp_path not in path.parents  # No plaintext on retained volume.
        path.write_bytes(b"bad archive")
        return Proc()

    with (
        patch("asyncio.create_subprocess_exec", dump),
        patch.object(backup, "_archive_wire_bytes", AsyncMock(return_value=None)),
    ):
        with pytest.raises(RuntimeError, match="integrity_failed"):
            await backup.create_backup(str(tmp_path), "postgresql://unused", recipient=age_keys[1])
    assert list(tmp_path.iterdir()) == [age_keys[0]]


def auth(
    *,
    writer: bool = False,
    capabilities: list[str] | None = None,
    buckets: Any = None,
    prefix: str | None = "coach/",
) -> dict[str, Any]:
    return {
        "authorizationToken": "private-token",
        "apiInfo": {
            "storageApi": {
                "apiUrl": "https://api001.backblazeb2.com",
                "downloadUrl": "https://f001.backblazeb2.com",
                "allowed": {
                    "buckets": [{"id": "bucket"}] if buckets is None else buckets,
                    "namePrefix": prefix,
                    "capabilities": capabilities
                    or (["writeFiles"] if writer else ["readFiles", "listFiles"]),
                },
            }
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"capabilities": ["writeFiles", "deleteFiles"]},
        {"capabilities": ["writeFiles", "readFiles"]},
        {"capabilities": ["writeFiles", "writeKeys"]},
        {"buckets": []},
        {"buckets": [{"id": "other"}]},
        {"prefix": None},
    ],
)
async def test_b2_rejects_excess_privilege_and_wrong_scope(changes: dict[str, Any]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=auth(writer=True, **changes))
        )
    ) as client:
        bucket = BackupBucket(client, "bucket")
        with pytest.raises(RuntimeError, match="key_scope_rejected"):
            await bucket.authorize("id", "key", writer=True)


@pytest.mark.asyncio
async def test_b2_upload_ciphertext_only_and_verify_receipt(tmp_path: Path) -> None:
    cipher = tmp_path / "coach_full_20261108_030000.dump.age"
    body = b"age-encryption.org/v1\nsynthetic ciphertext"
    cipher.write_bytes(body)
    requests: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        if req.url.path.endswith("b2_authorize_account"):
            return httpx.Response(200, json=auth(writer=True))
        if req.url.path.endswith("b2_get_upload_url"):
            return httpx.Response(
                200,
                json={
                    "uploadUrl": "https://pod001.backblaze.com/upload",
                    "authorizationToken": "upload-token",
                },
            )
        assert req.content == body
        assert req.headers["X-Bz-Content-Sha1"] == hashlib.sha1(body).hexdigest()
        return httpx.Response(
            200,
            json={
                "contentLength": len(body),
                "fileName": "coach/" + cipher.name,
                "contentSha1": hashlib.sha1(body).hexdigest(),
                "bucketId": "bucket",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bucket = BackupBucket(client, "bucket")
        await bucket.authorize("id", "key", writer=True)
        assert await bucket.upload(cipher) == len(body)
        cipher.write_bytes(b"PGDMP this is plaintext despite the name")
        with pytest.raises(RuntimeError, match="ciphertext_only"):
            await bucket.upload(cipher)
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"corrupt", b"correct-but-too-long"])
async def test_corrupt_download_is_removed(tmp_path: Path, body: bytes) -> None:
    expected = b"correct"
    meta = RemoteArchive(
        "coach_20261107_030000.dump.age",
        "file",
        len(expected),
        hashlib.sha1(expected).hexdigest(),
        hashlib.sha256(expected).hexdigest(),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body))
    ) as client:
        bucket = BackupBucket(client, "bucket")
        bucket.token = "token"
        bucket.download_url = "https://f001.backblazeb2.com"
        target = tmp_path / "download"
        with pytest.raises(RuntimeError, match="backup_download_"):
            await bucket.download(meta, target)
        assert not target.exists()
        target.write_bytes(b"preserve existing")
        with pytest.raises(FileExistsError):
            await bucket.download(meta, target)
        assert target.read_bytes() == b"preserve existing"


def file(name: str) -> dict[str, Any]:
    return {
        "fileName": "coach/" + name,
        "fileId": name,
        "contentLength": 10,
        "contentSha1": "a" * 40,
        "fileInfo": {"sha256": "b" * 64},
        "action": "upload",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("day_offset", [0, 3])
async def test_remote_pair_paginates_and_checks_actual_archive_age(day_offset: int) -> None:
    pages = [
        {"files": [file("coach_full_20261108_030000.dump.age")], "nextFileName": "cursor"},
        {"files": [file("coach_20261107_030000.dump.age")], "nextFileName": None},
    ]
    async with httpx.AsyncClient() as client:
        bucket = BackupBucket(client, "bucket")
        with patch.object(bucket, "_call", AsyncMock(side_effect=pages)) as call:
            pair = await bucket.latest_pair(now=NOW + timedelta(days=day_offset))
        assert len(pair) == 2 and call.await_count == 2
        assert call.await_args_list[1].args[1]["startFileName"] == "cursor"
        with patch.object(
            bucket,
            "_call",
            AsyncMock(
                return_value={
                    "files": [
                        file("coach_full_20261101_030000.dump.age"),
                        file("coach_20261030_030000.dump.age"),
                    ],
                    "nextFileName": None,
                }
            ),
        ):
            with pytest.raises(RuntimeError, match="stale_or_future"):
                await bucket.latest_pair(now=NOW)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:pw@db.example.supabase.co/postgres?sslmode=require",
        TARGET.replace("/coach_restore", "/production"),
        TARGET.replace("sslmode=disable", "sslmode=require"),
        TARGET.replace("127.0.0.1", "localhost"),
        TARGET.replace("127.0.0.1", "ep-test.eu-central-1.aws.neon.tech"),
        TARGET.replace(":55432", ":5432"),
        TARGET.replace("coach_restore:secret", "postgres:secret"),
        TARGET.replace(":secret@", "@"),
        TARGET + "&sslmode=disable",
        TARGET + "#fragment",
        TARGET + "&host=db.example.supabase.co",
        TARGET + "&host=",
        TARGET.replace("postgresql:", "postgresql+asyncpg:"),
    ],
)
def test_restore_refuses_every_other_target(url: str) -> None:
    with pytest.raises(RuntimeError, match="target_rejected"):
        backup_drill.validate_target(url)
    backup_drill.validate_target(TARGET)


@pytest.mark.asyncio
async def test_failed_decryption_never_mutates_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKUP_RESTORE_DATABASE_URL", TARGET)
    monkeypatch.setenv("BACKUP_AGE_IDENTITY", "AGE-SECRET-KEY-synthetic")
    monkeypatch.setenv("BACKUP_B2_BUCKET_ID", "bucket")
    item = RemoteArchive("coach_full_20261108_030000.dump.age", "id", 1, "a", "b" * 64)
    with (
        patch.object(BackupBucket, "authorize", AsyncMock()),
        patch.object(BackupBucket, "latest_pair", AsyncMock(return_value=[item])),
        patch.object(BackupBucket, "download", AsyncMock()),
        patch.object(
            backup_drill, "decrypt_archive", AsyncMock(side_effect=RuntimeError("bad key"))
        ),
        patch.object(backup_drill, "prepare_target", AsyncMock()) as prepare,
    ):
        with pytest.raises(RuntimeError, match="bad key"):
            await backup_drill.run_drill()
        prepare.assert_not_awaited()


def run(*, age: timedelta = timedelta(hours=1), **changes: Any) -> dict[str, Any]:
    result = {
        "head_branch": "main",
        "event": "schedule",
        "head_repository": {"full_name": "CraigR973/garmin-coach"},
        "status": "completed",
        "conclusion": "success",
        "created_at": (NOW - age).isoformat(),
        "updated_at": (NOW - age).isoformat(),
        "id": 123,
        "run_number": 1,
    }
    return result | changes


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [run(age=timedelta(days=9))],
        [run(conclusion="failure")],
        [run(head_branch="feat/unreviewed")],
        [run(head_repository={"full_name": "someone/fork"})],
        [run(event="pull_request")],
        [run(status="in_progress")],
        [run(age=timedelta(days=-1))],
    ],
)
def test_unproved_restore_cannot_be_green(runs: list[dict[str, Any]]) -> None:
    with pytest.raises(RuntimeError, match="backup_restore_"):
        proof_counters(runs, now=NOW)


def test_a_new_failure_is_not_hidden_by_an_older_success() -> None:
    assert proof_counters([run()], now=NOW)["verified_run_id"] == 123
    with pytest.raises(RuntimeError, match="latest_run_failed"):
        proof_counters([run(), run(run_number=2, conclusion="failure")], now=NOW)
    # An in-flight run can keep the still-fresh previous proof until it completes.
    assert (
        proof_counters([run(), run(run_number=2, status="in_progress")], now=NOW)["verified_run_id"]
        == 123
    )


@pytest.mark.asyncio
async def test_real_postgres_archive_encrypt_restore_both_kinds(
    db_engine: Any, tmp_path: Path, age_keys: tuple[Path, str], cluster_directories: list[Path]
) -> None:
    """Synthetic PostgreSQL data, with real pg_dump/age/pg_restore and auth policies.

    Fresh databases only. Never borrow or drop an existing restore database.
    """
    import importlib.util
    import uuid

    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    source_name = "coach_backup_" + uuid.uuid4().hex[:12]
    created: list[str] = []
    source_url = url.set(database=source_name).render_as_string(hide_password=False)

    def sql(target: str, statement: str) -> bytes:
        env = os.environ.copy()
        env["PGPASSWORD"] = backup._pg_password(target) or ""
        result = subprocess.run(
            [
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
                "--dbname",
                backup._pg_dsn(target),
                "-c",
                statement,
            ],
            env=env,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout

    try:
        async with db_engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for name in [source_name]:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
        sql(
            source_url,
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
                CREATE ROLE authenticated NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
                CREATE ROLE anon NOLOGIN;
              END IF;
            END $$;
            CREATE SCHEMA auth;
            CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'SELECT NULL::uuid';
            CREATE SCHEMA coach;
            CREATE TABLE coach.alembic_version(version_num text);
            INSERT INTO coach.alembic_version VALUES ('045');
            CREATE TABLE coach.profiles(id uuid PRIMARY KEY, name text);
            INSERT INTO coach.profiles VALUES ('00000000-0000-0000-0000-000000000001','Synthetic');
            ALTER TABLE coach.profiles ENABLE ROW LEVEL SECURITY;
            CREATE POLICY own_profile ON coach.profiles TO authenticated USING (auth.uid()=id);
            CREATE TABLE coach.analyses(id int PRIMARY KEY, user_id uuid REFERENCES coach.profiles,
                                        context_packet jsonb);
            INSERT INTO coach.analyses VALUES (1,'00000000-0000-0000-0000-000000000001',
                                              '{"synthetic": true}');
            CREATE TABLE coach.activity_timeseries(id int);
            INSERT INTO coach.activity_timeseries VALUES(1);
            CREATE TABLE coach.sleep(id int); INSERT INTO coach.sleep VALUES(2);
            CREATE TABLE coach.daily_metrics(id int); INSERT INTO coach.daily_metrics VALUES(3);
        """,
        )
        for index in range(20):
            sql(source_url, f"CREATE TABLE coach.synthetic_{index}(id int)")
        # The real function-grant migration removes inherited PUBLIC access too.
        sql(
            source_url,
            """
            CREATE FUNCTION public.rls_auto_enable() RETURNS event_trigger
            LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN RETURN; END $$;
            GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO anon, authenticated;
        """,
        )
        migration = (
            Path(__file__).resolve().parents[3]
            / "migrations/versions/045_revoke_public_event_trigger_execute.py"
        )
        spec = importlib.util.spec_from_file_location("revoke045", migration)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        statements: list[str] = []
        with patch.object(module.op, "execute", statements.append):
            module.upgrade()
        for statement in statements:
            sql(source_url, statement)
        assert (
            sql(
                source_url,
                "SELECT has_function_privilege('anon','public.rls_auto_enable()','EXECUTE'),"
                "has_function_privilege('authenticated','public.rls_auto_enable()','EXECUTE'),"
                "has_function_privilege(current_user,'public.rls_auto_enable()','EXECUTE')",
            ).strip()
            == b"f|f|t"
        )

        key, recipient = age_keys
        volume = tmp_path / "retained"
        full = await backup.create_backup(str(volume), source_url, recipient=recipient, full=True)
        nightly = await backup.create_backup(str(volume), source_url, recipient=recipient)
        assert all(p.name.endswith(".dump.age") for p in volume.iterdir())
        async with backup_drill.disposable_target() as restore_url:
            backup_drill.validate_target(restore_url)
            version = (
                int((await backup_drill._psql(restore_url, "SHOW server_version_num")).strip())
                // 10000
            )
            if expected := os.environ.get("EXPECTED_RESTORE_POSTGRES_MAJOR"):
                assert version == int(expected)
            assert await backup_drill._psql(restore_url, "SHOW listen_addresses") == b"127.0.0.1\n"
            assert (
                await backup_drill._psql(
                    restore_url,
                    "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user",
                )
                == b"f|f|f|f\n"
            )
            # A poisoned archive must not be able to read the runner's key files
            # or execute a shell as the PostgreSQL OS user.
            for forbidden_sql in (
                "SELECT pg_read_file('PG_VERSION')",
                "COPY (SELECT 1) TO PROGRAM 'true'",
            ):
                with pytest.raises(RuntimeError, match="backup_restore_sql_failed"):
                    await backup_drill._psql(restore_url, forbidden_sql)
            await backup_drill.prepare_target(restore_url)
            for info in (full, nightly):
                plain = tmp_path / info.filename.removesuffix(".age")
                await decrypt_archive(volume / info.filename, plain, key)
                counts = await backup_drill.restore_plain_archive(
                    restore_url, plain, full=info.full
                )
                assert counts["profiles"] == 1 and counts["analyses"] == 1
                assert counts["weekly_rows"] == (2 if info.full else 0)
                assert (
                    sql(restore_url, "SELECT context_packet FROM coach.analyses").strip()
                    == b'{"synthetic": true}'
                )
                assert (
                    sql(restore_url, "SELECT count(*) FROM coach.activity_timeseries").strip()
                    == b"0"
                )
        assert len(cluster_directories) == 1 and not cluster_directories[0].exists()

    finally:
        # Engine clients created by the validator have already been disposed.
        async with db_engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for name in reversed(created):
                await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.mark.asyncio
async def test_export_failure_is_not_reported_as_backup_success() -> None:
    from src import scheduler
    from src.services.backup import BackupInfo
    from src.services.job_runs import JobStatus

    class Sunday(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return NOW

    info = BackupInfo("coach_full_20261108_030000.dump.age", 100, NOW, full=True)
    with (
        patch.object(scheduler, "datetime", Sunday),
        patch.object(scheduler, "create_backup", AsyncMock(return_value=info)),
        patch.object(
            scheduler, "export_backup_pair", AsyncMock(side_effect=RuntimeError("upload_failed"))
        ),
        patch.object(scheduler, "AsyncSessionLocal") as sessions,
    ):
        sessions.return_value.__aenter__.return_value.commit = AsyncMock()
        sessions.return_value.__aenter__.return_value.add = MagicMock()
        result = await scheduler.run_scheduled_backup()
    assert result.status == JobStatus.failed
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_watchdog_requires_real_proof_within_eight_days(db_conn: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.models.operations import JobRun
    from src.services.job_ledger_freshness import collect_watchdog_report

    now = NOW.replace(tzinfo=None)
    async with AsyncSession(bind=db_conn, join_transaction_mode="create_savepoint") as session:
        from sqlalchemy import delete

        await session.execute(delete(JobRun).where(JobRun.job_name == "backup-drill"))
        row = JobRun(
            job_name="backup-drill",
            status="succeeded",
            counters={},
            scheduled_window_start_utc=now - timedelta(hours=1),
            scheduled_window_end_utc=now,
            started_at_utc=now - timedelta(minutes=1),
            finished_at_utc=now,
        )
        session.add(row)
        await session.flush()
        assert (
            "backup_restore_unproved"
            in (await collect_watchdog_report(session, now_utc=NOW)).problems
        )
        row.counters = {"proof_started_epoch": int(NOW.timestamp()) - 8 * 86400}
        await session.flush()
        assert (
            "backup_restore_unproved"
            not in (await collect_watchdog_report(session, now_utc=NOW)).problems
        )
        row.counters = {"proof_started_epoch": int(NOW.timestamp()) - 8 * 86400 - 1}
        await session.flush()
        assert (
            "backup_restore_unproved"
            in (await collect_watchdog_report(session, now_utc=NOW)).problems
        )


@pytest.mark.asyncio
async def test_restore_refuses_existing_foreign_tables_before_bootstrap() -> None:
    with patch.object(
        backup_drill, "_psql", AsyncMock(side_effect=[b"coach_restore\n", b"1\n"])
    ) as sql:
        with pytest.raises(RuntimeError, match="has_other_tables"):
            await backup_drill.prepare_target(TARGET)
    assert sql.await_count == 2
    assert all("CREATE" not in c.args[1] and "DROP" not in c.args[1] for c in sql.await_args_list)


def test_restore_cannot_inherit_a_libpq_redirect_or_leak_its_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("BACKUP_AGE_IDENTITY", "private-identity")
    env = backup_drill._libpq_environment(TARGET)
    assert env["PGPASSWORD"] == "secret"
    assert not ({"PGHOSTADDR", "PGSERVICE", "BACKUP_AGE_IDENTITY"} & env.keys())
    dsn = backup_drill._target_dsn(TARGET)
    assert "secret" not in dsn
    params = parse_qs(urlsplit(dsn).query)
    assert params == {"sslmode": ["disable"]}
    assert urlsplit(dsn).hostname == "127.0.0.1"
    assert urlsplit(dsn).port == 55432


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nightly_date,full_date,newest_full",
    [
        ("20261107", "20261108", True),
        ("20261109", "20261108", False),
    ],
)
async def test_manual_restore_leaves_newest_dated_state_including_on_sunday(
    tmp_path: Path,
    nightly_date: str,
    full_date: str,
    newest_full: bool,
) -> None:
    nightly = tmp_path / f"coach_{nightly_date}_030000.dump"
    full = tmp_path / f"coach_full_{full_date}_030000.dump"
    nightly.write_bytes(b"synthetic")
    full.write_bytes(b"synthetic")
    calls: list[bool] = []

    async def restore(
        directory: str, info: backup.BackupInfo, url: str
    ) -> backup.BackupRestoreResult:
        calls.append(info.full)
        return backup.BackupRestoreResult(info.filename, 26, "045", 1, 1, 0, full=info.full)

    with patch.object(backup, "_restore_one", restore):
        results = await backup.restore_latest_backup(
            str(tmp_path), "postgresql://source@prod/app", "postgresql://restore@disposable/drill"
        )
    assert calls == [not newest_full, newest_full]
    assert results[-1].full == newest_full


@pytest.mark.asyncio
async def test_disposable_database_is_removed_after_restore_failure(
    tmp_path: Path, cluster_directories: list[Path]
) -> None:
    bad_archive = tmp_path / "coach_full_20261108_030000.dump"
    bad_archive.write_bytes(b"synthetic corrupt archive")
    with pytest.raises(RuntimeError, match="backup_pg_restore_failed"):
        async with backup_drill.disposable_target() as url:
            await backup_drill.prepare_target(url)
            await backup_drill._psql(
                url, "CREATE SCHEMA coach; CREATE TABLE coach.synthetic(id int)"
            )
            await backup_drill.restore_plain_archive(url, bad_archive, full=True)
    assert len(cluster_directories) == 1 and not cluster_directories[0].exists()


@pytest.mark.asyncio
async def test_busy_restore_port_never_uses_or_stops_an_existing_server() -> None:
    import socket

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 55432))
        listener.listen()
        with pytest.raises(RuntimeError, match="cluster_command_failed"):
            async with backup_drill.disposable_target():
                pytest.fail("must not connect to a pre-existing listener")
        assert listener.getsockname() == ("127.0.0.1", 55432)


@pytest.mark.asyncio
async def test_drill_ignores_any_old_external_restore_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACKUP_RESTORE_DATABASE_URL", "postgresql://private@production/real")
    # A missing identity fails before touching a database or the network; an old
    # Neon/production URL never participates in target selection.
    monkeypatch.delenv("BACKUP_AGE_IDENTITY", raising=False)
    with pytest.raises(RuntimeError, match="backup_age_identity_unset"):
        await backup_drill.run_drill()
