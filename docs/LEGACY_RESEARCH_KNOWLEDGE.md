# Legacy Research Knowledge

## 目的

旧 `earnings-research-os` から移行した254件を、正式なprospective recordへ昇格させず、再現可能な記述集計と学習候補へ変換する。

入力は次に限定する。

- `record_mode=legacy_observational` の254件
- 各recordへpoint-in-timeで結合済みのTSO historical context
- 旧OSに保存された `ret_d1` / `ret_d5` / `ret_d20`
- `rank` / `narrative` / `judge` のGit履歴

## 出力

`outputs/historical_research/` に次を生成する。

| file | role |
|---|---|
| `research_knowledge.json` | 機械可読な全集計、例外、反転、学習候補 |
| `research_report.md` | 人間が読む研究レポート |
| `weekly_research_digest.md` | weekly reportへ組み込める短縮版 |
| `note_research_digest.md` | note下書きへ組み込める短縮版 |

旧出力とのbyte parityを保持する `weekly_report.md` と `note_draft.md` は変更しない。新しいdigestを別ファイルにすることで、移行検証済みの旧出力と研究知識を混同しない。

## 母数と欠損

D1、D5、D20は各期間で次を必ず保存する。

- 利用可能件数
- 欠損件数
- 利用可能な銘柄数
- 平均、中央値、上昇率
- 銘柄均等平均
- TSO snapshot均等平均
- 反復観測数

欠損は0、下落、失敗へ変換しない。現在の固定datasetではD1 245件、D5 242件、D20 139件であり、各期間を同じ254件として表示しない。

## 反復銘柄

254件は251銘柄であり、3銘柄が2回ずつ現れる。またTSO historical sourceの88 snapshotのうち、254件との結合で実際に使われた異なるsnapshotは42個であり、複数recordが同じ市場局面を共有する。全集計は観測単位の平均に加えて、銘柄ごとの平均を一度ずつ集計する `ticker_balanced_mean_return` と、snapshotごとの平均を一度ずつ集計する `context_balanced_mean_return` を保持する。254件を254社・254市場局面の独立標本とは扱わない。

## 小標本

利用可能な異なる銘柄数とTSO snapshot数の小さい方を実効母数とし、表示を固定する。

| distinct tickers | sample_grade | permitted interpretation |
|---:|---|---|
| 0-9 | `insufficient` | 数値の表示だけ。学習候補へ使わない |
| 10-29 | `limited` | 仮説候補。強い結論を出さない |
| 30+ | `descriptive` | 記述的傾向。因果とはしない |

## 市場環境

`risk_on_score` と `risk_off_score` は相対優位だけを表示し、TSOのregimeやsignalと呼ばない。volatilityとdollarは同dataset内の三分位で低・中・高を分け、閾値も出力へ保存する。

市場変数同士は相関し得る。単変量表と組み合わせ表は探索用であり、独立した多変量効果とは解釈しない。回帰モデルやweight最適化は実施しない。

## 評価内容

次を個別に保存する。

- rank / narrative / judge / reaction別
- risk balance / volatility / dollar別
- rank x narrativeなどの組み合わせ
- 高rank下落と低rank上昇
- D1からD20の符号反転・継続
- rank / narrative / judgeが初回記録後に変わった件数
- 月別drift確認

旧分類の時点保証はprospectiveほど強くない。`classification_lineage` は変更の有無を示すが、旧評価基準が全期間で同一だったとは主張しない。

`reaction` は旧コード上、翌営業日の寄付きから引けまでの動きで `GU継続`、`GU失速`、`GD反発`、`GD継続`等を分類している。したがってreactionとD5／D20の集計は、事前予測力ではなく初動後の継続・反転を記述するものとして扱う。

## 学習候補

学習候補は全体平均との差と上昇率差から機械的に抽出する。ただし出力は常に次の境界を持つ。

```text
measurement
-> hypothesis generation
-> prospective validation candidate
```

次は生成しない。

- scoring weight変更
- rank基準変更
- 売買ルール
- TSOへの書き戻し
- causal claim

## 再生成と検証

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli analyze-legacy-research \
  --input-root data/historical_research/earnings_research_os/v1 \
  --output-dir outputs/historical_research

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli verify-legacy-research \
  --input-root data/historical_research/earnings_research_os/v1 \
  --output-dir outputs/historical_research
```

検証は固定入力から4出力を再構築し、byte単位で一致することを確認する。
