"""Deterministic local procurement site used by integration tests and demos."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import parse_qs, urlsplit


NOTICES = {
    "purchase": [
        {"id": "p-100", "title": "教学设备采购公告", "publish_time": "2026-07-17", "category": "采购公告"},
        {"id": "p-099", "title": "实验室耗材采购公告", "publish_time": "2026-07-16", "category": "采购公告"},
        {"id": "p-old", "title": "历史采购公告", "publish_time": "2025-12-01", "category": "采购公告"},
    ],
    "result": [
        {"id": "r-200", "title": "教学设备成交结果", "publish_time": "2026-07-17", "category": "结果公告"},
        {"id": "r-199", "title": "实验室耗材成交结果", "publish_time": "2026-07-16", "category": "结果公告"},
        {"id": "r-old", "title": "历史成交结果", "publish_time": "2025-11-30", "category": "结果公告"},
    ],
}


class MockBidHandler(BaseHTTPRequestHandler):
    """Serve two paginated boards, detail JSON, HTML, and a breaking v2 schema."""

    server_version = "BidFactoryMock/1.0"

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _json(self, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, value: str, status: int = 200) -> None:
        payload = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler contract
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        version = query.get("version", ["v1"])[0]
        if parts.path == "/api/notices":
            category = query.get("category", ["purchase"])[0]
            page = max(1, int(query.get("page", ["1"])[0]))
            rows = NOTICES.get(category, [])
            page_size = 2
            selected = [dict(item) for item in rows[(page - 1) * page_size: page * page_size]]
            if version == "v2":
                for item in selected:
                    item["published_at"] = item.pop("publish_time")
                    item["schema_marker"] = {"version": 2}
            self._json({"rows": selected, "page": page, "total": len(rows), "total_pages": 2})
            return
        if parts.path == "/api/detail":
            raw_id = query.get("id", [""])[0]
            row = next((item for rows in NOTICES.values() for item in rows if item["id"] == raw_id), None)
            if not row:
                self._json({"error": "not found"}, 404)
                return
            content = f"<div class='notice-content'><p>{row['title']}正文</p><table><tr><th>编号</th><td>{raw_id}</td></tr></table></div>"
            if version == "v2":
                self._json({"id": raw_id, "title": row["title"], "body": content, "amount": "1000"})
            else:
                self._json({"id": raw_id, "title": row["title"], "content": content, "amount": 1000})
            return
        if parts.path.startswith("/notice/"):
            raw_id = parts.path.rsplit("/", 1)[-1]
            self._html(f"<!doctype html><article class='notice-content' data-id='{raw_id}'><h1>{raw_id}</h1></article>")
            return
        self._json({"error": "not found"}, 404)


@contextmanager
def running_mock_site(host: str = "127.0.0.1", port: int = 0) -> Iterator[str]:
    """Run the mock site in a background thread and yield its base URL."""

    server = ThreadingHTTPServer((host, port), MockBidHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
