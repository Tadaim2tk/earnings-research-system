"""End-to-end legacy migration entry point."""

import hashlib
import json
import csv

from datetime import date
from pathlib import Path

from .importer import build_import, write_atomic_tree
from .publishing import build_reports, reporting_date, write_reports


def migrate_legacy_os(
    source_repo: Path,
    source_commit: str,
    source_run_id: str,
    tso_repo: Path,
    tso_commit: str,
    output_root: Path,
    reports_output: Path,
    migration_recorded_at: str,
    as_of_date: date,
):
    files, manifest, records, context_views = build_import(
        source_repo, source_commit, source_run_id, tso_repo, tso_commit, migration_recorded_at
    )
    raw_rows = [record["raw_record"] for record in records]
    # The reports produced here are verified afterwards against the same
    # reports rebuilt from the committed migration, and that rebuild derives
    # its as-of from the record. A caller supplying a different one produced
    # files that failed their own verification on the next run, and rebuilding
    # them moved the weekly reporting window without saying so. Refused rather
    # than quietly overridden: the caller stated a date, and being told it
    # disagrees with the record is more use than having it replaced.
    derived = reporting_date(raw_rows)
    if as_of_date != derived:
        raise ValueError(
            "--as-of-date %s does not match the last day the record covers (%s); "
            "the published reports are verified against a date derived from the "
            "record, so the two have to agree" % (as_of_date, derived)
        )
    source_outputs, reports, parity = build_reports(
        Path(source_repo), manifest["frozen_source_commit"], raw_rows, context_views, as_of_date
    )
    files.update(source_outputs)
    manifest["output_sha256"].update({
        name: hashlib.sha256(content).hexdigest()
        for name, content in source_outputs.items()
    })
    manifest["reports_sha256"] = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(reports.items())
    }
    files["migration_manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    write_atomic_tree(output_root, files)
    write_reports(reports_output, reports)
    return {
        "status": "migrated",
        "source_commit": manifest["frozen_source_commit"],
        "record_count": manifest["source_row_count"],
        "tso_context_link_count": manifest["tso_link_row_count"],
        "publishing_parity": all(item["byte_equal"] for item in parity.values()),
        "output_root": str(output_root),
        "reports_output": str(reports_output),
    }


def verify_legacy_migration(output_root: Path, reports_output: Path):
    output_root = Path(output_root)
    reports_output = Path(reports_output)
    manifest = json.loads((output_root / "migration_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_origin") != "earnings-research-os":
        raise ValueError("migration manifest dataset origin is invalid")
    if manifest.get("record_mode") != "legacy_observational":
        raise ValueError("migration manifest record mode is invalid")
    if manifest.get("prospective_records_created") != 0 or manifest.get("formal_evidence_created") != 0:
        raise ValueError("legacy migration must not create prospective or formal evidence records")
    if manifest.get("tso_writeback_performed") is not False:
        raise ValueError("legacy migration must not write back to TSO")
    for relative, expected in manifest.get("output_sha256", {}).items():
        path = output_root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"migration output hash mismatch: {relative}")
    source = output_root / "source/records.csv"
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest.get("source_sha256"):
        raise ValueError("legacy source snapshot hash mismatch")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    records = [json.loads(line) for line in (output_root / "legacy_records.jsonl").read_text(encoding="utf-8").splitlines()]
    contexts = [json.loads(line) for line in (output_root / "legacy_context_view.jsonl").read_text(encoding="utf-8").splitlines()]
    history_count = len((output_root / "field_history.jsonl").read_text(encoding="utf-8").splitlines())
    expected_count = manifest.get("source_row_count")
    if len(source_rows) != expected_count or len(records) != expected_count or len(contexts) != expected_count:
        raise ValueError("legacy migration row counts disagree")
    if history_count != expected_count * manifest.get("source_column_count", 0):
        raise ValueError("legacy per-field history is incomplete")
    for source_row, record, context in zip(source_rows, records, contexts):
        if record.get("raw_record") != source_row:
            raise ValueError("normalized legacy record does not preserve its raw row")
        if record.get("dataset_origin") != "earnings-research-os" or record.get("record_mode") != "legacy_observational":
            raise ValueError("normalized legacy record escaped its cohort")
        if context.get("legacy_record_id") != record.get("legacy_record_id") or context.get("join_status") != "ok":
            raise ValueError("legacy TSO context view does not match its record")
    reports_hashes = manifest.get("reports_sha256", {})
    for name in ("dashboard.md", "weekly_report.md", "note_draft.md", "aggregation_summary.json", "publishing_parity.json"):
        expected = reports_hashes.get(name)
        path = reports_output / name
        if not expected or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"legacy report output hash mismatch: {name}")
    parity = json.loads((reports_output / "publishing_parity.json").read_text(encoding="utf-8"))
    if not all(item.get("byte_equal") for item in parity.get("outputs", {}).values()):
        raise ValueError("legacy publishing parity is not complete")
    aggregation = json.loads((reports_output / "aggregation_summary.json").read_text(encoding="utf-8"))
    # record_count became the explored subset when the reserve was introduced,
    # so the migration's completeness is asserted against the total instead. A
    # summary that lost rows on the way in still fails; one that merely holds
    # some back does not.
    counted = aggregation.get("record_count_including_reserved", aggregation.get("record_count"))
    if counted != expected_count or aggregation.get("prospective_records_included") != 0:
        raise ValueError("legacy aggregation count or cohort is invalid")
    return {
        "status": "verified",
        "record_count": expected_count,
        "field_history_count": history_count,
        "tso_context_link_count": len(contexts),
        "publishing_outputs_verified": len(parity["outputs"]),
    }
