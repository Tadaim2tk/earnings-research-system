"""CSV validation for the Earnings Research System foundation."""

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from earnings_research.validation.spec import ColumnSpec, TableSpec

JST = timezone(timedelta(hours=9))
TABLE_ORDER = [
    "company_master",
    "earnings_event",
    "score_definition",
    "pre_earnings_baseline",
    "post_earnings_review",
    "tso_snapshot",
    "hypothesis_log",
    "evidence",
    "kpi_observation",
]


@dataclass
class ValidationIssue:
    """One validation failure."""

    table: str
    row_number: Optional[int]
    column: Optional[str]
    message: str

    def format(self) -> str:
        """Return a compact human-readable issue string."""
        location = self.table
        if self.row_number is not None:
            location += " row %s" % self.row_number
        if self.column:
            location += " column %s" % self.column
        return "%s: %s" % (location, self.message)


@dataclass
class ValidationReport:
    """Validation result for one file or dataset."""

    issues: List[ValidationIssue]

    @property
    def ok(self) -> bool:
        """Whether validation passed."""
        return not self.issues

    def raise_if_failed(self) -> None:
        """Raise ValueError when validation failed."""
        if self.issues:
            raise ValueError("\n".join(issue.format() for issue in self.issues))


def project_root() -> Path:
    """Return the project root inferred from the package location."""
    return Path(__file__).resolve().parents[3]


def schema_dir() -> Path:
    """Return the schema directory."""
    return project_root() / "schemas"


def load_specs() -> Dict[str, TableSpec]:
    """Load table specs from JSON schema metadata files."""
    specs = {}
    for path in sorted(schema_dir().glob("*.schema.json")):
        with path.open("r", encoding="utf-8") as handle:
            spec = TableSpec.model_validate(json.load(handle))
        specs[spec.table] = spec
    return specs


def load_spec(table: str) -> TableSpec:
    """Load one table spec by name."""
    specs = load_specs()
    try:
        return specs[table]
    except KeyError as exc:
        raise ValueError("Unknown schema: %s" % table) from exc


def validate_dataset(dataset_dir: Path) -> ValidationReport:
    """Validate a directory containing the expected CSV files."""
    dataset_dir = Path(dataset_dir)
    specs = load_specs()
    rows_by_table = {}
    issues = []

    for table in TABLE_ORDER:
        spec = specs[table]
        path = dataset_dir / spec.file
        if not path.exists():
            issues.append(ValidationIssue(table, None, None, "missing expected file %s" % spec.file))
            rows_by_table[table] = []
            continue
        rows, table_issues = _read_and_validate_table(path, spec)
        rows_by_table[table] = rows
        issues.extend(table_issues)

    if issues:
        return ValidationReport(issues)

    issues.extend(_validate_foreign_keys(specs, rows_by_table))
    issues.extend(_validate_scoring_versions(rows_by_table))
    issues.extend(_validate_score_effective_dates(rows_by_table))
    issues.extend(_validate_temporal_constraints(rows_by_table))
    issues.extend(_validate_relationship_consistency(rows_by_table))
    issues.extend(_validate_kpi_constraints(rows_by_table))
    issues.extend(_validate_evidence_constraints(specs, rows_by_table))
    issues.extend(_validate_return_reference_constraints(rows_by_table))
    issues.extend(_validate_trade_constraints(rows_by_table))
    issues.extend(_validate_append_only_constraints(rows_by_table))
    issues.extend(_validate_hypothesis_constraints(rows_by_table))
    return ValidationReport(issues)


def validate_file(path: Path) -> ValidationReport:
    """Validate a single CSV file against the matching table schema."""
    path = Path(path)
    specs = load_specs()
    spec = _match_spec_for_file(path, specs.values())
    rows, issues = _read_and_validate_table(path, spec)

    if spec.table == "post_earnings_review":
        issues.extend(_validate_trade_constraints({spec.table: rows}))
        issues.extend(_validate_return_reference_constraints({spec.table: rows}))
    if spec.table == "pre_earnings_baseline":
        issues.extend(_validate_append_only_constraints({spec.table: rows}))
    if spec.table == "hypothesis_log":
        issues.extend(_validate_hypothesis_constraints({spec.table: rows}))
    if spec.table == "evidence":
        issues.extend(_validate_evidence_metadata_constraints(rows))
    return ValidationReport(issues)


