"""Capture public HTML/JSON responses into a portable, sanitized fixture."""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

from .errors import FixtureError
from .fixture import MANIFEST_SCHEMA_VERSION
from .io import compile_source, ensure_within, load_json, safe_filename, sha256_file, write_json
from .redaction import REDACTED, is_sensitive_key, redact_text, redact_value, sanitize_url


SAFE_RESPONSE_HEADERS = {
    "cache-control",
    "content-language",
    "content-type",
    "etag",
    "expires",
    "last-modified",
}
HARDCODED_SECRET = re.compile(
    r"(?i)\b(?:authorization|cookie|token|api[_-]?key|secret|password|passwd|pwd)\b"
    r"\s*[:=]\s*['\"](?!\$\{|\[REDACTED\]|your_|example)[^'\"]{4,}['\"]"
)


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    nested = config.get("capture", {})
    if nested is None:
        return {}
    if not isinstance(nested, dict):
        raise FixtureError("site_config.capture must be a JSON object")
    return nested


def _configured(config: dict[str, Any], key: str, default: Any = None) -> Any:
    nested = _settings(config)
    return nested[key] if key in nested else config.get(key, default)


def _scalar_secrets(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        secrets: list[str] = []
        for key, item in value.items():
            if is_sensitive_key(key):
                candidates = item if isinstance(item, (list, tuple, set)) else [item]
                for candidate in candidates:
                    text = str(candidate or "")
                    if text and text != REDACTED:
                        secrets.append(text)
                        if " " in text:
                            secrets.append(text.split(" ", 1)[1])
                        if "=" in text:
                            secrets.extend(part.split("=", 1)[1] for part in text.split(";") if "=" in part)
            secrets.extend(_scalar_secrets(item))
        return secrets
    if isinstance(value, (list, tuple, set)):
        secrets = []
        for item in value:
            secrets.extend(_scalar_secrets(item))
        return secrets
    return []


def _query_secrets(url: str) -> list[str]:
    return [value for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True) if is_sensitive_key(key) and value]


def _replace_known(value: Any, secrets: list[str]) -> Any:
    safe = redact_value(value)
    if isinstance(safe, dict):
        return {key: _replace_known(item, secrets) for key, item in safe.items()}
    if isinstance(safe, list):
        return [_replace_known(item, secrets) for item in safe]
    if isinstance(safe, str):
        return redact_text(safe, secrets)
    return safe


def _allowed_hosts(config: dict[str, Any]) -> set[str]:
    raw = _configured(config, "allowed_hosts")
    if not isinstance(raw, list) or not raw:
        raise FixtureError("site_config must declare a non-empty allowed_hosts list")
    result = set()
    for item in raw:
        text = str(item or "").strip().lower()
        if not text or "/" in text or "@" in text:
            raise FixtureError(f"Invalid allowed host: {item!r}")
        result.add(text.split(":", 1)[0])
    return result


def _validate_url(url: str, allowed_hosts: set[str]) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise FixtureError(f"Capture URL must be an absolute HTTP/HTTPS URL: {sanitize_url(url)}")
    if parts.username or parts.password:
        raise FixtureError("Credentials in capture URLs are forbidden")
    if parts.hostname.lower() not in allowed_hosts:
        raise FixtureError(f"Capture host is not allowed: {parts.hostname}")
    return url


def _safe_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in SAFE_RESPONSE_HEADERS
    }


def _send_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    allowed_hosts: set[str],
    follow_redirects: bool,
    max_redirects: int,
    kwargs: dict[str, Any],
) -> requests.Response:
    current_method = method
    current_url = _validate_url(url, allowed_hosts)
    current_kwargs = dict(kwargs)
    for redirect_index in range(max_redirects + 1):
        response = session.request(current_method, current_url, allow_redirects=False, **current_kwargs)
        if not follow_redirects or not response.is_redirect:
            return response
        if redirect_index >= max_redirects:
            response.close()
            raise FixtureError(f"Capture exceeded {max_redirects} redirects: {sanitize_url(url)}")
        location = response.headers.get("Location")
        if not location:
            return response
        next_url = _validate_url(urljoin(response.url, location), allowed_hosts)
        status = response.status_code
        response.close()
        if status == 303 or (status in {301, 302} and current_method not in {"GET", "HEAD"}):
            current_method = "GET"
            current_kwargs.pop("json", None)
            current_kwargs.pop("data", None)
        current_kwargs.pop("params", None)
        current_url = next_url
    raise AssertionError("redirect loop should always return or raise")


