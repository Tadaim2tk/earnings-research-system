# Three-company Historical Reconstruction Pilot Review

## 目的

Nintendo、Toyota、Olympic Groupの3社pilotを横断し、Obsidian knowledge layerの再利用性能、安全性、入力負荷を評価する。本書は個別企業の内容を再評価するものではなく、次のprospective運用へ進む前の設計根拠をまとめる。

## 評価範囲

- Vault repository: `maruyama-ai-research-lab`
- ERS reference commit: `a68625c`
- 対象は3社18件のcompany-pilot note。`index.md`と`hot.md`はrouting/cacheとして別集計する。
- 作成時間はagent-assisted wall-clockであり、Human hand-entry時間ではない。
- Fast Read時間が計測されていないcaseは推測せず `not_measured` とする。

## 関連設計文書

- [Obsidian Frontmatter Generator Specification](./OBSIDIAN_FRONTMATTER_GENERATOR_SPEC.md)
- [Obsidian Workflow Note Type Split](./OBSIDIAN_WORKFLOW_NOTE_TYPE_SPLIT.md)
- [Prospective Evidence Pilot Policy](./PROSPECTIVE_EVIDENCE_PILOT_POLICY.md)
- [Obsidian Cache Staleness Policy](./OBSIDIAN_CACHE_STALENESS_POLICY.md)
- [TSO Snapshot Import Defer Decision](./TSO_SNAPSHOT_DEFER_DECISION.md)
- [First Prospective Event Selection](./FIRST_PROSPECTIVE_EVENT_SELECTION.md)
- [Decisions](./DECISIONS.md)

## 横断比較

| company | ticker | event_type | session_candidate | notes_created | creation_time | fast_read_notes | fast_read_result | metric_count | metric_reproduction_rate | misuse_count | wikilink_growth | index_growth | hot_growth | common_frontmatter_occurrences | company_specific_decisions | formal_evidence_status | tso_snapshot_status |
| --- | --- | --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: | --- | --- | --- |
| Nintendo | 7974 | `earnings_release` | after-close candidate; 15:30 unconfirmed | 6 domain/pilot notes; initial change also created index/hot | 21.0 min | 3主要noteで成立、全8note読込を回避 | Pass | 11 KPI | 100% (11/11) | 0 | 35 in pilot notes + 1 Hub link | initial creation; comparable deltaなし | initial creation; comparable deltaなし | 90 normalized across 6 notes | Nintendo固有KPI、15:30未確認、FY2026情報を仮説から隔離 | unregistered | not acquired |
| Toyota | 7203 | `earnings_release` | intraday candidate; 13:55 unconfirmed | 6 | 7.1 min | 3主要noteで概要成立、Company/Source常時読込不要 | Pass | 13 KPI | 100% (13/13) | 0 | +36 net | +13 lines / +1,230 bytes | +9 lines / +800 bytes | 90 | IFRS、vehicle sales、currency assumptions、13:55と説明会開始時刻の分離 | unregistered | not acquired |
| Olympic Group | 8289 | `earnings_forecast_revision` | before-open candidate; 08:30 unconfirmed | 6 | 7.8 min | 3主要noteで概要成立、設計観測にPilot Logを追加 | Pass | 5 forecast rows | 100% (5/5) | 0 | +35 net | +13 lines / +1,430 bytes | +4 lines / +705 bytes | 90 | forecast revision形式、`undetermined_by_company`、before-open未確定 | unregistered | not acquired |

## 総合結果

| 評価軸 | 結果 |
| --- | --- |
| 主要3noteで概要成立 | Pass |
| KPI/forecast再現 | 29/29, 100% |
| historical reconstruction隔離 | 誤用0 |
| 時刻/session誤認防止 | 誤用0 |
| 価格/return誤用防止 | 誤用0 |
| company routing混同 | 0 |
| broken Wikilink | 0 at each completed pilot |
| duplicate `note_id` | 0 at each completed pilot |
| ERS/Vault/TSO境界 | 維持 |

## 3社共通構造

各社で次の6note topologyを再利用できた。

1. Company
2. Earnings Event
3. Reconstruction Hypothesis
4. Reconstruction Limitations
5. Source Index
6. Pilot Log

共通して有効だった要素は、stable ID関係、Eventへのmetric集約、source URLのSource Index集約、historical warning、formal evidence未登録の明示、price/return未作成状態、index routing、hot Fast Read Orderである。

