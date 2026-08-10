# 予想検証・理由分析・学習記録

## 目的

発表前に固定した仮説、決算そのものの評価、決算後の市場反応を結合し、1回の決算について次を一つの追記型記録として残す。

1. 事前予想の成否
2. 当たった、外れた、または判定できない理由
3. 次回決算で確認する改善候補

出力契約は [`post_event_learning_review.schema.json`](../schemas/analysis/post_event_learning_review.schema.json) とする。

## 入力

- locked済みの発表前baseline
- baseline lock以前に作成された事前仮説
- [`earnings_evaluation`](../schemas/analysis/earnings_evaluation.schema.json)
- [`market_reaction_tracking`](../schemas/analysis/market_reaction_tracking.schema.json)
- 任意の直前review version

外部情報を新たに取得せず、既に確定した研究記録だけを結合する。

## 分離する評価

次の5項目を別々に保持する。

- 事前仮説: `supported` / `partially_supported` / `rejected` / `pending`
- 決算評価: `positive` / `mixed` / `negative` / `in_line` / `inconclusive`
- 発表直後の市場反応
- 翌営業日の市場反応
- 5営業日後の市場反応

総合的な予想成否は事前仮説から判定し、株価方向だけでは決めない。したがって「良い決算だが株価下落」と「悪い決算で株価下落」は異なる記録になる。

## 総合成否

| 状態 | 条件 |
|---|---|
| `success` | 判定対象の事前仮説がすべて支持された |
| `failure` | 判定対象の事前仮説がすべて否定された |
| `partial_success` | 支持、部分支持、否定、未判定が混在する |
| `pending` | 仮説がない、またはすべて証拠不足である |

未判定や欠損を失敗へ変換しない。

## 理由分析

次を構造化する。

- 支持、否定、未判定となった仮説ID
- 事前期待を上回った、下回った数値項目
- 会社予想の上方、据置、下方修正
- 決算評価と市場初動の不一致から見た、市場期待水準の可能性
- 発表直後、翌営業日、5営業日後の方向変化
- append-onlyで追加された仮説撤回記録
- corporate actionや価格未到達による比較不能理由

市場期待の解釈は可能性として記録するだけで、原因を確定しない。根拠が不足する場合は`insufficient_evidence`とする。

会社予想についての読みは、事前仮説本文に`会社予想:`、`会社予想：`、または`company guidance:`と明示されている場合だけ成否を判定する。明示がなければ`not_recorded`とし、後から読みを創作しない。

## 撤回条件

locked済み仮説本文に`撤回条件:`、`撤回条件：`、または`invalidation condition:`と明記されている場合だけ、事前定義済み条件として扱う。

- append-onlyのinvalidation recordがある: `triggered`
- 条件記載がありinvalidation recordがない: `not_triggered`
- 条件記載がない: `not_recorded`
- 決算評価は仮説を否定したが正式な撤回記録がない: `insufficient_evidence`

文章から暗黙の撤回条件を推測しない。

## 学習記録

次回へ残す内容を、正式ルールとは分離して保存する。

- 維持候補の判断基準
- 弱める候補の判断基準
- 追加で観測する指標
- 再発防止すべき分析上の誤り
- 支持されたが一般則へ昇格させない仮説
- 否定された前提
- 次回確認事項

`production_rules_modified=false`および`scoring_weights_modified=false`を固定し、scoring ruleやweightを自動変更しない。

## 途中状態と追記

- 5営業日後まで揃った: `complete`
- 一部価格が未到達: `provisional`
- corporate action等で比較不能: `blocked`

後続価格が揃ったときは既存JSONを上書きしない。`review_version`を増やし、`supersedes_review_id`で前versionを参照する新しいファイルを作る。書込処理は既存pathへの上書きを拒否する。

## 情報境界

各入力を正規化したSHA-256とrecord IDを保存する。次を変更しない。

- locked baseline
- 発表前仮説本文
- 発表前予想値
- 発表前の撤回条件

後から得た決算結果や市場反応を発表前記録へ書き戻さない。

## CLI

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli review-earnings-outcome \
  --baseline path/to/pre_earnings_baseline.csv \
  --baseline-id BASE-EXAMPLE-001 \
  --hypotheses path/to/hypothesis_log.csv \
  --evaluation path/to/earnings_evaluation.json \
  --market-reaction path/to/market_reaction_tracking.json \
  --reviewed-at 2027-05-17T18:00:00+09:00 \
  --output path/to/post_event_learning_review-v1.json
```

後続versionでは`--previous-review`を指定する。

## 非対象

- 売買判断、発注、portfolio allocation
- scoring ruleまたはweightの自動変更
- TSOまたはTSO_LOGへの書戻し
- 外部情報取得
- IR監視、PDF解析、株価取得の再設計
