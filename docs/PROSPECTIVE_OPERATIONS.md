# Prospective Operations

## Status

第1号prospective pilotは `Conditionally ready` である。本書は運用開始条件を定義するが、event選定、実evidence登録、baseline作成、lock、post-event reviewを自動承認しない。

## Scope And Truth Boundary

第1号では手動・metadata-only運用に限定する。

本書を第1号prospective pilotの運用契約の正本とする。関連文書は要約と本書への参照だけを持ち、同一規則を複製しない。

```text
machine-data truth = ERS CSV / schema / Git
operational evidence = PROSPECTIVE_PILOT_LOG.md
knowledge layer = Obsidian Vault
TSO = read-only external source
```

ERSからTSOまたはTSO_LOGへ書き戻さない。Vaultは機械データ正本にせず、既存3差分を含む別repositoryとして扱う。

## Provider Terms Policy

本節は法的な包括判断ではなく、第1号pilotを保守的に運用するための内部方針である。公開情報であることと、保存、二次利用、AI入力、自動取得が許可されることを同一視しない。

### Terms Review Record

sourceごとに次を別々にHumanが記録する。未確認項目を他の許可から推測しない。

```text
source_name
source_category
viewing_permitted
metadata_recording_permitted
raw_storage_permitted
redistribution_permitted
ai_raw_input_permitted
automated_access_permitted
terms_checked_at
terms_checked_by
terms_reference
recheck_trigger
terms_review_state
```

`terms_review_state` は次のいずれかとする。

```text
policy_defined
candidate_specific_review_pending
candidate_specific_review_completed
rejected
```

- `policy_defined` は本書の一般方針だけが定義済みであることを示す。
- `candidate_specific_review_pending` は具体的なsource候補があるが、利用条件のHuman確認が未完了であることを示す。
- `candidate_specific_review_completed` は対象sourceと利用方法を特定したHuman確認が完了したことを示す。
- `rejected` は確認結果により予定用途へ使用しない判断をHumanが記録したことを示す。

現時点では会社公式IR、TDnet、具体的な価格表示元、J-Quantsのいずれも、第1号candidate固有の利用条件を確認済みまたは利用許可済みとは扱わない。

第1号のdefaultは次のとおりとする。

```text
raw_storage_permitted = false
redistribution_permitted = false
ai_raw_input_permitted = false
automated_access_permitted = false
```

`viewing_permitted` と `metadata_recording_permitted` はcandidate固有のprovider条件をHumanが確認するまで未承認とする。次の場合はterms reviewを再実施する。

- 新sourceを追加する。
- 規約改定を認知する。
- 利用方法を変更する。
- raw保存へ移行する。
- 自動取得へ移行する。

### Company Official IR

許可候補用途:

- event予定確認
- 公式資料の存在確認
- event発生確認
- 表題、URL、公開日時等の最小metadata記録

条件:

- candidate選定時にissuerサイトの利用条件をHumanが確認する。
- raw保存、自動取得、再配布、raw documentのAI入力をdefaultで禁止する。
- 利用条件が不明なら停止する。

### TDnet Timely Disclosure Viewing Service

許可候補用途:

- Humanによる手動閲覧でevent発生確認を補助する。
- 会社コード、開示表題、表示日時、URL等の最小metadataを、条件確認後に記録する。

禁止:

- raw PDFのERS repository保存
- 自動巡回または大量取得
- 再配布
- TDnetページ本文またはdataの大量AI入力
- TDnet APIまたはTDnet DBSの利用

TDnetは正式な開示経路だが、自由な二次利用を意味しない。会社公式IRをprimary候補とし、TDnet手動閲覧はoccurrence確認の補助候補として扱う。

### First Pilot Exclusions

次は第1号pilotのscope外とする。

```text
J-Quants API
J-Quants Pro
TDnet API
TDnet DBS
automated scraping
raw disclosure storage
raw disclosure redistribution
unreviewed price provider
```

