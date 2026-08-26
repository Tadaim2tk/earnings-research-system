# Earnings Research System

Earnings Research System is an initial research foundation for recording pre-earnings expectations, announced results, market reaction, and later hypothesis review. It is designed as an independent module that can later exchange CSV, JSON, or database views with Tactical Swing OS without changing TSO itself.

## Repository

- Authoritative remote: `https://github.com/Tadaim2tk/earnings-research-system`
- Permanent local working path: `/Users/maruyamayuuki/Documents/MaruyamaAIResearchLab/earnings-research-system`
- Durable external references use `repository_remote` plus `ers_commit`. The local path is environment-dependent execution metadata, not repository identity.

## Current Scope

- Project folder structure and agent handoff rules
- CSV-oriented data schema definitions
- Fictional sample data, including complex earnings scenarios
- Validation CLI for required columns, types, keys, event semantics, temporal constraints, scoring versions, evidence lineage, KPI references, NO_TRADE handling, and basic future-information contamination checks
- Pytest coverage for the initial validation contract
- Proposed reference-based integration with the existing Obsidian Research Lab, without automatic synchronization or schema changes
- Policy-gated Level 2 monitor contracts, validator, offline core, temporary state persistence, stale-gap detection, Issue notification, and live public-IR monitoring
- Temporary earnings-document acquisition, text extraction, normalized financial and narrative analysis, consistency checks, and structured handoff to pre-event comparison
- Locked pre-event expectation comparison, company-guidance revision checks, hypothesis review, and price-independent earnings evaluation
- Source-neutral tracking of pre-event close, immediate reaction, next-business-day close, and fifth-business-day close
- Append-only validation of pre-event forecasts with separated earnings, market-reaction, reason, and learning records
- Lossless migration of 254 legacy `earnings-research-os` records, Git field history, 254 TSO point-in-time links, legacy-only aggregation, and reproducible publishing outputs

## Prospective Operations

- [Operations contract](docs/PROSPECTIVE_OPERATIONS.md)
- [AI monitoring implementation design](docs/AI_MONITORING_IMPLEMENTATION_DESIGN.md)
- [Append-only pilot log](docs/PROSPECTIVE_PILOT_LOG.md)
- [First event selection criteria](docs/FIRST_PROSPECTIVE_EVENT_SELECTION.md)
- [Earnings document analysis](docs/EARNINGS_DOCUMENT_ANALYSIS.md)
- [Earnings expectation evaluation](docs/EARNINGS_EXPECTATION_EVALUATION.md)
- [Market reaction tracking](docs/MARKET_REACTION_TRACKING.md)
- [Post-event learning review](docs/POST_EVENT_LEARNING_REVIEW.md)
- [Legacy OS integration](docs/LEGACY_OS_INTEGRATION.md)
- [Legacy OS column mapping](docs/LEGACY_OS_COLUMN_MAPPING.md)

The first live pilot monitors ICECO public IR pages under the repository's low-frequency public-web policy. Human review remains an exception gate for explicit prohibitions, ambiguous terms, authentication, payment, private data, trading, or irreversible external actions. Price sourcing, formal evidence, event rows, and baseline lock remain separate.

## Out of Scope

- Broker connection, order placement, automated trading, or live trade recommendation
- External API integration requiring credentials
- Scraping sites whose terms have not been reviewed
- Real SNS posts or real ticker recommendations
- Backtesting or optimization of score weights
- Direct changes to Tactical Swing OS files, TSO_LOG, or TSO scoring logic

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Python 3.11 or newer is the project target.

## Validation

```bash
python -m earnings_research.cli validate data/samples
python -m earnings_research.cli validate-file data/samples/pre_earnings_baseline_sample.csv
python -m earnings_research.cli show-schema pre_earnings_baseline
```

The monitoring core remains deterministic and can be exercised without network access. The live-source adapter uses HTTPX/HTTPCore with fixed DNS, request, job, and response-size limits, manual same-origin redirects, sanitized failures, resolved-IP validation, a robots check, and an authorization gate before page access. It is connected to the scheduled workflow for activated production targets.

