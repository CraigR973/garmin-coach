"""Batch 348: Hive's sign-on page in either quote style, and a refresh that cannot text.

On 2026-10-20 Hive's sign-on page moved from minified, double-quoted assignments
to one single-quoted assignment per line, and pyhiveapi 0.5.16 could no longer
read it: 377 polls failed in a row before Mark noticed his bedroom temperature
had stopped. Both fixtures are the real page — the June copy from the Wayback
Machine and the live copy of 24 Oct — so the reader is tested against what Hive
actually served, not against a regex's idea of it.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.services.hive_cognito import (
    HIVE_COGNITO_CLIENT_ID,
    HIVE_SSO_URL,
    KNOWN_HIVE_COGNITO_APP,
    HiveAuthError,
    HiveCognitoApp,
    HiveTokenRejectedError,
    decode_hive_token_blob,
    encode_hive_token_blob,
    parse_hive_sso_page,
    read_hive_cognito_app,
    refresh_hive_id_token,
    token_blob_app,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hive"
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text()


# --- the sign-on page -------------------------------------------------------------


def test_the_page_hive_serves_since_20_october_is_read() -> None:
    page = _page("sso_page_2026-10-24.html")
    assert "window.HiveSSOPoolId = 'eu-west-1_SamNfoWtf'" in page

    assert parse_hive_sso_page(page) == KNOWN_HIVE_COGNITO_APP


def test_the_june_page_is_still_read() -> None:
    page = _page("sso_page_2026-06-08.html")
    assert 'window.HiveSSOPoolId="eu-west-1_SamNfoWtf",' in page

    assert parse_hive_sso_page(page) == KNOWN_HIVE_COGNITO_APP


def test_pyhiveapi_cannot_read_the_new_page() -> None:
    """The failure this batch exists for, reproduced with pyhiveapi's own recipe."""
    from pyquery import PyQuery  # type: ignore[import-untyped, unused-ignore]

    script = PyQuery(_page("sso_page_2026-10-24.html"))("script:first").text()
    with pytest.raises(json.JSONDecodeError, match="char 19"):
        json.loads(
            '{"' + script.replace(",", ', "').replace("=", '":').replace("window.", "") + "}"
        )


@pytest.mark.parametrize(
    "page",
    [
        "<html><body>maintenance</body></html>",
        "<script>window.HiveSSOPublicCognitoClientId = 'abc'</script>",
        "<script>window.HiveSSOPoolId = 'nopool'\n"
        "window.HiveSSOPublicCognitoClientId = 'x'</script>",
        "<script>window.HiveSSOPoolId = 'eu-west-1_A\"\n"
        "window.HiveSSOPublicCognitoClientId = 'x'</script>",
    ],
)
def test_a_page_without_both_ids_is_not_guessed_at(page: str) -> None:
    assert parse_hive_sso_page(page) is None


def test_an_unreadable_page_falls_back_to_the_known_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == HIVE_SSO_URL
        return httpx.Response(200, text="<html>a redesign</html>")

    app = read_hive_cognito_app(transport=httpx.MockTransport(handler))

    assert app == KNOWN_HIVE_COGNITO_APP


def test_an_unreachable_page_falls_back_to_the_known_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert read_hive_cognito_app(transport=httpx.MockTransport(handler)) == KNOWN_HIVE_COGNITO_APP


def test_new_ids_on_the_page_are_used_for_a_new_login() -> None:
    page = (
        "<script>window.HiveSSOPoolId = 'eu-west-2_NewPool'\n"
        "window.HiveSSOPublicCognitoClientId = 'newclient'</script>"
    )

    app = read_hive_cognito_app(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))
    )

    assert app == HiveCognitoApp("eu-west-2_NewPool", "newclient")
    assert app.region == "eu-west-2"


# --- the stored blob --------------------------------------------------------------


def test_a_new_blob_records_the_app_that_issued_its_token() -> None:
    app = HiveCognitoApp("eu-west-2_NewPool", "newclient")
    blob = encode_hive_token_blob(username="mark@example.com", refresh_token="r", app=app)

    decoded = decode_hive_token_blob(blob)

    assert decoded == {
        "username": "mark@example.com",
        "refresh_token": "r",
        "pool_id": "eu-west-2_NewPool",
        "client_id": "newclient",
    }
    assert token_blob_app(decoded) == app


