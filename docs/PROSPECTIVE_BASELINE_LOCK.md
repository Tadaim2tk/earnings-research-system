# Prospective Baseline Lock

## Status

`Accepted` under `ERS-ADR-0020`. Acceptance of this contract does not authorize selection or operation of the first prospective event.

## Purpose

Define the minimum machine-checkable contract that keeps a prospective pre-earnings baseline distinguishable as `draft` or `locked`, preserves earlier versions, and blocks post-lock evidence from entering the pre-event score.

## Scope

This patch covers baseline status, Human review, lock timestamp, canonical record hash, version order, supersession lineage, and formal evidence timing. Event lifecycle states such as cancellation remain outside this baseline schema.

It does not implement immutable external storage, event selection, raw file verification, cross-file lineage, a generator, cache lint, or TSO integration.

## Fields

Existing fields retained by the contract:

- `baseline_id`
- `earnings_event_id`
- `baseline_version`
- `as_of_datetime`
- `locked_at`
- `is_locked`
- `baseline_record_hash`
- `recorded_at`

Backward-compatible optional columns added for prospective rows:

| field | values / rule | purpose |
| --- | --- | --- |
| `baseline_status` | `draft`, `locked` | Explicit lifecycle state |
| `supersedes_baseline_id` | Earlier baseline ID for the same event | Append-only lineage |
| `supersession_reason` | Required with a supersession target | Human-readable reason |
| `lock_hash_algorithm` | `sha256` | Hash algorithm declaration |
| `human_review_status` | `pending`, `approved`, `rejected` | Human gate state |
| `reviewed_by` | Required for completed review | Reviewer identity |
| `reviewed_at` | Required for completed review | Review timestamp |

Use of any prospective metadata activates the prospective validation rules. Existing CSV files without these optional headers remain valid under the legacy contract.

## Status Model

### draft

- `is_locked=false`.
- `locked_at`, `baseline_record_hash`, and `lock_hash_algorithm` are empty.
- `supersedes_baseline_id` and `supersession_reason` are empty because supersession does not become effective from an unlocked draft.
- `human_review_status=pending` has no `reviewed_by` or `reviewed_at`.
- `approved` or `rejected` may be recorded before lock when both reviewer fields are present. Approval does not itself create a lock, and rejection cannot satisfy the locked gate.
- `reviewed_by` accepts a stable reviewer identifier; a person's legal name is not required.
- Evidence related to a draft cannot have `used_for_score=true`.
- A post-event review cannot reference a draft baseline.

### locked

- `is_locked=true`.
- `locked_at` is present.
- `lock_hash_algorithm=sha256`.
- `baseline_record_hash` is a valid 64-character hexadecimal SHA-256 digest and matches canonical locked content.
- `human_review_status=approved` with `reviewed_by` and `reviewed_at`.
- At least one related formal evidence row exists and at least one is approved with `used_for_score=true`.
- Related evidence contains the prospective metadata status bundle and every relevant timestamp is no later than `locked_at`.

No `superseded` status is added. An older locked row remains immutable; a later locked row expresses replacement through `supersedes_baseline_id`.

## Human Review Gate

`pending` must not contain reviewer identity or review time. `approved` and `rejected` require both. Only `approved` can become `locked`. Review completion alone does not select an event or authorize prospective operation.

`reviewed_at`, `as_of_datetime`, `evidence_published_at`, `source_data_max_observed_at`, and `recorded_at` must all be no later than `locked_at` for a locked prospective baseline.

## Hash Canonicalization V1

The validator calculates the hash from the explicit `BASELINE_LOCK_HASH_FIELDS_V1` field list. The list contains every current baseline field except `baseline_record_hash`, including lifecycle, review, supersession, timing, and `recorded_at` fields.

Schema field additions require an explicit hash contract review. A coverage test fails when schema fields and the V1 manifest diverge; a new field is not silently added to or omitted from the hash contract.

Canonicalization procedure:

1. Iterate fields in the fixed V1 list order; CSV header order is not used.
2. Represent the payload as a JSON array of `[field_name, normalized_value]` pairs.
3. Trim surrounding whitespace from string values.
4. Normalize booleans to lowercase `true` or `false`.
5. Normalize decimals to non-exponential decimal notation without insignificant trailing zeros.
6. Normalize datetimes to UTC ISO 8601 using the `Z` suffix.
7. Serialize as compact UTF-8 JSON with `ensure_ascii=false`.
8. Calculate SHA-256 and store lowercase hexadecimal output.

