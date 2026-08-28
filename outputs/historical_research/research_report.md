# Legacy Earnings Research Knowledge

> **⚠ この成果物は、統計ガードを通っていない経路から生成されています。**
>
> `knowledge.py` には留保期間の分割も、寄り付き起点のリターンも、多重比較補正も
> 入っていません（`aggregation.py` と `publishing.py` にのみ入っています）。
> したがって下の差分は、254件全部・前日終値起点・補正なしで算出されたもので、
> 統計的な所見ではありません。`potentially_favorable` /
> `potentially_unfavorable` は方向の候補であって、検証結果ではありません。
>
> とくに `reaction` を `D5` / `D20` で評価している項目は、現在のコードが
> 「分類の定義が結果に入っている」として withhold する組合せです。
> この経路の是正は ERS-ADR-0045 の未対応事項として別PRに残しています。

## 境界

このレポートは旧OSの `legacy_observational` だけを記述集計した研究出力である。相関を因果、正式スコア、売買ルールとして扱わない。

## データ利用可能性

- 全記録: 254
- 銘柄数: 251
- 反復銘柄数: 3
- TSO snapshot数: 42
- D1: 利用可能 245 / 欠損 9 / 銘柄 242 / snapshot 41 / 実効母数 41
- D5: 利用可能 242 / 欠損 12 / 銘柄 239 / snapshot 39 / 実効母数 39
- D20: 利用可能 139 / 欠損 115 / 銘柄 137 / snapshot 25 / 実効母数 25

## Rank別

| rank | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 50 | 50 | 25 | -0.99% | 42.00% | limited | 21 | 13 | 2.11% | 47.62% | limited |
| B | 89 | 84 | 35 | -1.03% | 40.48% | descriptive | 49 | 21 | 0.26% | 44.90% | limited |
| B+ | 67 | 65 | 36 | 2.44% | 58.46% | descriptive | 35 | 22 | 5.45% | 60.00% | limited |
| B- | 3 | 3 | 2 | 1.09% | 66.67% | insufficient | 3 | 2 | 1.09% | 100.00% | insufficient |
| C | 13 | 12 | 11 | 1.35% | 58.33% | limited | 10 | 9 | 1.18% | 50.00% | insufficient |
| C+ | 28 | 27 | 25 | -1.05% | 48.15% | limited | 20 | 18 | -0.32% | 55.00% | limited |
| D | 1 | 1 | 1 | -1.86% | 0.00% | insufficient | 1 | 1 | -3.72% | 0.00% | insufficient |
| not_recorded | 3 | 0 | 0 | - | - | insufficient | 0 | 0 | - | - | insufficient |

## Narrative別

| narrative | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| not_recorded | 3 | 0 | 0 | - | - | insufficient | 0 | 0 | - | - | insufficient |
| 中立 | 135 | 129 | 34 | 0.57% | 51.94% | descriptive | 76 | 21 | 1.17% | 47.37% | limited |
| 整合 | 105 | 102 | 37 | -0.81% | 40.20% | descriptive | 53 | 23 | 2.59% | 56.60% | limited |
| 衝突 | 11 | 11 | 10 | 1.79% | 63.64% | limited | 10 | 9 | 2.62% | 60.00% | insufficient |

## Judge別

| judge | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| not_recorded | 3 | 0 | 0 | - | - | insufficient | 0 | 0 | - | - | insufficient |
| 即買い候補 | 21 | 21 | 15 | -2.03% | 47.62% | limited | 10 | 8 | 0.32% | 50.00% | insufficient |
| 押し目待ち | 35 | 35 | 23 | 1.64% | 48.57% | limited | 21 | 15 | 5.86% | 61.90% | limited |
| 監視 | 155 | 148 | 37 | 0.29% | 47.30% | descriptive | 81 | 23 | 1.94% | 49.38% | limited |
| 見送り | 40 | 38 | 25 | -1.22% | 47.37% | limited | 27 | 18 | -1.15% | 51.85% | limited |

## 株価反応別

