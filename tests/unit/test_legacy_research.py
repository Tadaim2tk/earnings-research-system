import csv
import json
import subprocess
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from earnings_research.cli.__main__ import main
from earnings_research.legacy_research.importer import EXPECTED_FIELDS, build_import
from earnings_research.legacy_research.pipeline import migrate_legacy_os, verify_legacy_migration
from earnings_research.legacy_research.publishing import render_dashboard, render_note, render_weekly


ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def init_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://example.invalid/{path.name}.git"], cwd=path, check=True)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def commit_all(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    return git(repo, "rev-parse", "HEAD")


def row(code="1111", name="架空会社", event_date="2026-06-10"):
    item = {field: "" for field in EXPECTED_FIELDS}
    item.update({
        "code": code, "name": name, "date": event_date, "quarter": "1Q", "rank": "B",
        "surprise": "+1", "company_forecast": "維持", "rc1": "segment_growth",
        "narrative": "整合", "judge": "監視", "buy_condition": "legacy entry text",
        "exit_condition": "legacy exit text", "memo": "legacy memo",
    })
    return item


def make_source(tmp_path):
    repo = tmp_path / "old"
    init_repo(repo)
    first = row()
    write_csv(repo / "data/records.csv", EXPECTED_FIELDS, [first])
    commit_all(repo, "initial")
    first.update({
        "prev_close": "100", "next_open": "102", "next_close": "103", "d5_close": "105",
        "d20_close": "110", "gap": "0.02", "ret_d1": "0.03", "ret_d5": "0.05",
        "ret_d20": "0.1", "shodo": "GU", "reaction": "GU継続",
    })
    second = row("2222", "別の架空会社")
    write_csv(repo / "data/records.csv", EXPECTED_FIELDS, [first, second])
    as_of = date(2026, 6, 10)
    (repo / "dashboard.md").write_text(render_dashboard([first, second], "2026-06-10 20:00"), encoding="utf-8")
    (repo / "weekly_report.md").write_text(render_weekly([first, second], as_of), encoding="utf-8")
    (repo / "note_draft.md").write_text(render_note([first, second], as_of), encoding="utf-8")
    return repo, commit_all(repo, "enrich")


def make_tso(tmp_path, future=False, wrong_name=False, bad_cutoff=False, spoofed_usable=False):
    repo = tmp_path / "tso"
    init_repo(repo)
    context_fields = [
        "snapshot_id", "provenance", "context_date", "generated_at_utc", "generated_at_jst",
        "usable_from_utc", "source_run_id", "risk_on_score", "risk_off_score", "status",
        "source_artifact_id",
    ]
    # The context row always carries the snapshot's real usable-from timestamp.
    real_usable = "2026-06-10 01:00:00 UTC" if (future or spoofed_usable) else "2026-06-09 22:00:05 UTC"
    contexts = [{
        "snapshot_id": "MCTX-1", "provenance": "historical_artifact_join", "context_date": "2026-06-09",
        "generated_at_utc": "2026-06-09 22:00:00 UTC", "generated_at_jst": "2026-06-10 07:00:00 JST",
        "usable_from_utc": real_usable,
        "source_run_id": "10", "risk_on_score": "55", "risk_off_score": "45", "status": "ok",
        "source_artifact_id": "20",
    }]
    # spoofed_usable: the link claims an early usable-from time even though the
    # referenced context snapshot's real usable-from time is later (future leak).
    link_usable = "2026-06-09 22:00:05 UTC" if spoofed_usable else real_usable
    # bad_cutoff: decision_cutoff_utc is not anchored to a day prior to the legacy event date.
    cutoff = "2026-06-10 00:00:00 UTC" if bad_cutoff else "2026-06-09 23:00:00 UTC"
    link_fields = [
        "ers_code", "ers_name", "ers_date", "ers_quarter", "decision_cutoff_utc", "join_status",
        "snapshot_id", "provenance", "snapshot_usable_from_utc", "snapshot_generated_at_utc",
        "lag_hours", "snapshot_status", "snapshot_max_asset_staleness_days", "source_artifact_id",
        "source_run_id",
    ]
    links = []
    for code, name in (("1111", "違う会社" if wrong_name else "架空会社"), ("2222", "別の架空会社")):
        links.append({
            "ers_code": code, "ers_name": name, "ers_date": "2026-06-10", "ers_quarter": "1Q",
            "decision_cutoff_utc": cutoff, "join_status": "ok",
            "snapshot_id": "MCTX-1", "provenance": "historical_artifact_join",
            "snapshot_usable_from_utc": link_usable,
            "snapshot_generated_at_utc": contexts[0]["generated_at_utc"], "lag_hours": "2",
            "snapshot_status": "ok", "snapshot_max_asset_staleness_days": "0",
            "source_artifact_id": "20", "source_run_id": "10",
        })
    write_csv(repo / "data/ers_legacy_context_link.csv", link_fields, links)
    write_csv(repo / "data/market_context_historical.csv", context_fields, contexts)
    return repo, commit_all(repo, "contexts")


