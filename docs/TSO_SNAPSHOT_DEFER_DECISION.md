# TSO Snapshot Import Defer Decision

## Status

`Deferred`.

## Decision

TSO snapshot importとimport adapter実装を延期する。TSOはread-only external sourceのままとし、ERSからTSO_LOG、TSO設定、score、repositoryへ書き戻さない。

## Evidence from three pilots

Nintendo、Toyota、Olympic Groupの3社すべてで、TSO snapshotなしに次が成立した。

- company/event identity
- official KPIまたはforecast revisionの再現
- reconstructed hypothesis
- hindsight/temporal limitation
- candidate timeとsession uncertaintyの分離
- price/return未作成状態の理解
- index/hot Fast Read routing
- independent Fast Read Pass、metric再現100%、誤用0

TSO snapshotは企業理解やsource routingの成立条件ではなかった。

## 延期理由

1. 現在の目的は決算知識の再利用とprospective evidence運用の確立である。
2. TSOは別projectが所有するread-only sourceである。
3. TSO_LOG 29列にはmeaning、type、unit、mappingが`unknown`のfieldが残る。
4. `rank`、`side`等にはERSとの意味衝突がある。
5. snapshot導入はsource hash、mapping version、identity mapping、duplicate importを必要とし、結合度を上げる。
6. historical pilotにはprospective baseline lockがなく、当時のTSO値を後から結び付ける価値が限定的である。
7. prospective formal evidenceとprice referenceを先に成立させる方がlook-ahead防止に直接寄与する。
8. 3社でsnapshotの実需要が観測されなかった。

## Current boundary

```text
TSO signal_log.csv
        | read-only, no automatic sync
        v
future explicit ERS import adapter
        |
        v
tso_snapshot with source identity/hash/mapping version
```

禁止:

- ERSからTSO_LOG変更
- shared mutable CSVまたはsymlink
- automatic import/commit
- unknown fieldの強制変換
- TSO scoreの補正値をTSOへ返却
- source raw valueとERS interpretationの上書き混在

## 再検討条件

次をすべて、または実装に必要な組合せで満たした場合に新ADRを作る。

1. prospective eventでTSO当時状態との比較が具体的に必要になった。
2. TSO scoreと決算反応の相関分析を開始するHuman承認がある。
3. formal TSO import mapping contractが承認済み。
4. source row hash canonicalizationが確定済み。
5. `mapping_version` formatとmigration ruleが確定済み。
6. company/ticker/asset identity mappingが確定済み。
7. duplicate importとcorrectionのappend-only ruleが確定済み。
8. explicit read-only import adapter設計がreview済み。
9. prospective evidence/price workflowが先に運用確認済み。

## Future minimum contract

実装再検討時の最低field候補:

```text
source_repository_remote
source_commit_or_file_version
source_file_identifier
source_signal_id
source_row_hash
source_recorded_at
mapping_version
source_raw_value
ers_interpretation
company_id_or_unresolved_identity
imported_at
```

実際のTSO score列はformal mapping承認後に限定する。

## Consequence

当面、ERS/Vaultの決算研究はTSO snapshotなしで継続する。snapshot欠落をerrorにしない一方、TSO contextを参照したと主張するnoteでは欠落を明示する。延期は永久拒否ではなく、実需要とcontract成立を待つ境界判断である。
