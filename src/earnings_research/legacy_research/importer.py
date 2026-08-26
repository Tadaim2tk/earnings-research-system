"""Read-only migration of the legacy earnings research repository."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


DATASET_ORIGIN = "earnings-research-os"
RECORD_MODE = "legacy_observational"
SCHEMA_VERSION = "legacy_earnings_record_v1"
MAPPING_VERSION = "earnings-research-os-29-column-v1"
SOURCE_PATH = "data/records.csv"
TSO_LINK_PATH = "data/ers_legacy_context_link.csv"
TSO_CONTEXT_PATH = "data/market_context_historical.csv"

EXPECTED_FIELDS = (
    "code", "name", "date", "quarter", "rank", "surprise", "company_forecast",
    "rc1", "rc2", "rc3", "narrative", "judge", "buy_condition", "exit_condition",
    "memo", "prev_close", "next_open", "next_close", "d5_close", "d20_close",
    "gap", "ret_d1", "ret_d5", "ret_d20", "shodo", "reaction", "result",
    "error_type", "review_note",
)
PRICE_FIELDS = ("prev_close", "next_open", "next_close", "d5_close", "d20_close")
RETURN_FIELDS = ("gap", "ret_d1", "ret_d5", "ret_d20")
RANKS = ("A", "B+", "B", "C+", "C", "D")
JUDGES = ("即買い候補", "押し目待ち", "監視", "見送り")
NARRATIVES = ("整合", "中立", "衝突")
SURPRISES = ("+2", "+1", "0", "-1", "-2")
FORECASTS = ("上方修正", "維持", "下方修正", "新規", "未開示")


def git_bytes(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def git_text(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout


def resolve_commit(repo: Path, commit: str) -> str:
    value = git_text(repo, "rev-parse", f"{commit}^{{commit}}").strip()
    if len(value) != 40:
        raise ValueError("source commit must resolve to a full Git commit")
    return value


def repository_remote(repo: Path) -> str:
    return git_text(repo, "config", "--get", "remote.origin.url").strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_csv_bytes(value: bytes, expected_fields=None):
    text = value.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = tuple(reader.fieldnames or ())
    if expected_fields is not None and fields != tuple(expected_fields):
        raise ValueError("CSV header does not match the approved legacy contract")
    rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("CSV contains values beyond its declared header")
    return fields, rows


def _choice(value: str, allowed):
    value = (value or "").strip()
    if value in allowed:
        return value
    return None


def _surprise(value: str):
    normalized = (value or "").strip().translate(str.maketrans({"＋": "+", "−": "-", "–": "-", "‑": "-"}))
    if normalized in ("1", "2"):
        normalized = "+" + normalized
    return normalized if normalized in SURPRISES else None


def _decimal(value: str):
    if value in (None, ""):
        return None
    try:
        return format(Decimal(value), "f")
    except InvalidOperation:
        return None


def _record_key(row):
    return row.get("code", ""), row.get("date", "")


def _record_hash(row):
    return sha256_bytes(canonical_json_bytes({field: row.get(field, "") for field in EXPECTED_FIELDS}))


def reconstruct_history(source_repo: Path, source_commit: str, final_rows):
    commits = git_text(source_repo, "rev-list", "--reverse", source_commit, "--", SOURCE_PATH).splitlines()
    if not commits:
        raise ValueError("source history contains no records.csv commit")
    commit_times = {
        line.split("\x1f", 1)[0]: line.split("\x1f", 1)[1]
        for line in git_text(
            source_repo, "log", "--reverse", "--format=%H%x1f%cI", source_commit, "--", SOURCE_PATH
        ).splitlines()
    }
    first_seen = {}
    first_row_hash = {}
    last_changed = {}
    field_history = {}
    previous = {}
    previous_count = -1
    for commit in commits:
        _, rows = parse_csv_bytes(git_bytes(source_repo, commit, SOURCE_PATH), EXPECTED_FIELDS)
        if len(rows) < previous_count:
            raise ValueError("legacy source row count decreased inside Git history")
        previous_count = len(rows)
        current = {_record_key(row): row for row in rows}
        if len(current) != len(rows):
            raise ValueError("legacy source history contains duplicate code/date identity")
        for key, row in current.items():
            if key not in first_seen:
                first_seen[key] = commit
                first_row_hash[key] = _record_hash(row)
                last_changed[key] = commit
            prior = previous.get(key)
            for field in EXPECTED_FIELDS:
                if prior is None or prior.get(field, "") != row.get(field, ""):
                    item = field_history.setdefault((key, field), {})
                    item.setdefault("first_seen_commit", commit)
                    item.setdefault("first_seen_committed_at", commit_times[commit])
                    item["last_changed_commit"] = commit
                    item["last_changed_committed_at"] = commit_times[commit]
                    item["final_raw_value"] = row.get(field, "")
                    last_changed[key] = commit
        previous = current
    final_keys = {_record_key(row) for row in final_rows}
    if final_keys != set(previous):
        raise ValueError("final source rows do not match the reconstructed Git tail")
    return commits, commit_times, first_seen, first_row_hash, last_changed, field_history


def stable_record_id(source_remote: str, first_commit: str, first_row_hash: str) -> str:
    payload = f"{source_remote}\n{first_commit}\n{first_row_hash}".encode("utf-8")
    return "ERSO-" + sha256_bytes(payload)[:20].upper()


def normalize_record(row, record_id, source_row_number, source_commit, first_commit, last_commit):
    warnings = []
    quarter = (row.get("quarter") or "").strip()
    normalized_quarter = {
        "1Q": "Q1", "2Q": "Q2", "3Q": "Q3", "4Q": "Q4", "本決算": "FY",
    }.get(quarter)
    for label, raw, normalized in (
        ("quarter", quarter, normalized_quarter),
        ("rank", row.get("rank", ""), _choice(row.get("rank", ""), RANKS)),
        ("surprise", row.get("surprise", ""), _surprise(row.get("surprise", ""))),
        ("company_forecast", row.get("company_forecast", ""), _choice(row.get("company_forecast", ""), FORECASTS)),
        ("narrative", row.get("narrative", ""), _choice(row.get("narrative", ""), NARRATIVES)),
        ("judge", row.get("judge", ""), _choice(row.get("judge", ""), JUDGES)),
    ):
        if raw and normalized is None:
            warnings.append(f"unmapped_{label}:{raw}")
    price_mapping = {
        "prev_close": "legacy_date_close",
        "next_open": "next_session_open",
        "next_close": "next_session_close",
        "d5_close": "fifth_session_close",
        "d20_close": "twentieth_session_close",
        "gap": "legacy_gap_return",
        "ret_d1": "legacy_d1_return",
        "ret_d5": "legacy_d5_return",
        "ret_d20": "legacy_d20_return",
    }
    prices = {target: _decimal(row.get(source, "")) for source, target in price_mapping.items()}
    for field in PRICE_FIELDS + RETURN_FIELDS:
        if row.get(field, "") and prices[price_mapping[field]] is None:
            warnings.append(f"invalid_decimal:{field}")
    return {
        "schema_version": SCHEMA_VERSION,
        "legacy_record_id": record_id,
        "dataset_origin": DATASET_ORIGIN,
        "record_mode": RECORD_MODE,
        "source_row_number": source_row_number,
        "source_row_sha256": _record_hash(row),
        "source_snapshot_commit": source_commit,
        "source_first_seen_commit": first_commit,
        "source_last_changed_commit": last_commit,
        "mapping_version": MAPPING_VERSION,
        "raw_record": {field: row.get(field, "") for field in EXPECTED_FIELDS},
        "normalized_identity": {
            "ticker_candidate": row.get("code", ""),
            "company_name_candidate": row.get("name", ""),
            "legacy_event_date": row.get("date", ""),
        },
        "normalized_classifications": {
            "quarter": normalized_quarter,
            "legacy_rank": _choice(row.get("rank", ""), RANKS),
            "legacy_surprise": _surprise(row.get("surprise", "")),
            "company_forecast_label": _choice(row.get("company_forecast", ""), FORECASTS),
            "reason_codes": [row[field] for field in ("rc1", "rc2", "rc3") if row.get(field)],
            "legacy_narrative": _choice(row.get("narrative", ""), NARRATIVES),
            "legacy_judge": _choice(row.get("judge", ""), JUDGES),
            "initial_reaction": row.get("shodo") or None,
            "legacy_reaction": row.get("reaction") or None,
        },
        "normalized_prices": prices,
        "normalization_warnings": warnings,
    }


def build_context_views(records, link_bytes: bytes, context_bytes: bytes):
    _, links = parse_csv_bytes(link_bytes)
    _, contexts = parse_csv_bytes(context_bytes)
    if len(links) != len(records):
        raise ValueError("TSO context link count does not match legacy record count")
    links_by_key = {_record_key({"code": row["ers_code"], "date": row["ers_date"]}): row for row in links}
    if len(links_by_key) != len(links):
        raise ValueError("TSO context links contain duplicate code/date identity")
    contexts_by_id = {row["snapshot_id"]: row for row in contexts}
    if len(contexts_by_id) != len(contexts):
        raise ValueError("TSO historical context contains duplicate snapshot IDs")
    views = []
    for record in records:
        raw = record["raw_record"]
        link = links_by_key.get((raw["code"], raw["date"]))
        if link is None:
            raise ValueError("legacy record has no TSO point-in-time link")
        if link.get("ers_name") != raw["name"] or link.get("ers_quarter") != raw["quarter"]:
            raise ValueError("TSO point-in-time link identity does not match legacy record")
        if link.get("join_status") != "ok" or link.get("provenance") != "historical_artifact_join":
            raise ValueError("TSO point-in-time link is not an approved historical join")
        context = contexts_by_id.get(link.get("snapshot_id"))
        if context is None:
            raise ValueError("TSO point-in-time link references a missing context snapshot")
        if link.get("snapshot_usable_from_utc") != context.get("usable_from_utc"):
            raise ValueError("TSO link usable-from timestamp does not match its context snapshot")
        cutoff = _utc_datetime(link["decision_cutoff_utc"])
        event_date = date.fromisoformat(raw["date"])
        if cutoff.date() >= event_date:
            raise ValueError("TSO decision cutoff is not anchored to a prior legacy event date")
        usable = _utc_datetime(context["usable_from_utc"])
        if usable > cutoff:
            raise ValueError("TSO context became usable after the legacy decision cutoff")
        views.append({
            "schema_version": "legacy_context_view_v1",
            "legacy_record_id": record["legacy_record_id"],
            "dataset_origin": DATASET_ORIGIN,
            "record_mode": RECORD_MODE,
            "ticker": raw["code"],
            "company_name": raw["name"],
            "legacy_event_date": raw["date"],
            "legacy_quarter": raw["quarter"],
            "decision_cutoff_utc": link["decision_cutoff_utc"],
            "join_status": link["join_status"],
            "tso_snapshot_id": link["snapshot_id"],
            "tso_provenance": link["provenance"],
            "tso_source_run_id": link["source_run_id"],
            "tso_source_artifact_id": link["source_artifact_id"],
            "lag_hours": link["lag_hours"],
            "market_context": context,
        })
    return views, links, contexts


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" UTC", "+00:00"))


def jsonl_bytes(items) -> bytes:
    return b"".join(canonical_json_bytes(item) + b"\n" for item in items)


def write_atomic_tree(output_root: Path, files: dict[str, bytes]):
    output_root = Path(output_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=output_root.name + ".", dir=output_root.parent))
    try:
        for relative, content in files.items():
            path = temp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if output_root.exists():
            existing = {
                str(path.relative_to(output_root)): path.read_bytes()
                for path in output_root.rglob("*") if path.is_file()
            }
            generated = {
                str(path.relative_to(temp)): path.read_bytes()
                for path in temp.rglob("*") if path.is_file()
            }
            if existing != generated:
                raise FileExistsError("existing migration output differs; use a new migration version")
            return
        temp.replace(output_root)
        temp = None
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def build_import(
    source_repo: Path,
    source_commit: str,
    source_run_id: str,
    tso_repo: Path,
    tso_commit: str,
    migration_recorded_at: str,
):
    source_repo = Path(source_repo)
    tso_repo = Path(tso_repo)
    source_commit = resolve_commit(source_repo, source_commit)
    tso_commit = resolve_commit(tso_repo, tso_commit)
    if not source_run_id.strip():
        raise ValueError("source workflow run ID is required")
    recorded_at = datetime.fromisoformat(migration_recorded_at)
    if recorded_at.tzinfo is None:
        raise ValueError("migration_recorded_at must include timezone")
    source_remote = repository_remote(source_repo)
    tso_remote = repository_remote(tso_repo)
    source_bytes = git_bytes(source_repo, source_commit, SOURCE_PATH)
    fields, rows = parse_csv_bytes(source_bytes, EXPECTED_FIELDS)
    keys = [_record_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("legacy source contains duplicate code/date identity")
    commits, commit_times, first_seen, first_hashes, last_changed, history = reconstruct_history(
        source_repo, source_commit, rows
    )
    records = []
    record_ids = {}
    for number, row in enumerate(rows, 2):
        key = _record_key(row)
        record_id = stable_record_id(source_remote, first_seen[key], first_hashes[key])
        record_ids[key] = record_id
        records.append(normalize_record(
            row, record_id, number, source_commit, first_seen[key], last_changed[key]
        ))
    history_items = []
    for row in rows:
        key = _record_key(row)
        for field in EXPECTED_FIELDS:
            item = history[(key, field)]
            history_items.append({
                "legacy_record_id": record_ids[key],
                "field_name": field,
                "first_seen_commit": item["first_seen_commit"],
                "first_seen_committed_at": item["first_seen_committed_at"],
                "last_changed_commit": item["last_changed_commit"],
                "last_changed_committed_at": item["last_changed_committed_at"],
                "final_raw_value_sha256": sha256_bytes(row.get(field, "").encode("utf-8")),
            })
    link_bytes = git_bytes(tso_repo, tso_commit, TSO_LINK_PATH)
    context_bytes = git_bytes(tso_repo, tso_commit, TSO_CONTEXT_PATH)
    context_views, links, contexts = build_context_views(records, link_bytes, context_bytes)
    normalized_bytes = jsonl_bytes(records)
    history_bytes = jsonl_bytes(history_items)
    context_view_bytes = jsonl_bytes(context_views)
    files = {
        "source/records.csv": source_bytes,
        "source/tso/ers_legacy_context_link.csv": link_bytes,
        "source/tso/market_context_historical.csv": context_bytes,
        "legacy_records.jsonl": normalized_bytes,
        "field_history.jsonl": history_bytes,
        "legacy_context_view.jsonl": context_view_bytes,
    }
    manifest = {
        "schema_version": "legacy_migration_manifest_v1",
        "dataset_origin": DATASET_ORIGIN,
        "record_mode": RECORD_MODE,
        "migration_version": "v1",
        "mapping_version": MAPPING_VERSION,
        "migration_recorded_at": migration_recorded_at,
        "source_repository": source_remote,
        "source_branch": "main",
        "frozen_source_commit": source_commit,
        "source_workflow_run_id": source_run_id,
        "source_path": SOURCE_PATH,
        "source_sha256": sha256_bytes(source_bytes),
        "source_row_count": len(rows),
        "source_column_count": len(fields),
        "source_header": list(fields),
        "source_history_commit_count": len(commits),
        "source_first_commit": commits[0],
        "source_last_commit": commits[-1],
        "tso_repository": tso_remote,
        "tso_source_commit": tso_commit,
        "tso_link_row_count": len(links),
        "tso_context_snapshot_count": len(contexts),
        "tso_join_status_counts": dict(sorted(Counter(row["join_status"] for row in links).items())),
        "output_sha256": {name: sha256_bytes(content) for name, content in sorted(files.items())},
        "reports_sha256": {},
        "prospective_records_created": 0,
        "formal_evidence_created": 0,
        "tso_writeback_performed": False,
    }
    files["migration_manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    return files, manifest, records, context_views
