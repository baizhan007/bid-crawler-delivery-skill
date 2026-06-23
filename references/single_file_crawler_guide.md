# 单文件爬虫编写指南

本指南用于指导未来每个网站的 `完整源码/网站名_爬虫.py` 怎么写。目标不是炫技，而是让甲方、同事、后续维护者都能快速看懂。

## 代码整体顺序

推荐按以下顺序组织单文件：

1. 标准库和第三方库 import。
2. `CSV_FIELDS` 输出字段常量。
3. `BidRecord` 数据类。
4. `HttpClient` 请求客户端。
5. `CrawlState` 增量/断点状态类。
6. 目标网站 Spider 类。
7. HTML 清洗、日期标准化、字段提取等工具函数。
8. CSV、字段映射、验收报告写出函数。
9. `main()` 命令行入口。
10. `if __name__ == "__main__": main()`。

这样排布的好处是：上半部分是结构和基础设施，中间是网站差异，下半部分是通用输出和入口。

## 必备字段

默认输出 CSV 字段：

```python
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
```

验收重点字段：

- `title`: 公告标题。
- `msg`: 正文纯文本，不能为空。
- `publish_time`: 发布日期，格式 `YYYY-MM-DD`。
- `webname`: 网站名称。
- `href`: 详情页 URL。
- `html`: 正文 HTML 清洗结果，仅保留 table 相关标签。

## BidRecord 写法

`BidRecord` 是所有网站的统一数据结构。它应该提供：

- `normalize()`: 清理标题、正文、发布时间、HTML。
- `to_row()`: 转换为 CSV 字典。

不要默认提供 `to_db_row()`，除非用户明确要求数据库写入。验收表结构是字段标准，不是 SQL 交付要求。

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

    def crawl(self, start_date, end_date, max_pages=None, limit=None):
        """采集所有目标栏目。"""
        ...
```

Spider 至少包含：

- `crawl()`: 对外采集入口，yield `BidRecord`。
- `fetch_page()` 或 `fetch_sources()`: 采集列表页。
- `fetch_detail()`: 采集详情页。
- `build_record()`: 从列表/详情数据构造标准记录。
- `stats`: 记录每个栏目 expected/fetched，用于验收覆盖率。

## 优先使用接口

现代招投标网站常见是前端 SPA，页面里看到的表格来自 JSON API。优先找：

- 列表接口。
- 详情接口。
- 栏目字典接口。
- 日期筛选参数。
- 分页参数。
- 详情页路由参数。

不要一上来就用浏览器点击翻页或解析渲染后的 DOM。接口更稳定、可验收、可复跑。

## HTML 清洗

`msg` 应该是纯文本正文，便于下游搜索和入库。

`html` 应保留正文中的 table 结构，但移除脚本、样式和无关标签。只保留这些标签即可：

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
4. 成功输出后更新状态。

命令行参数建议：

```text
--days 30
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
--output-dir output_final
--max-pages 3
--limit 50
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
    "title": 1.0,
    "msg": 1.0,
    "html": 1.0,
    "publish_time": 1.0
  },
  "source_coverage": [],
  "site_counts": {},
  "quality_flags": {
    "records_ge_98_5_percent": true,
    "required_fields_ge_99_5_percent": true,
    "no_duplicates": true,
    "dates_in_range": true,
    "links_traceable": true,
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

- 数据库连接。
- SQL 文件输出。
- 浏览器自动化依赖。
- 多文件包结构。
- GUI。
- 与当前网站无关的站点代码。

这些都会让甲方交付包看起来复杂，除非用户明确要求。

