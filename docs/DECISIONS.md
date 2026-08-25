# Decisions

## ERS-ADR-0001

Date: 2026-07-19

Status: Accepted for initial foundation

Context: The first milestone should prepare folders, specifications, sample data, and validation without building external ingestion, trading logic, or a production database.

Decision: Start with CSV files plus JSON schema metadata and a Python validation CLI. Treat SQLite as a likely next-stage candidate, but do not make it the source of truth in this milestone.

Consequences: The project is easy for Codex, ChatGPT, Claude Code, spreadsheet tools, and human reviewers to inspect. Cross-file constraints must be implemented in Python rather than delegated to a database. Migration to SQLite will require an explicit decision and tests.

Alternatives Considered: SQLite as the source of truth with CSV import/export. This is attractive for append-only history and constraints, but it adds premature migration and operational choices before the research fields stabilize.

## ERS-ADR-0002

Date: 2026-07-19

Status: Accepted for initial foundation

Context: `pre_earnings_baseline` can become too wide if every evidence item is normalized early. Over-normalization would slow manual research capture.

Decision: Keep one operational baseline CSV for the initial milestone, but add explicit timing, evidence, scoring version, and lock fields. Defer deeper normalization into baseline_core, fundamentals, sentiment, supply_demand, TSO, and scores until real capture volume proves the need.

Consequences: Manual entry remains practical. The validator still blocks the most important leakage and history risks. Later decomposition must preserve baseline IDs and versions.

Alternatives Considered: Fully normalized baseline tables from day one. Rejected for now because the initial milestone needs reviewable samples and validation more than database elegance.

## ERS-ADR-0003

Date: 2026-07-19

Status: Accepted for initial foundation

Context: TSO integration fields are not formally mapped to the final TSO_LOG 28-column contract.

Decision: Store TSO values in `tso_snapshot` as external snapshots with `signal_id`, source file, source row hash, and provisional score ranges. Do not mutate or reformat TSO source rows in place.

Consequences: Earnings research can reference market regime and risk context while preserving TSO boundary discipline. Formal mapping remains an open question.

Alternatives Considered: Importing TSO_LOG into the same schema as native earnings records. Rejected because it would blur ownership before the formal mapping is approved.

## ERS-ADR-0004

Date: 2026-07-19

Status: Proposed

Context: Evidence/source lineage is required to prove that pre-earnings scores were based only on information available before the baseline and before the earnings announcement.

Decision: Add `evidence` as a first-class CSV entity in the initial schema. Keep the relation polymorphic for now through `related_entity_type` and `related_entity_id`, and enforce known references in the Python validator.

Consequences: Baselines, TSO snapshots, reviews, and hypotheses can cite source timing without waiting for a database migration. CSV cannot enforce polymorphic foreign keys by itself, so custom validation remains required.

Alternatives Considered: Add a separate evidence link table for each entity immediately. Rejected for this milestone because it would over-normalize before real manual cases expose the stable relationship patterns.

## ERS-ADR-0005

Date: 2026-07-19

Status: Proposed

Context: CSV is reviewable and agent-friendly, but the project is already cross-referencing companies, events, baselines, reviews, TSO snapshots, hypotheses, evidence, scoring versions, and correction history.

Decision: Continue CSV + JSON schema for the next review pass, but define SQLite migration triggers. Move to SQLite as source of truth when any of the following are true: more than 50 companies are tracked, more than 150 earnings events are stored, baseline/review/evidence joins become routine, corrections require audit queries, or score recalculation needs repeatable snapshots. Keep CSV/Excel/Google Sheets as import and review views after migration.

Consequences: Current artifacts remain easy to inspect in Git. The project has a clear path away from CSV before cross-file constraints become fragile.

Alternatives Considered:

- A. CSV + JSON Schema continued: best for manual review, Git diffs, and multi-agent handoff; weakest for foreign keys, history queries, score recalculation, and future leakage checks.
- B. SQLite source of truth with CSV views: best next step for append-only records, joins, referential integrity, recalculation, and look-ahead audits; moderate implementation cost; still local and portable.
- C. PostgreSQL from the start: strongest for multi-user operations and future services; too heavy before target market, volume, and ingestion policy are decided.

Comparison:

| Criterion | CSV + JSON Schema | SQLite Source | PostgreSQL |
| --- | --- | --- | --- |
| History management | medium | high | high |
| Foreign keys | low without custom validation | high | high |
| Manual review | high | medium | medium |
| Git diffs | high | low for DB file, high for exported views | low |
| Future backtests | medium | high | high |
| Excel/Sheets integration | high | high through exports | medium |
| Agent handoff | high | medium to high with docs/views | medium |
| Implementation load | low | medium | high |
| Data corruption risk | medium | low with constraints/backups | low |
| Score recalculation | medium | high | high |
| Future-information checks | medium | high | high |

## ERS-ADR-0006

Date: 2026-07-19

Status: Accepted for sample/schema validation

Context: Realistic earnings research needs to distinguish ordinary quarterly earnings, standalone guidance revisions, monthly disclosures, presentations, and the market session in which an announcement occurs.

Decision: Add `event_type`, `announcement_session`, `accounting_standard`, and `return_base_price_policy` to `earnings_event`.

Consequences: Return-window interpretation can distinguish before-open, intraday, and after-close announcements. Accounting-standard differences remain visible before score interpretation. The project still does not calculate returns automatically.

Alternatives Considered: Keep these fields in evidence only. Rejected because return measurement and future leakage checks need event-level semantics.

## ERS-ADR-0007

Date: 2026-07-19

Status: Accepted for sample/schema validation

Context: Industry KPIs matter, but creating a separate table for every industry would overfit the first samples and make manual research too heavy.

Decision: Add a generic `kpi_observation` table linked to company, earnings event, and source evidence.

Consequences: Retail, SaaS, manufacturing, construction, restaurant, cash-flow, and inventory metrics can be stored with expected value, actual value, unit, period, and evidence link. More specialized KPI tables are deferred until real capture volume proves the need.

Alternatives Considered: Store all KPI information inside `evidence.score_component`. Rejected because KPI expected values, actual values, units, and periods need structure for later comparison.

## ERS-ADR-0008

Date: 2026-07-20

Status: Accepted after Claude audit

Context: The first `kpi_observation` design stored `expected_value` and `actual_value` on one row with a single `recorded_at`. That allowed post-announcement actual KPI results to appear as if they were known before the earnings announcement.

Decision: Split KPI observations into append-only rows using `value_type=expected|actual` and one `value` column. Pre-event scoring may only use `value_type=expected`. `value_type=actual` rows must be recorded at or after the earnings announcement and must not be used for pre-event scoring.

Consequences: KPI expectations and KPI actuals now have separate timestamps and source evidence. Manual review is slightly less spreadsheet-compact, but the design better preserves append-only history and prevents look-ahead leakage.

Alternatives Considered: Keep one row with `expected_recorded_at` and `actual_recorded_at`. Rejected because actuals would still be added by updating a pre-event row, which conflicts with the append-only research log principle.

## ERS-ADR-0009

Date: 2026-07-20

Status: Accepted after Claude audit

Context: `return_base_price_policy` described the intended event-level policy but did not store the actual price used to calculate post-earnings returns.

Decision: Add `return_reference_price_type`, `return_reference_price`, and `return_reference_price_datetime` to `post_earnings_review`. Require these fields whenever return windows are populated.

Consequences: Later reviewers can reconstruct which price anchored day0/day1/day5/day20 returns. Price-data source selection and intraday availability remain open questions.

