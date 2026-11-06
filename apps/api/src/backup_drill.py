"""Off-Railway encrypted archive restore drill. No application/production credentials.

Creates its own disposable local cluster; no restore URL is accepted. Errors
print fixed codes only: PostgreSQL errors can contain COPY rows and thus health text.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from src.services.backup import (
    _archive_wire_bytes,
    _pg_dsn,
    _pg_password,
    _validate_restored_backup,
)
from src.services.backup_crypto import decrypt_archive
from src.services.backup_offsite import BackupBucket


def validate_target(url: str) -> None:
    target = urlsplit(url)
    # Literal loopback only: no DNS, production host, pooler, socket or redirect.
    if (
        target.scheme != "postgresql"
        or target.username != "coach_restore"
        or not target.password
        or target.hostname != "127.0.0.1"
        or target.path != "/coach_restore"
        or target.port != 55432
        or parse_qs(target.query, keep_blank_values=True) != {"sslmode": ["disable"]}
        or target.fragment
    ):
        raise RuntimeError("backup_restore_target_rejected")


def _libpq_environment(url: str) -> dict[str, str]:
    # Do not let ambient hostaddr/service settings redirect the approved target.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "BACKUP_"))}
    env["PGPASSWORD"] = _pg_password(url) or ""
    return env


def _target_dsn(url: str) -> str:
    validate_target(url)
    return _pg_dsn(url)


async def _cluster_command(url: str, *args: str, input_sql: bytes | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=_libpq_environment(url),
        stdin=asyncio.subprocess.PIPE if input_sql is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.communicate(input_sql), timeout=120)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError("backup_restore_cluster_command_failed")


@asynccontextmanager
async def disposable_target() -> AsyncIterator[str]:
    """Own the fresh cluster's full lifecycle, including failure cleanup.

    Its random password lasts for this process only. A busy port fails startup;
    it never falls back to another server. No external restore secret is read.
    """
    with tempfile.TemporaryDirectory(prefix="coach-restore-db-") as temporary:
        directory = Path(temporary)
        data = directory / "data"
        password = secrets.token_urlsafe(32)
        admin_password = secrets.token_urlsafe(32)
        password_file = directory / "password"
        password_file.touch(mode=0o600)
        password_file.write_text(admin_password)
        url = f"postgresql://coach_restore:{password}@127.0.0.1:55432/coach_restore?sslmode=disable"
        admin_url = (
            f"postgresql://coach_restore_admin:{admin_password}@127.0.0.1:55432/postgres"
            "?sslmode=disable"
        )
        await _cluster_command(
            admin_url,
            "initdb",
            "-D",
            str(data),
            "--username=coach_restore_admin",
            "--pwfile=" + str(password_file),
            "--auth-host=scram-sha-256",
            "--auth-local=reject",
            "--encoding=UTF8",
            "--no-locale",
        )
        try:
            await _cluster_command(
                admin_url,
                "pg_ctl",
                "-D",
                str(data),
                "-l",
                str(directory / "server.log"),
                "-o",
                "-h 127.0.0.1 -p 55432 -k ''",
                "-w",
                "start",
            )
            await _cluster_command(
                admin_url,
                "psql",
                "--no-password",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "--dbname",
                _pg_dsn(admin_url),
                # Generated URL-safe tokens have no SQL quote/backslash characters.
                # stdin keeps even these one-run passwords out of process argv.
                input_sql=(
                    f"CREATE ROLE coach_restore LOGIN PASSWORD '{password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;"
                    "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;"
                    "CREATE ROLE service_role NOLOGIN;"
                ).encode(),
            )
            await _cluster_command(
                admin_url,
                "createdb",
                "--no-password",
                "--host=127.0.0.1",
                "--port=55432",
                "--username=coach_restore_admin",
                "--owner=coach_restore",
                "coach_restore",
            )
            yield url
        finally:
            # Never stop a pre-existing server: this PID belongs to our new data dir.
            if (data / "postmaster.pid").exists():
                await _cluster_command(
                    admin_url,
                    "pg_ctl",
                    "-D",
                    str(data),
                    "-m",
                    "immediate",
                    "-w",
                    "stop",
                )


async def _psql(url: str, sql: str) -> bytes:
    validate_target(url)
    env = _libpq_environment(url)
    proc = await asyncio.create_subprocess_exec(
        "psql",
        "--no-password",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-At",
        "--dbname",
        _target_dsn(url),
        "--command",
        sql,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError("backup_restore_sql_failed")
    return output


async def prepare_target(url: str) -> None:
    validate_target(url)
    # Independent server-side database identity check before the first DROP.
    identity = await _psql(url, "SELECT current_database()")
    if identity.strip() != b"coach_restore":
        raise RuntimeError("backup_restore_database_identity_mismatch")
    # Do not wipe a database that has acquired another application's tables.
    foreign_tables = await _psql(
        url,
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema NOT IN ('coach','information_schema','pg_catalog')
          AND table_type='BASE TABLE'
    """,
    )
    if foreign_tables.strip() != b"0":
        raise RuntimeError("backup_restore_target_has_other_tables")
    # The coach dump has Supabase RLS policies. In this isolated drill only,
    # no-login roles and a NULL uid keep their dependencies intact and deny rows.
    await _psql(
        url,
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
            CREATE ROLE anon NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
            CREATE ROLE authenticated NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN
            CREATE ROLE service_role NOLOGIN;
          END IF;
        END $$;
        CREATE SCHEMA IF NOT EXISTS auth;
        CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
        LANGUAGE sql STABLE AS 'SELECT NULL::uuid';
        REVOKE ALL ON SCHEMA auth FROM PUBLIC;
    """,
    )


async def restore_plain_archive(url: str, archive: Path, *, full: bool) -> dict[str, int]:
    await _psql(url, "DROP SCHEMA IF EXISTS coach CASCADE")
    validate_target(url)
    env = _libpq_environment(url)
    proc = await asyncio.create_subprocess_exec(
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        "--no-password",
        "--dbname",
        _target_dsn(url),
        str(archive),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=900)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError("backup_pg_restore_failed")
    result = await _validate_restored_backup(url, archive.name, full=full)
    return {
        "tables": result.restored_tables,
        "profiles": result.profile_rows,
        "analyses": result.analysis_rows,
        "weekly_rows": result.weekly_only_rows,
    }


async def run_drill() -> dict[str, int]:
    identity = os.environ.get("BACKUP_AGE_IDENTITY", "")
    if not identity.startswith("#") and not identity.startswith("AGE-SECRET-KEY-"):
        raise RuntimeError("backup_age_identity_unset")
    # An identity is never put in argv, logs, an artifact, or a retained directory.
    with tempfile.TemporaryDirectory(prefix="coach-restore-") as temporary:
        directory = Path(temporary)
        keyfile = directory / "identity"
        keyfile.touch(mode=0o600)
        keyfile.write_text(identity)
        async with httpx.AsyncClient(timeout=300) as client:
            bucket = BackupBucket(client, os.environ.get("BACKUP_B2_BUCKET_ID", ""))
            await bucket.authorize(
                os.environ.get("BACKUP_B2_READ_KEY_ID", ""),
                os.environ.get("BACKUP_B2_READ_APPLICATION_KEY", ""),
                writer=False,
            )
            pair = await bucket.latest_pair()
            # Decrypt/integrity-check both BEFORE any target mutation.
            for item in pair:
                cipher = directory / item.filename
                await bucket.download(item, cipher)
                plain = directory / item.filename.removesuffix(".age")
                await decrypt_archive(cipher, plain, keyfile)
                if await _archive_wire_bytes(plain) is None:
                    raise RuntimeError("backup_downloaded_archive_integrity_failed")
        async with disposable_target() as url:
            await prepare_target(url)
            counts = []
            for index, item in enumerate(pair):
                counts.append(
                    await restore_plain_archive(
                        url, directory / item.filename.removesuffix(".age"), full=index == 0
                    )
                )
            # Exiting the context stops the server and removes its entire data dir,
            # even when bootstrap/restore/validation fails. Nothing persists to Neon.
    return {"archives_restored": len(counts), "tables": min(c["tables"] for c in counts)}


def main() -> None:
    try:
        result = asyncio.run(run_drill())
    except BaseException:
        # Do not print the exception or a traceback (may expose COPY data/credentials).
        print("FAIL offsite restore drill; no proof recorded", flush=True)
        raise SystemExit(1) from None
    print("PASS offsite restore drill " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
