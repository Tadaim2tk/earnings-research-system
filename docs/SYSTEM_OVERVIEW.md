# System Overview

## Purpose

Earnings Research System records the cycle from pre-earnings market expectations to announced results, price reaction, later review, and scoring-policy improvement. Its purpose is research memory and governance, not direct trading execution.

## Boundary

The system stores research records, validation rules, sample data, and future integration contracts. It does not connect to brokers, place orders, scrape unreviewed sites, or modify Tactical Swing OS.

## Roles

- Human reviewer: approves source policy, scoring changes, market scope, and any transition toward production data.
- ChatGPT: helps with interpretation, research drafting, hypothesis review, and design discussion.
- Codex: implements schemas, validation, tests, CLI, and reproducible project artifacts.
- Claude Code: can audit code, schema decisions, and architecture at milestone boundaries.

## Inputs

- Company master data
- Earnings calendar events
- Pre-earnings expectations and evidence
- Announced results and guidance
- Post-event returns and review outcomes
- Provisional TSO snapshots from external files
- Score definitions by version
- Immutable legacy observational snapshots with explicit source repository, commit, row hash, and migration version

## Outputs

- Validated CSV research records
- Schema documentation
- Validation reports
- Reproducible legacy dashboards and future exports for notebooks or SQLite views
- Legacy-only aggregation and reproducible dashboard, weekly report, and publication draft views
- Reproducible legacy research knowledge with horizon-specific coverage, small-sample boundaries, exception patterns, and publishing digests

## Legacy Research Layer

Historical records migrated from `earnings-research-os` remain a separate `legacy_observational` cohort. Their raw values and Git provenance are retained, while normalization and derived aggregates are stored separately. They are useful for hypothesis exploration and point-in-time coverage studies, but they are not prospective baselines, formal evidence, or validated market-reaction records.

The exact 254-row source snapshot, its 53-commit field history, 254 TSO point-in-time links, normalized legacy view, and reproducible reports are stored in ERS. The old daily AI selection, yfinance enrichment, GitHub Actions workflow, and automatic Issue publishing are not copied. See [LEGACY_OS_INTEGRATION.md](LEGACY_OS_INTEGRATION.md).

The research knowledge layer measures rank, narrative, judge, reaction, market context, combinations, and D1-to-D20 transitions without mixing missing horizons or treating repeated companies as independent. It emits learning candidates only; it does not change scoring, ranks, trading rules, or TSO. See [LEGACY_RESEARCH_KNOWLEDGE.md](LEGACY_RESEARCH_KNOWLEDGE.md).

The prospective hypothesis registry freezes those learning candidates before new trials, separates pre-event inputs from post-event reaction paths, appends one immutable trial bundle per completed event, and derives current status from the full trial history. It never promotes a supported hypothesis into scoring, rank, or trading rules automatically. See [PROSPECTIVE_HYPOTHESIS_REGISTRY.md](PROSPECTIVE_HYPOTHESIS_REGISTRY.md).

## Obsidian Knowledge Layer

ERS Git repository remains authoritative for schemas, validated records, baseline locks, evidence lineage, scoring versions, and ADRs. The existing Obsidian Research Lab may hold company patterns, industry knowledge, hypotheses, failure modes, and reviewed lessons.

Obsidian content is not a verified ERS fact by itself. Formal adoption requires an ERS evidence reference, temporal checks, and human approval. Initial integration is reference-based rather than automatic synchronization. See `OBSIDIAN_INTEGRATION_ARCHITECTURE.md`.

## Future Vision

The system should eventually support controlled ingestion, SQLite or PostgreSQL storage, richer evidence lineage, repeatable post-event review, and governed score calibration. Any trading-facing use remains a separate, explicitly approved phase.
