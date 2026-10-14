"""Command line entry points for the diagnostic MVP."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from diag.engine import init_engagement, report_engagement, run_engagement
from diag.packload import PackError


def main(argv: list[str] | None = None) -> int:
    """Run the diag command line. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="diag", description="Forecasting data and model diagnostic tool")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Create an engagement folder")
    init_parser.add_argument("engagement")

    run_parser = sub.add_parser("run", help="Inventory inputs and score the knowledge pack")
    run_parser.add_argument("engagement")
    run_parser.add_argument("--pack", required=True)

    report_parser = sub.add_parser("report", help="Write the HTML dashboard")
    report_parser.add_argument("engagement")

    demo_parser = sub.add_parser("demo", help="Copy a planted scenario and run it")
    demo_parser.add_argument("scenario", choices=["leaky"])

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            path = init_engagement(_resolve(args.engagement))
            print(path)
            return 0
        if args.command == "run":
            run_engagement(_resolve(args.engagement), _resolve(args.pack))
            print(_resolve(args.engagement) / "output" / "results.json")
            return 0
        if args.command == "report":
            dashboard = report_engagement(_resolve(args.engagement))
            print(dashboard)
            return 0
        if args.command == "demo":
            return _demo(args.scenario)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


def _demo(scenario: str) -> int:
    if scenario != "leaky":
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    source = root / "tests" / "planted" / "leaky_forecast"
    if not source.is_dir():
        raise FileNotFoundError(f"planted scenario not found: {source}")
    engagement = _resolve("demo")
    init_engagement(engagement)
    _replace_tree(source, engagement / "input")
    run_engagement(engagement, _resolve("pack"))
    dashboard = report_engagement(engagement)
    print(dashboard)
    return 0


def _replace_tree(source: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)


def _resolve(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path
