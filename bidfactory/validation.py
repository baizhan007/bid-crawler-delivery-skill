"""Record validation that derives every acceptance result from source data."""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import FactoryError
from .io import load_json
from .reports import write_report


REQUIRED_FIELDS = ("webname", "href", "msg", "html", "publish_time")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DANGEROUS_HTML = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|\bon\w+\s*=|(?:javascript|data\s*:\s*text/html)\s*:",
    re.I,
)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def load_records(target: Path, adapter: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load records from a fixture, records JSON/CSV, or delivery directory."""

    target = target.resolve()
    if target.is_file() and target.suffix.lower() == ".csv":
        return _read_csv(target), {}
    if target.is_file() and target.suffix.lower() == ".json":
        data = load_json(target)
        records = data.get("records") if isinstance(data, dict) else data
        if not isinstance(records, list):
            raise FactoryError(f"Expected a record list in {target}")
        return [dict(item) for item in records if isinstance(item, dict)], data if isinstance(data, dict) else {}
    if not target.is_dir():
        raise FactoryError(f"Validation input does not exist: {target}")

    manifest = target / "manifest.json"
    if manifest.exists():
        from .replay import replay_fixture

        records = replay_fixture(target, adapter_path=adapter)
        metadata = load_json(manifest)
        return records, metadata

    records_json = target / "artifacts" / "records.json"
    if records_json.exists():
        return load_records(records_json, adapter)

    csv_files = sorted(target.rglob("*.csv"))
    sample_files = [path for path in csv_files if "sample" in path.name.lower() or "验收样例" in path.parts]
    if sample_files:
        records: list[dict[str, Any]] = []
        for path in sample_files:
            records.extend(_read_csv(path))
        return records, {}
    raise FactoryError(f"No fixture manifest, records JSON, or sample CSV found under {target}")


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not DATE_RE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _valid_href(value: Any) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)


def _online_link_checks(hrefs: list[str], limit: int, delay: float) -> list[dict[str, Any]]:
    try:
        import requests
    except ImportError as exc:
        raise FactoryError("Online href checks require requests") from exc

    results = []
    for href in list(dict.fromkeys(hrefs))[: max(0, limit)]:
        status = None
        error = ""
        try:
            response = requests.get(
                href,
                timeout=12,
                allow_redirects=True,
                headers={"User-Agent": "BidCrawlerFactory/1.0 acceptance-check"},
                stream=True,
            )
            status = response.status_code
            response.close()
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
        results.append({"href": href, "status_code": status, "openable": bool(status and status < 400), "error": error})
        if delay:
            time.sleep(delay)
    return results


def validate_records(
    records: list[dict[str, Any]],
    *,
    expected_categories: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    required_rate: float = 0.995,
    check_links: bool = False,
    link_limit: int = 5,
    link_delay: float = 0.5,
) -> dict[str, Any]:
    """Calculate acceptance metrics from records; never trust precomputed flags."""

    total = len(records)
    non_empty = {
        field: sum(1 for row in records if str(row.get(field, "")).strip())
        for field in REQUIRED_FIELDS
    }
    rates = {field: round(count / total, 4) if total else 0.0 for field, count in non_empty.items()}
    keys = [(str(row.get("webname", "")).strip(), str(row.get("href", "")).strip()) for row in records]
    duplicate_count = total - len(set(keys))
    bad_hrefs = [
        {"index": index, "href": row.get("href", ""), "title": row.get("title", "")}
        for index, row in enumerate(records)
        if not _valid_href(row.get("href"))
    ]
    bad_dates = [
        {"index": index, "publish_time": row.get("publish_time", ""), "title": row.get("title", "")}
        for index, row in enumerate(records)
        if _parse_date(row.get("publish_time")) is None
    ]
    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None
    out_of_range = []
    for index, row in enumerate(records):
        parsed = _parse_date(row.get("publish_time"))
        if parsed and ((start and parsed < start) or (end and parsed > end)):
            out_of_range.append({"index": index, "publish_time": parsed.isoformat(), "title": row.get("title", "")})
    dangerous = [
        {"index": index, "title": row.get("title", "")}
        for index, row in enumerate(records)
        if DANGEROUS_HTML.search(str(row.get("html", "")))
    ]
    empty_bodies = [
        index
        for index, row in enumerate(records)
        if len(str(row.get("msg", "")).strip()) < 1 or len(str(row.get("html", "")).strip()) < 1
    ]
    categories = Counter(str(row.get("category", "")).strip() for row in records if str(row.get("category", "")).strip())
    expected = [str(item).strip() for item in (expected_categories or []) if str(item).strip()]
    missing_categories = [item for item in expected if categories.get(item, 0) == 0]
    online_checks = _online_link_checks(
        [str(row.get("href", "")) for row in records if _valid_href(row.get("href"))], link_limit, link_delay
    ) if check_links else []
    online_pass = all(item["openable"] for item in online_checks) if check_links else True
    flags = {
        "has_records": total > 0,
        "required_fields_ge_threshold": total > 0 and all(rate >= required_rate for rate in rates.values()),
        "no_duplicates": duplicate_count == 0,
        "dates_valid": not bad_dates,
        "dates_in_range": not out_of_range,
        "href_format_valid": not bad_hrefs,
        "categories_covered": not missing_categories,
        "body_quality_valid": not empty_bodies and not dangerous,
        "online_links_openable": online_pass,
    }
    flags["overall_pass"] = all(flags.values())
    return {
        "schema_version": 1,
        "total_records": total,
        "required_non_empty_rate": rates,
        "required_rate_threshold": required_rate,
        "duplicate_records": duplicate_count,
        "bad_href_samples": bad_hrefs[:50],
        "bad_date_samples": bad_dates[:50],
        "out_of_range_samples": out_of_range[:50],
        "dangerous_html_samples": dangerous[:50],
        "empty_body_indexes": empty_bodies[:50],
        "category_counts": dict(sorted(categories.items())),
        "expected_categories": expected,
        "missing_categories": missing_categories,
        "online_link_checks_enabled": check_links,
        "online_link_checks": online_checks,
        "quality_flags": flags,
    }


def validate_target(
    target: Path,
    *,
    adapter: Path | None = None,
    output_dir: Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    required_rate: float = 0.995,
    check_links: bool = False,
    link_limit: int = 5,
    link_delay: float = 0.5,
) -> tuple[dict[str, Any], Path]:
    """Load, validate, and write JSON/HTML reports for a target."""

    records, metadata = load_records(target, adapter)
    expected = metadata.get("expected_categories") or metadata.get("categories") or []
    if isinstance(expected, dict):
        expected = list(expected)
    report = validate_records(
        records,
        expected_categories=list(expected),
        start_date=start_date,
        end_date=end_date,
        required_rate=required_rate,
        check_links=check_links,
        link_limit=link_limit,
        link_delay=link_delay,
    )
    base = output_dir or ((target if target.is_dir() else target.parent) / "reports")
    write_report(base / "validation.json", base / "validation.html", "Bid crawler validation", report)
    return report, base
