"""Craig's local-only B2 key bootstrap; master credentials never reach the app.

The console's broad presets may include delete capability. This creates a fresh
bucket/prefix-scoped key with the exact upload OR restore-read permissions. No
rotation/deletion, no secrets in argv/stdout, no dependencies beyond Python 3.12.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class SetupFailure(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(stage, reason)


def safe_reason(error: BaseException) -> str:
    """Never expose a URL, header, server message or credential in diagnostics."""
    if isinstance(error, urllib.error.HTTPError):
        code = "unknown"
        try:
            candidate = json.loads(error.read(8192)).get("code")
            if candidate in {
                "unauthorized",
                "bad_auth_token",
                "expired_auth_token",
                "bad_bucket_id",
                "bad_request",
                "transaction_cap_exceeded",
                "unsupported",
            }:
                code = candidate
        except Exception:
            pass
        return f"http_{int(error.code)}_{code}"
    if isinstance(error, urllib.error.URLError):
        return (
            "tls_verification_failed"
            if isinstance(error.reason, ssl.SSLError)
            else "network_error"
        )
    if isinstance(error, FileExistsError):
        return "output_already_exists"
    if isinstance(error, (KeyboardInterrupt, EOFError)):
        return "input_cancelled"
    if isinstance(error, OSError):
        return "local_file_error"
    if isinstance(error, (KeyError, TypeError, ValueError)):
        return "unexpected_response_or_input"
    return "unexpected_error"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        # Never forward an operator credential to a redirect destination.
        return None


def request_json(
    url: str, headers: dict[str, str], body: dict[str, Any] | None = None
) -> Any:
    request = urllib.request.Request(
        url,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.build_opener(NoRedirect()).open(
        request, timeout=30
    ) as response:
        return json.load(response)


def stage_request(stage: str, *args: Any) -> Any:
    try:
        return request_json(*args)
    except Exception as error:
        raise SetupFailure(stage, safe_reason(error)) from None


def authorize(key_id: str, secret: str) -> tuple[dict[str, Any], str]:
    basic = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    auth = stage_request(
        "authorize",
        "https://api.backblazeb2.com/b2api/v4/b2_authorize_account",
        {"Authorization": "Basic " + basic},
    )
    api = auth["apiInfo"]["storageApi"]["apiUrl"]
    parsed = urlsplit(api)
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".backblazeb2.com")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise SetupFailure("authorize", "unexpected_provider_endpoint")
    return auth, api


def check_existing(
    bucket_id: str, access: str, key_id: str, secret: str
) -> dict[str, Any]:
    """Read-only reconciliation: never calls create/delete or writes a file."""
    auth, api = authorize(key_id, secret)
    headers = {
        "Authorization": auth["authorizationToken"],
        "Content-Type": "application/json",
    }
    keys = stage_request(
        "list_keys",
        api + "/b2api/v4/b2_list_keys",
        headers,
        {"accountId": auth["accountId"], "maxKeyCount": 1000},
    )
    if keys.get("nextApplicationKeyId"):
        raise SetupFailure("list_keys", "result_incomplete_check_console")
    matches = [k for k in keys["keys"] if k.get("keyName") == "garmin-coach-" + access]
    buckets = stage_request(
        "check_bucket",
        api + "/b2api/v4/b2_list_buckets",
        headers,
        {"accountId": auth["accountId"], "bucketId": bucket_id},
    )["buckets"]
    caps = {"writeFiles"} if access == "upload" else {"listFiles", "readFiles"}
    return {
        "mode": "read_only",
        "matching_keys": len(matches),
        "matching_scope": sum(
            k.get("bucketIds") == [bucket_id]
            and k.get("namePrefix") == "coach/"
            and set(k.get("capabilities", [])) == caps
            for k in matches
        ),
        "bucket_exists": any(b.get("bucketId") == bucket_id for b in buckets),
        "bucket_private": any(
            b.get("bucketId") == bucket_id and b.get("bucketType") == "allPrivate"
            for b in buckets
        ),
    }


def create_key(
    bucket_id: str, access: str, key_id: str, secret: str, output: Path
) -> None:
    if not bucket_id or access not in {"upload", "restore"}:
        raise ValueError("invalid key scope")
    output = output.expanduser()
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Reserve BEFORE the remote create. Refuse overwrite rather than lose a live key.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        auth, api = authorize(key_id, secret)
        caps = ["writeFiles"] if access == "upload" else ["listFiles", "readFiles"]
        result = stage_request(
            "create_key",
            api + "/b2api/v4/b2_create_key",
            {
                "Authorization": auth["authorizationToken"],
                "Content-Type": "application/json",
            },
            {
                "accountId": auth["accountId"],
                "bucketIds": [bucket_id],
                "namePrefix": "coach/",
                "keyName": "garmin-coach-" + access,
                "capabilities": caps,
            },
        )
        if (
            set(result["capabilities"]) != set(caps)
            or result.get("bucketIds") != [bucket_id]
            or result.get("namePrefix") != "coach/"
        ):
            raise SetupFailure("validate_scope", "unexpected_key_scope_check_console")
        with os.fdopen(fd, "w") as stream:
            fd = -1
            json.dump(
                {k: result[k] for k in ("applicationKeyId", "applicationKey")}, stream
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if fd != -1:
            os.close(fd)
        # Preserve a possibly written key for owner recovery; never print its contents.
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket-id", required=True)
    parser.add_argument("--access", choices=("upload", "restore"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Read-only account/key/bucket checks; no key creation or file changes",
    )
    args = parser.parse_args()
    try:
        key_id = getpass.getpass("B2 master key ID: ")
        secret = getpass.getpass("B2 master application key (local only): ")
        if args.check_only:
            result = check_existing(args.bucket_id, args.access, key_id, secret)
            print("CHECK_ONLY " + json.dumps(result, sort_keys=True))
            return
        create_key(args.bucket_id, args.access, key_id, secret, args.output)
    except BaseException as error:
        stage = error.stage if isinstance(error, SetupFailure) else "local_or_input"
        reason = error.reason if isinstance(error, SetupFailure) else safe_reason(error)
        print(f"FAIL stage={stage} reason={reason}; check_only={args.check_only}")
        print(
            "Key setup did not finish. Check the private output file and B2 console; no automatic retry."
        )
        raise SystemExit(1) from None
    print(
        "Scoped key saved to the owner-only output file. Store it in your password manager."
    )


if __name__ == "__main__":
    main()
