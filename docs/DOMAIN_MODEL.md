# Domain Model

## Entities

`company_master` stores fictional or real-world company identity information once real data use is approved.

`earnings_event` represents one earnings announcement for one company and fiscal period.

`pre_earnings_baseline` is a draft or locked pre-announcement expectation snapshot. It stores consensus, guidance, factor scores, evidence timing, scoring version, Human review state, and the pre-event decision.

`post_earnings_review` records announced results, surprise metrics, market reaction, decision outcome, and later review windows.

`tso_snapshot` stores external Tactical Swing OS context for an earnings event. It is a snapshot reference, not a TSO-owned row.

`hypothesis_log` tracks hypotheses, corrections, invalidations, and review outcomes using append-only records.

`score_definition` records score components and weights by version. Historical scores must keep their original version.

## Relationships

- One company has many earnings events.
- One earnings event can have multiple baseline versions, but only one locked version should be active for the same version key.
- One post-earnings review references one earnings event and optionally one baseline.
- One earnings event can have zero or more TSO snapshots.
- One hypothesis can reference a parent hypothesis when it corrects, invalidates, or refines earlier thinking.
- A scoring version can have multiple component definitions.

## Lifecycle

The lifecycle is registration, pre-event research, baseline lock, announcement, result entry, market reaction capture, later review, hypothesis evaluation, and scoring-policy proposal.

## Baseline Lock

After `locked_at`, a baseline must not be modified in place. A replacement is a later locked version with `supersedes_baseline_id` and a reason; the prior row remains visible. Draft rows cannot be used for scoring or post-event review. The validator checks Human approval, canonical hash, monotonic versioning, same-event backward lineage, evidence completeness, and pre-lock timing as defined in [PROSPECTIVE_BASELINE_LOCK.md](PROSPECTIVE_BASELINE_LOCK.md).

Event cancellation is not a baseline status. It remains a separate event lifecycle concern and does not mutate or delete the preserved baseline.

## Hypothesis Management

Hypotheses are append-only. Invalidating a hypothesis means adding a record with `status=invalidated` and a parent reference or filling invalidation fields on a new exported row; the original reasoning must remain visible for later learning.
