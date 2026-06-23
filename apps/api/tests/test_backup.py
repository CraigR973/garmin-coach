"""Tests for backup helpers — the password is kept out of the pg_dump argv (P3-6)."""

from __future__ import annotations

from src.services.backup import _pg_dsn, _pg_password


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
