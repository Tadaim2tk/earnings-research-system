## Legacy Research Weekly Digest

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

対象はlegacy_observational 254件。D1 245件（実効41）、D5 242件（実効39）、D20 139件（実効25）を利用した。

- reaction=GU継続のD5は全体比平均差9.59%（n=34、limited）。
- reaction=GU継続のD20は全体比平均差8.98%（n=20、limited）。
- judge=押し目待ちのD20は全体比平均差4.05%（n=21、limited）。
- rank=B+のD20は全体比平均差3.63%（n=35、limited）。
- reaction=GU失速のD20は全体比平均差3.44%（n=23、limited）。

これらは次回検証用の学習候補であり、正式なスコア・売買ルールではない。