Alternatives Considered: Store only policy-level information on `earnings_event`. Rejected because policy alone is insufficient for reproducible return calculations.

## ERS-ADR-0010

Date: 2026-07-20

Status: 暫定文書方針として承認

Context: 現行TSO ledgerは29列だが、従来ERS文書はformal 28-column contractを前提としていた。複数のTSO fieldはERSのtype・controlled vocabularyとも衝突する。また、実在caseのhand-entry test前に、決算後return検証の最低price-data granularityを定める必要がある。

Decision: `TSO_LOG_COLUMN_DEFINITION.md` で観測済み29列を定義し、不確定mappingは `unknown` のまま保持する。現フェーズではtrading/execution fieldを取り込まない。一般の最低price datasetはunadjusted/adjustedを識別できるdaily OHLCとし、確定的なintraday-event returnにはminute barsまたは監査可能なmanual referenceを要求する。event reactionはunadjusted actual traded priceで測り、adjusted priceは期間横断比較用に分離する。vendor integration、return自動計算、tick storage、backtestingは延期する。

Consequences: TSOを変更せず、不一致fieldを確定済みに見せずに、ERSでTSO contextとprice referenceをreviewできる。監査可能なpre-announcement priceがないintraday caseはprovisionalとし、依存するreturn fieldsを空欄にする。categorical rank、raw regime、non-company asset、ingestion originのschema変更は、後続の承認taskで扱う。

Alternatives Considered: TSO値を現行ERS schemaへ強制変換し、全sessionでdaily closeを使う案。source semanticsを失い、intraday announcementにlook-ahead riskを持ち込むため採用しない。

## ERS-ADR-0011

Date: 2026-07-23

Status: Accepted for manual pilot with conditions

Context: 実在銘柄のhand-entry pilot前に、価格source候補、manual fallback、TSO unknown列のraw保存、mapping versionを定義する必要がある。providerのstorage/license条件とpilot結果はまだ確認されていない。

Decision: 価格dataの第一候補をJ-Quants、actual announcement timestampの正本候補をTDnetとする。event reactionはunadjusted actual traded priceを使い、adjusted priceとadjustment factorは期間横断比較用に分離する。intradayは発表前に終了した最後の完全な1-minute barを使い、取得不能時のみ監査可能な `manual` を許容する。daily closeをintraday発表前価格へ代用せず、tick dataは使わない。異なるreference typeはcohortを分離する。TSOの意味衝突列は取り込まず、raw保存候補列はscoreへ使わない。最初の3件は `after_close`, `intraday`, `before_open` を各1件とする。

Consequences: 外部API実装や有料契約前に、入力負荷と欠落fieldを確認できる。J-Quants dataの保存、解約後retention、agent処理、派生値、screenshot、Git格納の可否は人間確認条件として残す。raw/adjusted/factorの専用schema列と本番利用は未承認であり、3件pilot後に判断する。

Alternatives Considered: 無料web scrapingでrecent minute dataを集める案はtermsと再現性のriskから採用しない。最初からFLEX Historicalまたは法人vendorを契約する案はpilot規模に対して過剰なためdeferredとする。

## ERS-ADR-0012

Date: 2026-07-23

Status: Accepted for documentation and pilot governance

Context: ERSのstructured recordだけでは、企業固有のguidance pattern、業種KPIの意味、失敗条件、複数eventから得たlessonを選択的に再利用しにくい。既存Obsidian VaultにはMaruyama AI Research Lab、Facts/Hypotheses/Lessons taxonomy、Protocol/Observation workflowが存在する。一方、Vaultには未commit変更があり、claude-obsidian固有のindex/hot/raw/ingest/lint機構は導入済みと確認できない。

Decision: ERS Git repositoryをschema、CSV、validator、baseline lock、evidence lineage、scoring version、ADRの正本とし、既存Obsidian Research Labをcompany pattern、industry knowledge、hypothesis、failure mode、lessonのknowledge layerとする。初期段階はObsidian noteにERS stable IDとcommitを保持するmanual reference方式とし、自動同期、schema変更、自動validated昇格、external plugin導入を行わない。共通frontmatterとclaim enumは `OBSIDIAN_FRONTMATTER_POLICY.md` を正本とし、`origin_mode` でprospective、historical reconstruction、syntheticを区別する。すべてのstatus変更はHuman承認を必要とする。Nintendo、Toyota、Olympic Groupのhistorical reconstructionを最大5〜8notes/companyでpilotする。

Consequences: 機械処理の正本と解釈知識を分離しながら、後続AIが必要contextだけを読める。Vault noteは単独でverified evidenceまたはscore inputにならず、人間reviewとERS evidence gateが必要になる。link table、lint code、raw retention、plugin導入、Vault変更はpilot後の別承認となる。

Alternatives Considered: ObsidianをERSのsource of truthにする案はbaseline lockとschema validationを弱めるため採用しない。全Vault自動同期はfuture leakageと競合riskが高い。各ERS rowへWikilinkを直接追加する案は多対多・rename・version管理に弱いため、将来は独立 `ers_knowledge_link` tableを第一候補とする。

## ERS-ADR-0013

Date: 2026-07-23

Status: Accepted and completed

Context: ERS repositoryは日付付きCodex作業directoryにあり、remoteが設定されていなかった。Obsidianの `ers_commit` が参照する履歴をlocal deletionから保護し、将来のagent handoffで恒久的に参照できる場所が必要だった。

Decision: Git historyを保持して `/Users/maruyamayuuki/Documents/MaruyamaAIResearchLab/earnings-research-system` へ移設し、private repository `https://github.com/Tadaim2tk/earnings-research-system` を `origin` とする。Obsidianの永続参照は `repository_remote` + `ers_commit` とし、local pathは環境依存の実行補助に限定する。旧pathは移設確認後もrollback用に保持する。

Consequences: commit hashを維持したprivate remoteが実行履歴の正本となり、Mac上のpath変更でObsidian参照が失われない。旧pathの保持期間だけは運用判断として残る。

Alternatives Considered: 現在のCodex作業directoryを恒久pathとして使い続ける案は削除riskと参照安定性に弱い。履歴なしで新repositoryへcopyする案は既存 `ers_commit` を無効化するため採用しない。

## ERS-ADR-0014

Date: 2026-07-24

Status: Proposed

Context: `THREE_COMPANY_PILOT_REVIEW.md` の横断結果では、Nintendo、Toyota、Olympic Groupの3社18noteで共通frontmatterが270回反復した。固定fieldの手入力はresearch valueを増やさず、company ID、date、status、commitのcopy-paste driftを生む。一方、semantic fieldの自動推測は未確認時刻、verification、hypothesis、KPIを誤生成するriskがある。

Decision: `OBSIDIAN_FRONTMATTER_GENERATOR_SPEC.md` に従い、固定fieldだけを生成するpreview-first generatorを設計候補とする。既存noteを上書きせず、Human field不足、ERS commit不存在、path/ID衝突ではfileを書かず停止する。Human承認前に適用せず、generator codeは別taskで実装判断する。

Consequences: 反復入力と構文driftを減らせるが、semantic field、status昇格、source/license/time/session、KPI、hypothesis、limitationsはHuman責任として残る。本ADRがAcceptedになるまでgeneratorを実装しない。

Alternatives Considered: 全frontmatterをAIに推測させる案は誤ったverified状態を量産するため採用しない。template copyだけを継続する案は270回の反復とcopy-paste riskを解消しない。

## ERS-ADR-0015

Date: 2026-07-24

Status: Proposed

Context: `index.md`、`hot.md`、Pilot Logは3社pilotで `tool_workflow` を共有したが、durable routing、再生成可能cache、process historyとしてlifecycle、loading、lint、status semanticsが異なる。

