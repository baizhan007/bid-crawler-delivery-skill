from __future__ import annotations

import argparse
import csv
import json
import py_compile
import re
from pathlib import Path


REQUIRED_DIRS = ["完整源码", "部署文档", "配置说明", "字段映射表", "验收报告"]
OPTIONAL_DIRS = ["验收样例"]
FORBIDDEN_NAMES = {".idea", ".vscode", "__pycache__", ".pytest_cache", "bid_spider"}
FORBIDDEN_FILE_PATTERNS = [r"批量", r"转换", r"临时", r"debug", r"demo", r"test", r"helper"]
REQUIRED_SAMPLE_FIELDS = ["webname", "href", "title", "publish_time", "msg", "html"]
REQUIRED_DB_ARGS = ["--to-db", "--db-host", "--db-port", "--db-user", "--db-password", "--db-name", "--db-table", "--db-skip-existing"]


def fail(message: str, failures: list[str]) -> None:
    """记录一个验收失败项。"""

    failures.append(message)


def has_forbidden_file_name(path: Path) -> bool:
    """判断文件名是否像临时或辅助文件。"""

    return any(re.search(pattern, path.name, flags=re.I) for pattern in FORBIDDEN_FILE_PATTERNS)


def validate_sample_csv(csv_file: Path, failures: list[str]) -> None:
    """检查样本 CSV 字段和 href。"""

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [field for field in REQUIRED_SAMPLE_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            fail(f"{csv_file} 缺少字段：{', '.join(missing)}", failures)
        rows = list(reader)
        if not rows:
            fail(f"{csv_file} 没有样本数据行", failures)
        duplicates = len(rows) - len({(row.get("webname"), row.get("href")) for row in rows})
        if duplicates:
            fail(f"{csv_file} 存在重复 webname+href：{duplicates} 条", failures)
        bad_href = [row.get("href", "") for row in rows if not str(row.get("href", "")).lower().startswith(("http://", "https://"))]
        if bad_href:
            fail(f"{csv_file} 存在非 http/https href：{bad_href[:3]}", failures)


def validate(root: Path) -> list[str]:
    """检查交付目录是否符合入库交付规范。"""

    failures: list[str] = []
    if not root.exists():
        return [f"交付根目录不存在：{root}"]

    for path in root.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            fail(f"发现不应交付的目录或文件：{path}", failures)
        if path.is_file() and has_forbidden_file_name(path):
            fail(f"发现疑似临时/辅助文件：{path}", failures)

    site_dirs = [p for p in root.iterdir() if p.is_dir()]
    if not site_dirs:
        fail("交付根目录下没有网站项目目录", failures)

    for site in site_dirs:
        for name in REQUIRED_DIRS:
            if not (site / name).is_dir():
                fail(f"{site.name} 缺少文件夹：{name}", failures)

        source_dir = site / "完整源码"
        source_files = list(source_dir.glob("*_爬虫.py")) if source_dir.exists() else []
        if len(source_files) != 1:
            fail(f"{site.name} 的完整源码中应有且只有一个 *_爬虫.py，实际 {len(source_files)} 个", failures)
        extra_py = [p for p in source_dir.glob("*.py") if p not in source_files] if source_dir.exists() else []
        for script in extra_py:
            fail(f"{site.name} 的完整源码中存在额外 Python 文件：{script}", failures)
        for script in source_files:
            try:
                py_compile.compile(str(script), doraise=True)
            except Exception as exc:
                fail(f"{script} 语法检查失败：{exc}", failures)
            text = script.read_text(encoding="utf-8")
            if '"""' not in text or "采集" not in text:
                fail(f"{script} 看起来缺少中文 docstring 或中文注释", failures)
            missing_args = [arg for arg in REQUIRED_DB_ARGS if arg not in text]
            if missing_args:
                fail(f"{script} 缺少入库参数：{', '.join(missing_args)}", failures)
            if "pymysql" in text and "import pymysql" in text.splitlines()[:30]:
                fail(f"{script} 不应在文件顶部导入 pymysql，应在 --to-db 启用时延迟导入", failures)

        req = source_dir / "requirements.txt"
        if not req.exists():
            fail(f"{site.name} 缺少 requirements.txt", failures)
        else:
            req_text = req.read_text(encoding="utf-8").lower()
            if "pymysql" not in req_text:
                fail(f"{site.name} requirements.txt 缺少 pymysql 入库依赖", failures)

        sample_dir = site / "验收样例"
        if sample_dir.exists():
            for csv_file in sample_dir.glob("*.csv"):
                validate_sample_csv(csv_file, failures)

        report = site / "验收报告" / "acceptance_report.json"
        if not report.exists():
            fail(f"{site.name} 缺少 acceptance_report.json", failures)
        else:
            data = json.loads(report.read_text(encoding="utf-8-sig"))
            flags = data.get("quality_flags", {})
            if flags.get("database_mode_supported") is not True:
                fail(f"{site.name} 验收报告缺少 database_mode_supported=true", failures)
            if flags.get("links_traceable") is not True:
                fail(f"{site.name} 验收报告 links_traceable 不是 true", failures)
            if flags.get("overall_pass") is not True:
                fail(f"{site.name} 验收报告 overall_pass 不是 true", failures)

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
