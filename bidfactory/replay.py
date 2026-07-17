"""Strictly offline fixture replay with optional site adapters."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from .errors import FixtureError
from .fixture import FixtureBundle, FixtureResponse, load_bundle
from .io import ensure_within, write_json
from .network_guard import offline_network_guard


def _adapter_definition(bundle: FixtureBundle, override: Path | None) -> tuple[Path, str] | None:
    if override is not None:
        path = override.resolve()
        callable_name = "parse_fixture"
    else:
        configured = bundle.manifest.get("adapter")
        if not configured:
            return None
        if isinstance(configured, str):
            relative_path = configured
            callable_name = "parse_fixture"
        elif isinstance(configured, dict):
            relative_path = configured.get("path")
            callable_name = str(configured.get("callable") or "parse_fixture")
        else:
            raise FixtureError("Fixture adapter must be a path string or object")
        if not isinstance(relative_path, str) or not relative_path:
            raise FixtureError("Fixture adapter path is missing")
        path = ensure_within(bundle.root / relative_path, bundle.root)
    if not path.is_file():
        raise FixtureError(f"Replay adapter does not exist: {path}")
    if path.suffix.lower() != ".py":
        raise FixtureError(f"Replay adapter must be a Python file: {path}")
    if not callable_name.isidentifier():
        raise FixtureError(f"Invalid replay adapter callable: {callable_name!r}")
    return path, callable_name


def _load_adapter(path: Path) -> ModuleType:
    module_name = f"_bidfactory_adapter_{abs(hash((str(path), path.stat().st_mtime_ns)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FixtureError(f"Unable to load replay adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _candidate_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return [dict(item) for item in value]
    if not isinstance(value, Mapping):
        return []
    for key in ("records", "items", "rows", "results", "list"):
        candidate = value.get(key)
        if isinstance(candidate, list) and all(isinstance(item, Mapping) for item in candidate):
            return [dict(item) for item in candidate]
    data = value.get("data")
    if data is not value:
        nested = _candidate_records(data)
        if nested:
            return nested
    record_fields = {"webname", "href", "title", "publish_time", "msg", "html"}
    return [dict(value)] if record_fields.intersection(value) else []


def _generic_replay(responses: Iterable[FixtureResponse]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for response in responses:
        content_type = response.content_type.lower()
        if response.body_path.suffix.lower() != ".json" and "json" not in content_type:
            continue
        records.extend(_candidate_records(response.json()))
    if not records:
        raise FixtureError(
            "No replay adapter is configured and the fixture has no record-like JSON list "
            "under records/items/rows/results/list/data"
        )
    return records


def _normalize_adapter_output(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, Mapping) and "records" in output:
        output = output["records"]
    if isinstance(output, Mapping):
        output = [output]
    if isinstance(output, (str, bytes)) or not isinstance(output, Iterable):
        raise FixtureError("Replay adapter must return an iterable of record mappings")
    rows = list(output)
    bad_indexes = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    if bad_indexes:
        raise FixtureError(f"Replay adapter returned non-object records at indexes: {bad_indexes[:10]}")
    return [dict(row) for row in rows]


def replay_fixture(
    fixture_dir: Path,
    adapter_path: Path | None = None,
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Replay captured responses without allowing any network or subprocess use."""

    bundle = load_bundle(Path(fixture_dir))
    definition = _adapter_definition(bundle, Path(adapter_path) if adapter_path else None)
    with offline_network_guard():
        if definition is None:
            records = _generic_replay(bundle.responses)
        else:
            path, callable_name = definition
            module = _load_adapter(path)
            adapter = getattr(module, callable_name, None)
            if not callable(adapter):
                raise FixtureError(f"Replay adapter {path} has no callable {callable_name}()")
            records = _normalize_adapter_output(adapter(bundle))
    destination = Path(output_path) if output_path else bundle.root / "artifacts" / "records.json"
    write_json(destination, {"schema_version": 1, "records": records})
    return records
