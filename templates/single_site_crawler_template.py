from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests


SITE_KEY = "example_site"
WEBNAME = "示例招投标网站"
BASE_URL = "https://example.com"

CSV_FIELDS = [
    "webname",
    "href",
    "title",
    "publish_time",
    "category",
    "project_name",
    "project_code",
    "purchaser",
    "supplier",
    "amount",
    "msg",
    "html",
    "raw_id",
    "source_site",
    "extra",
]


@dataclass
class BidRecord:
    """统一标讯记录结构，对应 CSV 输出字段和验收表结构字段。"""

    webname: str
    href: str
    title: str
    publish_time: str
    msg: str
    html: str
    category: str = ""
    project_name: str = ""
    project_code: str = ""
    purchaser: str = ""
    supplier: str = ""
    amount: str = ""
    raw_id: str = ""
    source_site: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def normalize(self) -> "BidRecord":
        """清理空白字符，并把发布时间统一为 YYYY-MM-DD。"""

        self.title = clean_space(self.title)
        self.project_name = clean_space(self.project_name or self.title)
        self.msg = clean_space(self.msg)
        self.publish_time = normalize_date(self.publish_time)
        self.html = keep_table_html(self.html or self.msg or self.title)
        return self

    def to_row(self) -> dict[str, Any]:
        """转换为 CSV 行。"""

        row = asdict(self)
        row["extra"] = json.dumps(self.extra or {}, ensure_ascii=False, sort_keys=True)
        return row


class HttpClient:
    """HTTP 请求客户端，统一处理请求头、代理、请求间隔和 JSON 解析。"""

    def __init__(self, base_url: str = "", headers: dict[str, str] | None = None) -> None:
        """初始化请求会话。"""

        self.base_url = base_url.rstrip("/")
        self.delay = float(os.getenv("BID_SPIDER_DELAY", "0.2"))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Connection": "keep-alive",
            }
        )
        if headers:
            self.session.headers.update(headers)
        proxy = os.getenv("BID_SPIDER_PROXY", "")
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    def url(self, path: str) -> str:
        """把相对地址转换为完整 URL。"""

        if path.startswith(("http://", "https://")):
            return path
        return urljoin(self.base_url + "/", path.lstrip("/")) if self.base_url else path

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """发送请求，并按配置等待，避免过快访问。"""

        if self.delay:
            time.sleep(self.delay)
        response = self.session.request(method, self.url(path), timeout=25, **kwargs)
        response.encoding = response.apparent_encoding or response.encoding
        return response

    def json(self, method: str, path: str, **kwargs: Any) -> Any:
        """发送请求并解析 JSON 响应。"""

        response = self.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        """发送 GET 请求。"""

        return self.request("GET", path, **kwargs)


