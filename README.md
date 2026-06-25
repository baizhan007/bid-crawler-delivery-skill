# Bid Crawler Delivery Skill

一个用于 Codex / Claude Code 的招投标网站爬虫交付 Skill。

它把“分析一个招投标/采购/标讯网站，并交付给甲方”的流程固化成可复用规范：每个网站一个独立项目、先确认采购相关栏目、单文件 Python 爬虫、中文注释、直接写入 `a_bidcollect_info`、href 可打开校验、字段映射、配置说明、部署文档、验收报告。CSV 只作为少量样本用于快速验证，不再作为默认全量交付物。

## 适用场景

- 招投标、采购公告、标讯、开标大厅、电子卖场等网站采集。
- 甲方要求程序部署后直接入库。
- 需要对齐 `a_bidcollect_info` 表结构。
- 需要保证 `href` 复制到浏览器可打开详情页。
- 需要支持增量采集或断点采集。
- 需要未来批量流程化开发很多网站。
- 需要每个网站独立项目，方便甲方验收和后续维护。

## 目录

```text
bid-crawler-delivery-skill/
├── SKILL.md
├── README.md
├── LICENSE
├── references/
│   ├── single_file_crawler_guide.md
│   ├── database_ingestion.md
│   ├── delivery_structure.md
│   └── acceptance_checklist.md
├── templates/
│   └── single_site_crawler_template.py
├── scripts/
│   ├── scaffold_site_project.py
│   └── validate_delivery.py
└── evals/
    └── evals.json
```

## 安装使用

把本目录复制到 Codex 的 skills 目录，或在支持自定义 Skill 的环境中引用该目录。

Windows 下如果终端显示中文路径乱码，通常是控制台编码显示问题，不代表文件内容损坏；可使用 UTF-8 终端，或用英文临时目录做脚手架测试。

常见触发话术：

- “按上次招投标交付模式做这个新网站”
- “这个标讯网站爬虫要符合验收标准，直接入库”
- “每个网站独立项目，源码一个 py，中文注释”
- “写入 a_bidcollect_info，href 要能复制到浏览器打开”
- “先确认栏目，再生成入库源码、字段映射、部署文档和验收报告”

## 交付原则

正式交付目标是源码直接写入 `a_bidcollect_info`。样本 CSV 只用于开发和验收抽查。最终交付目录保持清晰克制，只保留甲方验收需要的源码、样本、文档和报告。