The hash field itself is excluded to avoid recursion. A mismatch is a blocking validation error. A snapshot validator cannot prove that an actor did not rewrite both content and hash together; Git history or another immutable external record is still required for independent tamper evidence.

## Versioning And Supersession

- Prospective `baseline_version` uses ASCII `v<positive integer>` matching `^v[1-9][0-9]*$`, such as `v1`, `v2`, and `v10`. Leading zeros, Unicode digits, superscript digits, uppercase `V`, and decimal notation are rejected.
- Versions increase monotonically for each `earnings_event_id` in append order.
- A locked version greater than `v1` requires `supersedes_baseline_id` and `supersession_reason`.
- The target must exist earlier in the same dataset, must not be the current row, must belong to the same event, and must have a lower version number.
- The prior baseline is never deleted or edited.
- Duplicate baseline IDs and duplicate event/version keys remain invalid.

The current validator checks lineage within one loaded CSV dataset. Global or cross-file lineage needs a later registry/graph design.

Baseline lineage validation still reports its existing self, missing, forward, cross-event, version, and duplicate errors independently. Two later baselines may structurally reference the same earlier baseline (`A -> B` and `A -> C`), but an event that reaches `occurred` after postponement fails closed because it has multiple unsuperseded current tails.

Evidence is joined only where `related_entity_type=pre_earnings_baseline` and `related_entity_id` equals the current `baseline_id`. Unrelated company, event, KPI, review, hypothesis, or other baseline evidence is not compared with that lock time. A locked prospective baseline with no matching evidence fails validation. References outside the loaded dataset are not resolved by this patch.

## Postponement

When an event is postponed, the locked baseline remains unchanged with its original lock time, hash, and evidence lineage. Human review determines whether it remains valid for the new date. If validity is lost, create a new version that supersedes the previous baseline and records the reason. Evidence published after the old lock must not be attached as pre-event score evidence for the old baseline.

For the postponement-to-`occurred` gate, baseline validation runs first. The validator does not infer a tail when the loaded baseline dataset has a contract, hash, evidence, or lineage error. Among valid prospective rows with non-empty `baseline_status`, the current baseline is the only row for that event that is not referenced by another prospective row's `supersedes_baseline_id` in the same loaded dataset. Legacy placeholder rows are excluded from gate candidates. The gate requires exactly one current tail and requires that tail itself to be locked and approved, reviewed at or after the latest postponement record, and locked before the new schedule. Superseded locked rows are excluded. Zero tails, multiple tails, or a current draft tail fail closed; the validator does not fall back to an older locked version. Cross-file current-tail resolution remains unimplemented.

## Cancellation Boundary

Cancellation is an event lifecycle concern, not a baseline status. Accepted `ERS-ADR-0021` and [PROSPECTIVE_EVENT_LIFECYCLE.md](PROSPECTIVE_EVENT_LIFECYCLE.md) define an append-only status table that excludes cancelled events from scoring, calibration, and normal post-event review while preserving baseline and evidence rows.

## Future Leakage Controls

For a locked prospective baseline:

```text
published_at <= observed_at <= recorded_at <= locked_at
as_of_datetime <= locked_at
reviewed_at <= locked_at
baseline recorded_at <= locked_at
```

The validator rejects evidence observed before publication, evidence recorded before observation, any related evidence timestamp after lock, missing prospective evidence metadata, absence of score-approved evidence, draft evidence used for scoring, and post-event review linked to a draft baseline.

## Backward Compatibility

Legacy compatibility is defined at the file/dataset header boundary. The original 42-column baseline CSV remains accepted when none of the seven prospective headers is present. Legacy locked rows still require existing `locked_at` and `baseline_record_hash`, but their historical placeholder hash is not reinterpreted through V1 canonicalization.

A 49-column prospective-capable file cannot treat an `is_locked=true` row with all prospective metadata blank as legacy. Every locked row in that file must satisfy the prospective contract. In a mixed file, an unlocked row with all prospective metadata blank remains legacy-compatible, but it is not a valid prospective locked baseline. Adding new locked rows in legacy form is prohibited.

## Datetime Input Contract

CSV datetime input uses offset-bearing ISO 8601, for example `2026-07-23T10:00:00+09:00`. Invalid dates, invalid timezone offsets, and a `Z` suffix are reported as validation errors rather than parser crashes. The CSV parser intentionally does not accept the `Z` suffix so behavior remains consistent with the supported compatibility contract.

Canonical hash output is a separate representation. Valid input datetimes are normalized internally to UTC with a `Z` suffix, for example `2026-07-23T01:00:00Z`, before hashing.
