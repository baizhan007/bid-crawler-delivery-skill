---
name: bid-crawler-delivery
description: Use this skill whenever the user asks to build, analyze, repair, package, or deliver a procurement/tender/bidding website crawler, especially when they mention 招投标, 招标, 标讯, 采购公告, 开标大厅, 验收标准, 增量采集, 断点采集, CSV交付, 字段映射表, or one-site-one-project delivery. This skill produces a client-ready independent project folder per website with single-file Python crawler source, Chinese comments/docstrings, CSV data output, deployment docs, configuration docs, field mapping, and acceptance report aligned to a_bidcollect_info-style requirements.
---

# Bid Crawler Delivery

This skill turns one procurement/bidding announcement website into a clean, repeatable delivery package. It is designed for client acceptance, not just quick scraping. The end result should be a folder the user can hand to a customer without explaining internal development history.

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
│   ├── 采集结果/
│   │   └── 网站A.csv
│   └── 验收报告/
│       └── acceptance_report.json
└── 网站B/
    └── ...
```

Do not include process debris in the final delivery folder: no `.idea`, `.vscode`, `__pycache__`, scratch output, old module directories, unused websites, or files that are not part of the agreed client delivery.

## Default Acceptance Contract

Unless the user gives a different standard, align the output with this target table conceptually:

- `webname`: 网站名称。
- `href`: 详情页 URL，和 `webname` 组成唯一键。
- `msg`: HTML 清洗后的纯文本正文。
- `html`: 原始正文 HTML 的清洗结果，仅保留 table 相关结构。
- `publish_time`: 发布日期，标准格式 `YYYY-MM-DD`。
- Optional helper fields: `title`, `category`, `project_name`, `project_code`, `purchaser`, `supplier`, `amount`, `raw_id`, `source_site`, `extra`.

The actual data deliverable is CSV by default. The database table is a field and uniqueness standard for checking whether the CSV can be mapped downstream.

Acceptance checks should cover:

- Required fields: title, msg, publish_time.
- Required non-empty rate >= 99.5%.
- Record coverage >= 98.5% of expected list records where expected count can be measured.
- No duplicate records by `webname + href`.
- Date range traceability, normally recent one month when requested.
- All requested columns/boards are represented, not just one visible page.
- Incremental or breakpoint collection is supported through state tracking.

## Operating Workflow

1. Read the user-provided acceptance standard, requirement docs, spreadsheets, or current delivery folder.
2. Identify target websites and decide which websites are in scope. Respect explicit exclusions.
3. Inventory each website:
   - visible boards/columns,
   - list pages,
   - detail pages,
   - frontend JSON APIs,
   - pagination,
   - date filters,
   - anti-scraping controls.
4. Prefer public frontend JSON/API calls over brittle visual scraping when possible.
5. Build a small probe first: one board, one page, one detail.
6. Expand to all requested boards and the target date range.
7. Normalize records into the shared CSV fields.
8. Implement incremental collection:
   - keep a state JSON file,
   - remember latest publish date,
   - remember seen `href` and `raw_id`,
   - stop when repeated seen records indicate the previous collection boundary.
9. Generate delivery files per website.
10. Run verification and clean the final folder.

## Source Code Rules

Use one single Python file per website unless the user explicitly prefers a package. The single file should be readable, with Chinese docstrings/comments for every class and meaningful function.

The file should include:

- constants and output field list,
- `BidRecord` dataclass,
- HTTP client with headers, delay, optional proxy,
- state/checkpoint class,
- target-site spider class,
- HTML/text cleaning helpers,
- date normalization,
- CSV writer,
- field mapping writer,
- acceptance report builder,
- command-line `main()`.

Keep the source focused on collection, normalization, CSV output, field mapping, and acceptance reporting unless the user asks for a wider runtime.

Read `references/single_file_crawler_guide.md` before writing a crawler. Use `templates/single_site_crawler_template.py` as the starting skeleton when building a new site.

## Delivery Documents

For every website project, write:

- `部署文档/部署文档.md`: environment, dependency install command, full run command, date-range command, incremental command, output descriptions.
- `配置说明/配置说明.md`: proxy env var, request delay env var, state file path, board/API parameter locations.
- `字段映射表/field_mapping.csv`: source-to-output field mapping.
- `字段映射表/字段映射说明.md`: plain-language mapping against acceptance fields.
- `验收报告/acceptance_report.json`: machine-readable quality report.

Read `references/delivery_structure.md` and `references/acceptance_checklist.md` before final packaging.

## Final Verification

Before telling the user the package is ready:

- List final files and directories.
- Search final folder for forbidden leftovers.
- Confirm the final folder contains only the agreed delivery files.
- Confirm no out-of-scope website names.
- Confirm each site has the four required folders.
- Confirm each `完整源码` has exactly one main `*_爬虫.py` plus `requirements.txt`.
- Compile each Python file or otherwise syntax-check it.
- Count CSV records and compare with acceptance reports.
- Confirm acceptance flags pass or explain any failure plainly.

Use `scripts/validate_delivery.py` when available:

```bash
python scripts/validate_delivery.py "交付根目录"
```

## When the User Is Anxious About Files

Be explicit and calm. Explain which files are required and which are extras. If they say a file should not be there, remove it from the final delivery package unless it is truly required by the stated acceptance standard. The client-facing folder should be clean, boring, and easy to defend.
