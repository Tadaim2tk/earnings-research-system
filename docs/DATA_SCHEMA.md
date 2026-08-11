# Data Schema

The initial source format is CSV with JSON metadata in `schemas/`. Empty cells are treated as missing values unless a field is required.

## company_master

Primary key: `company_id`

| column | type | nullable | meaning |
| --- | --- | --- | --- |
| company_id | string | no | Stable company identifier |
| ticker | string | no | Research ticker, fictional in samples |
| exchange | string | no | Listing venue |
| company_name | string | no | Company name |
| sector | string | no | Sector |
| industry | string | no | Industry |
| sub_industry | string | yes | Sub-industry |
| market_cap_category | enum | no | micro, small, mid, large, mega |
| fiscal_year_end | string | no | Fiscal year-end month-day |
| primary_currency | string | no | Currency code |
| listing_status | enum | no | listed, delisted, watch |
| created_at | datetime | no | Row creation timestamp |
| updated_at | datetime | no | Row update timestamp |

## earnings_event

Primary key: `earnings_event_id`. Foreign key: `company_id`.

Announcement date and time define the barrier between baseline and post-event review.

Additional event semantics:

- `event_type`: quarterly earnings, full-year earnings, guidance revision, monthly disclosure, presentation, or other disclosure.
- `announcement_session`: before open, intraday, after close, or unknown.
- `accounting_standard`: JGAAP, IFRS, USGAAP, or unknown.
- `return_base_price_policy`: price reference policy for post-event return interpretation.

## pre_earnings_baseline

Primary key: `baseline_id`. Foreign key: `earnings_event_id`. Unique key: `earnings_event_id`, `baseline_version`.

Important fields include consensus values, company guidance, factor scores, evidence timing fields, `pre_event_score`, `pre_event_grade`, `pre_event_decision`, `pre_event_reason`, `scoring_version`, `is_locked`, `baseline_record_hash`, and `recorded_at`.

Prospective rows may add `baseline_status`, `supersedes_baseline_id`, `supersession_reason`, `lock_hash_algorithm`, `human_review_status`, `reviewed_by`, and `reviewed_at`. Their full status, hash, version, Human review, and evidence gate is defined in [PROSPECTIVE_BASELINE_LOCK.md](PROSPECTIVE_BASELINE_LOCK.md).

Timing fields:

- `as_of_datetime`: timestamp the baseline claims to represent
- `locked_at`: timestamp the baseline was frozen
- `evidence_published_at`: latest publication time of pre-event evidence
- `source_data_max_observed_at`: latest observation time included in the baseline
- `recorded_at`: row recording timestamp

The validator requires pre-event timestamps to be before the earnings announcement.

For a prospective `locked` row, the validator additionally requires `is_locked=true`, Human approval, a matching canonical SHA-256 record hash, append-only version lineage, related formal evidence, at least one `used_for_score=true` evidence row, and no baseline/evidence/review timestamp after `locked_at`. A `draft` row cannot carry lock fields, supersede another baseline, provide score-approved evidence, or be referenced by a post-event review.

Legacy 42-column CSV files remain valid without the seven prospective headers. New prospective samples use the 49-column contract.

## event_status_history

Primary key: `event_status_record_id`. Foreign keys: `earnings_event_id` and optional `replacement_event_id`.

Stores append-only `scheduled`, `postponed`, `cancelled`, and `occurred` status records. `supersedes_status_record_id` forms a single non-branching chain per event; the unsuperseded tail is current. Full dataset validation requires history for events activated by lifecycle rows, prospective baseline metadata, or related prospective evidence/reviews, then gates baseline revalidation and post-event review using [PROSPECTIVE_EVENT_LIFECYCLE.md](PROSPECTIVE_EVENT_LIFECYCLE.md).

## monitor_gap_acknowledgement

Primary key: `acknowledgement_id`. Foreign key: `monitor_target_id`; optional self-reference: `supersedes_acknowledgement_id`.

Stores an append-only Human or approved system-policy acknowledgement of a past monitoring interruption. `acknowledged_gap_start`, `acknowledged_gap_end`, and `acknowledged_at` are timezone-aware; a gap cannot end after it is acknowledged. Corrections append a new row and may supersede an existing row only once. The record advances only the stale-gap reference time for the next normal observation. It does not create an observation, resolve `pending_change_run_id`, or affect evidence, baselines, event status, scoring, or trading decisions.

## post_earnings_review

Primary key: `review_id`. Foreign keys: `earnings_event_id`, `baseline_id`.

Stores actual results, surprise percentages, guidance revision, KPI result, price reactions through day 20, post-event score, trade decision, return reference price, hypothesis result, review status, scoring version, and `recorded_at`.

When any post-event return window is populated, `return_reference_price_type`, `return_reference_price`, and `return_reference_price_datetime` must be populated so later reviews can reconstruct the actual base price used.

