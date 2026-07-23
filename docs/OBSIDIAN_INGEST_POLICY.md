# Obsidian Ingest Policy

## 原則

`.raw/` は無条件の保存箱ではない。sourceごとに保存権限、個人情報、secret、第三者共有、Git可否を判定し、許可できない場合はURL、metadata、hash、短い要約だけを残す。

Raw Source、Observed Fact、Derived Metric、Interpretationを同じfileへ上書き統合しない。rawは不変、抽出結果はversioned、knowledge noteはreview対象とする。

## Source別policy

| source type | `.raw/` local | Git | knowledge note | special rule |
| --- | --- | --- | --- | --- |
| TDnet disclosure | terms/copyright確認後 | 原則no | metadata、短い要約、evidence ID | actual disclosure datetimeを保持 |
| company IR PDF | personal research範囲を確認 | 原則no | URL、title、published time、要約 | official sourceでも転載権とは別 |
| EDINET document | terms確認後 | 原則no | filing ID、URL、要約 | XBRL/PDFの別を記録 |
| earnings presentation | terms/copyright確認後 | 原則no | page referenceと要約 | slide image大量保存を避ける |
| peer company results | company IRと同じ | 原則no | peer relationと比較可能性 | accounting/period差を明記 |
| paid news | no unless licensed | no | URL、headline、独自要約 | paywall本文を保存しない |
| free news | terms確認後 | 原則no | URL、短い引用、要約 | 記事全文を複製しない |
| SNS post | bulk raw禁止 | no | post ID、time、短い要約 | factでなくattention/sentiment材料 |
| message board / Minkabu | terms確認前no | no | URL、observed time、aggregate interpretation | comment本文の大量保存禁止 |
| J-Quants price data | human terms review前no | no | source statusのみ | raw、screenshot、derived値も確認待ち |
| Claude audit | yes if user-owned output | private repo可 | audit findingとreview status | market evidenceではなくprocess review |
| ChatGPT design decision | yes if user-owned output | private repo可 | proposalとして保存 | ADR採用前はofficial decisionにしない |
| Codex implementation report | yes | yes | commit、tests、limitations | Git execution truthを優先 |
| human observation | yes | private repo可 | author、observed_at、confidence | sourced factと分離 |

## Raw保存判定

次を全て満たす場合だけ原文をlocal `.raw/` へ置く。

1. sourceを取得する権限がある。
2. local long-term storageが許可される、または保存期間を明示できる。
3. agent処理が許可される。
4. personal data、credential、API keyを含まない。
5. Git statusとbackup destinationを把握している。
6. deletion/retention ruleがある。

1つでも不明なら `license_status: unknown` とし、URL/source metadataのみを保存する。

## Source manifest

raw fileごとに次を記録する。

```yaml
source_id: SRC-<hash-prefix>
source_type: company_ir
source_url: https://example.invalid/document.pdf
publisher: Example Corp
published_at: 2026-07-23T15:30:00+09:00
observed_at: 2026-07-23T15:31:00+09:00
ingested_at: 2026-07-23T16:00:00+09:00
content_sha256: "..."
license_status: unknown
raw_storage_allowed: false
git_allowed: false
retention_until:
ers_evidence_id: EVD-XXXX
```

manifest自体にsource本文やsecretを含めない。

## 重複防止

- bytesを保存できる場合はSHA-256をprimary dedup keyにする。
- URLのみの場合はnormalized URL、publisher、published_at、document IDを組み合わせる。
- 同じdocumentの言語版・訂正版は別source IDとしrelationを付ける。
- correctionをoriginalへ上書きせず、`corrects_source_id` を記録する。
- title一致だけでduplicate判定しない。

## 原文削除

license、retention、privacy理由でrawを削除しても、許可される範囲で次を残す。

- source ID
- URL/document identifier
- publisherとpublished time
- content hash
- 独自要約
- extraction version
- deletion date/reason

削除済みrawをAIが読めるように見せない。

## 個人情報とSNS

- 個人名、handle、位置情報、private messageを必要以上に保存しない。
- SNSは市場attentionの観測であり、企業業績のverified factではない。
- bot、削除、編集、時刻、sampling biasをlimitationsへ記録する。
- 個別投稿から人格や投資能力を断定しない。

## Ingest flow

```text
source candidate
  -> rights/privacy check
  -> source ID/hash
  -> raw or metadata-only保存
  -> fact/metric候補抽出
  -> interpretation分離
  -> link候補生成
  -> human review
  -> index更新
```

AIは既存noteの本文を自動上書きせず、patchまたは候補差分を提示する。