def test_lossless_import_keeps_raw_history_and_context(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    result = migrate_legacy_os(
        source, source_commit, "source-run-1", tso, tso_commit, output, reports,
        "2026-08-26T08:00:00+09:00", date(2026, 6, 10),
    )
    assert result["record_count"] == 2
    assert result["tso_context_link_count"] == 2
    assert result["publishing_parity"] is True
    assert (output / "source/records.csv").read_bytes() == (source / "data/records.csv").read_bytes()
    records = [json.loads(line) for line in (output / "legacy_records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(item["dataset_origin"] == "earnings-research-os" for item in records)
    assert all(item["record_mode"] == "legacy_observational" for item in records)
    assert records[0]["raw_record"]["buy_condition"] == "legacy entry text"
    assert records[0]["normalized_prices"]["legacy_d20_return"] == "0.1"
    assert len((output / "field_history.jsonl").read_text(encoding="utf-8").splitlines()) == 58
    contexts = [json.loads(line) for line in (output / "legacy_context_view.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(contexts) == 2
    assert contexts[0]["market_context"]["risk_on_score"] == "55"
    assert all(path.exists() for path in (reports / "dashboard.md", reports / "weekly_report.md", reports / "note_draft.md"))
    summary = json.loads((reports / "aggregation_summary.json").read_text(encoding="utf-8"))
    assert summary["record_count"] == 2
    assert summary["market_context"]["linked_count"] == 2
    assert summary["prospective_records_included"] == 0
    assert verify_legacy_migration(output, reports)["field_history_count"] == 58


def test_same_source_is_idempotent_but_changed_output_is_not_overwritten(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    kwargs = dict(source_repo=source, source_commit=source_commit, source_run_id="source-run-1", tso_repo=tso, tso_commit=tso_commit,
                  output_root=output, reports_output=tmp_path / "reports",
                  migration_recorded_at="2026-08-26T08:00:00+09:00", as_of_date=date(2026, 6, 10))
    migrate_legacy_os(**kwargs)
    migrate_legacy_os(**kwargs)
    (output / "legacy_records.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        migrate_legacy_os(**kwargs)


def test_context_future_leak_and_identity_mismatch_are_rejected(tmp_path):
    source, source_commit = make_source(tmp_path)
    future_tso, future_commit = make_tso(tmp_path, future=True)
    with pytest.raises(ValueError, match="usable after"):
        build_import(source, source_commit, "source-run-1", future_tso, future_commit, "2026-08-26T08:00:00+09:00")
    other = tmp_path / "other"
    other.mkdir()
    bad_tso, bad_commit = make_tso(other, wrong_name=True)
    with pytest.raises(ValueError, match="identity"):
        build_import(source, source_commit, "source-run-1", bad_tso, bad_commit, "2026-08-26T08:00:00+09:00")


def test_context_cutoff_and_usable_from_are_cross_checked(tmp_path):
    source, source_commit = make_source(tmp_path)
    # decision_cutoff_utc must be anchored to a day prior to the legacy event date,
    # not merely trusted as whatever the TSO link supplies.
    other = tmp_path / "other_bad_cutoff"
    other.mkdir()
    bad_cutoff_tso, bad_cutoff_commit = make_tso(other, bad_cutoff=True)
    with pytest.raises(ValueError, match="not anchored to a prior legacy event date"):
        build_import(source, source_commit, "source-run-1", bad_cutoff_tso, bad_cutoff_commit, "2026-08-26T08:00:00+09:00")
    # snapshot_usable_from_utc on the link must match the referenced context row's own
    # usable_from_utc; a link that copies an early time while the real snapshot became
    # usable later must not be trusted.
    spoofed = tmp_path / "spoofed_usable"
    spoofed.mkdir()
    spoofed_tso, spoofed_commit = make_tso(spoofed, spoofed_usable=True)
    with pytest.raises(ValueError, match="does not match its context snapshot"):
        build_import(source, source_commit, "source-run-1", spoofed_tso, spoofed_commit, "2026-08-26T08:00:00+09:00")


def test_schema_rejects_prospective_promotion(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    files, manifest, records, _ = build_import(source, source_commit, "source-run-1", tso, tso_commit, "2026-08-26T08:00:00+09:00")
    record_schema = json.loads((ROOT / "schemas/analysis/legacy_earnings_record.schema.json").read_text(encoding="utf-8"))
    manifest_schema = json.loads((ROOT / "schemas/analysis/legacy_migration_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(records[0], record_schema)
    jsonschema.validate(manifest, manifest_schema)
    records[0]["record_mode"] = "prospective"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(records[0], record_schema)
    assert files["source/records.csv"] == (source / "data/records.csv").read_bytes()


def test_cli_completes_one_integrated_migration(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    assert main([
        "migrate-legacy-os", "--source-repo", str(source), "--source-commit", source_commit,
        "--source-run-id", "source-run-1",
        "--tso-repo", str(tso), "--tso-commit", tso_commit, "--output-root", str(output),
        "--reports-output", str(reports), "--migration-recorded-at", "2026-08-26T08:00:00+09:00",
        "--as-of-date", "2026-06-10",
    ]) == 0
    assert json.loads((output / "migration_manifest.json").read_text(encoding="utf-8"))["prospective_records_created"] == 0
    assert main([
        "verify-legacy-migration", "--output-root", str(output), "--reports-output", str(reports)
    ]) == 0


def test_verifier_rejects_tampered_committed_data(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", date(2026, 6, 10))
    with (output / "legacy_records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_legacy_migration(output, reports)


def test_verifier_rejects_tampered_report_outputs(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", date(2026, 6, 10))
    verify_legacy_migration(output, reports)
    (reports / "dashboard.md").write_text("tampered dashboard\n", encoding="utf-8")
    with pytest.raises(ValueError, match="legacy report output hash mismatch: dashboard.md"):
        verify_legacy_migration(output, reports)


def test_verifier_rejects_tampered_publishing_parity(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", date(2026, 6, 10))
    parity_path = reports / "publishing_parity.json"
    tampered = json.loads(parity_path.read_text(encoding="utf-8"))
    for item in tampered["outputs"].values():
        item["byte_equal"] = True
    parity_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="legacy report output hash mismatch: publishing_parity.json"):
        verify_legacy_migration(output, reports)