## Event type別差分

### Earnings release

NintendoとToyotaはcompany forecast、actual、翌期guidanceを必要な範囲で分離した。KPI数を固定せず、企業・会計基準・event理解に必要な指標だけをHumanが選ぶ。

### Earnings forecast revision

OlympicはKPI result形式を流用せず、`previous_company_forecast`、`revised_company_forecast`、`revision_amount`、`revision_rate`、`revised_value_status`、reason、affected periodを中心にした。会社自身の未定とsource欠落を分離した。

### Session candidate

after-close、intraday、before-openの全caseで、候補時刻をconfirmedへ昇格させなかった。時刻、session、price reference、corporate action、returnを独立状態として保持する設計を共通化する。

## 自動化可能部分

次は3社でsemantic判断を伴わず反復した。

- `repository_remote`
- `ers_commit`
- `origin_mode`
- `status`
- `knowledge_version`
- current `created_at`, `updated_at`, `reconstructed_at`
- empty `source_evidence_ids` は `historical_reconstruction` に限り自動生成可能

prospectiveでは `source_evidence_ids` はHuman requiredであり、generatorが空配列を自動確定しない。`baseline_draft`でHumanが明示した空配列を許容する条件と、`baseline_lock`で1件以上を必須とする条件は [Obsidian Frontmatter Generator Specification](./OBSIDIAN_FRONTMATTER_GENERATOR_SPEC.md) に従う。

3社18noteで共通fieldは270 occurrencesとなった。固定fieldだけを生成するpreview-first generatorには十分な導入根拠がある。

## Human判断が必須の部分

- `note_type`, `note_id`, entity IDとrelation
- `knowledge_class`, `confidence`, `verified_status`
- event type、published time、session、before-open判定
- source/license/raw storage状態
- KPI/forecastの選択、値、単位、status
- hypothesis、limitations、invalidation
- score利用可否、formal evidence採用可否

## 安全上必要な冗長性

次は複数noteへ残す。削減より誤用防止を優先する。

- `historical_reconstruction` とprospective利用禁止
- hindsight bias
- 候補時刻とsession未確認
- price/return未作成
- formal evidence未登録
- TSO snapshot未取得

固定文の意味driftは将来lintで検出する。

## 削減可能な重複

- repository/commit/date/status/versionの手入力
- Source Index以外へのURL反復
- CompanyとEvent間のmetric全文重複
- completed Pilot Logの通常Fast Readへの混入
- cacheに残る旧branch/current status

## Index/hot分割の暫定閾値

3社時点の実測はindex 97 lines / 6,301 bytes、hot 70 lines / 約4.2 KB、company count 3、pilot note count 18、Wikilink 110でrouting混同0だった。現時点では分割しない。

次のいずれかでHuman reviewを必須とする。数値はpilot由来の暫定値であり、確定値ではない。

| trigger | provisional threshold | rationale |
| --- | ---: | --- |
| company count | `>= 10` | 現在の3倍超でidentity tableと6-link sectionのscan負荷を再評価 |
| pilot/domain note count | `>= 60` | 6note/company topologyを前提に10社相当 |
| index size | `>= 20 KB` or `>= 250 lines` | 現在の約3倍で本文集約化を疑う |
| completed pilot entries in hot | `>= 8` | current contextよりhistoryが支配し始める前に分離 |
| total Wikilinks in Earnings Research | `>= 300` | broken-link auditとvisual scan負荷を再評価 |
| Fast Read routing confusion | `> 0` | count/sizeに関係なく即時review |
| Fast Read route selection | `> 30 seconds` when measurable | routing tableの性能低下を示す |

threshold到達は自動分割ではなく、company sub-index、completed pilot archive、hot縮小のpatch proposalを作るtriggerとする。

## 次段階へ持ち越す課題

1. 固定field限定generatorのHuman承認
2. `domain_index`, `context_cache`, `pilot_log` migration ADR
3. prospective formal evidenceの保存metadata gap解消
4. cache staleness lintの実装判断
5. 第4号prospective caseでHuman作業時間とevidence登録時間を計測
6. TSO snapshotの実需要確認

## 判定

3社historical reconstruction pilotは完了。第4社を追加する前に、generator、note type、formal evidence、cache lintの設計をHuman reviewする。過去3社の一括evidence backfillとTSO snapshot importは行わない。
