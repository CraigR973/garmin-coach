"""Off-Railway encrypted archive restore drill. No application/production credentials.

Run only with the approved Neon disposable target and the B2 read-only key. Errors
print fixed codes only: PostgreSQL errors can contain COPY rows and thus health text.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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
    # Production is Supabase. No alias, pooler, socket, arbitrary host or DB can be
    # supplied here, even with a mistakenly copied production credential.
    if (
        target.scheme != "postgresql"
        or not target.username
        or not target.password
        or not (target.hostname or "").endswith(".eu-central-1.aws.neon.tech")
        or "-pooler." in (target.hostname or "")
        or target.path != "/coach_restore"
        or target.port not in (None, 5432)
        or parse_qs(target.query, keep_blank_values=True).get("sslmode")
        not in (["require"], ["verify-full"])
        or set(parse_qs(target.query, keep_blank_values=True)) - {"sslmode", "channel_binding"}
        or target.fragment
    ):
        raise RuntimeError("backup_restore_target_rejected")


def _libpq_environment(url: str) -> dict[str, str]:
    # Do not let ambient hostaddr/service settings redirect the approved target.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "BACKUP_"))}
    env["PGPASSWORD"] = _pg_password(url) or ""
    return env


def _target_dsn(url: str) -> str:
    parsed = urlsplit(_pg_dsn(url))
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "sslmode" in query:
        # libpq `require` encrypts but does not verify hostname. Authenticate the
        # exact approved Neon hostname with the runner's system CA bundle.
        query["sslmode"] = ["verify-full"]
        query["sslrootcert"] = [
            ssl.get_default_verify_paths().cafile or "/etc/ssl/certs/ca-certificates.crt"
        ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment)
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
    url = os.environ.get("BACKUP_RESTORE_DATABASE_URL", "")
    validate_target(url)
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
        await prepare_target(url)
        try:
            counts = []
            for index, item in enumerate(pair):
                counts.append(
                    await restore_plain_archive(
                        url, directory / item.filename.removesuffix(".age"), full=index == 0
                    )
                )
        finally:
            # Approved disposable target only; an incomplete cleanup fails the run.
            await _psql(url, "DROP SCHEMA IF EXISTS coach CASCADE")
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
