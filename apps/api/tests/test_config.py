"""Tests for Settings: production fail-closed validation of required secrets."""

from __future__ import annotations

import pytest

from src.config import Environment, Settings, docs_urls


def _build_settings(**overrides: object) -> Settings:
    """Construct Settings from a valid production baseline, overriding per test.

    Every field the prod validator inspects is supplied as an init kwarg so the
    result is deterministic regardless of the ambient .env / environment.
    """
    params: dict[str, object] = {
        "environment": Environment.production,
        "jwt_access_secret": "a" * 32,
        "jwt_refresh_secret": "b" * 32,
        "vapid_private_key": "vapid-private",
        "supabase_service_key": "supabase-service",
        "anthropic_api_key": "sk-ant-test",
        "database_url": "postgresql+asyncpg://u:p@host:5432/db",
        "frontend_origin": "https://coach.example.com",
    }
    params.update(overrides)
    return Settings(**params)  # type: ignore[arg-type]


def test_valid_production_settings_construct() -> None:
    settings = _build_settings()
    assert settings.environment == Environment.production


def test_production_rejects_missing_anthropic_api_key() -> None:
    with pytest.raises(ValueError, match="anthropic_api_key is empty"):
        _build_settings(anthropic_api_key="")


def test_development_allows_missing_anthropic_api_key() -> None:
    settings = _build_settings(environment=Environment.development, anthropic_api_key="")
    assert settings.anthropic_api_key == ""


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="jwt_access_secret must be at least"):
        _build_settings(jwt_access_secret="short")


def test_production_rejects_identical_jwt_secrets() -> None:
    with pytest.raises(ValueError, match="must be different"):
        _build_settings(jwt_access_secret="x" * 40, jwt_refresh_secret="x" * 40)


def test_development_allows_weak_jwt_secrets() -> None:
    # The validator is fully skipped in development, so a short/identical pair is fine.
    settings = _build_settings(
        environment=Environment.development,
        jwt_access_secret="dev",
        jwt_refresh_secret="dev",
    )
    assert settings.jwt_access_secret == "dev"


def test_docs_urls_disabled_in_production() -> None:
    assert docs_urls(Environment.production) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_docs_urls_enabled_outside_production() -> None:
    urls = docs_urls(Environment.development)
    assert urls["docs_url"] == "/api/docs"
    assert urls["redoc_url"] == "/api/redoc"
    assert urls["openapi_url"] == "/api/openapi.json"
