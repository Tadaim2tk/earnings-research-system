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

## Outputs

- Validated CSV research records
- Schema documentation
- Validation reports
- Future exports for TSO, notebooks, dashboards, or SQLite views

## Future Vision

The system should eventually support controlled ingestion, SQLite or PostgreSQL storage, richer evidence lineage, repeatable post-event review, and governed score calibration. Any trading-facing use remains a separate, explicitly approved phase.
