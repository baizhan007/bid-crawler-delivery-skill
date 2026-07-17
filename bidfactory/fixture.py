"""Versioned, portable response fixtures used by capture and replay."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import FixtureError
from .io import ensure_within, load_json


MANIFEST_SCHEMA_VERSION = 1


def load_manifest(root: Path) -> dict[str, Any]:
    """Load and minimally validate a fixture manifest."""

    fixture_root = root.resolve()
    manifest_path = fixture_root / "manifest.json"
    data = load_json(manifest_path)
    if not isinstance(data, dict):
        raise FixtureError(f"Fixture manifest must be a JSON object: {manifest_path}")
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise FixtureError(
            f"Unsupported fixture schema in {manifest_path}: "
            f"expected {MANIFEST_SCHEMA_VERSION}, got {data.get('schema_version')!r}"
        )
    entries = data.get("entries", data.get("requests"))
    if not isinstance(entries, list) or not entries:
        raise FixtureError(f"Fixture manifest has no response entries: {manifest_path}")
    return data


def manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized manifest entries while retaining unknown metadata."""

    raw_entries = manifest.get("entries", manifest.get("requests", []))
    if not isinstance(raw_entries, list):
        raise FixtureError("Fixture entries must be a list")
    entries = []
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise FixtureError(f"Fixture entry {index} must be a JSON object")
        entries.append(entry)
    return entries


def _entry_value(entry: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in entry:
        return entry[key]
    response = entry.get("response")
    if isinstance(response, dict):
        return response.get(key, default)
    return default


@dataclass(frozen=True)
class FixtureResponse:
    """A small requests-like response backed entirely by a fixture body."""

    root: Path
    entry: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.entry.get("id", ""))

    @property
    def status_code(self) -> int:
        return int(_entry_value(self.entry, "status_code", 0))

    @property
    def headers(self) -> dict[str, str]:
        raw = _entry_value(self.entry, "headers", {})
        return {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}

    @property
    def content_type(self) -> str:
        return str(_entry_value(self.entry, "content_type", ""))

    @property
    def url(self) -> str:
        response_url = _entry_value(self.entry, "url", "")
        if response_url:
            return str(response_url)
        request = self.entry.get("request", {})
        return str(request.get("url", "")) if isinstance(request, dict) else ""

    @property
    def request(self) -> dict[str, Any]:
        value = self.entry.get("request", {})
        return dict(value) if isinstance(value, dict) else {}

    @property
    def context(self) -> dict[str, Any]:
        ignored = {"request", "response", "body_file", "headers", "url", "content_type", "status_code"}
        return {key: value for key, value in self.entry.items() if key not in ignored}

    @property
    def body_path(self) -> Path:
        body_file = _entry_value(self.entry, "body_file")
        if not isinstance(body_file, str) or not body_file.strip():
            raise FixtureError(f"Fixture response {self.id or '<unknown>'} has no body_file")
        path = ensure_within(self.root / body_file, self.root)
        if not path.is_file():
            raise FixtureError(f"Fixture body does not exist for {self.id or '<unknown>'}: {body_file}")
        return path

    @property
    def content(self) -> bytes:
        return self.body_path.read_bytes()

    @property
    def text(self) -> str:
        encoding = str(_entry_value(self.entry, "encoding", "utf-8") or "utf-8")
        try:
            return self.content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("utf-8-sig", errors="replace")

    def json(self) -> Any:
        """Decode the recorded body as JSON."""

        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise FixtureError(f"Fixture response {self.id or '<unknown>'} is not valid JSON") from exc


@dataclass(frozen=True)
class FixtureBundle:
    """Manifest plus its ordered responses, passed to site adapters."""

    root: Path
    manifest: dict[str, Any]
    responses: tuple[FixtureResponse, ...]

    def __iter__(self) -> Iterator[FixtureResponse]:
        return iter(self.responses)

    def get(self, response_id: str) -> FixtureResponse:
        """Find one recorded response by id."""

        for response in self.responses:
            if response.id == response_id:
                return response
        raise FixtureError(f"Fixture response id not found: {response_id}")


def load_bundle(root: Path) -> FixtureBundle:
    """Load a fixture and resolve all body paths without network access."""

    fixture_root = root.resolve()
    manifest = load_manifest(fixture_root)
    responses = tuple(FixtureResponse(fixture_root, entry) for entry in manifest_entries(manifest))
    for response in responses:
        response.body_path
    return FixtureBundle(fixture_root, manifest, responses)
