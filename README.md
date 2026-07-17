# BidCrawler Factory v1

面向招投标、政府采购和电子卖场项目的离线优先交付工具。它把站点脚手架、公开响应录制、断网回放、数据验收、结构变化检测和客户交付打包统一为 `bidfactory` CLI，同时保留 `bid-crawler-delivery` Skill 的一站一项目、单文件爬虫、中文文档和 `a_bidcollect_info` 入库约定。

工具不会绕过登录、验证码或访问控制。只采集公开且获准的数据，并遵守目标站点条款、`robots.txt` 和合理请求频率。

## 环境与安装

- Python 3.10 或更高版本
- `requests` 用于显式执行的 `capture` 和可选在线链接抽查
- `pytest` 仅用于开发测试

```powershell
cd D:\path\to\bid-crawler-delivery-skill
python -m pip install -e .
python -m pip install -e ".[dev]"
python -m bidfactory doctor --json
```

Windows 含中文文件时建议使用 `python -X utf8 -B`：`-X utf8` 避免系统默认 GBK 误读 UTF-8，`-B` 避免生成 `__pycache__`。

## 五分钟上手

下面假设 `D:\work` 是本地工作目录，目标 URL 已获得采集许可。

```powershell
# 1. 创建独立站点项目
python -X utf8 -B -m bidfactory new "示例采购网" --root D:\work

# 2. 编辑站点配置：填写 base_url、allowed_hosts、requests 和 expected_categories
notepad D:\work\示例采购网\site_config.json

# 3. 录制一次真实响应；这是流程中明确发起网络请求的步骤
python -X utf8 -B -m bidfactory capture D:\work\示例采购网\site_config.json --output D:\work\示例采购网\fixtures\latest

# 4. 断网回放并输出规范化记录
python -X utf8 -B -m bidfactory replay D:\work\示例采购网\fixtures\latest --adapter D:\work\示例采购网\adapter.py --output D:\work\示例采购网\artifacts\records.json

# 5. 重新计算验收指标，输出 validation.json 和 validation.html
python -X utf8 -B -m bidfactory validate D:\work\示例采购网\artifacts\records.json --output D:\work\示例采购网\reports

# 6. 验收通过后生成干净交付目录、ZIP 和 SHA-256 清单
python -X utf8 -B -m bidfactory package D:\work\示例采购网 --output D:\work\dist
```

`adapter.py` 必须把列表页和详情页响应映射为至少包含 `webname`、`href`、`msg`、`html`、`publish_time` 的记录。`href` 必须是浏览器可打开的完整 HTTP/HTTPS 详情 URL。

## 七个命令

### `new`

生成独立站点目录、单文件爬虫模板、适配器、配置、测试和文档骨架。目标已存在时拒绝覆盖。

```powershell
python -m bidfactory new <site_name> [--root DIR] [--template FILE]
```

### `capture`

按 `site_config.json` 录制公开 HTML/JSON 响应。限制主机、响应大小和重定向，写入前脱敏请求头、参数、正文及 URL 中的敏感值。输出目录已存在时拒绝覆盖。

```powershell
python -m bidfactory capture <site_config> [--output FIXTURE_DIR]
```

### `replay`

从本地 fixture 加载响应并调用站点适配器；回放期间网络请求会被强制阻断。

```powershell
python -m bidfactory replay <fixture_dir> [--adapter FILE] [--output records.json]
```

未指定 `--output` 时写入 `<fixture_dir>/artifacts/records.json`。

### `validate`

从 fixture、记录 JSON/CSV 或交付目录重新计算必填字段完整率、`webname + href` 重复、日期、栏目、正文质量和 URL 格式，并同时生成 JSON/HTML 报告。不会相信输入中的预计算布尔值。

```powershell
python -m bidfactory validate <target> [--adapter FILE] [--output DIR] `
  [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] `
  [--required-rate 0.995] [--check-links] [--link-limit 5] [--link-delay 0.5]
```

默认不访问网络。只有明确指定 `--check-links` 才会限量抽查链接；质量不通过时返回退出码 1。

### `diff`

比较两个 fixture 的 JSON 路径与类型，并检查 `dom_selectors` 的命中数量。字段删除、类型改变或选择器跌破最低命中数会标记为破坏性变化。

```powershell
python -m bidfactory diff <old_fixture> <new_fixture> [--output DIR]
```

兼容变化返回 0，破坏性变化返回 1；两种情况都会生成 `diff.json` 和 `diff.html`。

### `package`

从站点项目生成一站一项目客户交付目录、ZIP 和带 SHA-256 的 manifest。打包前重新验收记录并重新读取样本核对报告；不会仅相信报告中的 `true`。

```powershell
python -m bidfactory package <site_project> [--output DIR] [--force]
```

已有输出时默认拒绝覆盖；只有确认目标后才使用 `--force`。正式数据写入数据库，交付 CSV 仅保留最多 20 条验收样本。

### `doctor`

检查 Python、依赖、模板、目录写权限、Git/`gh` 和敏感环境变量风险。只显示敏感变量名，不显示其值。

```powershell
python -m bidfactory doctor [--workdir DIR] [--json]
```

