# Obsidian Frontmatter Policy

## 正本

本書をERS domain noteの共通frontmatter、`knowledge_class`、`origin_mode`、status transitionの唯一の正本とする。他文書は本書を参照し、同じenumや共通field一覧を再定義しない。

新規ERS noteではYAML frontmatterをfile先頭に置く。既存TSO templateには見出し後にYAML blockを置く形式もあるため、本policyを既存Vault全体へ遡及適用しない。統一する場合は別のmigration reviewを行う。

```yaml
---
note_type: company
note_id: ERS-COMPANY-7974
knowledge_class:
  - observed_fact
  - interpretation
origin_mode: historical_reconstruction
reconstructed_at: 2026-07-23
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
| `knowledge_class` | list | 本書のformal enumから、note内に存在するclaim classを列挙 |
| `origin_mode` | enum | `prospective`, `historical_reconstruction`, `synthetic` |
| `reconstructed_at` | date or datetime | `historical_reconstruction` では必須。それ以外は空欄可 |
| `status` | enum | `draft`, `reviewed`, `validated`, `deprecated` |
| `confidence` | enum | `low`, `medium`, `high`, `unknown` |
| `verified_status` | enum | `unverified`, `mixed`, `verified`, `not_applicable` |
| `created_at` | date | noteを実際に初回作成した日。遡及しない |
| `updated_at` | date | content変更日 |
| `source_evidence_ids` | list | source不要typeは空listを許容 |
| `ers_commit` | list | 正式採用・参照commit。未採用は空list可 |
| `knowledge_version` | integer | semantic change時にincrement |

type別entity IDは追加requiredとする。例としてCompanyは `company_id`、Earnings Eventは `earnings_event_id`、Hypothesisは `hypothesis_id` を持つ。

## `knowledge_class` enum

formal enumは次の8値だけとし、表記揺れや別名を認めない。

```text
raw_source
observed_fact
derived_metric
interpretation
hypothesis
decision
outcome
knowledge_update
```

## `origin_mode`

- 通常の将来eventについて、当時利用可能な情報をその時点で記録するnoteは `prospective` とする。
- Nintendo、Toyota、Olympic Groupの過去caseを現在作成するpilot noteは `historical_reconstruction` とする。
- 架空企業や検証用の作例は `synthetic` とする。
- `historical_reconstruction` は実際の作成・再構成時刻を `reconstructed_at` に記録する。
- `created_at` やERS `recorded_at` を過去へ偽装せず、source published timeとも混同しない。
- `historical_reconstruction` はprospective calibration cohortおよびprospective context packから除外する。
- `historical_reconstruction` をlive decision record、発表前にlock済みの正式baseline、または実運用実績として扱わない。

## Status transition

```text
draft -> reviewed -> validated -> deprecated
  |         |            |
  +-------> deprecated <-+
```

- `draft`, `reviewed`, `validated`, `deprecated` のすべてのstatus変更はHumanだけが承認する。
- AIは変更案、根拠、patch previewを提示できるが、Human承認前にfrontmatterのstatusを変更しない。
- `draft -> reviewed` はHuman reviewerが構造、source、claim classを確認して承認する。
- AIによるreviewだけでは、いずれのstatusにも変更できない。
- `validated` は下記gateを満たしたうえでHumanが承認する。
- `deprecated` は古い、反証済み、または置換済みのnoteに使い、削除せずreplacementと理由を残す。
- deprecated noteの再利用・復帰はHuman承認と理由を必須とする。直接復帰ではなく、新versionまたは新noteで再評価する。

## `status` と `verified_status` の違い

`status` はnoteのreview lifecycle、`verified_status` は含まれるfactual claimの検証状態である。よく整理された仮説は `status: reviewed` になり得るが、仮説そのものを `verified_status: verified` にしない。

## Validated gate

すべての `status: validated` に次を要求する。

- 少なくとも1つのERS `source_evidence_id` または承認済み外部source ID
- `last_reviewed_at` とHumanを示す `reviewed_by`
- scopeとknown limitations
- 対応するERS ID、またはERS非対象である明示理由
- Git commit/PRなど変更履歴
- Humanによる昇格承認

単一eventに限定したclaimは、次をすべて満たす場合にevent scopeでvalidatedにできる。

- event scopeが明記されている。
- primary source、または信頼できるprice sourceへ追跡できる。
- published/observed/calculated時刻が記録されている。
- claimが `observed_fact`、またはinput・formula・basisを再現できる `derived_metric` である。
- Humanがscopeとevidenceを確認して承認している。

反復patternや一般化claimには、pilot期間の暫定ruleとして3件以上の独立eventを要求する。対象は少なくとも `management_guidance_pattern`、`price_reaction_pattern`、一般化した `validated_finding` を含む。

- 3件未満は `reviewed` を上限とし、scopeを限定して `provisional` または `hypothesis` と明示する。
- 一般化したfindingにはsupporting event、counterexample searchの対象範囲と結果（見つからなかった場合も含む）、applicable scope、invalidationを記録する。
- 3件という閾値はpilot用の暫定基準であり、pilot後に観測結果からcalibrateする。恒久的な十分条件ではない。

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

見出しは可読性のための表示名であり、frontmatterでは必ず上記formal enumを使う。AI生成文にはsourceを付けても自動で `observed_fact` としない。source内容とAI解釈を別sectionに置く。

## 更新と履歴

- 誤った仮説を削除せず `deprecated` にする。
- `knowledge_version` を上げ、変更理由とreplacement noteを記録する。
- event後の知識でevent前noteを上書きしない。Outcome/Knowledge Updateへappendする。
- ticker/社名変更はstable `company_id` を維持しalias履歴を追加する。ただし上場廃止・再上場等でentity continuityが不明な場合はHuman確認まで旧IDを再利用しない。
