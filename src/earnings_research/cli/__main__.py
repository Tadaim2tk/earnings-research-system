"""Command-line interface for Earnings Research System validation."""

import argparse
import json
import sys
from pathlib import Path

from earnings_research.monitoring.operational_cli import (
    build_handoff,
    fetch_state,
    notify_state,
    plan_registry,
    run_offline,
    run_live,
    verify_state,
)
from earnings_research.validation.validator import load_spec, validate_dataset, validate_file


def main(argv=None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(prog="python -m earnings_research.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a directory of expected CSV files.")
    validate_parser.add_argument("path", type=Path)

    file_parser = subparsers.add_parser("validate-file", help="Validate one CSV file against its matching schema.")
    file_parser.add_argument("path", type=Path)

    schema_parser = subparsers.add_parser("show-schema", help="Print one schema as JSON.")
    schema_parser.add_argument("table")

    plan_parser = subparsers.add_parser("monitor-plan", help="Plan active targets from a read-only registry.")
    plan_parser.add_argument("registry", type=Path)
    plan_parser.add_argument("--target-id")
    plan_parser.add_argument("--fixture-name")
    plan_parser.add_argument("--planned-at")
    plan_parser.add_argument("--force", action="store_true")

    fetch_parser = subparsers.add_parser("monitor-fetch-state", help="Fetch and verify prior GitHub artifact state.")
    fetch_parser.add_argument("--repository", required=True)
    fetch_parser.add_argument("--target-id", required=True)
    fetch_parser.add_argument("--output", required=True, type=Path)

    run_parser = subparsers.add_parser("monitor-run", help="Run the offline-compatible operational monitor.")
    run_parser.add_argument("--registry", required=True, type=Path)
    run_parser.add_argument("--target-id", required=True)
    run_parser.add_argument("--fixture-dir", required=True, type=Path)
    run_parser.add_argument("--fixture-name", required=True)
    run_parser.add_argument("--previous-dir", type=Path)
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--started-at", required=True)
    run_parser.add_argument("--finished-at", required=True)
    run_parser.add_argument("--event-date")

    live_parser = subparsers.add_parser("monitor-run-live", help="Run one authorized live monitor target.")
    live_parser.add_argument("--registry", required=True, type=Path)
    live_parser.add_argument("--target-id", required=True)
    live_parser.add_argument("--previous-dir", type=Path)
    live_parser.add_argument("--output", required=True, type=Path)
    live_parser.add_argument("--run-id", required=True)
    live_parser.add_argument("--started-at", required=True)
    live_parser.add_argument("--finished-at", required=True)

    handoff_parser = subparsers.add_parser("monitor-build-handoff", help="Build a research handoff for an autonomous change.")
    handoff_parser.add_argument("path", type=Path)
    handoff_parser.add_argument("--output", required=True, type=Path)

    verify_parser = subparsers.add_parser("monitor-verify-bundle", help="Verify one committed monitor bundle.")
    verify_parser.add_argument("path", type=Path)

    notify_parser = subparsers.add_parser("monitor-notify", help="Send one deduplicated Issue notification.")
    notify_parser.add_argument("path", type=Path)
    notify_parser.add_argument("--repository", required=True)
    notify_parser.add_argument("--receipt", required=True, type=Path)
    notify_parser.add_argument("--recorded-at", required=True)

    args = parser.parse_args(argv)

    if args.command == "validate":
        report = validate_dataset(args.path)
        return _print_report(report)
    if args.command == "validate-file":
        try:
            report = validate_file(args.path)
        except (FileNotFoundError, ValueError) as exc:
            print("Validation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
        return _print_report(report)
    if args.command == "show-schema":
        spec = load_spec(args.table)
        print(json.dumps(spec.model_dump(), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "monitor-plan":
            return plan_registry(
                args.registry,
                args.target_id,
                args.fixture_name,
                args.planned_at,
                args.force,
            )
        if args.command == "monitor-fetch-state":
            return fetch_state(args.repository, args.target_id, args.output)
        if args.command == "monitor-run":
            return run_offline(
                registry_path=args.registry,
                target_id=args.target_id,
                fixture_dir=args.fixture_dir,
                fixture_name=args.fixture_name,
                previous_dir=args.previous_dir,
                output_dir=args.output,
                run_id=args.run_id,
                started_at=args.started_at,
                finished_at=args.finished_at,
                event_date_value=args.event_date,
            )
        if args.command == "monitor-run-live":
            return run_live(
                registry_path=args.registry,
                target_id=args.target_id,
                previous_dir=args.previous_dir,
                output_dir=args.output,
                run_id=args.run_id,
                started_at=args.started_at,
                finished_at=args.finished_at,
            )
        if args.command == "monitor-build-handoff":
            return build_handoff(args.path, args.output)
        if args.command == "monitor-verify-bundle":
            return verify_state(args.path)
        if args.command == "monitor-notify":
            return notify_state(
                bundle_dir=args.path,
                repository=args.repository,
                receipt_path=args.receipt,
                recorded_at=args.recorded_at,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        print("Monitor operation failed:", file=sys.stderr)
        print("- %s" % exc, file=sys.stderr)
        return 1
    parser.error("unknown command")
    return 2


def _print_report(report) -> int:
    if report.ok:
        print("Validation passed.")
        return 0
    print("Validation failed:", file=sys.stderr)
    for issue in report.issues:
        print("- %s" % issue.format(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
