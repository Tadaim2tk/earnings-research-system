"""CSV validation for the Earnings Research System foundation."""

import csv
import hashlib
import json
import re
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
    "event_status_history",
    "score_definition",
    "pre_earnings_baseline",
    "post_earnings_review",
    "tso_snapshot",
    "hypothesis_log",
    "evidence",
    "kpi_observation",
]

BASELINE_LOCK_HASH_FIELDS_V1 = (
    "baseline_id",
    "earnings_event_id",
    "baseline_version",
    "as_of_datetime",
    "locked_at",
    "analyst",
    "market_consensus_revenue",
    "market_consensus_operating_income",
    "market_consensus_eps",
    "company_guidance_revenue",
    "company_guidance_operating_income",
    "company_guidance_eps",
    "guidance_style",
    "guidance_reliability_score",
    "earnings_quality_score",
    "peer_trend_score",
    "customer_industry_score",
    "nearby_sector_score",
    "external_environment_score",
    "sentiment_balance_score",
    "meme_overheat_penalty",
    "expectation_overheat_penalty",
    "credit_supply_score",
    "short_interest_score",
    "valuation_score",
    "value_trap_penalty",
    "governance_score",
    "capital_allocation_score",
    "historical_reaction_score",
    "analyst_coverage_score",
    "liquidity_score",
    "pre_event_score",
    "pre_event_grade",
    "pre_event_decision",
    "pre_event_reason",
    "scoring_version",
    "evidence_published_at",
    "source_data_max_observed_at",
    "uses_post_event_data",
    "is_locked",
    "baseline_status",
    "supersedes_baseline_id",
    "supersession_reason",
    "lock_hash_algorithm",
    "human_review_status",
    "reviewed_by",
    "reviewed_at",
    "recorded_at",
)

PROSPECTIVE_BASELINE_FIELDS = {
    "baseline_status",
    "supersedes_baseline_id",
    "supersession_reason",
    "lock_hash_algorithm",
    "human_review_status",
    "reviewed_by",
    "reviewed_at",
}
BASELINE_VERSION_PATTERN = re.compile(r"^v([1-9][0-9]*)$", re.ASCII)


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
    fieldnames_by_table = {}
    issues = []

    for table in TABLE_ORDER:
        spec = specs[table]
        path = dataset_dir / spec.file
        if not path.exists():
            if table == "event_status_history":
                rows_by_table[table] = []
                fieldnames_by_table[table] = []
                continue
            issues.append(ValidationIssue(table, None, None, "missing expected file %s" % spec.file))
            rows_by_table[table] = []
            continue
        rows, fieldnames, table_issues = _read_and_validate_table(path, spec)
        rows_by_table[table] = rows
        fieldnames_by_table[table] = fieldnames
        issues.extend(table_issues)

    if issues:
        return ValidationReport(issues)

    issues.extend(_validate_foreign_keys(specs, rows_by_table))
    issues.extend(_validate_scoring_versions(rows_by_table))
    issues.extend(_validate_score_effective_dates(rows_by_table))
    issues.extend(_validate_temporal_constraints(rows_by_table))
    issues.extend(_validate_event_lifecycle_constraints(rows_by_table))
    issues.extend(
        _validate_baseline_lock_constraints(
            specs["pre_earnings_baseline"],
            rows_by_table,
            True,
            PROSPECTIVE_BASELINE_FIELDS.issubset(set(fieldnames_by_table["pre_earnings_baseline"])),
        )
    )
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
    rows, fieldnames, issues = _read_and_validate_table(path, spec)

    if spec.table == "post_earnings_review":
        issues.extend(_validate_trade_constraints({spec.table: rows}))
        issues.extend(_validate_return_reference_constraints({spec.table: rows}))
    if spec.table == "pre_earnings_baseline":
        issues.extend(_validate_append_only_constraints({spec.table: rows}))
        issues.extend(
            _validate_baseline_lock_constraints(
                spec,
                {spec.table: rows},
                False,
                PROSPECTIVE_BASELINE_FIELDS.issubset(set(fieldnames)),
            )
        )
    if spec.table == "hypothesis_log":
        issues.extend(_validate_hypothesis_constraints({spec.table: rows}))
    if spec.table == "evidence":
        issues.extend(_validate_evidence_metadata_constraints(rows))
    if spec.table == "event_status_history":
        issues.extend(_validate_event_lifecycle_constraints({spec.table: rows}, False))
    return ValidationReport(issues)


