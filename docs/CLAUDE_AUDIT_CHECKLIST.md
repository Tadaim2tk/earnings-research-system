# Claude Code Audit Checklist

Use this checklist when handing the Earnings Research System foundation to Claude Code for architecture or code audit.

- Confirm Tactical Swing OS source files, TSO_LOG, `weights.json`, and signal generation code were not modified.
- Confirm the design is append-only and does not assume historical logs can be overwritten.
- Check whether pre-earnings information and post-earnings information can mix through any CSV, validator, or score field.
- Confirm score roots are traceable through `scoring_version`, `score_definition`, and `evidence`.
- Confirm evidence has `published_at`, `observed_at`, `recorded_at`, and `as_of_datetime`.
- Confirm evidence used for a pre-event score cannot be published or observed after the baseline timestamp.
- Review whether CSV validation catches required columns, types, unique keys, foreign keys, date constraints, score versions, NO_TRADE rules, and TSO score ranges.
- Check that tests assert real failure modes rather than disabling validation.
- Check that sample data includes realistic abnormal cases: overheat, conservative guidance, value trap, missing values, post-event evidence, and hypothesis invalidation.
- Confirm NO_TRADE rows are preserved and not dropped from samples or review logic.
- Confirm TSO snapshots preserve source identifiers and hashes rather than modifying source rows.
- Confirm schema changes are reflected in `docs/DECISIONS.md`.
- Review whether future backtests would be protected from look-ahead bias.
- Identify fields that are still too memo-like for real earnings research.
- Confirm unknown TSO mappings remain `unknown` and are not described as confirmed.
