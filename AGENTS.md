# Agent Rules

This project is a research foundation, not a trading bot. Codex, ChatGPT, Claude Code, and human reviewers must preserve the research record and keep Tactical Swing OS loosely coupled.

## Required Conduct

- Do not overwrite historical logs, locked baselines, decisions, corrections, cancellations, or reviews.
- Update `docs/DECISIONS.md` whenever a schema, storage, workflow, or integration design changes.
- Create a new `scoring_version` whenever score components, weights, missing-value policy, or calculation semantics change.
- Do not directly modify Tactical Swing OS, TSO_LOG, or TSO production scoring logic from this project.
- Review source terms before adding external data collection, scraping, API polling, or storage of third-party content.
- Read `README.md`, `docs/SYSTEM_OVERVIEW.md`, `docs/DATA_SCHEMA.md`, `docs/WORKFLOW.md`, and `docs/OPEN_QUESTIONS.md` before implementation.
- Do not merge schema changes without tests covering valid data and expected failure modes.
- Keep raw facts, derived metrics, analyst interpretation, decisions, and outcomes separate.
- Do not mark unverified information as verified.
- Do not add non-approved experimental factors to production scoring.
- Record uncertain assumptions in `docs/OPEN_QUESTIONS.md` rather than silently deciding them.
- Treat Obsidian as a knowledge layer, not as the authoritative ERS record. Do not promote Vault notes to verified evidence or score inputs without ERS evidence lineage, temporal checks, and human approval.
- Do not recursively rewrite the existing Vault, install plugins, or ingest third-party raw content without explicit human approval and a reviewed rollback plan.
- If future data could leak into a pre-event baseline, stop and add a validation rule or documented review step first.
