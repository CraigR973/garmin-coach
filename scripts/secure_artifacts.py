"""Helpers for operator-created secret artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def write_secret_file(path: Path, content: str) -> None:
    """Write a secret file atomically with owner-only permissions."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)

    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise SystemExit(
                f"Refusing to overwrite {path}: permissions must be 0600 or stricter"
            )

    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
