"""Client for the football-data.org v4 API (used for match result sync)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import StrEnum
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_WC_COMPETITION_ID = 2000
_BASE_URL = "https://api.football-data.org/v4"
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds


# ---------------------------------------------------------------------------
# Pydantic models for football-data.org v4 responses
# ---------------------------------------------------------------------------


class FDMatchStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    TIMED = "TIMED"
    IN_PLAY = "IN_PLAY"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


class FDScoreLine(BaseModel):
    home: int | None = None
    away: int | None = None


class FDScore(BaseModel):
    winner: str | None = None  # "HOME_TEAM", "AWAY_TEAM", "DRAW", or null
    duration: str = "REGULAR"  # "REGULAR", "EXTRA_TIME", "PENALTY_SHOOTOUT"
    fullTime: FDScoreLine = Field(default_factory=FDScoreLine)
    halfTime: FDScoreLine | None = None
    extraTime: FDScoreLine | None = None
    penalties: FDScoreLine | None = None


class FDTeam(BaseModel):
    id: int | None = None
    name: str | None = None
    tla: str | None = None  # 3-letter country code


class FDMatch(BaseModel):
    id: int
    utcDate: datetime
    status: FDMatchStatus
    stage: str
    group: str | None = None
    venue: str | None = None
    lastUpdated: datetime | None = None
    homeTeam: FDTeam
    awayTeam: FDTeam
    score: FDScore


class FDMatchesResponse(BaseModel):
    count: int = 0
    matches: list[FDMatch]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FootballDataError(Exception):
    """Base error for football-data.org client failures."""


class FootballDataRateLimitError(FootballDataError):
    """Raised after all retries are exhausted on 429 responses."""


class FootballDataServerError(FootballDataError):
    """Raised when the API returns a 5xx response."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FootballDataClient:
    """Async client for the football-data.org v4 API.

    Pass a custom ``client`` in tests to inject a mock transport.
    """

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=30.0,
        )
        # Always inject the auth header, even when a custom client is supplied for testing.
        self._client.headers["X-Auth-Token"] = api_key

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FootballDataClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def get_competition_matches(
        self, competition_id: int = _WC_COMPETITION_ID
    ) -> FDMatchesResponse:
        """Fetch all matches for the given competition (defaults to WC 2026)."""
        data = await self._get(f"/competitions/{competition_id}/matches")
        return FDMatchesResponse.model_validate(data)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.get(path, params=params)
            except httpx.RequestError as exc:
                # Connection / timeout / DNS errors. Retry with backoff, then
                # surface as FootballDataError so the sync loop's
                # consecutive-failure counter + admin alert engage — a raw
                # httpx error would bypass them (it is not a FootballDataError).
                if attempt == _MAX_RETRIES:
                    raise FootballDataError(
                        f"Network error after {_MAX_RETRIES} retries: {exc!r}"
                    ) from exc
                log.warning(
                    "football-data network error",
                    attempt=attempt,
                    error=repr(exc),
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code == 429:
                if attempt == _MAX_RETRIES:
                    raise FootballDataRateLimitError(
                        f"Rate limit exceeded after {_MAX_RETRIES} retries"
                    )
                retry_after = float(response.headers.get("Retry-After", str(backoff)))
                log.warning(
                    "football-data rate limited",
                    attempt=attempt,
                    retry_after=retry_after,
                )
                await asyncio.sleep(retry_after)
                backoff *= 2
                continue

            if response.status_code >= 500:
                # Transient upstream failure. Retry with exponential backoff
                # instead of aborting the whole sync cycle on the first 5xx.
                if attempt == _MAX_RETRIES:
                    raise FootballDataServerError(
                        f"Server error {response.status_code} after "
                        f"{_MAX_RETRIES} retries: {response.text[:200]}"
                    )
                log.warning(
                    "football-data server error",
                    attempt=attempt,
                    status_code=response.status_code,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Non-retryable client error (e.g. 403 bad key, 404). Wrap so it
                # too feeds the failure counter/alert rather than escaping raw.
                raise FootballDataError(
                    f"Unexpected status {response.status_code}: {response.text[:200]}"
                ) from exc
            data: dict[str, Any] = response.json()
            return data

        raise FootballDataError("Exhausted retries")