def _match_spec_for_file(path: Path, specs: Iterable[TableSpec]) -> TableSpec:
    stem = path.stem
    for spec in specs:
        if path.name == spec.file or stem == spec.table or stem == "%s_sample" % spec.table:
            return spec
    raise ValueError("Could not infer schema for %s" % path)


def _read_and_validate_table(path: Path, spec: TableSpec) -> Tuple[List[Dict[str, str]], List[ValidationIssue]]:
    issues = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in spec.required_columns if column not in fieldnames]
        for column in missing:
            issues.append(ValidationIssue(spec.table, None, column, "missing required column"))
        if missing:
            return [], issues

        rows = list(reader)

    column_by_name = {column.name: column for column in spec.columns}
    for row_number, row in enumerate(rows, start=2):
        for column in spec.columns:
            value = _clean(row.get(column.name, ""))
            if column.required and value == "":
                issues.append(ValidationIssue(spec.table, row_number, column.name, "required value is blank"))
                continue
            if value != "":
                issues.extend(_validate_value(spec.table, row_number, column, value))

    key_sets = [spec.primary_key] + list(spec.unique)
    for key_columns in key_sets:
        issues.extend(_validate_unique_key(spec.table, rows, key_columns))

    return rows, issues


def _validate_value(table: str, row_number: int, column: ColumnSpec, value: str) -> List[ValidationIssue]:
    issues = []
    parsed = None
    try:
        if column.type == "string":
            parsed = value
        elif column.type == "integer":
            parsed = int(value)
        elif column.type == "decimal":
            parsed = Decimal(value)
        elif column.type == "date":
            parsed = date.fromisoformat(value)
        elif column.type == "time":
            parsed = time.fromisoformat(value)
        elif column.type == "datetime":
            parsed = datetime.fromisoformat(value)
        elif column.type == "boolean":
            if value.lower() not in {"true", "false"}:
                raise ValueError("expected true or false")
            parsed = value.lower() == "true"
        elif column.type == "enum":
            if column.allowed and value not in column.allowed:
                issues.append(ValidationIssue(table, row_number, column.name, "value %r is not in allowed set" % value))
            parsed = value
        else:
            issues.append(ValidationIssue(table, row_number, column.name, "unknown schema type %s" % column.type))
    except (ValueError, InvalidOperation):
        issues.append(ValidationIssue(table, row_number, column.name, "invalid %s value %r" % (column.type, value)))
        return issues

    if isinstance(parsed, (int, Decimal)):
        if column.min is not None and Decimal(parsed) < Decimal(str(column.min)):
            issues.append(ValidationIssue(table, row_number, column.name, "value is below minimum %s" % column.min))
        if column.max is not None and Decimal(parsed) > Decimal(str(column.max)):
            issues.append(ValidationIssue(table, row_number, column.name, "value is above maximum %s" % column.max))
    return issues


def _validate_unique_key(table: str, rows: List[Dict[str, str]], columns: Sequence[str]) -> List[ValidationIssue]:
    issues = []
    seen = {}
    for row_number, row in enumerate(rows, start=2):
        key = tuple(_clean(row.get(column, "")) for column in columns)
        if any(value == "" for value in key):
            continue
        if key in seen:
            issues.append(
                ValidationIssue(table, row_number, ",".join(columns), "duplicate unique key also seen at row %s" % seen[key])
            )
        else:
            seen[key] = row_number
    return issues


