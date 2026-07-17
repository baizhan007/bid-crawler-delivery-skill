from __future__ import annotations

import argparse
import csv
import json
import runpy
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "single_site_crawler_template.py"
SCAFFOLD = ROOT / "scripts" / "scaffold_site_project.py"
VALIDATOR = ROOT / "scripts" / "validate_delivery.py"


def load(path: Path) -> dict:
    """以非 main 模式加载单文件脚本。"""

    return runpy.run_path(str(path))


def report_args() -> argparse.Namespace:
    """构造验收报告所需的最小命令参数。"""

    return argparse.Namespace(
        db_table="a_bidcollect_info",
        to_db=False,
        sample_csv="",
        sample_dir="",
        sample_size=20,
    )


def make_record(ns: dict, raw_id: str, category: str = "采购公告", href: str | None = None):
    """创建字段完整的测试公告。"""

    return ns["BidRecord"](
        webname="测试采购网",
        href=href or f"https://example.com/detail/{raw_id}",
        title=f"公告 {raw_id}",
        publish_time="2026-07-17",
        msg="正文",
        html="<p>正文</p>",
        category=category,
        raw_id=raw_id,
    )


def test_build_report_computes_href_and_date_metrics() -> None:
    """报告必须自行计算 href_bad，不能依赖悬空变量。"""

    ns = load(TEMPLATE)
    good = make_record(ns, "good")
    report = ns["build_report"](
        [good],
        [{"source": "采购公告", "expected": 1, "fetched": 1}],
        "2026-07-01",
        "2026-07-31",
        report_args(),
    )
    assert report["href_quality"]["bad_samples"] == []
    assert report["date_quality"]["bad_count"] == 0
    assert report["quality_flags"]["overall_pass"] is True

    bad = make_record(ns, "bad", href="javascript:alert(1)")
    bad_report = ns["build_report"](
        [bad],
        [{"source": "采购公告", "expected": 1, "fetched": 1}],
        "2026-07-01",
        "2026-07-31",
        report_args(),
    )
    assert bad_report["quality_flags"]["links_traceable"] is False
    assert bad_report["quality_flags"]["overall_pass"] is False


def test_html_sanitizer_preserves_tables_and_removes_active_content() -> None:
    """正文 HTML 只保留安全表格结构。"""

    ns = load(TEMPLATE)
    source = (
        "<script>alert(1)</script>"
        "<table onclick='evil()'><tr><td colspan='2' background='javascript:evil()'>ok</td></tr></table>"
        "&lt;img src=x onerror=evil()&gt;"
    )
    cleaned = ns["keep_table_html"](source)
    assert "alert(1)" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "<table>" in cleaned
    assert '<td colspan="2">ok</td>' in cleaned
    assert "&lt;img" in cleaned
    assert "<img" not in cleaned


@pytest.mark.parametrize("value", ["bad-name", "a` DROP TABLE x", "db.table", "1table", ""])
def test_mysql_table_identifier_rejects_unsafe_values(value: str) -> None:
    """任意表名不能进入 SQL 标识符。"""

    ns = load(TEMPLATE)
    with pytest.raises(ValueError):
        ns["validate_mysql_identifier"](value)
    assert ns["validate_mysql_identifier"]("a_bidcollect_info") == "a_bidcollect_info"


def test_incremental_boundary_is_per_category() -> None:
    """栏目 A 到达旧边界后必须继续采集栏目 B。"""

    ns = load(TEMPLATE)
    base = ns["ExampleBidSpider"]

    class FakeState:
        def is_seen(self, record) -> bool:
            return record.raw_id in {"a1", "a2"}

    class FakeSpider(base):
        def sources(self):
            return [{"name": "栏目A"}, {"name": "栏目B"}]

        def fetch_page(self, source, page):
            ids = ["a1", "a2", "a3"] if source["name"] == "栏目A" else ["b1"]
            return ([{"id": value, "publishTime": "2026-07-17"} for value in ids], 1)

        def fetch_detail(self, item, source):
            return make_record(ns, item["id"], category=source["name"])

    spider = FakeSpider()
    records = list(
        spider.crawl(
            date(2026, 7, 1),
            date(2026, 7, 31),
            state=FakeState(),
            incremental_stop_seen=2,
        )
    )
    assert [record.raw_id for record in records] == ["b1"]
    assert [stat["source"] for stat in spider.stats] == ["栏目A", "栏目B"]
    assert spider.stats[0]["incremental_boundary_reached"] is True


