# 見込み仮説のtrial記録（追記専用）

`evaluate-hypothesis-event` が生成した trial bundle がここに入る。1イベント1ファイル、
上書きも削除もしない。

**現在0件**。committed registry の19仮説は現行のcontamination rulesで全件 invalid のため、
`is_usable` がすべて拒否する。証拠収集は、汚染を除いた研究から新versionの仮説を凍結して
から始まる。

このディレクトリが空であることには意味がある。ある仮説に最初の trial が入った瞬間、その
仮説の `StopRule` と `PromotionRule` は変更不能になる（`verify-rule-freeze`）。
`evaluation_started_at` はここのファイルから導出される値で、どこにも保存されない。
