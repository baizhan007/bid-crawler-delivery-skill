---
name: bid-crawler-delivery
description: Use this skill whenever the user asks to build, analyze, repair, package, or deliver a procurement/tender/bidding website crawler, especially for 招投标, 招标, 标讯, 采购公告, 开标大厅, 验收标准, 增量采集, 断点采集, 直接入库, 数据库入库, a_bidcollect_info, href 可打开校验, 字段映射表, or one-site-one-project delivery. This skill produces a client-ready independent project folder per website with single-file Python crawler source, Chinese comments/docstrings, MySQL ingestion into a_bidcollect_info by default, sample CSV only for fast verification, deployment/config docs, field mapping, and acceptance report.
---

# Bid Crawler Delivery

This skill turns one procurement/bidding announcement website into a clean, repeatable delivery package. The current default delivery target is **database ingestion into `a_bidcollect_info`**. Sample CSV files are only for fast development verification and acceptance spot checks, not the default full data deliverable.

## Core Promise

For each target website, produce one independent project. Each project must be self-contained, easy to inspect, and shaped for future batch work across many websites.

Use this default structure:

```text
交付根目录/
├── 交付结构说明.md
├── 网站A/
│   ├── 完整源码/
│   │   ├── 网站A_爬虫.py
│   │   └── requirements.txt
│   ├── 部署文档/
│   │   └── 部署文档.md
│   ├── 配置说明/
│   │   └── 配置说明.md
│   ├── 字段映射表/
│   │   ├── field_mapping.csv
│   │   └── 字段映射说明.md
│   ├── 验收样例/
│   │   └── sample_records.csv
│   └── 验收报告/
│       └── acceptance_report.json
└── 网站B/
    └── ...
```

Do not include process debris in the final delivery folder: no `.idea`, `.vscode`, `__pycache__`, scratch output, old helper scripts, old module directories, unused websites, or files that are not part of the agreed client delivery.

## Default Acceptance Contract

Unless the user gives a different standard, align the crawler with this target table:

- `webname`: 网站名称。
- `href`: 详情页 URL，和 `webname` 组成唯一键；必须是复制到浏览器可打开的详情页。
- `msg`: HTML 清洗后的纯文本正文。
- `html`: 原始正文 HTML 的清洗结果，仅保留正文内容和必要 table 结构。
- `publish_time`: 发布日期，标准格式 `YYYY-MM-DD`。
- Optional source/helper fields used in code or sample CSV: `title`, `category`, `project_name`, `project_code`, `purchaser`, `supplier`, `amount`, `raw_id`, `source_site`, `extra`.

Formal ingestion writes only the fields needed by `a_bidcollect_info`:

```text
webname, href, msg, html, publish_time,
industry, from_auto_script, identify_code, etl_flag
```

Let the database maintain `id`, `create_time`, and `update_time`.

Acceptance checks should cover:

- Required fields: `webname`, `href`, `msg`, `html`, `publish_time`.
- `href` is a complete `http/https` browser-openable detail URL, not an API URL, relative path, bare ID, or incomplete hash route.
- Required non-empty rate >= 99.5% for formal runs where the source provides those fields.
- No duplicate records by `webname + href`.
- Date range traceability, normally recent one month when requested.
- All requested columns/boards are represented, not just one visible page.
- Incremental or breakpoint collection is supported through state tracking.
- Database mode supports insert/update by `webname + href` and optional insert-only behavior.

## Operating Workflow

1. Read the user-provided acceptance standard, target table requirement, requirement docs, spreadsheets, or current delivery folder.
2. Identify target websites and decide which websites are in scope. Respect explicit exclusions.
3. Inventory each website:
   - visible boards/columns,
   - list pages,
   - detail pages,
   - frontend JSON APIs,
   - pagination,
   - date filters,
   - detail URL construction,
   - anti-scraping controls.
4. Identify procurement-related candidate categories/boards from the current website's navigation, dictionaries, APIs, and visible boards.
5. Before full collection, report the candidate category list to the user and ask which ones should be crawled. Proceed after the user confirms or edits the list.
6. Prefer public frontend JSON/API calls over brittle visual scraping when possible.
7. Build a small probe first: one board, one page, one detail, one browser-openable `href`.
8. Expand to confirmed boards and the target date range.
9. Normalize records into the target table fields and optional helper fields.
10. Implement database ingestion as the formal output path.
11. Generate only small sample CSV files for verification, controlled by `--sample-csv`, `--sample-size`, `--limit`, `--limit-per-category`, or `--max-pages`.
12. Implement incremental collection:
    - keep a state JSON file,
    - remember latest publish date,
    - remember seen `href` and `raw_id`,
    - stop when repeated seen records indicate the previous collection boundary.
13. Generate delivery files per website.
14. Run verification and clean the final folder.

## Source Code Rules

Use one single Python file per website unless the user explicitly prefers a package. The single file should be readable, with Chinese docstrings/comments for every class and meaningful function.

The file should include:

- constants and field lists,
- `BidRecord` dataclass,
- HTTP client with headers, delay, optional proxy,
- state/checkpoint class,
- target-site spider class,
- HTML/text cleaning helpers,
- date normalization,
- `href` normalization and browser URL construction helpers,
- `MysqlWriter` or equivalent database writer,
- sample CSV writer for spot checks,
- field mapping writer,
- acceptance report builder,
- command-line `main()`.

Keep the source focused on collection, normalization, href construction, database ingestion, sample verification, field mapping, and acceptance reporting unless the user asks for a wider runtime.

Read these references before writing or repairing a crawler:

- `references/single_file_crawler_guide.md` for code structure and href/sample verification rules.
- `references/database_ingestion.md` for `a_bidcollect_info` insertion rules.
- `references/delivery_structure.md` and `references/acceptance_checklist.md` before final packaging.

Use `templates/single_site_crawler_template.py` as the starting skeleton when building a new site.

## Delivery Documents

For every website project, write:

- `部署文档/部署文档.md`: environment, dependency install command, formal database run command, sample verification command, date-range command, incremental command, output descriptions.
- `配置说明/配置说明.md`: database env vars, proxy env var, request delay env var, state file path, board/API parameter locations.
- `字段映射表/field_mapping.csv`: source-to-output field mapping.
- `字段映射表/字段映射说明.md`: plain-language mapping against `a_bidcollect_info`.
- `验收样例/sample_records.csv`: small sample only when useful for verification; do not treat it as the formal full data deliverable.
- `验收报告/acceptance_report.json`: machine-readable quality report, including href quality and database mode flags.

## Final Verification

Before telling the user the package is ready:

- List final files and directories.
- Search final folder for forbidden leftovers.
- Confirm the final folder contains only the agreed delivery files.
- Confirm no out-of-scope website names.
- Confirm each site has the required folders.
- Confirm each `完整源码` has exactly one main `*_爬虫.py` plus `requirements.txt`.
- Confirm there are no unrelated helper scripts such as batch converters, temporary tools, demos, tests, or debug outputs.
- Compile each Python file or otherwise syntax-check it.
- Confirm `--to-db`, database configuration, and duplicate handling are present.
- Confirm `href` fields are complete browser-openable URLs.
- Confirm sample CSV records, if generated, are only samples and not represented as the full formal deliverable.
- Confirm acceptance flags pass or explain any failure plainly.

Use `scripts/validate_delivery.py` when available:

```bash
python scripts/validate_delivery.py "交付根目录"
```

## When the User Is Anxious About Files

Be explicit and calm. Explain which files are required and which are extras. If they say a file should not be there, remove it from the final delivery package unless it is truly required by the stated acceptance standard. The client-facing folder should be clean, boring, and easy to defend.