J-Quantsは保存、AI処理、二次利用等の具体的な契約条件のHuman確認が未完了であるため採用しない。

### Price Source

- 第1号は `manual price entry` とする。
- candidate選定時に具体的な価格表示元を1つ決め、利用条件を個別確認する。
- price source未確定のままbaselineを開始しない。
- event時点までに確定できないcandidateは見送る。
- 利用条件未確認の価格、chart screenshot、raw row、derived VWAPを保存しない。

## Evidence Storage Mapping

第1号のformal evidence metadataは、現行schemaに存在する次のbundleへ固定する。

```text
raw_storage_status = metadata_only
raw_location = empty
content_hash_status = not_recorded
content_hash = empty
content_hash_algorithm = empty
```

`license_status` はHuman terms reviewの結果に対応する現行enumを記録する。未確認時は `unknown` または `review_required` とし、`used_for_score=true` にしない。

- source URLは `source_url` に記録する。URLは `raw_location` ではない。
- raw保存判断を変更する場合は作業を停止し、別承認を得る。
- AI要約はformal evidenceまたはprimary sourceにしない。
- `metadata_only` はrawの存在、内容、hashをERSが独立証明する状態ではない。
- raw実体確認とhash再計算は未実装である。

## Role Assignment

| role | 第1号担当 |
| --- | --- |
| event selector | Human |
| source terms reviewer | Human |
| evidence recorder | Human |
| baseline author | Human with AI drafting support |
| Human reviewer | Human |
| lock operator | Human |
| event monitor | Human |
| post-event reviewer | Human |
| incident owner | Human |

AIへ許可する作業:

- 候補整理
- 文書起草
- field入力案
- validator実行支援
- diff確認支援
- missing itemの指摘

AI支援へ渡せるのは、Humanが利用条件を確認した最小metadata、Human作成の要約、ERS内部fieldだけである。raw document、TDnet page本文、provider raw dataは入力しない。

AIへ委譲しない判断:

- provider termsの最終判断
- event選定承認
- `used_for_score`承認
- Human review承認
- baseline lock承認
- `occurred`の最終認定
- incidentの継続または停止判断
- stop／resumeの承認
- post-event reviewの確定

AIはこれらの判断案を提示できるが、Human承認済みとして記録してはならない。

### Combined Roles

第1号では同一Humanが複数roleを兼任できる。`baseline author == Human reviewer` の場合は次をすべて必須とする。

- Human review checklistを全項目実施する。
- validator成功を確認する。
- Git diffをreviewする。
- lock対象rowとevidence relationshipを再確認する。
- pilot logへ自己承認であることを記録する。
- AI提案を根拠に自動承認しない。

reviewerには個人本名ではなく、pilot開始前に固定した安定identifierを使う。実identifierはevent選定前にpilot logへ記録し、未決のまま推測作成しない。

## Event Monitoring

第1号はHumanによる手動監視とする。event選定時に次を記録する。

```text
primary_calendar_source
primary_occurrence_source
secondary_confirmation_source
```

会社公式IRをprimary候補とし、TDnet手動閲覧をsecondary occurrence確認候補にできる。

監視頻度:

- 通常は毎営業日1回。
- event予定日の5営業日前から毎営業日1回以上。
- event当日は予定session前後に確認する。
- event固有の確認時刻は選定checklistでHumanが決め、ここでは発明しない。
- 自動通知は未実装である。
- 監視不能期間が見込まれるcandidateは選定しない。

`status_recorded_at` はHumanが変更を実際に認知して記録した時刻とする。過去時刻へ偽装しない。延期または中止の根拠sourceをevidenceとして記録し、不確実ならstatusを推測更新せず停止する。

## Evidence Registration Rules

### Evidence ID

```text
EVD-<earnings_event_id>-<3-digit sequence>
```

- sequenceは同一event内で `001` から単調増加させる。
- 欠番と削除済みIDを再利用しない。
- duplicate validationを必須とする。
- correctionとretractionにも新IDを使い、元evidenceを上書きしない。
- 本書では実event IDまたは実evidence IDを作成しない。

