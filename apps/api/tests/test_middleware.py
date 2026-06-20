"""Tests for middleware: security headers and correlation ID coverage."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import Environment
from src.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Security headers (non-HTTPS headers always present regardless of environment)
# ---------------------------------------------------------------------------


async def test_x_content_type_options(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_x_frame_options(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers.get("x-frame-options") == "DENY"


async def test_referrer_policy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


async def test_content_security_policy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert "frame-ancestors 'none'" in response.headers.get("content-security-policy", "")


async def test_permissions_policy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    policy = response.headers.get("permissions-policy", "")
    assert "camera=()" in policy
    assert "microphone=()" in policy
    assert "geolocation=()" in policy


# ---------------------------------------------------------------------------
# HSTS: only emitted outside development
# ---------------------------------------------------------------------------


async def test_hsts_absent_in_development(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.middleware as mw

    monkeypatch.setattr(mw.settings, "environment", Environment.development)
    response = await client.get("/api/v1/health")
    assert "strict-transport-security" not in response.headers


async def test_hsts_present_in_production(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.middleware as mw

    monkeypatch.setattr(mw.settings, "environment", Environment.production)
    response = await client.get("/api/v1/health")
    assert "strict-transport-security" in response.headers
    assert "max-age=63072000" in response.headers["strict-transport-security"]
