# Prospective Evidence Pilot Policy

## Status

`Proposed`. 第4号prospective eventの選定前にHuman承認と現行schema gapの解消が必要である。

## 目的

最初のprospective eventで、発表前baselineが実際にその時点で利用可能だった一次情報だけに基づくことをERS evidenceで証明する。historical reconstruction 3社のURL routingと、prospective scoring用formal evidenceを混同しない。

## 適用範囲

- 適用開始: Human承認後の最初のprospective event
- 対象外: Nintendo、Toyota、Olympicの一括backfill
- 優先順位: pre-event baseline draftの`as_of_datetime`と記録を先に固定し、formal evidence登録後にHuman reviewとlockを行う
- formal evidence未登録またはtiming gate不合格ならprospective scoringへ進まない

## Lifecycle gate

```text
baseline_draft
  -> minimum_pre_event_evidence_registered
  -> human_reviewed
  -> baseline_locked
  -> event_occurred
  -> event_evidence_registered
  -> post_event_review
```

### Gate rules

- pre-event evidence未登録でも `baseline_draft` は作成できる。
- `baseline_draft` はscore確定、calibration cohort、発表前lock済み記録として扱わない。
- `baseline_locked` へ進む前に、最低限のpre-event formal evidence登録とHuman reviewを必須とする。
- lock後のbaseline本文・score・evidence relationを上書きしない。訂正はnew version/correction recordで行う。
- event後の資料、actual KPI、price reactionをlocked pre-event baselineへ混入させない。
- official event evidence未登録のままpost-event scoring/reviewを確定しない。
- session、price reference、corporate actionが未確認なら、event evidence登録後も依存するreturnを未確定に保つ。

## Lifecycle exception handling

以下はpolicy上のconceptual lifecycle stateであり、現行schemaに実装済みのenumではない。正式なevent/evidence status名、baseline version relation、correction relationはimplementation前のschema decisionで確定する。それまでは既存enumへ無理に変換せず、scoringとcalibrationを停止してHuman判断を記録する。

### Event延期

- locked baselineを上書きせず、元のlock timestamp、hash、evidence lineageを保持する。
- 新しいevent日でもbaselineが有効かHuman reviewを再実施する。
- baselineが有効な場合も、延期判断と再review結果を元baselineとは別のaudit recordへ残す。
- KPI対象期間、新規開示、前提条件、情報鮮度等により有効性を失った場合は、既存baselineを変更せずnew versionを作成する。
- 延期後に公表された資料を旧baselineへ追記せず、新versionまたはevent evidenceとしてappend-onlyで登録する。

### Event中止

- `event_cancelled`相当のconceptual terminal stateと取消理由を記録する。implementation enumはschema decisionまで未確定とする。
- baseline、evidence、lock timestamp、hash、lineageを保持する。
- 当該eventをscoring、calibration、通常のpost-event review対象から除外する。
- 後日別eventとして再設定された場合は、新しいevent identityまたは明示的なnew versionとして扱う。

### 誤開示・撤回・訂正

- 元の開示とevidenceを削除・上書きしない。
- 撤回状態は `verified_status: retracted` または同等のconceptual statusとして記録する。`retracted`を正式enumへ追加するかはschema decisionまで未確定とする。
- 訂正版を元evidenceとのrelationが追跡できるappend-only correctionとして登録する。
- locked baselineは変更しない。
- 元開示、撤回、訂正版の関係と有効なsourceがHuman確認されるまでscoringを確定しない。

## 最小登録source

1. 発表前の最新company forecastまたは直近決算資料
2. 対象eventの公式開示
3. event時刻を示す一次metadata
4. 使用する価格基準のsource
5. hypothesisを支える主要一次資料

同一documentが複数purposeを満たす場合はduplicate evidence rowを作らず、relation/notesで役割を明示する。AI要約は一次evidenceにしない。

## Required metadata contract

