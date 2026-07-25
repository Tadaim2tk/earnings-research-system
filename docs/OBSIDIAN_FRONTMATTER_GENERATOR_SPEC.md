# Obsidian Frontmatter Generator Specification

## Status

`Proposed`. 本書は仕様だけを定義し、generator code、template、plugin、Vault変更を行わない。

## 目的

3社18noteで270回発生した共通field反復を削減し、company ID、date、branch、statusのcopy-paste driftを減らす。semantic判断は自動化しない。

## 対象範囲

- 対象はERS管理下の `Earnings Research/` 新規noteだけ。
- 既存noteのmigrationや上書きには使用しない。
- Vault rootはHumanが明示し、生成器が探索・推測しない。
- ERSとVaultの外へ書き込まない。
- TSO repositoryを読まない、変更しない。

## Specification contract

本仕様のreviewと将来実装では、次のcontract keyを使用する。

```text
input
generated_output
required_human_fields
validation_rules
failure_behavior
preview_format
overwrite_policy
idempotency
rollback
audit_log
```

以下の各sectionがこの順にcontractを定義する。表記の違いから実装scopeが広がらないよう、machine-readable specを追加する場合も同じkeyを維持する。

## Input

### Machine input

```text
vault_root
output_relative_path
repository_remote
ers_commit
origin_mode
knowledge_version
current_datetime
```

`origin_mode=prospective` では、Humanが `prospective_stage=baseline_draft|baseline_lock` を指定する。generatorは本文や現在時刻からstageを推測しない。

### Required Human fields

```text
note_type
note_id
entity_id or type-specific entity ID
knowledge_class
confidence
verified_status
owner when required
source/license status when required
published time/session when required
KPI or forecast payload when required
hypothesis when required
limitations when required
source_evidence_ids when origin_mode is prospective
```

Human fieldはgeneratorがdefault、既存note、filename、ticker、AI推論から補完しない。

## Generated output

generatorが生成できるfieldは次だけとする。

```yaml
repository_remote: <validated ERS remote>
ers_commit:
  - <existing commit>
origin_mode: <Human-selected enum>
status: draft
knowledge_version: <positive integer>
created_at: <current date>
updated_at: <current date>
reconstructed_at: <current date only when historical_reconstruction>
source_evidence_ids: <origin mode and prospective stage rule below>
```

`source_evidence_ids` はorigin mode別に扱う。

### Historical reconstruction

```yaml
source_evidence_ids: []
```

を自動生成できる。空配列はformal evidence未登録を意味し、source不存在、source不要、evidence gate通過を意味しない。

### Prospective

`source_evidence_ids` はHuman requiredとし、自動で空配列を確定しない。

- 値未入力: previewに `HUMAN_REQUIRED` errorを出し、file/patchを適用しない。
- `baseline_draft`: Humanが明示的に `[]` を入力することは許容するが、previewにevidence未登録warningを出す。
- `baseline_lock`: 1件以上のpre-event evidence IDを必須とし、空配列ではlock用patchを生成・適用しない。
- evidence IDをgeneratorがURL、title、既存noteから推測・発行しない。

## Validation rules

1. `repository_remote` は承認済みERS remoteと完全一致する。
2. `ers_commit` はERS repositoryで次に成功する。

   ```bash
   git -C <ERS_REPOSITORY> cat-file -e <ERS_COMMIT>^{commit}
   ```

   `<ERS_REPOSITORY>` は実行環境設定であり永続identityにしない。永続参照は `repository_remote + ers_commit` とする。検証失敗時は生成停止、patch非適用、明示errorとし、HEADや別commitへfallbackしない。
3. `origin_mode` は既存frontmatter policyのenumに含まれる。
4. `status` は常に `draft`。generatorは昇格させない。
5. `knowledge_version` は正整数。
6. dateは実行時のlocal dateを使い、source/event dateへ遡及しない。
7. `historical_reconstruction` では `reconstructed_at` 必須。それ以外ではHuman policyに従い空欄を許容する。
8. output pathはcanonicalized後も指定Vault root配下である。
9. output path、`note_id`、entity IDが既存noteと衝突しない。
10. required Human fieldsに空欄、placeholder、未承認enumがあれば停止する。
11. semantic fieldの値をgenerator自身が作っていないことをpreview manifestで確認する。
12. prospective `baseline_lock` では `source_evidence_ids` が1件以上あり、各IDの存在とpre-event timing gateを別validatorで確認できる。

## Failure behavior

以下ではfileを書かず、non-zeroで終了し、理由とfield名を返す。

- ERS commit不存在
- Vault root不存在またはGit root不一致
- output pathがVault外
- 既存file/path衝突
- duplicate `note_id` / entity ID
- Human field不足
- enum不正
- date偽装要求
- uncommitted ERS commit参照要求
- prospective `source_evidence_ids` 未入力
- prospective `baseline_lock` でevidence IDが空または未解決
- source/license/time/sessionの推測要求

partial fileを残さない。複数note batchではall-or-nothing previewを基本とし、適用中failure時は当該runで新規作成したfileだけをrollback候補として列挙する。

## Preview format

Human承認前はfileを書かず、次を表示する。

```text
run_id
vault_root
ers_repository_remote
ers_commit
output_files
generated_fields
human_fields
unresolved_fields
collisions
validation_results
unified_diff_preview
apply_command_or_action
```

previewはgenerated fieldとHuman fieldを視覚的に分離する。`source_evidence_ids` の入力元と検証結果、`status: draft`、current dateを明示する。historical reconstructionまたはHumanが空配列を明示したprospective `baseline_draft` だけ、`source_evidence_ids: []` を表示する。

## Overwrite policy

- 既存noteを上書きしない。
- filename、`note_id`、entity IDのいずれかが衝突したら停止する。
- `--force` のようなoverride optionを初期版に設けない。
- 既存note更新はgeneratorとは別のreviewed patch workflowで行う。

## Idempotency

同一input、同一current date、同一ERS commitから同じpreviewを作る。適用後に同じrunを再実行した場合、既存file衝突として安全に停止し、内容を二重生成しない。

`run_id` はaudit用でありnote identityに使わない。current datetimeを秒単位で本文へ埋め込み、毎回diffを変える設計は避ける。

## Rollback

- 適用前: file未作成なので不要。
- 適用後・commit前: run manifestに記録した新規fileだけを削除候補としてHumanへ提示する。自動削除しない。
- commit後: Git revertまたはfollow-up correctionをHumanが選ぶ。generatorがhistoryを書き換えない。
- 既存fileは変更しないためrollback対象にならない。

## Audit log

初期版ではappend-onlyのrun manifestをERS側の非market process log候補として設計する。実装場所は別途承認する。

```text
run_id
requested_at
executed_at
requested_by
generator_version
ers_commit
vault_commit_before
output_paths
generated_field_names
human_field_names
validation_results
preview_hash
human_approval_reference
apply_result
vault_commit_after
```

audit logはmarket evidence、formal source evidence、score inputとして扱わない。

## Human approval gate

1. preview作成
2. Humanがsemantic field、IDs、source/time status、diffを確認
3. 明示的承認
4. 新規fileを適用
5. lintとWikilink検証
6. Git diff review
7. commit/PRは別承認

preview承認をstatus昇格やsource verification承認へ流用しない。

## Safe boundary

generatorは構文を生成する道具であり、research claimを生成するagentではない。KPI、forecast、hypothesis、limitations、event time、session、verification、license、score利用可否を決定しない。