class CrawlState:
    """保存增量采集断点，用 href、raw_id 和最新发布时间判断是否到达上次位置。"""

    def __init__(self, path: Path) -> None:
        """初始化断点文件路径。"""

        self.path = path
        self.data = self.load()

    def load(self) -> dict:
        """读取断点文件，不存在时返回空状态。"""

        if not self.path.exists():
            return {"sites": {}}
        return json.loads(self.path.read_text(encoding="utf-8-sig"))

    def save(self) -> None:
        """写入断点文件。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def site(self) -> dict:
        """取得当前网站的断点状态。"""

        return self.data.setdefault("sites", {}).setdefault(
            SITE_KEY,
            {"latest_publish_time": "", "seen_hrefs": [], "seen_raw_ids": [], "last_run_at": ""},
        )

    def incremental_start(self, fallback: date) -> date:
        """增量采集从上次最新日期前一天开始，兼顾迟发公告。"""

        latest = self.site().get("latest_publish_time") or ""
        if not latest:
            return fallback
        try:
            return datetime.strptime(latest[:10], "%Y-%m-%d").date() - timedelta(days=1)
        except ValueError:
            return fallback

    def is_seen(self, record: BidRecord) -> bool:
        """判断记录是否已经采集过。"""

        site = self.site()
        hrefs = set(site.get("seen_hrefs") or [])
        raw_ids = set(site.get("seen_raw_ids") or [])
        return bool((record.href and record.href in hrefs) or (record.raw_id and record.raw_id in raw_ids))

    def update(self, records: list[BidRecord]) -> None:
        """把本次成功采集的数据合并到断点状态。"""

        site = self.site()
        hrefs = list(dict.fromkeys((site.get("seen_hrefs") or []) + [r.href for r in records if r.href]))
        raw_ids = list(dict.fromkeys((site.get("seen_raw_ids") or []) + [r.raw_id for r in records if r.raw_id]))
        publish_times = [r.publish_time[:10] for r in records if r.publish_time]
        if site.get("latest_publish_time"):
            publish_times.append(site["latest_publish_time"][:10])
        site["seen_hrefs"] = hrefs[-20000:]
        site["seen_raw_ids"] = raw_ids[-20000:]
        site["latest_publish_time"] = max(publish_times) if publish_times else site.get("latest_publish_time", "")
        site["last_run_at"] = datetime.now().isoformat(timespec="seconds")


class ExampleBidSpider:
    """示例招投标网站采集器；开发新网站时替换本类中的接口和字段映射。"""

    def __init__(self) -> None:
        """初始化 HTTP 客户端和栏目统计。"""

        self.client = HttpClient(BASE_URL, headers={"Referer": BASE_URL})
        self.stats: list[dict] = []

    def crawl(
        self,
        start_date: date,
        end_date: date,
        max_pages: int | None = None,
        limit: int | None = None,
    ) -> Iterable[BidRecord]:
        """采集全部目标栏目，并逐条返回标准记录。"""

        count = 0
        seen: set[tuple[str, str]] = set()
        for source in self.sources():
            stat = {"webname": WEBNAME, "source": source["name"], "expected": 0, "fetched": 0}
            self.stats.append(stat)
            page = 1
            while True:
                items, total_pages = self.fetch_page(source, page)
                if not items:
                    break
                stop_by_date = False
                for item in items:
                    publish_time = normalize_date(self.get_publish_time(item))
                    if publish_time and publish_time < start_date.isoformat():
                        stop_by_date = True
                        continue
                    if publish_time and publish_time > end_date.isoformat():
                        continue
                    stat["expected"] += 1
                    record = self.fetch_detail(item, source).normalize()
                    key = (record.webname, record.href)
                    if key in seen:
                        continue
                    seen.add(key)
                    stat["fetched"] += 1
                    yield record
                    count += 1
                    if limit and count >= limit:
                        return
                if stop_by_date or (max_pages and page >= max_pages) or page >= total_pages:
                    break
                page += 1

    def sources(self) -> list[dict]:
        """返回需要采集的栏目配置。"""

        return [
            {
                "name": "采购公告",
                "list_api": "/api/list",
                "detail_api": "/api/detail",
                "params": {"category": "purchase"},
            }
        ]

    def fetch_page(self, source: dict, page: int) -> tuple[list[dict], int]:
        """采集一个列表页；需要按目标网站接口替换。"""

        # TODO: 替换为目标网站真实列表接口、请求方法、分页参数和返回字段。
        data = self.client.json(
            "GET",
            source["list_api"],
            params={**source["params"], "page": page, "pageSize": 20},
        )
        items = data.get("rows") or data.get("data") or []
        total_pages = int(data.get("totalPages") or page)
        return items, total_pages

    def fetch_detail(self, item: dict, source: dict) -> BidRecord:
        """采集详情页或详情接口，并转换为标准记录。"""

        raw_id = str(item.get("id") or item.get("noticeId") or "")
        # TODO: 替换为目标网站真实详情接口或详情页地址。
        detail = self.client.json("GET", source["detail_api"], params={"id": raw_id})
        title = clean_space(detail.get("title") or item.get("title"))
        publish_time = normalize_date(detail.get("publishTime") or self.get_publish_time(item))
        href = self.build_href(item, detail, raw_id)
        html = detail.get("content") or detail.get("contentHtml") or title
        msg = text_from_html(html) or title
        meta = extract_meta_fields(msg)
        return BidRecord(
            webname=WEBNAME,
            href=href,
            title=title,
            publish_time=publish_time,
            msg=msg,
            html=html,
            category=source["name"],
            project_name=title,
            project_code=meta["project_code"],
            purchaser=meta["purchaser"],
            supplier=meta["supplier"],
            amount=meta["amount"],
            raw_id=raw_id,
            source_site=BASE_URL,
            extra={"list": item, "detail": detail},
        )

    def get_publish_time(self, item: dict) -> str:
        """从列表字段中提取发布时间。"""

        return clean_space(item.get("publishTime") or item.get("publish_time") or item.get("date"))

    def build_href(self, item: dict, detail: dict, raw_id: str) -> str:
        """构造可追溯的详情页 URL。"""

        href = clean_space(detail.get("url") or item.get("url") or item.get("href"))
        if href:
            return urljoin(BASE_URL + "/", href)
        return urljoin(BASE_URL + "/", f"/detail/{raw_id}")


def clean_space(value: Any) -> str:
    """压缩空白字符。"""

    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def normalize_date(value: Any) -> str:
    """把常见日期格式转换为 YYYY-MM-DD。"""

    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-").replace(".", "-")
    if not text:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return text[:10]


def strip_noise(html: str) -> str:
    """移除脚本、样式和注释。"""

    html = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", "", html or "", flags=re.I)
    return re.sub(r"<!--[\s\S]*?-->", "", html)


def text_from_html(html: str) -> str:
    """把 HTML 转成纯文本正文。"""

    html = strip_noise(html)
    html = re.sub(r"</(p|div|li|tr|h\d|br|table)>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = html_lib.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def keep_table_html(html: str) -> str:
    """仅保留 table 相关标签，满足验收表 html 字段要求。"""

    placeholders: list[str] = []
    table_re = re.compile(r"</?\s*(table|thead|tbody|tfoot|tr|th|td|caption|colgroup|col)\b[^>]*>", re.I)

    def keep(match: re.Match) -> str:
        """临时保护允许保留的 table 标签。"""

        placeholders.append(match.group(0))
        return f"@@TABLE_TAG_{len(placeholders) - 1}@@"

    text = table_re.sub(keep, html or "")
    text = re.sub(r"</(p|div|li|h\d|br)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    for i, tag in enumerate(placeholders):
        text = text.replace(f"@@TABLE_TAG_{i}@@", tag)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def find_first(patterns: list[str], text: str) -> str:
    """按正则列表提取第一个命中的字段。"""

    for pattern in patterns:
        match = re.search(pattern, text or "", re.I | re.S)
        if match:
            return " ".join(match.group(1).split())
    return ""


def extract_meta_fields(text: str) -> dict[str, str]:
    """从正文里补充提取项目编号、采购人、供应商、金额等字段。"""

    return {
        "project_code": find_first([r"(?:项目编号|招标编号|采购编号|编号)[:：]\s*([A-Za-z0-9_\-（）()号\[\]【】]+)"], text),
        "purchaser": find_first([r"(?:采购人|招标人|建设单位)[:：]\s*([^\n，。；;]+)"], text),
        "supplier": find_first([r"(?:中标人|成交供应商|中标供应商|供应商名称)[:：]\s*([^\n，。；;]+)"], text),
        "amount": find_first([r"(?:中标金额|成交金额|项目金额|预算金额|最高限价)[:：]\s*([^\n，。；;]+)"], text),
    }


def write_csv(path: Path, records: list[BidRecord]) -> None:
    """写出 UTF-8-SIG CSV，方便 Excel 直接打开。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())