Decision: `OBSIDIAN_WORKFLOW_NOTE_TYPE_SPLIT.md` に従い、将来 `domain_index`、`context_cache`、`pilot_log` へ分割する。`context_cache` の失効条件は `OBSIDIAN_CACHE_STALENESS_POLICY.md` に従う。既存ID/path/body/statusを維持したtype-only migrationとし、policy/lint fixture、migration preview、Fast Read regressionを先に準備する。

Consequences: context loadingとstale cache lintを型別にでき、`draft`の意味を整理できる。既存noteとpolicyへのmigration costがあるため、Human承認前にtype enumやVault noteを変更しない。

Alternatives Considered: `tool_workflow`を継続する案は現規模では動くが、cacheと履歴の更新ruleを区別できない。全workflow noteを個別typeに細分化する案は初期scopeを超える。

## ERS-ADR-0016

Date: 2026-07-24

Status: Proposed

Context: 3社historical pilotはURLとSource IndexでHuman-readable reuseに成功したが、formal evidence ID、hash、observed time、machine reverse lookupを持たない。最初のprospective eventではbaseline lock前のsource timingをERSで証明する必要がある。

Decision: `PROSPECTIVE_EVIDENCE_PILOT_POLICY.md` に従い、`FIRST_PROSPECTIVE_EVENT_SELECTION.md` の条件を満たすHuman承認後の最初のprospective eventからformal evidence運用を開始する。pre-event company forecast/直近決算、official event disclosure、time-bearing primary metadata、price source、hypothesis-supporting primary sourceを最小対象とする。baseline draftはevidence登録前でも許容するが、formal evidence、Human review、timing gateを満たすまでlockせず、未登録claimをprospective scoreへ使わない。

Consequences: look-ahead防止とsource reverse lookupが強化される。hash/raw storage/license statusの表現はAcceptedの `ERS-ADR-0019` で追加済みだが、prospective運用開始は別gateのままとする。

Alternatives Considered: Source Indexだけでprospective scoringする案はtimingとlineageの機械検証が弱い。すべてのsourceをraw保存する案はlicense/storage条件未確認のため採用しない。

## ERS-ADR-0017

Date: 2026-07-24

Status: Rejected

Context: Nintendo、Toyota、Olympicはoutcomeを知った後に作成したhistorical reconstructionであり、actual observed/recorded timeはevent後である。3社の全sourceを一括遡及登録すると、prospective evidenceのように見えるriskがある。

Decision: historical 3社のformal evidence一括backfillを行わない。現在のURL、metadata、Source Indexを維持し、legal/audit/reuse上の必要が生じたsourceだけをactual observed/recorded timeで個別遡及登録できる。遡及登録してもprospective baselineやcalibrationへ昇格させない。

Consequences: 過去sourceのmachine reverse lookupは限定されたままだが、historical/prospective境界を守り、低価値な大量入力を避けられる。

Alternatives Considered: 3社の全primary sourceを一括登録する案は時点証拠と後日整理を混同するためRejected。過去sourceを永久に登録禁止とする案は将来の監査必要性へ対応できない。

## ERS-ADR-0018

Date: 2026-07-24

Status: Deferred

Context: 3社すべてでTSO snapshotなしにcompany/event理解、metric再現、Fast Read、安全なtime/price uncertainty管理が成立した。TSO_LOG 29列にはunknown mappingとmeaning conflictが残る。

Decision: `TSO_SNAPSHOT_DEFER_DECISION.md` に従い、TSO snapshot importとadapter実装を延期する。prospective evidence/price workflowを先に確立し、具体的なTSO比較需要、mapping contract、source row hash、mapping version、identity rule、explicit read-only adapter設計が揃った時点で再検討する。

Consequences: ERS/TSOの結合度と誤mapping riskを抑えられる。TSO contextを使ったscore/event correlationは延期されるが、現在の決算知識再利用には影響しない。

Alternatives Considered: historical 3社へ後付けsnapshotを作る案はprospective lockがなく価値が低い。TSO_LOGを直接共有・同期する案はownershipとrollback境界を壊すため採用しない。

## ERS-ADR-0019

Date: 2026-07-25

Status: Accepted

Approval: Human承認。schema、validator、docs、testsの整合と旧20列CSV互換性を維持し、optional fieldによるvalidation bypassがないことを独立監査で確認した。`raw_storage_status=stored` は `license_status=permitted` を必須とし、hash mismatchをblocking errorとする。correction lineageはself、missing、forward、entity mismatchを拒否する。既存64 testsに加えて独立監査の一時境界case 36件で誤受理がないことを確認した。本schema承認はprospective evidence実データ登録、baseline lock、scoring、prospective運用開始の自動承認ではない。

Context: prospective formal evidenceにはcontent hash、raw storage、license判断、source correction lineageが必要だが、既存 `evidence` schemaには専用fieldがない。sidecarは既存headerを維持できる一方、`evidence_id` join欠落、孤立metadata、重複lineageのriskがある。

Decision: `PROSPECTIVE_EVIDENCE_METADATA.md` に従い、既存 `evidence` rowへoptional direct columnsを追加する。追加8fieldのいずれかを使用した場合にhash/storage/licenseの3statusすべてを要求し、`license_status=permitted`以外のraw保存、verified hash欠落、hash mismatchをerrorにする。correction/retractionは `evidence_status` と `supersedes_evidence_id` を持つ新rowとしてappendし、元rowを変更しない。旧CSVはoptional headerなしでもvalidatorが受理する。

Consequences: identity、timing、storage/license、lineageを同じ `evidence_id` で検証できる。新metadataを採用しない既存rowは変更不要だが、prospective rowではstatus bundleとcross-field rulesが必要になる。schema追加だけではscoring、baseline lock、historical evidence昇格を有効化しない。

Alternatives Considered: sidecar metadata schemaはjoinとlineageの二重管理が増えるため採用しない。全field必須化と既存CSV migrationは初回prospective前の互換性costが高い。event lifecycleとbaseline parent/version/lock relationはownershipが異なるため別PRへ分離する。

## ERS-ADR-0020

Date: 2026-07-25

Status: Accepted

Approval: Human承認。Human approvalなしのlockを拒否し、明示的field manifestからcanonical SHA-256を再計算して不一致をblocking errorとする。baselineと関連evidenceの時刻gate、数値version比較、append-only supersessionをvalidatorで確認した。49列prospective-capable fileのlocked rowがmetadata全空でlegacy contractへ逃げる経路を閉じ、旧42列CSV互換性は維持する。不正version／datetimeをvalidation errorへ縮退し、CLI public経路のsuccess、validation failure、crash regression testsを追加した。本ADR承認はprospective event選定・実運用開始の自動承認ではない。

Context: prospective formal evidence metadataはAcceptedとなったが、baseline自体はdraftとlockedの明示的な区別、Human review gate、再計算可能なlock hash、延期時のappend-only versioningを機械保証していない。evidenceだけを固定してもbaseline本文とscoreを発表後に上書きできればfuture leakageを防げない。

Decision: [PROSPECTIVE_BASELINE_LOCK.md](PROSPECTIVE_BASELINE_LOCK.md) に従い、既存baseline rowへbackward-compatible optional columnsを追加する。prospective rowは `draft` または `locked` を明示し、lockedにはHuman approval、`locked_at`、canonical SHA-256 hash、formal evidence、score利用承認済みevidenceを要求する。versionはeventごとに単調増加し、locked `v2` 以降は同一eventの先行rowを `supersedes_baseline_id` で参照する。旧rowは上書き・削除しない。event cancellation enumは本ADRの対象外とする。

