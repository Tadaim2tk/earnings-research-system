import csv
import shutil
from pathlib import Path

import pytest

from earnings_research.validation.validator import (
    BASELINE_LOCK_HASH_FIELDS_V1,
    _calculate_baseline_record_hash,
    load_spec,
    validate_dataset,
    validate_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "data" / "samples"
PROSPECTIVE_EVIDENCE_SAMPLE = SAMPLES / "prospective_evidence" / "evidence_sample.csv"
INVALID_EVIDENCE_SAMPLES = SAMPLES / "invalid_evidence"
PROSPECTIVE_BASELINE_SAMPLES = SAMPLES / "prospective_baseline"
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
    existing_baseline_ids = {row["baseline_id"] for row in baseline_rows}
    normalized_baselines = [{field: row.get(field, "") for field in fixture_fieldnames} for row in baseline_rows]
    normalized_baselines.extend(row for row in fixture_rows if row["baseline_id"] not in existing_baseline_ids)
    write_rows(baseline_path, fixture_fieldnames, normalized_baselines)

    evidence_path = samples / "evidence_sample.csv"
    _, evidence_rows = read_rows(evidence_path)
    evidence_fieldnames, fixture_evidence = read_rows(PROSPECTIVE_BASELINE_SAMPLES / "evidence_sample.csv")
    normalized_evidence = [{field: row.get(field, "") for field in evidence_fieldnames} for row in evidence_rows]
    normalized_evidence.extend(fixture_evidence)
    write_rows(evidence_path, evidence_fieldnames, normalized_evidence)
    return samples


def prospective_baseline_fixture():
    return read_rows(PROSPECTIVE_BASELINE_SAMPLES / "pre_earnings_baseline_sample.csv")


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


def test_prospective_baseline_version_format_is_validated(tmp_path):
    fieldnames, rows = prospective_baseline_fixture()
    rows[-1]["baseline_version"] = "v0"
    path = tmp_path / "pre_earnings_baseline_sample.csv"
    write_rows(path, fieldnames, rows)

    report = validate_file(path)
    assert not report.ok
    assert "prospective baseline_version must use v followed by an integer of at least 1" in issue_text(report)


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
