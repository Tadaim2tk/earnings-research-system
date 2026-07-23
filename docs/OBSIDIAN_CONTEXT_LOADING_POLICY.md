# Obsidian Context Loading Policy

## 原則

AIは毎回Vault全体を読まない。indexをrouting tableとして使い、対象eventに必要なnoteだけを段階的にloadする。raw sourceはclaim検証が必要な場合に限定する。

## 標準読込順序

1. `Maruyama AI Research Lab/Earnings Research/index.md`
2. `Maruyama AI Research Lab/Earnings Research/hot.md`
3. 対象Company note
4. 対象Earnings Event note
5. 関連Management Guidance Pattern
6. Peer Group / Industry / Sector Driver
7. 必要なKPI note
8. relevant Failure Mode / Validated Finding
9. 必要なSource note
10. claim verificationが必要なraw file

TSO contextが必要な場合だけ、既存TSO domain index、Asset、regime/Meaning Spaceへ移る。

## Progressive loading

各段階で次を判断する。

- taskに必要なentityが特定できたか。
- claimのsourceとreview statusが分かるか。
- conflicting noteが示されているか。
- より深いsource読込が本当に必要か。

十分ならそこで停止する。graph traversalのdepthを無制限にしない。

## `hot.md` content

- 現在の対象銘柄
- 直近の決算event
- 未完了task
- 最近変更したhypothesis
- review待ちnote
- 現行scoring version
- ERS latest approved commit
- TSO mapping version
- 重要open question
- cache generated_atとsource note list

`hot.md` にdecision本文、唯一のsource、過去review履歴を置かない。削除してもindexとsource noteから再生成できるcacheとする。

## Task別context pack

| task | minimum context |
| --- | --- |
| pre-earnings baseline | Company、Event、Guidance Pattern、Peer/Industry、KPI、Failure Mode、pre-cutoff source |
| post-earnings review | Event、locked baseline reference、actual KPI、Price Reaction、Hypothesis |
| company pattern review | Company、複数Event、Management Pattern、counterexamples |
| score policy review | ERS ADR/scoring version、Validated Findings、Failure Modes |
| source audit | Data Source、manifest、evidence IDs、license status |
| TSO/ERS comparison | 両domain index、shared company ID、mapping version、term aliases |

## Temporal filter

pre-event taskでは、noteの現在内容をそのまま使用しない。claimごとのsource timeとERS baseline cutoffを確認し、cutoff後のOutcome、Lesson、Knowledge Updateをcontextから除外する。

`origin_mode=historical_reconstruction` はprospective context packおよびprospective calibration cohortから機械的に除外する。historical reconstruction内では、現在知っているoutcomeを別context blockに隔離し、当時利用可能だったsourceだけをpre-event reconstructionへ渡す。

## Status filter

- `validated`: scopeとevidenceを確認して再利用候補にできる。
- `reviewed`: human-reviewed contextだがformal ERS factではない。
- `draft`: idea discovery用。score inputへ直接使わない。
- `deprecated`: history/contradiction確認時のみ読む。

`verified_status: mixed` のnoteはsection単位で扱う。

## Context manifest

重要なAI作業では読込noteを記録する。

```text
task_id
loaded_note_ids
loaded_versions
repository_remote
ers_commit
vault_commit
cutoff_datetime
excluded_post_cutoff_notes
unresolved_conflicts
```

これにより同じ質問を後日再現し、古い `hot.md` に依存していないことを確認できる。
