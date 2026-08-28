## Legacy Research Note Digest

> **⚠ この成果物は、統計ガードを通っていない経路から生成されています。**
>
> `knowledge.py` には留保期間の分割も、寄り付き起点のリターンも、多重比較補正も
> 入っていません（`aggregation.py` と `publishing.py` にのみ入っています）。
> したがって下の「学習候補」は、254件全部・前日終値起点・補正なしで算出された
> 差分であり、統計的な所見ではありません。`potentially_favorable` /
> `potentially_unfavorable` というラベルは方向の候補であって、検証結果では
> ありません。
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
- dollar_environment=strongのD20は全体比平均差2.83%（n=52、limited）。
- rank=B+のD5は全体比平均差2.39%（n=65、descriptive）。
- reaction=フラットのD5は全体比平均差1.95%（n=67、limited）。
- reaction=GD継続のD20は全体比平均差-10.70%（n=25、limited）。
- reaction=GD継続のD5は全体比平均差-7.87%（n=54、limited）。

これらは次回検証用の学習候補であり、正式なスコア・売買ルールではない。
