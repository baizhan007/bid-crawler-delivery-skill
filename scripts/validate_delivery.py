from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REQUIRED_DIRS = ["完整源码", "部署文档", "配置说明", "字段映射表", "验收报告"]
FORBIDDEN_NAMES = {".idea", ".vscode", "__pycache__", ".pytest_cache", "bid_spider"}
FORBIDDEN_FILE_PATTERNS = [r"批量", r"转换", r"临时", r"debug", r"demo", r"test", r"helper"]
REQUIRED_SAMPLE_FIELDS = ["webname", "href", "title", "publish_time", "msg", "html"]
REQUIRED_RECORD_FIELDS = ["webname", "href", "msg", "html", "publish_time"]
REQUIRED_DB_ARGS = ["--to-db", "--db-host", "--db-port", "--db-user", "--db-password", "--db-name", "--db-table", "--db-skip-existing"]
REQUIRED_DB_FIELDS = [
    "webname",
    "href",
    "msg",
    "html",
    "publish_time",
    "industry",
    "from_auto_script",
    "identify_code",
    "etl_flag",
]
MYSQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def fail(message: str, failures: list[str]) -> None:
    """记录一个验收失败项。"""

    failures.append(message)


def has_forbidden_file_name(path: Path) -> bool:
    """判断文件名是否像临时或辅助文件。"""

    return any(re.search(pattern, path.name, flags=re.I) for pattern in FORBIDDEN_FILE_PATTERNS)


def is_http_url(value: Any) -> bool:
    """判断值是否为带主机名的完整 HTTP/HTTPS URL。"""

    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def parse_iso_date(value: Any) -> datetime | None:
    """严格解析 YYYY-MM-DD 日期。"""

    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d")
    except ValueError:
        return None


def as_int(value: Any, label: str, failures: list[str]) -> int | None:
    """把报告指标转换为非负整数。"""

    if isinstance(value, bool):
        fail(f"{label} 应为非负整数", failures)
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        fail(f"{label} 应为非负整数", failures)
        return None
    if result < 0:
        fail(f"{label} 应为非负整数", failures)
        return None
    return result


def as_rate(value: Any, label: str, failures: list[str]) -> float | None:
    """把报告指标转换为 0 到 1 的比例。"""

    if isinstance(value, bool):
        fail(f"{label} 应为 0 到 1 的数值", failures)
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        fail(f"{label} 应为 0 到 1 的数值", failures)
        return None
    if not 0 <= result <= 1:
        fail(f"{label} 应为 0 到 1 的数值", failures)
        return None
    return result


def validate_sample_csv(csv_file: Path, failures: list[str]) -> list[dict[str, str]]:
    """检查样本 CSV 字段、必填值、日期和 href，并返回数据行。"""

    try:
        with csv_file.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            missing = [field for field in REQUIRED_SAMPLE_FIELDS if field not in (reader.fieldnames or [])]
            if missing:
                fail(f"{csv_file} 缺少字段：{', '.join(missing)}", failures)
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        fail(f"{csv_file} 无法读取：{exc}", failures)
        return []

    if not rows:
        fail(f"{csv_file} 没有样本数据行", failures)
        return []
    for field in REQUIRED_RECORD_FIELDS:
        empty_count = sum(not str(row.get(field, "")).strip() for row in rows)
        rate = (len(rows) - empty_count) / len(rows)
        if rate < 0.995:
            fail(f"{csv_file} 必填字段 {field} 完整率 {rate:.4f} 低于 0.995", failures)
    duplicates = len(rows) - len({(row.get("webname"), row.get("href")) for row in rows})
    if duplicates:
        fail(f"{csv_file} 存在重复 webname+href：{duplicates} 条", failures)
    bad_href = [row.get("href", "") for row in rows if not is_http_url(row.get("href"))]
    if bad_href:
        fail(f"{csv_file} 存在无效 http/https href：{bad_href[:3]}", failures)
    bad_dates = [row.get("publish_time", "") for row in rows if parse_iso_date(row.get("publish_time")) is None]
    if bad_dates:
        fail(f"{csv_file} 存在非 YYYY-MM-DD 日期：{bad_dates[:3]}", failures)
    return rows


