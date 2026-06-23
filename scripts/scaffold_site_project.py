from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """写入 UTF-8 文本文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def scaffold(root: Path, site_name: str, template: Path) -> None:
    """生成一个符合交付规范的网站项目骨架。"""

    site_dir = root / site_name
    source_dir = site_dir / "完整源码"
    for name in ["完整源码", "部署文档", "配置说明", "字段映射表", "采集结果", "验收报告"]:
        (site_dir / name).mkdir(parents=True, exist_ok=True)

    script_path = source_dir / f"{site_name}_爬虫.py"
    shutil.copyfile(template, script_path)
    write_text(source_dir / "requirements.txt", "requests>=2.31.0\n")

    write_text(
        site_dir / "部署文档" / "部署文档.md",
        f"""# {site_name} 部署文档

## 项目说明

本项目为 {site_name} 独立爬虫项目。

## 环境要求

- Python 3.10+
- 网络可访问目标网站

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 正式全量运行

```powershell
python "{site_name}_爬虫.py" --days 30 --output-dir output_final
```

## 指定日期范围运行

```powershell
python "{site_name}_爬虫.py" --start-date 2026-05-24 --end-date 2026-06-22 --output-dir output_final
```

## 增量和断点运行

```powershell
python "{site_name}_爬虫.py" --incremental --days 30 --output-dir output_incremental
```

## 输出说明

- `采集结果/{site_name}.csv`：最终交付 CSV。
- `字段映射表/field_mapping.csv`：字段映射。
- `验收报告/acceptance_report.json`：验收报告。
""",
    )
    write_text(
        site_dir / "配置说明" / "配置说明.md",
        f"""# {site_name} 配置说明

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

默认状态文件：`state/crawl_state.json`。

## 栏目配置

栏目配置位于 `完整源码/{site_name}_爬虫.py`。
""",
    )
    write_text(
        site_dir / "字段映射表" / "字段映射说明.md",
        f"""# {site_name} 字段映射说明

本文件用于说明 CSV 字段与源网页/接口字段的对应关系。开发完成后补齐每个字段来源。

默认数据交付物为 CSV，不单独交付 SQL 文件。
""",
    )


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="生成招投标网站独立交付项目骨架")
    parser.add_argument("root", help="交付根目录")
    parser.add_argument("site_name", help="网站名称")
    parser.add_argument("--template", default=str(Path(__file__).resolve().parents[1] / "templates" / "single_site_crawler_template.py"))
    args = parser.parse_args()
    root = Path(args.root)
    template = Path(args.template)
    if not template.exists():
        raise SystemExit(f"模板不存在：{template}")
    scaffold(root, args.site_name, template)
    print(f"已生成：{root / args.site_name}")


if __name__ == "__main__":
    main()