def _match_spec_for_file(path: Path, specs: Iterable[TableSpec]) -> TableSpec:
    stem = path.stem
    for spec in specs:
        if path.name == spec.file or stem == spec.table or stem == "%s_sample" % spec.table:
            return spec
    raise ValueError("Could not infer schema for %s" % path)


def _read_and_validate_table(
    path: Path, spec: TableSpec
) -> Tuple[List[Dict[str, str]], List[str], List[ValidationIssue]]:
    issues = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in spec.required_columns if column not in fieldnames]
        for column in missing:
            issues.append(ValidationIssue(spec.table, None, column, "missing required column"))
        if missing:
            return [], fieldnames, issues

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

    return rows, fieldnames, issues


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
            if value.endswith(("Z", "z")):
                raise ValueError("UTC Z suffix is not supported in CSV input")
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


def _current_event_status_records(
    rows_by_table: Dict[str, List[Dict[str, str]]]
) -> Dict[str, Dict[str, str]]:
    rows = rows_by_table.get("event_status_history", [])
    referenced_ids = {
        _clean(row.get("supersedes_status_record_id", ""))
        for row in rows
        if _clean(row.get("supersedes_status_record_id", ""))
    }
    tails_by_event = {}
    for row in rows:
        record_id = _clean(row.get("event_status_record_id", ""))
        if not record_id or record_id in referenced_ids:
            continue
        tails_by_event.setdefault(_clean(row.get("earnings_event_id", "")), []).append(row)
    return {
        event_id: tail_rows[0]
        for event_id, tail_rows in tails_by_event.items()
        if len(tail_rows) == 1
    }


def _effective_event_datetimes(
    rows_by_table: Dict[str, List[Dict[str, str]]]
) -> Dict[str, datetime]:
    event_times = {
        row["earnings_event_id"]: _event_announcement_datetime(row)
        for row in rows_by_table.get("earnings_event", [])
    }
    for event_id, status_row in _current_event_status_records(rows_by_table).items():
        status = _clean(status_row.get("event_status", ""))
        field = "occurred_at" if status == "occurred" else "scheduled_at"
        lifecycle_time = _parse_datetime(_clean(status_row.get(field, "")))
        if lifecycle_time:
            event_times[event_id] = lifecycle_time
    return event_times


def _validate_temporal_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    events = _effective_event_datetimes(rows_by_table)

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


