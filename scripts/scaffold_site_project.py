from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """写入 UTF-8 文本文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_site_name(site_name: str) -> str:
    """校验网站名称，避免路径穿越和 Windows 非法文件名。"""

    site_name = site_name.strip()
    if not site_name or site_name in {".", ".."}:
        raise ValueError("网站名称不能为空或点路径。")
    if Path(site_name).name != site_name or re.search(r'[\\/:*?"<>|]', site_name):
        raise ValueError("网站名称不能包含路径分隔符或 Windows 非法字符。")
    if site_name.endswith((" ", ".")):
        raise ValueError("网站名称不能以空格或句点结尾。")
    return site_name


def render_template(template: Path, site_name: str) -> str:
    """替换模板中的站点标识和网站名称常量。"""

    text = template.read_text(encoding="utf-8")
    site_key = f"site_{hashlib.sha256(site_name.encode('utf-8')).hexdigest()[:12]}"
    replacements = {
        'SITE_KEY = "example_site"': f"SITE_KEY = {json.dumps(site_key, ensure_ascii=False)}",
        'WEBNAME = "示例招投标网站"': f"WEBNAME = {json.dumps(site_name, ensure_ascii=False)}",
    }
    for old, new in replacements.items():
        if old not in text:
            raise ValueError(f"模板缺少预期占位符：{old}")
        text = text.replace(old, new, 1)
    return text


def scaffold(root: Path, site_name: str, template: Path) -> None:
    """生成一个符合入库交付规范的网站项目骨架。"""

    site_name = validate_site_name(site_name)
    site_dir = root / site_name
    if site_dir.exists():
        raise FileExistsError(f"网站项目已存在，拒绝覆盖：{site_dir}")
    source_dir = site_dir / "完整源码"
    for name in ["完整源码", "部署文档", "配置说明", "字段映射表", "验收样例", "验收报告"]:
        (site_dir / name).mkdir(parents=True, exist_ok=True)

    script_path = source_dir / f"{site_name}_爬虫.py"
    write_text(script_path, render_template(template, site_name))
    write_text(source_dir / "requirements.txt", "requests>=2.31.0\npymysql>=1.1.0\n")

    structure_file = root / "交付结构说明.md"
    if not structure_file.exists():
        write_text(
            structure_file,
            "# 交付结构说明\n\n每个网站均为独立项目；完整源码只包含单文件爬虫和 requirements.txt。\n",
        )

    write_text(
        site_dir / "部署文档" / "部署文档.md",
        f"""# {site_name} 部署文档

## 项目说明

本项目为 {site_name} 独立爬虫项目。正式交付方式为写入数据库表 `a_bidcollect_info`，样本 CSV 仅用于快速验收抽查。

## 环境要求

- Python 3.10+
- 网络可访问目标网站
- 可连接 MySQL 数据库

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 数据库配置

```powershell
$env:BID_DB_HOST = "127.0.0.1"
$env:BID_DB_PORT = "3306"
$env:BID_DB_USER = "your_user"
$env:BID_DB_PASSWORD = "your_password"
$env:BID_DB_NAME = "your_database"
```

## 正式入库运行

```powershell
python "{site_name}_爬虫.py" --days 30 --to-db
```

## 指定日期范围入库

```powershell
python "{site_name}_爬虫.py" --start-date 2026-05-24 --end-date 2026-06-22 --to-db
```

## 增量和断点入库

```powershell
python "{site_name}_爬虫.py" --incremental --days 30 --to-db
```

## 抽样验证

```powershell
python "{site_name}_爬虫.py" --days 30 --max-pages 1 --limit-per-category 10 --sample-dir "..\\验收样例" --field-mapping-file "..\\字段映射表\\field_mapping.csv" --report-file "..\\验收报告\\acceptance_report.json"
```

## 输出说明

- `完整源码/{site_name}_爬虫.py`：单文件爬虫源码。
- `字段映射表/field_mapping.csv`：字段映射。
- `验收样例/*.csv`：少量样本，用于核对字段和 href，不是全量正式交付数据。
- `验收报告/acceptance_report.json`：验收报告。
- `运行状态/crawl_state.json`：成功入库或成功写出样本后生成的断点文件，不放进完整源码目录。
""",
    )
    write_text(
        site_dir / "配置说明" / "配置说明.md",
        f"""# {site_name} 配置说明

## 数据库配置

支持环境变量：`BID_DB_HOST`、`BID_DB_PORT`、`BID_DB_USER`、`BID_DB_PASSWORD`、`BID_DB_NAME`、`BID_DB_TABLE`。

默认表名：`a_bidcollect_info`。

重复数据默认按 `webname + href` 覆盖更新；追加 `--db-skip-existing` 后只插入新增记录。

## 请求间隔

通过环境变量 `BID_SPIDER_DELAY` 配置，单位为秒，默认 0.2。

```powershell
$env:BID_SPIDER_DELAY = "0.2"
```

## 代理 IP

通过环境变量 `BID_SPIDER_PROXY` 配置。

```powershell
$env:BID_SPIDER_PROXY = "http://127.0.0.1:7890"
```

## 断点状态文件

默认状态文件：`运行状态/crawl_state.json`，位于网站项目根目录；也可用 `--state-file` 覆盖。

## 栏目配置

栏目配置位于 `完整源码/{site_name}_爬虫.py`。
""",
    )
    write_text(
        site_dir / "字段映射表" / "字段映射说明.md",
        f"""# {site_name} 字段映射说明

本文件用于说明入库字段与源网页/接口字段的对应关系。开发完成后补齐每个字段来源。

`href` 必须是浏览器可打开的详情页 URL，和 `webname` 组成唯一键。

样本 CSV 只用于验收抽查，不作为正式全量数据交付物。
""",
    )
    write_text(
        site_dir / "字段映射表" / "field_mapping.csv",
        "字段,源网页/接口位置,说明\nwebname,站点配置 WEBNAME,网站名称\nhref,详情页路由,浏览器可打开详情页 URL\nmsg,详情正文,纯文本正文\nhtml,详情正文,安全清洗后的正文 HTML\npublish_time,列表或详情发布时间,YYYY-MM-DD\n",
    )


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="生成招投标网站独立入库交付项目骨架")
    parser.add_argument("root", help="交付根目录")
    parser.add_argument("site_name", help="网站名称")
    parser.add_argument("--template", default=str(Path(__file__).resolve().parents[1] / "templates" / "single_site_crawler_template.py"))
    args = parser.parse_args()
    root = Path(args.root)
    template = Path(args.template)
    if not template.exists():
        raise SystemExit(f"模板不存在：{template}")
    try:
        scaffold(root, args.site_name, template)
    except (FileExistsError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"已生成：{root / args.site_name}")


if __name__ == "__main__":
    main()
