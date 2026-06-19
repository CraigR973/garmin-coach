#!/usr/bin/env python3
"""M1 backfill: materialise the Steele Spreadsheet league and populate
multi-league identity columns on existing profiles.

Idempotent. Default is --dry-run; pass --apply to commit.

USAGE
  PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api \
    /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
    scripts/backfill_multi_league.py --sidecar emails.json [--apply]

ENV
  DATABASE_URL   asyncpg URL (e.g. postgresql+asyncpg://user:pw@host/db)

SIDECAR FORMAT
  A JSON map keyed by profile id (UUID string):

      {
        "<profile_id>": {
          "email": "alice@example.com",
          "first_name": "Alice",
          "last_name": "Wong"
        }
      }

  Any subset of the three fields may be supplied. Missing fields fall back
  to a derived value:
    * email      -> "pending+<slug(display_name)>@steele.invalid"
    * first_name -> split from display_name (first token)
    * last_name  -> split from display_name (remainder) or "" if single token

  Craig's row (display_name = 'Craig') is the operator's profile and is
  marked email_verified_at = NOW() automatically.

SAFETY
  * Aborts before committing if the Steele league privacy is not 'private'.
  * Aborts if migration 011 has not been applied.
  * Default mode is --dry-run (no COMMIT). --apply commits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

STEELE_SLUG = "steele-spreadsheet"
STEELE_NAME = "The Steele Spreadsheet"
STEELE_DESCRIPTION = "The original."
OPERATOR_DISPLAY_NAME = "Craig"


@dataclass
class SidecarEntry:
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass
class BackfillSummary:
    league_created: bool = False
    league_id: str = ""
    profiles_total: int = 0
    profiles_updated: int = 0
    memberships_created: int = 0
    memberships_existing: int = 0
    admin_membership_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _slugify(text_in: str) -> str:
    """Slug a display name to a safe email local-part placeholder."""
    slug = re.sub(r"[^a-z0-9]+", "-", text_in.lower()).strip("-")
    return slug or "player"


def _derive_first_last(display_name: str) -> tuple[str, str]:
    parts = display_name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _load_sidecar(path: Path | None) -> dict[str, SidecarEntry]:
    if path is None:
        return {}
    with path.open() as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Sidecar must be a JSON object, got {type(raw).__name__}")
    out: dict[str, SidecarEntry] = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            raise ValueError(f"Sidecar entry for {k!r} must be an object")
        out[str(k)] = SidecarEntry(
            email=v.get("email"),
            first_name=v.get("first_name"),
            last_name=v.get("last_name"),
        )
    return out


async def _assert_migration_applied(conn: AsyncConnection) -> None:
    revision = (
        await conn.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one_or_none()
    if revision is None:
        raise RuntimeError("alembic_version is empty; run `alembic upgrade head` first")
    # Lexical compare is fine here because revisions are numeric strings 001..NNN.
    if revision < "011":
        raise RuntimeError(
            f"Migration 011 not applied (current revision: {revision}). "
            "Run `alembic upgrade head` first."
        )


async def _upsert_steele_league(
    conn: AsyncConnection, operator_id: str, summary: BackfillSummary
) -> str:
    existing = (
        await conn.execute(
            text("SELECT id FROM leagues WHERE slug = :s"),
            {"s": STEELE_SLUG},
        )
    ).scalar_one_or_none()
    if existing is not None:
        summary.league_id = str(existing)
        return summary.league_id
    new_id = (
        await conn.execute(
            text(
                """
                INSERT INTO leagues
                    (id, slug, name, description, privacy, max_members, created_by, created_at)
                VALUES
                    (gen_random_uuid(), :slug, :name, :desc,
                     CAST(:privacy AS league_privacy), 15, :cb,
                     '2026-05-09 00:00:00')
                RETURNING id
                """
            ),
            {
                "slug": STEELE_SLUG,
                "name": STEELE_NAME,
                "desc": STEELE_DESCRIPTION,
                "privacy": "private",
                "cb": operator_id,
            },
        )
    ).scalar_one()
    summary.league_created = True
    summary.league_id = str(new_id)
    return summary.league_id


async def _assert_privacy_private(conn: AsyncConnection) -> None:
    privacy = (
        await conn.execute(
            text("SELECT privacy FROM leagues WHERE slug = :s"),
            {"s": STEELE_SLUG},
        )
    ).scalar_one_or_none()
    if privacy != "private":
        raise RuntimeError(
            f"FATAL: Steele league privacy is {privacy!r}, expected 'private'. Aborting."
        )


async def _find_operator_id(conn: AsyncConnection) -> str:
    pid = (
        await conn.execute(
            text(
                "SELECT id FROM profiles "
                "WHERE display_name = :n AND deleted_at IS NULL "
                "LIMIT 1"
            ),
            {"n": OPERATOR_DISPLAY_NAME},
        )
    ).scalar_one_or_none()
    if pid is None:
        raise RuntimeError(
            f"No active profile with display_name = {OPERATOR_DISPLAY_NAME!r}. "
            "Cannot determine league creator."
        )
    return str(pid)


async def _backfill_profiles_and_memberships(
    conn: AsyncConnection,
    league_id: str,
    sidecar: dict[str, SidecarEntry],
    summary: BackfillSummary,
) -> None:
    rows = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, display_name, role, email, first_name, last_name,
                       email_verified_at, site_role
                FROM profiles
                WHERE deleted_at IS NULL
                ORDER BY display_name
                """
                )
            )
        )
        .mappings()
        .all()
    )

    summary.profiles_total = len(rows)
    seen_emails: set[str] = set()

    for row in rows:
        pid = str(row["id"])
        display_name = row["display_name"]
        entry = sidecar.get(pid, SidecarEntry())

        first_default, last_default = _derive_first_last(display_name)
        first_name = entry.first_name or row["first_name"] or first_default
        last_name = (
            entry.last_name
            if entry.last_name is not None
            else (row["last_name"] if row["last_name"] is not None else last_default)
        )

        email = (
            entry.email
            or row["email"]
            or f"pending+{_slugify(display_name)}@steele.invalid"
        )
        email_lower = email.lower()
        if email_lower in seen_emails:
            summary.warnings.append(
                f"Duplicate email after backfill: {email} (profile {pid}). "
                "Update the sidecar to disambiguate."
            )
        seen_emails.add(email_lower)

        # Derived state for the operator only.
        is_operator = display_name == OPERATOR_DISPLAY_NAME
        site_role = "superadmin" if row["role"] == "admin" else "user"
        if is_operator and site_role != "superadmin":
            summary.warnings.append(
                f"Operator {display_name!r} did not have role='admin' on profiles; "
                "still mapping to site_role='superadmin'."
            )
            site_role = "superadmin"

        await conn.execute(
            text(
                """
                UPDATE profiles SET
                    email = :email,
                    first_name = :first_name,
                    last_name = :last_name,
                    email_verified_at = CASE
                        WHEN :is_operator AND email_verified_at IS NULL THEN NOW()
                        ELSE email_verified_at
                    END,
                    site_role = CAST(:site_role AS site_role)
                WHERE id = :pid
                """
            ),
            {
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "is_operator": is_operator,
                "site_role": site_role,
                "pid": pid,
            },
        )
        summary.profiles_updated += 1

        # Membership upsert: restore soft-deleted rows; insert fresh otherwise.
        membership_role = "admin" if row["role"] == "admin" else "player"
        existing_membership = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT id, deleted_at FROM league_memberships
                    WHERE league_id = :lid AND player_id = :pid
                    """
                    ),
                    {"lid": league_id, "pid": pid},
                )
            )
            .mappings()
            .one_or_none()
        )

        if existing_membership is None:
            await conn.execute(
                text(
                    """
                    INSERT INTO league_memberships
                        (id, league_id, player_id, role, joined_at)
                    VALUES
                        (gen_random_uuid(), :lid, :pid,
                         CAST(:role AS league_member_role), NOW())
                    """
                ),
                {"lid": league_id, "pid": pid, "role": membership_role},
            )
            summary.memberships_created += 1
        else:
            await conn.execute(
                text(
                    """
                    UPDATE league_memberships SET
                        role = CAST(:role AS league_member_role),
                        deleted_at = NULL
                    WHERE id = :mid
                    """
                ),
                {"mid": existing_membership["id"], "role": membership_role},
            )
            summary.memberships_existing += 1

        if membership_role == "admin":
            summary.admin_membership_count += 1


async def run_backfill(
    conn: AsyncConnection, sidecar: dict[str, SidecarEntry]
) -> BackfillSummary:
    """Driver — assumes `conn` is inside a transaction the caller will commit/rollback."""
    summary = BackfillSummary()
    await _assert_migration_applied(conn)
    operator_id = await _find_operator_id(conn)
    league_id = await _upsert_steele_league(conn, operator_id, summary)
    await _backfill_profiles_and_memberships(conn, league_id, sidecar, summary)
    await _assert_privacy_private(conn)
    if summary.admin_membership_count == 0:
        raise RuntimeError(
            "FATAL: backfill produced zero admin memberships on the Steele league. Aborting."
        )
    return summary


def _print_summary(s: BackfillSummary, *, applied: bool) -> None:
    mode = "APPLIED" if applied else "DRY RUN"
    print(f"=== Multi-league backfill — {mode} ===")
    print(f"  Steele league id      : {s.league_id}")
    print(f"  League created        : {s.league_created}")
    print(f"  Profiles updated      : {s.profiles_updated} / {s.profiles_total}")
    print(f"  Memberships created   : {s.memberships_created}")
    print(f"  Memberships restored  : {s.memberships_existing}")
    print(f"  Admin memberships     : {s.admin_membership_count}")
    if s.warnings:
        print("  WARNINGS:")
        for w in s.warnings:
            print(f"    - {w}")


async def _amain(args: argparse.Namespace) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    sidecar = _load_sidecar(Path(args.sidecar) if args.sidecar else None)
    engine = create_async_engine(url, future=True)
    try:
        async with engine.connect() as conn:
            summary = await run_backfill(conn, sidecar)
            if args.apply:
                await conn.commit()
            else:
                await conn.rollback()
            _print_summary(summary, applied=args.apply)
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sidecar",
        help="Path to a JSON sidecar with per-profile email/first/last overrides.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the backfill (default is --dry-run).",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
