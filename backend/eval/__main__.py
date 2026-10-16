"""CLI entry point: `python -m eval ...` from the `backend/` directory.

    python -m eval run --suite local --stages note
    python -m eval run --suite primock57 --stages asr,note,judge --limit 10
    python -m eval compare --baseline results/<a>.json --current results/<b>.json
    python -m eval list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from console import configure_console
from eval.datasets import SUITES, load_suite
from eval.runner import RESULTS_DIR, RunConfig, compare_reports, run_suite, save_report


def _cmd_run(args: argparse.Namespace) -> int:
    stages = tuple(stage.strip() for stage in args.stages.split(",") if stage.strip())
    try:
        cases = load_suite(args.suite)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not cases:
        print(f"error: suite '{args.suite}' contains no cases.", file=sys.stderr)
        return 2

    report = run_suite(cases, RunConfig(
        suite=args.suite,
        stages=stages,
        limit=args.limit,
        offset=args.offset,
        label=args.label,
        results_dir=Path(args.results_dir),
        audio_cache_dir=Path(args.audio_cache) if args.audio_cache else None,
    ))
    path = save_report(report, Path(args.results_dir))

    print(f"\n{report['case_count']} cases in {report['runtime_seconds']}s -> {path}")
    if report["failed_cases"]:
        print(f"failed: {', '.join(report['failed_cases'])}")
    _print_aggregate(report["aggregate"])

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        comparison = compare_reports(baseline, report, tolerance=args.tolerance)
        _print_comparison(comparison)
        if comparison["regressions"] and args.fail_on_regression:
            return 1
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    comparison = compare_reports(baseline, current, tolerance=args.tolerance)
    _print_comparison(comparison)
    return 1 if (comparison["regressions"] and args.fail_on_regression) else 0


def _cmd_list(_: argparse.Namespace) -> int:
    for name in sorted(SUITES):
        try:
            count = f"{len(load_suite(name))} cases"
        except (FileNotFoundError, KeyError) as exc:
            count = f"unavailable ({type(exc).__name__})"
        print(f"  {name:<12} {count}")
    return 0


def _print_aggregate(aggregate: dict) -> None:
    if not aggregate:
        print("no metrics produced (were the stages and references right?)")
        return
    print("\nmetric                          mean      n")
    print("-" * 46)
    for name, entry in aggregate.items():
        print(f"{name:<30} {entry['mean']:>8}  {entry['n']:>5}")


def _print_comparison(comparison: dict) -> None:
    if comparison.get("comparable_case_counts") is False:
        print(
            f"\nWARNING: baseline ran {comparison['baseline_case_count']} cases, "
            f"this run {comparison['current_case_count']}. The deltas below are "
            "not like-for-like; re-run the baseline config on the same cases."
        )
    print("\nmetric                        before     after     delta")
    print("-" * 58)
    for name, entry in comparison["deltas"].items():
        marker = "  <-- regression" if name in comparison["regressions"] else ""
        print(f"{name:<28} {entry['before']:>8} {entry['after']:>9} {entry['delta']:>9}{marker}")
    if comparison["regressions"]:
        print(f"\n{len(comparison['regressions'])} regression(s): {', '.join(comparison['regressions'])}")
    else:
        print("\nno regressions")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description="MediScribe AI evaluation harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a suite and write a report")
    run.add_argument("--suite", default="local", help=f"one of: {', '.join(sorted(SUITES))}")
    run.add_argument("--stages", default="note", help="comma-separated: asr,note,judge")
    run.add_argument("--limit", type=int, default=None, help="only the first N cases")
    run.add_argument("--offset", type=int, default=0,
                     help="skip the first N cases, for held-out evaluation")
    run.add_argument("--label", default="", help="label for the result filename")
    run.add_argument("--results-dir", default=str(RESULTS_DIR))
    run.add_argument(
        "--audio-cache", default=None,
        help="keep downloaded audio here for repeat runs (default: fetch and delete per case)",
    )
    run.add_argument("--baseline", default=None, help="report to compare against")
    run.add_argument("--tolerance", type=float, default=0.01)
    run.add_argument("--fail-on-regression", action="store_true", help="exit 1 if a metric regresses")
    run.set_defaults(func=_cmd_run)

    compare = subparsers.add_parser("compare", help="diff two existing reports")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--current", required=True)
    compare.add_argument("--tolerance", type=float, default=0.01)
    compare.add_argument("--fail-on-regression", action="store_true")
    compare.set_defaults(func=_cmd_compare)

    listing = subparsers.add_parser("list", help="show available suites and case counts")
    listing.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
