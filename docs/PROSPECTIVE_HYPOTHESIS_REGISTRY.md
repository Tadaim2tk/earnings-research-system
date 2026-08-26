# Prospective Hypothesis Registry

## 目的

旧 `earnings-research-os` の254件から得た19件の学習候補を、条件を後から動かせないprospective仮説として固定し、新しい決算イベントの観測を追記型で蓄積する。

この能力は研究仮説を測定する。weight、rank基準、売買ルールを変更しない。

## 正本と派生物

| record | role | update rule |
|---|---|---|
| `prospective_hypothesis_registry_v1` | 仮説の定義、比較条件、母数、判定基準 | version追加。既存versionを変更しない |
| `prospective_hypothesis_trial_bundle_v1` | 1決算イベントから得た対象群／非対象群の観測 | 1 event 1 fileで追記。上書きしない |
| `prospective_hypothesis_status_v1` | 全trialから再計算した現在状態 | 派生snapshot。正本ではない |

件数やstatusを可変の台帳行へ書き戻さない。`prospective_trials`、成功、失敗、平均差はtrialから毎回再計算する。

## 固定した19件

`data/prospective_hypotheses/legacy_research_v1.json` は `outputs/historical_research/research_knowledge.json` の19候補を一対一で固定する。source fileのSHA-256も保持し、候補値や効果量が変わった場合は検証に失敗する。

内訳は次のとおり。

- `pre_event`: 11件
- `post_event`: 8件
- `primary`: 6件
- `secondary`: 13件

`primary` は、方向性のある候補のうち、historical effective unitが20以上で、平均差2%以上または上昇率差10%以上のものとする。その他と`low_discrimination`は`secondary`とする。この優先度は調査順であり、正式ルールへの採否ではない。

## 発表前と発表後の分離

### pre_event

- `rank`
- `narrative`
- `judge`
- `risk_balance`
- `volatility_environment`
- `dollar_environment`

これらは `event_occurred_at` 以前に固定された値だけを使う。旧OSの分類時点が現行ERSほど厳密でなかったことはhistorical evidenceの限界として残し、prospective試行では発表前固定を必須にする。

### post_event

- `reaction`

reactionは発表後情報である。決算後の継続・反転研究だけに使い、発表前評価へ流用しない。

## イベント観測

`prospective_hypothesis_event_observation_v1` は次を分離する。

- 発表前に固定した特徴
- 発表後に得たreaction
- D1／D5／D20の期間別リターンと観測時刻
- 元となったERS record ID

必要な特徴や対象期間の価格が無い場合、その仮説は当該eventでは`ineligible`になる。欠損、未成熟、corporate action等による比較不能を失敗へ変換しない。

## 比較と判定

各仮説は、対象カテゴリの平均と同期間の全適格イベント平均を比較する。これはlegacy研究の `mean_return_delta_vs_overall` と同じ比較であり、対象カテゴリ自身も全体平均へ含む。

判定を開始する最低母数は固定する。

```text
target: 30 events
all eligible comparator: 30 events
```

母数到達前は`insufficient`、観測0件は`active`とする。

方向性仮説は、prospective平均差がhistoricalと同方向で、historical効果絶対値の50%以上なら`supported`、同方向だが50%未満なら`weakened`、方向が反転または0なら`rejected`とする。

`no_material_difference`は次の両方を満たせば`supported`とする。

```text
absolute mean return delta <= 0.5 percentage points
absolute positive-rate delta <= 5 percentage points
```

片方だけなら`weakened`、両方を外れれば`rejected`とする。

## 1件ごとの成功・失敗

方向性仮説では、対象カテゴリに該当したeventだけについて、期待方向と同符号なら成功、逆符号なら失敗、0ならneutralを記録する。非対象eventは全体比較には使うが、個別成功・失敗へ数えない。差が小さいという仮説は単一eventで判定できないため、個別成功・失敗を作らない。

## 正式ルールへの境界

`supported`は研究上の状態であり、production ruleへの昇格ではない。別の統治レビュー候補になる最低条件を次で固定する。

```text
target 50 events
all eligible comparator 50 events
distinct event quarters 2以上
supported evaluation 2回連続
```

条件到達後も自動昇格しない。今回の実装は常に次を維持する。

```text
automatic_weight_change = false
automatic_rank_rule_change = false
automatic_trading_rule_change = false
```

## 実行

台帳は固定sourceとの一致を確認できる。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli verify-hypothesis-registry \
  --knowledge outputs/historical_research/research_knowledge.json \
  --registry data/prospective_hypotheses/legacy_research_v1.json
```

イベント完了後は、正規化済み観測からevent単位のtrial fileを新規作成する。同じeventの再追記と既存fileの上書きは拒否する。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli evaluate-hypothesis-event \
  --registry data/prospective_hypotheses/legacy_research_v1.json \
  --observation completed_event.json \
  --trials-dir data/prospective_hypothesis_trials \
  --recorded-at 2026-09-30T18:00:00+09:00 \
  --output data/prospective_hypothesis_trials/EE-EXAMPLE.json
```

状態は全trialから別fileへ再計算する。状態snapshotも既存pathを上書きしない。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli summarize-hypothesis-registry \
  --registry data/prospective_hypotheses/legacy_research_v1.json \
  --trials-dir data/prospective_hypothesis_trials \
  --evaluated-at 2026-10-01T09:00:00+09:00 \
  --output outputs/prospective_hypotheses/status-20261001.json
```

## PR #50監査履歴

PR #50は独立監査を起動したが、利用上限により判定前に終了した。記録上は`独立監査未完了＋追加機械検証後にmerge`であり、`独立監査Pass`とは扱わない。この事実はPR #50を再監査する理由にはせず、同能力は完成として閉じる。