def _status_allowed(response: requests.Response, spec: dict[str, Any]) -> bool:
    configured = spec.get("expected_statuses", spec.get("expected_status"))
    if configured is None:
        return 200 <= response.status_code < 300
    values = configured if isinstance(configured, list) else [configured]
    try:
        return response.status_code in {int(value) for value in values}
    except (TypeError, ValueError) as exc:
        raise FixtureError(f"Invalid expected status list for request {spec.get('id')!r}") from exc


def _write_body(
    path_base: Path,
    response: requests.Response,
    response_type: str,
    secrets: list[str],
) -> tuple[Path, str, str]:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    requested = response_type.strip().lower()
    is_json = requested == "json" or "json" in content_type
    if is_json:
        try:
            payload = response.json()
        except (requests.JSONDecodeError, ValueError) as exc:
            raise FixtureError(f"Response declared JSON but could not be decoded: {sanitize_url(response.url)}") from exc
        path = path_base.with_suffix(".json")
        write_json(path, _replace_known(payload, secrets))
        return path, "application/json", "utf-8"
    if not (requested in {"", "auto", "html", "text"} or content_type.startswith("text/")):
        raise FixtureError(f"Unsupported capture response type {content_type or '<missing>'}: {sanitize_url(response.url)}")
    encoding = response.encoding or "utf-8"
    try:
        text = response.content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        encoding = "utf-8"
        text = response.content.decode("utf-8", errors="replace")
    text = redact_text(text, secrets)
    is_html = requested == "html" or "html" in content_type or "<html" in text[:1000].lower()
    path = path_base.with_suffix(".html" if is_html else ".txt")
    path.write_text(text, encoding="utf-8")
    return path, content_type or ("text/html" if is_html else "text/plain"), "utf-8"


def _snapshot_adapter(config: dict[str, Any], config_root: Path, fixture_root: Path) -> dict[str, str] | None:
    configured = config.get("adapter")
    if not configured:
        return None
    if isinstance(configured, str):
        relative = configured
        callable_name = "parse_fixture"
    elif isinstance(configured, dict):
        relative = configured.get("path")
        callable_name = str(configured.get("callable") or "parse_fixture")
    else:
        raise FixtureError("site_config.adapter must be a path string or object")
    if not isinstance(relative, str) or not relative:
        raise FixtureError("site_config.adapter.path is required")
    source = ensure_within(config_root / relative, config_root)
    if not source.is_file() or source.suffix.lower() != ".py":
        raise FixtureError(f"Adapter must be an existing Python file inside the project: {source}")
    compile_source(source)
    source_text = source.read_text(encoding="utf-8-sig")
    if HARDCODED_SECRET.search(source_text):
        raise FixtureError(f"Adapter appears to contain a hardcoded credential: {source.name}")
    destination = fixture_root / "adapter.py"
    destination.write_text(source_text, encoding="utf-8")
    if not callable_name.isidentifier():
        raise FixtureError(f"Invalid adapter callable: {callable_name!r}")
    return {"path": "adapter.py", "callable": callable_name}


def _default_output(config_path: Path, config: dict[str, Any]) -> Path:
    configured = _configured(config, "fixture_dir") or _configured(config, "output_dir")
    if configured:
        path = Path(str(configured))
        return path if path.is_absolute() else config_path.parent / path
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return config_path.parent / "fixtures" / stamp


