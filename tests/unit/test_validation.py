import csv
import shutil
from pathlib import Path

import pytest

from earnings_research.cli.__main__ import main as cli_main
from earnings_research.validation.validator import (
    BASELINE_LOCK_HASH_FIELDS_V1,
    _calculate_baseline_record_hash,
    _validate_event_lifecycle_constraints,
    load_spec,
    validate_dataset,
    validate_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "data" / "samples"
PROSPECTIVE_EVIDENCE_SAMPLE = SAMPLES / "prospective_evidence" / "evidence_sample.csv"
INVALID_EVIDENCE_SAMPLES = SAMPLES / "invalid_evidence"
PROSPECTIVE_BASELINE_SAMPLES = SAMPLES / "prospective_baseline"
PROSPECTIVE_EVENT_LIFECYCLE_SAMPLES = SAMPLES / "prospective_event_lifecycle"
EVIDENCE_METADATA_FIELDS = [
    "evidence_status",
    "supersedes_evidence_id",
    "content_hash_status",
    "content_hash",
    "content_hash_algorithm",
    "raw_storage_status",
    "raw_location",
    "license_status",
]


def copy_samples(tmp_path):
    target = tmp_path / "samples"
    shutil.copytree(SAMPLES, target)
    return target


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def issue_text(report):
    return "\n".join(issue.format() for issue in report.issues)


def copy_prospective_baseline_dataset(tmp_path):
    samples = copy_samples(tmp_path)
    baseline_path = samples / "pre_earnings_baseline_sample.csv"
    baseline_fieldnames, baseline_rows = read_rows(baseline_path)
    fixture_fieldnames, fixture_rows = read_rows(PROSPECTIVE_BASELINE_SAMPLES / "pre_earnings_baseline_sample.csv")
    fixture_by_id = {row["baseline_id"]: row for row in fixture_rows}
    existing_baseline_ids = {row["baseline_id"] for row in baseline_rows}
    normalized_baselines = []
    spec = load_spec("pre_earnings_baseline")
    for source_row in baseline_rows:
        if source_row["baseline_id"] in fixture_by_id:
            normalized_baselines.append(dict(fixture_by_id[source_row["baseline_id"]]))
            continue
        row = {field: source_row.get(field, "") for field in fixture_fieldnames}
        row.update(
            {
                "baseline_status": "locked",
                "lock_hash_algorithm": "sha256",
                "human_review_status": "approved",
                "reviewed_by": "test-reviewer",
                "reviewed_at": row["locked_at"],
                "recorded_at": row["locked_at"],
            }
        )
        row["baseline_record_hash"] = _calculate_baseline_record_hash(row, spec)
        normalized_baselines.append(row)
    normalized_baselines.extend(row for row in fixture_rows if row["baseline_id"] not in existing_baseline_ids)
    write_rows(baseline_path, fixture_fieldnames, normalized_baselines)

    evidence_path = samples / "evidence_sample.csv"
    _, evidence_rows = read_rows(evidence_path)
    evidence_fieldnames, fixture_evidence = read_rows(PROSPECTIVE_BASELINE_SAMPLES / "evidence_sample.csv")
    normalized_evidence = []
    for source_row in evidence_rows:
        row = {field: source_row.get(field, "") for field in evidence_fieldnames}
        row.update(
            {
                "evidence_status": "original",
                "content_hash_status": "not_recorded",
                "raw_storage_status": "metadata_only",
                "license_status": "not_applicable",
            }
        )
        normalized_evidence.append(row)
    normalized_evidence.extend(fixture_evidence)
    write_rows(evidence_path, evidence_fieldnames, normalized_evidence)
    return samples


def prospective_baseline_fixture():
    return read_rows(PROSPECTIVE_BASELINE_SAMPLES / "pre_earnings_baseline_sample.csv")


def event_lifecycle_fixture():
    return read_rows(PROSPECTIVE_EVENT_LIFECYCLE_SAMPLES / "event_status_history_sample.csv")


def postponed_occurred_statuses(event_id="E1"):
    return [
        {
            "event_status_record_id": "S1", "earnings_event_id": event_id, "event_status": "scheduled",
            "scheduled_at": "2026-10-01T15:30:00+09:00", "status_recorded_at": "2026-09-01T09:00:00+09:00",
        },
        {
            "event_status_record_id": "S2", "earnings_event_id": event_id, "event_status": "postponed",
            "scheduled_at": "2026-10-08T15:30:00+09:00", "previous_scheduled_at": "2026-10-01T15:30:00+09:00",
            "status_recorded_at": "2026-09-28T10:00:00+09:00", "status_reason": "Delay",
            "supersedes_status_record_id": "S1",
        },
        {
            "event_status_record_id": "S3", "earnings_event_id": event_id, "event_status": "occurred",
            "scheduled_at": "2026-10-08T15:30:00+09:00", "status_recorded_at": "2026-10-08T15:35:00+09:00",
            "occurred_at": "2026-10-08T15:30:00+09:00", "supersedes_status_record_id": "S2",
        },
    ]


def lifecycle_baseline(
    baseline_id,
    event_id="E1",
    reviewed_at="2026-09-28T10:00:00+09:00",
    locked_at="2026-09-28T10:05:00+09:00",
    supersedes_baseline_id="",
    baseline_status="locked",
    is_locked="true",
):
    return {
        "baseline_id": baseline_id,
        "earnings_event_id": event_id,
        "baseline_status": baseline_status,
        "is_locked": is_locked,
        "human_review_status": "approved" if baseline_status == "locked" else "pending",
        "reviewed_at": reviewed_at if baseline_status == "locked" else "",
        "locked_at": locked_at if baseline_status == "locked" else "",
        "supersedes_baseline_id": supersedes_baseline_id,
    }


def postponed_lifecycle_issues(baselines):
    return _validate_event_lifecycle_constraints(
        {
            "event_status_history": postponed_occurred_statuses(),
            "pre_earnings_baseline": baselines,
        }
    )


def rehash_baseline(row):
    row["baseline_record_hash"] = _calculate_baseline_record_hash(row, load_spec("pre_earnings_baseline"))


def test_valid_samples_pass():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)


def test_missing_required_column_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "company_master_sample.csv"
    fieldnames, rows = read_rows(path)
    fieldnames.remove("ticker")
    for row in rows:
        row.pop("ticker")
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "missing required column" in issue_text(report)


def test_type_mismatch_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "earnings_event_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["fiscal_year"] = "twenty twenty six"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "invalid integer value" in issue_text(report)


def test_foreign_key_mismatch_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "earnings_event_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["company_id"] = "CMP-NOT-FOUND"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "foreign key not found" in issue_text(report)


