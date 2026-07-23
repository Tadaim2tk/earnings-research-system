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

## Sample Data

`data/samples/` contains fictional companies only. The samples include a social-media overheat case, a conservative-guidance case, a value-trap case, an intraday upward-revision case, a good-earnings sell-the-news case, evidence/source lineage rows, KPI observations, a NO_TRADE decision, a controlled missing-value example, and an invalidated hypothesis that is preserved as an appended record.
