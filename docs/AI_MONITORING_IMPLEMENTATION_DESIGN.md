# AI Monitoring Implementation Design

## Status And Scope

本書は [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) で定義したapproval-gated Level 2 monitoringを、将来schema、validator、single-company monitorへ実装するための詳細設計である。

```text
PROSPECTIVE_OPERATIONS.md
  = Human gate、source利用条件、運用責任の正本

AI_MONITORING_IMPLEMENTATION_DESIGN.md
  = machine state、状態遷移、永続化、実行・通知契約の設計
```

本書はdocumentation-onlyである。monitor schema、validator、monitor code、source adapter、GitHub Actions、scheduler、price adapter、実target、実eventを実装または承認しない。[ERS-ADR-0022](DECISIONS.md#ers-adr-0022) は `Proposed` のままとし、独立監査Pass後にHumanがstatus変更を判断する。

## Design Invariants

1. `monitor_target` はHuman-owned configurationであり、workflowはread-onlyで扱う。
2. `monitor_checkpoint` はtargetごとの現在状態、`monitor_run` は1回ごとのappend-only監査記録である。
3. `error != no_change`、`change_detected != formal evidence`、`initialized != no_change` とする。
4. 前回の有効stateを取得できない場合は再初期化せず、`state_unavailable` で停止する。
5. runとcheckpointの片方だけをcommit済みstateとして公開しない。
6. GitHub Actions artifactは短期pilot用のtemporary persistenceであり、長期machine truthの唯一の正本にしない。
7. source observationとnotification deliveryを分離し、通知失敗で観測結果を消さない。
8. monitoring結果をformal evidence、event status、baseline approval、price referenceへ自動昇格しない。
9. unresolved `change_detected` はHuman resolutionまで `pending_human_review` を維持し、後続 `no_change` だけで解消しない。

## Data Responsibilities

3つの責務は統合しない。所有者、更新頻度、immutability、保存先が異なるため、分離した方がHuman approval bypassと履歴上書きを検出しやすい。

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
```

workflow tokenはregistryへのwrite権限を持たず、これらを変更できない。特に `automated_access_permitted=true`、`enabled=true`、`automation_approved_by` の設定をAIが行ってはならない。設定が不完全、不整合、期限外、terms未承認ならrunは `skipped` または `error` とし、sourceへaccessしない。

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
| `recorded_by` | string | workflow identityとversion |

`last_checked_at` はerror runでも更新候補だが、commit済みbundle内でのみ進める。`last_success_at` と `last_successful_run_id` はsource observationが成功し、run/checkpoint bundleがcommitされた場合だけ進める。notificationだけが失敗した場合もsource observationの成功は保持する。

### monitor_run

1回の監視処理に対するappend-only監査記録である。過去runを更新または削除しない。

| field | type candidate | meaning |
| --- | --- | --- |
| `monitor_run_id` | string | globally unique run ID |
| `monitor_target_id` | string | registry reference |
| `workflow_run_id` | string or null | GitHub Actions等のexternal execution ID |
| `started_at` | datetime | run開始時刻 |
| `finished_at` | datetime | run終了時刻 |
| `run_result` | enum | observationの結果 |
| `error_code` | enum or null | machine-readable observation/persistence error |
| `error_message` | string or null | raw本文やsecretを含めない短い診断 |
| `retry_count` | integer | 同一run内のbounded retry回数 |
| `checkpoint_version_before` | integer or null | initialization時だけnull候補 |
| `checkpoint_version_after` | integer or null | commit不可ならnull |
| `previous_successful_run_id` | string or null | run lineage |
| `fingerprint_before` | string or null | 初回だけnull |
| `fingerprint_after` | string or null | observation失敗時はnull候補 |
| `replacement_detection` | enum | same-URL replacement detection能力 |
| `detected_change_summary` | string or null | metadata差分の短い説明 |
| `observation_confidence` | enum | `high`、`medium`、`low`、`unknown` |
| `stale_gap_detected` | boolean | expected observation window違反 |
| `notification_required` | boolean | notification policyの判定 |
| `notification_status` | enum | `not_required`、`pending`、`delivered`、`failed` |
| `notification_error_code` | enum or null | observation resultを消さないdelivery error |
| `notification_dedup_key` | string or null | Issue重複抑制key |
| `notification_reference` | string or null | Issue URL等 |
| `recorded_by` | string | workflow identityとversion |

`error_message` は自由記述、`error_code` はmachine判定に使う。HTTP response body、PDF本文、credential、provider raw dataをerrorへ含めない。

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

実装時に追加する場合もenum、validator、docs、negative testsを同じPRで更新する。notification failureは `notification_error_code=notification_error` で表し、成功したsource observationの `run_result` を `error` へ上書きしない。

## State Transitions

| current state | run result / condition | next state | rule |
| --- | --- | --- | --- |
| `uninitialized` | first valid observation | `healthy` | runは `initialized`。state消失時には使用不可 |
| `healthy` | valid comparison, no suspicion | `healthy` | runは `no_change` |
| `healthy` | metadata change or replacement suspicion | `pending_human_review` | runは `change_detected` |
| any active state | transient observation error | `degraded` | bounded retry後も解消しない場合 |
| `degraded` | later valid no-change observation | `healthy` | error episodeをclose可能 |
| `degraded` | later change | `pending_human_review` | change notificationを優先 |
| `degraded` | retry exhausted or stale gap exceeds profile | `stopped` or `degraded` | Human notificationとpolicyに従う |
| `pending_human_review` | repeated same change | `pending_human_review` | Issueを重複発行しない |
| `pending_human_review` | later `no_change`, unresolved change remains | `pending_human_review` | 後続runは未解決changeを消去しない |
| `pending_human_review` | Human resolution recorded | next runで `healthy` candidate | workflowがHuman decisionを捏造しない |
| any state | `enabled=false` | `disabled` | source accessなし |
| any active state | previous valid state unavailable | `stopped` | `state_unavailable`、再初期化禁止 |

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
   + notification_status=failed
   + notification_error_code=notification_error
```

notification failureによって未確認のchangeを `degraded` へ置き換えない。`degraded` はsource observation failure、state retrieval failure、persistence failure、stale monitoring gap、その他の正常な監視継続能力の低下に使用する。

Run Nが `change_detected`、notification failureで終わり、Run N+1に追加変更がない場合、Run N+1の `run_result` は `no_change` にできるが、checkpointの `target_state` はHuman resolutionまで `pending_human_review` を維持する。

## Atomic Persistence

### Logical Transaction

1 runのlogical transactionは次のimmutable bundleとする。

```text
monitor_state_bundle/
  checkpoint_before.json
  monitor_run.json
  checkpoint_after.json
  manifest.json
```

初回だけ `checkpoint_before.json` は明示的なJSON `null` またはschemaで定義したinitial markerとする。ファイル欠落で初回を表現しない。

`manifest.json` は最後に生成し、最低限次を持つ。

```text
schema_version
bundle_format_version
monitor_target_id
monitor_run_id
created_at
checkpoint_version_before
checkpoint_version_after
previous_run_id
file_hashes
commit_state
```

`file_hashes` は各fileのSHA-256を持つ。`commit_state=committed` は全fileのschema validation、cross-file validation、hash照合が成功した場合だけ設定する。manifest欠落、unknown version、hash mismatch、ID不一致、version不連続、file欠落をpartial/uncommitted bundleとして拒否する。

### Commit Rule

commit済みstateとは、次をすべて満たす公開済みbundleである。

1. previous committed bundleを取得・検証できる。初回はHuman-approved activationによりprevious state不存在を証明できる。
2. `checkpoint_before` がprevious bundleの `checkpoint_after` と一致する。
3. `monitor_run` とbefore/after checkpointのtarget ID、run ID、version、fingerprint lineageが一致する。
4. after versionがbefore version + 1である。
5. manifestが最後に生成され、全hashと `commit_state=committed` が有効である。
6. bundle全体が1つのartifactとしてupload/finalizeされ、再取得して検証できる。

run保存失敗ならcheckpointを進めない。checkpoint保存失敗ならrunを成功扱いにしない。upload/finalizeまたはread-after-write validation失敗は `persistence_error` とし、partial bundleをcurrent stateへ昇格しない。

通知はbundle commit前に試行し、その結果をrunへ記録する。通知成功後にpersistenceが失敗した場合、次runはIssue dedup keyで重複を抑制する。通知失敗でもsource observationは消さず、`notification_status=failed` と `notification_error_code=notification_error` を記録する。重要なchangeが存在する場合は `target_state=pending_human_review` を維持し、changeがなく監視継続能力だけが低下した場合に `degraded` を使用する。

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

state取得不能を初回runとして再初期化してはならない。artifact retention日数はdomain contractへ固定せず、workflow側で設定・監視する。pilot中はretention残存期間とlast successful artifactの取得可能性を確認し、pilot終了前にobject storageまたはdatabase等の恒久storageを別ADRで再設計する。

artifact discovery、retention、run削除、permissionに関するGitHub API上の制約はPR D実装前に実測する。取得できるはずという仮定だけでactivationしない。

## Registry Format

| candidate | advantages | risks |
| --- | --- | --- |
| CSV | 現行ERSのrow-oriented data contract、diff、Human review、既存validator patternと整合 | null/boolean型、escaping、将来のnested schedule表現に注意 |
| JSON | type、null、将来のnested structureを表現しやすい | Human diffが冗長になり、現行CSV data contractと別運用になる |

第1号はflatなfieldだけで足りるため、`data/config/monitor_targets.csv` を推奨する。`schedule_profile` は別の承認済みprofile定義を参照し、cronやnested設定をrowへ埋め込まない。PR Bで `monitor_target.schema.json` とCSV validatorを追加する候補とする。

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

stale gapがprofileの最大許容値を超えた場合は `stale_gap_detected=true` とし、`no_change` にしない。通常時、5営業日前、前日、当日の具体的thresholdはPR Bまたは運用レビューでHuman承認するまで未確定とする。重大gapは `degraded`、Human notification、または `stopped` とする。

## GitHub Actions Contract

将来workflowのminimum permissions:

```yaml
permissions:
  contents: read
```

Issue通知を行うjobだけに `issues: write` を付与する。`contents: write`、mainへのpush、registry変更権限は付与しない。

workflowは次を満たす。

1. `workflow_dispatch` とscheduled executionを持つ。
2. target/run単位のconcurrencyとidempotency keyでduplicate observationを抑制する。
3. registryをvalidateし、terms、enabled、active period、Human approval gateをsource access前に検査する。
4. previous committed stateを取得・検証する。取得不能ならstopし、初期化しない。
5. bounded retryだけを行い、回数とbackoffをrunへ記録する。
6. source metadataを取得し、canonical fingerprintとreplacement indicatorsを比較する。
7. stale gapをprofileから検査する。
8. run/checkpoint bundleをcross-validateし、artifactとしてpublish後にread-after-write検証する。
9. change/errorだけIssue通知し、`no_change` はActions summaryに留める。
10. source result、persistence result、notification resultを別々に記録する。

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

indicatorが前回と矛盾する、またはfingerprint一致でも差替え疑いがある場合は `no_change` にせず、`change_detected`、`content_ambiguous`、またはHuman reviewへ送る。indicatorを取得できない場合は `replacement_detection=unavailable` とし、本文同一を断定しない。availabilityの低下自体もrunへ記録する。

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
monitor_target_id + fingerprint_after
```

error episodeのdedup key:

```text
monitor_target_id + error_code + error_episode_identifier
```

同一open episodeでは新規Issueを毎run作らず、既存Issueへ追記する。error episode identifierは最初の連続error run ID等から安定生成し、成功runでepisodeをcloseする。Issue close候補はHumanがchangeを解決済みと記録した場合、またはerror後のsuccessful observationとstate回復がcommitされ、未解決Human判断がない場合とする。Human decisionが必要なchange Issueをworkflowが観測成功だけでcloseしない。

### Notification Failure

source observation、state persistence、notification deliveryを別結果として扱う。

- source observation成功、state persistence成功、notification成功: observation resultを維持する。
- source observationが `change_detected`、state persistence成功、notification失敗: `run_result=change_detected` と `target_state=pending_human_review` を維持し、notification failureを別fieldへ記録する。代替notificationまたはwatchdogを要求する。
- source observationが成功し重要changeなし、state persistence成功、notification失敗: observation resultを維持し、監視継続能力への影響がある場合はtargetを `degraded` とする。
- source observation成功、notification成功、state persistence失敗: bundleはcommit不可。`persistence_error` とし、次runでIssue dedup keyを使う。
- source observation失敗: notification成否にかかわらず `no_change` または `change_detected` にしない。

notification failureが観測metadataを消さない一方、Humanへ届いていないchangeを `healthy` または単なる `degraded` と扱わない。未解決changeは後続runが `no_change` でも `pending_human_review` を維持し、対象changeに対するHuman resolution recordが確認された場合だけ解除候補になる。

## Schema Proposal

次PRでは次の3 schemaを分離して作る。

```text
monitor_target.schema.json
monitor_checkpoint.schema.json
monitor_run.schema.json
```

統合しない理由は、`monitor_target` がHuman-owned Git configuration、`monitor_checkpoint` がmutable current state、`monitor_run` がappend-only audit recordだからである。ownershipとimmutabilityの異なるrecordを1 schemaへ統合すると、workflowによるapproval field更新やrun履歴上書きを検出しにくくなる。

bundle manifestはpersistence transport contractであり、PR BまたはPR Dで独立schemaを追加するかを決める。ただしmanifest validationなしでartifactをcurrent stateへ昇格する実装は許可しない。

## Validator Proposal

PR Bのvalidatorは最低限次を検査する。

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
- manifest file set、hash、commit marker、read-after-write result。
- persistence error時にcheckpointをadvanceしない。
- stale gapをschedule profile thresholdに従ってfailまたはwarning化する。
- terms review未承認、expired、reference欠落時のaccess拒否。
- notification required/status/dedup/referenceの整合。
- unresolved `change_detected` が存在するcheckpointを `healthy` にしない。
- `change_detected + notification_error` でも `pending_human_review` を維持する。
- 後続 `no_change` が未解決changeを自動解消しない。
- Human resolutionなしの `pending_human_review -> healthy` を拒否する。
- notification resultとobservation resultを独立に検査し、一方のfailureで他方を書き換えない。
- raw content、credentials、provider dataをdiagnostic fieldへ保存しない。

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
2. PR B: monitor target/checkpoint/run schemas、manifest decision、validator、positive/negative fixtures。
3. PR C: single-company monitor、offline fixture/dry-run tests。network activationなし。
4. PR D: GitHub Actions、artifact temporary persistence、Issue notification。artifact APIとretentionを実測する。
5. PR E: Human terms承認後のICECO target activation。実event採用は別のHuman gateを満たす。

価格取得、price adapter、J-Quants採用はこの系列から分離する。

## Fail-Closed Conditions

次の場合はsourceへaccessしない、またはcurrent stateをadvanceせず停止する。

- Human-owned approval field不足または矛盾。
- terms未承認、期限切れ、変更疑い。
- previous committed state取得不能またはvalidation失敗。
- current checkpoint 0件または複数件。ただしHuman-approved初回activationは別。
- run/checkpoint/manifestの部分保存、hash mismatch、ID不一致、version不連続。
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

## Open Implementation Decisions

- artifact APIでprevious committed bundleを検索・再取得する具体的制約、retention監視、permission。
- 真の初回activationとprevious state消失を区別するmachine-readableなHuman-owned情報。`activation_state`、`activated_at`、`activation_approved_by`、`initialization_generation` 等を候補とし、fieldはPR Bで決定する。初回であることを積極的に証明できる場合だけ `initialized` を許し、artifactが見つからないだけなら `state_unavailable` で停止する。
- pending changeのHuman resolutionを示すidentifier、`resolved_at`、`resolved_by`、対象runとのlineage。
- 通常時、5営業日前、前日、当日の最大許容stale gap。
- manifestを独立schemaとする時期と恒久storage migration contract。
- GitHub Issue以外のbackup notificationと、全notification failureを検知するwatchdog。

これらは実装前に閉じる。未決の値をworkflowへ埋め込んで運用開始しない。
