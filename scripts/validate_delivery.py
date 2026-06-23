from __future__ import annotations

import argparse
import csv
import json
import py_compile
from pathlib import Path


REQUIRED_DIRS = ["完整源码", "部署文档", "配置说明", "字段映射表", "采集结果", "验收报告"]
FORBIDDEN_NAMES = {".idea", ".vscode", "__pycache__", ".pytest_cache", "bid_spider"}
DATABASE_SCRIPT_SUFFIXES = {"." + "s" + "ql"}
REQUIRED_CSV_FIELDS = ["webname", "href", "title", "publish_time", "msg", "html"]


def fail(message: str, failures: list[str]) -> None:
    """记录一个验收失败项。"""

    failures.append(message)


def validate(root: Path) -> list[str]:
    """检查交付目录是否符合独立项目交付规范。"""

    failures: list[str] = []
    if not root.exists():
        return [f"交付根目录不存在：{root}"]

    for path in root.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            fail(f"发现不应交付的目录或文件：{path}", failures)
        if path.is_file() and path.suffix.lower() in DATABASE_SCRIPT_SUFFIXES:
            fail(f"发现不在标准交付清单中的数据库脚本：{path}", failures)

    site_dirs = [p for p in root.iterdir() if p.is_dir()]
    if not site_dirs:
        fail("交付根目录下没有网站项目目录", failures)

    for site in site_dirs:
        for name in REQUIRED_DIRS:
            if not (site / name).is_dir():
                fail(f"{site.name} 缺少文件夹：{name}", failures)

        source_files = list((site / "完整源码").glob("*_爬虫.py")) if (site / "完整源码").exists() else []
        if len(source_files) != 1:
            fail(f"{site.name} 的完整源码中应有且只有一个 *_爬虫.py，实际 {len(source_files)} 个", failures)
        for script in source_files:
            try:
                py_compile.compile(str(script), doraise=True)
            except Exception as exc:
                fail(f"{script} 语法检查失败：{exc}", failures)
            text = script.read_text(encoding="utf-8")
            if '"""' not in text or "采集" not in text:
                fail(f"{script} 看起来缺少中文 docstring 或中文注释", failures)

        req = site / "完整源码" / "requirements.txt"
        if not req.exists():
            fail(f"{site.name} 缺少 requirements.txt", failures)
        elif ("py" + "my" + "s" + "ql") in req.read_text(encoding="utf-8").lower():
            fail(f"{site.name} 包含数据库写入依赖，请确认是否属于本次交付范围", failures)

        csv_files = list((site / "采集结果").glob("*.csv")) if (site / "采集结果").exists() else []
        if len(csv_files) != 1:
            fail(f"{site.name} 的采集结果中应有且只有一个 CSV，实际 {len(csv_files)} 个", failures)
        for csv_file in csv_files:
            with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                missing = [field for field in REQUIRED_CSV_FIELDS if field not in (reader.fieldnames or [])]
                if missing:
                    fail(f"{csv_file} 缺少字段：{', '.join(missing)}", failures)
                rows = list(reader)
                if not rows:
                    fail(f"{csv_file} 没有数据行", failures)
                duplicates = len(rows) - len({(row.get("webname"), row.get("href")) for row in rows})
                if duplicates:
                    fail(f"{csv_file} 存在重复 webname+href：{duplicates} 条", failures)

        report = site / "验收报告" / "acceptance_report.json"
        if not report.exists():
            fail(f"{site.name} 缺少 acceptance_report.json", failures)
        else:
            data = json.loads(report.read_text(encoding="utf-8-sig"))
            if data.get("quality_flags", {}).get("overall_pass") is not True:
                fail(f"{site.name} 验收报告 overall_pass 不是 true", failures)

    return failures


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="检查招投标爬虫交付目录")
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
