# このディレクトリの成果物について

**二種類が混在しています。片方は現行コードが生成したもの、もう片方はそうではありません。**

注記が冒頭に入っているのは Markdown の6ファイルだけです。`aggregation_summary.json` は
`superseded_note` キーで、`research_knowledge.json` と `publishing_parity.json` は
注記を持ちません。とくに `research_knowledge.json` は凍結レジストリに SHA-256 で
束縛されており、**1バイトでも足すと `verify-hypothesis-registry` が失敗する**ことを
実測で確認しています。そのための場所がここです。

## 二つの由来がある

**公開レポート（現行コードの出力）** — `dashboard.md` / `weekly_report.md` /
`note_draft.md` / `aggregation_summary.json`

**2026-08-29 に再生成しました。** 留保期間の分割、寄り付き起点のリターン、
Benjamini-Hochberg 補正がすべて入っています。冒頭に「917件の比較を補正した結果、
統計的に主張できる項目は0件」が出ます。

以前ここには「再生成できない」と書いてありました。`migrate-legacy-os` が
`decision_cutoff` 検証に阻まれていたためですが、**その検証が誤っていました**。
UTC の暦日で `cutoff.date() >= event_date` を比較しており、254件すべてが持つ
`イベント日 00:00:00 UTC`（= 09:00 JST、寄り付き）を「発表後」として弾いていました。
決算開示は 15:00 JST 以降なので、実際には6時間以上前です。市場が反応し得る最初の
瞬間（寄り付き）との比較に直しました。ERS-ADR-0056。

なお `publishing_parity.json` は退役システムの renderer が自分の出力を byte 単位で
再現することの記録で、こちらは変わっていません。

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

探索165件・917比較を Benjamini-Hochberg で補正した結果、**統計的に主張できる項目は
0件**です（`directional` 0 / `distinguishable` 0）。生成される `dashboard.md` は
その一文から始まります。
