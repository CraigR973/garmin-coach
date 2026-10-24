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
refresh the poller makes before it writes anything.
"""

from __future__ import annotations

import getpass
import os
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from secure_artifacts import write_secret_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from src.services.hive_cognito import (  # noqa: E402
    HiveCognitoApp,
    encode_hive_token_blob,
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
    if isinstance(result, dict) and result.get("ChallengeName") == "SMS_MFA":
        code = input("Hive SMS code (texted to the account phone): ").strip()
        result = auth.sms_2fa(code, result)

    auth_result = (result or {}).get("AuthenticationResult", {})
    refresh_token = auth_result.get("RefreshToken")
    if not refresh_token:
        raise SystemExit("Login did not return a refresh token; nothing to store.")

    # The poller's own refresh, before anything is written.
    id_token = refresh_hive_id_token(app, refresh_token)
    print(f"Token check: refresh works; Hive reports {_bedroom_temperature(id_token)}")

    blob = encode_hive_token_blob(username=username, refresh_token=refresh_token, app=app)
    if args.env_output:
        write_secret_file(args.env_output, f"HIVE_TOKENSTORE_B64={blob}\n")
        print(f"HIVE_TOKENSTORE_B64 written to {args.env_output} (0600)")
    else:
        print(f"HIVE_TOKENSTORE_B64={blob}")


if __name__ == "__main__":
    main()