def _validate_foreign_keys(specs: Dict[str, TableSpec], rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    indexes = {}
    for table, spec in specs.items():
        rows = rows_by_table.get(table, [])
        for key_columns in [spec.primary_key] + list(spec.unique):
            indexes[(table, tuple(key_columns))] = {
                tuple(_clean(row.get(column, "")) for column in key_columns)
                for row in rows
            }

    for table, spec in specs.items():
        for foreign_key in spec.foreign_keys:
            ref_key = (foreign_key.ref_table, tuple(foreign_key.ref_columns))
            ref_values = indexes.get(ref_key, set())
            for row_number, row in enumerate(rows_by_table.get(table, []), start=2):
                key = tuple(_clean(row.get(column, "")) for column in foreign_key.columns)
                if foreign_key.nullable and all(value == "" for value in key):
                    continue
                if key not in ref_values:
                    issues.append(
                        ValidationIssue(
                            table,
                            row_number,
                            ",".join(foreign_key.columns),
                            "foreign key not found in %s.%s" % (foreign_key.ref_table, ",".join(foreign_key.ref_columns)),
                        )
                    )
    return issues


def _validate_scoring_versions(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    versions = {_clean(row.get("scoring_version", "")) for row in rows_by_table.get("score_definition", [])}
    for table in ("pre_earnings_baseline", "post_earnings_review"):
        for row_number, row in enumerate(rows_by_table.get(table, []), start=2):
            version = _clean(row.get("scoring_version", ""))
            if version and version not in versions:
                issues.append(ValidationIssue(table, row_number, "scoring_version", "undefined scoring_version %s" % version))
    return issues


def _validate_score_effective_dates(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    effective_from_by_version = {}
    for row in rows_by_table.get("score_definition", []):
        version = _clean(row.get("scoring_version", ""))
        effective_from = _parse_date(_clean(row.get("effective_from", "")))
        if not version or not effective_from:
            continue
        current = effective_from_by_version.get(version)
        if current is None or effective_from > current:
            effective_from_by_version[version] = effective_from

    for table in ("pre_earnings_baseline", "post_earnings_review"):
        for row_number, row in enumerate(rows_by_table.get(table, []), start=2):
            version = _clean(row.get("scoring_version", ""))
            effective_from = effective_from_by_version.get(version)
            if not effective_from:
                continue
            timestamp_column = "as_of_datetime" if table == "pre_earnings_baseline" else "recorded_at"
            timestamp = _parse_datetime(_clean(row.get(timestamp_column, "")))
            if timestamp and timestamp.date() < effective_from:
                issues.append(
                    ValidationIssue(
                        table,
                        row_number,
                        "scoring_version",
                        "scoring_version %s is used before effective_from %s" % (version, effective_from.isoformat()),
                    )
                )
    return issues


def _validate_temporal_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    events = {
        row["earnings_event_id"]: _event_announcement_datetime(row)
        for row in rows_by_table.get("earnings_event", [])
    }

    for row_number, row in enumerate(rows_by_table.get("pre_earnings_baseline", []), start=2):
        event_time = events.get(row.get("earnings_event_id"))
        if not event_time:
            continue
        for column in ("as_of_datetime", "locked_at", "evidence_published_at", "source_data_max_observed_at", "recorded_at"):
            value = _parse_datetime(_clean(row.get(column, "")))
            if value and value >= event_time:
                issues.append(ValidationIssue("pre_earnings_baseline", row_number, column, "baseline timestamp is not before announcement"))
        if _clean(row.get("uses_post_event_data", "")).lower() == "true":
            issues.append(ValidationIssue("pre_earnings_baseline", row_number, "uses_post_event_data", "post-event data cannot be used in pre-event score"))

    for row_number, row in enumerate(rows_by_table.get("post_earnings_review", []), start=2):
        event_time = events.get(row.get("earnings_event_id"))
        recorded_at = _parse_datetime(_clean(row.get("recorded_at", "")))
        if event_time and recorded_at and recorded_at <= event_time:
            issues.append(ValidationIssue("post_earnings_review", row_number, "recorded_at", "review timestamp is not after announcement"))
    return issues


def _validate_evidence_constraints(specs: Dict[str, TableSpec], rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    id_sets = _build_primary_id_sets(specs, rows_by_table)
    context = _build_evidence_context(rows_by_table)
    evidence_rows = rows_by_table.get("evidence", [])

    issues.extend(_validate_evidence_metadata_constraints(evidence_rows))

    for row_number, row in enumerate(evidence_rows, start=2):
        related_type = _clean(row.get("related_entity_type", ""))
        related_id = _clean(row.get("related_entity_id", ""))
        if related_type in id_sets and related_id not in id_sets[related_type]:
            issues.append(ValidationIssue("evidence", row_number, "related_entity_id", "related entity not found"))

        used_for_score = _clean(row.get("used_for_score", "")).lower() == "true"
        if not used_for_score:
            continue

        is_pre_score = _is_pre_event_score_evidence(row)
        event_id, event_time, baseline_as_of = context.get((related_type, related_id), ("", None, None))
        if is_pre_score and not event_time:
            issues.append(ValidationIssue("evidence", row_number, "related_entity_id", "pre-event score evidence has no resolvable earnings event"))
            continue

        if not is_pre_score:
            continue

        cutoff = baseline_as_of or event_time
        cutoff_label = "baseline as_of_datetime" if baseline_as_of else "announcement timestamp"
        published_at = _parse_datetime(_clean(row.get("published_at", "")))
        observed_at = _parse_datetime(_clean(row.get("observed_at", "")))
        recorded_at = _parse_datetime(_clean(row.get("recorded_at", "")))
        evidence_as_of = _parse_datetime(_clean(row.get("as_of_datetime", "")))

        if cutoff and published_at and published_at > cutoff:
            issues.append(ValidationIssue("evidence", row_number, "published_at", "used evidence was published after %s" % cutoff_label))
        if cutoff and observed_at and observed_at > cutoff:
            issues.append(ValidationIssue("evidence", row_number, "observed_at", "used evidence was observed after %s" % cutoff_label))
        if cutoff and evidence_as_of and evidence_as_of > cutoff:
            issues.append(ValidationIssue("evidence", row_number, "as_of_datetime", "evidence as_of_datetime is after %s" % cutoff_label))
        if cutoff and recorded_at and recorded_at > cutoff:
            issues.append(ValidationIssue("evidence", row_number, "recorded_at", "pre-event scoring evidence was recorded after %s" % cutoff_label))
        if event_time and recorded_at and recorded_at >= event_time:
            issues.append(ValidationIssue("evidence", row_number, "recorded_at", "pre-event scoring evidence was recorded at or after announcement"))
        if _clean(row.get("source_type", "")) == "post_event_review":
            issues.append(ValidationIssue("evidence", row_number, "source_type", "post-event review evidence cannot be used for a pre-event score"))
        if _clean(row.get("score_component", "")).startswith("post_event"):
            issues.append(ValidationIssue("evidence", row_number, "score_component", "post-event score component cannot support a pre-event baseline"))
    return issues


def _validate_evidence_metadata_constraints(rows: List[Dict[str, str]]) -> List[ValidationIssue]:
    issues = []
    row_number_by_id = {
        _clean(row.get("evidence_id", "")): row_number
        for row_number, row in enumerate(rows, start=2)
        if _clean(row.get("evidence_id", ""))
    }
    row_by_id = {
        _clean(row.get("evidence_id", "")): row
        for row in rows
        if _clean(row.get("evidence_id", ""))
    }

    for row_number, row in enumerate(rows, start=2):
        evidence_id = _clean(row.get("evidence_id", ""))
        evidence_status = _clean(row.get("evidence_status", ""))
        supersedes_id = _clean(row.get("supersedes_evidence_id", ""))
        hash_status = _clean(row.get("content_hash_status", ""))
        content_hash = _clean(row.get("content_hash", ""))
        hash_algorithm = _clean(row.get("content_hash_algorithm", ""))
        raw_status = _clean(row.get("raw_storage_status", ""))
        raw_location = _clean(row.get("raw_location", ""))
        license_status = _clean(row.get("license_status", ""))

        metadata_fields = {
            "evidence_status": evidence_status,
            "supersedes_evidence_id": supersedes_id,
            "content_hash_status": hash_status,
            "content_hash": content_hash,
            "content_hash_algorithm": hash_algorithm,
            "raw_storage_status": raw_status,
            "raw_location": raw_location,
            "license_status": license_status,
        }
        metadata_statuses = {
            "content_hash_status": hash_status,
            "raw_storage_status": raw_status,
            "license_status": license_status,
        }
        if any(metadata_fields.values()):
            for column, value in metadata_statuses.items():
                if not value:
                    issues.append(
                        ValidationIssue("evidence", row_number, column, "evidence metadata status bundle is incomplete")
                    )

        if raw_status == "stored":
            if license_status != "permitted":
                issues.append(
                    ValidationIssue(
                        "evidence",
                        row_number,
                        "license_status",
                        "raw storage requires license_status permitted",
                    )
                )
            if not raw_location:
                issues.append(ValidationIssue("evidence", row_number, "raw_location", "stored raw evidence requires raw_location"))
        elif raw_location:
            issues.append(
                ValidationIssue("evidence", row_number, "raw_location", "raw_location is only allowed when raw_storage_status is stored")
            )

        if hash_status in {"verified", "recorded_unverified", "mismatch"}:
            if not content_hash or not hash_algorithm:
                issues.append(
                    ValidationIssue(
                        "evidence",
                        row_number,
                        "content_hash",
                        "%s content hash requires content_hash and content_hash_algorithm" % hash_status,
                    )
                )
            elif hash_algorithm == "sha256" and (
                len(content_hash) != 64 or any(character not in "0123456789abcdefABCDEF" for character in content_hash)
            ):
                issues.append(
                    ValidationIssue("evidence", row_number, "content_hash", "sha256 content_hash must be 64 hexadecimal characters")
                )
        elif hash_status in {"not_recorded", "not_applicable"} and (content_hash or hash_algorithm):
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "content_hash",
                    "content hash value must be blank when content_hash_status is %s" % hash_status,
                )
            )

        if hash_status == "mismatch":
            issues.append(
                ValidationIssue("evidence", row_number, "content_hash_status", "content hash mismatch blocks evidence validation")
            )

        if evidence_status in {"correction", "retraction_notice"} and not supersedes_id:
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "supersedes_evidence_id",
                    "evidence_status correction or retraction_notice requires supersedes_evidence_id",
                )
            )
        if evidence_status == "original" and supersedes_id:
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "supersedes_evidence_id",
                    "original evidence cannot supersede another evidence row",
                )
            )
        if supersedes_id and evidence_status not in {"correction", "retraction_notice"}:
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "evidence_status",
                    "supersedes_evidence_id requires evidence_status correction or retraction_notice",
                )
            )
        if not supersedes_id:
            continue
        if supersedes_id == evidence_id:
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "supersedes_evidence_id",
                    "supersedes_evidence_id cannot reference the same evidence_id",
                )
            )
            continue
        parent = row_by_id.get(supersedes_id)
        if parent is None:
            issues.append(
                ValidationIssue("evidence", row_number, "supersedes_evidence_id", "superseded evidence_id not found")
            )
            continue
        if row_number_by_id[supersedes_id] >= row_number:
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "supersedes_evidence_id",
                    "supersedes_evidence_id must reference an earlier evidence row",
                )
            )
        if (
            _clean(parent.get("related_entity_type", "")) != _clean(row.get("related_entity_type", ""))
            or _clean(parent.get("related_entity_id", "")) != _clean(row.get("related_entity_id", ""))
        ):
            issues.append(
                ValidationIssue(
                    "evidence",
                    row_number,
                    "supersedes_evidence_id",
                    "correction lineage must keep related entity unchanged",
                )
            )
    return issues


