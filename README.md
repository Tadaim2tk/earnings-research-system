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

## Prospective Operations

- [Operations contract](docs/PROSPECTIVE_OPERATIONS.md)
- [AI monitoring implementation design](docs/AI_MONITORING_IMPLEMENTATION_DESIGN.md)
- [Append-only pilot log](docs/PROSPECTIVE_PILOT_LOG.md)
- [First event selection criteria](docs/FIRST_PROSPECTIVE_EVENT_SELECTION.md)
- [Earnings document analysis](docs/EARNINGS_DOCUMENT_ANALYSIS.md)
- [Earnings expectation evaluation](docs/EARNINGS_EXPECTATION_EVALUATION.md)

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

The read-only production registry at `data/config/monitor_targets.csv` contains three activated ICECO targets authorized by `system_policy:public-web-low-frequency-v1`. Each target is processed independently and stores metadata and comparison digests, not raw page bodies.

The fictional offline workflow can be exercised with `workflow_dispatch`. Operational entry points are available under `python -m earnings_research.cli monitor-*`; they never write the registry or push repository contents. CI is fixed to Python 3.11.9. State artifacts use 14-day retention and are temporary pilot persistence, not permanent machine truth. Missing retained state fails closed outside an exact Human-approved initialization.

Permanent raw storage, price retrieval, Level 3 automation, event creation, evidence creation, and baseline creation remain out of scope.

Earnings PDFs are processed in temporary storage. Only structured results with source URL, hash, page provenance, units, periods, confidence, and consistency checks are retained. The ICECO historical proof is stored at `data/research/iceco/EDA-7698-20250212.json`; no source PDF is stored in the repository.

Locked baseline rows can be compared with structured results through `evaluate-earnings`. The event quarter fixes the expected reporting period, cumulative results remain separate from mismatched periods, company forecasts remain separate from actuals, ERS calculations are labeled, and hypotheses without an unambiguous document link remain pending. The output deliberately excludes market reaction and trade decisions.

## Sample Data

`data/samples/` contains fictional companies only. The samples include a social-media overheat case, a conservative-guidance case, a value-trap case, an intraday upward-revision case, a good-earnings sell-the-news case, evidence/source lineage rows, KPI observations, a NO_TRADE decision, a controlled missing-value example, and an invalidated hypothesis that is preserved as an appended record.
