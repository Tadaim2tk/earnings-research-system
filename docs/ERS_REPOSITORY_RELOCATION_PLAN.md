# ERS Repository Relocation Plan

## 状態と目的

Status: Completed on 2026-07-23

ERS repositoryは次の恒久保存先とprivate remoteへ移設済みである。

```text
permanent_local_path: /Users/maruyamayuuki/Documents/MaruyamaAIResearchLab/earnings-research-system
repository_remote: https://github.com/Tadaim2tk/earnings-research-system
visibility: private
preserved_head: 855ebb531d45938e1d55a201faa5dfc350d354ae
```

旧pathはrollback用copyとして保持し、今回削除しない。

```text
/Users/maruyamayuuki/Documents/Codex/2026-07-19/record-and-replay-plugin-record-and-3/earnings-research-system
```

## 移設要件

- `.git` directoryを含むhistoryを保持し、既存commit hashを変えない。
- 旧pathは移設直後に削除せず、検証期間中はread-only backupとして保持する。
- 新pathでsample validationとpytestを実行する。
- Humanが承認したprivate GitHub repositoryを `origin` として設定する。
- private remoteへのpush後、branch、HEAD commit、remote参照を検証する。
- Obsidianは `repository_remote` と `ers_commit` を永続参照とする。local pathは環境依存の実行補助に限定する。
- 移設失敗時は旧pathへ戻せるrollback手順と判定条件を記録する。

## 実施手順

1. Humanが恒久local pathとprivate repositoryを選ぶ。
2. 現repositoryのclean status、HEAD、branch、remote状態を確認する。
3. repository全体のbackupまたは検証用cloneを作る。
4. `.git` とhistoryを保持したまま新pathへ移す。
5. 新pathでvalidateとpytestを実行する。
6. Human承認済みremoteを設定する。
7. private repositoryへpushし、remote上のHEADと履歴を検証する。
8. 旧pathをread-onlyで一定期間保持する。
9. local pathを記載する運用文書を更新し、Obsidian参照をremote URL + commitへ切り替える。
10. 移設完了だけを対象とするseparate commitを作成する。

## Rollback

- 新pathのtest、remote push、commit照合のいずれかが失敗した場合、Obsidian参照を切り替えない。
- 旧pathを削除せず、旧pathのHEADとstatusを再確認して作業を継続する。
- partial remote設定は原因を記録して解除または修正し、historyを書き換えない。
- commit hashが一致しない場合は移設完了と判定せず、copy/move方法を再確認する。

## 完了確認

- 旧新repositoryのHEADとtree hashは移設時点で一致した。
- `origin/main` へ全local branch（`main`のみ）をpushした。
- GitHub visibilityは `PRIVATE` と確認した。
- 旧pathは保持している。
- 移設完了後のvalidation、pytest、remote HEAD照合結果は作業報告と移設完了commitで記録する。
