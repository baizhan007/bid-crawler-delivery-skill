# 交付结构规范

本规范用于最终桌面交付文件夹。重点是“每个网站独立项目”，正式交付目标是源码直接写入 `a_bidcollect_info`。CSV 仅作为抽样验收材料，不再默认作为全量数据交付物。

## 顶层结构

```text
招投标爬虫交付_项目名/
├── 交付结构说明.md
├── 网站A/
└── 网站B/
```

顶层只放总体说明和网站目录。不要把源码、临时输出、样本文件混在顶层。

## 单个网站结构

```text
网站名称/
├── 完整源码/
│   ├── 网站名称_爬虫.py
│   └── requirements.txt
├── 部署文档/
│   └── 部署文档.md
├── 配置说明/
│   └── 配置说明.md
├── 字段映射表/
│   ├── field_mapping.csv
│   └── 字段映射说明.md
├── 验收样例/
│   └── sample_records.csv
└── 验收报告/
    └── acceptance_report.json
```

`验收样例` 用于少量抽样核对，可以为空或按用户要求不生成；正式运行以数据库入库为准。

## 完整源码

只放本网站可独立运行的源码和依赖清单：

```text
完整源码/
├── 网站名称_爬虫.py
└── requirements.txt
```

默认不要放：

- `bid_spider/`
- `__pycache__/`
- `output_final/`
- `.idea/`
- `.vscode/`
- 批量转换脚本
- 临时修复脚本
- 测试 demo
- 与当前网站无关的工具脚本

入库项目的 `requirements.txt` 通常包含：

```text
requests>=2.31.0
pymysql>=1.1.0
```

只有脚本真的用到 `beautifulsoup4`、`lxml`、`pandas` 等库时才加。

## 部署文档

必须包含：

- 项目说明。
- 采集范围。
- 本次交付日期范围。
- 环境要求。
- 依赖安装命令。
- 数据库表名和入库字段说明。
- 正式入库运行命令。
- 指定日期范围入库命令。
- 增量/断点入库命令。
- 抽样验证命令。
- 输出文件说明。

示例：

```markdown
## 正式入库运行

```powershell
python "网站名称_爬虫.py" --days 30 --to-db
```
```

## 配置说明

必须包含：

- `BID_DB_HOST`: 数据库地址。
- `BID_DB_PORT`: 数据库端口。
- `BID_DB_USER`: 数据库用户。
- `BID_DB_PASSWORD`: 数据库密码。
- `BID_DB_NAME`: 数据库名。
- `BID_DB_TABLE`: 表名，默认 `a_bidcollect_info`。
- `BID_SPIDER_DELAY`: 请求间隔。
- `BID_SPIDER_PROXY`: 代理 IP。
- `state/crawl_state.json`: 断点状态文件。
- 栏目参数在哪里改。
- 日期范围参数怎么改。

不要在文档里写真实生产密码。用占位符或环境变量说明。

## 字段映射表

`field_mapping.csv` 至少三列：

```text
字段,源网页/接口位置,说明
```

映射说明里要写清楚：

- `webname` 来自哪里。
- `href` 怎么构造，为什么复制到浏览器可打开。
- 正文 `msg` 来自哪里。
- `html` 怎么清洗。
- 发布时间来自哪里。
- `industry` 默认取什么。
- `identify_code` 怎么生成。
- `extra` 是否只保存在样本 CSV，不入正式库。

## 验收样例

默认只生成少量样本：

```text
验收样例/sample_records.csv
```

样本 CSV 使用 `utf-8-sig` 编码，方便 Excel 打开不乱码。样本行数通常每栏目 5 到 20 条，或由 `--sample-size`、`--limit-per-category` 控制。

不要把样本 CSV 描述为全量采集结果。

## 验收报告

每个网站一个：

```text
验收报告/acceptance_report.json
```

验收报告要能回答：

- 抽样或正式运行采了多少条。
- 是否重复。
- 必填字段完整率。
- 是否在日期范围内。
- `href` 是否完整、可追溯、可复制到浏览器打开。
- 数据库入库模式是否支持。
- 入库表、唯一键、写入字段是什么。
- 栏目覆盖率是否达标。

## 最终清理规则

交付前删除：

- `.idea`
- `.vscode`
- `__pycache__`
- `.pytest_cache`
- `output_smoke`
- `output_test`
- 临时截图
- 旧版本源码目录
- 不在本次范围的网站目录
- 本次交付范围外的额外文件
- 批量转换、临时修补、调试、测试辅助脚本
- 非采集结果文件中的 AI / ChatGPT / Codex / OpenAI / GPT 等过程痕迹

采集到的源站公告正文如果真实包含 “AI” 或 “大模型”，不属于过程痕迹，不要为了清理而篡改数据。

用户给甲方看的目录应该干净到“每个文件都能解释为什么存在”。
