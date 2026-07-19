import csv
import shutil
from pathlib import Path

from earnings_research.validation.validator import validate_dataset, validate_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = PROJECT_ROOT / "data" / "samples"


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