`NO_TRADE` rows must preserve the decision row while leaving `trade_entry`, `stop_loss`, and `take_profit` empty.

## tso_snapshot

Primary key: `tso_snapshot_id`. Foreign key: `earnings_event_id`.

Stores provisional TSO context: `signal_id`, `cbs`, `ems`, `mes`, `expected_r`, `trend_score`, `regime`, `rank`, `no_trade_flag`, `no_trade_reason`, `reason_codes`, `source_file`, `source_row_hash`, and `recorded_at`.

TSO mappings are provisional until the formal TSO_LOG contract is approved.

## hypothesis_log

Primary key: `hypothesis_id`. Foreign key: `earnings_event_id`. Self-reference: `parent_hypothesis_id`.

Stores hypothesis text, evidence, confidence, status, creator, timestamps, and invalidation reason. Invalidations are append-only and must not delete the original hypothesis.

## score_definition

Composite key: `scoring_version`, `score_name`, `component_name`.

Stores score weights, bounds, missing-value policy, effective range, change reason, and creation timestamp.

## evidence

Primary key: `evidence_id`.

The relation is polymorphic through `related_entity_type` and `related_entity_id`. The CSV schema cannot express this as a static foreign key, so the Python validator checks the ID against known rows.

| column | type | nullable | meaning |
| --- | --- | --- | --- |
| evidence_id | string | no | Stable evidence identifier |
| related_entity_type | enum | no | Target entity type |
| related_entity_id | string | no | Target entity ID |
| source_name | string | no | Source or dataset name |
| source_type | enum | no | TDnet, IR, SNS, TSO log, manual note, and related categories |
| source_url | string | yes | URL or source path when allowed |
| source_title | string | no | Title or file label |
| publisher | string | yes | Source publisher |
| published_at | datetime | no | When source became public |
| observed_at | datetime | no | When source was observed |
| recorded_at | datetime | no | When row was recorded |
| as_of_datetime | datetime | no | Research snapshot this evidence supports |
| evidence_summary | string | no | Human-readable summary |
| raw_excerpt | string | yes | Allowed short excerpt or synthetic sample text |
| reliability_score | decimal | no | 0 to 100 provisional reliability |
| verified_status | enum | no | verified, partially_verified, unverified, terms_unreviewed, retracted |
| used_for_score | boolean | no | Whether evidence influenced a score |
| score_component | string | yes | Score component supported by this evidence |
| evidence_status | enum | yes | original, correction, or retraction_notice append-only row role |
| supersedes_evidence_id | string | yes | Earlier evidence row corrected or retracted by this row |
| content_hash_status | enum | yes | Hash verification/recording state; mismatch blocks validation |
| content_hash | string | yes | Recorded content hash when applicable |
| content_hash_algorithm | enum | yes | Hash algorithm; initially sha256 |
| raw_storage_status | enum | yes | stored, metadata_only, storage_prohibited, storage_pending_review, unavailable |
| raw_location | string | yes | Approved raw storage identifier; required only when stored |
| license_status | enum | yes | permitted, restricted, unknown, not_applicable, review_required |
| created_by | string | no | Agent or human entering the evidence |
| notes | string | yes | Additional restrictions or review notes |

The prospective metadata fields are backward-compatible optional columns. When any of the eight fields is populated, `content_hash_status`, `raw_storage_status`, and `license_status` must all be present. Raw storage requires `license_status=permitted`. Correction lineage is append-only and keeps the original evidence row unchanged.

## kpi_observation

Primary key: `kpi_id`. Foreign keys: `earnings_event_id`, `company_id`, and `source_evidence_id`.

`kpi_observation` is a generic append-only middle layer for industry KPIs. It avoids separate tables for every industry while preserving value type, value, unit, period, and source evidence. Expected and actual values are separate rows, never two fields on one row.

| column | type | nullable | meaning |
| --- | --- | --- | --- |
| kpi_id | string | no | Stable KPI observation ID |
| earnings_event_id | string | no | Related earnings event |
| company_id | string | no | Related company |
| kpi_name | string | no | KPI name such as ARR growth, order backlog, inventory growth |
| kpi_category | enum | no | KPI family such as retail, SaaS, manufacturing, cash_flow, inventory |
| value_type | enum | no | expected or actual |
| value | decimal | no | KPI value for this append-only observation row |
| unit | string | no | Unit, for example pct_yoy or index_0_100 |
| period | string | no | Fiscal or reporting period |
| source_evidence_id | string | no | Evidence row supporting the KPI |
| used_for_score | boolean | no | Whether the KPI informed a pre-event score; must be expected if true |
| recorded_at | datetime | no | Row recording timestamp |
| notes | string | yes | Caveats or interpretation notes |
