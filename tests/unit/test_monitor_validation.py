import csv
import json
import shutil
from pathlib import Path

import pytest

from earnings_research.cli.__main__ import main as cli_main
from earnings_research.validation.validator import load_spec, validate_dataset, validate_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "data" / "samples"
INVALID_CASES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "monitor_invalid_cases.json"
MONITOR_TABLES = (
    "monitor_target",
    "monitor_run",
    "monitor_resolution",
    "monitor_gap_acknowledgement",
    "monitor_checkpoint",
)


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def copy_samples(tmp_path):
    target = tmp_path / "samples"
    shutil.copytree(SAMPLES, target)
    return target


def issue_text(report):
    return "\n".join(issue.format() for issue in report.issues)


def load_invalid_cases():
    with INVALID_CASES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def apply_case(samples, case):
    for operation in case["operations"]:
        path = samples / (operation["table"] + "_sample.csv")
        fieldnames, rows = read_rows(path)
        selector = operation["selector"]

        def matches(row):
            return all(row.get(column) == value for column, value in selector.items())

        matched = [row for row in rows if matches(row)]
        assert matched, "fixture selector matched no rows: %s" % selector
        if operation["action"] == "update":
            for row in matched:
                row.update(operation["values"])
        elif operation["action"] == "delete":
            rows = [row for row in rows if not matches(row)]
        else:
            raise AssertionError("unknown fixture operation: %s" % operation["action"])
        write_rows(path, fieldnames, rows)


def test_monitor_positive_sample_bundle_passes():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)


@pytest.mark.parametrize("table", MONITOR_TABLES)
def test_monitor_positive_sample_file_passes(table):
    report = validate_file(SAMPLES / (table + "_sample.csv"))
    assert report.ok, issue_text(report)


def test_monitor_schemas_are_registered():
    for table in MONITOR_TABLES:
        assert load_spec(table).table == table


@pytest.mark.parametrize(
    ("table", "primary_key"),
    [
        ("monitor_target", "monitor_target_id"),
        ("monitor_run", "monitor_run_id"),
        ("monitor_resolution", "resolution_id"),
        ("monitor_gap_acknowledgement", "acknowledgement_id"),
        ("monitor_checkpoint", "monitor_target_id"),
    ],
)
def test_monitor_duplicate_primary_ids_are_rejected(tmp_path, table, primary_key):
    path = tmp_path / (table + "_sample.csv")
    fieldnames, rows = read_rows(SAMPLES / (table + "_sample.csv"))
    rows.append(dict(rows[0]))
    write_rows(path, fieldnames, rows)

    report = validate_file(path)

    assert not report.ok
    assert primary_key in issue_text(report)
    assert "duplicate unique key" in issue_text(report)


def test_pending_change_survives_notification_failure_and_timeout():
    _, checkpoints = read_rows(SAMPLES / "monitor_checkpoint_sample.csv")
    _, runs = read_rows(SAMPLES / "monitor_run_sample.csv")
    checkpoint = next(row for row in checkpoints if row["monitor_target_id"] == "MON-HOKUTO-NEWS")
    target_runs = [row for row in runs if row["monitor_target_id"] == "MON-HOKUTO-NEWS"]

    assert target_runs[-2]["run_result"] == "change_detected"
    assert target_runs[-2]["notification_status"] == "failed"
    assert target_runs[-1]["error_code"] == "timeout"
    assert checkpoint["target_state"] == "pending_human_review"
    assert checkpoint["pending_change_run_id"] == target_runs[-2]["monitor_run_id"]


def test_human_resolution_allows_healthy_checkpoint():
    _, checkpoints = read_rows(SAMPLES / "monitor_checkpoint_sample.csv")
    checkpoint = next(row for row in checkpoints if row["monitor_target_id"] == "MON-MINATO-DISCLOSURE")

    assert checkpoint["target_state"] == "healthy"
    assert checkpoint["pending_change_run_id"] == ""
    assert checkpoint["resolution_applied_id"] == "MRES-MINATO-001"


@pytest.mark.parametrize("case", load_invalid_cases(), ids=lambda case: case["id"])
def test_invalid_monitor_fixtures_are_rejected(tmp_path, case):
    samples = copy_samples(tmp_path)
    apply_case(samples, case)

    report = validate_dataset(samples)

    assert not report.ok
    assert case["expected_issue"] in issue_text(report)


