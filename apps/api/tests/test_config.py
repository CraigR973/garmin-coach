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


# ---------------------------------------------------------------------------
# Batch 233 — the Anthropic generation settings that reach the payload verbatim
# ---------------------------------------------------------------------------


def test_thinking_mode_and_effort_default_to_the_shipped_values() -> None:
    settings = _build_settings()
    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.anthropic_thinking_mode == "adaptive"
    # ``high`` is Sonnet 5's own default, set explicitly so the value is legible
    # in config rather than inherited from the provider and liable to move.
    assert settings.anthropic_effort == "high"


def test_an_unknown_thinking_mode_is_rejected_at_construction() -> None:
    """Catch it here, not as a 400 on Mark's first brief after a deploy."""
    with pytest.raises(ValueError, match="anthropic_thinking_mode"):
        _build_settings(anthropic_thinking_mode="enabled")


def test_an_unknown_effort_level_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="anthropic_effort"):
        _build_settings(anthropic_effort="highest")


def test_every_documented_effort_level_is_accepted() -> None:
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert _build_settings(anthropic_effort=level).anthropic_effort == level


def test_thinking_can_be_disabled_as_the_rollback_lever() -> None:
    assert _build_settings(anthropic_thinking_mode="disabled").anthropic_thinking_mode == "disabled"


def test_the_ceiling_clears_the_measured_thinking_demand() -> None:
    """Batch 233.1: ``max_tokens`` caps thinking and text together.

    A real morning brief on Sonnet 5 at ``high`` effort measured 16,157 output
    tokens — 14,610 of them thinking. The ceiling has to clear that with room,
    and the pre-233 value of 4096 did not clear it at all.
    """
    settings = _build_settings()
    assert settings.anthropic_max_tokens >= 24576
    assert settings.anthropic_max_tokens > 16157


def test_the_chat_and_learning_ceilings_are_settings_not_constants() -> None:
    """Batch 233.2: these were hardcoded at 1024 and 1800, below the new floor.

    Adaptive thinking shares the budget with the reply, so a 1024-token chat
    ceiling truncates routinely — and no ``ANTHROPIC_MAX_TOKENS`` change could
    reach it, because the value was a module constant.
    """
    settings = _build_settings(anthropic_chat_max_tokens=8000, anthropic_learning_max_tokens=9000)
    assert settings.anthropic_chat_max_tokens == 8000
    assert settings.anthropic_learning_max_tokens == 9000

    defaults = _build_settings()
    assert defaults.anthropic_chat_max_tokens > 1024
    assert defaults.anthropic_learning_max_tokens > 1800
