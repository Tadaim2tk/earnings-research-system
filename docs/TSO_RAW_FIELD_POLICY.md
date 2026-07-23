# TSO未確定列のraw保存方針

## 目的

TSO列の正式な意味やERS mappingが変わっても、source原文を失わず再解釈できるようにする。本書は将来の保存方式案であり、現行schemaへの列追加やimport実装は行わない。

## 共通rule

- `unknown` または `likely` の列をERS scoreへ使用しない。
- raw保存時はsource文字列・数値を変換せず、可能なら `_raw` suffixを使う。
- normalized interpretationをraw列へ上書きしない。
- `source_file`, `source_row_hash`, `mapping_version` を組で保持する。
- source row全体はTSO側をauthoritativeとし、ERSはsnapshot/provenanceを保持する。
- mapping変更時は過去rowをrewriteせず、新しいmapping versionで再解釈する。

暫定 `mapping_version` は `tso_ledger_29col_v0_2026-07-22` とする。これは列意味の承認versionではなく、今回観測した29列ledger mapping文書の識別子である。

## 列別方針

| source_column | raw_storage_column | store_or_skip | reason | used_for_score | mapping_status | mapping_version | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `regime` | `regime_raw` | store_after_schema_approval | open vocabularyをERS enumへ強制変換すると情報を失う | no | likely | `tso_ledger_29col_v0_2026-07-22` | normalized regimeを将来追加する場合も別列にする |
| `rank` | `rank_raw` | skip_structured_import_now | TSOはcategorical、現行ERSはintegerで衝突 | no | unknown | `tso_ledger_29col_v0_2026-07-22` | source row/hashでは保持。schema承認後にraw保存候補 |
| `origin` | `ingestion_origin_raw` | store_after_schema_approval | 取込経路として意味は確認済みだがERS targetがない | no | unknown | `tso_ledger_29col_v0_2026-07-22` | `source_name` や `created_by` へ流用しない |
| `asset` | `asset_raw` | store_after_schema_approval | non-company instrumentを含みcompany tickerへ直接mapできない | no | unknown | `tso_ledger_29col_v0_2026-07-22` | company relationは別mapping table候補 |
| `side` | `side_raw` | skip_structured_import_now | BUY/SELL/LONG/SHORT aliasとERS trade decisionの意味が異なる | no | unknown | `tso_ledger_29col_v0_2026-07-22` | source row/hashでは保持。売買判断へ転用しない |
| `ffs` | `ffs_raw` | store_after_schema_approval | acronymとhistorical calculation versionが未確定 | no | unknown | `tso_ledger_29col_v0_2026-07-22` | decimal文字列表現も原文保持を優先 |
| `cds` | `cds_raw` | store_after_schema_approval | current formulaは見えるがformal semantics未承認 | no | unknown | `tso_ledger_29col_v0_2026-07-22` | score componentとして再定義しない |
| `ias` | `ias_raw` | store_after_schema_approval | sampleとcurrent generatorの意味差があり得る | no | unknown | `tso_ledger_29col_v0_2026-07-22` | versionなしの横比較をしない |
| `no_trade_score` | `no_trade_score_raw` | store_after_schema_approval | `no_trade_flag` と同義でなくthreshold未決 | no | unknown | `tso_ledger_29col_v0_2026-07-22` | booleanへ変換しない |
| `verified_status` | `verified_status_raw` | store_after_schema_approval | TSO row outcomeとERS evidence verificationのscopeが異なる | no | unknown | `tso_ledger_29col_v0_2026-07-22` | ERS evidence statusへ直接mapしない |

## 現行schemaでの暫定運用

schema変更前は、新しい `_raw` 列をCSVへ勝手に追加しない。`tso_snapshot.source_file` と `source_row_hash` を保存し、必要なraw値はauthoritativeなTSO rowから再取得する。

`signal_id`, `expected_r` は既存のconfirmed mappingを使用できる。`cbs`, `ems`, `mes` は既存列へraw数値として保存候補だが、意味をERS側で再定義せず、scoreには使用しない。`date` はdatetime変換ruleが承認されるまでsource dateもprovenanceで保持する。

## 将来schema変更の条件

- pilotで3件以上、同じraw列を毎回参照する必要が確認された。
- mapping ownerとversion命名ruleが決まった。
- raw fieldをscoreへ接続しないvalidationまたはreview ruleを用意できた。
- correction時にsource row/hashとmapping versionを追跡できる。