def test_resolution_correction_is_append_only_and_valid(tmp_path):
    samples = copy_samples(tmp_path)
    resolution_path = samples / "monitor_resolution_sample.csv"
    fieldnames, resolutions = read_rows(resolution_path)
    correction = dict(resolutions[0])
    correction.update(
        {
            "resolution_id": "MRES-MINATO-002",
            "resolution": "Corrected Human decision after second review",
            "resolved_at": "2026-08-02T10:30:00+09:00",
            "supersedes_resolution_id": "MRES-MINATO-001",
            "notes": "Append-only correction",
        }
    )
    resolutions.append(correction)
    write_rows(resolution_path, fieldnames, resolutions)

    checkpoint_path = samples / "monitor_checkpoint_sample.csv"
    checkpoint_fields, checkpoints = read_rows(checkpoint_path)
    for checkpoint in checkpoints:
        if checkpoint["monitor_target_id"] == "MON-MINATO-DISCLOSURE":
            checkpoint["resolution_applied_id"] = "MRES-MINATO-002"
    write_rows(checkpoint_path, checkpoint_fields, checkpoints)

    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_gap_acknowledgement_append_only_violations_are_rejected(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "monitor_gap_acknowledgement_sample.csv"
    fieldnames, rows = read_rows(path)
    first = rows[0]
    correction = dict(first)
    correction.update(
        {
            "acknowledgement_id": "MGACK-MINATO-002",
            "acknowledged_at": "2026-08-01T11:00:00+09:00",
            "reason": "First correction",
            "supersedes_acknowledgement_id": first["acknowledgement_id"],
        }
    )
    branch = dict(correction)
    branch.update(
        {
            "acknowledgement_id": "MGACK-MINATO-003",
            "acknowledged_at": "2026-08-01T11:30:00+09:00",
            "reason": "Invalid second correction of the same record",
        }
    )
    rows.extend([correction, branch])
    write_rows(path, fieldnames, rows)
    report = validate_dataset(samples)
    assert not report.ok
    assert "gap acknowledgement cannot be superseded twice" in issue_text(report)


def test_gap_acknowledgement_rejects_non_authorizer_identifier(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "monitor_gap_acknowledgement_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["acknowledged_by"] = "workflow:github-actions"
    write_rows(path, fieldnames, rows)
    report = validate_dataset(samples)
    assert not report.ok
    assert "requires human:<stable-id> or system_policy:<policy-id>" in issue_text(report)


def test_one_monitoring_gap_cannot_be_acknowledged_twice(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "monitor_gap_acknowledgement_sample.csv"
    fieldnames, rows = read_rows(path)
    duplicate_gap = dict(rows[0])
    duplicate_gap["acknowledgement_id"] = "MGACK-MINATO-DUPLICATE"
    duplicate_gap["acknowledged_at"] = "2026-08-01T10:45:00+09:00"
    rows.append(duplicate_gap)
    write_rows(path, fieldnames, rows)
    report = validate_dataset(samples)
    assert not report.ok
    assert "one monitoring gap may be acknowledged only once" in issue_text(report)


@pytest.mark.parametrize(
    ("supersedes_id", "expected"),
    [
        ("MGACK-SELF", "cannot supersede itself"),
        ("MGACK-MISSING", "foreign key not found"),
    ],
)
def test_gap_acknowledgement_rejects_invalid_supersession_reference(
    tmp_path, supersedes_id, expected
):
    samples = copy_samples(tmp_path)
    path = samples / "monitor_gap_acknowledgement_sample.csv"
    fieldnames, rows = read_rows(SAMPLES / "monitor_gap_acknowledgement_sample.csv")
    row = dict(rows[0])
    row["acknowledgement_id"] = "MGACK-SELF"
    row["supersedes_acknowledgement_id"] = supersedes_id
    write_rows(path, fieldnames, [row])
    report = validate_dataset(samples)
    assert not report.ok
    assert expected in issue_text(report)


def test_partial_monitor_bundle_is_rejected(tmp_path):
    samples = copy_samples(tmp_path)
    (samples / "monitor_resolution_sample.csv").unlink()

    report = validate_dataset(samples)

    assert not report.ok
    assert "missing expected file monitor_resolution_sample.csv" in issue_text(report)


def test_legacy_dataset_without_monitor_bundle_remains_valid(tmp_path):
    samples = copy_samples(tmp_path)
    for table in MONITOR_TABLES:
        (samples / (table + "_sample.csv")).unlink()

    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_cli_rejects_unresolved_change_becoming_healthy(tmp_path, capsys):
    samples = copy_samples(tmp_path)
    case = next(case for case in load_invalid_cases() if case["id"] == "monitor_invalid_pending_change_becomes_healthy")
    apply_case(samples, case)

    exit_code = cli_main(["validate", str(samples)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "checkpoint must retain the unresolved change_detected run" in captured.err
