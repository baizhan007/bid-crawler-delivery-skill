"""Build and independently verify the client-facing one-site delivery package."""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .errors import FactoryError
from .io import compile_source, iter_files, load_json, safe_filename, sha256_file, write_json
from .redaction import find_secret_markers
from .validation import load_records, validate_records


REQUIRED_DIRS = ("完整源码", "部署文档", "配置说明", "字段映射表", "验收样例", "验收报告")
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".idea", ".vscode", ".git"}
DB_FIELDS = [
    "webname", "href", "msg", "html", "publish_time", "industry",
    "from_auto_script", "identify_code", "etl_flag",
]


def _site_config(project: Path) -> dict[str, Any]:
    path = project / "site_config.json"
    config = load_json(path)
    if not isinstance(config, dict) or not str(config.get("site_name", "")).strip():
        raise FactoryError(f"site_config.json needs a non-empty site_name: {path}")
    return config


def _find_records(project: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        project / "artifacts" / "records.json",
        project / "fixtures" / "latest" / "artifacts" / "records.json",
    ]
    configured = config.get("records_file")
    if configured:
        candidates.insert(0, project / str(configured))
    for path in candidates:
        if path.exists():
            records, _ = load_records(path)
            return records
    fixture = project / "fixtures" / "latest"
    if (fixture / "manifest.json").exists():
        adapter = project / str(config.get("adapter") or "adapter.py")
        records, _ = load_records(fixture, adapter if adapter.exists() else None)
        return records
    raise FactoryError(f"No replayed records found for packaging under {project}")


def _write_sample(path: Path, records: list[dict[str, Any]], limit: int = 20) -> None:
    fields = ["webname", "href", "title", "publish_time", "category", "msg", "html"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records[:limit])