Consequences: 発表後情報のscore混入、draftの誤利用、self/missing/forward/cross-event supersession、hash不一致をvalidatorで停止できる。旧42列CSVは維持できる一方、prospective 49列rowには厳格なstatus bundleが必要になる。snapshot内でcontentとhashを同時に改変する行為の独立検出、cross-file lineage、event cancellationは未実装である。本ADRのAccepted statusだけではprospective event選定・運用開始を承認しない。

Alternatives Considered: 既存 `is_locked` と自由形式hashだけを継続する案はHuman reviewとhash再計算を検証できない。`superseded` statusで旧rowを書き換える案はappend-onlyを壊す。event cancellationをbaseline statusへ追加する案はevent lifecycleとbaseline lifecycleの責務を混同するため採用しない。

## ERS-ADR-0021

Date: 2026-07-25

Status: Accepted

Approval: Human承認。lifecycle activation bypassがなく、first statusを `scheduled` のみに限定し、append-onlyの非分岐status chainとcurrent tail一意性を逐次・大域検査で保証することを独立監査で確認した。`cancelled` と `occurred` はterminalであり、延期時刻と直前予定時刻のchain、延期後baselineのHuman reviewとlock時刻gate、cancelledまたは未発生eventのreview・return遮断、occurred確認後のみのpost-event処理を検証する。既存164 testsに加え、実CLI経由の独立境界case 48件で予期しない受理がないことを確認した。本ADR承認はprospective event選定・実運用開始の自動承認ではない。

Context: baseline lockとformal evidence metadataは機械検証可能になったが、event延期・中止・発生確認はpolicy上の概念に留まる。既存 `earnings_event.announcement_status` を上書きすると履歴と認識時刻を失い、cancelled eventをpost-event scoringへ入れるriskがある。

Decision: [PROSPECTIVE_EVENT_LIFECYCLE.md](PROSPECTIVE_EVENT_LIFECYCLE.md) に従い、独立 `event_status_history` tableへ `scheduled`、`postponed`、`cancelled`、`occurred` をappend-onlyで記録する。各eventは非分岐lineageと一意なcurrent tailを持つ。lifecycle row、prospective baseline metadata、または関連prospective evidence/reviewでactivatedされたeventにstatus historyを要求する。postponement後のoccurredには再review済みlocked baselineを要求し、cancelledまたは未occurred eventのpost-event reviewを拒否する。source訂正はevidence lineageの責務として分離する。

Consequences: event rowとbaselineを上書きせず、延期履歴、cancelled除外、occurred gateをdataset-levelで検証できる。延期後gateはbaseline validation成功後、同一loaded dataset内のprospective rowから唯一のunsuperseded current locked baseline tailだけを使い、legacy、invalid lineage、superseded、0件、複数、current draftをfail-closedにする。activated prospective eventを含むcomplete datasetにはstatus history fileが必要になる。terminal statusの誤記録訂正、cross-file lineage、return計算、自動calibrationは未実装であり、本ADRのAccepted statusだけではprospective運用開始を承認しない。

Alternatives Considered: event rowへcurrent statusを追加する方式Aは単純だが履歴を上書きしやすい。event全体をversion化する方式Cはbaseline versionとidentity semanticsが衝突する。独立history tableがappend-onlyとlegacy event互換性を最も明確に保つため方式Bを選ぶ。

Historical Operational Clarification (2026-07-27): 当時の第1号prospective pilotは [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) のmetadata-only、Human-operated contractに従い、J-Quants、contract型TDnet service、自動取得、raw保存をscope外としていた。candidate固有terms、manual price source、reviewer、監視日程のHuman承認前にpilotを開始しない境界を記録したものである。Level 2への運用変更案は `ERS-ADR-0022` で追跡し、ADR-0021のlifecycle semanticsまたはstatusを変更しない。

## ERS-ADR-0022

Date: 2026-08-02

Status: Accepted

Context: 2026-07-27時点の第1号prospective contractはHumanによる定期巡回とmanual price entryを前提としていた。この方式は承認権限をHumanへ残す一方、変更のないsourceを毎日再確認する負荷と確認漏れriskをHumanへ集中させる。IR資料の再読込も、定常情報と新規差分を分離していなかった。

Decision: [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) に従い、第1号pilotの推奨をapproval-gated Level 2 monitoringとする。AIは `automated_access_permitted=true` をHumanがsource単位で承認した範囲だけ定期確認し、monitor checkpointとの差分、取得失敗、判断候補を整理する。変更なしではformal evidenceを作らない。candidate採用、terms、`used_for_score`、baseline review／lock、event status、price reference、stop／resume、post-event確定はHuman gateとして維持する。sourceの自動accessが未承認なら当該sourceだけLevel 1へ落とす。monitor checkpoint、scheduler、price adapterのschemaまたは実装は本ADRに含めない。実装候補のmachine state、atomic persistence、fingerprint、notification境界は [AI_MONITORING_IMPLEMENTATION_DESIGN.md](AI_MONITORING_IMPLEMENTATION_DESIGN.md) で設計する。

Consequences: Humanへ毎日の定期巡回を要求せず、AIへ作業量を移しながら承認権限を増やさない。monitor checkpointとformal evidenceを分離し、取得失敗を `no_change` と誤認しない。価格sourceはHuman承認済みproviderから必要項目だけ取得することを目標とするが、providerの正式採用と自動取得実装は別承認になる。本ADRがAcceptedになるまで、実monitoring automation、price adapter、実event登録を開始しない。

Alternatives Considered: 全sourceをHumanが毎日確認する方式は定期負荷と確認漏れriskが高い。terms未確認sourceを一律自動巡回する方式はprovider境界を破る。evidence登録やevent statusまでAIが自動確定するLevel 3は初回pilotのHuman gateを広く変更するため採用しない。

## ERS-ADR-0023

Date: 2026-08-09

Status: Accepted

Approval: Humanの恒久方針として、公開・認証不要・低頻度GET・最小保存・明示的な自動access禁止なし・外部契約なし・課金なし・実売買なし、をすべて満たす情報収集はAIが自律的に開始できることを承認した。

Context: ADR-0022はsource単位のHuman approvalを前提としたため、具体的な禁止や契約判断が存在しない公開IR監視でもHuman応答待ちになり、継続監視という目的を阻害した。

Decision: [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) と [ICECO_PILOT_APPROVAL.md](ICECO_PILOT_APPROVAL.md) に従い、適用条件を満たすsourceは `system_policy:public-web-low-frequency-v1` でmonitor authorizationとactivationを記録できる。明示禁止、実質的に判断困難な利用条件、login/authentication、有料契約、個人情報・非公開情報、実売買、金銭的または不可逆な外部操作を検出した場合だけfail-closedで停止し、Humanへ例外判断を求める。robots規則はpage取得前に確認する。

Consequences: 通常の公開IR監視はHuman不在でも継続できる。raw page本文は保存せず、metadataと比較digestだけを保持する。価格provider、formal evidence、baseline lock、event status、売買は本ADRの承認範囲外である。

Alternatives Considered: すべての新規公開URLをHuman approval待ちにする案は不要な停止を繰り返すため採用しない。公開情報なら無条件で取得する案は明示禁止、認証、課金、privacy等を見落とすため採用しない。

## ERS-ADR-0024

Date: 2026-08-10

Status: Accepted

Context: `post_event_learning_review` の学習候補はappend-onlyで保存されるが、次回baseline作成時に人間が参照する単一contextがなかった。

