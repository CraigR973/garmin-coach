"""M3 — League management API tests.

Coverage:
- Create / list / discover / get / update / delete round-trips
- Privacy-tier behavioural matrix:
    private → 403 on join
    public_request → creates join request
    public_open → instant membership
- Privacy transitions with side effects:
    → private: cancels pending join requests
    public_request → public_open: auto-approves pending requests
- Join/leave semantics including rejoin (soft-deleted restore)
- Last-admin protection on demote and remove
- max_members ceiling on join and approve
- Member promote/demote/remove
- Display-name override
- Per-league invite CRUD
- Per-league join-request approve/reject
- Auth checks: non-member gets 403 on member-only endpoints, non-admin gets 403 on admin endpoints
- Deprecation header on legacy POST /admin/invites
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.league import League, LeaguePrivacy
from src.models.league_join_request import JoinRequestStatus, LeagueJoinRequest
from src.models.league_membership import LeagueMemberRole, LeagueMembership
from src.models.profile import PlayerRole, Profile, SiteRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_profile(
    *,
    display_name: str = "Alice",
    role: PlayerRole = PlayerRole.player,
    site_role: SiteRole | None = None,
    deleted: bool = False,
) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = display_name
    p.role = role
    p.site_role = site_role
    p.deleted_at = _now() if deleted else None
    p.is_active = True
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    return p


def _make_league(
    *,
    privacy: LeaguePrivacy = LeaguePrivacy.public_open,
    max_members: int = 15,
    name: str = "Test League",
    deleted: bool = False,
) -> MagicMock:
    lg = MagicMock(spec=League)
    lg.id = uuid.uuid4()
    lg.slug = "test-league"
    lg.name = name
    lg.description = None
    lg.privacy = privacy
    lg.max_members = max_members
    lg.created_by = uuid.uuid4()
    lg.created_at = _now()
    lg.updated_at = _now()
    lg.join_code = "ABCDE2"
    lg.deleted_at = _now() if deleted else None
    return lg


def _make_membership(
    league_id: uuid.UUID,
    player_id: uuid.UUID,
    *,
    role: LeagueMemberRole = LeagueMemberRole.player,
    deleted: bool = False,
) -> MagicMock:
    m = MagicMock(spec=LeagueMembership)
    m.id = uuid.uuid4()
    m.league_id = league_id
    m.player_id = player_id
    m.role = role
    m.display_name_override = None
    m.joined_at = _now()
    m.updated_at = _now()
    m.deleted_at = _now() if deleted else None
    return m


def _make_join_request(
    league_id: uuid.UUID,
    player_id: uuid.UUID,
    *,
    status: JoinRequestStatus = JoinRequestStatus.pending,
) -> MagicMock:
    r = MagicMock(spec=LeagueJoinRequest)
    r.id = uuid.uuid4()
    r.league_id = league_id
    r.player_id = player_id
    r.status = status
    r.requested_at = _now()
    r.decided_at = None
    r.decided_by = None
    r.decision_note = None
    r.updated_at = _now()
    return r


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _rows(items: list) -> MagicMock:
    r = MagicMock()
    r.all.return_value = items
    return r


def _stub_db(side_effects: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=side_effects)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    return mock_db


@asynccontextmanager
async def _override(player: MagicMock, mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_player] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_player, None)


BASE = "http://test"


# ===========================================================================
# POST /api/v1/leagues — create
# ===========================================================================


@pytest.mark.asyncio
async def test_create_league_returns_201() -> None:
    player = _make_profile()
    league = _make_league()
    league.slug = "my-league"
    league.name = "My League"

    mock_db = _stub_db(
        [
            # _unique_slug: no collision
            _scalar(None),
            # _active_member_count after commit + refresh (LeagueResponse)
            _scalar_one(1),
        ]
    )
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                "/api/v1/leagues",
                json={"name": "My League", "privacy": "public_open"},
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My League"
    assert body["privacy"] == "public_open"


@pytest.mark.asyncio
async def test_create_league_defaults_to_private() -> None:
    player = _make_profile()
    mock_db = _stub_db([_scalar(None), _scalar_one(1)])
    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues", json={"name": "Secret Club"})
    assert resp.status_code == 201
    assert resp.json()["privacy"] == "private"


# ===========================================================================
# GET /api/v1/leagues/mine
# ===========================================================================


@pytest.mark.asyncio
async def test_list_my_leagues_returns_all_memberships() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id, role=LeagueMemberRole.admin)

    mock_db = _stub_db(
        [
            # The join query
            _rows([(league, membership, 1)]),
            # _active_member_count for the one league
            _scalar_one(1),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/mine")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["my_role"] == "admin"


# ===========================================================================
# GET /api/v1/leagues/discover
# ===========================================================================


@pytest.mark.asyncio
async def test_discover_returns_public_leagues() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_open)

    mock_db = _stub_db(
        [
            # total count query
            _scalar_one(1),
            # rows query
            _rows([(league, 3)]),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/discover")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["leagues"]) == 1
    assert body["leagues"][0]["member_count"] == 3


# ===========================================================================
# GET /api/v1/leagues/{slug}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_league_as_member_returns_member_list() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id)

    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (is member check)
            _scalar(membership),
            # _active_member_count
            _scalar_one(2),
            # member list query
            _rows([(membership, player)]),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league")

    assert resp.status_code == 200
    body = resp.json()
    assert body["member_count"] == 2
    assert isinstance(body["members"], list)


@pytest.mark.asyncio
async def test_get_league_as_non_member_hides_member_list() -> None:
    player = _make_profile()
    league = _make_league()

    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (not a member)
            _scalar(None),
            # _active_member_count
            _scalar_one(5),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league")

    assert resp.status_code == 200
    assert resp.json()["members"] is None


@pytest.mark.asyncio
async def test_get_league_404_when_not_found() -> None:
    player = _make_profile()
    mock_db = _stub_db([_scalar(None)])

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/nonexistent")

    assert resp.status_code == 404


# ===========================================================================
# PATCH /api/v1/leagues/{slug} — update
# ===========================================================================


def _admin_league_db(player: MagicMock, league: MagicMock, extra: list | None = None) -> AsyncMock:
    """Stub DB that passes require_league_admin then executes ``extra`` side effects."""
    base = [
        # _resolve_league
        _scalar(league),
        # _resolve_active_membership (admin check)
        _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
    ]
    return _stub_db(base + (extra or []))


@pytest.mark.asyncio
async def test_update_league_name() -> None:
    player = _make_profile()
    league = _make_league(name="Old Name")
    extra = [
        # _active_member_count for max_members validation not called (no max_members change)
        # _active_member_count for response
        _scalar_one(2),
    ]
    mock_db = _admin_league_db(player, league, extra)

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch(
                "/api/v1/leagues/test-league",
                json={"name": "New Name"},
            )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_league_max_members_below_current_count_422() -> None:
    player = _make_profile()
    league = _make_league()
    league.max_members = 10
    extra = [
        # _active_member_count — currently 8 members
        _scalar_one(8),
    ]
    mock_db = _admin_league_db(player, league, extra)

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch(
                "/api/v1/leagues/test-league",
                json={"max_members": 5},
            )

    assert resp.status_code == 422


# ===========================================================================
# DELETE /api/v1/leagues/{slug}
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_league_requires_name_confirmation() -> None:
    import json as _json

    player = _make_profile()
    league = _make_league(name="My League")
    mock_db = _admin_league_db(player, league)

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.request(
                "DELETE",
                "/api/v1/leagues/test-league",
                content=_json.dumps({"confirm_name": "Wrong Name"}),
                headers={"Content-Type": "application/json"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_league_succeeds_with_correct_name() -> None:
    import json as _json

    player = _make_profile()
    league = _make_league(name="My League")
    mock_db = _admin_league_db(player, league)

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.request(
                "DELETE",
                "/api/v1/leagues/test-league",
                content=_json.dumps({"confirm_name": "My League"}),
                headers={"Content-Type": "application/json"},
            )

    assert resp.status_code == 204


# ===========================================================================
# POST /api/v1/leagues/{slug}/join — privacy matrix
# ===========================================================================


@pytest.mark.asyncio
async def test_join_private_league_is_403() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.private)
    mock_db = _stub_db([_scalar(league)])

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues/test-league/join")

    assert resp.status_code == 403
    assert "PRIVATE_LEAGUE" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_join_public_open_creates_membership() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_open)
    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (already member check)
            _scalar(None),
            # _active_member_count
            _scalar_one(3),
            # _upsert_membership: existing soft-deleted lookup
            _scalar(None),
            # notify_member_joined: _admin_players query
            _scalars([]),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues/test-league/join")

    assert resp.status_code == 200
    assert resp.json()["status"] == "joined"


@pytest.mark.asyncio
async def test_join_public_request_creates_join_request() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_request)
    mock_db = _stub_db(
        [
            _scalar(league),
            # not already a member
            _scalar(None),
            # _active_member_count
            _scalar_one(3),
            # no existing pending request
            _scalar(None),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues/test-league/join")

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_join_already_member_is_409() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_open)
    membership = _make_membership(league.id, player.id)
    mock_db = _stub_db(
        [
            _scalar(league),
            # already a member
            _scalar(membership),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues/test-league/join")

    assert resp.status_code == 409
    assert "ALREADY_MEMBER" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_join_full_league_is_409() -> None:
    player = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_open, max_members=5)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(None),  # not already member
            _scalar_one(5),  # at capacity
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post("/api/v1/leagues/test-league/join")

    assert resp.status_code == 409
    assert "LEAGUE_FULL" in resp.json()["detail"]


# ===========================================================================
# DELETE /api/v1/leagues/{slug}/membership — leave
# ===========================================================================


@pytest.mark.asyncio
async def test_leave_league_succeeds() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id, role=LeagueMemberRole.player)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(membership),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete("/api/v1/leagues/test-league/membership")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_last_admin_cannot_leave() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id, role=LeagueMemberRole.admin)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(membership),
            # _active_admin_count → 1
            _scalar_one(1),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete("/api/v1/leagues/test-league/membership")

    assert resp.status_code == 409
    assert "LAST_ADMIN" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_with_co_admin_can_leave() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id, role=LeagueMemberRole.admin)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(membership),
            # two admins
            _scalar_one(2),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete("/api/v1/leagues/test-league/membership")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_leave_non_member_is_404() -> None:
    player = _make_profile()
    league = _make_league()
    mock_db = _stub_db([_scalar(league), _scalar(None)])

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete("/api/v1/leagues/test-league/membership")

    assert resp.status_code == 404


# ===========================================================================
# GET /api/v1/leagues/{slug}/members
# ===========================================================================


@pytest.mark.asyncio
async def test_list_members_requires_membership() -> None:
    player = _make_profile()
    mock_db = _stub_db(
        [
            _scalar(MagicMock(spec=League, deleted_at=None, id=uuid.uuid4())),
            # _resolve_active_membership → None (not a member, not superadmin)
            _scalar(None),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league/members")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_members_returns_members() -> None:
    player = _make_profile(display_name="Alice")
    league = _make_league()
    membership = _make_membership(league.id, player.id)

    mock_db = _stub_db(
        [
            # require_league_member: _resolve_league
            _scalar(league),
            # require_league_member: _resolve_active_membership
            _scalar(membership),
            # list_members query
            _rows([(membership, player)]),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league/members")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Alice"


# ===========================================================================
# POST /api/v1/leagues/{slug}/members/{player_id}/promote
# ===========================================================================


@pytest.mark.asyncio
async def test_promote_member_to_admin() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.player)

    mock_db = _admin_league_db(
        admin,
        league,
        [
            # _resolve_active_membership for target
            _scalar(target_membership),
        ],
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(f"/api/v1/leagues/test-league/members/{target_id}/promote")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_promote_already_admin_is_409() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.admin)

    mock_db = _admin_league_db(admin, league, [_scalar(target_membership)])

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(f"/api/v1/leagues/test-league/members/{target_id}/promote")

    assert resp.status_code == 409


# ===========================================================================
# POST /api/v1/leagues/{slug}/members/{player_id}/demote
# ===========================================================================


@pytest.mark.asyncio
async def test_demote_admin_to_player() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.admin)

    mock_db = _admin_league_db(
        admin,
        league,
        [
            _scalar(target_membership),
            # _active_admin_count → 2
            _scalar_one(2),
        ],
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(f"/api/v1/leagues/test-league/members/{target_id}/demote")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.admin)

    mock_db = _admin_league_db(
        admin,
        league,
        [
            _scalar(target_membership),
            # only 1 admin
            _scalar_one(1),
        ],
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(f"/api/v1/leagues/test-league/members/{target_id}/demote")

    assert resp.status_code == 409
    assert "LAST_ADMIN" in resp.json()["detail"]


# ===========================================================================
# DELETE /api/v1/leagues/{slug}/members/{player_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_remove_player_succeeds() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.player)

    mock_db = _admin_league_db(admin, league, [_scalar(target_membership)])

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete(f"/api/v1/leagues/test-league/members/{target_id}")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_remove_admin_is_409() -> None:
    admin = _make_profile()
    league = _make_league()
    target_id = uuid.uuid4()
    target_membership = _make_membership(league.id, target_id, role=LeagueMemberRole.admin)

    mock_db = _admin_league_db(admin, league, [_scalar(target_membership)])

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete(f"/api/v1/leagues/test-league/members/{target_id}")

    assert resp.status_code == 409


# ===========================================================================
# PUT /api/v1/leagues/{slug}/members/me/display-name
# ===========================================================================


@pytest.mark.asyncio
async def test_set_display_name_override() -> None:
    player = _make_profile()
    league = _make_league()
    membership = _make_membership(league.id, player.id)

    mock_db = _stub_db(
        [
            # require_league_member: _resolve_league
            _scalar(league),
            # require_league_member: _resolve_active_membership
            _scalar(membership),
            # set_my_display_name: _resolve_active_membership
            _scalar(membership),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.put(
                "/api/v1/leagues/test-league/members/me/display-name",
                json={"display_name_override": "Ali"},
            )

    assert resp.status_code == 204


# ===========================================================================
# Per-league invites
# ===========================================================================


def _make_invite_mock(league_id: uuid.UUID, admin_id: uuid.UUID) -> MagicMock:
    from src.models.invite import Invite

    inv = MagicMock(spec=Invite)
    inv.id = uuid.uuid4()
    inv.token = "test_token"
    inv.display_name_hint = None
    inv.created_by = admin_id
    inv.claimed_by = None
    inv.claimed_at = None
    inv.expires_at = None
    inv.is_active = True
    inv.created_at = _now()
    inv.league_id = league_id
    return inv


@pytest.mark.asyncio
async def test_create_league_invite() -> None:
    admin = _make_profile()
    league = _make_league()

    mock_db = _admin_league_db(admin, league)
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                "/api/v1/leagues/test-league/invites",
                json={"expires_in_days": 7},
            )

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_list_league_invites() -> None:
    admin = _make_profile()
    league = _make_league()
    invite = _make_invite_mock(league.id, admin.id)

    mock_db = _admin_league_db(admin, league, [_scalars([invite])])

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league/invites")

    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_revoke_league_invite() -> None:

    admin = _make_profile()
    league = _make_league()
    invite = _make_invite_mock(league.id, admin.id)

    mock_db = _admin_league_db(admin, league, [_scalar(invite)])

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.delete(f"/api/v1/leagues/test-league/invites/{invite.id}")

    assert resp.status_code == 204


# ===========================================================================
# Join requests — list / approve / reject
# ===========================================================================


def _admin_league_with_join_req_db(
    admin: MagicMock, league: MagicMock, join_req: MagicMock, extra: list | None = None
) -> AsyncMock:
    base = [
        # require_league_admin: _resolve_league
        _scalar(league),
        # require_league_admin: _resolve_active_membership
        _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
        # _load_pending_request or list query
    ]
    return _stub_db(base + [_scalar(join_req)] + (extra or []))


@pytest.mark.asyncio
async def test_list_join_requests() -> None:
    admin = _make_profile(display_name="Admin")
    league = _make_league(privacy=LeaguePrivacy.public_request)
    requester = _make_profile(display_name="Bob")
    join_req = _make_join_request(league.id, requester.id)

    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
            # list query
            _rows([(join_req, requester)]),
        ]
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/api/v1/leagues/test-league/join-requests")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Bob"


@pytest.mark.asyncio
async def test_approve_join_request() -> None:
    admin = _make_profile()
    league = _make_league(max_members=15)
    requester_id = uuid.uuid4()
    join_req = _make_join_request(league.id, requester_id)

    mock_db = _admin_league_with_join_req_db(
        admin,
        league,
        join_req,
        [
            # _active_member_count
            _scalar_one(5),
            # _upsert_membership: existing lookup
            _scalar(None),
        ],
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                f"/api/v1/leagues/test-league/join-requests/{join_req.id}/approve",
                json={},
            )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_approve_join_request_full_league_is_409() -> None:
    admin = _make_profile()
    league = _make_league(max_members=5)
    requester_id = uuid.uuid4()
    join_req = _make_join_request(league.id, requester_id)

    mock_db = _admin_league_with_join_req_db(
        admin,
        league,
        join_req,
        [
            # at capacity
            _scalar_one(5),
        ],
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                f"/api/v1/leagues/test-league/join-requests/{join_req.id}/approve",
                json={},
            )

    assert resp.status_code == 409
    assert "LEAGUE_FULL" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reject_join_request() -> None:
    admin = _make_profile()
    league = _make_league()
    requester_id = uuid.uuid4()
    join_req = _make_join_request(league.id, requester_id)

    mock_db = _admin_league_with_join_req_db(admin, league, join_req)

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                f"/api/v1/leagues/test-league/join-requests/{join_req.id}/reject",
                json={"note": "Sorry, full."},
            )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_approve_nonexistent_request_is_404() -> None:
    admin = _make_profile()
    league = _make_league()
    fake_id = uuid.uuid4()

    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
            # _load_pending_request → None
            _scalar(None),
        ]
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                f"/api/v1/leagues/test-league/join-requests/{fake_id}/approve",
                json={},
            )

    assert resp.status_code == 404


# ===========================================================================
# Superadmin bypass
# ===========================================================================


@pytest.mark.asyncio
async def test_superadmin_can_access_league_admin_endpoint() -> None:
    superadmin = _make_profile(site_role=SiteRole.superadmin)
    league = _make_league(name="Some League")
    extra = [_scalar_one(2)]  # _active_member_count for response
    mock_db = _stub_db(
        [
            # require_league_admin: _resolve_league (superadmin skips membership check)
            _scalar(league),
        ]
        + extra
    )

    async with _override(superadmin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch(
                "/api/v1/leagues/test-league",
                json={"name": "Renamed"},
            )

    assert resp.status_code == 200


# ===========================================================================
# Non-admin gets 403 on admin endpoints
# ===========================================================================


@pytest.mark.asyncio
async def test_non_admin_cannot_patch_league() -> None:
    player = _make_profile()
    league = _make_league()
    player_membership = _make_membership(league.id, player.id, role=LeagueMemberRole.player)

    mock_db = _stub_db(
        [
            _scalar(league),
            # membership with player role
            _scalar(player_membership),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch("/api/v1/leagues/test-league", json={"name": "Hack"})

    assert resp.status_code == 403


# ===========================================================================
# Privacy transition: → private cancels pending requests
# ===========================================================================


@pytest.mark.asyncio
async def test_privacy_change_to_private_cancels_join_requests() -> None:
    admin = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_request)
    req1 = _make_join_request(league.id, uuid.uuid4())
    req2 = _make_join_request(league.id, uuid.uuid4())

    # Build a DB mock that handles all the queries in sequence
    mock_db = _stub_db(
        [
            # require_league_admin: _resolve_league
            _scalar(league),
            # require_league_admin: membership check (admin)
            _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
            # _cancel_pending_requests query
            _scalars([req1, req2]),
            # _active_member_count for response
            _scalar_one(3),
        ]
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch(
                "/api/v1/leagues/test-league",
                json={"privacy": "private"},
            )

    assert resp.status_code == 200
    # Both requests should have been marked cancelled
    assert req1.status == JoinRequestStatus.cancelled
    assert req2.status == JoinRequestStatus.cancelled


# ===========================================================================
# Privacy transition: public_request → public_open auto-approves requests
# ===========================================================================


@pytest.mark.asyncio
async def test_privacy_change_public_request_to_open_approves_requests() -> None:
    admin = _make_profile()
    league = _make_league(privacy=LeaguePrivacy.public_request, max_members=15)
    req1 = _make_join_request(league.id, uuid.uuid4())

    mock_db = _stub_db(
        [
            # require_league_admin: _resolve_league
            _scalar(league),
            # require_league_admin: membership check
            _scalar(MagicMock(spec=LeagueMembership, role=LeagueMemberRole.admin, deleted_at=None)),
            # _active_member_count (under max_members check before auto-approve)
            _scalar_one(3),
            # _auto_approve_pending_requests: pending requests
            _scalars([req1]),
            # _upsert_membership: existing lookup for req1.player_id
            _scalar(None),
            # _active_member_count for response
            _scalar_one(4),
        ]
    )

    async with _override(admin, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.patch(
                "/api/v1/leagues/test-league",
                json={"privacy": "public_open"},
            )

    assert resp.status_code == 200
    assert req1.status == JoinRequestStatus.approved


# ===========================================================================
# POST /admin/invites — removed in M8 (per-league invites only)
# ===========================================================================


@pytest.mark.asyncio
async def test_legacy_create_invite_removed() -> None:
    """The global admin POST /invites route was removed in M8; use per-league invites."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.post("/api/v1/admin/invites", json={"display_name_hint": "Craig"})
    assert resp.status_code in (404, 405)