def _validate_event_lifecycle_constraints(
    rows_by_table: Dict[str, List[Dict[str, str]]],
    require_dataset_relations: bool = True,
) -> List[ValidationIssue]:
    issues = []
    rows = rows_by_table.get("event_status_history", [])
    rows_by_id = {
        _clean(row.get("event_status_record_id", "")): row
        for row in rows
        if _clean(row.get("event_status_record_id", ""))
    }
    row_number_by_id = {
        _clean(row.get("event_status_record_id", "")): row_number
        for row_number, row in enumerate(rows, start=2)
        if _clean(row.get("event_status_record_id", ""))
    }
    current_tail_by_event = {}
    referenced_ids = set()
    allowed_transitions = {
        "scheduled": {"postponed", "cancelled", "occurred"},
        "postponed": {"postponed", "cancelled", "occurred"},
        "cancelled": set(),
        "occurred": set(),
    }

    for row_number, row in enumerate(rows, start=2):
        record_id = _clean(row.get("event_status_record_id", ""))
        event_id = _clean(row.get("earnings_event_id", ""))
        status = _clean(row.get("event_status", ""))
        supersedes_id = _clean(row.get("supersedes_status_record_id", ""))
        replacement_event_id = _clean(row.get("replacement_event_id", ""))
        reason = _clean(row.get("status_reason", ""))
        scheduled_at = _parse_datetime(_clean(row.get("scheduled_at", "")))
        previous_scheduled_at = _parse_datetime(_clean(row.get("previous_scheduled_at", "")))
        status_recorded_at = _parse_datetime(_clean(row.get("status_recorded_at", "")))
        occurred_at = _parse_datetime(_clean(row.get("occurred_at", "")))

        if status == "occurred":
            if not occurred_at:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "occurred_at", "occurred status requires occurred_at")
                )
            elif status_recorded_at and occurred_at > status_recorded_at:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "occurred_at", "occurred_at must not be after status_recorded_at")
                )
        elif occurred_at:
            issues.append(
                ValidationIssue("event_status_history", row_number, "occurred_at", "non-occurred status must not contain occurred_at")
            )

        if status in {"postponed", "cancelled"} and not reason:
            issues.append(
                ValidationIssue("event_status_history", row_number, "status_reason", "%s status requires status_reason" % status)
            )
        if replacement_event_id:
            if status != "cancelled":
                issues.append(
                    ValidationIssue("event_status_history", row_number, "replacement_event_id", "replacement_event_id is only allowed for cancelled status")
                )
            if replacement_event_id == event_id:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "replacement_event_id", "replacement_event_id must differ from earnings_event_id")
                )

        if not supersedes_id:
            if event_id in current_tail_by_event:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "non-initial status record must supersede the current status")
                )
            if status != "scheduled":
                issues.append(
                    ValidationIssue("event_status_history", row_number, "event_status", "initial event status must be scheduled")
                )
            if previous_scheduled_at:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "previous_scheduled_at", "initial scheduled status must not contain previous_scheduled_at")
                )
            current_tail_by_event[event_id] = record_id
            continue

        referenced_ids.add(supersedes_id)
        if supersedes_id == record_id:
            issues.append(
                ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "status record cannot supersede itself")
            )
            continue
        parent = rows_by_id.get(supersedes_id)
        if parent is None:
            issues.append(
                ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "superseded status record not found")
            )
            continue
        if row_number_by_id[supersedes_id] >= row_number:
            issues.append(
                ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "status supersession must reference an earlier row")
            )
        if _clean(parent.get("earnings_event_id", "")) != event_id:
            issues.append(
                ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "status lineage must keep earnings_event_id unchanged")
            )
        if current_tail_by_event.get(event_id) != supersedes_id:
            issues.append(
                ValidationIssue("event_status_history", row_number, "supersedes_status_record_id", "status lineage cannot branch from a non-current record")
            )

        parent_status = _clean(parent.get("event_status", ""))
        if status not in allowed_transitions.get(parent_status, set()):
            issues.append(
                ValidationIssue("event_status_history", row_number, "event_status", "invalid event status transition %s -> %s" % (parent_status, status))
            )
        parent_recorded_at = _parse_datetime(_clean(parent.get("status_recorded_at", "")))
        if parent_recorded_at and status_recorded_at and status_recorded_at <= parent_recorded_at:
            issues.append(
                ValidationIssue("event_status_history", row_number, "status_recorded_at", "status_recorded_at must increase monotonically")
            )

        parent_scheduled_at = _parse_datetime(_clean(parent.get("scheduled_at", "")))
        if status == "postponed":
            if previous_scheduled_at != parent_scheduled_at:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "previous_scheduled_at", "postponed status must preserve the previous scheduled_at")
                )
            if scheduled_at and parent_scheduled_at and scheduled_at <= parent_scheduled_at:
                issues.append(
                    ValidationIssue("event_status_history", row_number, "scheduled_at", "postponed scheduled_at must be later than the previous schedule")
                )
        elif previous_scheduled_at:
            issues.append(
                ValidationIssue("event_status_history", row_number, "previous_scheduled_at", "previous_scheduled_at is only allowed for postponed status")
            )
        if status in {"cancelled", "occurred"} and scheduled_at != parent_scheduled_at:
            issues.append(
                ValidationIssue("event_status_history", row_number, "scheduled_at", "%s status must preserve the current scheduled_at" % status)
            )
        current_tail_by_event[event_id] = record_id

    tails_by_event = {}
    for record_id, row in rows_by_id.items():
        if record_id not in referenced_ids:
            tails_by_event.setdefault(_clean(row.get("earnings_event_id", "")), []).append(record_id)
    for event_id, tail_ids in tails_by_event.items():
        if len(tail_ids) != 1:
            issues.append(
                ValidationIssue("event_status_history", None, "supersedes_status_record_id", "event %s has multiple active status tails" % event_id)
            )

    if not require_dataset_relations:
        return issues

    current = _current_event_status_records(rows_by_table)
    required_event_ids = _lifecycle_required_event_ids(rows_by_table)
    event_rows = {
        _clean(row.get("earnings_event_id", "")): row
        for row in rows_by_table.get("earnings_event", [])
    }
    for event_id in required_event_ids:
        event_row = event_rows.get(event_id)
        if event_row is None:
            continue
        if event_id not in current:
            issues.append(
                ValidationIssue("earnings_event", None, "earnings_event_id", "event %s has no unique current lifecycle status" % event_id)
            )
        initial_rows = [
            row
            for row in rows
            if _clean(row.get("earnings_event_id", "")) == event_id
            and not _clean(row.get("supersedes_status_record_id", ""))
        ]
        original_schedule = _event_announcement_datetime(event_row)
        for initial_row in initial_rows:
            initial_schedule = _parse_datetime(_clean(initial_row.get("scheduled_at", "")))
            if initial_schedule and initial_schedule != original_schedule:
                issues.append(
                    ValidationIssue("event_status_history", row_number_by_id.get(_clean(initial_row.get("event_status_record_id", ""))), "scheduled_at", "initial scheduled_at must match earnings_event announcement date and time")
                )
    for row_number, row in enumerate(rows, start=2):
        replacement_event_id = _clean(row.get("replacement_event_id", ""))
        if not replacement_event_id:
            continue
        source_event = event_rows.get(_clean(row.get("earnings_event_id", "")))
        replacement_event = event_rows.get(replacement_event_id)
        if source_event and replacement_event and _clean(source_event.get("company_id", "")) != _clean(replacement_event.get("company_id", "")):
            issues.append(
                ValidationIssue("event_status_history", row_number, "replacement_event_id", "replacement event must belong to the same company")
            )
    reviews = rows_by_table.get("post_earnings_review", [])
    baseline_by_id = {
        _clean(row.get("baseline_id", "")): row
        for row in rows_by_table.get("pre_earnings_baseline", [])
    }
    return_columns = (
        "open_gap_pct",
        "day0_return_pct",
        "day1_return_pct",
        "day5_return_pct",
        "day20_return_pct",
        "max_favorable_excursion_pct",
        "max_adverse_excursion_pct",
    )
    for row_number, review in enumerate(reviews, start=2):
        event_id = _clean(review.get("earnings_event_id", ""))
        if event_id not in required_event_ids:
            continue
        status_row = current.get(event_id)
        current_status = _clean(status_row.get("event_status", "")) if status_row else ""
        has_return = any(_clean(review.get(column, "")) for column in return_columns)
        if current_status != "occurred":
            message = "cancelled event cannot have post-event review or scoring" if current_status == "cancelled" else "post-event review requires current event status occurred"
            issues.append(ValidationIssue("post_earnings_review", row_number, "earnings_event_id", message))
            if has_return:
                issues.append(ValidationIssue("post_earnings_review", row_number, "earnings_event_id", "event return requires occurred status"))
            continue
        baseline = baseline_by_id.get(_clean(review.get("baseline_id", "")))
        if baseline and _clean(baseline.get("is_locked", "")).lower() != "true":
            issues.append(
                ValidationIssue("post_earnings_review", row_number, "baseline_id", "post-event review requires a matching locked baseline")
            )
        review_recorded_at = _parse_datetime(_clean(review.get("recorded_at", "")))
        occurrence_confirmed_at = _parse_datetime(_clean(status_row.get("status_recorded_at", "")))
        if review_recorded_at and occurrence_confirmed_at and review_recorded_at < occurrence_confirmed_at:
            issues.append(
                ValidationIssue("post_earnings_review", row_number, "recorded_at", "post-event review was recorded before occurrence confirmation")
            )
    baselines_by_event = {}
    for baseline in rows_by_table.get("pre_earnings_baseline", []):
        baselines_by_event.setdefault(_clean(baseline.get("earnings_event_id", "")), []).append(baseline)
    for event_id, status_row in current.items():
        if _clean(status_row.get("event_status", "")) != "occurred":
            continue
        parent_id = _clean(status_row.get("supersedes_status_record_id", ""))
        parent = rows_by_id.get(parent_id, {})
        if _clean(parent.get("event_status", "")) != "postponed":
            continue
        postponed_at = _parse_datetime(_clean(parent.get("status_recorded_at", "")))
        scheduled_at = _parse_datetime(_clean(status_row.get("scheduled_at", "")))
        revalidated = False
        for baseline in baselines_by_event.get(event_id, []):
            reviewed_at = _parse_datetime(_clean(baseline.get("reviewed_at", "")))
            locked_at = _parse_datetime(_clean(baseline.get("locked_at", "")))
            if (
                _clean(baseline.get("baseline_status", "")) == "locked"
                and reviewed_at
                and postponed_at
                and reviewed_at >= postponed_at
                and locked_at
                and scheduled_at
                and locked_at < scheduled_at
            ):
                revalidated = True
        if not revalidated:
            issues.append(
                ValidationIssue("event_status_history", row_number_by_id.get(_clean(status_row.get("event_status_record_id", ""))), "earnings_event_id", "occurred event after postponement requires a revalidated locked baseline")
            )
    return issues


