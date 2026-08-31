# Legacy Earnings Research OS Integration

## Purpose

`earnings-research-os` に蓄積された実データと研究出力能力を、Earnings Research System（ERS）の厳密なprospective記録と混同せずに統合する。

統合はGit repository同士のmergeではない。旧OSをread-only sourceとして固定し、データ・由来・有用な集計仕様だけをERSへ移植する。旧workflow、API処理、価格取得、AI銘柄選定はコピーしない。

## Implementation Status

2026-08-26時点で、次の固定入力に対する統合実装と再現検証が完了している。

| item | fixed value |
| --- | --- |
| old OS final successful workflow run | `32839916267` |
| frozen old OS commit | `a738d2ded66e790fba5d155b5f50a50df7a81dc6` |
| TSO source commit | `f062111fe769c0104a444bb731969dc51620e115` |
| legacy records | 254 / 254 |
| source columns | 29 / 29 |
| per-field history | 254 records × 29 fields |
| TSO point-in-time links | 254 / 254, all `ok` |
| TSO historical snapshots | 88 |
| old dashboard parity | byte-equal |
| old weekly report parity | byte-equal |
| old note draft parity | byte-equal |

実装成果は`data/historical_research/earnings_research_os/v1`と`outputs/historical_research`に置く。manifestはprospective record作成0、formal evidence作成0、TSO writebackなしを明示する。

## Verified Source Snapshot

設計時点の確認対象は次のとおり。

| item | value |
| --- | --- |
| source repository | `https://github.com/Tadaim2tk/earnings-research-os` |
| source branch | `main` |
| observed source commit | `a738d2ded66e790fba5d155b5f50a50df7a81dc6` |
| source file | `data/records.csv` |
| source SHA-256 | `694a2605272bbdce950f32b19c571f269bcff92dea5238d66cbf3f2b5e294327` |
| rows | 254 |
| columns | 29 |
| unique `code + date` pairs | 254 |
| source history touching CSV | 53 commits |
| date range | 2026-06-10 through 2026-08-25 |

このcommitを、workflow run `32839916267`が作成した最終成功snapshotとして`frozen_source_commit`に固定した。

現在の充足状況は次のとおり。

| field group | populated rows |
| --- | ---: |
| AI selection and narrative fields | 254 |
| `prev_close` | 246 |
| `next_open`, `next_close`, `gap`, `ret_d1`, `shodo`, `reaction` | 245 |
| `d5_close`, `ret_d5` | 242 |
| `d20_close`, `ret_d20` | 139 |
| `result`, `error_type`, `review_note` | 0 |

全254行はGit履歴から初出commitを復元できる。245行は初出後に価格項目が追記されている。したがって、現在値だけでなく、行の初出と項目の変更履歴もmigration provenanceへ含める。

## Non-Negotiable Boundaries

各legacy recordには次を明示する。

```text
dataset_origin = earnings-research-os
record_mode = legacy_observational
```

- legacy recordをprospective baseline、formal evidence、正式なevent lifecycle、または検証済みmarket reactionとして扱わない。
- 旧値を新ERSのenumへ無理に変換しない。元値を常に残し、正規化値は別項目にする。
- 欠損を0、`unknown`以外の推測値、または現在知っている情報で埋めない。
- `rank`、`judge`、`surprise`を現行ERSのgrade、decision、overall assessmentへ直接対応させない。
- `buy_condition`と`exit_condition`はlegacy research textとして保存し、売買指示や正式なinvalidation ruleへ昇格させない。
- legacy cohortとprospective cohortを既定の集計で混ぜない。併記する場合も件数、定義、出典を分離する。
- TSOとの連携はread-only adapterとし、TSO、TSO_LOG、TSO設定へ書き戻さない。
- Vaultへ機械データを置かず、Vaultの既存差分にも触れない。

## Target Structure

実装時の配置は次を基本とする。

```text
data/historical_research/earnings_research_os/v1/
├── source/
│   └── records.csv
├── migration_manifest.json
├── legacy_records.jsonl
└── field_history.jsonl

outputs/historical_research/
├── dashboard.md
├── weekly_report.md
└── note_draft.md
```

### 1. Immutable source snapshot

`source/records.csv`は`frozen_source_commit`から取得したbyte-for-byte copyとする。列追加、文字修正、並べ替え、改行変換を行わない。

`migration_manifest.json`には最低限次を持つ。

```text
dataset_origin
record_mode
source_repository
source_branch
frozen_source_commit
source_workflow_run_id
source_path
source_sha256
row_count
column_count
header
source_first_commit
source_last_commit
migration_version
migrated_at
```

### 2. Normalized legacy view

`legacy_records.jsonl`は集計用のtyped viewであり、正本snapshotの代替ではない。1 recordは最低限次を持つ。

```text
legacy_record_id
dataset_origin
record_mode
source_row_number
source_row_sha256
source_first_seen_commit
source_last_changed_commit
raw_record
normalized_identity
normalized_classifications
normalized_prices
normalization_warnings
mapping_version
```

