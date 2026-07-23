# TSO_LOG 29列正式定義

## 対象範囲

本書は、2026-07-22時点のTSO `data/signal_log.csv` に存在する29列を、ERS連携の参照契約として整理する。TSO本体や既存ログを変更するものではない。

先頭27列はTSO `generate_signal.py` のlegacy signal fieldsにも存在する。`verified_status` は台帳の取込・採点フローで使用され、`origin` は `ingest_daily_log.py` が追加する取込経路列であり、27列のgenerator出力には含まれない。

`used_by_ERS` は次の3値を使う。

- `yes`: 現行ERSスキーマに直接の保存候補がある。
- `candidate`: 研究上有用だが、意味または保存先の承認が必要。
- `no`: 現フェーズでは取り込まない売買・執行データ。

`mapping_status` はTSO列の存在確認ではなく、ERSへのマッピング確度を表す。不確定な対応は、TSO ownerによる契約承認と必要なERS列の追加が完了するまで `unknown` とする。

## 29列定義

| column_name | meaning | type | unit | allowed_values_or_range | example | used_by_ERS | target_table | target_column | mapping_status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `date` | シグナル判断日 | date | 暦日 | 現行行はISO `YYYY-MM-DD` | `2026-06-08` | yes | `tso_snapshot` | `as_of_datetime` | likely | dateからdatetimeへの変換時刻・timezoneは未決。決算発表時刻として解釈してはならない。 |
| `signal_id` | TSO判断行の安定識別子 | string | なし | non-empty。現行形式は日付・asset・side・typeを含む | `20260608_WTI_LONG_A-MOMENTUM` | yes | `tso_snapshot` | `signal_id` | confirmed | ERSで再生成せず、原文を保持する。 |
| `asset` | TSOの市場assetまたはinstrument label | string | なし | TSO universe値。上場会社tickerに限定されない | `WTI` | candidate | `company_master` | `ticker` | unknown | WTI、BTC、index、FX、yield等は決算会社と1対1対応しない。明示的なcompany/event relationが必要。 |
| `side` | 記録された判断方向 | enum-like string | なし | observed: `LONG`, `SHORT`, `BUY`, `SELL`, `NONE` | `LONG` | candidate | unknown | unknown | unknown | TSO取込はBUY/SELL aliasも許容する。ERSにはTSO方向列がなく、この値からtrade decisionを推定しない。 |
| `rank` | TSO判断クラス | enum-like string | なし | observed: `A`, `B`, `NO_TRADE`。取込処理は `C` も認識 | `A` | candidate | `tso_snapshot` | `rank` | unknown | 現行ERS `rank` はintegerで型が衝突する。数値へ強制変換しない。 |
| `type` | signal/setup分類label | string | なし | open vocabulary。momentum、pullback、watch、event wait、`DATA_UNAVAILABLE` 等 | `A-Momentum` | candidate | unknown | unknown | unknown | 歴史行で大文字小文字とseparatorが揺れており、ERS側のcontrolled vocabularyは未定。 |
| `entry_low` | TSO entry zoneの下限 | decimal | asset price | 入力時はpositive。非actionable行では空欄可 | `95.5` | no | not_applicable | not_applicable | not_applicable | 執行geometryは現行ERSの範囲外。source row/hashのみで追跡する。 |
| `entry_high` | TSO entry zoneの上限 | decimal | asset price | 通常 `entry_low <= entry_high`。非actionable行では空欄可 | `97.0` | no | not_applicable | not_applicable | not_applicable | `entry_low` と同じ境界を適用する。 |
| `sl` | TSOに記録されたstop-loss level | decimal | asset price | 入力時はpositive。side別の大小整合が必要 | `92.0` | no | not_applicable | not_applicable | not_applicable | ERSのorderまたは売買指示へ変換しない。 |
| `tp1` | 第1take-profit level | decimal | asset price | 入力時はpositive。side別の大小整合が必要 | `102.0` | no | not_applicable | not_applicable | not_applicable | 執行field。 |
| `tp2` | 第2take-profit level | decimal | asset price | 入力時はpositive。side別の大小整合が必要 | `109.0` | no | not_applicable | not_applicable | not_applicable | 執行field。 |
| `rr` | TSO setupのreward-to-risk ratio | decimal | ratio | generator行ではnon-negative。manual歴史行の契約は未確定 | `2.3` | candidate | unknown | unknown | unknown | 価格基準と `tp1`/`tp2` の関係を確認するまでERSへ直接格納しない。 |
| `win_prob` | outcome確定前のTSO確率見積り | decimal | probability | 契約は `0..1`。percent表記の入力はunit不正警告 | `0.47` | candidate | unknown | unknown | unknown | event、horizon、calibration cohortが定義されるまでERS confidenceへ転用しない。 |
| `expected_r` | R単位で表したTSO期待値 | decimal | R multiple | generatorは `win_prob * rr - (1 - win_prob)`。ERS暫定範囲 `-10..10` | `0.58` | yes | `tso_snapshot` | `expected_r` | confirmed | source値とversion contextを保持し、import時に再計算しない。 |
| `tq_score` | legacy 6 componentから計算されるTSO aggregate quality score | decimal | score | generatorでは `0..100` にclamp | `79` | candidate | unknown | unknown | unknown | 現行formulaは確認できるが、acronymと安定したformal contractは未承認。`trend_score` へはmapしない。 |
| `opp_score` | opposite sideのopportunityを表すlegacy score | decimal | score | 現generatorは `0..50`。歴史manual契約はより広い可能性 | `84` | candidate | unknown | unknown | unknown | sampleが現generator範囲を超えており、歴史的なsemantic driftがある。 |
| `no_trade_score` | no-trade判断の強さを表すscore | decimal | score | generatorでは `0..100` にclamp | `39` | candidate | unknown | unknown | unknown | ERS `no_trade_flag` と同義ではなく、thresholdとversion semanticsは未決。 |
| `risk_pct` | TSO risk allocation percentage | decimal | percent of capital/risk budget | 現generator値は `0`, `0.5`, `1.0`。manual値は変動 | `0.75` | no | not_applicable | not_applicable | not_applicable | position sizingはERS範囲外で、推奨値として取り込まない。 |
| `regime` | TSO判断時のmarket regime label | string | なし | open vocabulary。case・separatorの揺れあり | `oil_supply_shock` | yes | `tso_snapshot` | `regime` | likely | ERS enumは `risk_on`, `risk_off`, `neutral`, `mixed`, `unknown` のみ。raw値保持列または承認済みnormalizationが必要。 |
| `ems` | legacy `ems` component score | decimal | score | generatorでは `0..100` にclamp | `84` | yes | `tso_snapshot` | `ems` | likely | 構造的mappingは存在するが、acronym展開とversion別semantic definitionは未確認。 |
| `ffs` | legacy `ffs` component score。現generatorはabsolute 5-day price changeから導出 | decimal | score | generatorでは `0..100` にclamp | `88` | candidate | unknown | unknown | unknown | formal TSO contractなしにacronym展開やERS factor意味を確定しない。 |
| `cds` | legacy `cds` component score。現generatorはMA20/ATR extensionに応じて低下 | decimal | score | generatorでは `0..100` にclamp | `58` | candidate | unknown | unknown | unknown | formulaは実装根拠だが、承認済みsemantic definitionではない。 |
| `ias` | legacy `ias` component score。現generatorはRSIが50から離れるほど低下 | decimal | score | generatorでは `0..100` にclamp | `82` | candidate | unknown | unknown | unknown | sampleは旧定義またはmanual定義の可能性があり、raw値とversion contextを保持する。 |
| `cbs` | legacy `cbs` component score | decimal | score | generatorでは `0..100` にclamp | `76` | yes | `tso_snapshot` | `cbs` | likely | 構造的mappingは存在する。acronym展開と歴史的計算versionは未確認。 |
| `mes` | legacy `mes` component score。現generatorはATR/price上昇に応じて低下 | decimal | score | generatorでは `0..100` にclamp | `74` | yes | `tso_snapshot` | `mes` | likely | 構造的mappingは存在するが、semantic/version確認が必要。 |
| `invalidation` | TSO setupまたはwatch thesisの無効化条件 | string | なし | open text。価格条件または定性条件 | `91割れ` | candidate | unknown | unknown | unknown | ERS `no_trade_reason` やhypothesis invalidationとは同一でない。専用field/link承認までsource contextとして保持する。 |
| `verification_target` | 記録判断を後日評価するための観測対象 | string | なし | open text。MFE/MAE、TP、intervention、wait condition等 | `TP1_MFE_MAE` | candidate | unknown | unknown | unknown | prospective evaluation targetであり、verified resultではない。将来のhypothesis/evaluation link候補。 |
| `verified_status` | TSO outcomeのverification state | enum-like string | なし | observed: empty, `unverified`, `verified` | `verified` | candidate | `evidence` | `verified_status` | unknown | ERS側は特定evidence行のstatusで追加値もある。直接変換するとscopeとlineageを失う。 |
| `origin` | ledger行を生成した取込経路 | enum-like string | なし | implementation: `chatgpt_app`, `gpt_terminal`, `manual`。歴史行は空欄可 | `chatgpt_app` | candidate | unknown | unknown | unknown | TSOの28列input contractへ取込時に付加される29列目extension。source上の意味は確認済みだがERS targetは未決。publisher、asset source、evidence authorではない。 |