def test_a_blob_from_before_batch_348_uses_the_known_app() -> None:
    """Every token stored before this batch was issued by the known client."""
    assert token_blob_app({"username": "m", "refresh_token": "r"}) == KNOWN_HIVE_COGNITO_APP
    assert token_blob_app({"refresh_token": "r", "pool_id": "x", "client_id": "y"}) == (
        KNOWN_HIVE_COGNITO_APP
    )


def test_a_garbled_blob_is_an_auth_error() -> None:
    with pytest.raises(HiveAuthError):
        decode_hive_token_blob("not base64!")
    with pytest.raises(HiveAuthError):
        decode_hive_token_blob(base64.b64encode(b"[1, 2]").decode())


# --- the refresh ------------------------------------------------------------------


def _cognito(
    status: int, payload: dict[str, Any], seen: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def test_the_refresh_is_one_cognito_initiate_auth_call() -> None:
    seen: list[httpx.Request] = []
    transport = _cognito(200, {"AuthenticationResult": {"IdToken": "id-token"}}, seen)

    token = refresh_hive_id_token(KNOWN_HIVE_COGNITO_APP, "r3fr3sh", transport=transport)

    assert token == "id-token"
    (request,) = seen
    assert str(request.url) == "https://cognito-idp.eu-west-1.amazonaws.com/"
    assert request.headers["X-Amz-Target"] == ("AWSCognitoIdentityProviderService.InitiateAuth")
    assert request.headers["Content-Type"] == "application/x-amz-json-1.1"
    assert json.loads(request.content) == {
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "ClientId": HIVE_COGNITO_CLIENT_ID,
        "AuthParameters": {"REFRESH_TOKEN": "r3fr3sh"},
    }


def test_a_rejected_token_says_re_seed_and_never_shows_the_token() -> None:
    """The exact reply Cognito gave the 21 Jun token on 24 Oct."""
    seen: list[httpx.Request] = []
    transport = _cognito(
        400, {"__type": "NotAuthorizedException", "message": "Invalid Refresh Token"}, seen
    )

    with pytest.raises(HiveTokenRejectedError) as exc_info:
        refresh_hive_id_token(KNOWN_HIVE_COGNITO_APP, "r3fr3sh-t0ken", transport=transport)

    message = str(exc_info.value)
    assert "HIVE_TOKENSTORE_B64" in message
    assert "bootstrap_hive_tokenstore.py" in message
    assert "r3fr3sh-t0ken" not in message


def test_a_namespaced_error_type_is_still_recognised() -> None:
    transport = _cognito(400, {"__type": "com.amazon#NotAuthorizedException"}, [])

    with pytest.raises(HiveTokenRejectedError):
        refresh_hive_id_token(KNOWN_HIVE_COGNITO_APP, "r", transport=transport)


def test_a_cognito_outage_is_not_a_dead_token() -> None:
    transport = _cognito(500, {"__type": "InternalErrorException"}, [])

    with pytest.raises(HiveAuthError) as exc_info:
        refresh_hive_id_token(KNOWN_HIVE_COGNITO_APP, "r", transport=transport)

    assert not isinstance(exc_info.value, HiveTokenRejectedError)
    assert "InternalErrorException" in str(exc_info.value)


def test_an_unreachable_cognito_is_not_a_dead_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(HiveAuthError) as exc_info:
        refresh_hive_id_token(KNOWN_HIVE_COGNITO_APP, "r", transport=httpx.MockTransport(handler))

    assert not isinstance(exc_info.value, HiveTokenRejectedError)


def test_a_reply_without_an_id_token_is_an_auth_error() -> None:
    with pytest.raises(HiveAuthError, match="did not return an id token"):
        refresh_hive_id_token(
            KNOWN_HIVE_COGNITO_APP, "r", transport=_cognito(200, {"AuthenticationResult": {}}, [])
        )


# --- the bootstrap script Craig runs ---------------------------------------------


def _load_bootstrap_script(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "bootstrap_hive_tokenstore", SCRIPTS / "bootstrap_hive_tokenstore.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHiveApi:
    def getLoginInfo(self) -> dict[str, str]:  # pragma: no cover - replaced by the script
        raise AssertionError("pyhiveapi's own page scrape must not run")


class _FakeAuth:
    created: list[tuple[str, str, dict[str, str]]] = []

    def __init__(self, username: str, password: str) -> None:
        # As pyhiveapi does: the constructor asks HiveApi for the login info.
        self.login_info = _FakeHiveApi().getLoginInfo()
        _FakeAuth.created.append((username, password, self.login_info))

    def login(self) -> dict[str, str]:
        return {"ChallengeName": "SMS_MFA", "Session": "s"}

    def sms_2fa(self, code: str, challenge: dict[str, str]) -> dict[str, Any]:
        assert code == "123456"
        assert challenge["Session"] == "s"
        return {"AuthenticationResult": {"RefreshToken": "fresh-refresh"}}


def _fake_pyhiveapi(monkeypatch: pytest.MonkeyPatch) -> None:
    root = types.ModuleType("pyhiveapi")
    root.Auth = _FakeAuth  # type: ignore[attr-defined]
    api_pkg = types.ModuleType("pyhiveapi.api")
    hive_api = types.ModuleType("pyhiveapi.api.hive_api")
    hive_api.HiveApi = _FakeHiveApi  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyhiveapi", root)
    monkeypatch.setitem(sys.modules, "pyhiveapi.api", api_pkg)
    monkeypatch.setitem(sys.modules, "pyhiveapi.api.hive_api", hive_api)
    monkeypatch.setattr(_FakeHiveApi, "getLoginInfo", _FakeHiveApi.getLoginInfo)


def test_the_bootstrap_logs_in_through_the_fixed_ids_and_records_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_pyhiveapi(monkeypatch)
    _FakeAuth.created = []
    script = _load_bootstrap_script(monkeypatch)
    refreshed: list[tuple[HiveCognitoApp, str]] = []
    monkeypatch.setattr(script, "read_hive_cognito_app", lambda: KNOWN_HIVE_COGNITO_APP)
    monkeypatch.setattr(
        script,
        "refresh_hive_id_token",
        lambda app, token: refreshed.append((app, token)) or "id-token",
    )
    monkeypatch.setattr(script, "_bedroom_temperature", lambda token: "19.4 °C")
    monkeypatch.setenv("HIVE_EMAIL", "mark@example.com")
    monkeypatch.setenv("HIVE_PASSWORD", "s3cret-pw")
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")
    target = tmp_path / "hive.env"
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--env-output", str(target)])

    script.main()

    (created,) = _FakeAuth.created
    assert created == ("mark@example.com", "s3cret-pw", KNOWN_HIVE_COGNITO_APP.login_info())
    # The token is checked with the poller's own refresh before anything is written.
    assert refreshed == [(KNOWN_HIVE_COGNITO_APP, "fresh-refresh")]
    line = target.read_text().strip()
    assert line.startswith("HIVE_TOKENSTORE_B64=")
    blob = decode_hive_token_blob(line.split("=", 1)[1])
    assert blob["refresh_token"] == "fresh-refresh"
    assert token_blob_app(blob) == KNOWN_HIVE_COGNITO_APP
    out = capsys.readouterr().out
    assert "19.4 °C" in out
    assert "fresh-refresh" not in out
    assert "s3cret-pw" not in out


def test_the_bootstrap_writes_nothing_when_the_new_token_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_pyhiveapi(monkeypatch)
    script = _load_bootstrap_script(monkeypatch)
    monkeypatch.setattr(script, "read_hive_cognito_app", lambda: KNOWN_HIVE_COGNITO_APP)

    def rejected(app: HiveCognitoApp, token: str) -> str:
        raise HiveTokenRejectedError("no")

    monkeypatch.setattr(script, "refresh_hive_id_token", rejected)
    monkeypatch.setenv("HIVE_EMAIL", "mark@example.com")
    monkeypatch.setenv("HIVE_PASSWORD", "pw")
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")
    target = tmp_path / "hive.env"
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--env-output", str(target)])

    with pytest.raises(HiveTokenRejectedError):
        script.main()

    assert not target.exists()