| reaction | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GD反発 | 49 | 48 | 29 | -1.96% | 31.25% | limited | 26 | 18 | -0.08% | 38.46% | limited |
| GD継続 | 54 | 54 | 28 | -7.82% | 11.11% | limited | 25 | 15 | -8.88% | 8.00% | limited |
| GU失速 | 39 | 39 | 24 | 1.71% | 61.54% | limited | 23 | 15 | 5.25% | 69.57% | limited |
| GU継続 | 34 | 34 | 22 | 9.63% | 88.24% | limited | 20 | 13 | 10.80% | 80.00% | limited |
| not_recorded | 9 | 0 | 0 | - | - | insufficient | 0 | 0 | - | - | insufficient |
| フラット | 69 | 67 | 29 | 2.00% | 59.70% | limited | 45 | 19 | 3.11% | 62.22% | limited |

## 市場環境別

### risk_balance

| risk_balance | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| risk_off_dominant | 78 | 74 | 13 | 1.85% | 51.35% | limited | 48 | 9 | 4.94% | 58.33% | insufficient |
| risk_on_dominant | 176 | 168 | 26 | -0.74% | 45.83% | limited | 91 | 16 | 0.17% | 48.35% | limited |

### volatility_environment

| volatility_environment | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| high | 86 | 82 | 14 | 1.16% | 48.78% | limited | 48 | 9 | 4.94% | 58.33% | insufficient |
| low | 87 | 85 | 10 | -1.68% | 43.53% | limited | 69 | 8 | -0.48% | 46.38% | insufficient |
| middle | 81 | 75 | 15 | 0.78% | 50.67% | limited | 22 | 8 | 2.22% | 54.55% | insufficient |

### dollar_environment

| dollar_environment | records | d5 n | d5 units | d5 mean | d5 positive | d5 grade | d20 n | d20 units | d20 mean | d20 positive | d20 grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| middle | 82 | 80 | 11 | -0.53% | 42.50% | limited | 48 | 7 | 1.21% | 52.08% | insufficient |
| strong | 87 | 79 | 17 | 0.88% | 49.37% | limited | 52 | 13 | 4.65% | 63.46% | limited |
| weak | 85 | 83 | 11 | -0.19% | 50.60% | limited | 39 | 5 | -1.21% | 35.90% | insufficient |

## 組み合わせ別の探索結果

- `reaction_x_volatility` reaction=GD継続, volatility_environment=middle: D5 -5.64% (n=21, limited), D20 -9.26% (n=4, insufficient)。
- `rank_x_judge` rank=B+, judge=押し目待ち: D5 5.48% (n=13, limited), D20 8.97% (n=9, insufficient)。
- `reaction_x_risk_balance` reaction=GD継続, risk_balance=risk_on_dominant: D5 -6.74% (n=43, limited), D20 -7.66% (n=17, limited)。
- `reaction_x_risk_balance` reaction=GU継続, risk_balance=risk_on_dominant: D5 6.95% (n=22, limited), D20 6.51% (n=12, insufficient)。
- `rank_x_narrative` rank=B+, narrative=整合: D5 2.30% (n=32, limited), D20 6.12% (n=17, limited)。
- `reaction_x_volatility` reaction=フラット, volatility_environment=middle: D5 2.56% (n=18, limited), D20 5.58% (n=5, insufficient)。
- `narrative_x_risk_balance` narrative=中立, risk_balance=risk_off_dominant: D5 2.65% (n=36, limited), D20 5.57% (n=24, insufficient)。
- `reaction_x_risk_balance` reaction=フラット, risk_balance=risk_off_dominant: D5 3.30% (n=26, limited), D20 5.03% (n=19, insufficient)。
- `reaction_x_volatility` reaction=フラット, volatility_environment=high: D5 3.30% (n=26, limited), D20 5.03% (n=19, insufficient)。
- `rank_x_narrative` rank=B+, narrative=中立: D5 2.56% (n=33, limited), D20 4.82% (n=18, limited)。
- `rank_x_narrative` rank=B, narrative=整合: D5 -4.80% (n=21, limited), D20 -0.90% (n=15, limited)。
- `narrative_x_risk_balance` narrative=整合, risk_balance=risk_off_dominant: D5 0.94% (n=32, limited), D20 4.40% (n=18, insufficient)。
- `rank_x_judge` rank=A, judge=押し目待ち: D5 -0.16% (n=18, limited), D20 4.36% (n=9, insufficient)。
- `rank_x_judge` rank=B+, judge=監視: D5 1.89% (n=51, limited), D20 4.23% (n=26, limited)。
- `reaction_x_volatility` reaction=GD反発, volatility_environment=high: D5 -2.44% (n=17, limited), D20 3.09% (n=10, insufficient)。