def test_baseline_after_announcement_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["as_of_datetime"] = "2026-08-08T16:00:00+09:00"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "baseline timestamp is not before announcement" in issue_text(report)


def test_undefined_scoring_version_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["scoring_version"] = "ERS-SCORE-NOT-DEFINED"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "undefined scoring_version" in issue_text(report)


def test_locked_baseline_modification_is_detected(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(path)
    changed = dict(rows[0])
    changed["baseline_id"] = "BASE-ASTER-001-MODIFIED"
    changed["baseline_record_hash"] = "hash_changed_after_lock"
    rows.append(changed)
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "locked baseline appears modified instead of appended" in issue_text(report)


def test_legacy_baseline_sample_without_prospective_headers_passes():
    fieldnames, _ = read_rows(SAMPLES / "pre_earnings_baseline_sample.csv")
    assert "baseline_status" not in fieldnames
    report = validate_file(SAMPLES / "pre_earnings_baseline_sample.csv")
    assert report.ok, issue_text(report)


def test_prospective_baseline_fixture_passes():
    path = PROSPECTIVE_BASELINE_SAMPLES / "pre_earnings_baseline_sample.csv"
    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_baseline_hash_field_list_covers_schema_except_hash():
    spec = load_spec("pre_earnings_baseline")
    expected = [column.name for column in spec.columns if column.name != "baseline_record_hash"]
    assert list(BASELINE_LOCK_HASH_FIELDS_V1) == expected


def test_baseline_hash_normalizes_equivalent_timezone_offsets():
    _, rows = prospective_baseline_fixture()
    original = dict(rows[1])
    equivalent = dict(original)
    equivalent["locked_at"] = "2026-08-07T11:00:00+00:00"
    spec = load_spec("pre_earnings_baseline")

    assert _calculate_baseline_record_hash(original, spec) == _calculate_baseline_record_hash(equivalent, spec)


def test_baseline_hash_normalizes_equivalent_decimal_values():
    _, rows = prospective_baseline_fixture()
    original = dict(rows[1])
    equivalent = dict(original)
    equivalent["company_guidance_revenue"] = "11300.00"
    spec = load_spec("pre_earnings_baseline")

    assert _calculate_baseline_record_hash(original, spec) == _calculate_baseline_record_hash(equivalent, spec)


def test_baseline_hash_ignores_input_mapping_order():
    _, rows = prospective_baseline_fixture()
    original = dict(rows[1])
    reversed_mapping = dict(reversed(list(original.items())))
    spec = load_spec("pre_earnings_baseline")

    assert _calculate_baseline_record_hash(original, spec) == _calculate_baseline_record_hash(reversed_mapping, spec)


def test_prospective_baseline_dataset_with_formal_evidence_passes(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_baseline_status_enum_is_validated(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[-1]["baseline_status"] = "almost_locked"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "value 'almost_locked' is not in allowed set" in issue_text(report)


@pytest.mark.parametrize("invalid_version", ["v0", "v01", "V1", "v1.0", "v²", "v١٢", "v"])
def test_prospective_baseline_version_format_is_validated(tmp_path, invalid_version):
    fieldnames, rows = prospective_baseline_fixture()
    rows[-1]["baseline_version"] = invalid_version
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "prospective baseline_version must use v followed by an integer of at least 1" in issue_text(report)


def test_prospective_header_rejects_locked_legacy_escape(tmp_path):
    legacy_fieldnames, legacy_rows = read_rows(SAMPLES / "pre_earnings_baseline_sample.csv")
    prospective_fieldnames, _ = prospective_baseline_fixture()
    escaped_row = {field: legacy_rows[0].get(field, "") for field in prospective_fieldnames}
    escaped_row["baseline_record_hash"] = "fake-placeholder-hash"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, prospective_fieldnames, [escaped_row])

    report = validate_file(path)
    assert not report.ok
    assert "locked row in a prospective-capable file cannot use the legacy baseline contract" in issue_text(report)


@pytest.mark.parametrize(
    "invalid_datetime",
    ["not-a-date", "2026-08-07T20:00:00+25:00", "2026-08-07T11:00:00Z"],
)
def test_invalid_prospective_datetime_does_not_crash(tmp_path, invalid_datetime):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["reviewed_at"] = invalid_datetime
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "invalid datetime value" in issue_text(report)


def test_cli_valid_dataset_exits_zero(capsys):
    exit_code = cli_main(["validate", str(SAMPLES)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validation passed." in captured.out
    assert "Traceback" not in captured.err


def test_cli_invalid_dataset_exits_one_without_traceback(tmp_path, capsys):
    samples = copy_samples(tmp_path)
    path = samples / "company_master_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["market_cap_category"] = "invalid-category"
    write_rows(path, fieldnames, rows)

    exit_code = cli_main(["validate", str(samples)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Validation failed:" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_issue"),
    [
        ("baseline_version", "v²", "prospective baseline_version must use v followed by an integer"),
        ("reviewed_at", "not-a-date", "invalid datetime value"),
        ("reviewed_at", "2026-08-07T11:00:00Z", "invalid datetime value"),
    ],
)
def test_cli_baseline_crash_regressions_exit_one(
    tmp_path, capsys, field_name, invalid_value, expected_issue
):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1][field_name] = invalid_value
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    exit_code = cli_main(["validate-file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert expected_issue in captured.err
    assert "Traceback" not in captured.err


def test_cli_validate_file_missing_path_exits_one_without_traceback(tmp_path, capsys):
    path = tmp_path / "pre_earnings_baseline_sample.csv"

    exit_code = cli_main(["validate-file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Validation failed:" in captured.err
    assert "No such file or directory" in captured.err
    assert "Traceback" not in captured.err


def test_cli_validate_file_unknown_schema_exits_one_without_traceback(tmp_path, capsys):
    path = tmp_path / "unknown.csv"
    path.write_text("value\n1\n", encoding="utf-8")

    exit_code = cli_main(["validate-file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Validation failed:" in captured.err
    assert "Could not infer schema" in captured.err
    assert "Traceback" not in captured.err


def test_legacy_earnings_event_sample_still_passes():
    report = validate_file(SAMPLES / "earnings_event_sample.csv")
    assert report.ok, issue_text(report)


def test_event_lifecycle_positive_fixture_passes():
    report = validate_file(PROSPECTIVE_EVENT_LIFECYCLE_SAMPLES / "event_status_history_sample.csv")
    assert report.ok, issue_text(report)


def test_event_lifecycle_enum_is_validated(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    rows[0]["event_status"] = "rescheduled"
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "is not in allowed set" in issue_text(report)


@pytest.mark.parametrize("first_status", ["postponed", "cancelled", "occurred"])
def test_first_event_status_must_be_scheduled(tmp_path, first_status):
    fieldnames, rows = event_lifecycle_fixture()
    first = rows[0]
    first["event_status"] = first_status
    first["status_reason"] = "Initial state bypass" if first_status in {"postponed", "cancelled"} else ""
    first["previous_scheduled_at"] = "2026-09-25T15:30:00+09:00" if first_status == "postponed" else ""
    first["occurred_at"] = "2026-09-01T08:55:00+09:00" if first_status == "occurred" else ""
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "initial event status must be scheduled" in issue_text(report)


def test_first_scheduled_status_cannot_have_supersession_reference(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    rows[0]["supersedes_status_record_id"] = rows[1]["event_status_record_id"]
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "status supersession must reference an earlier row" in issue_text(report)


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        ("self", "status record cannot supersede itself"),
        ("missing", "superseded status record not found"),
        ("event_mismatch", "status lineage must keep earnings_event_id unchanged"),
        ("timestamp_regression", "status_recorded_at must increase monotonically"),
    ],
)
def test_event_status_lineage_failures(tmp_path, mutation, expected_issue):
    fieldnames, rows = event_lifecycle_fixture()
    target = rows[1]
    if mutation == "self":
        target["supersedes_status_record_id"] = target["event_status_record_id"]
    elif mutation == "missing":
        target["supersedes_status_record_id"] = "EVST-NOT-FOUND"
    elif mutation == "event_mismatch":
        target["earnings_event_id"] = "EVT-PILOT-B"
    else:
        target["status_recorded_at"] = "2026-08-31T09:00:00+09:00"
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert expected_issue in issue_text(report)


def test_event_status_forward_reference_fails(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    first = rows.pop(0)
    rows.insert(1, first)
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "status supersession must reference an earlier row" in issue_text(report)


def test_event_status_duplicate_id_fails(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    rows.append(dict(rows[-1]))
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "duplicate unique key" in issue_text(report)


@pytest.mark.parametrize(
    ("row_index", "field_name", "value", "expected_issue"),
    [
        (3, "occurred_at", "", "occurred status requires occurred_at"),
        (1, "occurred_at", "2026-09-28T10:00:00+09:00", "non-occurred status must not contain occurred_at"),
        (1, "previous_scheduled_at", "", "postponed status must preserve the previous scheduled_at"),
        (5, "status_reason", "", "cancelled status requires status_reason"),
    ],
)
def test_event_status_cross_field_failures(tmp_path, row_index, field_name, value, expected_issue):
    fieldnames, rows = event_lifecycle_fixture()
    rows[row_index][field_name] = value
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert expected_issue in issue_text(report)


@pytest.mark.parametrize(
    ("terminal_status", "next_status"),
    [
        ("occurred", "scheduled"), ("occurred", "postponed"), ("occurred", "cancelled"), ("occurred", "occurred"),
        ("cancelled", "scheduled"), ("cancelled", "postponed"), ("cancelled", "cancelled"), ("cancelled", "occurred"),
    ],
)
def test_terminal_event_status_transitions_fail(tmp_path, terminal_status, next_status):
    fieldnames, rows = event_lifecycle_fixture()
    terminal = rows[3] if terminal_status == "occurred" else rows[5]
    next_row = dict(terminal)
    next_row["event_status_record_id"] += "-INVALID"
    next_row["event_status"] = next_status
    next_row["supersedes_status_record_id"] = terminal["event_status_record_id"]
    next_row["status_recorded_at"] = "2026-10-16T10:00:00+09:00"
    next_row["occurred_at"] = "2026-10-16T09:00:00+09:00" if next_status == "occurred" else ""
    next_row["status_reason"] = "Invalid transition test" if next_status in {"postponed", "cancelled"} else ""
    if next_status == "postponed":
        next_row["previous_scheduled_at"] = terminal["scheduled_at"]
        next_row["scheduled_at"] = "2026-10-20T15:30:00+09:00"
    rows.append(next_row)
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "invalid event status transition" in issue_text(report)


def test_event_status_branching_fails(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    branch = dict(rows[2])
    branch["event_status_record_id"] = "EVST-PILOT-A-BRANCH"
    branch["event_status"] = "cancelled"
    branch["scheduled_at"] = rows[1]["scheduled_at"]
    branch["previous_scheduled_at"] = ""
    branch["status_recorded_at"] = "2026-10-07T10:00:00+09:00"
    branch["occurred_at"] = ""
    branch["status_reason"] = "Invalid branch"
    branch["supersedes_status_record_id"] = rows[1]["event_status_record_id"]
    rows.append(branch)
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "status lineage cannot branch from a non-current record" in issue_text(report)
    assert "multiple active status tails" in issue_text(report)


def test_cancelled_event_rejects_post_event_review(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "event_status_history_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1].update(
        {
            "event_status": "cancelled",
            "occurred_at": "",
            "status_reason": "Company cancelled disclosure",
        }
    )
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "cancelled event cannot have post-event review or scoring" in issue_text(report)


def test_replacement_event_requires_same_company(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "event_status_history_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1].update(
        {
            "event_status": "cancelled",
            "occurred_at": "",
            "status_reason": "Replaced by another event",
            "replacement_event_id": "EVT-HOKUTO-2026Q1",
        }
    )
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "replacement event must belong to the same company" in issue_text(report)


def test_missing_replacement_event_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "event_status_history_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1].update(
        {
            "event_status": "cancelled",
            "occurred_at": "",
            "status_reason": "Replacement not registered",
            "replacement_event_id": "EVT-NOT-FOUND",
        }
    )
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "foreign key not found" in issue_text(report)


def test_replacement_event_same_company_is_allowed():
    event_rows = [
        {"earnings_event_id": "E1", "company_id": "C1", "announcement_date": "2026-10-01", "announcement_time": "15:30"},
        {"earnings_event_id": "E2", "company_id": "C1", "announcement_date": "2026-11-01", "announcement_time": "15:30"},
    ]
    statuses = [
        {"event_status_record_id": "S1", "earnings_event_id": "E1", "event_status": "scheduled", "scheduled_at": "2026-10-01T15:30:00+09:00", "status_recorded_at": "2026-09-01T09:00:00+09:00"},
        {"event_status_record_id": "S2", "earnings_event_id": "E1", "event_status": "cancelled", "scheduled_at": "2026-10-01T15:30:00+09:00", "status_recorded_at": "2026-09-20T09:00:00+09:00", "status_reason": "Replaced", "supersedes_status_record_id": "S1", "replacement_event_id": "E2"},
        {"event_status_record_id": "S3", "earnings_event_id": "E2", "event_status": "scheduled", "scheduled_at": "2026-11-01T15:30:00+09:00", "status_recorded_at": "2026-09-20T09:05:00+09:00"},
    ]
    issues = _validate_event_lifecycle_constraints(
        {"earnings_event": event_rows, "event_status_history": statuses}
    )
    assert not issues, "\n".join(issue.format() for issue in issues)


def test_replacement_event_is_rejected_for_non_cancelled_status(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    rows[3]["replacement_event_id"] = "EVT-PILOT-B"
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "replacement_event_id is only allowed for cancelled status" in issue_text(report)


def test_early_occurrence_is_allowed(tmp_path):
    fieldnames, rows = event_lifecycle_fixture()
    rows[3]["occurred_at"] = "2026-10-15T15:00:00+09:00"
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_scheduled_event_rejects_return_and_review(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "event_status_history_sample.csv"
    fieldnames, rows = read_rows(path)
    rows = [row for row in rows if row["event_status_record_id"] != "EVST-ASTER-002"]
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "post-event review requires current event status occurred" in issue_text(report)
    assert "event return requires occurred status" in issue_text(report)


def test_postponed_event_requires_revalidated_baseline_before_occurred():
    stale_baseline = lifecycle_baseline(
        "B1", reviewed_at="2026-09-20T10:00:00+09:00", locked_at="2026-09-20T10:05:00+09:00"
    )
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues([stale_baseline]))
    assert "current locked baseline was not reviewed at or after latest postponement" in messages


def test_postponed_event_accepts_revalidated_locked_baseline():
    issues = postponed_lifecycle_issues([lifecycle_baseline("B1")])
    assert not issues, "\n".join(issue.format() for issue in issues)


@pytest.mark.parametrize("version_count", [2, 3])
def test_postponed_event_uses_revalidated_current_baseline_tail(version_count):
    baselines = []
    for index in range(1, version_count + 1):
        baselines.append(
            lifecycle_baseline(
                "B%s" % index,
                reviewed_at="2026-09-20T10:00:00+09:00" if index < version_count else "2026-09-28T10:00:00+09:00",
                locked_at="2026-09-20T10:05:00+09:00" if index < version_count else "2026-09-28T10:05:00+09:00",
                supersedes_baseline_id="B%s" % (index - 1) if index > 1 else "",
            )
        )
    issues = postponed_lifecycle_issues(baselines)
    assert not issues, "\n".join(issue.format() for issue in issues)


def test_superseded_revalidated_baseline_does_not_bypass_current_stale_tail():
    baselines = [
        lifecycle_baseline("B1"),
        lifecycle_baseline(
            "B2",
            reviewed_at="2026-09-20T10:00:00+09:00",
            locked_at="2026-09-20T10:05:00+09:00",
            supersedes_baseline_id="B1",
        ),
    ]
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues(baselines))
    assert "current locked baseline was not reviewed at or after latest postponement" in messages


def test_current_draft_tail_does_not_fall_back_to_old_locked_baseline():
    baselines = [
        lifecycle_baseline("B1"),
        lifecycle_baseline("B2", baseline_status="draft", is_locked="false"),
    ]
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues(baselines))
    assert "multiple current prospective baseline tails; found 2" in messages


def test_only_current_draft_tail_fails_locked_gate():
    baselines = [lifecycle_baseline("B1", baseline_status="draft", is_locked="false")]
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues(baselines))
    assert "current prospective baseline is not locked" in messages


def test_multiple_current_baseline_tails_fail_closed():
    baselines = [
        lifecycle_baseline("B1", reviewed_at="2026-09-20T10:00:00+09:00"),
        lifecycle_baseline("B2", supersedes_baseline_id="B1"),
        lifecycle_baseline("B3", supersedes_baseline_id="B1"),
    ]
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues(baselines))
    assert "multiple current prospective baseline tails; found 2" in messages


def test_missing_current_locked_baseline_tail_fails_closed():
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues([]))
    assert "no current prospective baseline tail" in messages


def test_other_event_current_baseline_does_not_satisfy_postponement_gate():
    messages = "\n".join(
        issue.format() for issue in postponed_lifecycle_issues([lifecycle_baseline("B2", event_id="E2")])
    )
    assert "no current prospective baseline tail" in messages


def test_legacy_baseline_is_not_a_current_prospective_tail():
    legacy_baseline = lifecycle_baseline("B1")
    legacy_baseline["baseline_status"] = ""
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues([legacy_baseline]))
    assert "no current prospective baseline tail" in messages


@pytest.mark.parametrize(
    ("reviewed_at", "locked_at", "expected_issue"),
    [
        (
            "2026-09-28T09:59:59+09:00",
            "2026-09-28T10:05:00+09:00",
            "current locked baseline was not reviewed at or after latest postponement",
        ),
        (
            "2026-09-28T10:00:00+09:00",
            "2026-10-08T15:30:00+09:00",
            "current locked baseline must be locked before postponed scheduled_at",
        ),
        (
            "2026-09-28T10:00:00+09:00",
            "2026-10-08T15:30:01+09:00",
            "current locked baseline must be locked before postponed scheduled_at",
        ),
    ],
)
def test_current_baseline_postponement_time_boundaries_fail(reviewed_at, locked_at, expected_issue):
    baseline = lifecycle_baseline("B1", reviewed_at=reviewed_at, locked_at=locked_at)
    messages = "\n".join(issue.format() for issue in postponed_lifecycle_issues([baseline]))
    assert expected_issue in messages


def test_review_at_postponement_timestamp_is_accepted():
    issues = postponed_lifecycle_issues([lifecycle_baseline("B1", reviewed_at="2026-09-28T10:00:00+09:00")])
    assert not issues, "\n".join(issue.format() for issue in issues)


def test_legacy_dataset_without_lifecycle_file_still_passes(tmp_path):
    samples = copy_samples(tmp_path)
    (samples / "event_status_history_sample.csv").unlink()

    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_prospective_baseline_activates_lifecycle_requirement(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    (samples / "event_status_history_sample.csv").unlink()

    report = validate_dataset(samples)
    assert not report.ok
    assert "has no unique current lifecycle status" in issue_text(report)


def test_invalid_baseline_lineage_skips_postponement_tail_inference(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    baseline_path = samples / "pre_earnings_baseline_sample.csv"
    baseline_fieldnames, baselines = read_rows(baseline_path)
    current = next(row for row in baselines if row["baseline_id"] == "BASE-ASTER-003")
    current["supersedes_baseline_id"] = current["baseline_id"]
    rehash_baseline(current)
    write_rows(baseline_path, baseline_fieldnames, baselines)

    status_path = samples / "event_status_history_sample.csv"
    status_fieldnames, statuses = read_rows(status_path)
    occurred_index = next(
        index for index, row in enumerate(statuses) if row["event_status_record_id"] == "EVST-ASTER-002"
    )
    postponed = {field: "" for field in status_fieldnames}
    postponed.update(
        {
            "event_status_record_id": "EVST-ASTER-POSTPONED",
            "earnings_event_id": "EVT-ASTER-2026Q1",
            "event_status": "postponed",
            "scheduled_at": "2026-08-09T15:30:00+09:00",
            "previous_scheduled_at": "2026-08-08T15:30:00+09:00",
            "status_recorded_at": "2026-08-07T19:00:00+09:00",
            "status_reason": "Delay",
            "supersedes_status_record_id": "EVST-ASTER-001",
        }
    )
    statuses.insert(occurred_index, postponed)
    occurred = next(row for row in statuses if row["event_status_record_id"] == "EVST-ASTER-002")
    occurred["scheduled_at"] = postponed["scheduled_at"]
    occurred["supersedes_status_record_id"] = postponed["event_status_record_id"]
    write_rows(status_path, status_fieldnames, statuses)

    report = validate_dataset(samples)
    messages = issue_text(report)
    assert "supersedes_baseline_id cannot reference the same baseline_id" in messages
    assert "current prospective baseline" not in messages
    assert "current locked baseline" not in messages


def test_occurred_review_requires_locked_baseline(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["is_locked"] = "false"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "post-event review requires a matching locked baseline" in issue_text(report)


def test_cli_event_lifecycle_validation(capsys):
    path = PROSPECTIVE_EVENT_LIFECYCLE_SAMPLES / "event_status_history_sample.csv"
    exit_code = cli_main(["validate-file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validation passed." in captured.out


@pytest.mark.parametrize("failure_mode", ["invalid_transition", "missing_target", "malformed_datetime", "multiple_tails"])
def test_cli_event_lifecycle_failures_exit_one(tmp_path, capsys, failure_mode):
    fieldnames, rows = event_lifecycle_fixture()
    if failure_mode == "invalid_transition":
        invalid = dict(rows[3])
        invalid["event_status_record_id"] = "EVST-INVALID-TRANSITION"
        invalid["event_status"] = "scheduled"
        invalid["occurred_at"] = ""
        invalid["status_recorded_at"] = "2026-10-16T10:00:00+09:00"
        invalid["supersedes_status_record_id"] = rows[3]["event_status_record_id"]
        rows.append(invalid)
    elif failure_mode == "missing_target":
        rows[1]["supersedes_status_record_id"] = "EVST-NOT-FOUND"
    elif failure_mode == "malformed_datetime":
        rows[1]["status_recorded_at"] = "not-a-date"
    else:
        branch = dict(rows[5])
        branch["event_status_record_id"] = "EVST-PILOT-B-BRANCH"
        branch["status_recorded_at"] = "2026-09-30T11:00:00+09:00"
        branch["supersedes_status_record_id"] = rows[4]["event_status_record_id"]
        rows.append(branch)
    path = tmp_path / "event_status_history_sample.csv"
    write_rows(path, fieldnames, rows)

    exit_code = cli_main(["validate-file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Validation failed:" in captured.err
    assert "Traceback" not in captured.err


def test_cli_cancelled_event_with_review_exits_one(tmp_path, capsys):
    samples = copy_samples(tmp_path)
    path = samples / "event_status_history_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1].update(
        {"event_status": "cancelled", "occurred_at": "", "status_reason": "Cancelled"}
    )
    write_rows(path, fieldnames, rows)

    exit_code = cli_main(["validate", str(samples)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cancelled event cannot have post-event review or scoring" in captured.err
    assert "event return requires occurred status" in captured.err


@pytest.mark.parametrize(
    ("field_name", "expected_issue"),
    [
        ("locked_at", "locked baseline requires locked_at"),
        ("baseline_record_hash", "locked baseline requires baseline_record_hash"),
    ],
)
def test_locked_baseline_requires_lock_fields(tmp_path, field_name, expected_issue):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1][field_name] = ""
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert expected_issue in issue_text(report)


def test_locked_baseline_requires_sha256_algorithm(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["lock_hash_algorithm"] = ""
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "locked baseline requires sha256 lock_hash_algorithm" in issue_text(report)


@pytest.mark.parametrize("field_name", ["locked_at", "baseline_record_hash", "lock_hash_algorithm"])
def test_draft_baseline_rejects_lock_fields(tmp_path, field_name):
    fieldnames, rows = prospective_baseline_fixture()
    draft = rows[-1]
    values = {
        "locked_at": "2026-08-04T18:40:00+09:00",
        "baseline_record_hash": "a" * 64,
        "lock_hash_algorithm": "sha256",
    }
    draft[field_name] = values[field_name]
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "draft baseline must not contain lock state timestamp hash or algorithm" in issue_text(report)


@pytest.mark.parametrize("review_status", ["approved", "rejected"])
def test_draft_baseline_allows_completed_review_without_lock(tmp_path, review_status):
    fieldnames, rows = prospective_baseline_fixture()
    draft = rows[-1]
    draft["human_review_status"] = review_status
    draft["reviewed_by"] = "reviewer-team-alpha"
    draft["reviewed_at"] = "2026-08-04T18:36:00+09:00"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_pending_draft_rejects_reviewer_metadata(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    draft = rows[-1]
    draft["reviewed_by"] = "reviewer-team-alpha"
    draft["reviewed_at"] = "2026-08-04T18:36:00+09:00"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "pending Human review must not have reviewer identity or reviewed_at" in issue_text(report)


def test_baseline_self_supersession_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["supersedes_baseline_id"] = rows[1]["baseline_id"]
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersedes_baseline_id cannot reference the same baseline_id" in issue_text(report)


def test_missing_superseded_baseline_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["supersedes_baseline_id"] = "BASE-NOT-FOUND"
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "superseded baseline_id not found" in issue_text(report)


def test_forward_baseline_supersession_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    v3 = rows.pop(2)
    rows.insert(1, v3)
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersedes_baseline_id must reference an earlier baseline row" in issue_text(report)


def test_baseline_version_regression_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[2]["baseline_version"] = "v1"
    rehash_baseline(rows[2])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "baseline_version must increase monotonically" in issue_text(report)
    assert "superseding baseline_version must be greater" in issue_text(report)


def test_baseline_versions_are_compared_numerically(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[2]["baseline_version"] = "v10"
    rehash_baseline(rows[2])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_supersedes_baseline_requires_reason(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["supersession_reason"] = ""
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersedes_baseline_id requires supersession_reason" in issue_text(report)


def test_supersession_reason_requires_baseline_reference(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["supersedes_baseline_id"] = ""
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersession_reason requires supersedes_baseline_id" in issue_text(report)


def test_baseline_supersession_event_mismatch_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[2]["earnings_event_id"] = "EVT-HOKUTO-2026Q1"
    rehash_baseline(rows[2])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersession lineage must keep earnings_event_id unchanged" in issue_text(report)


def test_locked_baseline_requires_human_approval(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["human_review_status"] = "pending"
    rows[1]["reviewed_by"] = ""
    rows[1]["reviewed_at"] = ""
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "locked baseline requires approved Human review" in issue_text(report)


def test_locked_baseline_recorded_after_lock_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["recorded_at"] = "2026-08-07T20:05:00+09:00"
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "prospective baseline must be recorded no later than locked_at" in issue_text(report)


def test_locked_baseline_reviewed_after_lock_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["reviewed_at"] = "2026-08-07T20:05:00+09:00"
    rehash_baseline(rows[1])
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "reviewed_at must be no later than locked_at" in issue_text(report)


def test_baseline_hash_mismatch_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["company_guidance_revenue"] = "99999"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "baseline_record_hash does not match canonical locked content" in issue_text(report)


def test_baseline_hash_format_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[1]["baseline_record_hash"] = "not-a-sha256-hash"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "sha256 baseline_record_hash must be 64 hexadecimal characters" in issue_text(report)


def test_duplicate_prospective_baseline_id_fails(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows.append(dict(rows[1]))
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "duplicate unique key" in issue_text(report)


def test_locked_prospective_baseline_requires_formal_evidence(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    rows = [row for row in rows if row["related_entity_id"] not in {"BASE-ASTER-002", "BASE-ASTER-003"}]
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "locked prospective baseline requires related formal evidence" in issue_text(report)


def test_locked_prospective_baseline_requires_score_approved_evidence(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    for row in rows:
        if row["evidence_id"] == "EVD-BASE-ASTER-002":
            row["used_for_score"] = "false"
            row["score_component"] = ""
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "locked prospective baseline requires evidence approved for score use" in issue_text(report)


def test_locked_prospective_baseline_requires_complete_evidence_metadata(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    for row in rows:
        if row["evidence_id"] == "EVD-BASE-ASTER-002":
            row["content_hash_status"] = ""
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "evidence metadata status bundle is incomplete" in issue_text(report)


def test_related_evidence_after_baseline_lock_fails(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    for row in rows:
        if row["evidence_id"] == "EVD-BASE-ASTER-002":
            row["recorded_at"] = "2026-08-07T20:05:00+09:00"
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "related evidence recorded_at must be no later than locked_at" in issue_text(report)


def test_unrelated_evidence_is_not_compared_to_baseline_lock(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    unrelated = dict([row for row in rows if row["evidence_id"] == "EVD-BASE-ASTER-003"][0])
    unrelated.update(
        {
            "evidence_id": "EVD-COMPANY-ASTER-UNRELATED",
            "related_entity_type": "company_master",
            "related_entity_id": "CMP-ASTER",
            "published_at": "2026-08-07T21:30:00+09:00",
            "observed_at": "2026-08-07T21:35:00+09:00",
            "recorded_at": "2026-08-07T21:40:00+09:00",
            "as_of_datetime": "2026-08-07T21:40:00+09:00",
            "used_for_score": "false",
            "score_component": "",
        }
    )
    rows.append(unrelated)
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_draft_baseline_evidence_cannot_be_used_for_score(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    evidence_path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(evidence_path)
    draft_evidence = dict([row for row in rows if row["evidence_id"] == "EVD-BASE-ASTER-002"][0])
    draft_evidence["evidence_id"] = "EVD-BASE-HOKUTO-DRAFT"
    draft_evidence["related_entity_id"] = "BASE-HOKUTO-002-DRAFT"
    rows.append(draft_evidence)
    write_rows(evidence_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "draft baseline evidence cannot be approved for score use" in issue_text(report)


def test_post_event_review_cannot_reference_draft_baseline(tmp_path):
    samples = copy_prospective_baseline_dataset(tmp_path)
    review_path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(review_path)
    rows[0]["baseline_id"] = "BASE-HOKUTO-002-DRAFT"
    write_rows(review_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "post-event review cannot reference a draft baseline" in issue_text(report)


def test_evidence_published_after_observation_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["published_at"] = "2026-08-07T14:05:00+09:00"
    rows[0]["observed_at"] = "2026-08-07T14:00:00+09:00"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "evidence was published after it was observed" in issue_text(report)


def test_evidence_observed_after_recording_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["observed_at"] = "2026-08-07T14:05:00+09:00"
    rows[0]["recorded_at"] = "2026-08-07T14:00:00+09:00"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "evidence was observed after it was recorded" in issue_text(report)


def test_no_trade_rows_are_preserved_with_blank_prices():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)
    _, rows = read_rows(SAMPLES / "post_earnings_review_sample.csv")
    no_trade_rows = [row for row in rows if row["trade_decision"] == "NO_TRADE"]
    assert no_trade_rows
    assert all(row["trade_entry"] == "" and row["stop_loss"] == "" and row["take_profit"] == "" for row in no_trade_rows)


def test_hypothesis_invalidation_appends_without_deleting_parent():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)
    _, rows = read_rows(SAMPLES / "hypothesis_log_sample.csv")
    ids = {row["hypothesis_id"] for row in rows}
    invalidations = [row for row in rows if row["status"] == "invalidated"]
    assert invalidations
    assert all(row["parent_hypothesis_id"] in ids for row in invalidations)


def test_evidence_sample_file_passes():
    report = validate_file(SAMPLES / "evidence_sample.csv")
    assert report.ok, issue_text(report)


def test_legacy_evidence_sample_without_optional_metadata_headers_passes():
    fieldnames, _ = read_rows(SAMPLES / "evidence_sample.csv")
    assert "content_hash_status" not in fieldnames
    report = validate_file(SAMPLES / "evidence_sample.csv")
    assert report.ok, issue_text(report)


def test_existing_optional_evidence_header_remains_required(tmp_path):
    fieldnames, rows = read_rows(SAMPLES / "evidence_sample.csv")
    fieldnames.remove("source_url")
    for row in rows:
        row.pop("source_url")
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "column source_url: missing required column" in issue_text(report)


def test_prospective_evidence_metadata_sample_passes():
    report = validate_file(PROSPECTIVE_EVIDENCE_SAMPLE)
    assert report.ok, issue_text(report)
    _, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    correction = [row for row in rows if row["evidence_status"] == "correction"][0]
    assert correction["supersedes_evidence_id"] == "EVD-PROSPECT-META-001"


@pytest.mark.parametrize(
    ("fixture_name", "expected_issue"),
    [
        ("license_unknown_raw_stored", "raw storage requires license_status permitted"),
        ("verified_hash_missing", "verified content hash requires content_hash and content_hash_algorithm"),
        ("self_supersession", "supersedes_evidence_id cannot reference the same evidence_id"),
    ],
)
def test_invalid_prospective_evidence_samples_fail(fixture_name, expected_issue):
    path = INVALID_EVIDENCE_SAMPLES / fixture_name / "evidence_sample.csv"
    report = validate_file(path)
    assert not report.ok
    assert expected_issue in issue_text(report)


def test_evidence_metadata_enum_is_validated(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[0]["license_status"] = "probably_allowed"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "value 'probably_allowed' is not in allowed set" in issue_text(report)


def test_evidence_metadata_status_bundle_must_be_complete(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[0]["license_status"] = ""
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "evidence metadata status bundle is incomplete" in issue_text(report)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("evidence_status", "original"),
        ("supersedes_evidence_id", "EVD-PROSPECT-META-001"),
        ("content_hash_status", "not_recorded"),
        ("content_hash", "a" * 64),
        ("content_hash_algorithm", "sha256"),
        ("raw_storage_status", "metadata_only"),
        ("raw_location", "external://partial-metadata"),
        ("license_status", "permitted"),
    ],
)
def test_each_partial_metadata_field_activates_bundle_validation(tmp_path, field_name, field_value):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    row = dict(rows[0])
    for metadata_field in EVIDENCE_METADATA_FIELDS:
        row[metadata_field] = ""
    row[field_name] = field_value
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, [row])

    report = validate_file(path)
    assert not report.ok
    assert "evidence metadata status bundle is incomplete" in issue_text(report)


def test_missing_superseded_evidence_fails(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[-1]["supersedes_evidence_id"] = "EVD-NOT-FOUND"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "superseded evidence_id not found" in issue_text(report)


def test_supersession_requires_lineage_status(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[-1]["evidence_status"] = ""
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersedes_evidence_id requires evidence_status correction or retraction_notice" in issue_text(report)


def test_correction_status_requires_superseded_evidence_id(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[-1]["supersedes_evidence_id"] = ""
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "evidence_status correction or retraction_notice requires supersedes_evidence_id" in issue_text(report)


def test_original_evidence_cannot_have_superseded_evidence_id(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[0]["supersedes_evidence_id"] = "EVD-PROSPECT-RAW-001"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "original evidence cannot supersede another evidence row" in issue_text(report)


def test_correction_must_reference_earlier_evidence_row(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    correction = rows.pop()
    rows.insert(0, correction)
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "supersedes_evidence_id must reference an earlier evidence row" in issue_text(report)


def test_duplicate_evidence_id_fails(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    duplicate = dict(rows[0])
    rows.append(duplicate)
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "duplicate unique key" in issue_text(report)


def test_content_hash_mismatch_blocks_validation(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[1]["content_hash_status"] = "mismatch"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "content hash mismatch blocks evidence validation" in issue_text(report)


def test_sha256_hash_format_is_validated(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[1]["content_hash"] = "not-a-sha256-hash"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "sha256 content_hash must be 64 hexadecimal characters" in issue_text(report)


def test_uppercase_sha256_hash_is_accepted(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[1]["content_hash"] = "A" * 64
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_stored_raw_evidence_requires_location(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[1]["raw_location"] = ""
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "stored raw evidence requires raw_location" in issue_text(report)


def test_stored_raw_evidence_rejects_not_applicable_license(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[1]["license_status"] = "not_applicable"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "raw storage requires license_status permitted" in issue_text(report)


def test_correction_lineage_cannot_change_related_entity(tmp_path):
    fieldnames, rows = read_rows(PROSPECTIVE_EVIDENCE_SAMPLE)
    rows[-1]["related_entity_id"] = "EVT-DIFFERENT-001"
    path = tmp_path / "evidence_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "correction lineage must keep related entity unchanged" in issue_text(report)


def test_used_evidence_published_after_baseline_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["published_at"] = "2026-08-07T17:30:00+09:00"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "used evidence was published after baseline as_of_datetime" in issue_text(report)


def test_unknown_tso_mapping_is_not_marked_confirmed():
    mapping_path = PROJECT_ROOT / "docs" / "TSO_LOG_MAPPING_DRAFT.md"
    text = mapping_path.read_text(encoding="utf-8")
    assert "mapping_status |" in text
    assert "| asset |" in text
    assert "| asset | TSO asset symbol | `tso_snapshot` | unknown | required | string | unknown | ERS company mapping is not defined. | unknown |" in text
    assert "unknown mapping should be promoted to confirmed" in text


def test_score_version_before_effective_from_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "score_definition_sample.csv"
    fieldnames, rows = read_rows(path)
    for row in rows:
        if row["scoring_version"] == "ERS-SCORE-0.1":
            row["effective_from"] = "2026-08-08"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "used before effective_from" in issue_text(report)


def test_post_event_data_policy_blocks_pre_event_baseline(tmp_path):
    samples = copy_samples(tmp_path)
    baseline_path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(baseline_path)
    rows[0]["uses_post_event_data"] = "true"
    write_rows(baseline_path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "post-event data cannot be used in pre-event score" in issue_text(report)


def test_post_event_review_evidence_cannot_support_pre_event_score(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    changed = dict(rows[3])
    changed["evidence_id"] = "EVD-POST-LEAK-001"
    changed["related_entity_type"] = "pre_earnings_baseline"
    changed["related_entity_id"] = "BASE-ASTER-001"
    changed["used_for_score"] = "true"
    changed["published_at"] = "2026-08-07T13:00:00+09:00"
    changed["observed_at"] = "2026-08-07T13:10:00+09:00"
    changed["recorded_at"] = "2026-08-07T13:20:00+09:00"
    changed["as_of_datetime"] = "2026-08-07T17:00:00+09:00"
    changed["score_component"] = "post_event_score"
    rows.append(changed)
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    text = issue_text(report)
    assert "post-event review evidence cannot be used for a pre-event score" in text
    assert "post-event score component cannot support a pre-event baseline" in text


def test_intraday_guidance_revision_sample_passes():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)
    _, rows = read_rows(SAMPLES / "earnings_event_sample.csv")
    event = [row for row in rows if row["earnings_event_id"] == "EVT-KISARAGI-2026REV"][0]
    assert event["event_type"] == "guidance_revision"
    assert event["announcement_session"] == "intraday"
    assert event["return_base_price_policy"] == "pre_announcement_price"


def test_session_values_cover_before_open_after_close_and_intraday():
    _, rows = read_rows(SAMPLES / "earnings_event_sample.csv")
    sessions = {row["announcement_session"] for row in rows}
    assert {"before_open", "after_close", "intraday"}.issubset(sessions)


def test_invalid_announcement_session_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "earnings_event_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["announcement_session"] = "lunch_break_magic"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "announcement_session" in issue_text(report)


def test_invalid_accounting_standard_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "earnings_event_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["accounting_standard"] = "LOCAL_CUSTOM"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "accounting_standard" in issue_text(report)


def test_unknown_return_base_price_policy_is_allowed(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "earnings_event_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["return_base_price_policy"] = "unknown"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert report.ok, issue_text(report)


def test_kpi_observation_source_evidence_id_is_validated(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "kpi_observation_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["source_evidence_id"] = "EVD-NOT-FOUND"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "foreign key not found" in issue_text(report)


def test_kpi_expected_before_announcement_and_actual_after_announcement_pass():
    report = validate_dataset(SAMPLES)
    assert report.ok, issue_text(report)
    _, rows = read_rows(SAMPLES / "kpi_observation_sample.csv")
    expected = [row for row in rows if row["value_type"] == "expected"]
    actual = [row for row in rows if row["value_type"] == "actual"]
    assert expected
    assert actual
    assert all(row["used_for_score"] == "true" for row in expected)
    assert all(row["used_for_score"] == "false" for row in actual)


def test_actual_kpi_before_announcement_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "kpi_observation_sample.csv"
    fieldnames, rows = read_rows(path)
    for row in rows:
        if row["kpi_id"] == "KPI-KISARAGI-BACKLOG-ACT-001":
            row["recorded_at"] = "2026-09-10T12:50:00+09:00"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "actual KPI rows must be recorded at or after announcement" in issue_text(report)


def test_actual_kpi_used_for_pre_event_score_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "kpi_observation_sample.csv"
    fieldnames, rows = read_rows(path)
    for row in rows:
        if row["kpi_id"] == "KPI-NOZOMI-ARR-ACT-001":
            row["used_for_score"] = "true"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "KPI rows used for pre-event score must be expected values" in issue_text(report)


def test_case_b_post_event_evidence_cannot_be_used_for_pre_score(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    for row in rows:
        if row["evidence_id"] == "EVD-NOZOMI-POST-001":
            row["related_entity_type"] = "pre_earnings_baseline"
            row["related_entity_id"] = "BASE-NOZOMI-001"
            row["used_for_score"] = "true"
            row["score_component"] = "expectation_overheat_penalty"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    text = issue_text(report)
    assert "post-event review evidence cannot be used for a pre-event score" in text
    assert "used evidence was published after baseline as_of_datetime" in text


def test_event_level_post_announcement_evidence_used_for_pre_score_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    changed = dict(rows[6])
    changed["evidence_id"] = "EVD-EVENT-POST-LEAK-001"
    changed["related_entity_type"] = "earnings_event"
    changed["related_entity_id"] = "EVT-KISARAGI-2026REV"
    changed["used_for_score"] = "true"
    changed["score_component"] = "pre_event_score"
    rows.append(changed)
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "used evidence was published after announcement timestamp" in issue_text(report)


def test_kpi_related_post_announcement_evidence_used_for_pre_score_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "evidence_sample.csv"
    fieldnames, rows = read_rows(path)
    changed = dict(rows[6])
    changed["evidence_id"] = "EVD-KPI-POST-LEAK-001"
    changed["related_entity_type"] = "kpi_observation"
    changed["related_entity_id"] = "KPI-KISARAGI-BACKLOG-EXP-001"
    changed["used_for_score"] = "true"
    changed["score_component"] = "pre_event_score"
    rows.append(changed)
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "used evidence was published after announcement timestamp" in issue_text(report)


def test_review_baseline_event_mismatch_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["baseline_id"] = "BASE-HOKUTO-001"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "baseline earnings_event_id does not match review earnings_event_id" in issue_text(report)


def test_kpi_company_event_mismatch_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "kpi_observation_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["company_id"] = "CMP-ASTER"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "company_id does not match earnings_event company_id" in issue_text(report)


def test_case_c_value_trap_penalty_range_is_enforced(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "pre_earnings_baseline_sample.csv"
    fieldnames, rows = read_rows(path)
    for row in rows:
        if row["baseline_id"] == "BASE-SHIZUKU-001":
            row["value_trap_penalty"] = "101"
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "value_trap_penalty" in issue_text(report)


def test_tso_mapping_keeps_unresolved_fields_unknown():
    mapping_path = PROJECT_ROOT / "docs" / "TSO_LOG_MAPPING_DRAFT.md"
    text = mapping_path.read_text(encoding="utf-8")
    assert "| ffs | FFS score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No ERS column yet. | unknown |" in text
    assert "| origin | Source origin | evidence | `source_name` | optional | string | unknown | Current local `signal_log.csv` includes this extension. | likely |" in text
    assert "origin` must remain provisional" in text


def test_return_fields_require_reference_price_fields(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[0]["return_reference_price_type"] = ""
    rows[0]["return_reference_price"] = ""
    rows[0]["return_reference_price_datetime"] = ""
    write_rows(path, fieldnames, rows)

    report = validate_dataset(samples)
    assert not report.ok
    assert "return reference price fields are required when return fields are present" in issue_text(report)


def test_valid_long_price_order_passes(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1]["trade_decision"] = "LONG"
    rows[1]["trade_entry"] = "100"
    rows[1]["stop_loss"] = "90"
    rows[1]["take_profit"] = "125"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_invalid_long_price_order_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1]["trade_decision"] = "LONG"
    rows[1]["trade_entry"] = "100"
    rows[1]["stop_loss"] = "110"
    rows[1]["take_profit"] = "125"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "expected stop_loss < trade_entry < take_profit for LONG" in issue_text(report)


def test_valid_short_price_order_passes(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1]["trade_decision"] = "SHORT"
    rows[1]["trade_entry"] = "100"
    rows[1]["stop_loss"] = "115"
    rows[1]["take_profit"] = "80"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert report.ok, issue_text(report)


def test_invalid_short_price_order_fails(tmp_path):
    samples = copy_samples(tmp_path)
    path = samples / "post_earnings_review_sample.csv"
    fieldnames, rows = read_rows(path)
    rows[1]["trade_decision"] = "SHORT"
    rows[1]["trade_entry"] = "100"
    rows[1]["stop_loss"] = "90"
    rows[1]["take_profit"] = "80"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "expected take_profit < trade_entry < stop_loss for SHORT" in issue_text(report)