def validate_report(
    report_file: Path,
    sample_rows: list[dict[str, str]],
    failures: list[str],
    site_name: str,
) -> None:
    """从报告数值和样本重新推导质量标志，拒绝仅声明 true 的报告。"""

    try:
        data = json.loads(report_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{site_name} 验收报告无法读取：{exc}", failures)
        return
    if not isinstance(data, dict):
        fail(f"{site_name} 验收报告根节点必须是对象", failures)
        return

    total = as_int(data.get("total_records"), f"{site_name}.total_records", failures)
    duplicates = as_int(data.get("duplicate_records"), f"{site_name}.duplicate_records", failures)
    rates_data = data.get("required_non_empty_rate")
    rates_data = rates_data if isinstance(rates_data, dict) else {}
    rates = {
        field: as_rate(rates_data.get(field), f"{site_name}.required_non_empty_rate.{field}", failures)
        for field in REQUIRED_RECORD_FIELDS
    }

    coverage_ok = True
    coverage = data.get("source_coverage", [])
    if not isinstance(coverage, list):
        fail(f"{site_name}.source_coverage 必须是数组", failures)
        coverage = []
        coverage_ok = False
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            fail(f"{site_name}.source_coverage[{index}] 必须是对象", failures)
            coverage_ok = False
            continue
        expected = as_int(item.get("expected"), f"{site_name}.source_coverage[{index}].expected", failures)
        fetched = as_int(item.get("fetched"), f"{site_name}.source_coverage[{index}].fetched", failures)
        if expected is None or fetched is None:
            coverage_ok = False
            continue
        calculated = fetched >= ceil(expected * 0.985)
        reported_rate = as_rate(item.get("coverage_rate"), f"{site_name}.source_coverage[{index}].coverage_rate", failures)
        calculated_rate = fetched / expected if expected else 1.0
        if reported_rate is not None and abs(reported_rate - round(calculated_rate, 4)) > 0.0001:
            fail(f"{site_name}.source_coverage[{index}] 覆盖率与 expected/fetched 不一致", failures)
        if item.get("passed") is not calculated:
            fail(f"{site_name}.source_coverage[{index}].passed 与重新计算结果不一致", failures)
        coverage_ok = coverage_ok and calculated

    href_quality = data.get("href_quality")
    href_quality = href_quality if isinstance(href_quality, dict) else {}
    href_rate = as_rate(href_quality.get("http_url_rate"), f"{site_name}.href_quality.http_url_rate", failures)
    href_bad = href_quality.get("bad_samples")
    if not isinstance(href_bad, list):
        fail(f"{site_name}.href_quality.bad_samples 必须是数组", failures)
        href_bad = ["invalid"]

    date_quality = data.get("date_quality")
    date_quality = date_quality if isinstance(date_quality, dict) else {}
    date_rate = as_rate(
        date_quality.get("valid_and_in_range_rate"),
        f"{site_name}.date_quality.valid_and_in_range_rate",
        failures,
    )
    bad_date_count = as_int(date_quality.get("bad_count"), f"{site_name}.date_quality.bad_count", failures)

    database = data.get("database")
    database = database if isinstance(database, dict) else {}
    table = str(database.get("db_table") or "")
    database_ok = (
        database.get("database_mode_supported") is True
        and bool(MYSQL_IDENTIFIER_RE.fullmatch(table))
        and database.get("db_unique_key") == "webname + href"
        and database.get("db_write_fields") == REQUIRED_DB_FIELDS
    )
    if not database_ok:
        fail(f"{site_name} 数据库验收指标与 a_bidcollect_info 规范不一致", failures)

    derived_flags = {
        "records_ge_98_5_percent": coverage_ok,
        "required_fields_ge_99_5_percent": bool(total) and all(rate is not None and rate >= 0.995 for rate in rates.values()),
        "no_duplicates": duplicates == 0 if duplicates is not None else False,
        "dates_in_range": bool(total) and date_rate == 1.0 and bad_date_count == 0,
        "links_traceable": bool(total) and href_rate == 1.0 and not href_bad,
        "database_mode_supported": database_ok,
    }
    flags = data.get("quality_flags")
    flags = flags if isinstance(flags, dict) else {}
    for name, expected in derived_flags.items():
        if flags.get(name) is not expected:
            fail(f"{site_name} 验收报告 {name}={flags.get(name)!r}，重新计算应为 {expected}", failures)
    overall = all(derived_flags.values())
    if flags.get("overall_pass") is not overall:
        fail(f"{site_name} 验收报告 overall_pass 与重新计算结果不一致", failures)
    if not overall:
        fail(f"{site_name} 验收报告关键指标未通过", failures)

    if sample_rows:
        sample_keys = [(row.get("webname"), row.get("href")) for row in sample_rows]
        sample_duplicates = len(sample_keys) - len(set(sample_keys))
        if sample_duplicates:
            fail(f"{site_name} 跨样本文件存在重复 webname+href：{sample_duplicates} 条", failures)
        if total is not None and total < len(sample_rows):
            fail(f"{site_name} 报告总数 {total} 小于样本行数 {len(sample_rows)}", failures)
        date_range = data.get("date_range")
        date_range = date_range if isinstance(date_range, dict) else {}
        start = parse_iso_date(date_range.get("start_date"))
        end = parse_iso_date(date_range.get("end_date"))
        if start is None or end is None or start > end:
            fail(f"{site_name} 报告日期范围无效", failures)
        else:
            out_of_range = [
                row.get("publish_time", "")
                for row in sample_rows
                if (parsed := parse_iso_date(row.get("publish_time"))) is not None and not (start <= parsed <= end)
            ]
            if out_of_range:
                fail(f"{site_name} 样本存在超出报告日期范围的记录：{out_of_range[:3]}", failures)


def validate_source(source_dir: Path, site_name: str, failures: list[str]) -> str:
    """严格检查完整源码目录，并以内存编译避免生成 __pycache__。"""

    if not source_dir.exists():
        return ""
    source_files = [path for path in source_dir.iterdir() if path.is_file() and path.match("*_爬虫.py")]
    if len(source_files) != 1:
        fail(f"{site_name} 的完整源码中应有且只有一个 *_爬虫.py，实际 {len(source_files)} 个", failures)
    requirements = source_dir / "requirements.txt"
    allowed = set(source_files[:1]) | {requirements}
    extras = [path for path in source_dir.iterdir() if path not in allowed]
    for path in extras:
        fail(f"{site_name} 的完整源码中存在额外交付项：{path}", failures)

    source_text = ""
    for script in source_files:
        try:
            source_text = script.read_text(encoding="utf-8")
            compile(source_text, str(script), "exec")
            tree = ast.parse(source_text, filename=str(script))
        except (OSError, UnicodeError, SyntaxError) as exc:
            fail(f"{script} 语法检查失败：{exc}", failures)
            continue
        if '"""' not in source_text or "采集" not in source_text:
            fail(f"{script} 看起来缺少中文 docstring 或中文注释", failures)
        missing_args = [arg for arg in REQUIRED_DB_ARGS if arg not in source_text]
        if missing_args:
            fail(f"{script} 缺少入库参数：{', '.join(missing_args)}", failures)
        for node in tree.body:
            if isinstance(node, ast.Import) and any(alias.name == "pymysql" for alias in node.names):
                fail(f"{script} 不应在文件顶部导入 pymysql，应在 --to-db 启用时延迟导入", failures)
            if isinstance(node, ast.ImportFrom) and node.module == "pymysql":
                fail(f"{script} 不应在文件顶部导入 pymysql，应在 --to-db 启用时延迟导入", failures)

    if not requirements.exists():
        fail(f"{site_name} 缺少 requirements.txt", failures)
    else:
        try:
            requirements_text = requirements.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeError) as exc:
            fail(f"{site_name} requirements.txt 无法读取：{exc}", failures)
        else:
            if "pymysql" not in requirements_text:
                fail(f"{site_name} requirements.txt 缺少 pymysql 入库依赖", failures)
    return source_text


