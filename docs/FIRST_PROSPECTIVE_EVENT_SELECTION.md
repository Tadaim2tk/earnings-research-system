# First Prospective Event Selection

## Status

`Proposed`. 本書はselection criteriaだけを定義し、企業名やeventを確定しない。

## 目的

最初のprospective eventで、発表前baseline lock、formal evidence、時刻、price reference、Human reviewを無理なく実運用できるcaseを選ぶ。銘柄の話題性や結果予想の容易さではなく、監査可能性と手順検証可能性を優先する。

## 必須条件

| criterion | acceptance evidence |
| --- | --- |
| 発表予定日を事前確認可能 | company IR calendarまたはexchange一次情報 |
| baseline lock時間を確保 | 発表予定より十分前のHuman review slot |
| baseline lock契約を利用可能 | Acceptedの`ERS-ADR-0020`に基づくschema、validator、sample、testsが利用可能 |
| event lifecycle契約を利用可能 | `ERS-ADR-0021`承認後にstatus historyとcancelled／occurred gateが利用可能 |
| 公式資料へアクセス可能 | current company forecast/直近決算資料のURL |
| formal evidence登録可能 | source timing、entity relation、publisher/titleを記録可能 |
| event時刻を監査可能 | time-bearing primary metadataまたはunconfirmed時の安全な延期手順 |
| price sourceを合法利用可能 | license/storage/AI processing条件をHuman確認済み |
| price reference policy適用可能 | sessionに応じたraw unadjusted price候補がある |
| KPI/forecastが明確 | 主要3〜15項目程度を一次資料から定義可能 |
| 過度な企業複雑性がない | accounting/corporate actionでpilot目的が埋没しない |
| TSO snapshotなしで成立 | company/event/evidence captureにTSOを必須としない |
| Human review時間を確保 | baseline、evidence、event後reviewの担当時間がある |
| provider terms確認済み | raw/metadata/hash/derived valueの許容範囲を記録済み |
| postponement contingency準備済み | 延期・中止・訂正・撤回時にbaselineを保持して安全に停止・再reviewできる |

## 除外条件

- 突発開示または予定日直前でbaseline lock不能
- event時刻を監査できず、session不明がpilot主要目的を阻害
- raw/source利用条件が未確認
- licensed market consensusがないと仮説を作れない
- 複雑なsplit、merger、tender offer、上場廃止等がprice比較を支配
- IPO/上場直後で比較可能periodが不足
- M&A、事業再編、会計基準変更で通常決算比較が困難
- 多通貨、多segment、特殊会計が初回evidence workflow測定を過度に複雑化
- official sourceが安定URL/identifierを持たない
- Human reviewerを確保できない

## Selection scorecard

候補を0〜2で評価する。合計点だけで自動決定せず、必須条件と除外条件を先に適用する。

| dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| schedule certainty | unknown | date only | date/time primary metadata |
| source accessibility | unstable/blocked | partially accessible | stable official sources |
| evidence readiness | schema/policy gap | manual workaround | approved formal workflow |
| price readiness | unavailable/terms unknown | manual candidate | approved source and policy |
| KPI clarity | ambiguous | moderate | limited clear KPI set |
| company complexity | high | medium | low/moderate |
| Human capacity | unavailable | constrained | scheduled |
| corporate action risk | high | possible | none identified |

推奨候補は必須条件をすべて満たし、除外条件0、scorecard 12/16以上を暫定目安とする。

## Session coverage

first prospectiveはsessionの多様性よりevidence workflowの成功を優先する。before-open/intraday/after-closeのどれでもよいが、次を満たすcaseを選ぶ。

- event timeのprimary metadataが取得可能
- session ruleが明確
- price referenceをHumanが確認できる
- unavailable時にreturnを作らず停止できる

## Pre-selection checklist

```text
candidate_company
ticker
candidate_event
scheduled_date
scheduled_time_status
primary_calendar_source
pre_event_source_urls
formal_evidence_storage_mapping_ready
baseline_lock_contract_ready
event_lifecycle_contract_ready
license_review_status
price_source
price_reference_policy
corporate_action_check
expected_kpi_count
baseline_lock_deadline
human_reviewer
review_time_reserved
exclusion_flags
selection_score
decision
decision_reason
postponement_contingency
```

### Postponement contingency

`postponement_contingency` は最低限、次を事前確認して記録する。

- 発表延期時にHuman reviewを再実施できる。
- locked baselineを上書きせず、元のlock情報とlineageを保持できる。
- baselineが有効性を失った場合に、旧baselineを残したnew versionを作成できる。
- event中止時にscoring、calibration、通常のpost-event reviewから除外できる。
- 誤開示、撤回、訂正時に元evidenceを保持したappend-only correctionを扱える。

これらは選定時点の運用準備確認である。baseline version relationは [PROSPECTIVE_BASELINE_LOCK.md](PROSPECTIVE_BASELINE_LOCK.md) とAcceptedの `ERS-ADR-0020` に従う。`event_cancelled`相当のevent enumは別のschema decisionを必要とする。source撤回は既存 `verified_status: retracted` とAcceptedの `ERS-ADR-0019` correction lineageを使う。baseline contractの承認はprospective運用開始の自動承認ではない。

## Pilot success measures

- evidence registration time
- baseline creation/lock time
- Human review time
- source countとduplicate input
- missing fieldとschema friction
- event time/session判定
- price reference作成可否
- metric reproduction rate
- future leakage finding
- Fast Read loaded note countとmisuse count

## Decision gate

Humanがcandidate、evidence/price readiness、baseline deadlineを承認するまでCompany/Event noteを作らない。candidate選定とbaseline開始は別gateとし、candidateが不適切になった場合は理由を残して次候補へ移る。
