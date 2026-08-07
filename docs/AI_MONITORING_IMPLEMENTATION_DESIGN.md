# AI Monitoring Implementation Design

## Status And Scope

本書は [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) で定義したapproval-gated Level 2 monitoringを、schema、validator、single-company monitorへ段階実装するための詳細設計である。

```text
PROSPECTIVE_OPERATIONS.md
  = Human gate、source利用条件、運用責任の正本

AI_MONITORING_IMPLEMENTATION_DESIGN.md
  = machine state、状態遷移、永続化、実行・通知契約の設計
```

[ERS-ADR-0022](DECISIONS.md#ers-adr-0022) は `Accepted` である。PR Bで4つのmonitor schemaとvalidator、PR Cでnetwork-freeなoffline runtime、PR DでGitHub Actions、temporary artifact persistence、stale gap、Issue通知を実装した。PR E1はapproval-gated live source adapterをlibrary boundaryとして追加するが、scheduled workflowへ接続しない。production registryはheader-onlyで、自動実行対象は存在しない。ICECO activation、price adapter、実eventは未実装・未承認のままとする。

## Design Invariants

1. `monitor_target` はHuman-owned configurationであり、workflowはread-onlyで扱う。
2. `monitor_checkpoint` はtargetごとの現在状態、`monitor_run` は1回ごとのappend-only監査記録、`monitor_resolution` はHuman判断のappend-only記録である。
3. `error != no_change`、`change_detected != formal evidence`、`initialized != no_change` とする。
4. 前回の有効stateを取得できない場合は再初期化せず、`state_unavailable` で停止する。
5. runとcheckpointの片方だけをcommit済みstateとして公開しない。
6. GitHub Actions artifactは短期pilot用のtemporary persistenceであり、長期machine truthの唯一の正本にしない。
7. source observationとnotification deliveryを分離し、通知失敗で観測結果を消さない。
8. monitoring結果をformal evidence、event status、baseline approval、price referenceへ自動昇格しない。
9. unresolved `change_detected` はHuman resolutionまで `pending_human_review` を維持し、後続 `no_change` だけで解消しない。

## Data Responsibilities

4つの責務は統合しない。所有者、更新頻度、immutability、保存先が異なるため、分離した方がHuman approval bypassと履歴上書きを検出しやすい。

### monitor_target

Humanが承認する監視設定である。第1号pilotのregistry候補はGit管理された `data/config/monitor_targets.csv` とし、pull requestとHuman reviewを経て更新する。

| field | type candidate | meaning |
| --- | --- | --- |
| `monitor_target_id` | string | targetのstable unique ID |
| `company_id` | string | `company_master` reference。未登録例ではactivationしない |
| `earnings_event_id` | string or null | event固有targetの場合のevent reference |
| `source_name` | string | Human-readable source name |
| `source_url` | URI | Human承認対象のsource URL |
| `source_category` | enum | calendar、news index、disclosure index等 |
| `monitoring_level` | enum | `level_1` または `level_2`。Level 3はscope外 |
| `automated_access_permitted` | boolean | source固有termsに基づくHuman承認 |
| `enabled` | boolean | workflow対象に含めるHuman decision |
| `schedule_profile` | enum | domain schedule profile identifier |
| `timezone` | IANA timezone | scheduleとsource timestampの解釈基準 |
| `active_from` | datetime or null | monitoring開始境界 |
| `active_until` | datetime or null | monitoring終了境界 |
| `terms_review_state` | enum | operations contractのTerms Review Recordと一致 |
| `last_terms_review_at` | datetime or null | 最終Human確認時刻 |
| `terms_review_reference` | string | 規約URL、契約identifier、provider回答reference |
| `automation_approved_by` | string or null | stable Human identifier |
| `activation_state` | enum | Human-owned activation lifecycle |
| `activated_at` | datetime or null | Human activation timestamp |
| `activation_approved_by` | string or null | stable Human identifier |
| `initialization_generation` | integer | activation generation。未activationは0 |
| `initialization_run_id` | string or null | Human-reviewed first initialized run marker |

次はHuman-only fieldである。

```text
source_url
monitoring_level
automated_access_permitted
enabled
schedule_profile
active_from
active_until
terms_review_state
last_terms_review_at
terms_review_reference
automation_approved_by
activation_state
activated_at
activation_approved_by
initialization_generation
initialization_run_id
```

workflow tokenはregistryへのwrite権限を持たず、これらを変更できない。特に `automated_access_permitted=true`、`enabled=true`、`automation_approved_by` の設定をAIが行ってはならない。設定が不完全、不整合、期限外、terms未承認ならrunは `skipped` または `error` とし、sourceへaccessしない。

schemaはfield typeとenum、validatorはapproval組合せと `human:<stable-id>` identifierを検査する。実際のactor authorizationは将来runtimeでregistryをread-onlyにするpermission boundaryが担う。schemaまたは文字列prefixだけでidentityを証明したとは扱わない。

### monitor_checkpoint

targetごとの最後にcommitされたmachine stateである。過去runの代替ではなく、次runが比較を開始する唯一のcurrent stateとする。

| field | type candidate | meaning |
| --- | --- | --- |
| `monitor_target_id` | string | registry reference |
| `checkpoint_version` | integer | target単位で1から単調増加 |
| `target_state` | enum | targetの現在状態 |
| `last_checked_at` | datetime or null | 最後にsource確認を試みた時刻 |
| `last_success_at` | datetime or null | source observationが成功した最後の時刻 |
| `last_successful_run_id` | string or null | 最後にcommitされたsuccessful observation run |
| `last_seen_document_id` | string or null | 最後に観測したsource-side identifier |
| `last_seen_title` | string or null | 監査可能なtitle metadata |
| `last_seen_published_at` | datetime or null | timezone付きsource publication time |
| `metadata_fingerprint` | lowercase SHA-256 or null | canonical metadata fingerprint |
| `fingerprint_version` | enum or null | canonicalization version |
| `observed_etag` | string or null | terms上取得可能な補助metadata |
| `observed_last_modified` | string or null | terms上取得可能な補助metadata |
| `observed_content_length` | integer or null | terms上取得可能な補助metadata |
| `replacement_detection` | enum | `available`、`partial`、`unavailable` |
| `last_error_code` | enum or null | 最後のmachine-readable error |
| `consecutive_error_count` | integer | 連続error回数 |
| `pending_change_run_id` | string or null | 未解決 `change_detected` run |
| `resolution_applied_id` | string or null | current stateへ適用したeffective Human resolution |
| `recorded_by` | string | workflow identityとversion |

`last_checked_at` はerror runでも更新候補だが、commit済みbundle内でのみ進める。`last_success_at` と `last_successful_run_id` はsource observationが成功し、run/checkpoint bundleがcommitされた場合だけ進める。notificationだけが失敗した場合もsource observationの成功は保持する。

### monitor_run

1回の監視処理に対するappend-only監査記録である。過去runを更新または削除しない。

| field | type candidate | meaning |
| --- | --- | --- |
| `monitor_run_id` | string | globally unique run ID |
| `monitor_target_id` | string | registry reference |
| `started_at` | datetime | run開始時刻 |
| `finished_at` | datetime | run終了時刻 |
| `run_result` | enum | observationの結果 |
| `observation_status` | enum | observation execution result |
| `error_code` | enum or null | machine-readable observation/persistence error |
| `error_detail` | string or null | raw本文やsecretを含めない短い診断 |
| `retry_count` | integer | 同一run内のbounded retry回数 |
| `checkpoint_version_before` | integer or null | initialization時だけnull候補 |
| `checkpoint_version_after` | integer or null | commit不可ならnull |
| `initialization_generation` | integer or null | initialized runのHuman-approved generation |
| `fingerprint_before` | string or null | 初回だけnull |
| `fingerprint_after` | string or null | observation失敗時はnull候補 |
| `fingerprint_version` | enum or null | canonicalization version |
| `detected_change_summary` | string or null | metadata差分の短い説明 |
| `persistence_status` | enum | `committed`、`failed`、`not_attempted` |
| `notification_required` | boolean | notification policyの判定 |
| `notification_status` | enum | `not_required`、`pending`、`delivered`、`failed` |
| `notification_error_code` | enum or null | observation resultを消さないdelivery error |
| `notification_reference` | string or null | Issue URL等 |
| `previous_run_id` | string or null | append-only target run lineage |
| `recorded_by` | string | workflow identityとversion |

`error_detail` は自由記述、`error_code` はmachine判定に使う。HTTP response body、PDF本文、credential、provider raw dataをerrorへ含めない。

### monitor_resolution

未解決changeに対するHuman判断のappend-only recordである。monitor executionではないため `monitor_run` へ混在させない。

| field | meaning |
| --- | --- |
| `resolution_id` | stable resolution ID |
| `monitor_target_id` | target reference |
| `source_monitor_run_id` | 解決対象の `change_detected` run |
| `resolution_type` | Human判断の分類 |
| `resolution` | Human-readable decision |
| `resolved_at` | source run完了以後のtimezone-aware timestamp |
| `resolved_by` | `human:<stable-id>` identifier |
| `supersedes_resolution_id` | append-only correction parent |
| `notes` | optional note |

訂正は元recordを上書きせず、同じtargetとsource runを維持した新recordでcurrent resolutionをsupersedeする。

## Enumerations

### run_result

```text
initialized
no_change
change_detected
error
skipped
```

- `initialized`: previous checkpointが存在しないとHuman-approved activation recordから確認でき、初回metadataを保存した。
- `no_change`: 有効なprevious checkpointとの比較に成功し、fingerprintとreplacement indicatorsに変更疑いがない。
- `change_detected`: metadata差分またはsame-URL replacement疑いを検出した。formal evidenceではない。
- `error`: access、parse、state、persistence等により信頼できる判定を完了できない。
- `skipped`: disabled、active期間外、Level 1 target等、sourceへaccessせず意図的に処理対象外とした。

### target_state

```text
uninitialized
healthy
degraded
pending_human_review
stopped
disabled
```

`initialized` はrun resultでありtarget stateではない。初回runのcommit後はcheckpointを `healthy` とする。`disabled` はHuman-owned registryの `enabled=false` を反映する状態で、workflowがregistryを変更して作る状態ではない。

### error_code

```text
http_error
timeout
authentication_required
rate_limited
parse_error
timestamp_parse_error
content_ambiguous
low_confidence
source_unavailable
unexpected_format
terms_not_approved
state_unavailable
persistence_error
notification_error
```

実装時に追加する場合もenum、validator、docs、negative testsを同じPRで更新する。PR Dはstateを先にcommitするため、notification failureを独立receiptの `status=failed` とerror分類で表し、commit済みrunを事後更新しない。成功したsource observationの `run_result` を `error` へ上書きしない。

## State Transitions

| current state | run result / condition | next state | rule |
| --- | --- | --- | --- |
| `uninitialized` | first valid observation | `healthy` | runは `initialized`。state消失時には使用不可 |
| `healthy` | valid comparison, no suspicion | `healthy` | runは `no_change` |
| `healthy` | metadata fingerprint change | `pending_human_review` | runは `change_detected` |
| `healthy` | fingerprint一致かつreplacement suspicion | `degraded` | runは `error/content_ambiguous`。`no_change`禁止 |
| any active state | transient observation error | `degraded` | bounded retry後も解消しない場合 |
| `degraded` | later valid no-change observation | `healthy` | error episodeをclose可能 |
| `degraded` | later change | `pending_human_review` | change notificationを優先 |
| `degraded` | retry exhausted or stale gap exceeds profile | `stopped` or `degraded` | Human notificationとpolicyに従う |
| `pending_human_review` | repeated same change | `pending_human_review` | Issueを重複発行しない |
| `pending_human_review` | later `no_change`, unresolved change remains | `pending_human_review` | 後続runは未解決changeを消去しない |
| `pending_human_review` | transient observation error | `pending_human_review` | pending pointerとerror healthを直交して保持 |
| `pending_human_review` | Human resolution recorded | next runで `healthy` candidate | workflowがHuman decisionを捏造しない |
| any state | `enabled=false` | `disabled` | source accessなし |
| any active state | previous valid state unavailable | `stopped` | `state_unavailable`、再初期化禁止 |
| any active state | fatal persistence failure | `stopped` candidate | partial stateをcommitせずPR Dのatomic persistenceで確定 |

```text
error != no_change
change_detected != formal evidence
initialized != no_change
notification failure != observation failure
unresolved change_detected cannot transition to healthy until Human review resolves the pending change
```

### State Priority

重要な `change_detected` が存在する場合、notificationの成否にかかわらず `target_state=pending_human_review` を優先する。

```text
change_detected + notification success
-> pending_human_review

change_detected + notification failure
-> pending_human_review
   + committed run notification_status=pending
   + notification receipt status=failed
```

notification failureによって未確認のchangeを `degraded` へ置き換えない。`degraded` はsource observation failure、state retrieval failure、persistence failure、stale monitoring gap、その他の正常な監視継続能力の低下に使用する。

PR Cのruntimeでは、未解決changeがあるtransient errorは `pending_human_review` と `last_error_code` を同時に保持する。fatal `state_unavailable` はpending pointerを保持したまま `stopped` とする。`state_unavailable` または `persistence_error` がcheckpointのlatest fatal errorである場合、validatorは `target_state=healthy` を拒否する。

実際の `persistence_error` は保存失敗時に発生するため、persistenceを実装しないPR Cは「失敗した書込みがcheckpointをcommitした」とするrecordを生成しない。fatal state分類は `stopped` と確定するが、run、partial bundle、current checkpointの公開規則はPR Dのatomic persistenceで実装する。

Run Nが `change_detected`、notification failureで終わり、Run N+1に追加変更がない場合、Run N+1の `run_result` は `no_change` にできるが、checkpointの `target_state` はHuman resolutionまで `pending_human_review` を維持する。

## Atomic Persistence

### Logical Transaction

1 runのlogical transactionは次のimmutable bundleとする。

```text
monitor_state_bundle/
  target.json
  checkpoint.json
  run.json
  run_history.json
  resolution_history.json
  manifest.json
```

単一checkpointだけでなく、validatorがlineageと未解決changeを再検証できるrun/resolution履歴を同じbundleへ保存する。上記6ファイル以外の欠落・追加を許可しない。

`manifest.json` は最後に生成し、最低限次を持つ。

```text
schema_version = monitor_state_bundle_v1
monitor_target_id
monitor_run_id
created_at
checkpoint_version
previous_run_id
target_sha256
checkpoint_sha256
run_sha256
run_history_sha256
resolution_history_sha256
bundle_status = committed
```

manifestはstrict Pydantic modelでmachine validationし、unknown fieldを拒否する。`bundle_status=committed` は全fileのcontract validation、cross-file validation、hash照合が成功した場合だけ設定する。manifest欠落、unknown version、hash mismatch、ID不一致、version不連続、file欠落をpartial/uncommitted bundleとして拒否する。manifest延期はPR Dで `CLOSED` とする。

### Commit Rule

commit済みstateとは、次をすべて満たす公開済みbundleである。

1. previous committed bundleを取得・検証できる。初回はHuman-approved activationによりprevious state不存在を証明できる。
2. previous bundleのcheckpoint、run history、resolution historyをruntime入力にする。
3. generated run/checkpointと全履歴を `validate_monitor_bundle` へ通し、`validation_report.ok=true` を保存前hard gateにする。
4. staging directoryへ全fileを書き、manifestを最後に生成してhashを照合する。
5. localでbundle全体を再検証し、directory renameで公開する。
6. bundle全体を1つのimmutable artifactとしてuploadし、再取得してmanifest、hash、ID、version、lineageを再検証する。

run保存失敗ならcheckpointを進めない。checkpoint保存失敗ならrunを成功扱いにしない。upload/finalizeまたはread-after-write validation失敗は `persistence_error` とし、partial bundleをcurrent stateへ昇格しない。

通知はartifactのuploadと再取得検証が成功した後に別jobで実行する。通知失敗でもcommit済みobservationとcheckpointを変更せず、bounded retryの最終結果を独立notification receipt artifactへ保存する。重要なchangeは `target_state=pending_human_review` とrun上の `notification_status=pending` を維持する。

`last_successful_run_id` は最後にcommit済みでsource observationが成功したrunを指す。復旧時はlatestと称するartifact名だけを信用せず、lineage、version、manifest hashを検証してcurrent stateを決定する。

## Persistence Boundary

論理保存方式は次とする。

```text
current checkpoint + append-only monitor run
```

第1号pilotではGitHub Actions artifactをtemporary persistenceとして使用できる。ただしartifactはretention期限、workflow run削除、取得失敗、repository設定変更により消失し得るため、長期machine truthの唯一の正本ではない。

```text
previous valid stateを取得不能
-> state_unavailable
-> sourceへaccessせずstop
-> Human notification
```

state取得不能を初回runとして再初期化してはならない。例外はregistryのHuman-owned activation fieldsが、run IDとgeneration 1を積極的に証明する初回だけである。artifact retentionは14日とするが、長期machine truthではない。retention等でstateが消失した場合は `state_unavailable` としてfail closedし、pilot終了前にobject storageまたはdatabase等の恒久storageを別ADRで再設計する。

artifact名は `monitor_target_id + checkpoint_version + run_attempt + monitor_run_id` で一意化する。旧artifact名もread互換を維持する。GitHub APIから非expiredかつ `head_branch=main` の候補を列挙し、最大version内の最大run attemptが一意な場合だけdownloadする。manifestのtarget/version/run identityがartifact名と一致しなければ拒否する。

## Registry Format

| candidate | advantages | risks |
| --- | --- | --- |
| CSV | 現行ERSのrow-oriented data contract、diff、Human review、既存validator patternと整合 | null/boolean型、escaping、将来のnested schedule表現に注意 |
| JSON | type、null、将来のnested structureを表現しやすい | Human diffが冗長になり、現行CSV data contractと別運用になる |

第1号はflatなfieldだけで足りるため、`data/config/monitor_targets.csv` を採用する。`schedule_profile` は別の承認済みprofile定義を参照し、cronやnested設定をrowへ埋め込まない。production registryはheader-onlyで、実targetを含まない。manual dispatchだけがtest fixture registryのfictional targetを使用できる。

registryはmain上のHuman-reviewed configurationを正本とする。GitHub Actionsは `contents: read` で読むだけとし、mainへのpush、registry自動修正、approval fieldの補完を禁止する。runtime checkpoint/runはregistry CSVへ書き込まない。

## Schedule Profile

domain dataにはcron文字列ではなく、意味を持つprofile IDを保存する。

```text
schedule_profile = prospective_event_v1
```

profileのminimum semantics:

- 通常期間: business dayに1回。
- event予定日の5営業日前から: business dayに1回以上。
- 前日: Human-approved windowで追加確認。
- 当日: planned session前後を確認。
- session不明: 自動時刻を推測せずHuman review。

exchange calendar、holiday、event-specific windows、最大許容gapはprofile定義の責務とする。GitHub Actions cronは起動機構でありdomain scheduleの正本ではない。scheduled runは厳密時刻を保証しないため、各runでprofile上のexpected previous observation windowとcheckpointの `last_success_at` を比較する。

stale gapがprofileの最大許容値を超えた場合は `no_change` にしない。PR Dでは通常時36時間、event 5営業日前から前日24時間、event当日12時間を上限とする。休日calendarを増設せず平日だけを数えるpilot最小実装とし、event dateが必要なのに不明なら最も厳しい12時間を使う。閾値超過は `ObservationFailure(state_unavailable)`、`target_state=stopped`、Human通知へ進む。

## GitHub Actions Contract

workflowのminimum permissions:

```yaml
permissions:
  contents: read
```

Issue通知を行うjobだけに `issues: write` を付与する。`contents: write`、mainへのpush、registry変更権限は付与しない。

artifact取得jobだけに `actions: read` を付与する。`actions: write` と `pull-requests: write` は使用しない。新しいsource credentialは導入せず、GitHub APIはjob-scoped `GITHUB_TOKEN` だけを環境変数から受け取る。tokenをURL、manifest、diagnostic、Issue本文へ含めない。

workflowは次を満たす。

1. `workflow_dispatch` と6時間ごとのscheduled executionを持ち、毎時0分を避ける。cronはmachine truthにしない。
2. target/run単位のconcurrencyとidempotency keyでduplicate observationを抑制する。
3. registryをvalidateし、terms、enabled、active period、Human approval gateをsource access前に検査する。
4. previous committed stateを取得・検証する。取得不能ならstopし、初期化しない。
5. bounded retryだけを行い、回数とbackoffをrunへ記録する。
6. source metadataを取得し、canonical fingerprintとreplacement indicatorsを比較する。
7. stale gapをprofileから検査する。
8. run/checkpoint bundleをcross-validateし、artifactとしてpublish後にread-after-write検証する。
9. change/errorだけIssue通知し、`no_change` はActions summaryに留める。
10. source result、persistence result、notification resultを別々に記録する。
11. Python `3.11.9` を固定し、project最低versionと一致させる。
12. target単位の `concurrency` を使い、state保存途中をcancelしないため `cancel-in-progress=false` とする。

workflow run欠落自体はそのrunから記録できないため、次回runのstale gap検査と、別のwatchdogまたはHuman dashboardで検知する。stale watchdogが同じmonitor stateへ書き込む場合も、同じatomic bundle契約とconcurrencyを使用する。

## Fingerprint V1

fingerprint inputは固定順序のordered pairとする。

```text
[
  ["source_url", normalized_value],
  ["title", normalized_value],
  ["document_id", normalized_value],
  ["published_at", normalized_value],
  ["stable_metadata", normalized_value]
]
```

serializationとhash:

```text
ordered [field_name, normalized_value] pairs
UTF-8
compact JSON
SHA-256
lowercase hex
fingerprint_version = metadata_v1
```

canonicalization:

- URLはschemeとhostをlowercase化し、fragmentを除去する。path caseを維持する。queryの除去や並替えはsource別に勝手に行わない。
- titleはUnicode NFKC、trim、連続whitespaceの単一space化を行う。
- datetimeはtimezone必須とし、UTCのcanonical表現へ変換する。date-onlyを架空時刻へ変換しない。
- missingはJSON `null` とし、空文字と同一視しない。
- `stable_metadata` は承認済みkeyだけをkey名順に並べ、unknown fieldを黙ってhash inputへ追加しない。

```text
monitor fingerprint != evidence content hash
fingerprint equality != body identity
```

fingerprint一致は観測対象metadataがcanonical contract上同じことだけを示す。本文同一、raw file同一、source未変更を証明しない。

## Same-URL Replacement

利用条件上取得可能な範囲で次を補助indicatorとする。

```text
ETag
Last-Modified
Content-Length
source-side corrected marker
source-side updated timestamp
```

PR Cではindicatorが前回と矛盾する、source側markerがある、またはadapterが差替え疑いを返し、かつfingerprintが一致する場合、`run_result=error`、`error_code=content_ambiguous` とする。既存contractではfingerprint差分のない `change_detected` は不正であるため、この経路を使用する。checkpointはpending changeがなければ `degraded`、既存pending changeがあればpointerを保持して `pending_human_review` とし、いずれもHuman notificationを必要とする。indicatorを取得できない場合は `replacement_detection=unavailable` とし、本文同一を断定しない。

## Notification Contract

| condition | notification |
| --- | --- |
| `initialized` | pilot activation時のHuman確認用に1回通知候補 |
| `no_change` | 通知しない |
| `change_detected` | 通知する |
| observation `error` | bounded retry後に通知する |
| `degraded` / `stopped` | 通知する |
| `skipped` | terms/approval異常時は通知、通常のdisabled/期間外はsummaryのみ |

通知には最低限次を含める。

```text
monitor_target_id
company_id
earnings_event_id
monitor_run_id
detected_at
run_result
what_changed
source_url
observation_confidence
recommended_next_action
requires_human_decision
```

通知はformal evidenceではなく、Human decisionの代替でもない。

### GitHub Issue Dedupe

change episodeのdedup key:

```text
monitor_target_id + first unresolved change run ID
```

error episodeのdedup key:

```text
monitor_target_id + error_code + error_episode_identifier
```

同一open episodeでは新規Issueを毎run作らず、既存Issueへcommentを追記する。pending中の追加changeはappend-only run historyへ残し、checkpointはlatest unresolved changeを指す。dedup keyはfirst unresolved changeを使うため、Humanは同じIssue内で最初と追加changeを区別できる。error episode identifierは最初の連続同一error run IDから生成する。PR DはIssueを自動closeしない。change IssueはHuman resolutionまでopen、error Issueはsource回復、state正常化、unresolved Human decisionなしを満たした場合にclose候補とする。

### Notification Failure

source observation、state persistence、notification deliveryを別結果として扱う。

- source observation成功、state persistence成功、notification成功: observation resultを維持する。
- source observationが `change_detected`、state persistence成功、notification失敗: `run_result=change_detected` と `target_state=pending_human_review` を維持し、notification failureを独立receiptへ記録する。代替notificationまたはwatchdogを要求する。
- source observationが成功し重要changeなし、state persistence成功、notification失敗: observation resultを維持し、監視継続能力への影響がある場合はtargetを `degraded` とする。
- source observation成功、notification成功、state persistence失敗: bundleはcommit不可。`persistence_error` とし、次runでIssue dedup keyを使う。
- source observation失敗: notification成否にかかわらず `no_change` または `change_detected` にしない。

notificationは最大3 attempts、backoff 0/1/2秒の固定bounded retryとする。failureが観測metadataを消さない一方、Humanへ届いていないchangeを `healthy` または単なる `degraded` と扱わない。最終failureはreceipt artifactとworkflow failureで別経路から検知可能にする。未解決changeは後続runが `no_change` でも `pending_human_review` を維持し、対象changeに対するHuman resolution recordが確認された場合だけ解除候補になる。

## Implemented Data Contracts And Runtime

PR Bでは次の4 schemaを分離する。

```text
monitor_target.schema.json
monitor_checkpoint.schema.json
monitor_run.schema.json
monitor_resolution.schema.json
```

統合しない理由は、`monitor_target` がHuman-owned Git configuration、`monitor_checkpoint` がmutable current state、`monitor_run` がappend-only machine audit record、`monitor_resolution` がappend-only Human decisionだからである。

bundle manifestはPR Dでstrict Python modelとして実装済みである。CSV上のrun/checkpoint version、previous run、last successful run、fingerprint、resolution lineageに加え、artifact file set、SHA-256、identity、read-after-writeを検査する。manifest validationなしでartifactをcurrent stateへ昇格しない。

PR Cでは `src/earnings_research/monitoring/` に次を実装する。

```text
offline fixture -> SourceObservation -> normalization -> metadata_v1 fingerprint
-> comparison/state transition -> monitor_run + monitor_checkpoint
-> validate_monitor_bundle
```

adapter inputはrepository内の自作HTML/JSON fixtureだけで、live network clientを持たない。coreはrunとcheckpointを1つの `MonitorTransitionResult` として返し、全run lineage、Human resolution、current checkpointをin-memory validatorへ通す。PR Dはtestableなoperational CLI、registry reader、stale評価、bundle persistence、GitHub artifact/Issue clientをcoreの外側へ追加する。GitHub clientはActionsのstate transportと通知だけに限定し、IR sourceへ接続しない。

live adapterのfailure contractは次に固定する。これらを `no_change` へ変換してはならない。

```text
HTML/API parse failure -> ObservationFailure(parse_error)
timestamp parse failure -> ObservationFailure(timestamp_parse_error)
authentication failure -> ObservationFailure(authentication_required)
rate limit -> ObservationFailure(rate_limited)
```

`source_url` にusernameまたはpasswordのuserinfoがあるtargetはregistry validationで拒否する。credentialがlog、artifact、Issueへ流出する入口を閉じるためである。

## Live Source Adapter Contract

PR E1の `LiveSourceAdapter` はpublic HTML／JSON metadataを1件観測するためのlibraryであり、実targetのactivationまたはscheduled executionではない。HTTP clientにはHTTPXを採用し、redirectを自動追従せず、streaming responseとtimeoutを明示制御する。

network callより前に、既存 `monitor_target` の次の全条件を検査する。

- `enabled=true`。
- `automated_access_permitted=true`。
- `monitoring_level=level_2`。
- `terms_review_state=candidate_specific_review_completed`。
- `automation_approved_by` が `human:` identifierである。
- `activation_state=activated`。
- `activation_approved_by` が `human:` identifierである。

1条件でも欠ければ `access_not_approved` とし、transport call countは0でなければならない。AIがapproval fieldを補完、推定、更新してはならない。

request policyは次に固定する。

- `https`、default port 443、userinfoなし、credential様query keyなし。
- target `source_url` のscheme／host／effective portをexact approved originとする。
- redirectは1 hopずつ手動検査し、same-originだけを最大3 hop許可する。
- cross-origin、HTTPSからHTTPへのdowngrade、userinfo、port変更、loop、hop超過を拒否する。
- `localhost`、localhost suffix、private／loopback／link-local等のliteral IPを拒否する。
- cookies、authentication、proxy環境変数、automatic retryを使用しない。TLS certificate verificationを無効化しない。
- User-AgentはERS public-metadata monitorであることを明示する。

PR E1.5では各requestの直前にapproved hostnameをresolverで解決し、全A／AAAA answerがglobally routable unicastである場合だけ続行する。1件でもloopback、private、link-local、multicast、unspecified、reserved、その他non-global addressが混ざれば全answerを拒否する。DNS失敗または空answerは `source_unavailable` とし、`no_change` へ変換しない。

PR E1.6ではresolverをdaemon workerで実行し、callerの待機時間を5秒またはoverall budget残時間の短い方へ制限する。timeout後にworkerが完了してもHTTP処理へ進めず、同じadapter instanceから新しいresolver workerを起動しない。resolverが返った直後にoverall 15秒budgetを再計算し、残時間がなければHTTPを開始しない。`UnicodeError`、`ValueError`、`RuntimeError`等の予期しないresolver exceptionもraw detailを出さず `source_unavailable` へ正規化する。

A／AAAAがともに安全な場合はIPv4を優先し、同一family内では数値順で決定的に選択する。IPv6 literalのcanonical URLとauthorityにはbracketを維持する。IPv4-mapped IPv6、6to4、well-known NAT64に埋め込まれたIPv4も検査し、埋込先がnon-globalなら拒否する。

検証後はHTTPCoreのpublic custom `NetworkBackend`で、選択した検証済みIP literalへTCP接続する。HTTP requestのHost semantics、TLS SNI、certificate hostname verificationにはapproved hostnameを維持するため、check後にOS resolverを再利用しない。requestごとにconnection poolを新規作成してresponse処理後に閉じ、別run、別redirect、別DNS validation結果を跨いだconnection reuseを禁止する。redirect先もURL／origin検査後に同じDNS検査とIP pinningを繰り返す。

application側のDNS rebinding／TOCTOU境界はこれで閉じる。GitHub-hosted runnerまたは将来のself-hosted runnerにおけるegress firewallはdefense-in-depthとして別途検討する。

resource limitはDNS 5秒、connect 5秒、read 10秒、overall 15秒、response body 2 MiB、connection 1本とする。scheduled workflowのtarget単位monitor jobには `timeout-minutes: 10` を設定し、process-levelの上限も持たせる。`Content-Length`が上限超過、invalid、または実bodyと矛盾する場合は成功扱いしない。許可するmedia typeは `text/html` と `application/json` だけである。charsetはUTF-8と一般的な日本語encodingをstrict decodeし、未知charset、decode replacement、JSONの非UTF-8を拒否する。

generic parserが抽出するのはtitle、document ID候補、published timestamp候補、訂正marker等の最小metadataだけである。raw bodyは `SourceObservation`、monitor bundle、error detailへ保存しない。timestampがtimezoneなしまたは矛盾する場合は `timestamp_parse_error`、HTML／JSON構造または必須metadataを安全に読めない場合は `parse_error` とする。

HTTP 401／403は `authentication_required`、429は `rate_limited`、408とtimeoutは `timeout`、404／5xx／transport failureは `source_unavailable`、その他の不正responseは `http_error` または `unexpected_format` へ写像する。`javascript:`、`mailto:`、`data:`等のopaque redirectでHTTPXが返す `InvalidURL` も `unexpected_format` へ変換し、adapter contract外へescapeさせない。exception本文、Location本文、response本文、query、credentialをdiagnosticへ含めない。adapter自身はretryせず、retryable分類だけを返す。

adapter自身はapplication logを出さない。callerが運用logを追加する場合も、`monitor_target_id`、sanitized origin、status class、elapsed time、`error_code`に限定し、full URL、query、cookies、authorization、response bodyを記録しない。

ETag、Last-Modified、Content-Length、明示的な訂正markerが前回checkpointと矛盾する場合はreplacement suspicionを立てる。fingerprint一致でも `no_change` へ落とさず、runtimeの `content_ambiguous` 経路へ送る。conditional requestは未実装である。

testはinjected resolver、HTTPX mock transport、HTTPCore fake network backendだけを使用し、実DNSまたは実internetへ接続しない。pinning wiring contract testは `LiveSourceAdapter` から `PinnedHTTPTransport` とHTTPCore `NetworkBackend` までの実経路を通し、TCP接続先が検証済みIP、TLS server hostnameがapproved hostname、HTTP Host authorityもapproved hostnameであることを別々に実測する。production registry、workflow、fixtureへ実企業、実ticker、実IR URLを追加しない。

## Validator Contract

PR BからPR Dのvalidator/persistence boundaryは最低限次を検査する。

- unique `monitor_target_id`。
- `company_id`、`earnings_event_id`、target referenceの存在とscope。
- `monitoring_level=level_2` ではHuman-approved `automated_access_permitted=true`、`enabled=true`、`automation_approved_by`、completed terms reviewが揃う。
- Human-only fieldがworkflow outputまたはruntime bundleに含まれない。
- active periodとtimestamp ordering。
- timezoneとschedule profileが承認済みenumである。
- `run_result`、`error_code`、notification fieldの組合せ。
- 初回だけ `initialized` を許し、previous committed state消失時の再初期化を拒否する。
- `no_change` はvalid previous checkpoint、successful observation、fingerprint比較、replacement suspicionなしを要求する。
- observation errorをsuccess resultへしない。
- fingerprint format、algorithm、version、canonical input completeness。
- checkpoint versionのtarget単位単調増加とexact +1。
- before/run/after ID、version、fingerprint、previous run lineage。
- targetごとのcurrent checkpoint一意性。
- run/checkpointのversion、ID、fingerprint lineage、manifest file set、hash、commit marker、read-after-write result。
- persistence error時にcheckpointをadvanceしない。
- terms review未承認、expired、reference欠落時のaccess拒否。
- notification required/status/referenceのrow整合とIssue episode dedup。
- unresolved `change_detected` が存在するcheckpointを `healthy` にしない。
- `change_detected + notification_error` でも `pending_human_review` を維持する。
- 後続 `no_change` が未解決changeを自動解消しない。
- Human resolutionなしの `pending_human_review -> healthy` を拒否する。
- notification resultとobservation resultを独立に検査し、一方のfailureで他方を書き換えない。
- raw content、credentials、provider dataをdiagnostic fieldへ保存しない。
- latest fatal `state_unavailable` / `persistence_error`を持つcheckpointが `healthy` を名乗らない。

次は実装済みとは扱わない。

- live sourceからのsame-URL replacement signal取得。
- Issueの自動closeとbackup notification。
- permanent state storageとcross-artifact retention保証。

positive fixtureだけでなく、state loss、partial bundle、version skip、duplicate tail、approval bypass、false no-change、notification failureのnegative fixtureを必須とする。

PR Bでは最低限次のfixtureを含める。

| case | input | expected |
| --- | --- | --- |
| 1 | Run Nが `change_detected`、notification failed、`checkpoint_after=degraded` | reject |
| 2 | Run Nがunresolved `change_detected`、Run N+1が `no_change`、Human resolutionなしで `checkpoint_after=healthy` | reject |
| 3 | `change_detected`、notification failed、`checkpoint_after=pending_human_review` | valid |

## ICECO Non-Activated Examples

次はID設計例であり、正式company、event、source、terms、target registrationではない。

| monitor_target_id | source category | automated_access_permitted | enabled | company_id |
| --- | --- | --- | --- | --- |
| `ICECO_IR_CALENDAR` | `company_ir_calendar` | `false` | `false` | `pending_formal_record` |
| `ICECO_IR_NEWS` | `company_ir_news_index` | `false` | `false` | `pending_formal_record` |
| `ICECO_DISCLOSURE` | `company_ir_disclosure_index` | `false` | `false` | `pending_formal_record` |

`pending_formal_record` は実schemaへ投入可能な値ではなくdocumentation placeholderである。Human terms承認、formal company/event identity、reviewer、monitoring schedule、target activationが揃うまでregistry rowを作らず、有効化しない。

## Pull Request Sequence

1. PR A: 本書と最小限のreferenceだけを追加するdocumentation-only PR。
2. PR B: monitor target/checkpoint/run/resolution schemas、validator、positive/negative fixtures。manifestはPR Dへ延期。
3. PR C: single-company monitor、offline fixture/dry-run tests。network activationなし。
4. PR D: GitHub Actions、artifact temporary persistence、stale gap、Issue notification、operational CLI。live IR accessなし。
5. PR E1: approval-gated live source adapter library。mock-only test、実target activationなし、workflow接続なし。
6. PR E2: Human terms承認後のICECO target activation。実event採用は別のHuman gateを満たす。

価格取得、price adapter、J-Quants採用はこの系列から分離する。

## Fail-Closed Conditions

次の場合はsourceへaccessしない、またはcurrent stateをadvanceせず停止する。

- Human-owned approval field不足または矛盾。
- terms未承認、期限切れ、変更疑い。
- previous committed state取得不能またはvalidation失敗。
- current checkpoint 0件または複数件。ただしHuman-approved初回activationは別。
- run/checkpoint/manifestの部分保存、unexpected file、hash mismatch、ID不一致、version不連続。
- fingerprint version unknown、timestamp timezone欠落、canonical input ambiguity。
- access/parse/response formatの失敗。
- replacement suspicionを解消できない。
- stale gapが承認済みthresholdを超える。
- Human decisionが必要なchangeで全notification経路が失敗する。

## Independent Audit Focus

1. 前回stateを失ったときに `initialized` へ戻らず、`state_unavailable` で停止するか。
2. run、checkpoint、manifestの一部だけをcommit済みstateにできないか。
3. GitHub ActionsがHuman-owned registryを変更、補完、mainへpushできないか。
4. notification failureとsource observation failureを別々に保持できるか。
5. artifact retentionまたはworkflow run削除後の復旧がfail-closedか。
6. fingerprint一致を本文同一またはformal evidence同一と誤認しないか。
7. same-URL replacementの補助metadata不足を `no_change` にしないか。
8. stale gap、retry、Issue dedupが無限実行または通知洪水を起こさないか。

## Remaining Implementation Decisions

- live adapterのcompany固有parse contract、runner egress defense、terms再確認。
- ICECO targetのHuman activation、event identity、reviewer、monitoring dates。
- 14日retentionに依存しないpermanent storageとmigration contract。
- GitHub Issue以外のbackup notificationと、全notification failureを検知するwatchdog。
- 日本の祝日を含むexchange calendarがpilot後に必要か。

PR Dはfictional offline dispatchまでを実装し、production registryは空のままにする。上記を未決のまま実targetをactivationしない。

PR E1で、state生成、upload後の再取得検証、notifyを同じtarget単位jobへ統合し、全処理を1つのconcurrency group内で直列化する。third-party Actionsはcommit SHAへ固定する。artifact identityには `run_attempt` を含め、workflow re-runを区別する。Human-approved intentional reinitializationはPR E2以降の別設計とし、artifact lossから自動的に入れない。実装する場合は `initialization_generation` の増加と新しいHuman approvalを必須にする。
