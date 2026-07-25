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

Consequences: event rowとbaselineを上書きせず、延期履歴、cancelled除外、occurred gateをdataset-levelで検証できる。activated prospective eventを含むcomplete datasetにはstatus history fileが必要になる。terminal statusの誤記録訂正、cross-file lineage、return計算、自動calibrationは未実装であり、本ADRのAccepted statusだけではprospective運用開始を承認しない。

Alternatives Considered: event rowへcurrent statusを追加する方式Aは単純だが履歴を上書きしやすい。event全体をversion化する方式Cはbaseline versionとidentity semanticsが衝突する。独立history tableがappend-onlyとlegacy event互換性を最も明確に保つため方式Bを選ぶ。