def _is_pre_event_score_evidence(row: Dict[str, str]) -> bool:
    related_type = _clean(row.get("related_entity_type", ""))
    score_component = _clean(row.get("score_component", ""))
    return related_type == "pre_earnings_baseline" or score_component.startswith("pre_")


def _build_evidence_context(rows_by_table: Dict[str, List[Dict[str, str]]]) -> Dict[Tuple[str, str], Tuple[str, Optional[datetime], Optional[datetime]]]:
    events = {
        row["earnings_event_id"]: _event_announcement_datetime(row)
        for row in rows_by_table.get("earnings_event", [])
    }
    baselines = {row["baseline_id"]: row for row in rows_by_table.get("pre_earnings_baseline", [])}
    reviews = {row["review_id"]: row for row in rows_by_table.get("post_earnings_review", [])}
    kpis = {row["kpi_id"]: row for row in rows_by_table.get("kpi_observation", [])}
    snapshots = {row["tso_snapshot_id"]: row for row in rows_by_table.get("tso_snapshot", [])}
    hypotheses = {row["hypothesis_id"]: row for row in rows_by_table.get("hypothesis_log", [])}

    context = {}
    for event_id, event_time in events.items():
        context[("earnings_event", event_id)] = (event_id, event_time, None)
    for baseline_id, row in baselines.items():
        event_id = _clean(row.get("earnings_event_id", ""))
        context[("pre_earnings_baseline", baseline_id)] = (
            event_id,
            events.get(event_id),
            _parse_datetime(_clean(row.get("as_of_datetime", ""))),
        )
    for review_id, row in reviews.items():
        event_id = _clean(row.get("earnings_event_id", ""))
        baseline = baselines.get(_clean(row.get("baseline_id", "")), {})
        context[("post_earnings_review", review_id)] = (
            event_id,
            events.get(event_id),
            _parse_datetime(_clean(baseline.get("as_of_datetime", ""))),
        )
    for kpi_id, row in kpis.items():
        event_id = _clean(row.get("earnings_event_id", ""))
        context[("kpi_observation", kpi_id)] = (event_id, events.get(event_id), None)
    for snapshot_id, row in snapshots.items():
        event_id = _clean(row.get("earnings_event_id", ""))
        context[("tso_snapshot", snapshot_id)] = (event_id, events.get(event_id), None)
    for hypothesis_id, row in hypotheses.items():
        event_id = _clean(row.get("earnings_event_id", ""))
        context[("hypothesis_log", hypothesis_id)] = (event_id, events.get(event_id), None)
    return context


