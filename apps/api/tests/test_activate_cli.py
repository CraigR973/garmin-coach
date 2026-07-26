"""Operator activation and lost-device recovery tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from src.activate import mint_activation_link
from src.auth import hash_token
from src.models.profile import Profile
from src.models.refresh_token import RefreshToken


class _SessionContext:
    def __init__(self, session: MagicMock) -> None:
        self.session = session

    async def __aenter__(self) -> MagicMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_recovery_link_revokes_devices_and_mints_single_use_code(monkeypatch) -> None:
    profile = Profile(display_name="Mark", timezone="Europe/London")
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile
    session.execute.side_effect = [profile_result, MagicMock(), MagicMock()]
    monkeypatch.setattr(
        "src.activate.AsyncSessionLocal",
        lambda: _SessionContext(session),
    )

    url = await mint_activation_link("Mark", revoke_existing_devices=True)

    statements = [call.args[0] for call in session.execute.await_args_list]
    update_params = [
        statement.compile().params
        for statement in statements
        if getattr(statement, "is_update", False)
    ]
    assert any("device" in params.values() for params in update_params)
    assert any("activation" in params.values() for params in update_params)

    record = session.add.call_args.args[0]
    assert isinstance(record, RefreshToken)
    assert record.purpose == "activation"
    code = parse_qs(urlparse(url).query)["code"][0]
    assert record.token_hash == hash_token(code)
    session.commit.assert_awaited_once()