`legacy_record_id`はsource repository、初出commit、初出行hashから決定的に生成する。最終snapshot commitや行番号だけに依存させず、後日の価格追記でidentityが変わらないようにする。

### 3. Field history

`field_history.jsonl`はGit履歴から復元し、各項目の初出・最終変更を追跡する。

```text
legacy_record_id
field_name
first_seen_commit
first_seen_committed_at
last_changed_commit
last_changed_committed_at
final_raw_value_sha256
```

Git commit時刻は観測・発表時刻の代用ではない。あくまで「その値が遅くともsource repositoryへ記録された時刻」の証跡として扱う。

## Temporal Interpretation

旧pipelineは行作成と価格追記を別時点で行う。項目を次の3群へ分ける。

| group | columns | interpretation |
| --- | --- | --- |
| legacy selection snapshot | `code` through `memo` | AIが当日生成した選定・評価。正確な発表時刻、観測時刻、根拠sourceが無いためlocked pre-event factとはみなさない |
| legacy post-event enrichment | `prev_close` through `reaction` | yfinanceで後から補完された価格と派生値。追加commitは追跡できるが、正式なmarket-reaction contractは満たさない |
| legacy manual review | `result`, `error_type`, `review_note` | Human review用の予約欄。現snapshotでは全件空 |

旧pipelineの`prev_close`は名称と異なり、`date`と同じ取引日の終値を取得している。発表sessionが無いため、before-open、intraday、after-closeのどの基準価格に相当するかは確定できない。値は保存するが、現行ERSの`pre_event_close`や`pre_announcement_price`へ直接移さない。

`next_open`、`next_close`、`d5_close`、`d20_close`は、`date`が取引日である場合にその行から1、5、20取引行後を選んだ値である。取引calendar identity、取得時刻、corporate action確認を持たないため、legacy観測値としてのみ集計する。

## Mapping Policy

29列の個別対応は[LEGACY_OS_COLUMN_MAPPING.md](LEGACY_OS_COLUMN_MAPPING.md)に定義する。mapping statusは次の4種類とする。

| status | meaning |
| --- | --- |
| `exact_raw` | 元値を意味変更せず保存できる |
| `normalized_legacy` | 元値を残した上でlegacy専用の正規化値を作れる |
| `reference_only` | 参考情報として保存するが現行ERSの正式fieldへ接続しない |
| `unmapped` | 意味・時点・出典が不足し、正規化しない |

正規化不能な表記は`normalization_warnings`へ残す。現時点で`quarter`、`rank`、`surprise`、`company_forecast`、`narrative`、`judge`には想定enum外の表記揺れがある。

## Aggregation

legacy dataset向けに次の集計を再現する。

- 銘柄別
- legacy `rank`別
- `narrative`別
- `judge`別
- `surprise`別
- `shodo`／`reaction`別
- `rc1`〜`rc3`をまとめたreason code別
- 日付cohort別
- データ充足率とsample size

平均値だけでなく、件数、欠損数、中央値を出す。sample sizeが小さい集計は明示する。旧出力との互換表示では既存平均値を再現するが、新しい集計APIでは分母と欠損規則を固定する。

市場環境別成績は旧CSV単独では作れない。現在値から市場環境を後付けせず、point-in-time sourceが得られた行だけを別のderived linkで集計する。

## TSO Point-in-Time Join

「日本株データ0件」という前提は採用しない。254件の`code + date`はjoin候補になる。ただし、旧recordには発表時刻が無いため、次の順で適格性を判定する。

1. TSO側のsource commit、row hash、recorded time、mapping versionを確認する。
2. `code`を銘柄identityへ解決する。
3. event時刻が未確認の行では、**東証の寄り付き(09:00 JST)より前に確定した** point-in-time snapshot だけを候補にする。`usable_from_utc <= decision_cutoff_utc <= 09:00 JST` の連鎖で強制する。

   **2026-08-29 に規則を変更した(ERS-ADR-0056)。** それ以前は「発表日前までに確定した snapshot」だったが、committed 254件の実測は **234件が発表日当日**の 07:00〜08:17 JST 確定で、この規則を満たすのは20件だけである。規則とデータは最初から一致していなかった。実装(`cutoff.date() >= event_date`)は不一致を報告する代わりに移行を全件ブロックし、レポートは数週間再生成できないまま古い数字を載せ続けた。

   **この緩和が引き受けたリスク:** 寄り付き前(08:17 JST以前)の開示があった場合、そのイベントの snapshot は開示後の情報を含み得る。旧recordに発表時刻が無い以上、行ごとの検証はできない。snapshot は個別銘柄ではなく市場全体の risk-on/risk-off スコアなので影響は小さいと考えられるが、**これは測定ではなく推測である**。発表時刻を持つ行が得られれば、その行はより厳しい規則で判定できる。
4. sourceとcutoffを満たす行だけ`legacy_context_link`として別保存する。
5. join不能、複数候補、時刻不足は`not_linked`として残す。

このjoinは仮説探索用であり、prospective calibrationやTSO score変更には使わない。TSO repositoryはread-onlyで、共有CSV、symlink、自動同期、書き戻しを行わない。

