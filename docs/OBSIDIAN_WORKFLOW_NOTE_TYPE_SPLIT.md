# Obsidian Workflow Note Type Split

## Status

`Proposed`. 既存noteの `note_type` は今回変更しない。

## 背景

3社pilotでは `index.md`、`hot.md`、Pilot Logが暫定的に `tool_workflow` を共有した。3者はpurpose、owner、lifecycle、loading policy、status semantics、更新契機が異なり、同一typeに置くとlintとcontext loadingが曖昧になる。

## 比較

| dimension | `domain_index` | `context_cache` | `pilot_log` |
| --- | --- | --- | --- |
| purpose | durable routing、identity registry、note catalog | current taskのFast Read cache | 作業結果、測定、設計観測の履歴 |
| owner | Human domain owner | current task owner; generation may be assisted | pilot owner / reviewer |
| status semantics | catalogのreview状態 | cache freshness。knowledge validationとは別 | process recordのreview状態 |
| update trigger | company/note追加、ID/status/replacement変更 | current task、branch、ERS commit、merge状態変更 | pilot milestoneと測定完了 |
| loading policy | domain入口として通常load | active task時だけload | 通常Fast Readではloadせず、process review時だけload |
| retention | pilot完了後も保持 | 再生成可能。削除しても正本から復元可能 | 完了後は原則固定、append-only correction |
| source requirements | cataloged noteとidentity registry | source note ID、generated_at、参照commit | process evidence、measurement source、commit/PR |
| market evidence | ならない | ならない | ならない |

## `domain_index`

### Purpose

- domainのdurable routing
- company identity registry
- note catalog
- status/replacementへの入口
- cacheではなく、pilot完了後も保持

### Required frontmatter

```text
note_type: domain_index
note_id
entity_id
workflow_id
owner
status
knowledge_class: [knowledge_update]
created_at
updated_at
source_evidence_ids: []
repository_remote
ers_commit
knowledge_version
```

`origin_mode` はcatalog内容にhistorical noteが含まれることとindex自身のoriginを混同しないよう、migration ADRで最終決定する。初期migrationでは既存値を保持し、意味変更を同時に行わない。

### Lint rules

- duplicate identity / note ID禁止
- catalog link target必須
- company noteとidentity registryのticker/company ID一致
- deprecated/replaced noteのcurrent表示警告
- index size threshold監視
- cache専用field (`generated_at`, current branch) を正本として要求しない

## `context_cache`

### Purpose

- current taskだけを保持するFast Read cache
- current company/event、最小load順、active unresolved itemを示す
- 履歴、source、decisionの正本にはしない

### Required frontmatter

```text
note_type: context_cache
note_id
entity_id
workflow_id
owner
status
knowledge_class: [knowledge_update]
created_at
updated_at
source_evidence_ids: []
repository_remote
ers_commit
knowledge_version
```

本文必須metadata:

```text
generated_at
current_company
current_event
current_status
pilot_branch or explicit no-active-branch
source_note_ids
```

### Status semantics

`status` はknowledge validationではなくcache review状態を示す。将来は `fresh/stale` を別fieldとして設ける案をHuman reviewする。`validated` をcache freshnessの意味に流用しない。

### Lint rules

- stale branch/current status/merge mismatch
- current companyがdomain indexに存在
- current event link存在
- `generated_at`存在とage policy
- ERS commit存在
- completed pilotとactive pilotの矛盾
- source noteなしの唯一情報を禁止

stale発見時は自動修正せずpatch proposalを作る。

## `pilot_log`

### Purpose

- 作業時間、note数、link数、validation、摩擦、設計観測を記録
- process evidenceでありmarket evidenceではない
- pilot完了後は原則固定

### Required frontmatter

```text
note_type: pilot_log
note_id
entity_id
workflow_id
owner
status
knowledge_class
created_at
updated_at
source_evidence_ids: []
repository_remote
ers_commit
knowledge_version
```

### Lint rules

- measurementにsourceまたは `not_measured` がある
- Human時間とagent-assisted時間を混同しない
- market evidence IDを発行しない
-完了後の既存値上書きを警告
- correctionは理由、旧値、新値、updated_atを残す
-通常Fast Read manifestへの自動loadを禁止

## Allowed knowledge class

| type | allowed |
| --- | --- |
| `domain_index` | `knowledge_update` |
| `context_cache` | `knowledge_update` |
| `pilot_log` | `observed_fact`, `knowledge_update`, 必要時のみ `decision` |

`raw_source`、`outcome`、`hypothesis`をworkflow note typeのprimary classにしない。

## 移行方法

### Phase 0: current state

既存 `tool_workflow` を維持し、本仕様をHuman reviewする。

### Phase 1: policy and lint preparation

1. `OBSIDIAN_KNOWLEDGE_MODEL.md` とfrontmatter policyへ新typeをProposed追加
2. type別required fieldとloading/lint ruleをtest fixtureで検証
3. migration previewを作成

### Phase 2: existing note migration

- `Earnings Research/index.md`: `tool_workflow` → `domain_index`
- `Earnings Research/hot.md`: `tool_workflow` → `context_cache`
- 3社Pilot Log: `tool_workflow` → `pilot_log`

本文、ID、status、dates、ERS referenceは同時に変更しない。typeだけの独立commitにする。

### Phase 3: verification

- all links / duplicate IDs / enum / required fields
- Fast Read regression for 3 companies
- `hot.md` staleness test
- context manifestからPilot Logが通常除外されること

### Rollback

migration commitをrevertし、既存 `tool_workflow` へ戻す。IDやpathを変えないためlink rollbackを不要にする。

## 判定

型分割の方向は妥当だが、既存policy、lint、3社noteへ波及する。Human承認と独立migration taskまで `Proposed` とし、今回実変更しない。