def write_field_mapping(path: Path) -> None:
    """写出字段映射表，说明 CSV 字段与源网页/接口字段的关系。"""

    rows = [
        ("webname", "站点配置 WEBNAME", "网站名称"),
        ("href", "详情页 URL 或 build_href()", "详情页 URL，和 webname 组成唯一键"),
        ("title", "列表/详情标题字段", "公告标题"),
        ("publish_time", "列表/详情发布时间字段", "发布日期，YYYY-MM-DD"),
        ("msg", "详情正文 HTML 清洗文本", "纯文本正文"),
        ("html", "详情正文 HTML/content 字段", "正文 HTML，仅保留 table 结构"),
        ("raw_id", "源站 ID", "唯一标识参考字段"),
        ("extra", "列表/详情原始字段", "保留原始字段，便于排错和补采"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["字段", "源网页/接口位置", "说明"])
        writer.writerows(rows)


def build_report(records: list[BidRecord], source_stats: list[dict], start_date: str, end_date: str) -> dict:
    """生成验收报告，检查完整率、重复、日期范围和链接可追溯。"""

    total = len(records)
    keys = [(r.webname, r.href) for r in records]
    duplicate_records = total - len(set(keys))
    required = ["webname", "href", "title", "msg", "html", "publish_time"]
    rates = {
        field: round(sum(1 for r in records if getattr(r, field, "")) / total, 4) if total else 0
        for field in required
    }
    coverage = []
    for stat in source_stats:
        expected = int(stat.get("expected") or 0)
        fetched = int(stat.get("fetched") or 0)
        required_min = ceil(expected * 0.985)
        coverage.append(
            {
                **stat,
                "coverage_rate": round(fetched / expected, 4) if expected else 1.0,
                "required_min": required_min,
                "passed": fetched >= required_min,
            }
        )
    by_site = defaultdict(list)
    for record in records:
        by_site[record.webname].append(record)
    flags = {
        "records_ge_98_5_percent": all(item["passed"] for item in coverage),
        "required_fields_ge_99_5_percent": all(rate >= 0.995 for rate in rates.values()) if total else False,
        "no_duplicates": duplicate_records == 0,
        "dates_in_range": all(start_date <= r.publish_time[:10] <= end_date for r in records if r.publish_time),
        "links_traceable": all(r.href.startswith(("http://", "https://")) for r in records),
    }
    flags["overall_pass"] = all(flags.values())
    return {
        "date_range": {"start_date": start_date, "end_date": end_date},
        "total_records": total,
        "duplicate_records": duplicate_records,
        "required_non_empty_rate": rates,
        "source_coverage": coverage,
        "site_counts": {site: len(rows) for site, rows in by_site.items()},
        "quality_flags": flags,
    }


def dedupe(records: list[BidRecord]) -> list[BidRecord]:
    """按 webname + href 去重。"""

    seen = set()
    result = []
    for record in records:
        key = (record.webname, record.href)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def parse_date(value: str) -> date:
    """解析 YYYY-MM-DD 日期。"""

    y, m, d = value.split("-")
    return date(int(y), int(m), int(d))


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(prog=f"{WEBNAME}_爬虫")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", default="output_final")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--state-file", default="state/crawl_state.json")
    parser.add_argument("--incremental-stop-seen", type=int, default=3)
    args = parser.parse_args()

    end = parse_date(args.end_date) if args.end_date else date.today()
    start = parse_date(args.start_date) if args.start_date else end - timedelta(days=args.days - 1)
    state = CrawlState(Path(args.state_file))
    crawl_start = state.incremental_start(start) if args.incremental else start
    spider = ExampleBidSpider()
    records: list[BidRecord] = []
    seen_count = 0
    for record in spider.crawl(crawl_start, end, max_pages=args.max_pages, limit=args.limit):
        if args.incremental and state.is_seen(record):
            seen_count += 1
            if seen_count >= args.incremental_stop_seen:
                print(f"已到上次采集位置，连续遇到 {seen_count} 条已采记录，停止翻页。")
                break
            continue
        records.append(record)
    records = dedupe(records)

    out_dir = Path(args.output_dir)
    write_csv(out_dir / "bid_records.csv", records)
    write_field_mapping(out_dir / "field_mapping.csv")
    report_stats = [] if args.incremental else spider.stats
    report = build_report(records, report_stats, start.isoformat(), end.isoformat())
    (out_dir / "acceptance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    state.update(records)
    state.save()
    if not args.incremental and not report["quality_flags"]["overall_pass"]:
        raise SystemExit("严格验收未通过，请查看 acceptance_report.json")
    print(f"完成：{len(records)} 条 -> {out_dir}")


if __name__ == "__main__":
    main()