## Publishing

旧OSの出力目的は維持し、実装はERSのtyped legacy viewから再構築する。

| output | retained value | change in ERS |
| --- | --- | --- |
| `dashboard.md` | 直近記録、レビュー待ち、分類別成績 | `dataset_origin`、cohort、件数、欠損を明示する |
| `weekly_report.md` | 直近7日と過去35日の経過観測 | `as_of_date`を引数化し、再現可能にする |
| `note_draft.md` | 箇条書き記事ドラフト | 公開前の編集欄と研究上の注意を残し、自動公開しない |

生成物はmachine truthではなく再生成可能なviewである。`source_commit`、`migration_version`、`as_of_date`をヘッダーへ記録する。旧Markdownのbyte一致ではなく、対象行、集計値、分母、並び順、欠損表示の意味的parityを検証する。

## Capabilities To Reuse or Retire

| old capability | treatment |
| --- | --- |
| CSVの254件 | exact snapshotとtyped legacy viewとして移行 |
| dashboard／weekly／note rendering | ERS側で再実装 |
| 銘柄別・分類別集計 | ERS側で再実装 |
| daily AI stock selection | 移植しない。現行ERSのevent-driven researchと競合する |
| OpenAI web search prompt | 移植しない。formal evidenceと時点管理を満たさない |
| yfinance price enrichment | 移植しない。現行market reaction経路と二重化し、source contractも不足する |
| `records.xlsx` | 正本として移行しない。必要ならERS viewから再生成する |
| old GitHub Actions | コピーしない。ERS parity確認後に停止する |
| Friday GitHub Issue publishing | 自動公開せず、ERS内のdraft生成までに限定する |

## Migration and Cutover

旧workflowが動いている間に件数が増えるため、次の順序を崩さない。1〜5は完了済みである。

1. **Read-only rehearsal**: 現在のsource commitでmigrationを試行し、全列、全行、履歴、出力parityを検証する。
2. **ERS capability completion**: import、validator、aggregation、3出力をERS内で完成させる。旧workflowはまだ止めない。
3. **Final source freeze**: 旧OSの最後の成功runを確認し、そのcommitを`frozen_source_commit`として固定する。
4. **Final delta migration**: rehearsal後に増えた行と価格追記を再取込し、manifest、row hashes、field historyを再生成する。
5. **Cutover verification**: 固定commitに対する行数・列数・hash・集計・3出力を再検証する。
6. **Stop old workflow**: ERS側の同等出力が確認された後だけ旧scheduled workflowをdisableする。旧データや履歴は削除しない。
7. **Observation period**: ERS側でdashboard／weekly／note draftを再生成し、旧OSを使わずに運用できることを確認する。
8. **Archive**: 最終source commitと復元手順を記録した後、GitHub上の旧repositoryをArchiveする。

workflow停止はERS mainへのmerge後に実行する。repository Archiveはworkflow停止、ERS main再検証、復元情報確認の後に行う最終cutover操作とする。

## Acceptance Tests

統合能力全体の完了条件は次のとおり。

### Losslessness

- frozen `records.csv`のSHA-256がsource commitのblobと一致する。
- headerは29列、行数はfrozen commitと一致する。
- 全raw cellがbyte-level source snapshotへ戻って照合できる。
- 全legacy recordにstable ID、source row hash、first-seen commit、last-changed commitがある。
- migrationを同じsource commitへ再実行して同じnormalized outputを得る。
- source commitが変わる場合は既存snapshotを上書きせず新しいmigration versionを作る。

### Separation

- 全行に`dataset_origin=earnings-research-os`と`record_mode=legacy_observational`がある。
- prospective baseline、evidence、event、evaluation、market reaction、learningの既存recordを変更しない。
- legacy valuesを現行ERS scoreやdecisionへ自動昇格しない。
- legacyとprospectiveを既定で混合集計しない。
- TSO、TSO_LOG、Vaultに差分を出さない。

### Output parity

- dashboardの直近20件、レビュー待ち件数、分類別平均が旧出力と一致する。
- weekly reportの7日窓と35日経過観測が同じ`as_of_date`で一致する。
- note draftの対象行、並び順、n>=3の集計条件が一致する。
- 全出力にsource commit、migration version、record modeを表示する。

### Regression

- 既存sample validationが成功する。
- 既存testがすべて成功する。
- migration専用negative testsが、列欠落、row hash不一致、件数不一致、enum誤昇格、cohort混在を拒否する。
- 旧Actionsや旧API呼出しがERSへ追加されていない。

## Implementation Unit

次の実装は「旧決算研究OS統合能力」1件として扱う。内部checkpointは設けるが、細かなPRへ分解して利用者価値を未完成のまま残さない。

```text
lossless import
→ provenance validation
→ legacy-only aggregation
→ dashboard / weekly / note reproduction
→ final delta migration
→ cutover verification
```

独立監査はこの能力の最後に1回行う。再現可能な重大問題があれば、その問題だけを修正し、Pass後は統合能力を完成として閉じる。