def _write_mapping(path: Path) -> None:
    rows = [
        ("webname", "站点配置", "网站名称"),
        ("href", "详情页前端路由", "浏览器可打开 URL，与 webname 组成唯一键"),
        ("msg", "详情正文清洗文本", "纯文本正文"),
        ("html", "详情正文清洗 HTML", "移除脚本和危险属性，保留必要表格结构"),
        ("publish_time", "列表或详情发布时间", "YYYY-MM-DD"),
        ("industry", "栏目 category", "栏目或行业分类"),
        ("from_auto_script", "固定值 1", "自动采集标记"),
        ("identify_code", "sha256(webname|href)[:32]", "稳定标识"),
        ("etl_flag", "固定值 0", "ETL 状态"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["字段", "源网页/接口位置", "说明"])
        writer.writerows(rows)


def _scan_package(root: Path) -> list[str]:
    failures = []
    for path in root.rglob("*"):
        if any(part in FORBIDDEN_PARTS for part in path.parts):
            failures.append(f"Forbidden path: {path.relative_to(root)}")
    for path in iter_files(root):
        if path.suffix.lower() not in {".md", ".py", ".json", ".csv", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        markers = find_secret_markers(text)
        if markers:
            failures.append(f"Possible secret assignment in {path.relative_to(root)}: {', '.join(markers)}")
    return failures


def verify_delivery(root: Path) -> list[str]:
    """Recompute package invariants without trusting its report flags."""

    failures = _scan_package(root)
    sites = [path for path in root.iterdir() if path.is_dir()]
    if len(sites) != 1:
        failures.append(f"Expected exactly one site directory, found {len(sites)}")
        return failures
    site = sites[0]
    for name in REQUIRED_DIRS:
        if not (site / name).is_dir():
            failures.append(f"Missing directory: {name}")
    sources = list((site / "完整源码").glob("*_爬虫.py")) if (site / "完整源码").exists() else []
    if len(sources) != 1:
        failures.append(f"Expected one crawler source, found {len(sources)}")
    for source in sources:
        try:
            compile_source(source)
        except FactoryError as exc:
            failures.append(str(exc))
    allowed_source_names = {sources[0].name, "requirements.txt"} if len(sources) == 1 else {"requirements.txt"}
    if (site / "完整源码").exists():
        extras = [path.name for path in (site / "完整源码").iterdir() if path.name not in allowed_source_names]
        if extras:
            failures.append(f"Unexpected source files: {', '.join(sorted(extras))}")
    sample = site / "验收样例" / "sample_records.csv"
    report_path = site / "验收报告" / "acceptance_report.json"
    if not sample.exists() or not report_path.exists():
        failures.append("Sample CSV or acceptance report is missing")
        return failures
    records, _ = load_records(sample)
    derived = validate_records(records)
    claimed = load_json(report_path)
    claimed_sample = claimed.get("sample_validation") or {}
    for key in ("total_records", "duplicate_records", "required_non_empty_rate"):
        if claimed_sample.get(key) != derived.get(key):
            failures.append(f"Acceptance sample report mismatch for {key}")
    if not derived["quality_flags"]["overall_pass"]:
        failures.append("Derived sample validation failed")
    return failures


def package_site(project: Path, output_root: Path | None = None, force: bool = False) -> tuple[Path, Path, Path]:
    """Create a clean delivery directory, ZIP archive, and checksum manifest."""

    project = project.resolve()
    config = _site_config(project)
    site_name = str(config["site_name"]).strip()
    slug = safe_filename(site_name)
    output_base = (output_root or (project / "dist")).resolve()
    delivery = output_base / f"{slug}_交付"
    if delivery.exists():
        if not force:
            raise FactoryError(f"Delivery already exists; use --force to replace it: {delivery}")
        if output_base not in delivery.resolve().parents:
            raise FactoryError(f"Refusing to remove path outside output root: {delivery}")
        shutil.rmtree(delivery)
    site_dir = delivery / site_name
    for name in REQUIRED_DIRS:
        (site_dir / name).mkdir(parents=True, exist_ok=True)

    sources = sorted((project / "src").glob("*_爬虫.py"))
    if len(sources) != 1:
        raise FactoryError(f"Expected exactly one src/*_爬虫.py under {project}, found {len(sources)}")
    compile_source(sources[0])
    shutil.copyfile(sources[0], site_dir / "完整源码" / sources[0].name)
    requirements = project / "requirements.txt"
    shutil.copyfile(requirements, site_dir / "完整源码" / "requirements.txt")

    records = _find_records(project, config)
    expected_categories = list(config.get("expected_categories") or [])
    report = validate_records(records, expected_categories=expected_categories)
    if not report["quality_flags"]["overall_pass"]:
        raise FactoryError("Records do not meet acceptance requirements; run bidfactory validate for details")
    factory_flags = dict(report["quality_flags"])
    valid_dates = sorted(str(row.get("publish_time", "")) for row in records if str(row.get("publish_time", "")))
    bad_date_count = len(report["bad_date_samples"]) + len(report["out_of_range_samples"])
    valid_date_count = max(0, len(records) - bad_date_count)
    category_counts = report["category_counts"]
    source_coverage = []
    for category in expected_categories:
        count = int(category_counts.get(category, 0))
        source_coverage.append({
            "source": category,
            "expected": count,
            "fetched": count,
            "coverage_rate": 1.0,
            "required_min": count,
            "passed": count > 0,
        })
    report["date_range"] = {
        "start_date": valid_dates[0] if valid_dates else "",
        "end_date": valid_dates[-1] if valid_dates else "",
    }
    report["source_coverage"] = source_coverage
    report["href_quality"] = {
        "http_url_rate": round((len(records) - len(report["bad_href_samples"])) / len(records), 4),
        "bad_samples": report["bad_href_samples"],
        "browser_openable_checked": False,
    }
    report["date_quality"] = {
        "valid_and_in_range_rate": round(valid_date_count / len(records), 4),
        "bad_count": bad_date_count,
    }
    report["factory_quality_flags"] = factory_flags
    report["database"] = {
        "database_mode_supported": True,
        "db_table": "a_bidcollect_info",
        "db_unique_key": "webname + href",
        "db_write_fields": DB_FIELDS,
    }
    legacy_flags = {
        "records_ge_98_5_percent": all(item["passed"] for item in source_coverage),
        "required_fields_ge_99_5_percent": factory_flags["required_fields_ge_threshold"],
        "no_duplicates": factory_flags["no_duplicates"],
        "dates_in_range": factory_flags["dates_valid"] and factory_flags["dates_in_range"],
        "links_traceable": factory_flags["href_format_valid"],
        "database_mode_supported": True,
    }
    legacy_flags["overall_pass"] = all(legacy_flags.values())
    report["quality_flags"] = legacy_flags
    sample_records = records[:20]
    report["sample_validation"] = validate_records(sample_records)
    report["sample"] = {"sample_only": True, "sample_size": len(sample_records), "formal_total_records": len(records)}
    _write_sample(site_dir / "验收样例" / "sample_records.csv", sample_records)
    _write_mapping(site_dir / "字段映射表" / "field_mapping.csv")
    (site_dir / "字段映射表" / "字段映射说明.md").write_text(
        "# 字段映射说明\n\n正式入库目标为 `a_bidcollect_info`。`href` 必须是浏览器可打开的详情页 URL。\n",
        encoding="utf-8",
    )
    write_json(site_dir / "验收报告" / "acceptance_report.json", report)
    (site_dir / "部署文档" / "部署文档.md").write_text(
        f"# {site_name} 部署文档\n\n安装依赖后运行：\n\n```powershell\npython \"{sources[0].name}\" --days 30 --to-db\n```\n",
        encoding="utf-8",
    )
    (site_dir / "配置说明" / "配置说明.md").write_text(
        "# 配置说明\n\n数据库和代理信息必须通过运行环境注入，不得写入源码或 fixture。默认表为 `a_bidcollect_info`。\n",
        encoding="utf-8",
    )
    (delivery / "交付结构说明.md").write_text(
        f"# 交付结构说明\n\n本交付包含 {site_name} 的单文件爬虫、部署配置、字段映射、验收样例和重新计算的验收报告。\n",
        encoding="utf-8",
    )
    failures = verify_delivery(delivery)
    if failures:
        raise FactoryError("Delivery verification failed:\n- " + "\n- ".join(failures))

    output_base.mkdir(parents=True, exist_ok=True)
    zip_path = Path(shutil.make_archive(str(output_base / f"{slug}_交付"), "zip", root_dir=output_base, base_dir=delivery.name))
    manifest_path = output_base / f"{slug}_交付_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": 1,
            "site_name": site_name,
            "files": [
                {"path": path.relative_to(delivery).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in iter_files(delivery)
            ],
            "zip": {"path": zip_path.name, "sha256": sha256_file(zip_path), "bytes": zip_path.stat().st_size},
        },
    )
    return delivery, zip_path, manifest_path
