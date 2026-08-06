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
- Approval-gated Level 2 monitor contracts, validator, network-free core, and GitHub Actions pilot infrastructure for validated temporary state artifacts, stale-gap detection, and Issue notification

## Prospective Operations

- [Operations contract](docs/PROSPECTIVE_OPERATIONS.md)
- [AI monitoring implementation design](docs/AI_MONITORING_IMPLEMENTATION_DESIGN.md)
- [Append-only pilot log](docs/PROSPECTIVE_PILOT_LOG.md)
- [First event selection criteria](docs/FIRST_PROSPECTIVE_EVENT_SELECTION.md)

The first pilot remains conditional on candidate-specific provider terms, an approved price source and acquisition method, a stable reviewer identifier, source assignments, monitoring availability, and Human event-selection approval. AI may monitor only sources whose automated access has been explicitly approved by a Human; other sources fall back to Level 1 manual initiation.

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

The monitoring core remains network-free for source observations. PR D adds a read-only Human-owned registry, operational CLI, GitHub Actions artifact transport, strict manifest verification, stale-gap detection, and Issue notification. `data/config/monitor_targets.csv` is intentionally empty, so no real company is activated and scheduled runs have no live source target.

The fictional offline workflow can be exercised with `workflow_dispatch`. Operational entry points are available under `python -m earnings_research.cli monitor-*`; they never write the registry or push repository contents. CI is fixed to Python 3.11.9. State artifacts use 14-day retention and are temporary pilot persistence, not permanent machine truth. Missing retained state fails closed outside an exact Human-approved initialization.

Live IR access, ICECO activation, permanent storage, price retrieval, Level 3 automation, event creation, evidence creation, and baseline creation remain out of scope.

## Sample Data

`data/samples/` contains fictional companies only. The samples include a social-media overheat case, a conservative-guidance case, a value-trap case, an intraday upward-revision case, a good-earnings sell-the-news case, evidence/source lineage rows, KPI observations, a NO_TRADE decision, a controlled missing-value example, and an invalidated hypothesis that is preserved as an appended record.
