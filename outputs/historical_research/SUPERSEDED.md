# このディレクトリの成果物について

**ここにある数字は、現在のコードが到達する結論と一致しません。** 各ファイルの冒頭にも
同じ注記がありますが、`research_knowledge.json` だけは凍結レジストリに SHA-256 で
束縛されており、1バイトでも足すと `verify-hypothesis-registry` が失敗するため、
ファイル自体には何も書けません。そのための場所がここです。

## 二つの由来がある

**移行成果物** — `dashboard.md` / `weekly_report.md` / `note_draft.md` /
`aggregation_summary.json` / `publishing_parity.json`

退役した earnings-research-os が公開していたものを再現した記録です。生成時点では
留保期間の分割も、寄り付き起点のリターンも、多重比較補正もありませんでした。
とくに `dashboard.md` の「初動分類別」は、分類に使ったギャップ自体を成果として
数え直しています。同じ254件を寄り付き起点で測ると **GU +5.8% → -0.4%、
GD -5.3% → +0.5%** と符号が反転します。

再生成は現在できません。`migrate-legacy-os` が PR #53 で追加された
`decision_cutoff` 検証に阻まれ、凍結ソースを受け付けないためです（ERS-ADR-0045
の未対応事項）。

**`knowledge.py` の出力** — `research_knowledge.json` / `research_report.md` /
`note_research_digest.md` / `weekly_research_digest.md`

こちらは古い成果物ではなく、**現在のコードが今も生成するもの**です。ただし
`knowledge.py` には留保期間の分割も、寄り付き起点も、多重比較補正も入っていません
（それらは `aggregation.py` と `publishing.py` にしかありません）。つまり
「規律を一箇所に入れて、別の経路に効いているか確かめていなかった」という、この
リポジトリが繰り返してきた失敗形がここに残っています。

`research_knowledge.json` の `learning.next_hypotheses` にある
`potentially_favorable` / `potentially_unfavorable` は**方向の候補**であって、
検証を通過した所見ではありません。

## 凍結済み19仮説への影響

`data/prospective_hypotheses/legacy_research_v1.json` は上記
`research_knowledge.json` に SHA-256 で束縛されています。したがって19仮説は、
留保期間を含む254件・前日終値起点・補正なしの分析から作られています。

うち8件は `reaction` を `ret_d5` / `ret_d20` で評価しており、これは現在のコードが
`lookahead.contamination()` で「分類の定義が結果に入っている」として withhold する
組合せです。

これらを削除する予定はありません。**なぜその仮説を作ったか、なぜ後で無効と分かったか**
は研究履歴として残す価値があり、汚染を見逃した経路を後から検証するための標本でも
あります。無効化は新しいレジストリversionとして積む形で行います（ERS-ADR-0045
の未対応事項）。

## 現在のコードが到達する結論

探索165件・827比較を Benjamini-Hochberg で補正した結果、**統計的に主張できる項目は
0件**です（`directional` 0 / `distinguishable` 0）。生成される `dashboard.md` は
その一文から始まります。
