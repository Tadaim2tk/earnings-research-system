"""Command-line interface for Earnings Research System validation."""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from earnings_research.document_analysis.disclosure import analyze_named_disclosure
from earnings_research.document_analysis.pipeline import (
    analyze_document_url,
    analyze_handoff,
    write_analysis,
)
from earnings_research.earnings_evaluation import (
    evaluate_earnings,
    load_evaluation_context,
    load_evaluation_inputs,
    write_evaluation,
)
from earnings_research.market_reaction import track_files, write_reaction
from earnings_research.post_event_learning import review_files, write_review
from earnings_research.baseline_carryover import prepare_files, write_carryover
from earnings_research.legacy_research import (
    migrate_legacy_os,
    verify_legacy_migration,
    verify_research_outputs,
    write_research_outputs,
)
from earnings_research.prospective_hypotheses import (
    build_registry_file,
    evaluate_observation_and_status_file,
    summarize_trials_file,
    verify_registry_file,
)

from earnings_research.monitoring.notifications import WORKFLOW_FAILURE_REASONS
from earnings_research.monitoring.operational_cli import (
    build_handoff,
    fetch_state,
    notify_state,
    notify_workflow_failure,
    plan_registry,
    record_gap_acknowledgement,
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
    plan_parser.add_argument("--schedule-state", type=Path)

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
    run_parser.add_argument("--gap-acknowledgement", type=Path)

    live_parser = subparsers.add_parser("monitor-run-live", help="Run one authorized live monitor target.")
    live_parser.add_argument("--registry", required=True, type=Path)
    live_parser.add_argument("--target-id", required=True)
    live_parser.add_argument("--previous-dir", type=Path)
    live_parser.add_argument("--output", required=True, type=Path)
    live_parser.add_argument("--run-id", required=True)
    live_parser.add_argument("--started-at", required=True)
    live_parser.add_argument("--finished-at", required=True)
    live_parser.add_argument("--gap-acknowledgement", type=Path)
    live_parser.add_argument("--event-date")

    acknowledge_parser = subparsers.add_parser(
        "monitor-acknowledge-gap", help="Record an append-only monitoring gap acknowledgement."
    )
    acknowledge_parser.add_argument("--previous-dir", required=True, type=Path)
    acknowledge_parser.add_argument("--output", required=True, type=Path)
    acknowledge_parser.add_argument("--acknowledgement-id", required=True)
    acknowledge_parser.add_argument("--gap-start", required=True)
    acknowledge_parser.add_argument("--gap-end", required=True)
    acknowledge_parser.add_argument("--acknowledged-at", required=True)
    acknowledge_parser.add_argument("--acknowledged-by", required=True)
    acknowledge_parser.add_argument("--reason", required=True)
    acknowledge_parser.add_argument("--supersedes-id", default="")

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

    failure_parser = subparsers.add_parser(
        "monitor-notify-workflow-failure",
        help="Report a monitor job that failed before committing a state bundle.",
    )
    failure_parser.add_argument("--target-id", required=True)
    failure_parser.add_argument("--repository", required=True)
    failure_parser.add_argument("--receipt", required=True, type=Path)
    failure_parser.add_argument("--recorded-at", required=True)
    failure_parser.add_argument("--workflow-run-url", default="")
    failure_parser.add_argument(
        "--reason", default="no_bundle", choices=WORKFLOW_FAILURE_REASONS
    )

    analysis_parser = subparsers.add_parser(
        "analyze-earnings-document",
        help="Temporarily fetch and convert one earnings PDF into structured research data.",
    )
    analysis_parser.add_argument("--url", required=True)
    analysis_parser.add_argument("--title", required=True)
    analysis_parser.add_argument("--acquired-at")
    analysis_parser.add_argument("--output", required=True, type=Path)

    dispatch_parser = subparsers.add_parser(
        "analyze-earnings-handoff",
        help="Discover and analyze target earnings documents from a monitor handoff.",
    )
    dispatch_parser.add_argument("handoff", type=Path)
    dispatch_parser.add_argument("--output-dir", required=True, type=Path)
    dispatch_parser.add_argument("--acquired-at")

    named_parser = subparsers.add_parser(
        "analyze-named-disclosure",
        help="Analyze the disclosure document a monitor handoff already named.",
    )
    named_parser.add_argument("handoff", type=Path)
    named_parser.add_argument("--output-dir", required=True, type=Path)
    named_parser.add_argument("--acquired-at")

    evaluation_parser = subparsers.add_parser(
        "evaluate-earnings", help="Compare one locked pre-event baseline with analyzed earnings results."
    )
    evaluation_parser.add_argument("--baseline", required=True, type=Path)
    evaluation_parser.add_argument("--baseline-id", required=True)
    evaluation_parser.add_argument("--hypotheses", required=True, type=Path)
    evaluation_parser.add_argument("--events", required=True, type=Path)
    evaluation_parser.add_argument("--companies", required=True, type=Path)
    evaluation_parser.add_argument("--analysis", required=True, type=Path)
    evaluation_parser.add_argument("--evaluated-at")
    evaluation_parser.add_argument("--baseline-unit-multiplier", type=float, default=1_000_000)
    evaluation_parser.add_argument("--output", required=True, type=Path)

    reaction_parser = subparsers.add_parser(
        "track-market-reaction",
        help="Calculate immediate, next-session, and fifth-session earnings reactions.",
    )
    reaction_parser.add_argument("--observations", required=True, type=Path)
    reaction_parser.add_argument("--evaluation", required=True, type=Path)
    reaction_parser.add_argument("--events", required=True, type=Path)
    reaction_parser.add_argument("--event-status-history", required=True, type=Path)
    reaction_parser.add_argument("--companies", required=True, type=Path)
    reaction_parser.add_argument("--output", required=True, type=Path)

    learning_parser = subparsers.add_parser(
        "review-earnings-outcome",
        help="Validate a pre-event forecast against earnings and market-reaction snapshots.",
    )
    learning_parser.add_argument("--baseline", required=True, type=Path)
    learning_parser.add_argument("--baseline-id", required=True)
    learning_parser.add_argument("--hypotheses", required=True, type=Path)
    learning_parser.add_argument("--evaluation", required=True, type=Path)
    learning_parser.add_argument("--market-reaction", required=True, type=Path)
    learning_parser.add_argument("--reviewed-at", required=True)
    learning_parser.add_argument("--previous-review", type=Path)
    learning_parser.add_argument("--output", required=True, type=Path)

    carryover_parser = subparsers.add_parser(
        "prepare-baseline-carryover",
        help="Prepare human-readable prior-learning context for a future baseline.",
    )
    carryover_parser.add_argument("--review", required=True, action="append", type=Path)
    carryover_parser.add_argument("--target-event-id", required=True)
    carryover_parser.add_argument("--prepared-at", required=True)
    carryover_parser.add_argument("--output", required=True, type=Path)

    legacy_parser = subparsers.add_parser(
        "migrate-legacy-os",
        help="Losslessly import the retired earnings-research-os dataset and publishing views.",
    )
    legacy_parser.add_argument("--source-repo", required=True, type=Path)
    legacy_parser.add_argument("--source-commit", required=True)
    legacy_parser.add_argument("--source-run-id", required=True)
    legacy_parser.add_argument("--tso-repo", required=True, type=Path)
    legacy_parser.add_argument("--tso-commit", required=True)
    legacy_parser.add_argument("--output-root", required=True, type=Path)
    legacy_parser.add_argument("--reports-output", required=True, type=Path)
    legacy_parser.add_argument("--migration-recorded-at", required=True)
    legacy_parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)

    legacy_verify_parser = subparsers.add_parser(
        "verify-legacy-migration",
        help="Verify committed legacy data, provenance, context links, and reports without source access.",
    )
    legacy_verify_parser.add_argument("--output-root", required=True, type=Path)
    legacy_verify_parser.add_argument("--reports-output", required=True, type=Path)

    legacy_research_parser = subparsers.add_parser(
        "analyze-legacy-research",
        help="Generate descriptive research knowledge from the frozen legacy observational cohort.",
    )
    legacy_research_parser.add_argument("--input-root", required=True, type=Path)
    legacy_research_parser.add_argument("--output-dir", required=True, type=Path)

    legacy_research_verify_parser = subparsers.add_parser(
        "verify-legacy-research",
        help="Rebuild and verify committed legacy research knowledge outputs.",
    )
    legacy_research_verify_parser.add_argument("--input-root", required=True, type=Path)
    legacy_research_verify_parser.add_argument("--output-dir", required=True, type=Path)

    hypothesis_registry_parser = subparsers.add_parser(
        "build-hypothesis-registry",
        help="Freeze legacy learning candidates as prospective hypothesis definitions.",
    )
    hypothesis_registry_parser.add_argument("--knowledge", required=True, type=Path)
    hypothesis_registry_parser.add_argument("--frozen-at", required=True)
    hypothesis_registry_parser.add_argument("--output", required=True, type=Path)

    hypothesis_verify_parser = subparsers.add_parser(
        "verify-hypothesis-registry",
        help="Verify a frozen prospective hypothesis registry against legacy research.",
    )
    hypothesis_verify_parser.add_argument("--knowledge", required=True, type=Path)
    hypothesis_verify_parser.add_argument("--registry", required=True, type=Path)

    hypothesis_evaluate_parser = subparsers.add_parser(
        "evaluate-hypothesis-event",
        help="Append prospective hypothesis trials for one completed earnings event.",
    )
    hypothesis_evaluate_parser.add_argument("--registry", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--observation", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--dataset", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--market-reaction", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--trials-dir", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--recorded-at", required=True)
    hypothesis_evaluate_parser.add_argument("--evaluated-at", required=True)
    hypothesis_evaluate_parser.add_argument("--output", required=True, type=Path)
    hypothesis_evaluate_parser.add_argument("--status-output", required=True, type=Path)

    hypothesis_summary_parser = subparsers.add_parser(
        "summarize-hypothesis-registry",
        help="Derive current hypothesis status from append-only event trials.",
    )
    hypothesis_summary_parser.add_argument("--registry", required=True, type=Path)
    hypothesis_summary_parser.add_argument("--trials-dir", required=True, type=Path)
    hypothesis_summary_parser.add_argument("--evaluated-at", required=True)
    hypothesis_summary_parser.add_argument("--output", required=True, type=Path)

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
    if args.command == "analyze-earnings-document":
        try:
            result = analyze_document_url(args.url, args.title, args.acquired_at)
            write_analysis(result, args.output)
            print(json.dumps({"status": result.status, "analysis_id": result.analysis_id, "output": str(args.output)}))
            return 0
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            print("Document analysis failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "analyze-earnings-handoff":
        try:
            # Prefers the document the handoff already names and falls back to
            # discovery when it names none, so the caller needs one command.
            result = analyze_named_disclosure(
                handoff_path=args.handoff,
                output_dir=args.output_dir,
                acquired_at=args.acquired_at,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            print("Document analysis failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "analyze-named-disclosure":
        try:
            result = analyze_named_disclosure(
                handoff_path=args.handoff,
                output_dir=args.output_dir,
                acquired_at=args.acquired_at,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            print("Document analysis failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "evaluate-earnings":
        try:
            baseline, hypotheses, analysis = load_evaluation_inputs(
                args.baseline, args.hypotheses, args.analysis, args.baseline_id
            )
            period_scope, ticker = load_evaluation_context(
                args.events, args.companies, baseline, analysis
            )
            evaluated_at = datetime.fromisoformat(args.evaluated_at) if args.evaluated_at else None
            result = evaluate_earnings(
                baseline,
                hypotheses,
                analysis,
                evaluated_at,
                args.baseline_unit_multiplier,
                expected_ticker=ticker,
                expected_period_scope=period_scope,
            )
            write_evaluation(result, args.output)
            print(json.dumps({"status": result.status, "evaluation_id": result.evaluation_id, "output": str(args.output)}))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Earnings evaluation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "track-market-reaction":
        try:
            result = track_files(
                args.observations,
                args.evaluation,
                args.events,
                args.event_status_history,
                args.companies,
            )
            write_reaction(result, args.output)
            print(json.dumps({
                "status": result.status,
                "tracking_id": result.tracking_id,
                "reaction_path": result.summary.reaction_path,
                "output": str(args.output),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Market reaction tracking failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "review-earnings-outcome":
        try:
            result = review_files(
                args.baseline,
                args.baseline_id,
                args.hypotheses,
                args.evaluation,
                args.market_reaction,
                datetime.fromisoformat(args.reviewed_at),
                args.previous_review,
            )
            write_review(result, args.output)
            print(json.dumps({
                "status": result.status,
                "review_id": result.review_id,
                "overall_forecast_result": result.overall_forecast_result,
                "output": str(args.output),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Post-event learning review failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "prepare-baseline-carryover":
        try:
            result = prepare_files(
                args.review,
                args.target_event_id,
                datetime.fromisoformat(args.prepared_at),
            )
            write_carryover(result, args.output)
            print(json.dumps({
                "status": "prepared",
                "target_event_id": result.target_event_id,
                "source_review_count": len(result.source_reviews),
                "output": str(args.output),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Baseline carryover preparation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "migrate-legacy-os":
        try:
            result = migrate_legacy_os(
                source_repo=args.source_repo,
                source_commit=args.source_commit,
                source_run_id=args.source_run_id,
                tso_repo=args.tso_repo,
                tso_commit=args.tso_commit,
                output_root=args.output_root,
                reports_output=args.reports_output,
                migration_recorded_at=args.migration_recorded_at,
                as_of_date=args.as_of_date,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print("Legacy OS migration failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "verify-legacy-migration":
        try:
            result = verify_legacy_migration(args.output_root, args.reports_output)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Legacy migration verification failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "analyze-legacy-research":
        try:
            result = write_research_outputs(args.input_root, args.output_dir)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Legacy research analysis failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "verify-legacy-research":
        try:
            result = verify_research_outputs(args.input_root, args.output_dir)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Legacy research verification failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "build-hypothesis-registry":
        try:
            registry = build_registry_file(
                args.knowledge,
                args.output,
                datetime.fromisoformat(args.frozen_at),
            )
            print(json.dumps({
                "registry_id": registry.registry_id,
                "hypothesis_count": len(registry.hypotheses),
                "output": str(args.output),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Hypothesis registry generation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "verify-hypothesis-registry":
        try:
            registry = verify_registry_file(args.knowledge, args.registry)
            print(json.dumps({
                "registry_id": registry.registry_id,
                "hypothesis_count": len(registry.hypotheses),
                "status": "verified",
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Hypothesis registry verification failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "evaluate-hypothesis-event":
        try:
            bundle, snapshot = evaluate_observation_and_status_file(
                args.registry,
                args.observation,
                args.trials_dir,
                args.output,
                args.status_output,
                datetime.fromisoformat(args.recorded_at),
                datetime.fromisoformat(args.evaluated_at),
                args.dataset,
                args.market_reaction,
            )
            print(json.dumps({
                "earnings_event_id": bundle.earnings_event_id,
                "trial_count": len(bundle.trials),
                "output": str(args.output),
                "status_output": str(args.status_output),
                "status_hypothesis_count": len(snapshot.hypotheses),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Hypothesis event evaluation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    if args.command == "summarize-hypothesis-registry":
        try:
            snapshot = summarize_trials_file(
                args.registry,
                args.trials_dir,
                args.output,
                datetime.fromisoformat(args.evaluated_at),
            )
            print(json.dumps({
                "registry_id": snapshot.registry_id,
                "hypothesis_count": len(snapshot.hypotheses),
                "output": str(args.output),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print("Hypothesis summary generation failed:", file=sys.stderr)
            print("- %s" % exc, file=sys.stderr)
            return 1
    try:
        if args.command == "monitor-plan":
            return plan_registry(
                args.registry,
                args.target_id,
                args.fixture_name,
                args.planned_at,
                args.force,
                args.schedule_state,
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
                gap_acknowledgement_path=args.gap_acknowledgement,
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
                gap_acknowledgement_path=args.gap_acknowledgement,
                event_date=args.event_date,
            )
        if args.command == "monitor-acknowledge-gap":
            return record_gap_acknowledgement(
                previous_dir=args.previous_dir,
                output_path=args.output,
                acknowledgement_id=args.acknowledgement_id,
                gap_start=args.gap_start,
                gap_end=args.gap_end,
                acknowledged_at=args.acknowledged_at,
                acknowledged_by=args.acknowledged_by,
                reason=args.reason,
                supersedes_id=args.supersedes_id,
            )
        if args.command == "monitor-build-handoff":
            return build_handoff(args.path, args.output)
        if args.command == "monitor-verify-bundle":
            return verify_state(args.path)
        if args.command == "monitor-notify-workflow-failure":
            return notify_workflow_failure(
                target_id=args.target_id,
                repository=args.repository,
                receipt_path=args.receipt,
                recorded_at=args.recorded_at,
                workflow_run_url=args.workflow_run_url,
                reason=args.reason,
            )
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
