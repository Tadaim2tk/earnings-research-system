# Obsidian Frontmatter Policy

## 暫定仕様

新規ERS noteではYAML frontmatterをfile先頭に置く。既存TSO templateには見出し後にYAML blockを置く形式もあるため、本policyを既存Vault全体へ遡及適用しない。統一する場合は別のmigration reviewを行う。

```yaml
---
note_type: company
note_id: ERS-COMPANY-7974
knowledge_class:
  - fact
  - interpretation
company_id: CMP-7974
ticker: "7974"
market: TSE
status: draft
confidence: medium
verified_status: mixed
created_at: 2026-07-23
updated_at: 2026-07-23
last_reviewed_at:
reviewed_by: []
source_evidence_ids:
  - EVD-XXXX
earnings_event_ids:
  - EVT-XXXX
related_note_ids: []
ers_commit:
  - 5a2393e
knowledge_version: 1
---
```

## Required field

| key | type | rule |
| --- | --- | --- |
| `note_type` | controlled string | `OBSIDIAN_KNOWLEDGE_MODEL.md` のtype |
| `note_id` | stable string | pathやtitleから独立。一度発行したIDを再利用しない |
| `knowledge_class` | list | note内に存在するclaim classを列挙 |
| `status` | enum | `draft`, `reviewed`, `validated`, `deprecated` |
| `confidence` | enum | `low`, `medium`, `high`, `unknown` |
| `verified_status` | enum | `unverified`, `mixed`, `verified`, `not_applicable` |
| `created_at` | date | 初回作成日。遡及しない |
| `updated_at` | date | content変更日 |
| `source_evidence_ids` | list | source不要typeは空listを許容 |
| `ers_commit` | list | 正式採用・参照commit。未採用は空list可 |
| `knowledge_version` | integer | semantic change時にincrement |

type別entity IDは追加requiredとする。例としてCompanyは `company_id`、Earnings Eventは `earnings_event_id`、Hypothesisは `hypothesis_id` を持つ。

## Status transition

```text
draft -> reviewed -> validated -> deprecated
  |         |            |
  +-------> deprecated <-+
```

- `reviewed`: 構造、source、claim classを人間または独立reviewerが確認した状態。
- `validated`: 定義済みscopeで再利用可能と人間が承認した状態。
- `deprecated`: 古い、反証済み、置換済み。削除せずreplacementと理由を残す。
- `deprecated -> validated` の直接復帰は禁止し、新versionまたは新noteで再評価する。

## `status` と `verified_status` の違い

`status` はnoteのreview lifecycle、`verified_status` は含まれるfactual claimの検証状態である。よく整理された仮説は `status: reviewed` になり得るが、仮説そのものを `verified_status: verified` にしない。

## Validated gate

`status: validated` には次を要求する。

- 少なくとも1つのERS `source_evidence_id` または承認済み外部source ID
- `last_reviewed_at` と `reviewed_by`
- scopeとknown limitations
- competing evidenceまたは「確認できなかった」記録
- 対応するERS IDまたは、ERS非対象である明示理由
- Git commit/PRなど変更履歴

出典不明、AI生成のみ、SNS単独のclaimはvalidatedにしない。

## Claim section

混在noteは本文を次の見出しで分離する。

```text
## Observed Facts
## Derived Metrics
## Analyst Interpretation
## Hypotheses
## Decisions
## Outcomes
## Knowledge Updates
```

AI生成文にはsourceを付けても自動でObserved Factとしない。source内容とAI解釈を別sectionに置く。

## 更新と履歴

- 誤った仮説を削除せず `deprecated` にする。
- `knowledge_version` を上げ、変更理由とreplacement noteを記録する。
- event後の知識でevent前noteを上書きしない。Outcome/Knowledge Updateへappendする。
- `created_at`, source published time、ERS `recorded_at` を混同しない。
- ticker/社名変更はstable `company_id` を維持しalias履歴を追加する。
