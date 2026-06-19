"""Tests for R1 backend hardening: input validation, secrets, security headers."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.config import Settings
from src.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# R1.1 — Settings rejects placeholder JWT secrets in production
# ---------------------------------------------------------------------------


def test_settings_rejects_placeholder_access_secret() -> None:
    with pytest.raises(ValidationError, match="jwt_access_secret is a placeholder"):
        Settings(
            jwt_access_secret="change-me-access",
            jwt_refresh_secret="real-refresh-secret-that-is-long-enough",
            environment="production",
        )


def test_settings_rejects_placeholder_refresh_secret() -> None:
    with pytest.raises(ValidationError, match="jwt_refresh_secret is a placeholder"):
        Settings(
            jwt_access_secret="real-access-secret-that-is-long-enough",
            jwt_refresh_secret="change-me-refresh",
            environment="production",
        )


def test_settings_allows_placeholder_in_development() -> None:
    s = Settings(
        jwt_access_secret="change-me-access",
        jwt_refresh_secret="change-me-refresh",
        environment="development",
    )
    assert s.environment == "development"


def test_settings_rejects_empty_vapid_key_in_production() -> None:
    with pytest.raises(ValidationError, match="vapid_private_key is empty"):
        Settings(
            jwt_access_secret="real-access",
            jwt_refresh_secret="real-refresh",
            vapid_private_key="",
            supabase_service_key="real-key",
            football_data_api_key="real-key",
            environment="production",
        )


# ---------------------------------------------------------------------------
# R1.4 — Auth schema validation: bad PIN rejected with 422
# ---------------------------------------------------------------------------


async def test_login_rejects_non_numeric_pin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "pin": "abcd"}
    )
    assert resp.status_code == 422


async def test_login_rejects_pin_too_short(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "pin": "123"}
    )
    assert resp.status_code == 422


async def test_login_rejects_pin_too_long(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "pin": "12345"}
    )
    assert resp.status_code == 422


async def test_signup_rejects_pin_too_long(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "pin": "12345",
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 422


async def test_login_requires_email(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={"pin": "1234"})
    assert resp.status_code == 422


async def test_login_requires_pin(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": "alice@example.com"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R1.4 — Prediction schema: negative / out-of-range scores rejected
# ---------------------------------------------------------------------------


def test_prediction_rejects_negative_score() -> None:
    from src.routers.predictions import PredictionRequest

    with pytest.raises(ValidationError):
        PredictionRequest(predicted_home=-1, predicted_away=0)


def test_prediction_rejects_score_above_max() -> None:
    from src.routers.predictions import PredictionRequest

    with pytest.raises(ValidationError):
        PredictionRequest(predicted_home=21, predicted_away=0)


def test_prediction_accepts_valid_scores() -> None:
    from src.routers.predictions import PredictionRequest

    r = PredictionRequest(predicted_home=3, predicted_away=0)
    assert r.predicted_home == 3


# ---------------------------------------------------------------------------
# R1.3 — Security headers present on every response
# ---------------------------------------------------------------------------


async def test_security_headers_present(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


async def test_hsts_absent_in_development(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    # app runs with environment=development in tests — HSTS must be omitted
    assert "strict-transport-security" not in resp.headers


async def test_hsts_present_in_production(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    import src.middleware as mw

    monkeypatch.setattr(mw.settings, "environment", "production")
    resp = await client.get("/api/v1/health")
    assert resp.headers.get("strict-transport-security") == "max-age=63072000; includeSubDomains"


# ---------------------------------------------------------------------------
# R8.3 — Settings rejects localhost/empty frontend_origin and empty database_url
# ---------------------------------------------------------------------------

_PROD_BASE = dict(
    jwt_access_secret="real-access-secret",
    jwt_refresh_secret="real-refresh-secret",
    vapid_private_key="real-vapid",
    supabase_service_key="real-supabase",
    football_data_api_key="real-football",
    database_url="postgresql+asyncpg://prod:prod@host/db",
    environment="production",
)


def test_settings_rejects_localhost_frontend_origin_in_production() -> None:
    with pytest.raises(ValidationError, match="frontend_origin must not be empty or localhost"):
        Settings(**{**_PROD_BASE, "frontend_origin": "http://localhost:5173"})


def test_settings_rejects_empty_frontend_origin_in_production() -> None:
    with pytest.raises(ValidationError, match="frontend_origin must not be empty or localhost"):
        Settings(**{**_PROD_BASE, "frontend_origin": ""})


def test_settings_rejects_empty_database_url_in_production() -> None:
    with pytest.raises(ValidationError, match="database_url is empty"):
        Settings(
            **{
                **_PROD_BASE,
                "database_url": "",
                "frontend_origin": "https://wc2026-prod.vercel.app",
            }
        )


def test_settings_accepts_valid_prod_origin() -> None:
    s = Settings(**{**_PROD_BASE, "frontend_origin": "https://wc2026-prod.vercel.app"})
    assert s.frontend_origin == "https://wc2026-prod.vercel.app"
