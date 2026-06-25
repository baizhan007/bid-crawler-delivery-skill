# 单文件爬虫编写指南

本指南用于指导未来每个网站的 `完整源码/网站名_爬虫.py` 怎么写。目标是让客户能把源码放到自己的环境里定时运行并直接写入 `a_bidcollect_info`，开发人员只用少量样本快速验证。

## 代码整体顺序

推荐按以下顺序组织单文件：

1. 标准库和第三方库 import。
2. 输出字段、入库字段、站点常量。
3. `BidRecord` 数据类。
4. HTTP 请求客户端。
5. 增量/断点状态类。
6. 目标网站 Spider 类。
7. `href` 构造、HTML 清洗、日期标准化、字段提取等工具函数。
8. `MysqlWriter` 数据库写入器。
9. 样本 CSV、字段映射、验收报告写出函数。
10. `main()` 命令行入口。
11. `if __name__ == "__main__": main()`。

## 目标字段

正式入库字段：

```python
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
```

样本 CSV 可包含更多排错字段：

```python
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
```

验收重点字段：

- `webname`: 网站名称。
- `href`: 浏览器可打开详情页 URL。
- `msg`: 正文纯文本，不能为空。
- `html`: 正文 HTML 清洗结果。
- `publish_time`: 发布日期，格式 `YYYY-MM-DD`。

## href 规范

`href` 是核心验收字段，不只是源站 ID。必须满足：

- 完整 `http://` 或 `https://` URL。
- 复制到浏览器能打开对应详情页。
- 不是接口 URL，除非该接口本身就是客户认可的详情访问地址。
- 不是相对路径、裸 ID、缺参 hash 路由或列表页 URL。
- 与 `webname` 组成唯一键。

推荐实现：

```python
from urllib.parse import urljoin
import html as html_lib


def normalize_href(value: str, base_url: str) -> str:
    """把源站链接规范为浏览器可打开的绝对 URL。"""

    text = html_lib.unescape(value or "").strip()
    text = text.replace("\\r", "").replace("\\n", "").replace(" ", "")
    if not text:
        return ""
    return urljoin(base_url.rstrip("/") + "/", text)


def build_detail_href(raw_id: str) -> str:
    """用源站 ID 构造前端详情页 URL；按目标网站实际路由替换。"""

    return f"https://example.com/detail/{raw_id}"
```

SPA/hash 站点必须补齐 hash 路由所需参数，例如 `#/detail?id=...&moduleNo=...`。如果列表接口只有 `id`，先在浏览器或前端源码中确认详情路由，再拼 `href`。

验收报告里至少检查：

- `href` 非空率。
- `href` 是否以 `http://` 或 `https://` 开头。
- `webname + href` 是否重复。
- 抽样 `href` 是否可打开。

## BidRecord 写法

`BidRecord` 是所有网站的统一记录结构。它应该提供：

- `normalize()`: 清理标题、正文、发布时间、HTML、href。
- `to_sample_row()`: 转换为样本 CSV 字典。

验收表结构用于约束字段含义、唯一性和入库映射。不要把只用于排错的扩展字段写进正式入库表。

## HTTP 客户端

请求客户端需要支持：

- 浏览器常见请求头。
- `BID_SPIDER_DELAY` 请求间隔环境变量。
- `BID_SPIDER_PROXY` 代理环境变量。
- `GET`、`POST`、`json()`。
- 自动拼接 base URL。

不要把代理、Cookie、Token 写死在源码里。需要时放到环境变量或配置说明中。

## 网站 Spider 类

每个网站一个 Spider 类，例如：

```python
class ExampleBidSpider:
    """某某招投标网站采集器。"""

    webname = "某某招投标网站"
    base_url = "https://example.com"

    def crawl(self, start_date, end_date, max_pages=None, limit=None, limit_per_category=None):
        """采集所有目标栏目。"""
        ...
```

Spider 至少包含：

- `crawl()`: 对外采集入口，yield `BidRecord`。
- `fetch_page()` 或 `fetch_sources()`: 采集列表页。
- `fetch_detail()`: 采集详情页。
- `build_href()`: 构造浏览器可打开详情页 URL。
- `build_record()`: 从列表/详情数据构造标准记录。
- `stats`: 记录每个栏目 expected/fetched，用于验收覆盖率。

## 栏目确认

正式采集前，先基于当前网站可确定的采购相关导航、接口字典、列表参数或可见栏目整理候选 category。把候选列表反馈给用户确认：

