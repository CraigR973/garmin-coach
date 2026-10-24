"""Hive's Cognito app, its sign-on page, and the stored refresh-token blob (Batch 348).

A leaf: no settings, models or database, so the interactive bootstrap script can
import it without the app's configuration.

Hive's single sign-on page publishes the Cognito user pool and public app client
that its logins run against, as ``window.HiveSSOPoolId = '…'`` assignments. On
2026-10-20 the page changed from minified, double-quoted assignments to one
single-quoted assignment per line. pyhiveapi 0.5.16 (its last release; upstream
now ships the async-only ``pyhive-integration``) builds JSON from that text by
string replacement, so every Hive login and token refresh failed inside
``HiveAuth.__init__`` from 13:04 UTC that day — before any call reached Cognito.

The ids themselves did not change: the page's copy of 8 Jun 2026 carries the same
two, and every refresh token stored so far was issued under them. So the poller
does not read the page at all. A refresh token works only with the app client
that issued it, so the blob records that client (since Batch 348), and a blob
from before then can only have come from the known one.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

HIVE_SSO_URL = "https://sso.hivehome.com/"
HIVE_COGNITO_POOL_ID = "eu-west-1_SamNfoWtf"
HIVE_COGNITO_CLIENT_ID = "3rl4i0ajrmtdm8sbre54p9dvd9"

#: Either quote style, and the closing quote must match the opening one.
_SSO_ASSIGNMENT = re.compile(r"""window\.(\w+)\s*=\s*(["'])(.*?)\2""")
#: Cognito's own formats: ``<region>_<id>`` and a short alphanumeric client id. A
#: value that is not one of these is not used, however it was found.
_POOL_ID = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d+_[0-9A-Za-z]+$")
_CLIENT_ID = re.compile(r"^[0-9A-Za-z]{1,128}$")

_COGNITO_INITIATE_AUTH = "AWSCognitoIdentityProviderService.InitiateAuth"


class HiveAuthError(RuntimeError):
    """A Hive token refresh failed. Never carries a credential."""


class HiveTokenRejectedError(HiveAuthError):
    """Cognito refused the stored refresh token: it expired or was revoked.

    Only a fresh interactive login fixes this, so it is kept apart from a refresh
    that merely could not reach Cognito.
    """


@dataclass(frozen=True)
class HiveCognitoApp:
    """The Cognito user pool and public app client a Hive login runs against."""

    pool_id: str
    client_id: str

    @property
    def region(self) -> str:
        return self.pool_id.split("_", 1)[0]

    def login_info(self) -> dict[str, str]:
        """The shape pyhiveapi's ``HiveApi.getLoginInfo`` returns."""
        return {"UPID": self.pool_id, "CLIID": self.client_id, "REGION": self.pool_id}


KNOWN_HIVE_COGNITO_APP = HiveCognitoApp(HIVE_COGNITO_POOL_ID, HIVE_COGNITO_CLIENT_ID)


def _cognito_app(pool_id: Any, client_id: Any) -> HiveCognitoApp | None:
    if not isinstance(pool_id, str) or not _POOL_ID.match(pool_id):
        return None
    if not isinstance(client_id, str) or not _CLIENT_ID.match(client_id):
        return None
    return HiveCognitoApp(pool_id=pool_id, client_id=client_id)


def parse_hive_sso_page(html: str) -> HiveCognitoApp | None:
    """Read the pool and public client from the sign-on page, in either quote style."""
    values = {key: value for key, _quote, value in _SSO_ASSIGNMENT.findall(html)}
    return _cognito_app(values.get("HiveSSOPoolId"), values.get("HiveSSOPublicCognitoClientId"))


def read_hive_cognito_app(
    *,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> HiveCognitoApp:
    """The app a new interactive login should use: the page's, else the known one."""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.get(HIVE_SSO_URL)
            response.raise_for_status()
        app = parse_hive_sso_page(response.text)
    except httpx.HTTPError:
        app = None
    if app is None:
        log.warning("hive_sso_page_unreadable", using="known_ids")
        return KNOWN_HIVE_COGNITO_APP
    if app != KNOWN_HIVE_COGNITO_APP:
        # Public values, printed on Hive's own page.
        log.warning("hive_sso_ids_changed", pool_id=app.pool_id, client_id=app.client_id)
    return app


def encode_hive_token_blob(*, username: str, refresh_token: str, app: HiveCognitoApp) -> str:
    """The ``HIVE_TOKENSTORE_B64`` value, recording the app that issued the token."""
    payload = {
        "username": username,
        "refresh_token": refresh_token,
        "pool_id": app.pool_id,
        "client_id": app.client_id,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode_hive_token_blob(blob: str) -> dict[str, Any]:
    try:
        data = json.loads(base64.b64decode(blob, validate=True))
    except (ValueError, TypeError) as exc:
        raise HiveAuthError("Hive token blob is not valid base64 JSON.") from exc
    if not isinstance(data, dict):
        raise HiveAuthError("Hive token blob did not decode to an object.")
    return data


def token_blob_app(blob: dict[str, Any]) -> HiveCognitoApp:
    """The app a stored token was issued by: recorded since Batch 348, else the known one."""
    return _cognito_app(blob.get("pool_id"), blob.get("client_id")) or KNOWN_HIVE_COGNITO_APP


def refresh_hive_id_token(
    app: HiveCognitoApp,
    refresh_token: str,
    *,
    timeout: float = 20.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Exchange a refresh token for a fresh Cognito id token (``REFRESH_TOKEN_AUTH``).

    ``InitiateAuth`` is an unauthenticated Cognito call for a public client, so
    this is one JSON POST rather than an AWS SDK client. No password and no MFA:
    nothing here can make Cognito text the account phone.
    """
    body = {
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "ClientId": app.client_id,
        "AuthParameters": {"REFRESH_TOKEN": refresh_token},
    }
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(
                f"https://cognito-idp.{app.region}.amazonaws.com/",
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": _COGNITO_INITIATE_AUTH,
                },
                content=json.dumps(body),
            )
    except httpx.HTTPError as exc:
        raise HiveAuthError("Hive token refresh could not reach Cognito.") from exc

    payload = _json_object(response)
    if response.status_code != httpx.codes.OK:
        error_type = _cognito_error_type(response, payload)
        if error_type == "NotAuthorizedException":
            raise HiveTokenRejectedError(
                "Hive rejected the stored refresh token (expired or revoked); re-seed "
                "HIVE_TOKENSTORE_B64 with scripts/bootstrap_hive_tokenstore.py and the "
                "account phone."
            )
        raise HiveAuthError(f"Hive token refresh failed ({error_type or response.status_code}).")

    result = payload.get("AuthenticationResult")
    token = result.get("IdToken") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise HiveAuthError("Hive token refresh did not return an id token.")
    return token


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _cognito_error_type(response: httpx.Response, payload: dict[str, Any]) -> str:
    raw = payload.get("__type") or response.headers.get("x-amzn-ErrorType") or ""
    # Either "NotAuthorizedException" or a namespaced "...#NotAuthorizedException".
    return str(raw).rsplit("#", 1)[-1].split(":", 1)[0]
