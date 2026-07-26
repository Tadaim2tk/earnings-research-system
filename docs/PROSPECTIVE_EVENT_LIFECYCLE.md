# Prospective Event Lifecycle

## Status

`Accepted` under `ERS-ADR-0021`. This contract does not authorize prospective event selection or real evidence registration.

## Representation

ERS uses a separate append-only `event_status_history` table. The existing `earnings_event` row keeps event identity and its initially recorded announcement schedule. `announcement_status` remains a legacy descriptor and is not the authoritative current lifecycle state when status history is present.

Current status is the unique status row that is not superseded by another row for the same event. Multiple active tails are invalid.

## Identity

An event keeps the same `earnings_event_id` across postponements when company, fiscal period, event type, and disclosure purpose remain the same. Disclosure purpose is a Human identity decision based on structured event fields, not validator inference. A materially different disclosure or a separately scheduled replacement uses a new event ID. `replacement_event_id` may appear only on a cancelled status, must differ from the cancelled event ID, resolve to an existing event, and belong to the same company in dataset validation. Fiscal period and event type are not required to match because replacement means a distinct event rather than a postponement.

## Fields

| field | rule |
| --- | --- |
| `event_status_record_id` | Stable unique status record ID |
| `earnings_event_id` | Existing event identity |
| `event_status` | `scheduled`, `postponed`, `cancelled`, `occurred` |
| `scheduled_at` | Current expected occurrence time |
| `previous_scheduled_at` | Required only for postponement and equal to parent schedule |
| `status_recorded_at` | Actual time ERS recorded/recognized the state |
| `occurred_at` | Required only for `occurred` |
| `status_reason` | Required for postponement and cancellation |
| `supersedes_status_record_id` | Immediate prior current status record |
| `replacement_event_id` | Optional new event identity after cancellation |

CSV datetimes follow the offset-bearing ISO 8601 contract. `Z` input is not accepted; invalid values become validation errors.

## Transitions

Allowed:

```text
scheduled -> postponed
scheduled -> cancelled
scheduled -> occurred
postponed -> postponed
postponed -> cancelled
postponed -> occurred
```

`cancelled` and `occurred` are terminal in this contract. A mistaken terminal record cannot be rewritten or transitioned back. Terminal correction needs a later append-only correction/retraction design or a replacement event identity.

## Append-Only Lineage

- The first row for an event is `scheduled` and has no parent.
- Every later row supersedes the unique current tail.
- Self, missing, forward, and cross-event references are invalid.
- `status_recorded_at` increases strictly.
- Branches such as `A -> B` and `A -> C` are invalid.
- Each event has exactly one current tail in a complete dataset.

The initial `scheduled_at` must equal the date/time stored in `earnings_event`. Later schedule changes are represented only by appended `postponed` rows.

## Timestamp Rules

- `scheduled_at` is the expected disclosure time, not a claim about when ERS learned it.
- `status_recorded_at` records when ERS recognized the status and must not be backdated relative to its parent row.
- `occurred_at` records confirmed occurrence and must be no later than `status_recorded_at`.
- An occurrence earlier than `scheduled_at` is accepted because early disclosure is possible. It remains a Human review condition; this patch does not implement warning severity.
- Non-occurred rows cannot contain `occurred_at`.
- A postponement preserves the parent schedule in `previous_scheduled_at` and moves `scheduled_at` later.
- Cancelled and occurred rows preserve their parent's current schedule.

Publication time for the notice proving a postponement, cancellation, or occurrence belongs in formal evidence, not in the lifecycle row.

## Baseline Relation

Lifecycle validation is dataset-level and does not modify baseline rows.

### Postponed

- Existing locked baselines remain unchanged.
- Post-event review remains blocked while current status is `postponed`.
- Before a postponed event can become operationally `occurred`, baseline contract and lineage validation must succeed. The validator does not infer a current tail from invalid lineage.
- The validator derives the current baseline tail only from prospective rows with non-empty `baseline_status` that are not referenced by another prospective row's `supersedes_baseline_id` in the same loaded dataset. Legacy rows are not gate candidates.
- The event must have exactly one current tail, and that row must have `baseline_status=locked` and `is_locked=true`. Zero or multiple tails fail closed.
- Only that current locked tail is checked for Human approval, review at or after the latest postponement status, and lock before the new schedule. Superseded baselines cannot satisfy the gate. Distinct errors identify no tail, multiple tails, unlocked/draft current state, stale review, and an invalid lock boundary.
- A current draft tail does not fall back to an earlier locked version.
- This conservative pilot contract records revalidation through a new locked baseline version. Evidence published after the old lock is not added to the old baseline.

### Cancelled

- Baseline and evidence remain stored.
- Post-event review, post-event scoring, returns, and calibration use are prohibited.
- No cancellation field is written back to the baseline.

### Occurred

- `occurred_at` and occurrence confirmation time are required.
- A post-event review must be recorded after `status_recorded_at` of the current occurred row.
- Existing post-event return fields are available only inside a review that passes the occurred gate.
- This schema does not calculate returns or automatically start scoring.

## Evidence Boundary

Event source corrections continue to use `evidence_status`, `supersedes_evidence_id`, and evidence correction lineage. They do not create `corrected` or `retracted` event lifecycle states. Lifecycle history records what happened to the event; evidence lineage records what happened to a source record.

## Backward Compatibility

The existing `earnings_event` schema and CSV remain unchanged and still pass standalone validation. Complete datasets now include `event_status_history_sample.csv`. This avoids optional current-status fields and destructive updates in legacy event rows.

Standalone `validate-file` checks status schema, transition, timestamp, and lineage. Full `validate` additionally checks event foreign keys, one current status per activated event, initial schedule consistency, baseline revalidation, and post-event review/scoring gates.

Lifecycle activation is event-specific. An event requires matching status history when any of the following is true:

- it already has an `event_status_history` row;
- it has a baseline with non-empty prospective `baseline_status`;
- prospective evidence metadata targets the event, its baseline, or its review;
- a review references a baseline with non-empty prospective `baseline_status`.

Legacy baseline/review rows without prospective metadata do not activate lifecycle by themselves, so a legacy complete dataset without the new file remains valid. New prospective events must not omit both lifecycle rows and all prospective markers; event origin is not inferred from company or date.

## Deferred Boundaries

- terminal status correction/retraction
- cross-file/global lifecycle lineage
- cross-file/global baseline lineage and current-tail resolution
- immutable external status record
- automatic calibration cohort generation
- return calculation
- real prospective event selection and evidence registration