Decision: [BASELINE_CARRYOVER.md](BASELINE_CARRYOVER.md) に従い、1件以上のreviewから、人間向け `baseline_carryover_context_v1` を作る。各文字列は出典review IDとreview単位の出現回数を伴い、市場期待解釈とreaction transitionの食い違い履歴も同様に保持する。異なるeventは同一企業に限り、source event IDを明示する。未来sourceと既存出力pathは拒否する。

Consequences: 次回baseline作成者は過去の学習候補を機械的に収集できるが、production rule、scoring weight、trade decisionへは反映されない。validated／確立等への昇格、独立3イベント判定、TSO／Vault／registry連携は実装しない。

## ERS-ADR-0025

Date: 2026-08-11

Status: Accepted

Context: stale gapを暦時間で測ると週末だけで閾値を超え、event windowを朝1回だけ監視すると24時間閾値に対して遅延余地がない。また、一度stale停止したstateは再初期化禁止のため、監視途切れを記録した上で通常観測へ戻るappend-only経路が必要である。

Decision: stale経過時間は土曜・日曜を除外し、祝日calendarは追加しない。event 5営業日前から当日までは既存3 cron slotをdueとする。独立 `monitor_gap_acknowledgement` schemaを追加し、有効なappend-only tailの `acknowledged_gap_end` だけを次回stale評価の基準にできる。未来gap、解決済みgapの新規再利用、self／missing／二重supersessionを拒否する。acknowledgement後もrobots確認とsource observationを必須とし、pending changeを解除しない。

Consequences: artifact削除や再初期化なしでstale停止から通常観測を再開できる。acknowledgementは監視健全性の履歴に限定され、formal evidence、baseline、event status、scoring、売買判断へ影響しない。threshold値、registry、外部network境界は変更しない。event_window初日とevent当日の朝slotは閾値到達時刻とほぼ一致して遅延余裕がほぼゼロであり、Actionsの通常遅延でもacknowledgementが定常的に必要になり得る。恒久対応は閾値を本ADRで変更せず、別ADRで決定する。

## ERS-ADR-0026

Date: 2026-08-15

Status: Accepted

Context: ICECOの静的IR HTMLはXJ Storage資料一覧を動的表示するため、PDF追加をresponse metadataまたは本文digestで検知できず、2026-08-13 15:30の第1四半期決算短信を見逃した。代替候補のrobots.txtを実測したところ、`www.xj-storage.jp`、`contents.xj-storage.jp`、`www.release.tdnet.info` はいずれも `User-Agent: *` / `Disallow: /` で全パスの自動accessを明示禁止していた。pilot方針は明示禁止を検出したsourceを停止・例外報告とするため、この2案は採用できない。`webapi.yanoshin.jp` は `Allow: /` に加え、AI agent向けの `llms.txt`（2026-02-09公開）で認証不要・利用目的・頻度配慮を明示しており、`system_policy:public-web-low-frequency-v1` の条件を満たす。

Decision: 監視対象を公開TDnet適時開示index（`webapi.yanoshin.jp`、`json2` format、`limit=10`）の新target `ICECO_TDNET_INDEX` へ移す。旧3 targetはregistryから削除せず `retired` として終了記録を残し、checkpoint／artifactの孤児化を避ける。target IDを維持したまま別sourceへ差し替えると「監視対象が変わった」ことが本物の資料追加と区別できないchange通知になるため、新IDで開始する。`tdnet_index_json` categoryは先頭1件の `id`／`title`／`pubdate`／`document_url` と一覧 `total_count` だけをfingerprintに入れ、raw JSONを保存しない。providerが全formatを `text/html` で返すため、parserはmedia typeではなくcategoryで選ぶ。timezoneなし `pubdate` はJSTと明示的に解釈する。

`www.xj-storage.jp`／`www.release.tdnet.info` の明示禁止は、pilot方針の定めるHuman例外案件として報告する。決算短信PDF本体はこの2 hostにしか存在しないため、検知は自動化されるが**document本体の自動取得は現時点で許可されたsourceが無い**。

Decision（付随）: robots.txt取得は `Accept: text/plain, */*` を使う。実測で `www.xj-storage.jp` は監視の既定Acceptに406を返し、robots方針が読めないことが `http_error` に化けていた。robots経路の非200（404／410を除く）は `terms_not_approved` とし、読めないrobotsを許可として扱わない。

Decision（付随）: 通常日のdue slotを09:17から引け後の17:17へ移す。1日1回という頻度は変えず、15時台の開示を当日中に観測する。

Decision（付随）: checkpointに `last_seen_document_url` を追加し、research handoffへ渡す。document byteは保存しない。`analyze-earnings-handoff` は `tdnet_index_json` のhandoffでdocument discoveryを実行しない。indexはhardened monitoring adapter専用の認可であり、pipeline側から再取得するとrobots未確認・IP pinningなしのrequestが増え、その先のdocumentは明示禁止hostにある。

Decision（付随）: `document_url` の空userinfo（`https://@host/...`）とobserved_atより未来の `pubdate` を拒否する。前者は `or parts.username` が空文字を偽と判定して素通ししていた。後者はproviderの異常値が研究handoffの基準時刻になるのを防ぐ（時計ずれ許容5分）。

Decision（付随）: change Issue本文に `latest_title`、`latest_published_at`、`latest_document_url` を含める。従来は変更されたfield名しか出ず、何が開示されたか本文から分からなかった。

Decision（付随）: workflowの `analyze` stepを `continue-on-error` とし、`notify` を `always()` にする。実測で、handoff先がPDFでanalyzeが失敗すると `notify` がskipされchange Issueが届かなかった。analyzeの失敗は通知後に別stepで再表面化する。

Consequences: 新資料が先頭へ追加されればfingerprintは必ず変わり、2026-08-13の見逃しは再現しない。実測で初回observationは `id=1275226`、`2027年３月期第１四半期決算短信〔日本基準〕(非連結)`、`2026-08-13T15:30:00+09:00` を取得し、2回目は `no_change`。取得は平日1日1回、robots.txtと合わせて2 requestに留まる（change検知日も、pipelineがindexを再取得しないため2 requestのまま）。`total_count` はfingerprintに入るがproviderの返却件数であり、`limit` 到達後は沈黙防止として機能しない。IP pinning、TLS SNI、DNS rebinding、redirect、append-only bundle、pending、stale acknowledgementの境界は変更しない。document本体の取得可否は未解決のHuman例外案件として残る。

## ERS-ADR-0027

Date: 2026-08-15

Status: Accepted

Context: 通常日のstale閾値36時間は、runの間隔から導いたものではなく手で選んだ定数だった。ERS-ADR-0026で通常日のdue slotを1営業日1回に固定した結果、成功間隔は24時間となり、遅延余裕は12時間しか残らない。実測では、土曜11:55の成功を起点に月曜17:17は17.3時間で健全だが、月曜が欠けると火曜17:17で41.3時間となり閾値超過で `stopped` になる。1日欠けただけでHuman acknowledgementが必要になる設計であり、2026-08-13にevent当日閾値12時間で3日間停止した構造と同じである。ERS-ADR-0025の時点でこの遅延余裕の無さは指摘されていたが、閾値を変えず先送りした。

Decision: stale閾値はrunの間隔から導く。通常日の閾値を36時間から60時間へ変更する。成功間隔24時間に対し、単発の欠落は自動で回復し、連続2日の欠落で停止する。event window（24時間）とevent当日（12時間）は成功間隔が4時間であり、それぞれ5回・2回の欠落を吸収できるため変更しない。