def validate(root: Path) -> list[str]:
    """检查交付目录是否符合入库交付规范。"""

    failures: list[str] = []
    if not root.exists():
        return [f"交付根目录不存在：{root}"]
    if not (root / "交付结构说明.md").is_file():
        fail("交付根目录缺少 交付结构说明.md", failures)

    for path in root.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            fail(f"发现不应交付的目录或文件：{path}", failures)
        if path.is_file() and has_forbidden_file_name(path):
            fail(f"发现疑似临时/辅助文件：{path}", failures)

    site_dirs = [path for path in root.iterdir() if path.is_dir()]
    if not site_dirs:
        fail("交付根目录下没有网站项目目录", failures)

    for site in site_dirs:
        for name in REQUIRED_DIRS:
            if not (site / name).is_dir():
                fail(f"{site.name} 缺少文件夹：{name}", failures)
        required_files = [
            site / "部署文档" / "部署文档.md",
            site / "配置说明" / "配置说明.md",
            site / "字段映射表" / "field_mapping.csv",
            site / "字段映射表" / "字段映射说明.md",
        ]
        for required_file in required_files:
            if not required_file.is_file():
                fail(f"{site.name} 缺少文件：{required_file.relative_to(site)}", failures)

        validate_source(site / "完整源码", site.name, failures)

        sample_rows: list[dict[str, str]] = []
        sample_dir = site / "验收样例"
        if sample_dir.exists():
            for csv_file in sample_dir.glob("*.csv"):
                sample_rows.extend(validate_sample_csv(csv_file, failures))

        report_file = site / "验收报告" / "acceptance_report.json"
        if not report_file.exists():
            fail(f"{site.name} 缺少 acceptance_report.json", failures)
        else:
            validate_report(report_file, sample_rows, failures, site.name)

    return failures


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="检查招投标爬虫入库交付目录")
    parser.add_argument("root", help="交付根目录")
    args = parser.parse_args()
    failures = validate(Path(args.root))
    if failures:
        print("检查未通过：")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(1)
    print("检查通过。")


if __name__ == "__main__":
    main()