```text
发现以下采购相关栏目：
1、采购公告
2、结果公告
3、变更公告

请确认是否都采集，或指出需要排除的栏目。
```

不要把候选栏目写死成某两个示例网站。每个新网站都要重新发现。

## 数据库入库

默认交付目标是直接写入 `a_bidcollect_info`。源码必须支持：

```text
--to-db
--db-host
--db-port
--db-user
--db-password
--db-name
--db-table
--db-skip-existing
```

配置优先支持环境变量：

```text
BID_DB_HOST
BID_DB_PORT
BID_DB_USER
BID_DB_PASSWORD
BID_DB_NAME
BID_DB_TABLE
```

`pymysql` 只在 `--to-db` 开启时延迟导入。默认用 `INSERT ... ON DUPLICATE KEY UPDATE`，按 `webname + href` 更新；`--db-skip-existing` 使用 `INSERT IGNORE`。

## 样本 CSV

CSV 不是默认正式数据交付物。它用于快速验证字段、正文、日期和 href。推荐参数：

```text
--sample-csv ..\验收样例\sample_records.csv
--sample-size 20
--limit 100
--limit-per-category 10
--max-pages 1
```

样本 CSV 使用 `utf-8-sig` 编码，方便 Excel 打开不乱码。不要为了开发验收默认跑全量 CSV。

## HTML 清洗

`msg` 应该是纯文本正文，便于下游搜索和处理。

`html` 应保留正文内容，表格保留结构，移除脚本、样式和无关属性。至少保留这些表格标签：

```text
table, thead, tbody, tfoot, tr, th, td, caption, colgroup, col
```

如果详情接口没有 HTML，只能从列表字段拼正文，也要保证 `msg` 和 `html` 非空，并在字段映射说明里写清楚来源。

## 增量和断点采集

默认用 `state/crawl_state.json` 保存状态：

```json
{
  "sites": {
    "site_key": {
      "latest_publish_time": "2026-06-22",
      "seen_hrefs": [],
      "seen_raw_ids": [],
      "last_run_at": "2026-06-23T10:00:00"
    }
  }
}
```

增量逻辑：

1. 如果有 `latest_publish_time`，从它前一天开始采，避免源站迟发或改时间。
2. 每条记录用 `href` 和 `raw_id` 判断是否已采。
3. 连续遇到若干条已采记录时停止翻页。
4. 成功入库或成功生成样本后更新状态。

命令行参数建议：

```text
--days 30
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
--max-pages 3
--limit 50
--limit-per-category 10
--incremental
--state-file state/crawl_state.json
--incremental-stop-seen 3
```

## 验收报告

每个网站输出 `acceptance_report.json`，至少包含：

```json
{
  "date_range": {"start_date": "2026-05-24", "end_date": "2026-06-22"},
  "total_records": 100,
  "duplicate_records": 0,
  "required_non_empty_rate": {
    "webname": 1.0,
    "href": 1.0,
    "msg": 1.0,
    "html": 1.0,
    "publish_time": 1.0
  },
  "href_quality": {
    "http_url_rate": 1.0,
    "browser_openable_checked": true,
    "bad_samples": []
  },
  "database": {
    "database_mode_supported": true,
    "db_table": "a_bidcollect_info",
    "db_unique_key": "webname + href",
    "db_write_fields": ["webname", "href", "msg", "html", "publish_time", "industry", "from_auto_script", "identify_code", "etl_flag"]
  },
  "quality_flags": {
    "required_fields_ge_99_5_percent": true,
    "no_duplicates": true,
    "dates_in_range": true,
    "links_traceable": true,
    "database_mode_supported": true,
    "overall_pass": true
  }
}
```

如果源站无法提供总数，只能按分页停止条件估算，也要在验收报告或部署文档中说明。

## 中文注释标准

类和函数必须有中文 docstring。关键业务判断也应有简短中文注释，例如：

```python
def fetch_detail(self, item: dict) -> BidRecord:
    """采集详情接口，并把源站字段转换为标准记录。"""
```

避免无意义注释，例如“给变量赋值”。注释应该解释业务意图、边界处理或验收原因。

## 不要默认写的东西

默认不要写：

- 全量 CSV 作为正式交付物。
- 与当前验收范围无关的额外输出。
- 浏览器自动化依赖。
- 多文件包结构。
- GUI。
- 与当前网站无关的站点代码。
- 批量转换、临时修复、测试 demo 等辅助脚本。

这些都会让甲方交付包看起来复杂，除非用户明确要求。