Consequences: 監視が完全に沈黙した場合、最初に実行されたrunが停止を検知する時点は2営業日後から3営業日後へ遅くなる。observationが失敗したrunは閾値と無関係に即座にerror Issueを起票するが、workflowの `notify` は `if: always() && steps.run-monitor.outcome == 'success'` であり、`run-monitor` step自体またはそれ以前のstep（checkout、pip、`monitor-fetch-state`）が落ちた場合はIssueが出ず、stale閾値が唯一の検知経路になる。この穴の大部分はERS-ADR-0028で塞ぐ。acknowledgementが定常運用に入り込まなくなる。event窓の閾値、observation、robots、append-only、pendingの扱いは変更しない。

なお、cronが1営業日おきにしか起動しない劣化（間隔48h）は60h閾値では健全に見える。36hでは停止していたが、その停止は「1日欠落で毎回停止する」副作用と同じ現象であり、間隔の劣化はstale閾値ではなくrun頻度そのものを見る指標で検出すべき課題として残す。

## ERS-ADR-0028

Date: 2026-08-15

Status: Accepted

Context: change/errorのIssue通知は検証済みbundleを前提とする。workflowの `notify` は `if: always() && steps.run-monitor.outcome == 'success'` であり、`run-monitor` step自体が落ちた場合やcheckout・pip・`monitor-fetch-state` が失敗した場合はbundleが存在せず、Issueが1件も出ない。job失敗はActions上では見えるがrepositoryの通知経路には現れず、stale閾値が唯一の検知手段になる。これは2026-08-13の見逃しと同じ「静かに失う」系統である。

Decision: `monitor-notify-workflow-failure` を追加し、jobが失敗し通常通知が届かなかった場合だけ起票する。dedup keyは `(target_id, "workflow_failure", JST日付)` から作り、1日1 targetにつき1 Issue、同日の再発はcommentにする。本文は `run_result=not_recorded`、`confidence=none`、`requires_human_decision=true` を明示し、「この runは何も観測していない。no_changeと読まないこと」を必ず含める。既存の3回retryとreceipt生成の仕組みをそのまま使い、receiptもartifactへ保存する。

通知の理由を3つに分ける。`no_bundle`（bundleを作る前に失敗）、`notification_failed`（bundleは作れたがIssue配信が3回とも失敗）、`pipeline`（targetが1件も観測されなかった）。`notification_failed` のときに「何も観測していない」と書くと、artifactに実在するchangeを過小評価させるため、本文を分ける。3つとも「`no_change` と読まないこと」と `requires_human_decision=true` は共通にする。

monitor job内のstepは、jobがcancelされた場合（timeout含む）は `failure()` が偽になり発火しない。plan jobが失敗してmonitor jobがskipされた場合はstep自体が実行されない。この2つは「targetが1件も観測されない」最悪ケースなので、`needs: [plan, monitor]` の独立job `report-pipeline-failure` で通知する。monitor jobの `failure` は除外する。in-job stepが既に通知しており、含めると1つの障害で2 Issueになる。

skipの扱いには条件を付ける。monitor jobは `needs.plan.outputs.matrix != '[]'` でskipされるため、**その日dueなtargetが無いという正常な結果でもskipになる**。matrixが空でないときのskipだけを異常として扱う（ERS-ADR-0031）。

Consequences: 次の障害はHumanに届く。`run-monitor` step自体のcrash、`monitor-fetch-state` の失敗、Issue配信の失敗、plan jobの失敗、monitor jobのcancel／timeout、monitor jobのskip。届かない障害は次に限られる。monitor job内のcheckout／setup-python／pipが失敗した場合（CLIが存在しないため通知stepも実行できない。ただしこのときplan jobは成功しmonitor jobはfailureなのでworkflowは赤になる）、`report-pipeline-failure` job自身のcheckout／pipが失敗した場合、workflowが一度も起動しない場合（Actions停止、schedule無効化）。最後のケースは依然としてstale閾値が唯一の検知経路である。observation、robots、append-only、pending、stale閾値、承認gateは変更しない。

## ERS-ADR-0029

Date: 2026-08-15

Status: Accepted

Context: ERS-ADR-0026で `ICECO_IR_CALENDAR` を含む3 targetをretireしたが、判定の根拠は「静的HTMLに資料一覧が無い」であり、日程についてではなかった。実測すると `https://www.iceco.co.jp/ir/calendar/` はserver-rendered HTMLに決算発表予定日を持つ（2026-05-13、2026-08-13、2026-11-13、および日付未確定の2027年2月中旬）。robots許可の承認済みドメインであり、当初設計の「発表予定日と日程変更の検知」という役割は成立していた。retireは役割の判定を誤ったものである。また `ICECO_TDNET_INDEX` の `event_date` は空で、次回発表日を誰かが手で入れる必要があった。

Decision: 新category `earnings_calendar_html` と新target `ICECO_EARNINGS_CALENDAR` を追加する。既存 `company_ir_calendar` の意味は変えない（他targetへの副作用を避けるため）。parserは可視テキストから `YYYY年M月D日` と直後40文字以内の `決算発表` を対にして抽出し、定時株主総会などは除外する。`2027年2月中旬` のように日が無い行は日付を捏造せず `approximate_rows` として数える。`期`（2027年3月期）を日付末尾と誤認しないよう、日か上旬／中旬／下旬／初旬／末だけを日付部分として認める。

fingerprintはページ全体のdigestを使わず、抽出した日程を対象にする（generic parserが読む `<title>` とmetaは従来どおり残る）。page digestだとフッターやバナーの変更でも `change_detected` になり、日程監視がノイズになる。決算発表行が1件も取れない場合、およびHTML以外のcontent-typeで返された場合はfail-closedとする。

ラベルは日付と同じテキストノードの残り、または日付がセルを占める場合は次のノードだけから取る。ページ内の別の場所にある「決算発表資料はこちら」が無関係な日付（定時株主総会など）に結び付くのを防ぐため、窓の長さではなくセル境界で区切る。ラベルが長い場合は行を捨てず、保存する文字列だけを切り詰める。

日が無い行は件数ではなく値ごと `approximate_schedule` に記録する（`2027-02-中旬=...`）。件数だけだと、実ページで唯一日付未確定な第3四半期の行がどこへ動いても検知できない。日付の捏造はしない。

観測した日程から `ICECO_TDNET_INDEX` の `event_date` に 2026-11-13 を記録する。registryはHuman所有のread-only configであり、監視コードは書き込まない。

Consequences: 平常日の取得は2 target×1枠=2 fetch/日、event windowとevent当日は7 fetch/日。日程が動けばfingerprintが変わりIssueが出て、本文の `earnings_schedule` に**変更後**の日程が出る。旧値は本文に出ないため、差分を見るには前世代のartifactを参照する必要がある。`analyze-earnings-handoff` は `earnings_calendar_html` でもdiscoveryを実行しない（日程ページに解析対象documentは無く、実行すればhardened adapter外の再取得になる）。日程が変わったときにregistryの `event_date` を書き換える人の作業は、ERS-ADR-0032で解消する。

## ERS-ADR-0030

Date: 2026-08-15

Status: Accepted

Context: `content_ambiguous` は、fingerprintが一致するのにETag・Last-Modified・Content-Lengthのいずれかが前回と食い違うときのエラーである。この経路ではcheckpointの `replacement_detection` しか更新されず、観測したindicatorは捨てられていた。したがって次回以降のrunも同じ古い値と比較し続け、**一度発生すると永久にerrorのまま**になる。`last_success_at` が凍結するため、通常日なら60営業時間で `state_unavailable` → `stopped`（FATAL）となり、Humanのgap acknowledgementなしには復帰しない。

