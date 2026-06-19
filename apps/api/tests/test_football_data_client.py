"""Unit tests for the football-data.org API client.

All tests use httpx.AsyncBaseTransport subclassing so no live network
calls are made and no DATABASE_URL is required.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.services.football_data import (
    FDMatchStatus,
    FootballDataClient,
    FootballDataError,
    FootballDataRateLimitError,
    FootballDataServerError,
)

# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------

_FINISHED_MATCH = {
    "id": 419665,
    "utcDate": "2026-06-11T18:00:00Z",
    "status": "FINISHED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_A",
    "lastUpdated": "2026-06-11T20:15:00Z",
    "homeTeam": {"id": 9, "name": "Mexico", "tla": "MEX"},
    "awayTeam": {"id": 12, "name": "USA", "tla": "USA"},
    "score": {
        "winner": "HOME_TEAM",
        "duration": "REGULAR",
        "fullTime": {"home": 2, "away": 1},
        "halfTime": {"home": 1, "away": 0},
    },
}

_IN_PLAY_MATCH = {
    "id": 419666,
    "utcDate": "2026-06-11T21:00:00Z",
    "status": "IN_PLAY",
    "stage": "GROUP_STAGE",
    "group": "GROUP_B",
    "lastUpdated": "2026-06-11T21:45:00Z",
    "homeTeam": {"id": 3, "name": "Germany", "tla": "GER"},
    "awayTeam": {"id": 7, "name": "France", "tla": "FRA"},
    "score": {
        "winner": None,
        "duration": "REGULAR",
        "fullTime": {"home": None, "away": None},
        "halfTime": {"home": None, "away": None},
    },
}

_SCHEDULED_MATCH = {
    "id": 419667,
    "utcDate": "2026-06-15T18:00:00Z",  # shifted kickoff
    "status": "TIMED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_C",
    "lastUpdated": "2026-05-01T00:00:00Z",
    "homeTeam": {"id": 5, "name": "Brazil", "tla": "BRA"},
    "awayTeam": {"id": 6, "name": "Argentina", "tla": "ARG"},
    "score": {
        "winner": None,
        "duration": "REGULAR",
        "fullTime": {"home": None, "away": None},
        "halfTime": None,
    },
}

_POSTPONED_MATCH = {
    "id": 419668,
    "utcDate": "2026-06-20T15:00:00Z",
    "status": "POSTPONED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_D",
    "lastUpdated": "2026-06-10T00:00:00Z",
    "homeTeam": {"id": 1, "name": "England", "tla": "ENG"},
    "awayTeam": {"id": 2, "name": "Spain", "tla": "ESP"},
    "score": {
        "winner": None,
        "duration": "REGULAR",
        "fullTime": {"home": None, "away": None},
        "halfTime": None,
    },
}

_CANCELLED_MATCH = {
    "id": 419669,
    "utcDate": "2026-06-25T18:00:00Z",
    "status": "CANCELLED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_E",
    "lastUpdated": "2026-06-05T00:00:00Z",
    "homeTeam": {"id": 11, "name": "Portugal", "tla": "POR"},
    "awayTeam": {"id": 14, "name": "Italy", "tla": "ITA"},
    "score": {
        "winner": None,
        "duration": "REGULAR",
        "fullTime": {"home": None, "away": None},
        "halfTime": None,
    },
}

_MATCHES_RESPONSE = {
    "count": 5,
    "matches": [
        _FINISHED_MATCH,
        _IN_PLAY_MATCH,
        _SCHEDULED_MATCH,
        _POSTPONED_MATCH,
        _CANCELLED_MATCH,
    ],
}


class _MockTransport(httpx.AsyncBaseTransport):
    """Replays queued httpx.Response objects in order.

    A queued ``Exception`` is raised instead of returned, so transport-level
    network failures (httpx.RequestError subclasses) can be simulated.
    """

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._iter: Iterator[httpx.Response | Exception] = iter(responses)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        item = next(self._iter)
        if isinstance(item, Exception):
            raise item
        return item


def _make_client(responses: list[httpx.Response | Exception]) -> FootballDataClient:
    transport = _MockTransport(responses)
    inner = httpx.AsyncClient(
        base_url="https://api.football-data.org/v4",
        transport=transport,
    )
    return FootballDataClient(api_key="test-key", client=inner)


def _ok(body: object) -> httpx.Response:
    return httpx.Response(200, json=body)


def _rate_limit(retry_after: str = "1") -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": retry_after}, text="Too Many Requests")


def _server_error(code: int = 500) -> httpx.Response:
    return httpx.Response(code, text="Internal Server Error")


# ---------------------------------------------------------------------------
# Status mapping tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finished_match_parses_correctly() -> None:
    client = _make_client([_ok(_MATCHES_RESPONSE)])
    result = await client.get_competition_matches()

    finished = next(m for m in result.matches if m.status == FDMatchStatus.FINISHED)
    assert finished.id == 419665
    assert finished.score.fullTime.home == 2
    assert finished.score.fullTime.away == 1
    assert finished.score.winner == "HOME_TEAM"
    assert finished.score.duration == "REGULAR"
    assert finished.homeTeam.tla == "MEX"
    assert finished.awayTeam.tla == "USA"


@pytest.mark.asyncio
async def test_in_play_match_parses_correctly() -> None:
    client = _make_client([_ok(_MATCHES_RESPONSE)])
    result = await client.get_competition_matches()

    in_play = next(m for m in result.matches if m.status == FDMatchStatus.IN_PLAY)
    assert in_play.id == 419666
    assert in_play.score.fullTime.home is None
    assert in_play.score.fullTime.away is None
    assert in_play.score.winner is None


@pytest.mark.asyncio
async def test_scheduled_kickoff_change_captures_utc_date() -> None:
    """TIMED/SCHEDULED matches expose their (possibly updated) utcDate."""
    client = _make_client([_ok(_MATCHES_RESPONSE)])
    result = await client.get_competition_matches()

    scheduled = next(m for m in result.matches if m.id == 419667)
    assert scheduled.status == FDMatchStatus.TIMED
    assert scheduled.utcDate.year == 2026
    assert scheduled.utcDate.month == 6
    assert scheduled.utcDate.day == 15


@pytest.mark.asyncio
async def test_postponed_match_maps_correctly() -> None:
    client = _make_client([_ok(_MATCHES_RESPONSE)])
    result = await client.get_competition_matches()

    postponed = next(m for m in result.matches if m.status == FDMatchStatus.POSTPONED)
    assert postponed.id == 419668
    assert postponed.score.fullTime.home is None


@pytest.mark.asyncio
async def test_cancelled_match_maps_correctly() -> None:
    client = _make_client([_ok(_MATCHES_RESPONSE)])
    result = await client.get_competition_matches()

    cancelled = next(m for m in result.matches if m.status == FDMatchStatus.CANCELLED)
    assert cancelled.id == 419669
    assert cancelled.homeTeam.tla == "POR"


@pytest.mark.asyncio
async def test_penalty_shootout_score_fields_parsed() -> None:
    """Duration PENALTY_SHOOTOUT and penalty scores parse without error."""
    penalty_match = {
        **_FINISHED_MATCH,
        "id": 419670,
        "score": {
            "winner": "AWAY_TEAM",
            "duration": "PENALTY_SHOOTOUT",
            "fullTime": {"home": 1, "away": 1},
            "halfTime": {"home": 0, "away": 0},
            "extraTime": {"home": 0, "away": 0},
            "penalties": {"home": 3, "away": 5},
        },
    }
    response_body = {"count": 1, "matches": [penalty_match]}
    client = _make_client([_ok(response_body)])
    result = await client.get_competition_matches()

    m = result.matches[0]
    assert m.score.duration == "PENALTY_SHOOTOUT"
    assert m.score.winner == "AWAY_TEAM"
    assert m.score.penalties is not None
    assert m.score.penalties.home == 3
    assert m.score.penalties.away == 5


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_retries_and_raises_after_max_retries() -> None:
    """Three 429s exhaust retries and raise FootballDataRateLimitError."""
    # _MAX_RETRIES=3 → attempts 0,1,2,3 → 4 responses needed
    responses = [_rate_limit("0"), _rate_limit("0"), _rate_limit("0"), _rate_limit("0")]
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(FootballDataRateLimitError):
            await client.get_competition_matches()


@pytest.mark.asyncio
async def test_429_retries_then_succeeds() -> None:
    """Two 429s followed by a 200 should return successfully."""
    responses = [_rate_limit("0"), _rate_limit("0"), _ok({"count": 0, "matches": []})]
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client.get_competition_matches()

    assert result.count == 0
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_500_retries_then_raises_server_error() -> None:
    """5xx is retried (not aborted on the first one); 4 in a row exhaust retries."""
    responses: list[httpx.Response | Exception] = [_server_error(500)] * 4
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(FootballDataServerError) as exc_info:
            await client.get_competition_matches()

    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_503_retries_then_raises_server_error() -> None:
    responses: list[httpx.Response | Exception] = [_server_error(503)] * 4
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(FootballDataServerError) as exc_info:
            await client.get_competition_matches()

    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds() -> None:
    """A couple of 5xx responses followed by a 200 should recover, not abort."""
    responses: list[httpx.Response | Exception] = [
        _server_error(500),
        _server_error(502),
        _ok({"count": 0, "matches": []}),
    ]
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client.get_competition_matches()

    assert result.count == 0
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_network_error_retries_then_wraps_as_football_data_error() -> None:
    """httpx network errors are retried, then surfaced as FootballDataError.

    A raw httpx error would bypass the sync loop's consecutive-failure counter
    and admin alert (it is not a FootballDataError); wrapping fixes that.
    """
    err = httpx.ConnectError("connection refused")
    responses: list[httpx.Response | Exception] = [err, err, err, err]
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(FootballDataError) as exc_info:
            await client.get_competition_matches()

    # Wrapped — not a raw httpx error escaping the client.
    assert not isinstance(exc_info.value, httpx.HTTPError)
    assert "Network error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_network_error_retries_then_succeeds() -> None:
    responses: list[httpx.Response | Exception] = [
        httpx.ConnectError("boom"),
        _ok({"count": 0, "matches": []}),
    ]
    client = _make_client(responses)

    with patch("src.services.football_data.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client.get_competition_matches()

    assert result.count == 0
    assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_4xx_wrapped_as_football_data_error() -> None:
    """A non-retryable client error (e.g. 403 bad key) surfaces as FootballDataError."""
    client = _make_client([httpx.Response(403, text="Forbidden")])

    with pytest.raises(FootballDataError):
        await client.get_competition_matches()


@pytest.mark.asyncio
async def test_get_competition_matches_requests_correct_competition() -> None:
    """Default competition ID is 2000 (FIFA World Cup)."""
    captured_paths: list[str] = []

    class _CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_paths.append(request.url.path)
            return httpx.Response(200, json={"count": 0, "matches": []})

    inner = httpx.AsyncClient(
        base_url="https://api.football-data.org/v4",
        transport=_CapturingTransport(),
    )
    client = FootballDataClient(api_key="test-key", client=inner)
    await client.get_competition_matches()

    assert captured_paths == ["/v4/competitions/2000/matches"]


@pytest.mark.asyncio
async def test_custom_competition_id_used_in_request() -> None:
    captured_paths: list[str] = []

    class _CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_paths.append(request.url.path)
            return httpx.Response(200, json={"count": 0, "matches": []})

    inner = httpx.AsyncClient(
        base_url="https://api.football-data.org/v4",
        transport=_CapturingTransport(),
    )
    client = FootballDataClient(api_key="test-key", client=inner)
    await client.get_competition_matches(competition_id=9999)

    assert "/v4/competitions/9999/matches" in captured_paths[0]


@pytest.mark.asyncio
async def test_auth_token_sent_in_header() -> None:
    captured_headers: list[dict[str, str]] = []

    class _HeaderCapture(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json={"count": 0, "matches": []})

    inner = httpx.AsyncClient(
        base_url="https://api.football-data.org/v4",
        transport=_HeaderCapture(),
    )
    client = FootballDataClient(api_key="my-secret-key", client=inner)
    await client.get_competition_matches()

    assert captured_headers[0].get("x-auth-token") == "my-secret-key"