## ERS取込境界

現行の直接候補は `date`, `signal_id`, `expected_r`, `regime`, `ems`, `cbs`, `mes` とする。このうち構造的に `confirmed` なのは `signal_id` と `expected_r`。`regime`, `ems`, `cbs`, `mes` はsource semanticsまたはallowed valuesが完全一致しないため `likely` に留める。

次の列はschemaまたはgovernance判断前に取り込まない: `asset`, `side`, `rank`, `type`, `rr`, `win_prob`, `tq_score`, `opp_score`, `no_trade_score`, `ffs`, `cds`, `ias`, `invalidation`, `verification_target`, `verified_status`, `origin`。

`entry_low`, `entry_high`, `sl`, `tp1`, `tp2`, `risk_pct` は現フェーズで取り込まない。ERSは `source_file` と `source_row_hash` でprovenanceを保持し、TSO source rowをauthoritativeとする。

## 未確定事項

- TSOの入力は28列contract、保存ledgerは `origin` を付加した29列であることを実装とPR #99の取込記録で確認した。ERS側の正式import contract versionとownerは未決。
- TSO `rank` はcategorical、ERS `tso_snapshot.rank` はintegerで不一致。
- TSO `regime` はopen text、ERSは狭いenumで不一致。
- TSO `asset` はnon-company instrumentを含むため、`company_master.ticker` との文字列一致joinは不可。
- score acronym、計算version、歴史的互換性は正式import contractになっていない。

未確定列をraw保存する場合の列名、score非接続、mapping version方針は `TSO_RAW_FIELD_POLICY.md` を参照する。現行schemaへ未承認の `_raw` 列を追加してはならない。