警告不导致失败；缺少运行必需项时返回非零退出码。所有命令的配置或运行错误统一返回退出码 2。

## 站点配置示例

```json
{
  "schema_version": 1,
  "site_name": "示例采购网",
  "base_url": "https://procurement.example.gov.cn",
  "allowed_hosts": ["procurement.example.gov.cn"],
  "adapter": "adapter.py",
  "expected_categories": ["采购公告", "结果公告"],
  "dom_selectors": {
    "a.notice": {"min": 1},
    ".notice-content": {"min": 1}
  },
  "capture": {
    "timeout": 15,
    "delay": 0.5,
    "max_response_bytes": 5242880,
    "follow_redirects": false,
    "max_redirects": 5,
    "verify_tls": true
  },
  "requests": [
    {
      "id": "purchase-page-1",
      "role": "list",
      "category": "采购公告",
      "page": 1,
      "method": "GET",
      "path": "/api/notices",
      "params": {"category": "purchase", "page": 1},
      "response_type": "json"
    }
  ]
}
```

单个请求支持 `GET`/`POST`、`url` 或相对 `path`、`headers`、`params`、`json`、`data`、`role`、`category`、`page` 和期望状态配置。不要在配置中写入真实 Cookie、Authorization、Token、代理密码或数据库密码；需要认证或绕过访问控制的目标不在本工具范围内。

## Fixture 格式

Fixture 是可移植目录，不是网络缓存黑盒：

```text
fixtures/latest/
├── manifest.json
├── adapter.py              # capture 时保存的无敏感适配器快照（如已配置）
└── bodies/
    ├── 001_purchase-page-1.json
    └── 002_detail-p-100.html
```

`manifest.json` 使用 `schema_version: 1`，主要字段包括：

- `site_name`、`captured_at`、`allowed_hosts`
- `expected_categories`、`dom_selectors`、`date_range`
- `adapter`：相对路径和 callable 名称
- `entries`：按录制顺序保存 `id`、角色、栏目、页码、脱敏请求、状态码、安全响应头、正文相对路径、SHA-256 和耗时

正文必须位于 fixture 内；加载器会拒绝 `../` 路径逃逸。fixture 可以提交本地模拟数据或彻底脱敏的数据，不应提交客户真实响应和凭据。

## 验收与交付

默认必填字段完整率阈值为 99.5%。交付包包含：

```text
<站点>_交付/<站点>/
├── 完整源码/       # 恰好一个 *_爬虫.py 和 requirements.txt
├── 部署文档/
├── 配置说明/
├── 字段映射表/
├── 验收样例/       # 少量 sample_records.csv
└── 验收报告/       # 重新计算的 acceptance_report.json
```

交付校验会拒绝缓存、VCS 目录、多余源码、疑似硬编码凭据、语法错误、报告与样本不一致，以及未通过质量指标的数据。

## 安全边界

- 仅录制明确列入 `allowed_hosts` 的 HTTP/HTTPS 地址。
- 默认不跟随重定向；启用后每一次跳转仍检查目标主机。
- 录制时限制响应大小，只接受 HTML/JSON，并检查落盘文件中是否残留已知秘密。
- 回放阶段禁止 socket、`requests`、`urllib` 和常见 HTTP 客户端联网。
- 不写真实生产数据库；数据库密码和代理凭据仅通过运行环境注入。
- `--check-links` 是显式、限量、带延迟的在线抽查，不属于默认离线验收。

## 测试

```powershell
python -X utf8 -B -m pytest
```

测试只使用本地临时目录和内置模拟站点，不需要生产凭据。提交前还应执行：

```powershell
python -X utf8 -B -m bidfactory --help
python -X utf8 -B -m bidfactory doctor --json
git diff --check
```

## 故障排查

- `No module named pytest`：先安装开发依赖 `python -m pip install -e ".[dev]"`。
- `Capture output already exists`：为新录制指定新目录；不要手工覆盖可追溯 fixture。
- `host is not allowed`：把获准主机准确加入 `allowed_hosts`，不要用通配符扩大范围。
- `manifest has no response entries`：先配置至少一个请求并完成 `capture`。
- 回放没有规范化记录：在 `adapter.py` 中实现列表/详情关联和字段映射。
- `validate` 返回 1：打开同目录的 `validation.html`，按缺字段、重复、日期、URL、栏目或正文问题修复。
- `diff` 返回 1：这是检测到破坏性变化的预期信号，查看 `diff.json` 后更新适配器并重新回归。
- `package` 拒绝交付：先运行 `validate`，不要手工把报告布尔值改成通过。
- Windows 中文解码错误：使用 `python -X utf8 -B` 并确认文件实际保存为 UTF-8。
- `doctor` 报 `gh` warning：不影响本地开发；仅在创建 GitHub PR 时需要安装 GitHub CLI。

## Skill 使用

将本目录安装为 `bid-crawler-delivery` Skill 后，可用“每个网站独立项目”“直接写入 `a_bidcollect_info`”“增量采集”“href 可打开校验”“生成字段映射和验收报告”等请求触发完整交付工作流。详细执行约定见 `SKILL.md` 与 `references/`。
