# Obsidian Save Workflow

## 保存単位

1回のsave operationは、対象event、追加source、作成/更新note、ERS ID、reviewerを明示する。会話全体を無選別に保存しない。

## 決算前

1. `index.md` と `hot.md` を読む。
2. 対象Company noteを読む。
3. Management Guidance Patternを読む。
4. Peer Group、Industry Driver、KPIを読む。
5. relevant Failure Modeを読む。
6. 新sourceをrights checkし、source IDとevidence候補を作る。
7. Observed Fact、Derived Metric、Interpretationを分ける。
8. baseline hypothesisとinvalidationを作る。
9. 人間review後にERSへevidence/baselineを記録する。
10. baselineを発表前にlockする。
11. `hot.md` を再生成する。

Vault noteの知識は、ERS evidence timingを満たすsourceに遡れない限りpre-event scoreへ使わない。

## 決算後

1. actual resultとKPI actual rowをERSへappendする。
2. approved sourceでraw/adjusted referenceとprice reactionを記録する。
3. 事前hypothesisをsupported/mixed/invalidated/openで評価する。
4. Company noteのOutcome sectionをappendする。
5. Management Patternを更新するが、単一事例でvalidatedにしない。
6. Failure ModeまたはValidated Finding候補を作る。
7. Peer Groupへ適用可能性と非適用条件を記録する。
8. `index.md` と `hot.md` を更新する。
9. day1/day5/day20到達時にreviewをappendする。

## 週次review

1. 新規・更新note一覧
2. orphan note
3. dead link
4. duplicate entity/source
5. contradictory claim
6. stale note
7. evidenceなしvalidated note
8. ERS IDなしformal knowledge
9. deprecated noteをcurrent扱いするlink
10. TSO/ERS用語衝突
11. future information contamination
12. 次週knowledge gaps

## Explicit save operation

```text
1. Read current note and frontmatter.
2. Resolve stable IDs.
3. Classify each claim.
4. Attach source/evidence IDs.
5. Produce a patch preview.
6. Human accepts or rejects.
7. Apply the patch.
8. Update index/hot cache.
9. Run lint.
10. Record commit or leave an explicit uncommitted status.
```

`/save` 相当のcommandを将来実装しても、step 5と6を省略しない。

## Conflict handling

- dirty Vaultではrecursive saveを停止する。
- active Claude/Codex sessionが同じnoteを編集している場合はwriterを1つにする。
- ERSとVaultが矛盾した場合、schema/CSV/commitの事実はERS、研究解釈はreview status付きVaultを参照する。
- TSO execution stateはTSO GitHub/body repositoryを優先する。

## Rollback

- commit済み変更はrevert commitで戻す。
- 未commit変更は作業者のdiffを保護し、対象fileだけの逆patchを使う。
- raw file削除はmanifestへdeletion recordを残す。
- index/hotはsource noteから再生成できるようにする。

## Pilot

Nintendo `7974`、Toyota `7203`、Olympic Group `8289` をhistorical reconstructionとして扱う。過去時点の正式baselineとして偽装しない。

各社最大5〜8noteに限定する。

1. Company
2. Earnings Event
3. Management Guidance Pattern
4. Peer/IndustryまたはKPI
5. Hypothesis
6. Reconstruction Limitation
7. Knowledge Gap

目的はnote数ではなく、source分離、ERS ID link、context loading、lint負荷を測ることである。

