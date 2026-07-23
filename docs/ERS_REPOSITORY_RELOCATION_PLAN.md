# ERS Repository Relocation Plan

## 状態と目的

本書は計画だけを定義する。現在のrepositoryを移動せず、remoteやGitHub repositoryも作成しない。

現在のERS repositoryには次の恒久化riskがある。

- 日付付きCodex作業directory配下にあり、恒久保管場所として不安定である。
- Git remoteが未設定で、local disk以外にhistoryの正本がない。
- Obsidianが参照する `ers_commit` はlocal repositoryが失われると追跡不能になる。
- 作業directoryの整理・削除により、repository全体を失う可能性がある。

## 移設要件

- `.git` directoryを含むhistoryを保持し、既存commit hashを変えない。
- 旧pathは移設直後に削除せず、検証期間中はread-only backupとして保持する。
- 新pathでsample validationとpytestを実行する。
- Humanが承認したprivate GitHub repositoryをremoteとして設定する。
- private remoteへのpush後、branch、HEAD commit、remote参照を検証する。
- Obsidianは最終的にremote URLとcommit hashを正本参照とする。local pathは実行補助に限定する。
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

## Human decision

実行前に恒久local path、private repository名、remote URL、実施時期、Obsidian参照形式の承認が必要である。具体的なpathやrepository名は本書では決定しない。
