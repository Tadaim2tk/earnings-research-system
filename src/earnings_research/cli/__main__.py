"""Command-line interface for Earnings Research System validation."""

import argparse
import json
import sys
from pathlib import Path

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