def _lifecycle_required_event_ids(
    rows_by_table: Dict[str, List[Dict[str, str]]]
) -> set:
    required = {
        _clean(row.get("earnings_event_id", ""))
        for row in rows_by_table.get("event_status_history", [])
        if _clean(row.get("earnings_event_id", ""))
    }
    baselines = {
        _clean(row.get("baseline_id", "")): row
        for row in rows_by_table.get("pre_earnings_baseline", [])
    }
    reviews = {
        _clean(row.get("review_id", "")): row
        for row in rows_by_table.get("post_earnings_review", [])
    }
    for baseline in baselines.values():
        if _clean(baseline.get("baseline_status", "")):
            required.add(_clean(baseline.get("earnings_event_id", "")))
    prospective_evidence_fields = (
        "evidence_status",
        "content_hash_status",
        "raw_storage_status",
        "license_status",
    )
    for evidence in rows_by_table.get("evidence", []):
        if not any(_clean(evidence.get(field, "")) for field in prospective_evidence_fields):
            continue
        related_type = _clean(evidence.get("related_entity_type", ""))
        related_id = _clean(evidence.get("related_entity_id", ""))
        if related_type == "earnings_event":
            required.add(related_id)
        elif related_type == "pre_earnings_baseline" and related_id in baselines:
            required.add(_clean(baselines[related_id].get("earnings_event_id", "")))
        elif related_type == "post_earnings_review" and related_id in reviews:
            required.add(_clean(reviews[related_id].get("earnings_event_id", "")))
    for review in reviews.values():
        baseline = baselines.get(_clean(review.get("baseline_id", "")))
        if baseline and _clean(baseline.get("baseline_status", "")):
            required.add(_clean(review.get("earnings_event_id", "")))
    required.discard("")
    return required


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

        published_at = _parse_datetime(_clean(row.get("published_at", "")))
        observed_at = _parse_datetime(_clean(row.get("observed_at", "")))
        recorded_at = _parse_datetime(_clean(row.get("recorded_at", "")))
        if published_at and observed_at and published_at > observed_at:
            issues.append(ValidationIssue("evidence", row_number, "published_at", "evidence was published after it was observed"))
        if observed_at and recorded_at and observed_at > recorded_at:
            issues.append(ValidationIssue("evidence", row_number, "observed_at", "evidence was observed after it was recorded"))

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
    events = _effective_event_datetimes(rows_by_table)
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
        if baseline and _clean(baseline.get("baseline_status", "")) == "draft":
            issues.append(ValidationIssue("post_earnings_review", row_number, "baseline_id", "post-event review cannot reference a draft baseline"))

    for row_number, row in enumerate(rows_by_table.get("kpi_observation", []), start=2):
        expected_company = event_company.get(_clean(row.get("earnings_event_id", "")))
        if expected_company and expected_company != _clean(row.get("company_id", "")):
            issues.append(ValidationIssue("kpi_observation", row_number, "company_id", "company_id does not match earnings_event company_id"))
    return issues


