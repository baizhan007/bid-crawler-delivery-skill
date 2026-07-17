"""Fixture schema and lightweight DOM selector change detection."""

from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .errors import FactoryError
from .io import load_json
from .reports import write_report


def _walk_schema(value: Any, path: str = "$") -> dict[str, str]:
    kind = "null" if value is None else type(value).__name__
    result = {path: kind}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(_walk_schema(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for item in value[:20]:
            result.update(_walk_schema(item, f"{path}[]"))
    return result


class _ElementCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag.lower(), {key.lower(): value or "" for key, value in attrs}))


def _matches(tag: str, attrs: dict[str, str], selector: str) -> bool:
    selector = selector.strip()
    attr_match = re.fullmatch(r"(?:([\w-]+))?\[([\w-]+)(?:=['\"]?([^'\"]+)['\"]?)?\]", selector)
    if attr_match:
        expected_tag, key, value = attr_match.groups()
        return (not expected_tag or tag == expected_tag.lower()) and key.lower() in attrs and (value is None or attrs[key.lower()] == value)
    id_match = re.fullmatch(r"(?:([\w-]+))?#([\w-]+)", selector)
    if id_match:
        expected_tag, value = id_match.groups()
        return (not expected_tag or tag == expected_tag.lower()) and attrs.get("id") == value
    class_match = re.fullmatch(r"(?:([\w-]+))?\.([\w-]+)", selector)
    if class_match:
        expected_tag, value = class_match.groups()
        classes = set(attrs.get("class", "").split())
        return (not expected_tag or tag == expected_tag.lower()) and value in classes
    return tag == selector.lower()


def _selector_counts(html_texts: list[str], selectors: dict[str, Any]) -> dict[str, int]:
    elements = []
    for text in html_texts:
        parser = _ElementCounter()
        parser.feed(text)
        elements.extend(parser.elements)
    return {
        selector: sum(1 for tag, attrs in elements if _matches(tag, attrs, selector))
        for selector in selectors
    }


def _load_fixture_shape(root: Path) -> tuple[dict[str, str], dict[str, int], dict[str, Any]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FactoryError(f"Fixture manifest not found: {manifest_path}")
    manifest = load_json(manifest_path)
    requests = manifest.get("requests") or manifest.get("entries") or []
    schema: dict[str, str] = {}
    html_texts: list[str] = []
    for index, entry in enumerate(requests):
        body_file = entry.get("body_file")
        if not body_file:
            continue
        path = (root / body_file).resolve()
        if root.resolve() not in path.parents:
            raise FactoryError(f"Body path escapes fixture: {body_file}")
        content_type = str(entry.get("content_type", "")).lower()
        if path.suffix.lower() == ".json" or "json" in content_type:
            value = load_json(path)
            for key, kind in _walk_schema(value, f"requests[{index}]").items():
                schema[key] = kind
        else:
            html_texts.append(path.read_text(encoding="utf-8-sig"))
    selectors = manifest.get("dom_selectors") or {}
    if isinstance(selectors, list):
        selectors = {selector: 1 for selector in selectors}
    counts = _selector_counts(html_texts, selectors)
    return schema, counts, selectors


def diff_fixtures(old: Path, new: Path, output_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Compare fixture JSON shapes and configured selector counts."""

    old_schema, old_counts, old_selectors = _load_fixture_shape(old.resolve())
    new_schema, new_counts, new_selectors = _load_fixture_shape(new.resolve())
    removed = sorted(set(old_schema) - set(new_schema))
    added = sorted(set(new_schema) - set(old_schema))
    type_changes = [
        {"path": path, "old": old_schema[path], "new": new_schema[path]}
        for path in sorted(set(old_schema) & set(new_schema))
        if old_schema[path] != new_schema[path]
    ]
    selector_changes = []
    breaking_selectors = []
    selectors = {**old_selectors, **new_selectors}
    for selector, rule in selectors.items():
        minimum = int(rule.get("min", 1)) if isinstance(rule, dict) else int(rule or 1)
        before = old_counts.get(selector, 0)
        after = new_counts.get(selector, 0)
        if before != after:
            item = {"selector": selector, "old": before, "new": after, "minimum": minimum}
            selector_changes.append(item)
            if before >= minimum and after < minimum:
                breaking_selectors.append(item)
    breaking = bool(removed or type_changes or breaking_selectors)
    report = {
        "schema_version": 1,
        "breaking": breaking,
        "removed_json_paths": removed,
        "added_json_paths": added,
        "json_type_changes": type_changes,
        "selector_changes": selector_changes,
        "breaking_selector_changes": breaking_selectors,
        "summary": {
            "removed": len(removed),
            "added": len(added),
            "type_changed": len(type_changes),
            "selector_changed": len(selector_changes),
        },
    }
    base = output_dir or (new / "reports")
    write_report(base / "diff.json", base / "diff.html", "Bid crawler fixture diff", report)
    return report, base
