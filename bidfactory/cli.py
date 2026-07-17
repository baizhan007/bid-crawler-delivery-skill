"""Unified command-line entry point for BidCrawler Factory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .diffing import diff_fixtures
from .doctor import run_doctor
from .errors import FactoryError
from .packaging import package_site
from .scaffold import new_site
from .validation import validate_target


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser so help output is also testable."""

    parser = argparse.ArgumentParser(prog="bidfactory", description="招投标爬虫录制、回放、验收与交付工具")
    parser.add_argument("--version", action="version", version="bidfactory 1.0.0")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="生成独立站点开发项目")
    new.add_argument("site_name")
    new.add_argument("--root", type=Path, default=Path.cwd())
    new.add_argument("--template", type=Path)

    capture = commands.add_parser("capture", help="按配置录制脱敏 HTTP fixture")
    capture.add_argument("site_config", type=Path)
    capture.add_argument("--output", type=Path)

    replay = commands.add_parser("replay", help="在强制禁网环境中回放 fixture")
    replay.add_argument("fixture_dir", type=Path)
    replay.add_argument("--adapter", type=Path)
    replay.add_argument("--output", type=Path)

    validate = commands.add_parser("validate", help="重新计算数据验收指标")
    validate.add_argument("target", type=Path)
    validate.add_argument("--adapter", type=Path)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--start-date")
    validate.add_argument("--end-date")
    validate.add_argument("--required-rate", type=float, default=0.995)
    validate.add_argument("--check-links", action="store_true")
    validate.add_argument("--link-limit", type=int, default=5)
    validate.add_argument("--link-delay", type=float, default=0.5)

    diff = commands.add_parser("diff", help="检测 JSON Schema 和关键 DOM 选择器变化")
    diff.add_argument("old_fixture", type=Path)
    diff.add_argument("new_fixture", type=Path)
    diff.add_argument("--output", type=Path)

    package = commands.add_parser("package", help="生成并验证一站一项目客户交付包")
    package.add_argument("site_project", type=Path)
    package.add_argument("--output", type=Path)
    package.add_argument("--force", action="store_true")

    doctor = commands.add_parser("doctor", help="检查运行环境和敏感配置风险")
    doctor.add_argument("--workdir", type=Path)
    doctor.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "new":
        path = new_site(args.site_name, args.root, args.template)
        print(f"站点项目已生成：{path}")
        return 0
    if args.command == "capture":
        from .capture import capture_from_config

        path = capture_from_config(args.site_config, output_dir=args.output)
        print(f"Fixture 已录制：{path}")
        return 0
    if args.command == "replay":
        from .replay import replay_fixture

        output = args.output or (args.fixture_dir / "artifacts" / "records.json")
        records = replay_fixture(args.fixture_dir, adapter_path=args.adapter, output_path=output)
        print(f"离线回放完成：{len(records)} 条 -> {output}")
        return 0
    if args.command == "validate":
        report, output = validate_target(
            args.target,
            adapter=args.adapter,
            output_dir=args.output,
            start_date=args.start_date,
            end_date=args.end_date,
            required_rate=args.required_rate,
            check_links=args.check_links,
            link_limit=args.link_limit,
            link_delay=args.link_delay,
        )
        print(f"验收报告：{output}")
        return 0 if report["quality_flags"]["overall_pass"] else 1
    if args.command == "diff":
        report, output = diff_fixtures(args.old_fixture, args.new_fixture, args.output)
        print(f"差异报告：{output}")
        return 1 if report["breaking"] else 0
    if args.command == "package":
        delivery, zip_path, manifest = package_site(args.site_project, args.output, args.force)
        print(f"交付目录：{delivery}\n压缩包：{zip_path}\n清单：{manifest}")
        return 0
    if args.command == "doctor":
        report = run_doctor(args.workdir)
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for item in report["checks"]:
                status = "PASS" if item["passed"] else item["severity"].upper()
                print(f"[{status}] {item['name']}: {item['detail']}")
        return 0 if report["ok"] else 1
    raise FactoryError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments, execute a command, and use stable non-zero failures."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = _run(args)
    except FactoryError as exc:
        print(f"bidfactory: {exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