ERS-ADR-0029でカレンダーのfingerprintを日程だけに絞ったことで、この経路が現実に踏まれるようになった。日程以外のページ編集はfingerprintを動かさないが `observed_content_length` は動くためである。実測では、フッター文言の変更1回で3日後に `stopped` に到達した。実ページの応答にはETagもLast-Modifiedも無く、判定は本文バイト長だけに依存する。

Decision: `content_ambiguous` のcheckpoint更新で、`replacement_detection` に加えて `observed_etag` / `observed_last_modified` / `observed_content_length` も観測値へ更新する。曖昧性の通知は従来どおり1回出すが、比較の基準は前へ進める。

Consequences: 差替えの疑いは検知した時点で1回通知され、その後は新しい観測を基準に比較が続く。1回のページ編集が監視停止に育つことはなくなる。連続して曖昧な観測が続く場合は毎回通知される。`no_change` へ落とすことはせず、fingerprint比較、pending保持、stale閾値、承認gateは変更しない。この修正は全categoryに効く。

## ERS-ADR-0031

Date: 2026-08-17

Status: Accepted

Context: ERS-ADR-0028で追加した `report-pipeline-failure` は `needs.monitor.result == 'skipped'` を異常として扱っていた。しかしmonitor jobは `needs.plan.outputs.matrix != '[]'` を条件に持ち、**その日dueなtargetが1件も無い正常な結果でもskipになる**。通常日はJST 17:17枠しかdueにならないため、他の5枠すべてがこの条件に当たる。結果として2026-08-15から3日連続で `[ERS monitor] pipeline: workflow_failure` が起票された。dedupで1日1件に抑えられていたが、内容は誤りである。

これは「何も観測していないrunを見逃さない」ための機構が、逆に「正常なrunを障害として報告する」側へ振れた例である。誤報が続く通知は読まれなくなり、本物の障害を隠す。

Decision: skipの条件を `needs.monitor.result == 'skipped' && needs.plan.outputs.matrix != '[]'` に限定する。matrixが空のskipはplan jobの設計どおりの正常終了であり、通知しない。plan jobの失敗とmonitor jobのcancelは従来どおり通知する。

Consequences: 通常日の5枠は静かになる。matrixが空でないのにmonitor jobがskipされる状態（GitHub側の異常やmatrix展開の失敗）は引き続き通知される。誤報として起票済みの3件はcloseする。monitor jobとreport jobが同じ `needs.plan.outputs.matrix != '[]'` を参照することをtestで固定し、片方だけ変更されて再発することを防ぐ。

## ERS-ADR-0032

Date: 2026-08-17

Status: Accepted

Context: ERS-ADR-0029でカレンダーから決算発表予定日を読めるようにしたが、`event_date` はHuman所有のregistry列のままで、日程が動くたびに人が書き換える必要があった。planはregistryだけを読みcheckpointを見ないため、観測した日付がwindow判定へ届かなかった。四半期ごとに人が転記する運用は、そもそも監視を自動化した目的に反する。

代案として「planは寛容に全targetを出し、monitorがstateを見てdue判定する」構造も検討した。これはjob起動が1日1回から6回へ増える。実際に必要なのは「planが日程を知ること」だけなので、planがschedule sourceのartifactを1件取得する方を採る。

Decision: `monitor_target` に `schedule_source_target_id` 列を追加する。plan jobは、registryに現れるschedule sourceのbundleを `monitor-fetch-state` で取得し、その `last_seen_schedule` から「今日以降で最も早い発表日」を求めて `event_date` を上書きする。registryの `event_date` は fallback として残す。

日が公表されていない行（`2027-02-中旬`）はISO日付として解釈できないためwindowを開く根拠にならない。日程が取れない、bundleが無い、artifactが期限切れ、checkpointがdictでない、いずれの場合もplanは失敗せずregistryの値へ落ちる。ただし**落ちたことをstderrに明示する**。fallbackは安全な方向だが、それが見えないまま古い日付で回り続けるのは、windowが開かない事故そのものである。

解決した日付は matrix の `event_date` として monitor jobへ渡し、`monitor-run-live --event-date` で stale window の計算にも使う。planだけが観測日を使い monitor がregistry列を読むと、発表当日の閾値が12hではなく60hのままになる。

`schedule_source_target_id` は自己参照、registry未登録、およびschedule source自身がschedule sourceを持つ連鎖を拒否する。plan jobに `actions: read` を付与する。

registryは引き続きread-onlyであり、監視コードは書き込まない。観測した日付はmachine stateから毎回導出するのであって、registryへ反映するのではない。

Consequences: 会社が発表日を動かすと、カレンダーtargetが次回観測でそれを取り込み、その日程でevent windowが開く。人の転記は不要になる。planのHTTPは1日あたりGitHub artifact取得1件だけ増え、外部サイトへのアクセスは増えない。取得したbundleは読むだけで、checkpointの更新も再アップロードもしない。schedule source自身は `schedule_source_target_id` を持たないので循環しない。

## ERS-ADR-0033

Date: 2026-08-17

Status: Accepted

Context: ERS-ADR-0026以降、開示の検知は自動化されたが、決算短信PDF本体の取得は保留していた。本体は `www.release.tdnet.info` と `contents.xj-storage.jp` にしか存在せず、両者のrobots.txtが `User-Agent: *` / `Disallow: /` だったためである。この保留はAI側の判断で設けたものであり、Humanの意図ではなかった。Humanは2026-08-17に「全部許可します。そもそもその辺のセーフガードはAIで勝手に設定したもので私の意図ではありません。それで作業が止まることを好ましく思いません」と明示的に承認した。

対象は法令および東証規則で公開が義務づけられた適時開示資料であり、認証も課金も個人情報も伴わない。robots.txtはcrawler向けの除外規約であって、公開済み法定開示1件の取得を禁じる法規ではない。判断は運用者であるHumanのものである。

Decision: `document_analysis/acquisition.py` に取得可否の方針をデータとして置き、request前に一箇所で判定する。承認範囲は狭く限定する。

- 取得先は `www.release.tdnet.info` と `contents.xj-storage.jp` のみ。他のhostは `AcquisitionNotAuthorized` で明示的に失敗させ、黙って読み飛ばさない
- 取得するのは**許可されたindexが既に渡したdocument URLだけ**。link追跡もdirectory走査も行わない
- 1 runあたり最大4件（`MAX_DOCUMENTS_PER_RUN`）。現状のhandoffは1件しか名指ししないので実効は1件だが、複数を渡す形へ広げたときに上限が先に効くようにしておく
- 401 / 403 / 429 / 451 は拒否であって一時障害ではないので再試行しない
- **redirectは1 hopずつ解決し、各hopの遷移先を同じ承認リストで検査する**。汎用fetcherは `follow_redirects=True` で自動追従するため、承認hostが任意のhostへ302すれば承認範囲が意味を失う（実測で確認: 承認hostから `elsewhere.invalid` への302がそのまま追従された）。hop上限は3
- 決算短信・決算説明資料以外は取得前に除外する
- document byteは従来どおり保存しない（`raw_document_retained: false`）

解析入口は `document_analysis/disclosure.py` の `analyze_named_disclosure` に置き、handoffがdocumentを名指ししていればそれを読み、していなければ従来のdiscovery pipelineへ委譲する。`analyze-earnings-handoff` はこの入口を呼ぶので、workflowの記述は変わらない。

取得は `document_analysis/guarded_fetch.py` の `GuardedDocumentFetcher` が担う。汎用の `TemporaryDocumentFetcher` は方針を知らないので、承認範囲の強制はこの層に置く。同classは `html()` も拒否する。継承したままだと、将来この fetcher を discovery pipeline へ渡した瞬間に承認外hostでlink追跡が動くためである。

