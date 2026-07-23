# Obsidian Knowledge Model

## 基本分類

既存Research Labの `Facts / Hypotheses / Lessons` を上位taxonomyとして維持する。ERS固有note typeはtopicと責務を示し、claim classはnote内の各claimがraw fact、metric、interpretation等のどれかを示す。

```text
Raw Source
Observed Fact
Derived Metric
Analyst Interpretation
Hypothesis
Decision
Outcome
Knowledge Update
```

1つのnoteに複数claim classがある場合はsectionを分ける。タイトルやfrontmatterだけでfactとinterpretationを混同しない。

## Note type

共通required frontmatterは `note_type`, `note_id`, `status`, `confidence`, `verified_status`, `created_at`, `updated_at`, `knowledge_version` とする。

| note_type | purpose | additional required_frontmatter | recommended_sections | allowed_links | ERS_reference | review_status | update_trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `company` | 企業固有の長期知識 | `company_id`, `ticker`, `market` | Facts、Patterns、Risks、Open Questions | event、industry、peer、KPI、pattern | `company_master.company_id` | draft以上 | 新決算、社名/ticker変更 |
| `earnings_event` | 1イベントの知識view | `earnings_event_id`, `company_id` | Pre-event、Disclosure、Outcome、Lessons | company、KPI、hypothesis、source | `earnings_event_id` | draft以上 | baseline、発表、各review horizon |
| `management_guidance_pattern` | 会社予想の癖を仮説化 | `company_id`, `sample_event_ids` | Observations、Competing Explanations、Failure Conditions | company、event、validated finding | evidence/event IDs | reviewed以上推奨 | 新しいguidanceと実績 |
| `industry` | 業種固有の構造 | `industry_id` | Drivers、KPI、Cycles、Risks | company、peer、KPI、sector driver | optional | reviewed以上推奨 | sector event、定義変更 |
| `sector_driver` | 外部driverと伝播経路 | `driver_id`, `scope` | Mechanism、Indicators、Lag、Invalidation | industry、company、hypothesis | evidence IDs | draft以上 | macro/sector evidence |
| `customer_industry` | 顧客業種の需要連鎖 | `industry_id` | Demand Chain、Lead Indicators、Exceptions | company、industry、KPI | optional | draft以上 | 顧客業種決算 |
| `peer_group` | 比較対象と除外理由 | `peer_group_id`, `member_company_ids` | Inclusion、Exclusion、Comparability | company、industry、KPI | company IDs | reviewed以上推奨 | member/事業構成変更 |
| `kpi` | KPI定義と企業差 | `kpi_id`, `unit_policy` | Definition、Formula、Company Variants、Pitfalls | company、industry、source | `kpi_observation.kpi_name` | reviewed以上推奨 | 定義・開示方法変更 |
| `accounting_quality` | 利益の質と会計論点 | `scope` | Facts、Adjustments、Cash Flow、Risks | company、event、KPI、source | evidence IDs | draft以上 | 開示、訂正、監査事項 |
| `value_trap` | 割安放置理由の仮説 | `scope`, `sample_company_ids` | Symptoms、Mechanism、Counterexample | company、failure mode、hypothesis | company/event IDs | reviewed以上推奨 | thesis検証、資本政策変更 |
| `market_expectation` | 市場が織り込む期待 | `company_id`, `as_of` | Observed Facts、Interpretation、Alternatives | event、attention、hypothesis | baseline/evidence IDs | draft | baseline作成・lock |
| `attention_pattern` | SNS/meme等の注目状態 | `scope`, `as_of` | Source Limits、Signals、Interpretation | company、event、failure mode | evidence IDs | draft | attention snapshot |
| `price_reaction_pattern` | event後反応の反復性仮説 | `scope`, `reference_policy` | Cohort、Raw/Adjusted Basis、Exceptions | event、company、validated finding | review IDs | reviewed以上推奨 | return horizon到達 |
| `hypothesis` | 検証可能な解釈 | `hypothesis_id`, `invalidation` | Thesis、Evidence、Protocol、Review History | company、event、protocol、source | `hypothesis_log.hypothesis_id` | draft以上 | new evidence、review due |
| `decision_rule` | 人間承認済み判断rule候補 | `rule_id`, `scope` | Preconditions、Rule、Exceptions、Evidence | failure mode、finding、ADR | ADR/score version | reviewed以上必須 | policy review |
| `failure_mode` | 誤り方と再発条件 | `failure_mode_id` | Trigger、Observed Failure、Detection、Mitigation | event、hypothesis、rule | event/review IDs | reviewed以上推奨 | invalidation、audit finding |
| `validated_finding` | 反復review済みlesson | `finding_id`, `supporting_event_ids` | Claim、Evidence、Scope、Known Limits | company、industry、failure mode | evidence/review IDs | validatedのみ | contradicting evidence、scheduled review |
| `open_question` | 未解決knowledge gap | `question_id`, `owner` | Question、Why It Matters、Needed Evidence | any domain note | optional | draft/reviewed | answer、priority変更 |
| `data_source` | sourceの意味・利用条件 | `source_id`, `license_status` | Coverage、Timing、Terms、Limitations | source notes、workflow | evidence source fields | reviewed以上推奨 | terms/API変更 |
| `tool_workflow` | 再現可能な運用知識 | `workflow_id`, `owner` | Inputs、Steps、Checks、Rollback | data source、audit | commit/ADR | reviewed以上推奨 | process変更 |
| `reconstruction_limitation` | retrospective pilotの制約 | `earnings_event_ids` | Limitation、Impact、Allowed Use | event、failure mode、open question | pilot/event IDs | reviewed以上推奨 | schema/policy決定 |

## Claim昇格rule

- `Observed Fact`: sourceとpublished/observed時刻が必要。
- `Derived Metric`: input、formula、basis、calculated_atが必要。
- `Analyst Interpretation`: factと明確に分け、competing explanationを残す。
- `Hypothesis`: invalidationとreview triggerが必要。
- `Decision`: 人間承認またはERS ADR/PRが必要。
- `Outcome`: eventとmeasurement policyが必要。
- `Knowledge Update`: prior version、変更理由、reviewerが必要。

「保守的予想型」「ビッグマウス」「value trap」は初期状態でinterpretationまたはhypothesisとする。複数事例があっても自動的にfactへ変えない。

