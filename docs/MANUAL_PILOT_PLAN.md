# 小規模手入力パイロット計画

## 目的

実在銘柄3〜5件を使い、schemaの妥当性、入力負荷、evidence lineage、reference price rule、TSO snapshot mappingを検証する。大量入力、外部API接続、backtest、score最適化は行わない。

計画段階では銘柄名を固定しない。case選定時にactual announcement timestampと必要price evidenceを取得できることを優先する。

## Case構成

| case_id | archetype | required_session | 主な確認目的 |
| --- | --- | --- | --- |
| `PILOT-01` | 引け後決算 | `after_close` | `next_open`、prior close、翌日特別気配の扱い |
| `PILOT-02` | 場中決算または業績修正 | `intraday` | last completed minute bar、halt、announcement timestamp |
| `PILOT-03` | 朝発表 | `before_open` | raw previous close、adjusted comparison、adjustment factor、announcement-day open、PTS分離 |
| `PILOT-04` | 良決算だが株価下落 | any | hypothesisとmarket reactionの分離、negative return入力 |
| `PILOT-05` | 割安放置またはvalue trap | any | KPI、guidance、cash-flow evidence、長期review負荷 |

3件で開始する場合は `PILOT-01`〜`03` を必須とし、4・5は余力がある場合に追加する。

## Case選定条件

- 日本株でcompany codeとactual disclosureをTDnet等のofficial sourceで確認できる。
- event sessionが3分類のいずれかへ明確に入る。
- daily OHLCを確認でき、intraday caseではminute barまたは監査可能なmanual sourceがある。
- split、halt、特別気配等の複雑caseは最大1件までとし、最初から全件を例外caseにしない。
- 銘柄選定は予測成績を良く見せる目的で行わない。

## 入力手順

1. companyとearnings eventを登録する。
2. announcement前のevidenceだけでbaselineを作りlockする。
3. KPI expected rowを必要数だけ登録する。
4. TSO snapshotはconfirmed/likely mappingだけを使い、unknown列はscoreへ使わない。
5. actual TDnet timestampを確認する。
6. `MANUAL_ENTRY_POLICY.md` に従ってreference priceを選ぶ。
7. actual result、KPI actual row、post-event reviewをappendする。
8. validationを実行し、error messageと修正時間を記録する。
9. day1/day5/day20は到達時にappendし、未到達windowを推測入力しない。

## 計測項目

各caseについて次を記録する。

| metric | unit / record |
| --- | --- |
| baseline入力時間 | minutes |
| evidence登録数 | count |
| KPI登録数 | expected/actual別count |
| reference price取得可否 | `automatic_candidate`, `manual`, `unknown` |
| reference price取得時間 | minutes |
| unadjusted price取得可否 | yes/no + source |
| adjusted price取得可否 | yes/no + source |
| corporate action adjustment factor | numeric / unknown |
| TSO snapshot入力可否 | yes/no + blocked columns |
| validation error | message、原因、修正時間 |
| post-review入力時間 | minutes |
| 欠落項目 | field list |
| 重複入力 | table/row count |
| 人間判断が難しい列 | field + reason |
| source terms確認事項 | provider + question |

## Pilot log template

各caseの作業logには最低限次を残す。

```text
pilot_case_id
company_id
earnings_event_id
announcement_session
baseline_minutes
evidence_count
kpi_expected_count
kpi_actual_count
reference_price_availability
reference_price_source
reference_price_minutes
return_reference_price_raw
return_reference_price_adjusted
corporate_action_adjustment_factor
tso_snapshot_available
tso_blocked_columns
validation_errors
validation_fix_minutes
post_review_minutes
missing_fields
duplicate_rows
difficult_fields
operator_notes
```

このtemplateは計画用であり、今回は新しいCSV schemaやsample dataを作らない。

## 合格基準

- 3つのsession caseでreference ruleを迷わず適用できる。
- 全caseでannouncement timestampとprice sourceをevidenceへ結び付けられる。
- `unknown` referenceのdependent return fieldsが空欄になる。
- baseline lock後にpre-event rowを書き換えない。
- TSO unknown列がscoreへ使われない。
- raw event referenceとadjusted comparisonが混同されず、factorとbasisを追跡できる。
- validation errorが人間に原因と対象rowを特定できる形で表示される。
- 1caseのbaseline入力が60分以内、post-review入力が30分以内を暫定目標とする。超過しても失敗ではなくschema改善材料として記録する。

## 中止条件

- source terms上、価格の保存・転記可否を判断できない。
- actual announcement timestampを確認できない。
- event後情報がbaselineへ混入した。
- source rowを上書きしないと入力できない。
- schema変更なしでは同じ重要fieldが3件以上記録不能になる。

中止時はcaseを都合のよい別銘柄へ黙って差し替えず、blocked理由を記録する。