### Unknown `published_at`

- exact published timestampを確認できないsourceをformal score evidenceに採用しない。
- `published_at` はschema required datetimeなので、exact timestampがない状態でformal evidence rowを作成しない。
- date-onlyという制約と発見経路はcandidate note、pilot logまたは非formal noteへ記録し、machine-dataへ虚偽時刻を入れない。
- date-only sourceへformal evidence IDを発行せず、`used_for_score=false` として扱う。
- schemaを通す目的で00:00、23:59その他の架空時刻を入力しない。
- exact timestampを持つ別の公式sourceを探す。
- 見つからなければ停止するか、ERS formal evidence外のscore非利用補助sourceとして扱う。

### Raw Hash

metadata-only運用ではraw file hashを計算しない。`content_hash_status=not_recorded` とし、`verified` または `recorded_unverified` を使用しない。raw保存へ移行する場合は別承認を必要とする。

## Baseline Human Review Checklist

### Identity

- [ ] event identityが一致する。
- [ ] company、会計期間、event typeが一致する。
- [ ] candidate選定がHuman承認済みである。
- [ ] lifecycle current statusを確認した。

### Evidence

- [ ] minimum source条件を満たす。
- [ ] official sourceを含む。
- [ ] terms確認済みsourceだけをscoreへ使用する。
- [ ] prospective metadata bundleが完全である。
- [ ] `published_at <= observed_at <= recorded_at` が成立する。
- [ ] related baseline IDが一致する。
- [ ] correctionまたはretraction関係を確認した。
- [ ] AI要約を一次evidenceとしていない。
- [ ] `used_for_score` の根拠をHumanが確認した。

### Future Leakage

- [ ] evidence timestampがlock以前である。
- [ ] event後情報を含まない。
- [ ] 延期後なら最新postponement後にreviewした。
- [ ] current baseline tailが一意である。
- [ ] superseded baselineを評価していない。

### Baseline Content

- [ ] score入力根拠を確認した。
- [ ] hypothesisを確認した。
- [ ] uncertaintyを明記した。
- [ ] limitationsを明記した。
- [ ] `NO_TRADE` または見送り理由を必要に応じて明記した。
- [ ] missing dataを推測補完していない。

### Lock

- [ ] `human_review_status=approved` である。
- [ ] reviewer identifierを記録した。
- [ ] `reviewed_at` を実時刻で記録した。
- [ ] canonical hashを生成した。
- [ ] validatorが成功した。
- [ ] Git diffをreviewした。
- [ ] pilot logへ記録した。

reviewが `rejected` の場合はlockせず、理由と再開条件をpilot logへ記録する。

## Canonical Hash And Lock Procedure

現行の `_calculate_baseline_record_hash` と `load_spec` を一時運用手順として使用する。どちらもprivate implementationであり、恒久public APIではなく将来変更され得る。

生成前にrepository root、cleanなworktree、実行対象commitを確認し、commitをpilot logへ記録する。

```bash
pwd
git status --short
git rev-parse HEAD
```

対象rowはprospective baseline contractのrequired field、Human review field、lock fieldがすべて確定した状態でなければならない。row indexではなく明示的な `baseline_id` で一意に選択する。

repository rootで、対象CSVとbaseline IDを明示して次を実行する。

```bash
BASELINE_CSV=path/to/pre_earnings_baseline.csv BASELINE_ID=BASELINE-ID PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -c 'import csv,os; from pathlib import Path; from earnings_research.validation.validator import _calculate_baseline_record_hash,load_spec; p=Path(os.environ["BASELINE_CSV"]); rows=[r for r in csv.DictReader(p.open("r",encoding="utf-8-sig",newline="")) if r.get("baseline_id")==os.environ["BASELINE_ID"]]; assert len(rows)==1,"baseline_id must resolve to exactly one row"; print(_calculate_baseline_record_hash(rows[0],load_spec("pre_earnings_baseline")))'
```

