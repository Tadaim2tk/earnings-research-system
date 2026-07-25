# Obsidian Cache Staleness Policy

## Status

`Proposed`. 本書はlint仕様だけを定義し、lint codeやVault自動修正を実装しない。

## 目的

`hot.md`をFast Read用の再生成可能cacheとして維持し、削除・merge済みbranch、古いcurrent status、欠落link、古いERS commitが正本のように読まれることを防ぐ。

## 原則

- cacheは履歴、decision、source、merge状態の正本ではない。
- GitHub/Git execution state、domain index、source noteを正本として照合する。
- staleを検出しても自動修正しない。
- lintはmachine findingとHuman review itemを出し、patch proposalを作る。
- cache findingはprocess evidenceでありmarket evidenceではない。

## Machine-checkable checks

| check_id | condition | severity | evidence | proposed response |
| --- | --- | --- | --- | --- |
| `deleted_or_merged_branch_still_current` | `pilot_branch`がremoteに存在しない、または対応PRがmerged/closed | warning | branch/PR state | current branchを除去・更新するpatch proposal |
| `current_status_mismatch` | cache statusとPR/branch/task stateが機械的に矛盾 | warning | PR state、branch、frontmatter | status差替えproposal |
| `current_company_not_in_index` | current company ID/linkがdomain index registryにない | error | index registry | cacheまたはindexのHuman確認 |
| `current_event_link_missing` | Wikilink target不存在 | error | filesystem/link resolver | broken link proposal、推測pathへ自動変更しない |
| `ers_commit_stale` | commit不存在、またはapproved referenceと不一致 | warning/error | ERS `git cat-file`、approved commit | Humanへ差分提示 |
| `generated_at_missing` | `generated_at`がない/parse不能 | error | cache metadata | regeneration proposal |
| `generated_at_too_old` | active task中にage threshold超過 | warning | current time、task state | regeneration review |
| `completed_pilot_missing` | merged pilot companyがindexにありcache completed一覧にない | warning | index、merged PR registry | completed entry proposal |
| `active_pilot_already_merged` | current pilotのPRがmerged | warning | PR state | active→completed proposal |
| `source_note_missing` | Fast Read Order target不存在 | error | link resolver | load order repair proposal |
| `duplicate_current_entity` | current company/eventが複数指定 | error | cache table | Human selection要求 |

## Human review checks

| check | review question |
| --- | --- |
| task still active | PR/branchが存在してもHuman taskは完了済みではないか |
| current company semantics | currentは作業対象、review対象、直近追加のどれか |
| status wording | `draft` note lifecycleとtask進捗を混同していないか |
| completed pilot scope | merge済みとHuman content approval済みを区別しているか |
| ERS commit relevance | latest commitではなくtaskで承認されたcommitを使うべきではないか |
| cache age | 時間経過だけでなくsource stateが変わったか |
| Fast Read order | taskに必要な最小noteへ到達する順序か |
| pending/open questions | 完了済み事項を未決として残していないか |

## Freshness policy

### Immediate invalidation events

- current PR merge/close
- current branch delete/rename
- current company/event変更
- ERS approved commit変更
- indexからcurrent entity削除・replacement
- Fast Read Order target rename/delete

### Age threshold

active task中は `generated_at` から24時間を暫定warning thresholdとする。ただしageだけでstale確定や自動更新をしない。taskがinactiveならageよりexecution-state mismatchを優先する。

3社pilot完了後にactive companyがない場合、`current_status: no_active_pilot`等の正式表現をHumanが承認するまで、merged pilotをcurrentとして放置しない。

## Patch proposal format

```text
cache_path
checked_at
vault_commit
ers_commit
machine_findings
human_review_items
current_values
proposed_values
source_of_truth
unified_diff
not_applied_reason: human_approval_required
```

patch proposalはfileを変更しない。複数candidateがある場合は1つに推測せず選択肢を提示する。

## Index/hot size monitoring

cache lintは次の暫定thresholdもreportする。

```text
company_count >= 10
domain_note_count >= 60
index_size >= 20 KB
index_lines >= 250
completed_pilot_entries >= 8
total_earnings_research_wikilinks >= 300
Fast Read routing confusion > 0
measured route selection > 30 seconds
```

threshold超過はwarningであり、自動splitしない。`THREE_COMPANY_PILOT_REVIEW.md`の実測基準を参照する。

## Lint execution boundary

- default scopeは `Maruyama AI Research Lab/Earnings Research/hot.md` と関連index/linkだけ。
- TSO repositoryを変更しない。
- ERSからVaultへ自動書込みしない。
- remote API unavailable時はunknownをstaleと断定しない。
- dirty Vaultではread-only reportだけを許可し、applyを禁止する。

## Acceptance criteria for future implementation

- 3社cache fixtureでToyota stale branch/statusを検出できる
- correct current cacheでfalse positive 0
- broken event linkとmissing company registryを区別できる
- merged PRをcurrentとするcaseを検出できる
- patch proposalだけを生成しfileを書かない
- machine findingとHuman review itemを分離する
