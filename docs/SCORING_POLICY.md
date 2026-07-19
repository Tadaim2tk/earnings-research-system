# Scoring Policy

Scores are hypotheses, not facts. They summarize uncertain evidence into a reviewable research artifact and must never replace the underlying observations.

## Current Policy

- Keep raw data, derived metrics, interpretation, decisions, and outcomes separate.
- Version every scoring definition with `scoring_version`.
- Preserve the weights, missing-value policy, and change reason used at the time of scoring.
- When old cases are recalculated under a new version, retain the original score and create a new versioned result.
- Do not optimize weights from small or cherry-picked samples.
- Treat SNS as a signal of overheat, imbalance, or attention rather than as truth.
- Treat TSO values as market regime, supply-demand, and risk context.
- Do not assume the earnings score and TSO score should be simply added.
- Keep NO_TRADE rules independent from score ranking.

## Not Yet Decided

Formal weights, score thresholds, trade criteria, SNS methods, and TSO integration formulas are intentionally not defined in this milestone.