The read-only production registry at `data/config/monitor_targets.csv` contains one activated ICECO TDnet disclosure-index target authorized by `system_policy:public-web-low-frequency-v1`, plus three retired ICECO page targets kept as an explicit end-of-lineage record. The activated target stores only the newest disclosure's ID, title, JST publication time, document URL, index item count, and comparison fingerprint, never the JSON body or older list items.

The fictional offline workflow can be exercised with `workflow_dispatch`. Operational entry points are available under `python -m earnings_research.cli monitor-*`; they never write the registry or push repository contents. CI is fixed to Python 3.11.9. State artifacts use 14-day retention and are temporary pilot persistence, not permanent machine truth. Missing retained state fails closed outside an exact Human-approved initialization.

Permanent raw storage, price retrieval, Level 3 automation, event creation, evidence creation, and baseline creation remain out of scope.

Earnings PDFs are processed in temporary storage. Only structured results with source URL, hash, page provenance, units, periods, confidence, and consistency checks are retained. The ICECO historical proof is stored at `data/research/iceco/EDA-7698-20250212.json`; no source PDF is stored in the repository.

Locked baseline rows can be compared with structured results through `evaluate-earnings`. The event quarter fixes the expected reporting period, cumulative results remain separate from mismatched periods, company forecasts remain separate from actuals, ERS calculations are labeled, and hypotheses without an unambiguous document link remain pending. The output deliberately excludes market reaction and trade decisions.

Approved, normalized price observations can be processed through `track-market-reaction`. It keeps the four requested price milestones, uses a separate pre-announcement minute reference for intraday events, verifies actual occurrence and company identity, preserves pending milestones, and blocks return calculation while corporate actions remain unresolved. It retrieves no prices and retains no raw market-data files.

`review-earnings-outcome` joins an immutable baseline and pre-event hypotheses with the earnings evaluation and market-reaction snapshot. It records forecast success, evidence-backed reasons, and next-event learning candidates without rewriting source records or changing production scoring rules.

## Legacy Research

The retired `earnings-research-os` dataset is stored under `data/historical_research/earnings_research_os/v1`. Its exact source CSV, source reports, TSO historical context inputs, normalized records, per-field Git history, and joined context view remain explicitly `legacy_observational`; they never become prospective baselines or formal evidence.

Reproducible research views are under `outputs/historical_research`: dashboard, weekly report, note draft, publishing parity, and aggregation summary. The old daily AI selection and yfinance enrichment are not part of ERS.

The migration can be reproduced from fixed commits with:

```bash
python -m earnings_research.cli migrate-legacy-os \
  --source-repo /path/to/earnings-research-os \
  --source-commit <frozen-commit> \
  --source-run-id <github-actions-run-id> \
  --tso-repo /path/to/tactical-swing-os \
  --tso-commit <point-in-time-context-commit> \
  --output-root data/historical_research/earnings_research_os/v1 \
  --reports-output outputs/historical_research \
  --migration-recorded-at <timezone-aware-datetime> \
  --as-of-date <YYYY-MM-DD>
```

After the source repository is no longer active, the committed migration remains independently verifiable:

```bash
python -m earnings_research.cli verify-legacy-migration \
  --output-root data/historical_research/earnings_research_os/v1 \
  --reports-output outputs/historical_research
```

The frozen cohort can be converted into descriptive, human-readable research knowledge without entering prospective schemas or changing scoring and trading rules:

```bash
python -m earnings_research.cli analyze-legacy-research \
  --input-root data/historical_research/earnings_research_os/v1 \
  --output-dir outputs/historical_research

python -m earnings_research.cli verify-legacy-research \
  --input-root data/historical_research/earnings_research_os/v1 \
  --output-dir outputs/historical_research
```

See [Legacy Research Knowledge](docs/LEGACY_RESEARCH_KNOWLEDGE.md) for missing-value, repeated-company, small-sample, and interpretation boundaries.

## Sample Data

`data/samples/` contains fictional companies only. The samples include a social-media overheat case, a conservative-guidance case, a value-trap case, an intraday upward-revision case, a good-earnings sell-the-news case, evidence/source lineage rows, KPI observations, a NO_TRADE decision, a controlled missing-value example, and an invalidated hypothesis that is preserved as an appended record.
