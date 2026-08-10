# Baseline Carryover Context

`prepare-baseline-carryover` は、過去の `post_event_learning_review` を次回baseline作成者が読むための1つのJSON recordへ集約する。文字列はそのまま持ち越し、出現review数とsource review／eventを明示する。一般化や昇格は行わない。

```bash
python -m earnings_research.cli prepare-baseline-carryover \
  --review path/to/review-1.json --review path/to/review-2.json \
  --target-event-id EVT-FICTIONAL-NEXT-001 \
  --prepared-at 2027-06-01T09:00:00+09:00 \
  --output path/to/new-carryover.json
```

## 境界

1. 人間向け参考材料のみであり、scoring・判定へ自動反映しない。3つのgovernance flagは常にfalse。
2. 1件から一般化せず、出現回数だけを記録する。独立3イベントによる昇格工程は実装しない。
3. `reviewed_at` と全source `recorded_at` が `prepared_at` より後なら拒否する。異なるeventは同一企業のreviewだけを許可し、`source_event_ids` を明示する。
4. 出力はappend-onlyで、既存pathを上書きしない。入力reviewは変更しない。
5. 空項目は空配列のまま保持し、説明を推測・作文しない。
6. TSO、TSO_LOG、Vault、scoring weight、registryには触れない。
7. 外部networkへアクセスしない。