def capture_fixture(config_path: Path, output_dir: Path | None = None) -> Path:
    """Capture all configured requests and return the completed fixture path."""

    config_file = Path(config_path).resolve()
    config = load_json(config_file)
    if not isinstance(config, dict):
        raise FixtureError(f"Site config must be a JSON object: {config_file}")
    requests_config = _configured(config, "requests")
    if not isinstance(requests_config, list) or not requests_config:
        raise FixtureError("site_config must contain at least one capture request")
    allowed_hosts = _allowed_hosts(config)
    destination = (Path(output_dir) if output_dir else _default_output(config_file, config)).resolve()
    if destination.exists():
        raise FixtureError(f"Capture output already exists; refusing to overwrite: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.partial")
    if staging.exists():
        raise FixtureError(f"Stale capture staging directory exists: {staging}")
    staging.mkdir(parents=True)
    (staging / "bodies").mkdir()
    timeout = float(_configured(config, "timeout", 15.0))
    delay = max(0.0, float(_configured(config, "delay", 0.0)))
    max_bytes = int(_configured(config, "max_response_bytes", 5 * 1024 * 1024))
    follow_redirects = bool(_configured(config, "follow_redirects", False))
    max_redirects = int(_configured(config, "max_redirects", 5))
    verify_tls = bool(_configured(config, "verify_tls", True))
    base_url = str(config.get("base_url") or "")
    seen_ids: set[str] = set()
    entries: list[dict[str, Any]] = []
    all_secrets = _scalar_secrets(config)
    session = requests.Session()
    session.headers.update({"User-Agent": "BidCrawlerFactory/1.0 capture"})
    try:
        adapter = _snapshot_adapter(config, config_file.parent, staging)
        for index, raw_spec in enumerate(requests_config):
            if not isinstance(raw_spec, dict):
                raise FixtureError(f"Capture request {index} must be a JSON object")
            spec = dict(raw_spec)
            response_id = str(spec.get("id") or f"response-{index + 1}").strip()
            if response_id in seen_ids:
                raise FixtureError(f"Duplicate capture request id: {response_id}")
            seen_ids.add(response_id)
            raw_url = str(spec.get("url") or spec.get("path") or "")
            url = urljoin(base_url.rstrip("/") + "/", raw_url) if base_url and not urlsplit(raw_url).scheme else raw_url
            _validate_url(url, allowed_hosts)
            method = str(spec.get("method") or "GET").upper()
            if method not in {"GET", "POST"}:
                raise FixtureError(f"Capture request {response_id} uses unsupported method: {method}")
            headers = spec.get("headers") or {}
            params = spec.get("params") or {}
            json_body = spec.get("json")
            data_body = spec.get("data")
            if not isinstance(headers, dict) or not isinstance(params, dict):
                raise FixtureError(f"Capture request {response_id} headers and params must be objects")
            if json_body is not None and data_body is not None:
                raise FixtureError(f"Capture request {response_id} cannot set both json and data")
            secrets = list(dict.fromkeys(all_secrets + _scalar_secrets(spec) + _query_secrets(url)))
            kwargs: dict[str, Any] = {
                "headers": headers,
                "params": params,
                "timeout": timeout,
                "verify": verify_tls,
            }
            if json_body is not None:
                kwargs["json"] = json_body
            if data_body is not None:
                kwargs["data"] = data_body
            try:
                response = _send_request(
                    session,
                    method,
                    url,
                    allowed_hosts=allowed_hosts,
                    follow_redirects=follow_redirects,
                    max_redirects=max_redirects,
                    kwargs=kwargs,
                )
            except requests.RequestException as exc:
                raise FixtureError(f"Capture request {response_id} failed: {type(exc).__name__}: {sanitize_url(url)}") from exc
            try:
                if not _status_allowed(response, spec):
                    raise FixtureError(
                        f"Capture request {response_id} returned unexpected status {response.status_code}: "
                        f"{sanitize_url(response.url)}"
                    )
                if len(response.content) > max_bytes:
                    raise FixtureError(f"Capture response {response_id} exceeds {max_bytes} bytes")
                response_secrets = _scalar_secrets({"set-cookie": response.headers.get("Set-Cookie", "")})
                secrets = list(dict.fromkeys(secrets + response_secrets))
                all_secrets = list(dict.fromkeys(all_secrets + response_secrets))
                stem = f"{index + 1:03d}_{safe_filename(response_id, f'response-{index + 1}')}"
                body_path, content_type, encoding = _write_body(
                    staging / "bodies" / stem,
                    response,
                    str(spec.get("response_type") or "auto"),
                    secrets,
                )
                entry = {
                    "id": response_id,
                    "role": str(spec.get("role") or ""),
                    "category": str(spec.get("category") or ""),
                    "page": spec.get("page"),
                    "request": _replace_known(
                        {
                            "method": method,
                            "url": sanitize_url(response.request.url or url),
                            "headers": dict(headers),
                            "params": params,
                            "json": json_body,
                            "data": data_body,
                        },
                        secrets,
                    ),
                    "status_code": response.status_code,
                    "url": sanitize_url(response.url),
                    "headers": _safe_headers(response.headers),
                    "content_type": content_type,
                    "encoding": encoding,
                    "body_file": body_path.relative_to(staging).as_posix(),
                    "body_sha256": sha256_file(body_path),
                    "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 3),
                }
                entries.append(entry)
            finally:
                response.close()
            if delay and index + 1 < len(requests_config):
                time.sleep(delay)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "site_name": str(config.get("site_name") or config_file.stem),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source_config": {"name": config_file.name, "sha256": sha256_file(config_file)},
            "allowed_hosts": sorted(allowed_hosts),
            "expected_categories": list(config.get("expected_categories") or config.get("categories") or []),
            "dom_selectors": config.get("dom_selectors") or {},
            "date_range": config.get("date_range") or {},
            "adapter": adapter,
            "entries": entries,
        }
        write_json(staging / "manifest.json", manifest)
        for secret in {item for item in all_secrets if item}:
            for path in staging.rglob("*"):
                if path.is_file() and secret in path.read_text(encoding="utf-8", errors="ignore"):
                    raise FixtureError(f"Secret redaction failed before writing fixture file: {path.name}")
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        session.close()
    return destination


capture_from_config = capture_fixture
capture_site = capture_fixture
