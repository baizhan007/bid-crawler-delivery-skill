# 数据库入库规范

本规范用于甲方要求“程序直接入库”的招投标爬虫。正式交付默认写入 `a_bidcollect_info`，CSV 仅用于抽样验证。

## 目标表

默认目标表：`a_bidcollect_info`。

程序只写这些字段：

```text
webname, href, msg, html, publish_time,
industry, from_auto_script, identify_code, etl_flag
```

不要手动写：

```text
id, create_time, update_time
```

这三个字段由数据库默认值、主键和自动更新时间维护。

## 字段映射

- `webname`: 网站名称常量。
- `href`: 浏览器可打开详情页 URL，和 `webname` 组成唯一键。
- `msg`: 正文纯文本。
- `html`: 正文清洗 HTML，普通正文可保留文本，表格保留 `table/tr/td/th` 等结构。
- `publish_time`: `YYYY-MM-DD` 或 `None`。
- `industry`: 可用栏目/category、行业分类或空值；下游可覆盖。
- `from_auto_script`: 默认 `1`。
- `identify_code`: 默认 `sha256(webname|href)[:32]` 或甲方指定规则。
- `etl_flag`: 默认 `0`。

## 命令行参数

源码必须支持：

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

同时支持环境变量：

```text
BID_DB_HOST
BID_DB_PORT
BID_DB_USER
BID_DB_PASSWORD
BID_DB_NAME
BID_DB_TABLE
```

`--db-table` 默认 `a_bidcollect_info`。

## 写入策略

默认使用唯一键 `webname + href` 做 upsert：

```sql
INSERT INTO a_bidcollect_info (...)
VALUES (...)
ON DUPLICATE KEY UPDATE
  msg = VALUES(msg),
  html = VALUES(html),
  publish_time = VALUES(publish_time),
  industry = VALUES(industry),
  from_auto_script = VALUES(from_auto_script),
  identify_code = VALUES(identify_code),
  etl_flag = VALUES(etl_flag)
```

当用户要求只插入新增记录时，`--db-skip-existing` 使用 `INSERT IGNORE`。

## 依赖

`requirements.txt` 在入库项目中包含：

```text
pymysql>=1.1.0
```

为了保持 CSV 抽样或无库试跑可用，`pymysql` 应延迟导入：只在 `--to-db` 开启时导入并连接数据库。

## 快速验证

开发阶段不要为了验证而默认跑全量 CSV。推荐：

```powershell
python "网站_爬虫.py" --days 30 --max-pages 1 --limit-per-category 10 --sample-csv "..\验收样例\sample_records.csv"
```

有测试库时再跑少量入库：

```powershell
python "网站_爬虫.py" --days 30 --max-pages 1 --limit-per-category 10 --to-db
```

验收报告应记录：

- `database_mode_supported`
- `db_table`
- `db_unique_key`
- `db_write_fields`
- `href_browser_openable`
- `sample_only`