def test_incremental_seen_counter_resets_after_new_record() -> None:
    """非连续旧记录之间出现新记录时必须重置计数。"""

    ns = load(TEMPLATE)
    base = ns["ExampleBidSpider"]

    class FakeState:
        def is_seen(self, record) -> bool:
            return record.raw_id in {"old1", "old2"}

    class FakeSpider(base):
        def sources(self):
            return [{"name": "栏目A"}]

        def fetch_page(self, source, page):
            ids = ["old1", "new1", "old2", "new2"]
            return ([{"id": value, "publishTime": "2026-07-17"} for value in ids], 1)

        def fetch_detail(self, item, source):
            return make_record(ns, item["id"], category=source["name"])

    spider = FakeSpider()
    records = list(
        spider.crawl(
            date(2026, 7, 1),
            date(2026, 7, 31),
            state=FakeState(),
            incremental_stop_seen=2,
        )
    )
    assert [record.raw_id for record in records] == ["new1", "new2"]
    assert "incremental_boundary_reached" not in spider.stats[0]


def scaffold_delivery(tmp_path: Path) -> tuple[Path, Path, dict]:
    """生成一套可通过严格验收的最小交付目录。"""

    scaffold_ns = load(SCAFFOLD)
    delivery = tmp_path / "delivery"
    scaffold_ns["scaffold"](delivery, "测试采购网", TEMPLATE)
    site = delivery / "测试采购网"
    script = site / "完整源码" / "测试采购网_爬虫.py"
    crawler_ns = load(script)
    record = make_record(crawler_ns, "sample")
    sample_file = site / "验收样例" / "sample_records.csv"
    crawler_ns["write_sample_csv"](sample_file, [record], 20)
    report = crawler_ns["build_report"](
        [record],
        [{"source": "采购公告", "expected": 1, "fetched": 1}],
        "2026-07-01",
        "2026-07-31",
        report_args(),
    )
    report_file = site / "验收报告" / "acceptance_report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    return delivery, site, report


def test_scaffold_customizes_site_and_refuses_overwrite(tmp_path: Path) -> None:
    """脚手架必须替换站点常量，且不得覆盖已有项目。"""

    scaffold_ns = load(SCAFFOLD)
    delivery = tmp_path / "delivery"
    scaffold_ns["scaffold"](delivery, "测试采购网", TEMPLATE)
    script = delivery / "测试采购网" / "完整源码" / "测试采购网_爬虫.py"
    text = script.read_text(encoding="utf-8")
    assert 'WEBNAME = "测试采购网"' in text
    assert 'SITE_KEY = "example_site"' not in text
    assert (delivery / "交付结构说明.md").is_file()
    assert (delivery / "测试采购网" / "字段映射表" / "field_mapping.csv").is_file()
    assert "--field-mapping-file" in text
    assert 'default="验收输出"' not in text
    with pytest.raises(FileExistsError):
        scaffold_ns["scaffold"](delivery, "测试采购网", TEMPLATE)
    with pytest.raises(ValueError):
        scaffold_ns["scaffold"](delivery, "../越界", TEMPLATE)


def test_validator_recomputes_metrics_and_creates_no_cache(tmp_path: Path) -> None:
    """验收器必须重算指标，且语法检查不能污染源码目录。"""

    delivery, site, report = scaffold_delivery(tmp_path)
    validator_ns = load(VALIDATOR)
    assert validator_ns["validate"](delivery) == []
    assert not (site / "完整源码" / "__pycache__").exists()

    report["required_non_empty_rate"]["msg"] = 0.0
    report["quality_flags"]["required_fields_ge_99_5_percent"] = True
    report["quality_flags"]["overall_pass"] = True
    (site / "验收报告" / "acceptance_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    failures = validator_ns["validate"](delivery)
    assert any("required_fields_ge_99_5_percent" in failure for failure in failures)


def test_validator_rejects_any_extra_source_item(tmp_path: Path) -> None:
    """完整源码必须严格只有爬虫单文件和 requirements.txt。"""

    delivery, site, _ = scaffold_delivery(tmp_path)
    (site / "完整源码" / "notes.txt").write_text("extra", encoding="utf-8")
    failures = load(VALIDATOR)["validate"](delivery)
    assert any("额外交付项" in failure and "notes.txt" in failure for failure in failures)