仮hashを入力してvalidator errorから正解値を取得しない。手計算しない。hash生成後にCSVへ記録し、対象datasetへvalidatorを再実行する。hash生成とlock変更は専用commitにし、そのcommit hashをpilot logへ記録する。

sample rowとのhash一致確認は手順自体の動作確認に限る。sample hashを別baselineへ再利用しない。

lock順序:

```text
draft完成
-> Human review approved
-> reviewed fields確定
-> locked_at確定
-> canonical hash生成
-> baseline_record_hash記入
-> validator実行
-> Git diff review
-> dedicated Git commit
-> commit hashをpilot logへ記録
```

`locked_at` を過去へ偽装しない。

## Occurred Confirmation Checklist

- [ ] 予定時刻の経過だけで `occurred` にしていない。
- [ ] 会社公式IRまたは正式な適時開示の存在を確認した。
- [ ] occurrence根拠をformal evidenceとして登録した。
- [ ] `occurred_at` は実際の公表または発生時刻である。
- [ ] `status_recorded_at` はHumanが確認・記録した実時刻である。
- [ ] `occurred_at <= status_recorded_at` が成立する。
- [ ] event evidence登録後にstatus rowをappendした。
- [ ] 不確実な場合は `occurred` へ進めず停止した。
- [ ] 予定より早い発表ではHuman reviewを記録した。
- [ ] terminal status訂正が未実装であるため、登録前に二重確認した。

## Stop Conditions

次のいずれかに該当した場合は停止する。

1. provider termsが不明。
2. official sourceへ到達不能。
3. exact `published_at` が不明でscore利用が必要。
4. evidence timestampが矛盾。
5. metadata bundleが不完全。
6. raw保存判断が必要になった。
7. Human reviewerが不在。
8. baseline lockが新予定時刻に間に合わない。
9. lifecycle current statusが不明。
10. current baseline tailが0件。
11. current baseline tailが複数件。
12. 延期後に再reviewできない。
13. `occurred` の根拠が不十分。
14. validator errorがある。
15. ERS worktreeがdirty。
16. source correction関係が不明。
17. 監視不能期間が発生する。
18. provider規約変更の疑いがある。
19. operatorが手順を一意に判断できない。
20. AI出力以外に根拠がない。

停止時は推測して続行せず、machine-dataを無理に埋めない。incidentまたは停止理由と再開条件をpilot logへappendし、必要ならcandidateを見送る。

停止・再開entryには最低限次を記録する。

```text
stop_reason
affected_event_or_phase
evidence_reference
decision_maker
stopped_at
resume_requirements
resume_approved_by
resumed_at
```

再開は `resume_requirements` が満たされたことをHumanが確認し、`resume_approved_by` と `resumed_at` を新しいappend-only entryへ記録した後に限る。AIは停止・再開案を提示できるが、承認済みとして記録しない。

該当する場合、再開前にprovider terms、exact timestampを持つ公式source、Human reviewer、validator成功、clean worktree、current lifecycle status、current baseline tail一意性、再review完了をHumanが確認する。根拠は `evidence_reference`、未解消条件は `resume_requirements` に残す。

## Operational Record

[PROSPECTIVE_PILOT_LOG.md](PROSPECTIVE_PILOT_LOG.md) へ最低限、次を固定形式で記録する。

```text
timestamp
entry_id
corrects_entry_id
event_id
phase
actor_role
action
decision
evidence_reference
validation_result
git_commit
exception_or_stop_reason
next_gate
stop_reason
affected_event_or_phase
decision_maker
stopped_at
resume_requirements
resume_approved_by
resumed_at
```

## Candidate-Specific Gates Still Required

本書が承認されてもpilotは自動開始しない。event選定時にHumanが次を完了する。

1. 候補会社IRサイトの利用条件確認
2. 具体的な価格表示元の利用条件確認
3. reviewer identifierの記録
4. primary calendar sourceとoccurrence sourceの指定
5. 監視可能日程の確認
6. candidate選定のHuman承認
