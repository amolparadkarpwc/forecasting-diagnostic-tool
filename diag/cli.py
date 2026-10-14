"""Command line for the diagnostic MVP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from diag import __version__
from diag.runner import finalise_engagement, init_engagement, report_engagement, run_engagement


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diag",
        description="Forecasting data and model diagnostic tool (MVP). Deterministic, no network, no code execution.",
    )
    parser.add_argument("--version", action="version", version=f"diag {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create input/, work/, and output/ for an engagement")
    init.add_argument("engagement", help="Engagement folder")

    run = commands.add_parser("run", help="Intake, evidence, and provisional scores")
    run.add_argument("engagement")
    run.add_argument("--pack", required=True, help="Knowledge pack directory")

    finalise = commands.add_parser("finalise", help="Write the final results file")
    finalise.add_argument("engagement")
    finalise.add_argument("--pack", help="Knowledge pack directory (defaults to the pack used by run)")

    report = commands.add_parser("report", help="Write the HTML dashboard from results.json")
    report.add_argument("engagement")

    commands.add_parser("test", help="Run the MVP test suite")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required.", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            path = init_engagement(_path(args.engagement))
            print(f"Initialised {path}")
            print("Put client files in input/, then run: python -m diag run <engagement> --pack pack")
            return 0
        if args.command == "run":
            engagement = _path(args.engagement)
            results = run_engagement(engagement, _path(args.pack))
            print(f"Wrote {engagement / 'output' / 'inventory.json'}")
            print(f"Wrote {engagement / 'output' / 'evidence_log.json'}")
            print(f"Wrote {engagement / 'output' / 'results.json'}")
            print(results["overall"]["headline"])
            return 0
        if args.command == "finalise":
            engagement = _path(args.engagement)
            pack = _path(args.pack) if args.pack else None
            results = finalise_engagement(engagement, pack)
            print(f"Wrote {engagement / 'output' / 'results.json'}")
            print(results["overall"]["headline"])
            return 0
        if args.command == "report":
            dashboard = report_engagement(_path(args.engagement))
            print(f"Wrote {dashboard}")
            return 0
        if args.command == "test":
            import unittest

            suite = unittest.defaultTestLoader.discover("tests")
            outcome = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if outcome.wasSuccessful() else 1
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
