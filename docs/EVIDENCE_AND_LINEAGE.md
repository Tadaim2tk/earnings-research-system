# Evidence And Lineage

Evidence records explain what the research system knew, when it knew it, and whether it was allowed to influence a score.

## Goals

- Trace each pre-earnings baseline back to source material.
- Prevent information published after the baseline from influencing the pre-event score.
- Separate official disclosures, vendor data, unofficial sentiment, manual notes, and post-event reviews.
- Keep AI interpretation separate from raw facts and source metadata.
- Preserve citations and timing for later review.

## Evidence Fields

`evidence_id` is the stable primary key.

`related_entity_type` and `related_entity_id` point to the research object the evidence supports, including KPI observations. This is intentionally polymorphic in CSV. The validator checks the ID against known tables.

`published_at` is when the source became public. `observed_at` is when the system or human observed it. `recorded_at` is when the evidence row was entered. `as_of_datetime` is the research snapshot time the evidence claims to support.

`used_for_score` marks whether the evidence was allowed to influence a score. For pre-event baselines, used evidence must be published and observed no later than the baseline `as_of_datetime` and before the earnings announcement. Evidence linked to events, KPI observations, reviews, hypotheses, or TSO snapshots is also checked conservatively when it is marked as pre-event score evidence.

`verified_status` must remain conservative. SNS, message board, and unreviewed source data should not be treated as verified factual evidence.

## Current Validation

The initial validator checks:

- Required columns, types, ranges, and allowed values.
- Related entity IDs against known CSV rows.
- Evidence used for pre-event scoring was not published after baseline `as_of_datetime`.
- Evidence used for pre-event scoring was not observed after baseline `as_of_datetime`.
- Evidence used for pre-event scoring was not recorded after the baseline timestamp or at/after the earnings announcement, depending on the resolvable context.
- Post-event review evidence is not used for pre-event score components.
- Event-level and KPI-linked evidence with `score_component` beginning with `pre_` is checked against the relevant earnings announcement.

## Future Validation

SQLite or PostgreSQL should eventually replace polymorphic CSV references with explicit link tables, such as `baseline_evidence`, `review_evidence`, and `tso_snapshot_evidence`. A richer lineage model should also track source file hashes, extraction method, license status, and whether a raw excerpt is allowed to be stored.
