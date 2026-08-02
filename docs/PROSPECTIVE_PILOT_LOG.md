# Prospective Pilot Log

## Purpose

第1号prospective pilotの運用判断、停止、validation、Git参照をappend-onlyで記録する。本書はmachine-data truthを置き換えず、event未選定の段階で実event、company、evidence IDを作成しない。

運用契約は [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) を参照する。

## Append-Only Rule

- entryを削除または上書きしない。
- 各entryへ安定した一意の `entry_id` を付ける。
- 訂正は新しいentryとしてappendし、`corrects_entry_id` で元entryを参照する。
- 訂正前entryを編集または削除せず、Humanがcorrection chainを確認して現在有効な判断を追跡する。
- 未確認値を推測入力しない。
- `event_id` 未選定時は `not_selected` とする。
- machine-dataはERS CSV、schema、Gitを正本とし、本logだけでstatus、score、lockを変更しない。
- Humanがまだ承認していないdecisionは必ず `pending` とし、AIの推奨を確定判断として記録しない。
- `no_change` はmonitoring結果でありformal evidenceではない。取得失敗を `no_change` として記録しない。
- `stopped_at` と `resumed_at` は実際の認知・実行時刻とし、backdateしない。

## Entry Template

```text
## <timestamp> - <phase>

timestamp: <offset-bearing ISO 8601>
entry_id: <stable unique ID>
corrects_entry_id: <entry ID | none>
event_id: <ID | not_selected>
phase: <phase>
actor_role: <role>
action: <observed action>
decision: <Human decision | pending>
monitor_target_id: <target ID | not_applicable>
monitor_result: <no_change/change_detected/error/not_run>
metadata_fingerprint: <fingerprint | not_applicable>
error_code: <code | none>
evidence_reference: <evidence ID/source reference | not_applicable>
validation_result: <success/failure/not_run>
git_commit: <commit hash | pending | not_applicable>
exception_or_stop_reason: <reason | none>
next_gate: <next Human-approved gate>
stop_reason: <reason | none>
affected_event_or_phase: <event or phase | not_applicable>
decision_maker: <Human identifier | pending | not_applicable>
stopped_at: <offset-bearing ISO 8601 | not_applicable>
resume_requirements: <requirements | not_applicable>
resume_approved_by: <Human identifier | pending | not_applicable>
resumed_at: <offset-bearing ISO 8601 | not_applicable>
```

## 2026-07-27T12:35:19+09:00 - preflight_documentation

timestamp: 2026-07-27T12:35:19+09:00
entry_id: OPLOG-20260727-001
corrects_entry_id: none
event_id: not_selected
phase: preflight_documentation
actor_role: AI drafting support
action: prospective運用開始checklistとappend-only log templateを文書化
decision: Conditionally ready。prospective event未選定
evidence_reference: not_applicable
validation_result: pending
git_commit: pending
exception_or_stop_reason: provider方針はmetadata-only。J-Quantsは第1号scope外。候補固有termsと価格sourceは未確認
next_gate: 運用文書のHuman review後、第1号candidate選定とterms個別確認
stop_reason: none
affected_event_or_phase: not_applicable
decision_maker: pending
stopped_at: not_applicable
resume_requirements: not_applicable
resume_approved_by: not_applicable
resumed_at: not_applicable

## 2026-07-27T12:40:54+09:00 - preflight_validation

timestamp: 2026-07-27T12:40:54+09:00
entry_id: OPLOG-20260727-002
corrects_entry_id: none
event_id: not_selected
phase: preflight_validation
actor_role: AI validation support
action: sample validation、pytest、schema parse、ADR status、relative Markdown link、documentation-only境界を確認
decision: 運用文書patchはHuman review可能。prospective eventは未選定
evidence_reference: not_applicable
validation_result: success。sample validation成功、pytest 180件成功
git_commit: pending
exception_or_stop_reason: candidate固有terms、manual price source、reviewer identifier、source assignment、監視日程が未確定
next_gate: patch previewのHuman承認
stop_reason: none
affected_event_or_phase: not_applicable
decision_maker: pending
stopped_at: not_applicable
resume_requirements: not_applicable
resume_approved_by: not_applicable
resumed_at: not_applicable
