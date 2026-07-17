"""Environment diagnostics for repeatable factory runs."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def run_doctor(workdir: Path | None = None) -> dict[str, Any]:
    """Return checks without exposing values from sensitive environment variables."""

    root = (workdir or Path.cwd()).resolve()
    checks = []

    def add(name: str, passed: bool, detail: str, severity: str = "error") -> None:
        checks.append({"name": name, "passed": passed, "severity": severity, "detail": detail})

    add("python_version", sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}; requires 3.10+")
    add("requests", importlib.util.find_spec("requests") is not None, "requests is required for capture")
    add("pytest", importlib.util.find_spec("pytest") is not None, "pytest is needed for development tests", "warning")
    template = Path(__file__).resolve().parents[1] / "templates" / "single_site_crawler_template.py"
    add("crawler_template", template.exists(), str(template))
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="bidfactory-doctor-", dir=root, delete=True):
            pass
        writable = True
    except OSError:
        writable = False
    add("workspace_writable", writable, str(root))
    add("git", shutil.which("git") is not None, "git command available", "warning")
    add("gh", shutil.which("gh") is not None, "GitHub CLI available", "warning")
    sensitive_names = sorted(
        name for name in os.environ
        if any(marker in name.upper() for marker in ("TOKEN", "PASSWORD", "SECRET", "COOKIE", "AUTHORIZATION"))
    )
    add(
        "sensitive_environment",
        not sensitive_names,
        "No sensitive variable names detected" if not sensitive_names else f"Sensitive variables are set (values hidden): {', '.join(sensitive_names)}",
        "warning",
    )
    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    return {"ok": not errors, "checks": checks, "error_count": len(errors), "warning_count": len(warnings)}
