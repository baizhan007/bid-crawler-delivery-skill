from __future__ import annotations

import json
import runpy
import zipfile
from pathlib import Path

from bidfactory.diffing import diff_fixtures
from bidfactory.doctor import run_doctor
from bidfactory.io import compile_source
from bidfactory.packaging import package_site, verify_delivery
from bidfactory.validation import validate_target


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _record(
    href: str,
    *,
    category: str = "采购公告",
    publish_time: str = "2026-07-17",
) -> dict[str, object]:
    return {
        "webname": "本地模拟采购网",
        "href": href,
        "title": f"公告 {href.rsplit('/', 1)[-1]}",
        "msg": "用于离线验收的公告正文。",
        "html": "<article><p>用于离线验收的公告正文。</p></article>",
        "publish_time": publish_time,
        "category": category,
    }


def _fixture(
    root: Path,
    *,
    payload: object,
    html: str,
    selectors: dict[str, object] | None = None,
) -> None:
    _write_json(root / "bodies" / "list.json", payload)
    (root / "bodies" / "list.html").write_text(html, encoding="utf-8")
    _write_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "requests": [
                {
                    "url": "https://example.test/api/notices",
                    "body_file": "bodies/list.json",
                    "content_type": "application/json",
                },
                {
                    "url": "https://example.test/notices",
                    "body_file": "bodies/list.html",
                    "content_type": "text/html",
                },
            ],
            "dom_selectors": selectors or {"a.notice": {"min": 1}},
        },
    )


def _project(root: Path) -> tuple[Path, list[dict[str, object]]]:
    project = root / "site-project"
    _write_json(
        project / "site_config.json",
        {
            "site_name": "本地模拟采购网",
            "expected_categories": ["采购公告", "结果公告"],
        },
    )
    source = project / "src" / "本地模拟采购网_爬虫.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).resolve().parents[1] / "templates" / "single_site_crawler_template.py"
    source.write_text(template.read_text(encoding="utf-8-sig"), encoding="utf-8")
    (project / "requirements.txt").write_text("requests>=2.31.0\npymysql>=1.1.0\n", encoding="utf-8")
    records = [
        _record("https://example.test/detail/1", category="采购公告"),
        _record("https://example.test/detail/2", category="结果公告"),
    ]
    _write_json(project / "artifacts" / "records.json", {"records": records})
    return project, records


def test_validate_recomputes_metrics_instead_of_trusting_claims(tmp_path: Path) -> None:
    input_path = tmp_path / "records.json"
    _write_json(
        input_path,
        {
            "records": [
                _record("not-a-http-url", publish_time="2026-13-40"),
                _record("not-a-http-url", publish_time="2026-13-40"),
            ],
            "quality_flags": {"overall_pass": True},
            "duplicate_records": 0,
        },
    )

    report, report_dir = validate_target(input_path, output_dir=tmp_path / "reports")

    assert report["duplicate_records"] == 1
    assert len(report["bad_href_samples"]) == 2
    assert len(report["bad_date_samples"]) == 2
    assert report["quality_flags"]["overall_pass"] is False
    assert (report_dir / "validation.json").exists()
    assert (report_dir / "validation.html").exists()


def test_diff_reports_json_and_dom_breaking_changes(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _fixture(
        old,
        payload={"items": [{"id": 1, "title": "采购公告"}]},
        html='<a class="notice" href="/1">公告一</a><a class="notice" href="/2">公告二</a>',
    )
    _fixture(
        new,
        payload={"items": [{"id": "1"}]},
        html="<main>页面结构已变化</main>",
    )

    report, report_dir = diff_fixtures(old, new, output_dir=tmp_path / "diff-report")

    assert report["breaking"] is True
    assert "requests[0].items[].title" in report["removed_json_paths"]
    assert {
        "path": "requests[0].items[].id",
        "old": "int",
        "new": "str",
    } in report["json_type_changes"]
    assert report["breaking_selector_changes"] == [
        {"selector": "a.notice", "old": 2, "new": 0, "minimum": 1}
    ]
    assert (report_dir / "diff.json").exists()
    assert (report_dir / "diff.html").exists()


def test_package_is_clean_and_verifier_rejects_false_report(tmp_path: Path) -> None:
    project, records = _project(tmp_path)
    delivery, zip_path, manifest_path = package_site(project, tmp_path / "dist")

    assert verify_delivery(delivery) == []
    legacy_validator = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "validate_delivery.py"))
    assert legacy_validator["validate"](delivery) == []
    assert zip_path.exists()
    assert manifest_path.exists()
    assert not list(delivery.rglob("__pycache__"))
    assert not list(delivery.rglob("*.pyc"))
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    assert not any(".git/" in name or ".pytest_cache/" in name for name in names)

    site_dir = next(path for path in delivery.iterdir() if path.is_dir())
    report_path = site_dir / "验收报告" / "acceptance_report.json"
    claimed = json.loads(report_path.read_text(encoding="utf-8"))
    assert claimed["total_records"] == len(records)
    claimed["sample_validation"]["total_records"] = 999
    _write_json(report_path, claimed)

    failures = verify_delivery(delivery)

    assert "Acceptance sample report mismatch for total_records" in failures


def test_doctor_hides_sensitive_values_and_keeps_warnings_nonfatal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret_value = "must-not-appear-in-doctor-output"
    monkeypatch.setenv("BIDFACTORY_TEST_TOKEN", secret_value)

    result = run_doctor(tmp_path / "doctor-workspace")
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is True
    assert result["error_count"] == 0
    assert secret_value not in serialized
    sensitive = next(item for item in result["checks"] if item["name"] == "sensitive_environment")
    assert sensitive["passed"] is False
    assert sensitive["severity"] == "warning"
    assert "BIDFACTORY_TEST_TOKEN" in sensitive["detail"]


def test_compile_source_does_not_create_pyc(tmp_path: Path) -> None:
    source = tmp_path / "crawler.py"
    source.write_text("value = 42\n", encoding="utf-8")

    compile_source(source)

    assert not (tmp_path / "__pycache__").exists()
    assert not list(tmp_path.rglob("*.pyc"))
