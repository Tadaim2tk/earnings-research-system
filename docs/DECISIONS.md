# Decisions

## ERS-ADR-0001

Date: 2026-07-19

Status: Accepted for initial foundation

Context: The first milestone should prepare folders, specifications, sample data, and validation without building external ingestion, trading logic, or a production database.

Decision: Start with CSV files plus JSON schema metadata and a Python validation CLI. Treat SQLite as a likely next-stage candidate, but do not make it the source of truth in this milestone.

Consequences: The project is easy for Codex, ChatGPT, Claude Code, spreadsheet tools, and human reviewers to inspect. Cross-file constraints must be implemented in Python rather than delegated to a database. Migration to SQLite will require an explicit decision and tests.

Alternatives Considered: SQLite as the source of truth with CSV import/export. This is attractive for append-only history and constraints, but it adds premature migration and operational choices before the research fields stabilize.

## ERS-ADR-0002

Date: 2026-07-19

Status: Accepted for initial foundation

Context: `pre_earnings_baseline` can become too wide if every evidence item is normalized early. Over-normalization would slow manual research capture.

Decision: Keep one operational baseline CSV for the initial milestone, but add explicit timing, evidence, scoring version, and lock fields. Defer deeper normalization into baseline_core, fundamentals, sentiment, supply_demand, TSO, and scores until real capture volume proves the need.

Consequences: Manual entry remains practical. The validator still blocks the most important leakage and history risks. Later decomposition must preserve baseline IDs and versions.

Alternatives Considered: Fully normalized baseline tables from day one. Rejected for now because the initial milestone needs reviewable samples and validation more than database elegance.

## ERS-ADR-0003

Date: 2026-07-19

Status: Accepted for initial foundation

Context: TSO integration fields are not formally mapped to the final TSO_LOG 28-column contract.

Decision: Store TSO values in `tso_snapshot` as external snapshots with `signal_id`, source file, source row hash, and provisional score ranges. Do not mutate or reformat TSO source rows in place.

Consequences: Earnings research can reference market regime and risk context while preserving TSO boundary discipline. Formal mapping remains an open question.

Alternatives Considered: Importing TSO_LOG into the same schema as native earnings records. Rejected because it would blur ownership before the formal mapping is approved.

## ERS-ADR-0004

Date: 2026-07-19

Status: Proposed

Context: Evidence/source lineage is required to prove that pre-earnings scores were based only on information available before the baseline and before the earnings announcement.

Decision: Add `evidence` as a first-class CSV entity in the initial schema. Keep the relation polymorphic for now through `related_entity_type` and `related_entity_id`, and enforce known references in the Python validator.

Consequences: Baselines, TSO snapshots, reviews, and hypotheses can cite source timing without waiting for a database migration. CSV cannot enforce polymorphic foreign keys by itself, so custom validation remains required.

Alternatives Considered: Add a separate evidence link table for each entity immediately. Rejected for this milestone because it would over-normalize before real manual cases expose the stable relationship patterns.

## ERS-ADR-0005

Date: 2026-07-19

Status: Proposed

Context: CSV is reviewable and agent-friendly, but the project is already cross-referencing companies, events, baselines, reviews, TSO snapshots, hypotheses, evidence, scoring versions, and correction history.

Decision: Continue CSV + JSON schema for the next review pass, but define SQLite migration triggers. Move to SQLite as source of truth when any of the following are true: more than 50 companies are tracked, more than 150 earnings events are stored, baseline/review/evidence joins become routine, corrections require audit queries, or score recalculation needs repeatable snapshots. Keep CSV/Excel/Google Sheets as import and review views after migration.

Consequences: Current artifacts remain easy to inspect in Git. The project has a clear path away from CSV before cross-file constraints become fragile.

Alternatives Considered:

- A. CSV + JSON Schema continued: best for manual review, Git diffs, and multi-agent handoff; weakest for foreign keys, history queries, score recalculation, and future leakage checks.
- B. SQLite source of truth with CSV views: best next step for append-only records, joins, referential integrity, recalculation, and look-ahead audits; moderate implementation cost; still local and portable.
- C. PostgreSQL from the start: strongest for multi-user operations and future services; too heavy before target market, volume, and ingestion policy are decided.

Comparison:

| Criterion | CSV + JSON Schema | SQLite Source | PostgreSQL |
| --- | --- | --- | --- |
| History management | medium | high | high |
| Foreign keys | low without custom validation | high | high |
| Manual review | high | medium | medium |
| Git diffs | high | low for DB file, high for exported views | low |
| Future backtests | medium | high | high |
| Excel/Sheets integration | high | high through exports | medium |
| Agent handoff | high | medium to high with docs/views | medium |
| Implementation load | low | medium | high |
| Data corruption risk | medium | low with constraints/backups | low |
| Score recalculation | medium | high | high |
| Future-information checks | medium | high | high |

