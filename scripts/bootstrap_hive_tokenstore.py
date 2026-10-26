"""Interactively mint a Hive Cognito refresh-token blob for HIVE_TOKENSTORE_B64.

Mark's Hive account uses AWS Cognito ``SMS_MFA``, so the unattended poller never
does a password login. Run this once, with the account phone to hand for the SMS
code, to exchange a full SMS-2FA login for a refresh token, then store the
``HIVE_TOKENSTORE_B64`` value as a deployment secret. The poller resumes from it
via ``REFRESH_TOKEN_AUTH`` without further SMS prompts.

    apps/api/.venv/bin/python scripts/bootstrap_hive_tokenstore.py --env-output hive.env

It asks for the Hive email and password (or reads ``HIVE_EMAIL`` /
``HIVE_PASSWORD`` from this shell's environment), then for the code Hive texts.

Batch 348: Hive's sign-on page changed on 2026-10-20 and pyhiveapi can no longer
read it, so this script points pyhiveapi's login at the pool and client from
``services/hive_cognito`` (the page's, read in either quote style, else the known
ones), records that client in the blob, and checks the new token with the same
refresh the poller makes before it writes anything. Batch 351: it also records the
device key the login returns, which every refresh must now carry.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from secure_artifacts import write_secret_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from src.services.hive_cognito import (  # noqa: E402
    HiveAuthError,
    HiveCognitoApp,
    encode_hive_token_blob,
    login_device_key,
    read_hive_cognito_app,
    refresh_hive_id_token,
)


def _point_pyhiveapi_at(app: HiveCognitoApp) -> Any:
    """pyhiveapi's ``Auth``, with its sign-on page scrape replaced by ``app``.

    ``HiveAuth.__init__`` calls ``HiveApi.getLoginInfo``, which cannot parse the
    page since 2026-10-20. Patched in this process only; the app never uses it.
    """
    try:
        from pyhiveapi import Auth  # type: ignore[import-untyped, unused-ignore]
        from pyhiveapi.api.hive_api import (  # type: ignore[import-untyped, unused-ignore]
            HiveApi,
        )
    except ImportError as exc:  # pragma: no cover - operator environment only
        raise SystemExit("pyhiveapi is not installed in this environment.") from exc

    def login_info(self: Any) -> dict[str, str]:
        return app.login_info()

    HiveApi.getLoginInfo = login_info
    # pyhiveapi installs a global excepthook that itself crashes, burying the real
    # error under a second traceback (25 Oct). Ours should read plainly.
    sys.excepthook = sys.__excepthook__
    return Auth


def _bedroom_temperature(id_token: str) -> str:
    """What the poller would read with this token, as a sanity check."""
    from pyhiveapi import API  # type: ignore[import-untyped, unused-ignore]

    payload = API(token=id_token).getAll()
    parsed = payload.get("parsed") if isinstance(payload, dict) else None
    products = parsed.get("products", []) if isinstance(parsed, dict) else []
    for product in products:
        props = product.get("props") if isinstance(product, dict) else None
        if isinstance(props, dict) and props.get("temperature") is not None:
            return f"{props['temperature']} °C"
    return "no temperature in the reply"


#: What a remembered device is called on Mark's Hive account.
DEVICE_NAME = "garmin-coach"


def _try_refresh(app: HiveCognitoApp, refresh_token: str, device_key: str | None) -> str | None:
    """The poller's own refresh; the id token, or None with Hive's reason printed."""
    try:
        return refresh_hive_id_token(app, refresh_token, device_key=device_key)
    except HiveAuthError as exc:
        print(f"  refused: {exc}")
        return None


def _remember_device(auth: Any, result: dict[str, Any], device_key: str) -> bool:
    """Confirm the login's new device and mark it remembered, as the Hive app does.

    Batch 351: a code-free login on 25 Oct returned a device whose refresh was
    refused even with its key. Cognito pools that remember devices expect the
    client to confirm the device (``ConfirmDevice``) and remember it
    (``UpdateDeviceStatus``); upstream pyhive-integration does both after a
    login. This adds one device, named ``DEVICE_NAME``, to Mark's account.
    """
    auth_result = result.get("AuthenticationResult") or {}
    metadata = auth_result.get("NewDeviceMetadata") or {}
    group_key = metadata.get("DeviceGroupKey")
    access_token = auth_result.get("AccessToken")
    if not isinstance(group_key, str) or not isinstance(access_token, str):
        print("  cannot register: the login returned no device group or access token")
        return False
    auth.access_token = access_token
    auth.device_key = device_key
    auth.device_group_key = group_key
    try:
        auth.device_registration(DEVICE_NAME)
    except Exception as exc:  # noqa: BLE001 - report Cognito's refusal, never the secrets
        print(f"  registration refused: {type(exc).__name__}")
        return False
    return True


def _probe_rotating_refresh(app: HiveCognitoApp, refresh_token: str, device_key: str | None) -> str:
    """Whether Hive now rotates refresh tokens (``GetTokensFromRefreshToken``).

    Diagnostic only: with rotation on, ``REFRESH_TOKEN_AUTH`` is not how a token
    is refreshed, and the poller would have to store each new token. Says what
    Cognito answered; never returns or prints a token.
    """
    import httpx

    body: dict[str, str] = {"ClientId": app.client_id, "RefreshToken": refresh_token}
    if device_key is not None:
        body["DeviceKey"] = device_key
    try:
        response = httpx.post(
            f"https://cognito-idp.{app.region}.amazonaws.com/",
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "AWSCognitoIdentityProviderService.GetTokensFromRefreshToken",
            },
            content=json.dumps(body),
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        return f"could not reach Cognito ({type(exc).__name__})"
    if response.status_code == httpx.codes.OK:
        return "WORKS: Hive rotates refresh tokens"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    kind = str(payload.get("__type", response.status_code)).rsplit("#", 1)[-1]
    return f"refused: {kind} ({str(payload.get('message', ''))[:120]})"


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-output",
        type=Path,
        help="Optional path to write a HIVE_TOKENSTORE_B64 line.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help=(
            "Print HIVE_TOKENSTORE_B64 to stdout. Use only in a private shell; "
            "stdout may be captured by terminal, CI, or remote-session logs."
        ),
    )
    args = parser.parse_args()
    if not args.env_output and not args.stdout:
        parser.error("choose --env-output FILE for a 0600 file, or explicit --stdout")

    app = read_hive_cognito_app()
    print(f"Hive login: pool {app.pool_id}, app client ending {app.client_id[-4:]}")
    auth_cls = _point_pyhiveapi_at(app)

    username = os.getenv("HIVE_EMAIL") or input("Hive email: ").strip()
    password = os.getenv("HIVE_PASSWORD") or getpass.getpass("Hive password: ")

    auth = auth_cls(username, password)
    result = auth.login()
    challenge = result.get("ChallengeName") if isinstance(result, dict) else None
    if challenge == "SMS_MFA":
        code = input("Hive SMS code (texted to the account phone): ").strip()
        result = auth.sms_2fa(code, result)
    elif challenge is not None:
        raise SystemExit(f"Hive asked for a {challenge} step this script cannot answer.")
    print(f"Login: {'with an SMS code' if challenge else 'no code asked for'}")

    auth_result = (result or {}).get("AuthenticationResult", {})
    refresh_token = auth_result.get("RefreshToken")
    if not refresh_token:
        raise SystemExit("Login did not return a refresh token; nothing to store.")
    # Batch 351: the refresh token is bound to the device this login created.
    device_key = login_device_key(result)
    print(f"Device key: {'returned' if device_key else 'none returned'}")

    # The poller's own refresh, before anything is written.
    print("Token check: refreshing as the poller will")
    id_token = _try_refresh(app, refresh_token, device_key)
    if id_token is None and device_key is not None:
        print(f"Registering this app as a remembered device ({DEVICE_NAME}), then checking again")
        if _remember_device(auth, result, device_key):
            id_token = _try_refresh(app, refresh_token, device_key)
    if id_token is None:
        rotation = _probe_rotating_refresh(app, refresh_token, device_key)
        raise SystemExit(
            f"Token check failed, nothing written. Rotating-refresh probe: {rotation}. "
            "Show Claude this output."
        )
    print(f"Token check: refresh works; Hive reports {_bedroom_temperature(id_token)}")

    blob = encode_hive_token_blob(
        username=username, refresh_token=refresh_token, app=app, device_key=device_key
    )
    if args.env_output:
        write_secret_file(args.env_output, f"HIVE_TOKENSTORE_B64={blob}\n")
        print(f"HIVE_TOKENSTORE_B64 written to {args.env_output} (0600)")
    else:
        print(f"HIVE_TOKENSTORE_B64={blob}")


if __name__ == "__main__":
    main()