def _validate_relationship_consistency(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    baselines = {row["baseline_id"]: row for row in rows_by_table.get("pre_earnings_baseline", [])}
    event_company = {row["earnings_event_id"]: row["company_id"] for row in rows_by_table.get("earnings_event", [])}

    for row_number, row in enumerate(rows_by_table.get("post_earnings_review", []), start=2):
        baseline = baselines.get(_clean(row.get("baseline_id", "")))
        if baseline and _clean(baseline.get("earnings_event_id", "")) != _clean(row.get("earnings_event_id", "")):
            issues.append(ValidationIssue("post_earnings_review", row_number, "baseline_id", "baseline earnings_event_id does not match review earnings_event_id"))

    for row_number, row in enumerate(rows_by_table.get("kpi_observation", []), start=2):
        expected_company = event_company.get(_clean(row.get("earnings_event_id", "")))
        if expected_company and expected_company != _clean(row.get("company_id", "")):
            issues.append(ValidationIssue("kpi_observation", row_number, "company_id", "company_id does not match earnings_event company_id"))
    return issues


def _validate_kpi_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    events = {
        row["earnings_event_id"]: _event_announcement_datetime(row)
        for row in rows_by_table.get("earnings_event", [])
    }
    for row_number, row in enumerate(rows_by_table.get("kpi_observation", []), start=2):
        value_type = _clean(row.get("value_type", ""))
        used_for_score = _clean(row.get("used_for_score", "")).lower() == "true"
        recorded_at = _parse_datetime(_clean(row.get("recorded_at", "")))
        event_time = events.get(_clean(row.get("earnings_event_id", "")))
        if used_for_score and value_type != "expected":
            issues.append(ValidationIssue("kpi_observation", row_number, "value_type", "KPI rows used for pre-event score must be expected values"))
        if used_for_score and event_time and recorded_at and recorded_at >= event_time:
            issues.append(ValidationIssue("kpi_observation", row_number, "recorded_at", "KPI pre-event score rows must be recorded before announcement"))
        if value_type == "actual" and event_time and recorded_at and recorded_at < event_time:
            issues.append(ValidationIssue("kpi_observation", row_number, "recorded_at", "actual KPI rows must be recorded at or after announcement"))
    return issues


def _validate_return_reference_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    return_columns = (
        "day0_return_pct",
        "day1_return_pct",
        "day5_return_pct",
        "day20_return_pct",
        "max_favorable_excursion_pct",
        "max_adverse_excursion_pct",
    )
    reference_columns = (
        "return_reference_price_type",
        "return_reference_price",
        "return_reference_price_datetime",
    )
    for row_number, row in enumerate(rows_by_table.get("post_earnings_review", []), start=2):
        if any(_clean(row.get(column, "")) for column in return_columns):
            missing = [column for column in reference_columns if not _clean(row.get(column, ""))]
            if missing:
                issues.append(ValidationIssue("post_earnings_review", row_number, ",".join(missing), "return reference price fields are required when return fields are present"))
    return issues


def _build_primary_id_sets(specs: Dict[str, TableSpec], rows_by_table: Dict[str, List[Dict[str, str]]]) -> Dict[str, set]:
    id_sets = {}
    for table, spec in specs.items():
        if len(spec.primary_key) != 1:
            continue
        key = spec.primary_key[0]
        id_sets[table] = {_clean(row.get(key, "")) for row in rows_by_table.get(table, [])}
    return id_sets


def _validate_trade_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    for row_number, row in enumerate(rows_by_table.get("post_earnings_review", []), start=2):
        decision = _clean(row.get("trade_decision", ""))
        price_values = [_clean(row.get(column, "")) for column in ("trade_entry", "stop_loss", "take_profit")]
        if decision == "NO_TRADE" and any(price_values):
            issues.append(ValidationIssue("post_earnings_review", row_number, "trade_decision", "NO_TRADE must leave trade price fields blank"))
        if decision in {"LONG", "SHORT"}:
            if any(value == "" for value in price_values):
                issues.append(ValidationIssue("post_earnings_review", row_number, "trade_entry,stop_loss,take_profit", "trade prices are required for trade decisions"))
                continue
            entry, stop, target = [Decimal(value) for value in price_values]
            if decision == "LONG" and not stop < entry < target:
                issues.append(ValidationIssue("post_earnings_review", row_number, "trade_entry,stop_loss,take_profit", "expected stop_loss < trade_entry < take_profit for LONG"))
            if decision == "SHORT" and not target < entry < stop:
                issues.append(ValidationIssue("post_earnings_review", row_number, "trade_entry,stop_loss,take_profit", "expected take_profit < trade_entry < stop_loss for SHORT"))
    return issues


def _validate_append_only_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    locked_hashes = {}
    for row_number, row in enumerate(rows_by_table.get("pre_earnings_baseline", []), start=2):
        if _clean(row.get("is_locked", "")).lower() != "true":
            continue
        key = (_clean(row.get("earnings_event_id", "")), _clean(row.get("baseline_version", "")))
        record_hash = _clean(row.get("baseline_record_hash", ""))
        if key in locked_hashes and locked_hashes[key] != record_hash:
            issues.append(ValidationIssue("pre_earnings_baseline", row_number, "baseline_record_hash", "locked baseline appears modified instead of appended"))
        locked_hashes[key] = record_hash
    return issues


def _validate_hypothesis_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    rows = rows_by_table.get("hypothesis_log", [])
    ids = {_clean(row.get("hypothesis_id", "")) for row in rows}
    for row_number, row in enumerate(rows, start=2):
        parent_id = _clean(row.get("parent_hypothesis_id", ""))
        if parent_id and parent_id not in ids:
            issues.append(ValidationIssue("hypothesis_log", row_number, "parent_hypothesis_id", "parent hypothesis is not preserved in log"))
        if _clean(row.get("status", "")) == "invalidated":
            if not _clean(row.get("invalidated_at", "")) or not _clean(row.get("invalidation_reason", "")):
                issues.append(ValidationIssue("hypothesis_log", row_number, "invalidation_reason", "invalidated hypotheses need timestamp and reason"))
    return issues


def _event_announcement_datetime(row: Dict[str, str]) -> datetime:
    event_date = date.fromisoformat(_clean(row["announcement_date"]))
    event_time = time.fromisoformat(_clean(row["announcement_time"]))
    return datetime.combine(event_date, event_time, tzinfo=JST)


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _clean(value: Optional[str]) -> str:
    return "" if value is None else value.strip()
