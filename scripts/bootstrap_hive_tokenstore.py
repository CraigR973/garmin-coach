"""Interactively mint a Hive Cognito refresh-token blob for HIVE_TOKENSTORE_B64.

Mark's Hive account uses AWS Cognito ``SMS_MFA``, so the unattended poller cannot
do a password login. Run this once (with the account phone to hand for the SMS
code) to exchange a full SMS-2FA login for a refresh token, then store the
printed ``HIVE_TOKENSTORE_B64`` value as a deployment secret. The poller resumes
from it via ``REFRESH_TOKEN_AUTH`` without further SMS prompts.

    HIVE_EMAIL=... HIVE_PASSWORD=... \
        apps/api/.venv/bin/python scripts/bootstrap_hive_tokenstore.py
"""

from __future__ import annotations

import base64
import getpass
import json
import os
from argparse import ArgumentParser
from pathlib import Path


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-output",
        type=Path,
        help="Optional path to write a HIVE_TOKENSTORE_B64 line.",
    )
    args = parser.parse_args()

    try:
        from pyhiveapi import Auth  # type: ignore[import-untyped, unused-ignore]
    except ImportError as exc:  # pragma: no cover - operator environment only
        raise SystemExit("pyhiveapi is not installed in this environment.") from exc

    username = os.getenv("HIVE_EMAIL") or input("Hive email: ").strip()
    password = os.getenv("HIVE_PASSWORD") or getpass.getpass("Hive password: ")

    auth = Auth(username, password)
    result = auth.login()
    if isinstance(result, dict) and result.get("ChallengeName") == "SMS_MFA":
        code = input("Hive SMS code (texted to the account phone): ").strip()
        result = auth.sms_2fa(code, result)

    auth_result = (result or {}).get("AuthenticationResult", {})
    refresh_token = auth_result.get("RefreshToken")
    if not refresh_token:
        raise SystemExit("Login did not return a refresh token; nothing to store.")

    blob = base64.b64encode(
        json.dumps({"username": username, "refresh_token": refresh_token}).encode()
    ).decode()

    if args.env_output:
        args.env_output.write_text(f"HIVE_TOKENSTORE_B64={blob}\n", encoding="utf-8")
        print(f"HIVE_TOKENSTORE_B64 written to {args.env_output}")
    else:
        print(f"HIVE_TOKENSTORE_B64={blob}")


if __name__ == "__main__":
    main()
