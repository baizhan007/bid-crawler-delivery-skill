from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bidfactory.mocksite import running_mock_site


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-B", "-m", "bidfactory", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == expected, result.stdout + "\n" + result.stderr
    return result


def _adapter(base_url: str) -> str:
    return f'''def parse_fixture(bundle):
    details = {{}}
    for response in bundle:
        if response.context.get("role") == "detail":
            details[response.id.replace("detail-", "")] = response.json()
    records = []
    for response in bundle:
        if response.context.get("role") != "list":
            continue
        for row in response.json().get("rows", []):
            published = row.get("publish_time", "")
            if not published.startswith("2026-"):
                continue
            detail = details[row["id"]]
            content = detail.get("content", "")
            records.append({{
                "webname": "演示采购网",
                "href": "{base_url}/notice/" + row["id"],
                "title": row["title"],
                "publish_time": published,
                "category": row["category"],
                "msg": row["title"] + "正文",
                "html": content,
                "raw_id": row["id"],
            }})
    return records
'''


def _config(base_url: str, version: str) -> dict:
    requests = []
    for board, category in (("purchase", "采购公告"), ("result", "结果公告")):
        for page in (1, 2):
            requests.append({
                "id": f"list-{board}-{page}", "role": "list", "category": category, "page": page,
                "url": f"/api/notices?category={board}&page={page}&version={version}", "response_type": "json",
            })
    for raw_id, category in (("p-100", "采购公告"), ("p-099", "采购公告"), ("r-200", "结果公告"), ("r-199", "结果公告")):
        requests.append({
            "id": f"detail-{raw_id}", "role": "detail", "category": category,
            "url": f"/api/detail?id={raw_id}&version={version}", "response_type": "json",
        })
    requests.append({
        "id": "detail-html", "role": "detail-html", "category": "采购公告",
        "url": "/notice/p-100", "response_type": "html",
    })
    return {
        "schema_version": 1,
        "site_name": "演示采购网",
        "base_url": base_url,
        "allowed_hosts": ["127.0.0.1"],
        "adapter": "adapter.py",
        "expected_categories": ["采购公告", "结果公告"],
        "dom_selectors": {".notice-content": {"min": 1}},
        "requests": requests,
    }


def test_full_cli_mock_site_workflow(tmp_path: Path) -> None:
    for command in ("new", "capture", "replay", "validate", "diff", "package", "doctor"):
        _run(command, "--help")

    _run("new", "演示采购网", "--root", str(tmp_path))
    project = tmp_path / "演示采购网"
    generated_source = (project / "src" / "演示采购网_爬虫.py").read_text(encoding="utf-8")
    assert 'WEBNAME = \'演示采购网\'' in generated_source
    assert "example_site" not in generated_source

    with running_mock_site() as base_url:
        (project / "adapter.py").write_text(_adapter(base_url), encoding="utf-8")
        config = project / "site_config.json"
        config.write_text(json.dumps(_config(base_url, "v1"), ensure_ascii=False, indent=2), encoding="utf-8")
        fixture_v1 = project / "fixtures" / "v1"
        _run("capture", str(config), "--output", str(fixture_v1))
        records = project / "artifacts" / "records.json"
        _run("replay", str(fixture_v1), "--output", str(records))
        _run("validate", str(records), "--output", str(project / "reports"))

        config.write_text(json.dumps(_config(base_url, "v2"), ensure_ascii=False, indent=2), encoding="utf-8")
        fixture_v2 = project / "fixtures" / "v2"
        _run("capture", str(config), "--output", str(fixture_v2))

    diff = _run("diff", str(fixture_v1), str(fixture_v2), "--output", str(project / "diff-report"), expected=1)
    assert "差异报告" in diff.stdout
    diff_report = json.loads((project / "diff-report" / "diff.json").read_text(encoding="utf-8"))
    assert diff_report["breaking"] is True
    assert diff_report["removed_json_paths"]

    package_root = tmp_path / "deliveries"
    _run("package", str(project), "--output", str(package_root))
    assert (package_root / "演示采购网_交付.zip").exists()
    assert (package_root / "演示采购网_交付_manifest.json").exists()
    assert (package_root / "演示采购网_交付" / "演示采购网" / "完整源码" / "演示采购网_爬虫.py").exists()
    _run("doctor", "--workdir", str(project), "--json")
