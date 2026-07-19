# SQLite Schema Draft

This is a planning draft only. No SQLite database or migration script is created in the current milestone.

## Tables

- `company_master`: primary key `company_id`.
- `earnings_event`: primary key `earnings_event_id`, foreign key `company_id`.
- `pre_earnings_baseline`: primary key `baseline_id`, foreign key `earnings_event_id`.
- `post_earnings_review`: primary key `review_id`, foreign keys `earnings_event_id`, `baseline_id`.
- `tso_snapshot`: primary key `tso_snapshot_id`, foreign key `earnings_event_id`.
- `hypothesis_log`: primary key `hypothesis_id`, foreign key `earnings_event_id`, optional self-reference `parent_hypothesis_id`.
- `score_definition`: composite primary key `scoring_version`, `score_name`, `component_name`.
- `evidence`: primary key `evidence_id`.
- `kpi_observation`: primary key `kpi_id`, foreign keys `earnings_event_id`, `company_id`, `source_evidence_id`; expected and actual KPI values are separate append-only rows.

## Foreign Key Design

CSV currently uses polymorphic evidence references. SQLite should replace this with explicit link tables if the relationship volume grows:

- `baseline_evidence(baseline_id, evidence_id, used_for_score)`
- `review_evidence(review_id, evidence_id)`
- `tso_snapshot_evidence(tso_snapshot_id, evidence_id)`
- `hypothesis_evidence(hypothesis_id, evidence_id)`

This avoids weak polymorphic foreign keys while preserving the same research model.

## Index Candidates

- `earnings_event(company_id, announcement_date, announcement_time)`
- `pre_earnings_baseline(earnings_event_id, baseline_version)`
- `post_earnings_review(earnings_event_id, baseline_id)`
- `evidence(published_at, observed_at, recorded_at)`
- `evidence(source_type, verified_status)`
- `kpi_observation(earnings_event_id, kpi_name, period)`
- `score_definition(scoring_version, effective_from, effective_to)`
- `tso_snapshot(earnings_event_id, as_of_datetime, signal_id)`

## Append-Only Protection

- Store corrections as new rows with parent references.
- Add `created_at` and `superseded_at` fields where needed.
- Use triggers to prevent updates to locked baselines.
- Prefer insert-only workflows for evidence, hypotheses, reviews, and score definitions.

## Baseline Lock

`pre_earnings_baseline.is_locked` and `locked_at` should become hard constraints. A trigger can reject updates to locked rows except for appending a correction or a new `baseline_version`.

## Evidence Lineage

Evidence should keep source timing columns and be linked through explicit join tables. Pre-event score queries should require `published_at <= baseline.as_of_datetime`, `observed_at <= baseline.as_of_datetime`, and no post-event evidence links.

## Migration Conditions

Move from CSV to SQLite when any trigger in `ERS-ADR-0005` is met: more than 50 companies, more than 150 events, routine joins, audit queries for corrections, or repeatable score recalculation.

## Fragile Migration Points

- CSV blank values versus SQL `NULL`.
- Decimal precision for money, prices, rates, and scores.
- Timezone normalization.
- Polymorphic evidence references.
- Locked baseline hashes.
- Git review workflow for DB-backed data.