人手起動の `analyze-earnings-document`（単体URL指定）は従来どおり汎用取得のままで、この承認範囲の外にある。自動運用経路ではないが、抜け道として残ることを記録する。

Consequences: 開示検知から構造化データ生成までが人手なしで通る。実測で、2026-08-13 15:30公開の第1四半期決算短信を実URLから取得・解析し、売上高15,584百万円（正規化 15,584,000,000 JPY、`q1_cumulative`、page/anchor付き）を含む34 metricを生成した。承認範囲外のhostは失敗するため、将来targetが増えても取得先が黙って広がることはない。低頻度という前提は、監視側の枠（平常日2 fetch/日）と1 runあたり4件の上限で担保される。

## ERS-ADR-0034

Date: 2026-08-17

Status: Accepted

Context: baselineは `pre_event_score` と、それを生んだはずの `scoring_version` を並べて記録し、lockする。しかし `ERS-SCORE-0.1` は18構成要素のうち5つしか重みを定義しておらず、合計は0.12だった。したがってsampleの `pre_event_score`（47.5など）は**誰も再計算できない手書きの数字**であり、`scoring_version` はその数字に一度も触れていない名前でしかなかった。

lockの目的は「後から検証できる形で事前の判断を固定する」ことである。再現できない数字をlockしても、commitmentの見た目だけが残って中身がない。`CLAUDE_AUDIT_CHECKLIST.md` の「score rootsが `scoring_version`／`score_definition`／`evidence` を通じて追跡可能であること」も、現状では成立していなかった。

Decision: `scoring/pre_event.py` に導出を実装し、**lockされたbaselineは自身の `scoring_version` から再計算できなければならない**というvalidator規則を追加する。再現できない場合はblocking errorとする。draftは検討中なので対象外。

重みは符号付きとする。スコアを下げる要素は負の重みを持つ（`meme_overheat_penalty` は既に -0.08 で記録されており、この読み方を裏付けている）。方向をデータに置くことで、覚えておくべき暗黙の規約を作らない。符号付き重みの合計は1.0でなければならない。全要素が同じ値なら合成スコアもその値になり、構成要素と同じ尺度に留まる。

`missing_value_policy` は空欄の扱いを決める。`require` と `human_review` は機械が埋めてはならないので失敗させる。`neutral` は宣言されたmin/maxの中点を使い、`exclude_with_note` は要素ごと重みから外す。除外後に残る重みが宣言合計の半分（0.5）を下回る場合は失敗させる。残りが小さいまま再正規化すると生き残った要素が無制限に拡大され、実測では正の要素を全て除外しペナルティを最大にした行が100.0（最良）に、重み合計0.04では700.0になった。

記録値と導出値は**厳密に一致**しなければならない。導出値は既に0.1刻みなので、許容差は丸めの余裕ではなく検出されない改竄になる。legacy形式のCSVにはlock hashが無いため、比較が見逃したものは回復できない。実測で、許容差0.05は導出58.0に対する58.05の記録を素通しした。

符号付き重みの合計が1.0でも**値域は保証されない**。ペナルティがあるため合成値は構成要素の尺度（0〜100）を出うる（現行のplaceholder重みでは -24.0〜124.0）。尺度外になる行は失敗させる。`pre_event_score` 列はmin 0 / max 100なので、そのような行はどの値を書いてもlockできない。本番のscoring versionは値域が保たれるように重みを設計する必要がある。

sampleの `ERS-SCORE-0.1` に不足13要素を追加して合計1.0にし、6件のbaselineの `pre_event_score` と `baseline_record_hash` を再計算した。追加した重みはchange_reasonのとおり **placeholderであり本番の重みではない**。架空企業のテストデータなので、これは方法論の決定ではない。実際の重みは、本番の scoring version を定義するときにHumanが決める。

同じ問題が `pre_event_grade` と `pre_event_decision` にも残る。スコアからgradeへの閾値はどこにも定義されておらず、これらも導出できない。sampleのgradeは新しいスコアに対しても単調（37.2 D / 42.0 D / 53.2 C / 58.0 C / 79.1 B / 82.4 B）なので矛盾は生じていないが、再現可能ではない。閾値表は重みと同じく方法論の決定なので、本ADRでは決めない。

既にlock済みのbaselineがある状態でこの規則を導入すると、`pre_event_score` と `baseline_record_hash` の両方を書き換える必要が生じ、それはlockが禁じる操作そのものになる。repo内の既存baselineはsampleだけなので今回は問題にならないが、本番データが存在する状態で同種の規則を追加する場合は、旧scoring versionを `effective_to` で閉じ、新しいversionで新しいbaselineを起こすこと。既存のlock行は書き換えない。

Consequences: lockされたスコアは監査時に再計算できる。`explain()` が要素ごとの寄与を返すので、スコアの内訳を後から説明できる。**本番運用の baseline をlockするには、全18要素を被覆し合計1.0になる scoring version が先に必要**になる。これは方法論の決定であり、機械が代行しない。2026-11-13のICECO Q2 baselineをlockする前に決める必要がある。

## ERS-ADR-0035

Date: 2026-08-25

Status: Accepted

Approval: Humanは、`earnings-research-os`を別系統で維持せず、蓄積データと有用な研究出力能力をERSへ移植し、検証完了後に旧repositoryを停止・Archiveする方針を承認した。

Context: 旧OSには254件の日本株決算記録、翌日・5日・20日価格反応、AI分類、dashboard、weekly report、note draft生成がある。一方、正確な発表時刻、formal evidence、baseline lock、provider provenance、corporate action確認を持たず、現在の厳密なERS recordと同じ品質を主張できない。旧workflowとAPI処理を丸ごと移すと、ERSで完成済みの監視、資料解析、評価、市場反応追跡と二重化する。

Decision: [LEGACY_OS_INTEGRATION.md](LEGACY_OS_INTEGRATION.md)に従い、旧OSのGit repositoryはmergeしない。固定source commitの`records.csv`をbyte-for-byte snapshotとして保存し、全recordへ`dataset_origin=earnings-research-os`、`record_mode=legacy_observational`、source row hash、Git first-seen／last-changed provenanceを付ける。raw snapshot、normalized legacy view、derived aggregation／publishing viewを分離する。29列は[LEGACY_OS_COLUMN_MAPPING.md](LEGACY_OS_COLUMN_MAPPING.md)に従い、意味・時点・出典が不足する値をprospective schemaへ昇格させない。旧dashboard、weekly report、note draftの利用価値はERS側で再現するが、daily AI selection、yfinance enrichment、旧Actions、automatic Issue publishingは移植しない。

TSOとの結合可能性は0件前提にせず、254件の`code + date`を候補としてcoverageを測る。ただし、発表時刻が無い行ではevent当日TSO値を使わず、source commit、row hash、recorded time、mapping versionを満たすpoint-in-time snapshotだけをread-onlyで結合する。legacyとprospectiveは既定で別cohortとし、TSOへ書き戻さない。

Consequences: workflow run `32839916267`とcommit `a738d2ded66e790fba5d155b5f50a50df7a81dc6`を固定し、254件のlossless import、29項目のGit履歴、TSO context 254件、3出力のbyte-level parityをERS側で実装した。旧scheduled workflowはERS mainへのmerge後に停止し、旧データや履歴を削除しない。旧repositoryのArchiveはworkflow停止とmain再検証後の最終cutover操作とする。独立監査は統合能力が完成した時点で1回行う。
