# Claude Code Audit Request

Role: Maruyama AI Research Lab Scientific Reviewer / Code Auditor

Target project:

```text
/Users/maruyamayuuki/Documents/Codex/2026-07-19/record-and-replay-plugin-record-and-3/earnings-research-system
```

This is an independent Earnings Research System for recording pre-earnings expectations, announced results, price reactions, TSO snapshots, evidence/source lineage, KPI observations, and later review. Tactical Swing OS itself must remain untouched.

## Audit Goal

Do not expand implementation during this audit. Review whether the current design is reliable enough before the project proceeds to TSO_LOG column-definition work, price-data policy, SQLite DDL review, or hand-entry operations.

Audit these points:

1. Whether the schema is robust as an earnings research log.
2. Whether future information contamination is meaningfully prevented.
3. Whether pre-earnings baseline and post-earnings review data stay separate.
4. Whether evidence/source lineage is effective.
5. Whether generic KPI design is balanced, neither too broad nor over-normalized.
6. Whether `return_base_price_policy` can handle before-open, intraday, and after-close announcements.
7. Whether Tactical Swing OS source files and TSO_LOG are not modified.
8. Whether `TSO_LOG_MAPPING_DRAFT.md` keeps unresolved mappings as `unknown`.
9. Whether CSV as temporary source of truth and SQLite migration triggers are reasonable.
10. Whether validator and tests really enforce the stated constraints.

Do not make file changes unless there is a clearly broken typo or test fixture. If a tiny fix is necessary, explain it first and keep it minimal.

## First Commands

```bash
cd /Users/maruyamayuuki/Documents/Codex/2026-07-19/record-and-replay-plugin-record-and-3/earnings-research-system
pwd
find . -maxdepth 3 -type f | sort
git status --short
```

