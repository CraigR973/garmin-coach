"""The owner-only key bootstrap cannot give the uploader deletion privileges."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def load() -> Any:
    path = Path(__file__).resolve().parents[3] / "scripts/create_backup_bucket_key.py"
    spec = importlib.util.spec_from_file_location("backup_bucket_key", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "access,expected", [("upload", ["writeFiles"]), ("restore", ["listFiles", "readFiles"])]
)
def test_minimal_key_scope_and_private_output(
    tmp_path: Path, access: str, expected: list[str]
) -> None:
    module = load()
    calls = []

    def api(url: str, headers: Any, body: Any = None) -> Any:
        calls.append(body)
        if body is None:
            return {
                "accountId": "account",
                "authorizationToken": "token",
                "apiInfo": {"storageApi": {"apiUrl": "https://api001.backblazeb2.com"}},
            }
        assert body["bucketIds"] == ["bucket"] and body["namePrefix"] == "coach/"
        assert body["capabilities"] == expected
        return body | {"applicationKeyId": "scoped-id", "applicationKey": "synthetic-secret"}

    output = tmp_path / "key.json"
    with patch.object(module, "request_json", api):
        module.create_key("bucket", access, "master-id", "master-secret", output)
        assert output.stat().st_mode & 0o777 == 0o600
        assert "synthetic-secret" in output.read_text()
        assert "master-secret" not in output.read_text()
        with pytest.raises(FileExistsError):
            module.create_key("bucket", access, "master-id", "master-secret", output)
    assert len(calls) == 2


def test_operator_credential_is_not_forwarded_on_http_redirect() -> None:
    import threading
    import urllib.error
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/leak")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            load().request_json(
                f"http://127.0.0.1:{server.server_port}/", {"Authorization": "synthetic"}
            )
        assert error.value.code == 302
        assert seen == ["/"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_read_only_check_reconciles_keys_and_bucket_without_creating_anything() -> None:
    module = load()
    endpoints: list[str] = []

    def api(url: str, headers: Any, body: Any = None) -> Any:
        endpoints.append(url.rsplit("/", 1)[-1])
        if body is None:
            return {
                "accountId": "account",
                "authorizationToken": "private-token",
                "apiInfo": {"storageApi": {"apiUrl": "https://api001.backblazeb2.com"}},
            }
        if url.endswith("b2_list_keys"):
            return {
                "keys": [
                    {
                        "keyName": "garmin-coach-upload",
                        "bucketIds": ["bucket"],
                        "namePrefix": "coach/",
                        "capabilities": ["writeFiles"],
                        "applicationKeyId": "private-id",
                    }
                ],
                "nextApplicationKeyId": None,
            }
        assert url.endswith("b2_list_buckets") and body["bucketId"] == "bucket"
        return {"buckets": [{"bucketId": "bucket", "bucketType": "allPrivate"}]}

    with patch.object(module, "request_json", api):
        result = module.check_existing("bucket", "upload", "master", "private-secret")
    assert endpoints == ["b2_authorize_account", "b2_list_keys", "b2_list_buckets"]
    assert result == {
        "mode": "read_only",
        "matching_keys": 1,
        "matching_scope": 1,
        "bucket_exists": True,
        "bucket_private": True,
    }
    assert "private" not in str(result).replace("bucket_private", "")


def test_check_only_main_preserves_empty_output_and_never_calls_create(
    tmp_path: Path,
    capsys: Any,
) -> None:
    module = load()
    output = tmp_path / "existing.json"
    output.touch(mode=0o600)
    with (
        patch(
            "sys.argv",
            [
                "helper",
                "--bucket-id",
                "bucket",
                "--access",
                "upload",
                "--output",
                str(output),
                "--check-only",
            ],
        ),
        patch.object(module.getpass, "getpass", side_effect=["private-id", "private-secret"]),
        patch.object(
            module, "check_existing", return_value={"mode": "read_only", "matching_keys": 0}
        ) as check,
        patch.object(module, "create_key") as create,
    ):
        module.main()
    create.assert_not_called()
    check.assert_called_once()
    assert output.read_bytes() == b""
    text = capsys.readouterr().out
    assert "CHECK_ONLY" in text and "private-secret" not in text


def test_api_failure_exposes_only_allowlisted_stage_status_and_code(
    tmp_path: Path,
    capsys: Any,
) -> None:
    import io
    import urllib.error

    module = load()
    error = urllib.error.HTTPError(
        "https://provider.invalid/private-secret",
        401,
        "private-secret",
        {},
        io.BytesIO(b'{"code":"unauthorized","message":"private-secret"}'),
    )
    with (
        patch(
            "sys.argv",
            [
                "helper",
                "--bucket-id",
                "bucket",
                "--access",
                "upload",
                "--output",
                str(tmp_path / "key.json"),
                "--check-only",
            ],
        ),
        patch.object(module.getpass, "getpass", side_effect=["private-id", "private-secret"]),
        patch.object(module, "request_json", side_effect=error) as api,
    ):
        with pytest.raises(SystemExit) as stopped:
            module.main()
    assert stopped.value.code == 1 and api.call_count == 1
    text = capsys.readouterr().out
    assert "stage=authorize reason=http_401_unauthorized" in text
    assert (
        "private-secret" not in text and "private-id" not in text and "provider.invalid" not in text
    )
    assert not (tmp_path / "key.json").exists()


def test_incomplete_key_listing_cannot_report_zero_matches() -> None:
    module = load()
    with patch.object(
        module,
        "request_json",
        side_effect=[
            {
                "accountId": "account",
                "authorizationToken": "token",
                "apiInfo": {"storageApi": {"apiUrl": "https://api001.backblazeb2.com"}},
            },
            {"keys": [], "nextApplicationKeyId": "more"},
        ],
    ) as api:
        with pytest.raises(module.SetupFailure, match="result_incomplete"):
            module.check_existing("bucket", "upload", "master", "secret")
    assert api.call_count == 2