def _validate_kpi_constraints(rows_by_table: Dict[str, List[Dict[str, str]]]) -> List[ValidationIssue]:
    issues = []
    events = _effective_event_datetimes(rows_by_table)
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


def _validate_baseline_lock_constraints(
    spec: TableSpec,
    rows_by_table: Dict[str, List[Dict[str, str]]],
    require_evidence: bool,
    prospective_headers_present: bool,
) -> List[ValidationIssue]:
    issues = []
    rows = rows_by_table.get("pre_earnings_baseline", [])
    evidence_rows = rows_by_table.get("evidence", [])
    row_by_id = {
        _clean(row.get("baseline_id", "")): row
        for row in rows
        if _clean(row.get("baseline_id", ""))
    }
    row_number_by_id = {
        _clean(row.get("baseline_id", "")): row_number
        for row_number, row in enumerate(rows, start=2)
        if _clean(row.get("baseline_id", ""))
    }
    prior_versions_by_event: Dict[str, List[int]] = {}

    for row_number, row in enumerate(rows, start=2):
        baseline_id = _clean(row.get("baseline_id", ""))
        event_id = _clean(row.get("earnings_event_id", ""))
        baseline_status = _clean(row.get("baseline_status", ""))
        supersedes_id = _clean(row.get("supersedes_baseline_id", ""))
        supersession_reason = _clean(row.get("supersession_reason", ""))
        hash_algorithm = _clean(row.get("lock_hash_algorithm", ""))
        review_status = _clean(row.get("human_review_status", ""))
        reviewed_by = _clean(row.get("reviewed_by", ""))
        reviewed_at = _parse_datetime(_clean(row.get("reviewed_at", "")))
        locked_at = _parse_datetime(_clean(row.get("locked_at", "")))
        recorded_at = _parse_datetime(_clean(row.get("recorded_at", "")))
        as_of_datetime = _parse_datetime(_clean(row.get("as_of_datetime", "")))
        record_hash = _clean(row.get("baseline_record_hash", ""))
        is_locked = _clean(row.get("is_locked", "")).lower() == "true"
        prospective_fields = (
            baseline_status,
            supersedes_id,
            supersession_reason,
            hash_algorithm,
            review_status,
            reviewed_by,
            _clean(row.get("reviewed_at", "")),
        )
        version = _parse_baseline_version(_clean(row.get("baseline_version", "")))

        if prospective_headers_present and is_locked and not any(prospective_fields):
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "baseline_status",
                    "locked row in a prospective-capable file cannot use the legacy baseline contract",
                )
            )

        if not any(prospective_fields) and not (prospective_headers_present and is_locked):
            if is_locked and (not locked_at or not record_hash):
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "locked_at,baseline_record_hash",
                        "legacy locked baseline requires locked_at and baseline_record_hash",
                    )
                )
            if version is not None:
                prior_versions_by_event.setdefault(event_id, []).append(version)
            continue

        if not baseline_status:
            issues.append(
                ValidationIssue("pre_earnings_baseline", row_number, "baseline_status", "prospective baseline metadata requires baseline_status")
            )
        if not review_status:
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "human_review_status",
                    "prospective baseline metadata requires human_review_status",
                )
            )
        if version is None:
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "baseline_version",
                    "prospective baseline_version must use v followed by an integer of at least 1",
                )
            )
        else:
            prior_versions = prior_versions_by_event.setdefault(event_id, [])
            if prior_versions and version <= max(prior_versions):
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_version",
                        "baseline_version must increase monotonically for the earnings event",
                    )
                )
            prior_versions.append(version)

        if review_status == "pending" and (reviewed_by or reviewed_at):
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "human_review_status",
                    "pending Human review must not have reviewer identity or reviewed_at",
                )
            )
        if review_status in {"approved", "rejected"} and (not reviewed_by or not reviewed_at):
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "reviewed_by,reviewed_at",
                    "completed Human review requires reviewed_by and reviewed_at",
                )
            )

        if baseline_status == "draft":
            if is_locked or locked_at or record_hash or hash_algorithm:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_status",
                        "draft baseline must not contain lock state timestamp hash or algorithm",
                    )
                )
            if supersedes_id or supersession_reason:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "supersedes_baseline_id",
                        "draft baseline must not supersede a locked baseline",
                    )
                )

        if baseline_status == "locked":
            if not is_locked:
                issues.append(
                    ValidationIssue("pre_earnings_baseline", row_number, "is_locked", "locked baseline requires is_locked=true")
                )
            if not locked_at:
                issues.append(
                    ValidationIssue("pre_earnings_baseline", row_number, "locked_at", "locked baseline requires locked_at")
                )
            if not record_hash:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline", row_number, "baseline_record_hash", "locked baseline requires baseline_record_hash"
                    )
                )
            if hash_algorithm != "sha256":
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline", row_number, "lock_hash_algorithm", "locked baseline requires sha256 lock_hash_algorithm"
                    )
                )
            if review_status != "approved":
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline", row_number, "human_review_status", "locked baseline requires approved Human review"
                    )
                )
            if recorded_at and locked_at and recorded_at > locked_at:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline", row_number, "recorded_at", "prospective baseline must be recorded no later than locked_at"
                    )
                )
            for column, value in (
                ("as_of_datetime", as_of_datetime),
                ("reviewed_at", reviewed_at),
                ("evidence_published_at", _parse_datetime(_clean(row.get("evidence_published_at", "")))),
                ("source_data_max_observed_at", _parse_datetime(_clean(row.get("source_data_max_observed_at", "")))),
            ):
                if value and locked_at and value > locked_at:
                    issues.append(
                        ValidationIssue(
                            "pre_earnings_baseline", row_number, column, "%s must be no later than locked_at" % column
                        )
                    )
            if record_hash and hash_algorithm == "sha256":
                if len(record_hash) != 64 or any(character not in "0123456789abcdefABCDEF" for character in record_hash):
                    issues.append(
                        ValidationIssue(
                            "pre_earnings_baseline",
                            row_number,
                            "baseline_record_hash",
                            "sha256 baseline_record_hash must be 64 hexadecimal characters",
                        )
                    )
                else:
                    expected_hash = _calculate_baseline_record_hash(row, spec)
                    if record_hash.lower() != expected_hash:
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "baseline_record_hash",
                                "baseline_record_hash does not match canonical locked content",
                            )
                        )

        if supersession_reason and not supersedes_id:
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "supersedes_baseline_id",
                    "supersession_reason requires supersedes_baseline_id",
                )
            )
        if supersedes_id:
            if baseline_status != "locked":
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_status",
                        "supersession is effective only from a locked baseline",
                    )
                )
            if not supersession_reason:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "supersession_reason",
                        "supersedes_baseline_id requires supersession_reason",
                    )
                )
            if supersedes_id == baseline_id:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "supersedes_baseline_id",
                        "supersedes_baseline_id cannot reference the same baseline_id",
                    )
                )
            else:
                parent = row_by_id.get(supersedes_id)
                if parent is None:
                    issues.append(
                        ValidationIssue(
                            "pre_earnings_baseline",
                            row_number,
                            "supersedes_baseline_id",
                            "superseded baseline_id not found",
                        )
                    )
                else:
                    if row_number_by_id[supersedes_id] >= row_number:
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "supersedes_baseline_id",
                                "supersedes_baseline_id must reference an earlier baseline row",
                            )
                        )
                    if _clean(parent.get("earnings_event_id", "")) != event_id:
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "supersedes_baseline_id",
                                "supersession lineage must keep earnings_event_id unchanged",
                            )
                        )
                    parent_version = _parse_baseline_version(_clean(parent.get("baseline_version", "")))
                    if version is not None and parent_version is not None and version <= parent_version:
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "baseline_version",
                                "superseding baseline_version must be greater than superseded version",
                            )
                        )
        elif baseline_status == "locked" and version is not None and version > 1:
            issues.append(
                ValidationIssue(
                    "pre_earnings_baseline",
                    row_number,
                    "supersedes_baseline_id",
                    "locked baseline version greater than 1 requires supersedes_baseline_id",
                )
            )

        if require_evidence and baseline_status == "draft":
            draft_score_evidence = [
                evidence
                for evidence in evidence_rows
                if _clean(evidence.get("related_entity_type", "")) == "pre_earnings_baseline"
                and _clean(evidence.get("related_entity_id", "")) == baseline_id
                and _clean(evidence.get("used_for_score", "")).lower() == "true"
            ]
            if draft_score_evidence:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_status",
                        "draft baseline evidence cannot be approved for score use",
                    )
                )

        if require_evidence and baseline_status == "locked":
            related_evidence = [
                evidence
                for evidence in evidence_rows
                if _clean(evidence.get("related_entity_type", "")) == "pre_earnings_baseline"
                and _clean(evidence.get("related_entity_id", "")) == baseline_id
            ]
            if not related_evidence:
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_id",
                        "locked prospective baseline requires related formal evidence",
                    )
                )
            if related_evidence and not any(
                _clean(evidence.get("used_for_score", "")).lower() == "true" for evidence in related_evidence
            ):
                issues.append(
                    ValidationIssue(
                        "pre_earnings_baseline",
                        row_number,
                        "baseline_id",
                        "locked prospective baseline requires evidence approved for score use",
                    )
                )
            for evidence in related_evidence:
                for column in ("content_hash_status", "raw_storage_status", "license_status"):
                    if not _clean(evidence.get(column, "")):
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "baseline_id",
                                "locked prospective baseline evidence requires %s" % column,
                            )
                        )
                for column in ("published_at", "observed_at", "recorded_at", "as_of_datetime"):
                    evidence_time = _parse_datetime(_clean(evidence.get(column, "")))
                    if evidence_time and locked_at and evidence_time > locked_at:
                        issues.append(
                            ValidationIssue(
                                "pre_earnings_baseline",
                                row_number,
                                "baseline_id",
                                "related evidence %s must be no later than locked_at" % column,
                            )
                        )
    return issues


def _parse_baseline_version(value: str) -> Optional[int]:
    match = BASELINE_VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    return int(match.group(1))


def _calculate_baseline_record_hash(row: Dict[str, str], spec: TableSpec) -> str:
    columns = {column.name: column for column in spec.columns}
    canonical_values = [
        [field, _canonicalize_baseline_value(columns[field], _clean(row.get(field, "")))]
        for field in BASELINE_LOCK_HASH_FIELDS_V1
    ]
    payload = json.dumps(canonical_values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonicalize_baseline_value(column: ColumnSpec, value: str) -> str:
    if not value:
        return ""
    if column.type == "datetime":
        parsed = _parse_datetime(value)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if parsed else ""
    if column.type == "decimal":
        parsed_decimal = Decimal(value)
        if parsed_decimal == 0:
            return "0"
        return format(parsed_decimal.normalize(), "f")
    if column.type == "integer":
        return str(int(value))
    if column.type == "boolean":
        return value.lower()
    return value


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
    if value.endswith(("Z", "z")):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _clean(value: Optional[str]) -> str:
    return "" if value is None else value.strip()
