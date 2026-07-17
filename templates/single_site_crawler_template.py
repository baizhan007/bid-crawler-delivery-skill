from __future__ import annotations

import argparse
import csv
import hashlib
import html as html_lib
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from math import ceil
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import requests


SITE_KEY = "example_site"
WEBNAME = "示例招投标网站"
BASE_URL = "https://example.com"

SAMPLE_FIELDS = [
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

DB_FIELDS = [
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
TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col"}
TABLE_ATTRIBUTES = {
    "table": {"summary"},
    "colgroup": {"span"},
    "col": {"span"},
    "th": {"abbr", "colspan", "headers", "rowspan", "scope"},
    "td": {"colspan", "headers", "rowspan"},
}
DROP_CONTENT_TAGS = {"script", "style", "noscript", "template"}
LINE_BREAK_TAGS = {"br", "div", "p", "li", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class BidRecord:
    """统一标讯记录结构，对应样本 CSV 字段和入库字段。"""

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
        self.href = normalize_href(self.href, BASE_URL)
        self.html = keep_table_html(self.html or self.msg or self.title)
        return self

    def to_sample_row(self) -> dict[str, Any]:
        """转换为样本 CSV 行。"""

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
        limit_per_category: int | None = None,
        state: CrawlState | None = None,
        incremental_stop_seen: int = 3,
    ) -> Iterable[BidRecord]:
        """采集全部目标栏目；增量边界只停止当前栏目，不影响后续栏目。"""

        count = 0
        seen: set[tuple[str, str]] = set()
        for source in self.sources():
            stat = {"webname": WEBNAME, "source": source["name"], "expected": 0, "fetched": 0}
            self.stats.append(stat)
            page = 1
            category_count = 0
            consecutive_seen = 0
            stop_by_seen = False
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
                    if state is not None and state.is_seen(record):
                        consecutive_seen += 1
                        if consecutive_seen >= incremental_stop_seen:
                            stop_by_seen = True
                            stat["incremental_boundary_reached"] = True
                            stat["incremental_seen_count"] = consecutive_seen
                            break
                        continue
                    consecutive_seen = 0
                    stat["fetched"] += 1
                    yield record
                    count += 1
                    category_count += 1
                    if limit and count >= limit:
                        return
                    if limit_per_category and category_count >= limit_per_category:
                        stop_by_date = True
                        break
                if stop_by_seen:
                    print(
                        f"栏目 {source['name']} 已到上次采集位置，"
                        f"连续遇到 {consecutive_seen} 条已采记录，继续下一个栏目。"
                    )
                    break
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


def normalize_href(value: Any, base_url: str) -> str:
    """把源站链接规范为浏览器可打开的绝对 URL。"""

    text = html_lib.unescape("" if value is None else str(value)).strip()
    text = text.replace("\r", "").replace("\n", "").replace(" ", "")
    if not text:
        return ""
    return urljoin(base_url.rstrip("/") + "/", text)


def is_http_url(value: str) -> bool:
    """判断链接是否为带主机名的完整 http/https URL。"""

    try:
        parsed = urlsplit(value or "")
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def validate_mysql_identifier(value: str) -> str:
    """校验 MySQL 表名，防止标识符拼接造成 SQL 注入。"""

    value = clean_space(value)
    if not MYSQL_IDENTIFIER_RE.fullmatch(value):
        raise ValueError("数据库表名只能包含英文字母、数字和下划线，且不能以数字开头。")
    return value


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


class SafeTableHTMLParser(HTMLParser):
    """仅输出正文文本和安全的表格标签、属性。"""

    def __init__(self) -> None:
        """初始化安全 HTML 输出缓冲区。"""

        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """处理开始标签，危险内容标签整段丢弃。"""

        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag in TABLE_TAGS:
            allowed = TABLE_ATTRIBUTES.get(tag, set())
            safe_attrs = []
            for name, value in attrs:
                name = name.lower()
                if name not in allowed or name.startswith("on") or value is None:
                    continue
                safe_attrs.append(f'{name}="{html_lib.escape(value, quote=True)}"')
            suffix = f" {' '.join(safe_attrs)}" if safe_attrs else ""
            self.parts.append(f"<{tag}{suffix}>")
        elif tag in LINE_BREAK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """处理自闭合标签。"""

        if tag.lower() in DROP_CONTENT_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if tag.lower() in TABLE_TAGS and not self.drop_depth:
            self.parts.append(f"</{tag.lower()}>")

    def handle_endtag(self, tag: str) -> None:
        """处理结束标签，并维护危险内容跳过深度。"""

        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            if self.drop_depth:
                self.drop_depth -= 1
            return
        if self.drop_depth:
            return
        if tag in TABLE_TAGS:
            self.parts.append(f"</{tag}>")
        elif tag in LINE_BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """转义正文文本，避免实体解码后重新形成可执行标签。"""

        if not self.drop_depth:
            self.parts.append(html_lib.escape(data, quote=False))


def keep_table_html(html: str) -> str:
    """清洗正文 HTML，只保留安全表格结构并转义普通文本。"""

    parser = SafeTableHTMLParser()
    parser.feed(html or "")
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    return text.strip()


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


class MysqlWriter:
    """将采集记录写入 a_bidcollect_info。"""

    def __init__(self, args: argparse.Namespace) -> None:
        """初始化数据库连接和写入 SQL。"""

        table_name = validate_mysql_identifier(args.db_table)
        if not args.db_user or not args.db_name:
            raise RuntimeError("启用 --to-db 时必须提供 --db-user 和 --db-name，或配置 BID_DB_USER/BID_DB_NAME。")
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise RuntimeError("启用 --to-db 需要安装 pymysql：pip install pymysql") from exc
        placeholders = ", ".join(["%s"] * len(DB_FIELDS))
        columns = ", ".join(f"`{field}`" for field in DB_FIELDS)
        table = f"`{table_name}`"
        if args.db_skip_existing:
            self.sql = f"INSERT IGNORE INTO {table} ({columns}) VALUES ({placeholders})"
        else:
            updates = ", ".join(
                f"`{field}`=VALUES(`{field}`)"
                for field in ["msg", "html", "publish_time", "industry", "from_auto_script", "identify_code", "etl_flag"]
            )
            self.sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
        self.conn = pymysql.connect(
            host=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
            database=args.db_name,
            charset="utf8mb4",
            autocommit=False,
        )
        self.count = 0

    def write_many(self, records: list[BidRecord]) -> None:
        """批量写入数据库。"""

        if not records:
            return
        values = [[db_row_from_record(record).get(field) for field in DB_FIELDS] for record in records]
        with self.conn.cursor() as cursor:
            cursor.executemany(self.sql, values)
        self.count += len(records)
        self.conn.commit()

    def close(self) -> None:
        """提交并关闭数据库连接。"""

        self.conn.commit()
        self.conn.close()


def db_row_from_record(record: BidRecord) -> dict[str, Any]:
    """把标准记录映射为 a_bidcollect_info 可写字段。"""

    href = normalize_href(record.href, BASE_URL)
    webname = clean_space(record.webname or WEBNAME)
    identify = hashlib.sha256(f"{webname}|{href}".encode("utf-8")).hexdigest()[:32]
    return {
        "webname": webname,
        "href": href,
        "msg": clean_space(record.msg or record.title),
        "html": record.html or "",
        "publish_time": normalize_date(record.publish_time) or None,
        "industry": clean_space(record.category) or None,
        "from_auto_script": 1,
        "identify_code": identify,
        "etl_flag": 0,
    }


def write_sample_csv(path: Path, records: list[BidRecord], sample_size: int) -> None:
    """写出少量 UTF-8-SIG 样本 CSV，用于验收抽查。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for record in records[:sample_size]:
            writer.writerow(record.to_sample_row())

def safe_filename(value: str) -> str:
    """清理 Windows 文件名不允许的字符。"""

    return re.sub(r'[\\/:*?"<>|]', "_", clean_space(value) or "未分类")


def record_group(record: BidRecord) -> str:
    """取得用于拆分 CSV 的采购相关栏目。"""

    return clean_space(record.category) or "未分类"


def write_sample_csv_by_category(out_dir: Path, records: list[BidRecord], order: list[str], sample_size: int) -> list[dict]:
    """按栏目输出少量样本 CSV；空栏目不生成文件。"""

    grouped: dict[str, list[BidRecord]] = defaultdict(list)
    for record in records:
        grouped[record_group(record)].append(record)
    summary = []
    index = 1
    for category in order + sorted(cat for cat in grouped if cat not in order):
        rows = grouped.get(category, [])
        if not rows:
            continue
        sample_rows = rows[:sample_size]
        filename = f"{index}、{safe_filename(category)}_sample.csv"
        write_sample_csv(out_dir / filename, sample_rows, sample_size)
        summary.append({"category": category, "filename": filename, "sample_count": len(sample_rows), "total_seen": len(rows)})
        index += 1
    return summary


def write_field_mapping(path: Path) -> None:
    """写出字段映射表，说明入库字段与源网页/接口字段的关系。"""

    rows = [
        ("webname", "站点配置 WEBNAME", "网站名称"),
        ("href", "详情页 URL 或 build_href()", "浏览器可打开详情页 URL，和 webname 组成唯一键"),
        ("publish_time", "列表/详情发布时间字段", "发布日期，YYYY-MM-DD"),
        ("msg", "详情正文 HTML 清洗文本", "纯文本正文"),
        ("html", "详情正文 HTML/content 字段", "正文 HTML，仅保留 table 结构"),
        ("industry", "栏目 category", "行业或栏目分类，可由下游覆盖"),
        ("from_auto_script", "脚本默认值 1", "来源标记"),
        ("identify_code", "sha256(webname|href)[:32]", "稳定唯一标识"),
        ("etl_flag", "脚本默认值 0", "ETL 处理标记"),
        ("title/category/raw_id/extra", "列表/详情原始字段", "仅用于样本 CSV 和排错，不写入正式库"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["字段", "源网页/接口位置", "说明"])
        writer.writerows(rows)


def build_report(records: list[BidRecord], source_stats: list[dict], start_date: str, end_date: str, args: argparse.Namespace) -> dict:
    """生成验收报告，检查完整率、重复、日期范围、链接和入库能力。"""

    total = len(records)
    keys = [(r.webname, r.href) for r in records]
    duplicate_records = total - len(set(keys))
    required = ["webname", "href", "msg", "html", "publish_time"]
    rates = {
        field: round(sum(1 for r in records if getattr(r, field, "")) / total, 4) if total else 0
        for field in required
    }
    href_bad = [
        {"href": r.href, "title": r.title}
        for r in records
        if not is_http_url(r.href)
    ][:50]
    date_bad = []
    bad_date_count = 0
    for record in records:
        try:
            publish_date = datetime.strptime(record.publish_time, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            bad_date_count += 1
            date_bad.append({"publish_time": record.publish_time, "title": record.title, "reason": "invalid_format"})
            continue
        if not (parse_date(start_date) <= publish_date <= parse_date(end_date)):
            bad_date_count += 1
            date_bad.append({"publish_time": record.publish_time, "title": record.title, "reason": "out_of_range"})
    date_bad = date_bad[:50]
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
        "dates_in_range": total > 0 and bad_date_count == 0,
        "links_traceable": not href_bad,
        "database_mode_supported": True,
    }
    flags["overall_pass"] = all(flags.values())
    return {
        "date_range": {"start_date": start_date, "end_date": end_date},
        "total_records": total,
        "duplicate_records": duplicate_records,
        "required_non_empty_rate": rates,
        "source_coverage": coverage,
        "site_counts": {site: len(rows) for site, rows in by_site.items()},
        "href_quality": {
            "http_url_rate": round(sum(1 for r in records if is_http_url(r.href)) / total, 4) if total else 0,
            "browser_openable_checked": False,
            "bad_samples": href_bad,
        },
        "date_quality": {
            "valid_and_in_range_rate": round((total - bad_date_count) / total, 4) if total else 0,
            "bad_count": bad_date_count,
            "bad_samples": date_bad,
        },
        "database": {
            "database_mode_supported": True,
            "db_table": validate_mysql_identifier(args.db_table),
            "db_unique_key": "webname + href",
            "db_write_fields": DB_FIELDS,
            "to_db_enabled_this_run": bool(args.to_db),
        },
        "sample": {
            "sample_only": True,
            "sample_csv": args.sample_csv or "",
            "sample_size": args.sample_size,
        },
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
    parser.add_argument("--output-dir", default="", help="兼容旧调用：同时覆盖字段映射和验收报告目录")
    parser.add_argument("--field-mapping-file", default="", help="字段映射 CSV 路径，默认写入站点项目的字段映射表目录")
    parser.add_argument("--report-file", default="", help="验收报告 JSON 路径，默认写入站点项目的验收报告目录")
    parser.add_argument("--sample-csv", default="", help="写出单个样本 CSV，用于快速验收抽查")
    parser.add_argument("--sample-dir", default="", help="按栏目写出样本 CSV 的目录")
    parser.add_argument("--sample-size", type=int, default=20, help="每个样本 CSV 最多写出多少条")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--limit-per-category", type=int)
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--state-file", default="", help="断点文件，默认写入站点项目的运行状态目录")
    parser.add_argument("--incremental-stop-seen", type=int, default=3)
    parser.add_argument("--to-db", action="store_true", help="启用 MySQL 直接入库，写入 a_bidcollect_info 表")
    parser.add_argument("--db-host", default=os.getenv("BID_DB_HOST", "127.0.0.1"), help="数据库地址，默认读取 BID_DB_HOST")
    parser.add_argument("--db-port", type=int, default=int(os.getenv("BID_DB_PORT", "3306")), help="数据库端口，默认读取 BID_DB_PORT")
    parser.add_argument("--db-user", default=os.getenv("BID_DB_USER", ""), help="数据库用户名，默认读取 BID_DB_USER")
    parser.add_argument("--db-password", default=os.getenv("BID_DB_PASSWORD", ""), help="数据库密码，默认读取 BID_DB_PASSWORD")
    parser.add_argument("--db-name", default=os.getenv("BID_DB_NAME", ""), help="数据库名，默认读取 BID_DB_NAME")
    parser.add_argument("--db-table", default=os.getenv("BID_DB_TABLE", "a_bidcollect_info"), help="入库表名，默认 a_bidcollect_info")
    parser.add_argument("--db-skip-existing", action="store_true", help="遇到 webname + href 已存在时跳过，不覆盖更新")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days 必须大于等于 1")
    if args.incremental_stop_seen < 1:
        parser.error("--incremental-stop-seen 必须大于等于 1")
    if args.sample_size < 1:
        parser.error("--sample-size 必须大于等于 1")
    try:
        validate_mysql_identifier(args.db_table)
    except ValueError as exc:
        parser.error(str(exc))

    end = parse_date(args.end_date) if args.end_date else date.today()
    start = parse_date(args.start_date) if args.start_date else end - timedelta(days=args.days - 1)
    if start > end:
        parser.error("开始日期不能晚于结束日期")
    project_root = Path(__file__).resolve().parent.parent
    legacy_out_dir = Path(args.output_dir) if args.output_dir else None
    field_mapping_file = (
        Path(args.field_mapping_file)
        if args.field_mapping_file
        else (legacy_out_dir / "field_mapping.csv" if legacy_out_dir else project_root / "字段映射表" / "field_mapping.csv")
    )
    report_file = (
        Path(args.report_file)
        if args.report_file
        else (legacy_out_dir / "acceptance_report.json" if legacy_out_dir else project_root / "验收报告" / "acceptance_report.json")
    )
    state_file = Path(args.state_file) if args.state_file else project_root / "运行状态" / "crawl_state.json"
    state = CrawlState(state_file)
    crawl_start = state.incremental_start(start) if args.incremental else start
    spider = ExampleBidSpider()
    records: list[BidRecord] = []
    for record in spider.crawl(
        crawl_start,
        end,
        max_pages=args.max_pages,
        limit=args.limit,
        limit_per_category=args.limit_per_category,
        state=state if args.incremental else None,
        incremental_stop_seen=args.incremental_stop_seen,
    ):
        records.append(record)
    records = dedupe(records)

    write_field_mapping(field_mapping_file)
    report_stats = [] if args.incremental else spider.stats
    report = build_report(records, report_stats, crawl_start.isoformat(), end.isoformat(), args)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    if records and not report["quality_flags"]["overall_pass"]:
        raise SystemExit(f"严格验收未通过，请查看 {report_file}")
    if not args.incremental and not records:
        raise SystemExit(f"严格验收未通过：没有采集到记录，请查看 {report_file}")

    persisted = False
    if args.to_db:
        db_writer = MysqlWriter(args)
        try:
            db_writer.write_many(records)
        finally:
            db_writer.close()
        print(f"入库完成：{db_writer.count} 条 -> {args.db_table}")
        persisted = bool(records)
    if args.sample_csv and records:
        write_sample_csv(Path(args.sample_csv), records, args.sample_size)
        persisted = True
    if args.sample_dir and records:
        write_sample_csv_by_category(Path(args.sample_dir), records, [source["name"] for source in spider.sources()], args.sample_size)
        persisted = True
    if persisted:
        state.update(records)
        state.save()
    print(f"完成：{len(records)} 条；正式入库={'是' if args.to_db else '否'}；验收报告 -> {report_file}")


if __name__ == "__main__":
    main()
