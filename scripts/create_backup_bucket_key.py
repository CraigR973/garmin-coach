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
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
        basic = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
        auth = request_json(
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
            raise RuntimeError("unexpected provider endpoint")
        caps = ["writeFiles"] if access == "upload" else ["listFiles", "readFiles"]
        result = request_json(
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
            raise RuntimeError("unexpected key scope")
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
    args = parser.parse_args()
    try:
        create_key(
            args.bucket_id,
            args.access,
            getpass.getpass("B2 master key ID: "),
            getpass.getpass("B2 master application key (local only): "),
            args.output,
        )
    except BaseException:
        print(
            "Key setup did not finish. Check the private output file and B2 console; no automatic retry."
        )
        raise SystemExit(1) from None
    print(
        "Scoped key saved to the owner-only output file. Store it in your password manager."
    )


if __name__ == "__main__":
    main()
