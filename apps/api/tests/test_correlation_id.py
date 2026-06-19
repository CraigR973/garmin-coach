import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_correlation_id_generated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert "x-correlation-id" in response.headers
    assert UUID4_RE.match(response.headers["x-correlation-id"])


async def test_correlation_id_passthrough(client: AsyncClient) -> None:
    cid = "my-custom-correlation-id"
    response = await client.get("/api/v1/health", headers={"X-Correlation-ID": cid})
    assert response.headers["x-correlation-id"] == cid
