"""Small deterministic file helpers shared by the factory commands."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .errors import FactoryError


def load_json(path: Path) -> Any:
    """Read a UTF-8 JSON document with a useful path in failures."""

    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise FactoryError(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FactoryError(f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}") from exc


def write_json(path: Path, value: Any) -> None:
    """Write stable, human-readable UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_filename(value: str, fallback: str = "site") -> str:
    """Return a cross-platform filename without changing display labels."""

    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._")
    return text or fallback


def ensure_within(path: Path, root: Path) -> Path:
    """Resolve a path and reject traversal outside the expected root."""

    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise FactoryError(f"Path escapes the allowed root: {path}")
    return resolved


def compile_source(path: Path) -> None:
    """Syntax-check Python without creating ``__pycache__`` files."""

    try:
        compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
    except (OSError, SyntaxError) as exc:
        raise FactoryError(f"Python syntax check failed for {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    """Calculate a file checksum without loading the whole file in memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path) -> Iterable[Path]:
    """Yield files in deterministic relative-path order."""

    yield from sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.relative_to(root).as_posix())
