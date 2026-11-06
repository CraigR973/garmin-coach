"""age subprocess boundary. Identities belong to the off-platform runner only."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path


def validate_recipient(recipient: str) -> None:
    # Native X25519 recipients only: no argument/file/SSH/plugin interpretation.
    if not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", recipient):
        raise RuntimeError("backup_age_recipient_invalid_or_unset")


async def _age(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "age", *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError("backup_age_failed")


async def encrypt_archive(source: Path, destination: Path, recipient: str) -> None:
    validate_recipient(recipient)
    try:
        await _age("--encrypt", "--recipient", recipient, "--output", str(destination), str(source))
        destination.chmod(0o600)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


async def decrypt_archive(source: Path, destination: Path, identity: Path) -> None:
    try:
        await _age(
            "--decrypt", "--identity", str(identity), "--output", str(destination), str(source)
        )
        destination.chmod(0o600)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
