# Prospective Evidence Metadata

## Status

`Proposed`. 本書は `ERS-ADR-0019` のreview対象であり、Human承認前にprospective evidence登録やscoringを開始しない。

## Scope

prospective formal evidenceに必要なcontent hash、raw storage、license、append-only correction lineageを、既存 `evidence` rowへ直接保持する。

今回含めないもの:

- event延期・中止を表す `event_status`
- baseline親子関係、version、lock実装
- raw document downloaderまたはrepository内raw保存
- schema変更によるscoringの自動有効化
- historical 3社のevidence backfill

`pre_earnings_baseline` は既に `baseline_version`、`locked_at`、`baseline_record_hash` を持つ。parent/supersedes関係と延期時のnew version作成規則は、evidence lineageへ混在させず別PRで設計する。

## Representation

sidecarを作らず、`evidence_id`と同じCSV rowへoptional columnsを追加する。

理由:

- identityとmetadataのjoin失敗が起きない。
- `supersedes_evidence_id`を同一table内で検証できる。
- source timing、score利用可否、license/storage状態を一行で監査できる。
- 旧CSVは新しいoptional headerなしでもvalidatorが受理できる。

sidecarは既存CSV headerを変えない利点がある一方、join key欠落、孤立metadata、重複metadata、lineageの二重管理を防ぐ追加validatorが必要になるため採用しない。

## Fields

| field | enum / type | rule |
| --- | --- | --- |
| `evidence_status` | `original`, `correction`, `retraction_notice` | append-only rowの役割。現在の有効性を上書き表現しない |
| `supersedes_evidence_id` | string | correction/retraction target。self、missing、forward reference、entity変更を禁止 |
| `content_hash_status` | `verified`, `recorded_unverified`, `not_recorded`, `not_applicable`, `mismatch` | `mismatch`はblocking error |
| `content_hash` | string | hash値。`verified`、`recorded_unverified`、`mismatch`で必須 |
| `content_hash_algorithm` | `sha256` | hash値がある場合に必須 |
| `raw_storage_status` | `stored`, `metadata_only`, `storage_prohibited`, `storage_pending_review`, `unavailable` | raw未保存理由をsource不存在と分離 |
| `raw_location` | string | `stored`の場合だけ必須。Git pathを意味せず、承認済み保存先のidentifier |
| `license_status` | `permitted`, `restricted`, `unknown`, `not_applicable`, `review_required` | `unknown`や`review_required`は保存許可ではない |

## Metadata bundle

既存rowは新fieldをすべて省略できる。追加8fieldのいずれか一つでも記録する場合、次の3 statusをすべて記録する。

```text
content_hash_status
raw_storage_status
license_status
```

これにより、hashだけを記録してlicense/storage判断が欠落する状態を防ぐ。

## Cross-field validation

- `raw_storage_status=stored` では `raw_location` 必須。
- `raw_storage_status=stored` は `license_status=permitted` の場合だけ許可する。
- stored以外で `raw_location` を持たない。
- `content_hash_status=verified|recorded_unverified|mismatch` ではhash値とalgorithmを必須とする。
- `content_hash_status=not_recorded|not_applicable` ではhash値とalgorithmを持たない。
- `content_hash_status=mismatch` はvalidation failureとし、score利用やbaseline lockへ進めない。
- `evidence_status=correction|retraction_notice` では `supersedes_evidence_id` 必須。
- `supersedes_evidence_id` はself-reference、missing reference、後続row参照を禁止する。
- correction/retraction lineageでは `related_entity_type` と `related_entity_id` を変えない。

初期版はlicense overrideを設けない。例外承認fieldがない状態で`restricted`、`unknown`、`review_required`のraw保存を許すと監査不能になるためである。

## Correction lineage

元evidenceを削除・更新せず、訂正版または撤回通知を新しいrowとしてappendする。

```text
original evidence
  <- supersedes_evidence_id
correction or retraction_notice
```

新rowは元rowより後に置き、同じrelated entityを維持する。訂正関係が確定するまでscoringを確定しない。`verified_status`はsource verificationの保守的評価として残し、`evidence_status`はlineage上のrow役割として分離する。

## Backward compatibility

- 新fieldはすべてvalue optional。
- 新fieldだけ `header_required: false` とし、旧20列CSVでheader省略を許容する。既存columnのcanonical header契約は変更しない。
- 既存20列の `evidence_sample.csv` は変更せずvalidationを維持する。
- metadataを採用する新rowはbundleとcross-field rulesを満たす。
- schema変更だけでは既存evidenceをprospectiveへ昇格させず、`used_for_score`も変更しない。

## Raw storage boundary

`raw_location`はraw contentそのものではない。sampleではrepository外のimmutable storageを示すopaque identifierを使う。実provider dataの保存先、retention、AI processing、derived data条件はHuman承認が必要であり、raw fileをGitへ入れることをdefaultにしない。