## ERS-ADR-0006

Date: 2026-07-19

Status: Accepted for sample/schema validation

Context: Realistic earnings research needs to distinguish ordinary quarterly earnings, standalone guidance revisions, monthly disclosures, presentations, and the market session in which an announcement occurs.

Decision: Add `event_type`, `announcement_session`, `accounting_standard`, and `return_base_price_policy` to `earnings_event`.

Consequences: Return-window interpretation can distinguish before-open, intraday, and after-close announcements. Accounting-standard differences remain visible before score interpretation. The project still does not calculate returns automatically.

Alternatives Considered: Keep these fields in evidence only. Rejected because return measurement and future leakage checks need event-level semantics.

## ERS-ADR-0007

Date: 2026-07-19

Status: Accepted for sample/schema validation

Context: Industry KPIs matter, but creating a separate table for every industry would overfit the first samples and make manual research too heavy.

Decision: Add a generic `kpi_observation` table linked to company, earnings event, and source evidence.

Consequences: Retail, SaaS, manufacturing, construction, restaurant, cash-flow, and inventory metrics can be stored with expected value, actual value, unit, period, and evidence link. More specialized KPI tables are deferred until real capture volume proves the need.

Alternatives Considered: Store all KPI information inside `evidence.score_component`. Rejected because KPI expected values, actual values, units, and periods need structure for later comparison.

## ERS-ADR-0008

Date: 2026-07-20

Status: Accepted after Claude audit

Context: The first `kpi_observation` design stored `expected_value` and `actual_value` on one row with a single `recorded_at`. That allowed post-announcement actual KPI results to appear as if they were known before the earnings announcement.

Decision: Split KPI observations into append-only rows using `value_type=expected|actual` and one `value` column. Pre-event scoring may only use `value_type=expected`. `value_type=actual` rows must be recorded at or after the earnings announcement and must not be used for pre-event scoring.

Consequences: KPI expectations and KPI actuals now have separate timestamps and source evidence. Manual review is slightly less spreadsheet-compact, but the design better preserves append-only history and prevents look-ahead leakage.

Alternatives Considered: Keep one row with `expected_recorded_at` and `actual_recorded_at`. Rejected because actuals would still be added by updating a pre-event row, which conflicts with the append-only research log principle.

## ERS-ADR-0009

Date: 2026-07-20

Status: Accepted after Claude audit

Context: `return_base_price_policy` described the intended event-level policy but did not store the actual price used to calculate post-earnings returns.

Decision: Add `return_reference_price_type`, `return_reference_price`, and `return_reference_price_datetime` to `post_earnings_review`. Require these fields whenever return windows are populated.

Consequences: Later reviewers can reconstruct which price anchored day0/day1/day5/day20 returns. Price-data source selection and intraday availability remain open questions.

Alternatives Considered: Store only policy-level information on `earnings_event`. Rejected because policy alone is insufficient for reproducible return calculations.

## ERS-ADR-0010

Date: 2026-07-20

Status: 暫定文書方針として承認

Context: 現行TSO ledgerは29列だが、従来ERS文書はformal 28-column contractを前提としていた。複数のTSO fieldはERSのtype・controlled vocabularyとも衝突する。また、実在caseのhand-entry test前に、決算後return検証の最低price-data granularityを定める必要がある。

Decision: `TSO_LOG_COLUMN_DEFINITION.md` で観測済み29列を定義し、不確定mappingは `unknown` のまま保持する。現フェーズではtrading/execution fieldを取り込まない。一般の最低price datasetはadjusted daily OHLCとし、確定的なintraday-event returnにはminute barsまたは監査可能なmanual referenceを要求する。vendor integration、return自動計算、tick storage、backtestingは延期する。

Consequences: TSOを変更せず、不一致fieldを確定済みに見せずに、ERSでTSO contextとprice referenceをreviewできる。監査可能なpre-announcement priceがないintraday caseはprovisionalとし、依存するreturn fieldsを空欄にする。categorical rank、raw regime、non-company asset、ingestion originのschema変更は、後続の承認taskで扱う。

Alternatives Considered: TSO値を現行ERS schemaへ強制変換し、全sessionでdaily closeを使う案。source semanticsを失い、intraday announcementにlook-ahead riskを持ち込むため採用しない。