組み合わせは探索用の記述結果であり、多変量効果や独立要因を意味しない。

## 高rank下落・低rank上昇

- D5 高rank下落: 56件。最多条件: narrative=整合 (41/56)。
- D5 低rank上昇: 22件。最多条件: narrative=中立 (15/22)。
- D20 高rank下落: 25件。最多条件: narrative=整合 (14/25)。
- D20 低rank上昇: 19件。最多条件: narrative=中立 (12/19)。

## 初動からD20への反転

- includes_zero: 4件
- negative_continuation: 53件
- negative_to_positive: 16件
- positive_continuation: 54件
- positive_to_negative: 12件
- unavailable: 115件

## 評価分類の履歴

- rank: 254件中、初回記録後に最終値が変わったもの 1件。
- narrative: 254件中、初回記録後に最終値が変わったもの 0件。
- judge: 254件中、初回記録後に最終値が変わったもの 0件。

## 学習候補

- `potentially_favorable`: reaction=GU継続 / D5 / 平均差 9.59% / 上昇率差 40.71% / n=34。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: reaction=GU継続 / D20 / 平均差 8.98% / 上昇率差 28.20% / n=20。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: judge=押し目待ち / D20 / 平均差 4.05% / 上昇率差 10.11% / n=21。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: rank=B+ / D20 / 平均差 3.63% / 上昇率差 8.20% / n=35。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: reaction=GU失速 / D20 / 平均差 3.44% / 上昇率差 17.77% / n=23。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: dollar_environment=strong / D20 / 平均差 2.83% / 上昇率差 11.66% / n=52。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: rank=B+ / D5 / 平均差 2.39% / 上昇率差 10.94% / n=65。prospectiveで再検証する候補であり、ルールではない。
- `potentially_favorable`: reaction=フラット / D5 / 平均差 1.95% / 上昇率差 12.18% / n=67。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: reaction=GD継続 / D20 / 平均差 -10.70% / 上昇率差 -43.80% / n=25。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: reaction=GD継続 / D5 / 平均差 -7.87% / 上昇率差 -36.41% / n=54。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: reaction=GD反発 / D5 / 平均差 -2.01% / 上昇率差 -16.27% / n=48。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: reaction=GD反発 / D20 / 平均差 -1.90% / 上昇率差 -13.34% / n=26。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: rank=B / D20 / 平均差 -1.56% / 上昇率差 -6.90% / n=49。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: rank=B / D5 / 平均差 -1.08% / 上昇率差 -7.04% / n=84。prospectiveで再検証する候補であり、ルールではない。
- `potentially_unfavorable`: rank=A / D5 / 平均差 -1.03% / 上昇率差 -5.52% / n=50。prospectiveで再検証する候補であり、ルールではない。
- `low_discrimination`: judge=監視 / D20 / 平均差 0.13% / 上昇率差 -2.42% / n=81。prospectiveで再検証する候補であり、ルールではない。
- `low_discrimination`: dollar_environment=weak / D5 / 平均差 -0.24% / 上昇率差 3.08% / n=83。prospectiveで再検証する候補であり、ルールではない。
- `low_discrimination`: judge=監視 / D5 / 平均差 0.24% / 上昇率差 -0.22% / n=148。prospectiveで再検証する候補であり、ルールではない。
- `low_discrimination`: rank=A / D20 / 平均差 0.29% / 上昇率差 -4.18% / n=21。prospectiveで再検証する候補であり、ルールではない。

## 解釈上の制約

- D1、D5、D20は利用可能件数が異なり、欠損は失敗として数えていない。
- 同一銘柄の反復を考慮し、銘柄均等平均も機械可読データに保持した。
- 小標本は `insufficient` または `limited` とし、強い結論を出さない。
- 市場環境変数は相関し得るため、単変量結果と組み合わせ結果を因果効果として合算しない。
- 自動weight変更、rank基準変更、売買ルール変更は生成していない。