| policy field | current ERS mapping | rule |
| --- | --- | --- |
| `evidence_id` | `evidence.evidence_id` | stable、重複不可 |
| `entity_type` | `related_entity_type` | current schema enumを使用 |
| `entity_id` | `related_entity_id` | existing entityへ解決可能 |
| `source_type` | `source_type` | controlled enum |
| `publisher` | `publisher` | primary publisher |
| `title` | `source_title` | source原題 |
| `url_or_identifier` | `source_url` | URLがない場合のidentifier保存方法は実装前に決定 |
| `published_at` | `published_at` | public availability time。dateだけなら時刻を推測しない |
| `observed_at` | `observed_at` | Human/systemが確認した実時刻 |
| `recorded_at` | `recorded_at` | ERSへ記録した実時刻 |
| `as_of_datetime` | `as_of_datetime` | supporting snapshot cutoff |
| `verified_status` | `verified_status` | conservative enum |
| `used_for_score` | `used_for_score` | baseline lock前に確定 |
| `score_component` | `score_component` | score不使用なら空欄 |
| `content_hash_status` | current schemaに専用列なし | implementation前のschema/sidecar decisionが必要 |
| `raw_storage_status` | current schemaに専用列なし | implementation前のschema/sidecar decisionが必要 |
| `license_status` | current schemaに専用列なし | implementation前のschema/sidecar decisionが必要 |

`source_name`、`evidence_summary`、`reliability_score`、`created_by`など現行schema required fieldも満たす。

## Current schema gap

現行 `evidence.schema.json` には `content_hash_status`、`raw_storage_status`、`license_status` の専用列がない。今回はschemaを変更しないため、次のprospective実装taskで保存場所をHuman承認する。

専用列を追加する案を第一候補とする。暫定的にfree-text `notes`へ埋め込む方法は検索・validationが弱く、正式運用のdefaultにしない。保存mappingが未承認のままprospective scoringを開始しない。

## Timing gate

### Pre-event source

```text
published_at <= observed_at <= recorded_at <= baseline.locked_at
published_at <= as_of_datetime
observed_at <= as_of_datetime
recorded_at <= baseline.locked_at
```

announcement以後のsourceはpre-event scoreへ使わない。date-only metadataを便宜的な00:00や23:59でverified timestampにしない。

### Event and post-event source

event official disclosureとactual KPIはannouncement以後に登録する。pre-event baselineを更新せず、append-only evidence/event/KPI rowとして追加する。

## Score gate

- `used_for_score=true` はHumanがsource relevanceとtimingを確認した場合だけ。
- `score_component` は既存scoring versionのcomponentへ解決可能でなければならない。
- unverified、terms未確認、date-only timestamp、AI summary単独sourceはpre-event scoreへ使用しない。
- formal evidence未登録のclaimをbaseline narrativeへ記載する場合、score非利用と明示する。
- baseline lock後にevidenceを差し替えない。correctionはnew row/versionで行う。

## Raw storage and license

- raw保存不可でもURL、publisher、title、timing、hash statusを残す。
- `license_status=unknown` は保存許可を意味しない。
- local temporary reviewとGit/Vault長期保存を分ける。
- screenshot、derived VWAP、vendor price、解約後retention、AI処理はprovider条件をHumanが確認する。
- raw fileをGitへ入れることをdefaultにしない。

## Historical three-company policy

- 3社を一括backfillしない。
- current Source IndexとURL metadataを維持する。
- legal/audit/reuse上の必要が生じたsourceだけ個別遡及登録できる。
- 遡及evidenceはactual `observed_at` / `recorded_at` を使い、historical source dateへ偽装しない。
- 遡及登録してもhistorical noteをprospective baseline/calibrationへ昇格させない。

## Pilot workflow

1. event候補と予定日をHuman承認
2. source/license/price availability確認
3. company/event entityと `baseline_draft` 作成
4. pre-event primary sourceをformal evidence登録
5. minimum evidence gate確認、Human review、baseline lock
6. 発表時刻の一次metadata取得
7. event発生後、official event disclosureとactual KPIをappend
8. event evidence gate確認
9. price reference sourceとcorporate action確認
10. post-event scoring/reviewを作成
11. evidence登録時間、欠落、重複入力、逆引き性能をPilot Logへ記録

延期、中止、誤開示、撤回、訂正が発生した場合は通常系の次stepへ進まず、`Lifecycle exception handling` のHuman reviewと停止条件を適用する。

## Minimum pilot measurements

```text
evidence_registration_minutes
evidence_rows_created
source_documents_reviewed
license_unknown_count
raw_not_stored_count
hash_not_calculated_count
timing_gate_failures
duplicate_entry_count
reverse_lookup_failures
human_review_minutes
```

取得不能値は `not_measured` とする。

## Acceptance gate

- baseline lock前にpre-event evidenceが登録済み
- source timingがcutoff以前
- official event timeの一次metadataがある、またはsession/price計算を未確定に保つ
- used score componentがevidenceへ追跡可能
- raw/license/hash statusが明示
- AI要約をprimary source扱いしていない
- ERS/Vault/TSO境界が維持されている

gate未達ならevent captureは継続できるが、prospective scoring/calibration対象へ入れない。
