from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from bidfactory.capture import capture_fixture
from bidfactory.errors import FixtureError, NetworkAccessBlocked
from bidfactory.fixture import load_bundle, load_manifest
from bidfactory.replay import replay_fixture


class _MockSiteHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path == "/data":
            query = parse_qs(parsed.query)
            body = {
                "records": [
                    {
                        "webname": "本地模拟采购网",
                        "href": f"http://127.0.0.1:{self.server.server_port}/detail/1",
                        "title": "采购公告一",
                        "publish_time": "2026-07-17",
                        "category": "采购公告",
                        "msg": "正文",
                        "html": "<p>正文</p>",
                    }
                ],
                "password": "server-password-789",
                "echo": self.headers.get("Authorization", ""),
                "query_token": query.get("token", [""])[0],
            }
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "session=response-cookie-secret")
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/page":
            token = parse_qs(parsed.query).get("token", [""])[0]
            cookie_echo = self.headers.get("Cookie", "")
            payload = (
                f"<html><body><div class='notice-body'>token={token}</div>"
                f"<div class='echo'>{cookie_echo}</div></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"pong")
            return
        self.send_response(404)
        self.end_headers()


@contextmanager
def _mock_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockSiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _write_config(root: Path, base_url: str, *, adapter: bool = True) -> Path:
    if adapter:
        (root / "adapter.py").write_text(
            """def parse_fixture(bundle):
    data = bundle.get("list-json").json()
    return data["records"]
""",
            encoding="utf-8",
        )
    config = {
        "schema_version": 1,
        "site_name": "本地模拟采购网",
        "base_url": base_url,
        "allowed_hosts": ["127.0.0.1"],
        "expected_categories": ["采购公告"],
        "dom_selectors": {".notice-body": {"min": 1}},
        "adapter": "adapter.py" if adapter else None,
        "requests": [
            {
                "id": "list-json",
                "role": "list",
                "category": "采购公告",
                "page": 1,
                "url": "/data",
                "params": {"token": "query-secret-456"},
                "headers": {
                    "Authorization": "Bearer header-secret-123",
                    "Cookie": "session=request-cookie-secret",
                },
                "response_type": "json",
            },
            {
                "id": "detail-html",
                "role": "detail",
                "category": "采购公告",
                "url": "/page?token=query-secret-456",
                "response_type": "html",
            },
        ],
    }
    path = root / "site_config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_capture_records_json_and_html_without_secrets_and_replays(tmp_path: Path) -> None:
    with _mock_site() as base_url:
        config = _write_config(tmp_path, base_url)
        fixture = capture_fixture(config, tmp_path / "fixture-v1")

    manifest = load_manifest(fixture)
    assert manifest["schema_version"] == 1
    assert manifest["adapter"] == {"path": "adapter.py", "callable": "parse_fixture"}
    assert manifest["expected_categories"] == ["采购公告"]
    assert [entry["body_file"] for entry in manifest["entries"]] == [
        "bodies/001_list-json.json",
        "bodies/002_detail-html.html",
    ]
    assert "set-cookie" not in manifest["entries"][0]["headers"]
    assert manifest["entries"][0]["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert manifest["entries"][0]["request"]["params"]["token"] == "[REDACTED]"

    fixture_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in fixture.rglob("*")
        if path.is_file()
    )
    for secret in (
        "query-secret-456",
        "header-secret-123",
        "request-cookie-secret",
        "response-cookie-secret",
        "server-password-789",
    ):
        assert secret not in fixture_text
    assert "[REDACTED]" in fixture_text

    bundle = load_bundle(fixture)
    assert bundle.get("list-json").json()["password"] == "[REDACTED]"
    records = replay_fixture(fixture)
    assert records[0]["title"] == "采购公告一"
    artifact = json.loads((fixture / "artifacts" / "records.json").read_text(encoding="utf-8"))
    assert artifact["records"] == records


def test_capture_rejects_host_outside_explicit_allowlist(tmp_path: Path) -> None:
    config = {
        "site_name": "bad-host",
        "allowed_hosts": ["localhost"],
        "requests": [{"id": "outside", "url": "http://127.0.0.1:9/data"}],
    }
    path = tmp_path / "site_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "fixture"
    with pytest.raises(FixtureError, match="not allowed"):
        capture_fixture(path, output)
    assert not output.exists()
    assert not (tmp_path / ".fixture.partial").exists()


def test_replay_blocks_network_during_adapter_import_and_execution(tmp_path: Path) -> None:
    with _mock_site() as base_url:
        config = _write_config(tmp_path, base_url)
        fixture = capture_fixture(config, tmp_path / "fixture")
        adapter = fixture / "adapter.py"
        adapter.write_text(
            f"""import socket
socket.create_connection(("127.0.0.1", {urlsplit(base_url).port}), timeout=1)

def parse_fixture(bundle):
    return []
""",
            encoding="utf-8",
        )
        with pytest.raises(NetworkAccessBlocked):
            replay_fixture(fixture)

        adapter.write_text(
            f"""import requests

def parse_fixture(bundle):
    requests.get("{base_url}/ping", timeout=1)
    return []
""",
            encoding="utf-8",
        )
        with pytest.raises(NetworkAccessBlocked):
            replay_fixture(fixture)

        response = requests.get(f"{base_url}/ping", timeout=2)
        assert response.text == "pong"


def test_generic_json_replay_without_adapter(tmp_path: Path) -> None:
    with _mock_site() as base_url:
        config = _write_config(tmp_path, base_url, adapter=False)
        raw = json.loads(config.read_text(encoding="utf-8"))
        raw["requests"] = raw["requests"][:1]
        config.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        fixture = capture_fixture(config, tmp_path / "fixture-generic")

    records = replay_fixture(fixture)
    assert len(records) == 1
    assert records[0]["webname"] == "本地模拟采购网"
    assert records[0]["href"].startswith("http://127.0.0.1:")


def test_offline_guard_blocks_raw_socket_even_without_requests(tmp_path: Path) -> None:
    fixture = tmp_path / "manual-fixture"
    (fixture / "bodies").mkdir(parents=True)
    (fixture / "bodies" / "records.json").write_text('{"records": []}', encoding="utf-8")
    (fixture / "adapter.py").write_text(
        """import socket

def parse_fixture(bundle):
    sock = socket.socket()
    sock.connect(("127.0.0.1", 1))
    return []
""",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "site_name": "manual",
        "adapter": {"path": "adapter.py", "callable": "parse_fixture"},
        "entries": [
            {
                "id": "records",
                "status_code": 200,
                "content_type": "application/json",
                "encoding": "utf-8",
                "body_file": "bodies/records.json",
            }
        ],
    }
    (fixture / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(NetworkAccessBlocked):
        replay_fixture(fixture)


def test_fixture_body_path_cannot_escape_root(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "entries": [{"id": "escape", "body_file": "../outside.json"}],
    }
    (fixture / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Exception, match="escapes"):
        load_bundle(fixture)
