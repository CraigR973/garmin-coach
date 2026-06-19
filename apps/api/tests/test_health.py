from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# R8.1 — /health returns sha field


async def test_health_ok_has_sha(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "sha" in data


async def test_health_sha_from_env(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.routers.health as h

    monkeypatch.setattr(h.settings, "railway_git_commit_sha", "abc1234")
    response = await client.get("/api/v1/health")
    assert response.json()["sha"] == "abc1234"


async def test_health_sha_unknown_when_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.routers.health as h

    monkeypatch.setattr(h.settings, "railway_git_commit_sha", None)
    response = await client.get("/api/v1/health")
    assert response.json()["sha"] == "unknown"


# R8.2 — /health/ready returns 503 when DB is unreachable


async def test_ready_db_ok(client: AsyncClient) -> None:
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    with patch("src.routers.health.AsyncSessionLocal", return_value=mock_session):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["db"] == "ok"


async def test_ready_db_down_returns_503(client: AsyncClient) -> None:
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.routers.health.AsyncSessionLocal", return_value=mock_session):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["db"] == "unreachable"