Then run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m earnings_research.cli validate data/samples
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -q -p no:cacheprovider
```

If either command fails, diagnose the cause but do not make broad fixes.

## Files To Read

- `README.md`
- `AGENTS.md`
- `docs/SYSTEM_OVERVIEW.md`
- `docs/DATA_SCHEMA.md`
- `docs/SCHEMA_REVIEW.md`
- `docs/EVIDENCE_AND_LINEAGE.md`
- `docs/RETURN_BASE_PRICE_POLICY.md`
- `docs/SQLITE_SCHEMA_DRAFT.md`
- `docs/TSO_LOG_MAPPING_DRAFT.md`
- `docs/CLAUDE_AUDIT_CHECKLIST.md`
- `docs/DECISIONS.md`
- `docs/ACCEPTANCE_TESTS.md`
- `docs/OPEN_QUESTIONS.md`
- `src/earnings_research/validation/validator.py`
- `tests/unit/test_validation.py`
- `schemas/*.schema.json`
- `data/samples/*.csv`

## Audit Focus

### TSO Boundary

- Confirm the ERS project does not modify TSO source files.
- Confirm TSO_LOG is treated as external input.
- Confirm `tso_snapshot` stores source identifiers and hashes rather than mutating the source log.
- Confirm unresolved mapping items such as `asset`, `side`, `rank`, `ffs`, `cds`, `ias`, and `origin` are not promoted to `confirmed`.
- Confirm the 28-column versus current 29-column issue is explicitly unresolved.

### Baseline Preservation

- Confirm `pre_earnings_baseline` is a pre-announcement snapshot.
- Confirm `locked_at`, `is_locked`, and `baseline_record_hash` have a clear meaning.
- Confirm locked baseline mutation is tested or at least detected in CSV form.
- Confirm corrections are append-oriented rather than overwrite-oriented.
- Confirm `scoring_version` is preserved and historical scores are not silently recalculated away.

### Future Information Contamination

Check whether the validator and tests catch:

- `evidence.published_at > baseline.as_of_datetime` when used for score.
- `evidence.observed_at > baseline.as_of_datetime` when used for score.
- post-event review evidence used for pre-event score.
- `pre_earnings_baseline.uses_post_event_data=true`.
- score versions used before `score_definition.effective_from`.
- baseline timestamps at or after the earnings announcement.

Point out any realistic leakage path that still passes validation.

### Evidence And Source Lineage

- Confirm evidence can be traced to a related entity.
- Review whether polymorphic `related_entity_type` / `related_entity_id` validation is enough for CSV phase.
- Confirm `source_type`, `verified_status`, `reliability_score`, `used_for_score`, and `score_component` semantics are clear.
- Check whether raw facts, derived metrics, AI interpretation, decisions, and outcomes can still blur.
- Review copyright/source-policy risks around `raw_excerpt`.
- Confirm SNS/message-board material is treated as attention or overheat evidence, not truth.

### Return Base Price Policy

- Confirm before-open, intraday, and after-close cases are covered.
- Check whether intraday use of `previous_close` is warned against.
- Check whether missing `pre_announcement_price` handling is conservative.
- Check whether `vwap_after_announcement` is framed as a future-data-dependent policy.
- Identify whether post-event reviews can actually trace the reference price used.
- Review whether `return_base_price_policy=unknown` should be a warning, exclusion flag, or acceptable draft state.

### KPI Design

- Confirm `kpi_observation` can represent retail, SaaS, manufacturing, construction, restaurant, cash-flow, inventory, finance, real estate, and trading-company style KPIs.
- Check whether append-only `value_type`, `value`, `unit`, and `period` are enough.
- Confirm `source_evidence_id` is validated.
- Identify risks from mixing percentages, money, counts, indexes, and textual KPIs.
- Check whether KPI timing is sufficiently explicit.
- Check whether KPI-to-score-component linkage is understandable.

### CSV vs SQLite

- Evaluate whether CSV should continue only through the next review.
- Evaluate whether migration triggers such as 50 companies, 150 events, routine joins, corrections, or score recalculation are too late.
- Review SQLite append-only, baseline lock, evidence lineage, foreign key, index, and score-version plans.
- Review whether PostgreSQL deferral is reasonable.

### Validator And Tests

- Confirm tests include meaningful bad paths, not just happy paths.
- Confirm date comparisons use parsed datetimes, not strings.
- Check timezone-naive timestamp behavior.
- Check blank, missing, and numeric range handling.
- Check whether schema JSON and validator behavior can drift.
- Check whether CLI errors are actionable for manual researchers.

## Priority Risks To Seek

1. Samples are too shallow and only exist to satisfy tests.
2. Evidence timing checks miss realistic leakage.
3. Baseline lock remains conceptual.
4. Review values can still leak into baseline scoring.
5. Return base price remains ambiguous enough to distort outcome studies.
6. KPI observations are so generic that later scoring cannot interpret them.
7. CSV source of truth will break earlier than the current SQLite triggers.
8. TSO_LOG 29-column mismatch is unresolved but already treated as usable.
9. `score_definition` exists but actual score rows cannot be traced to component weights.
10. AI interpretation is stored as if it were raw fact.

## Required Output Format

### Overall Rating

- `Pass`, `Conditional Pass`, or `Needs Fix`
- Short reason

### Execution Results

- validate result
- pytest result
- git status summary

### Major Risks

Use a table with:

```text
ID
Severity: critical / high / medium / low
File
Problem
Why It Matters
Recommended Action
```

### Design Findings

Group by:

- schema
- evidence
- return_base_price_policy
- KPI
- TSO mapping
- CSV vs SQLite
- validator/tests

### Immediate Fixes

Maximum 5, ordered by priority.

### Deferrable Items

Maximum 5.

### Instructions To Return To Codex

Provide a ready-to-paste instruction block for Codex.

### Why Claude Did Not Implement More

Explain that this pass is audit-first and avoids locking in large design changes without human approval.
