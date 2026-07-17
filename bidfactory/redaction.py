"""Credential redaction and conservative secret scanning."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(
    r"(?:authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|token|access[-_]?token|"
    r"refresh[-_]?token|api[-_]?key|apikey|secret|password|passwd|pwd|db[-_]?password)",
    re.I,
)
INLINE_SECRET = re.compile(
    r"(?i)\b(authorization|cookie|token|access_token|api[_-]?key|password|passwd|pwd)\b"
    r"\s*[:=]\s*([^\s,;\"'<>]+)"
)


def is_sensitive_key(key: Any) -> bool:
    """Return whether a mapping key represents authentication material."""

    return bool(SENSITIVE_KEY.search(str(key)))


def redact_value(value: Any) -> Any:
    """Recursively redact values whose key names indicate secrets."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_sensitive_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


def sanitize_url(url: str) -> str:
    """Redact sensitive URL query parameters while preserving request shape."""

    parts = urlsplit(str(url))
    query = [
        (key, REDACTED if is_sensitive_key(key) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def redact_text(text: str, known_secrets: list[str] | None = None) -> str:
    """Remove inline credentials and exact configured secret values from text."""

    result = INLINE_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", text or "")
    for secret in sorted({item for item in (known_secrets or []) if item}, key=len, reverse=True):
        result = result.replace(secret, REDACTED)
    return result


def find_secret_markers(text: str) -> list[str]:
    """Return suspicious credential markers without returning their values."""

    markers = set()
    safe_prefixes = ("args.", "os.getenv", "getenv", "[redacted]", "<", "your_", "none", "null")
    for match in INLINE_SECRET.finditer(text or ""):
        value = match.group(2).strip("\"' ,)}]").lower()
        if not value or value.startswith(safe_prefixes) or re.fullmatch(r"[a-z_][a-z0-9_.]*", value):
            continue
        markers.add(match.group(1).lower())
    return sorted(markers)
