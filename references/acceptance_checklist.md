# 验收检查清单

交付前逐项检查，不要只看程序能不能跑。默认正式交付是入库源码，样本 CSV 只用于快速核验。

## 范围检查

- [ ] 只包含用户要求的网站。
- [ ] 明确排除的网站没有残留目录、文件、文档描述。
- [ ] 每个网站数据和源码分开。
- [ ] 每个网站按确认采集的采购相关栏目实现采集。
- [ ] 日期范围写清楚，避免“最近一个月”这种相对表达。
- [ ] 样本 CSV 如存在，只标注为抽样验收，不标注为全量结果。

## 目录检查

- [ ] 每个网站都有 `完整源码`。
- [ ] 每个网站都有 `部署文档`。
- [ ] 每个网站都有 `配置说明`。
- [ ] 每个网站都有 `字段映射表`。
- [ ] 每个网站都有 `验收报告`。
- [ ] 顶层有 `交付结构说明.md`。
- [ ] `验收样例` 如存在，只放样本文件。

## 源码检查

- [ ] 每个网站源码是独立单文件 `*_爬虫.py`。
- [ ] `完整源码` 中只有一个 `*_爬虫.py` 和 `requirements.txt`。
- [ ] 不存在批量转换、临时修复、测试 demo、debug helper 等额外脚本。
- [ ] 类和函数有中文 docstring。
- [ ] 关键业务逻辑有中文注释。
- [ ] 支持 `--days`。
- [ ] 支持 `--start-date` 和 `--end-date`。
- [ ] 支持 `--incremental`。
- [ ] 支持 `--state-file`。
- [ ] 支持 `--incremental-stop-seen`。
- [ ] 支持代理 `BID_SPIDER_PROXY`。
- [ ] 支持请求间隔 `BID_SPIDER_DELAY`。
- [ ] 支持快速验证参数，如 `--limit`、`--limit-per-category`、`--max-pages`、`--sample-csv`。
- [ ] 支持 `--to-db`。
- [ ] 支持 `--db-host`、`--db-port`、`--db-user`、`--db-password`、`--db-name`、`--db-table`。
- [ ] 支持 `--db-skip-existing`。
- [ ] `pymysql` 只在入库模式启用时延迟导入。

## 数据库检查

- [ ] 默认表名为 `a_bidcollect_info`。
- [ ] 正式入库只写 `webname, href, msg, html, publish_time, industry, from_auto_script, identify_code, etl_flag`。
- [ ] 不手写 `id`、`create_time`、`update_time`。
- [ ] 默认按 `webname + href` 使用 upsert。
- [ ] `--db-skip-existing` 可改为只插入新增记录。
- [ ] `requirements.txt` 包含 `pymysql>=1.1.0`。
- [ ] 部署文档包含正式入库命令。
- [ ] 配置说明包含数据库环境变量。

## href 检查

- [ ] `href` 非空。
- [ ] `href` 是完整 `http/https` URL。
- [ ] `href` 复制到浏览器能打开详情页。
- [ ] `href` 不是相对路径。
- [ ] `href` 不是裸 ID。
- [ ] `href` 不是缺参 hash 路由。
- [ ] `href` 不是仅供程序调用的 API URL，除非客户明确接受。
- [ ] `webname + href` 无重复。

## 样本 CSV 检查

- [ ] 样本 CSV 编码为 `utf-8-sig`。
- [ ] 样本 CSV 包含 `webname`。
- [ ] 样本 CSV 包含 `href`。
- [ ] 样本 CSV 包含 `title`。
- [ ] 样本 CSV 包含 `publish_time`。
- [ ] 样本 CSV 包含 `msg`。
- [ ] 样本 CSV 包含 `html`。
- [ ] 样本行数足够验证字段和链接，但不是默认全量结果。
- [ ] 不为本次 0 条栏目生成空样本 CSV。

## 栏目覆盖检查

- [ ] 用户要求的每个栏目都实现采集。
- [ ] 正式采集前已向用户反馈候选采购相关栏目，并按确认范围执行。
- [ ] “查看更多”等隐藏或二级列表已检查。
- [ ] 如果某个网站近一个月无数据，文档里说明原因，并按用户要求决定是否跳过。
- [ ] 如果源站有总数，验收报告记录 expected/fetched。
- [ ] 覆盖率 >= 98.5%，或说明源站无法测量总数。

## 文档检查

- [ ] 部署文档命令可直接复制运行。
- [ ] 部署文档包含正式入库命令和抽样验证命令。
- [ ] 配置说明写清数据库、代理和请求间隔怎么改。
- [ ] 字段映射说明能追溯每个字段来自哪里。
- [ ] 验收报告 `overall_pass` 为 true，或明确解释失败原因。
- [ ] 文档不再提旧包、旧模块、不用爬的网站或全量 CSV 默认交付。

## 清理检查

运行最终搜索：

```powershell
rg -n "python -m|bid_spider|__pycache__|\\.idea|\\.vscode|output_smoke|output_test|批量转换|临时|debug|demo|ChatGPT|Codex|OpenAI|GPT" "交付根目录"
```

如果不是用户明确要求的内容，搜索结果应为空。采集结果中源站真实公告文本包含 “AI/大模型/GPT” 时，不要篡改原始数据，但应确认非采集结果文件没有过程痕迹。

## 最终汇报

向用户汇报时只讲高信号内容：

- 交付目录路径。
- 每个网站源码和文档是否齐全。
- 是否支持入库。
- href 是否已检查。
- 样本验证结果。
- 是否去掉无关文件。
- 仍需用户或客户配置的数据库连接信息。
