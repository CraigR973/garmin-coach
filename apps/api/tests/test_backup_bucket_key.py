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
