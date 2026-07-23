# Obsidian Lint And Audit

## 目的

VaultのMarkdown品質だけでなく、research claim、ERS参照、future leakage、knowledge lifecycleを監査する。本格lint codeはpilot後に判断する。

初期lint scopeは新設する `Earnings Research/` domainだけとする。既存TSO noteへ新frontmatter policyを遡及適用せず、cross-domain checkはID/link衝突に限定する。

## 機械検査候補

| check | severity | detection |
| --- | --- | --- |
| dead link | error | Wikilink target/path resolution |
| orphan note | warning | inbound link zero。ただしtemplate/rawは除外 |
| duplicate `note_id` | error | frontmatter uniqueness |
| duplicate entity | error | same `company_id` / `earnings_event_id` |
| missing frontmatter | error | note type別required key |
| invalid enum | error | status/confidence/verified status/knowledge class |
| missing/invalid `origin_mode` | error | frontmatter policyのenumとrequired field |
| historical reconstruction timestamp missing | error | `origin_mode=historical_reconstruction` で `reconstructed_at` が空 |
| invalid status transition | error | git diffとtransition rule |
| missing source | error for fact/validated | evidence/source list empty |
| duplicate source ID/hash | warning/error | manifest comparison |
| stale note | warning | update triggerとlast reviewed date |
| deprecated current link | warning | active indexからdeprecated note参照 |
| ERS ID format mismatch | error | known prefix/schema |
| ERS ID missing | warning/error | formal note type別rule |
| Git commit not found | warning | ERS repo `git cat-file -e` |
| future contamination | error | source published/observed time > baseline cutoff |
| prospective context contamination | error | `historical_reconstruction` noteがprospective context packまたはcalibration cohortへ混入 |
| peer-group circular reference | warning | graph cycle rule |
| hot cache stale | warning | latest approved commit/event mismatch |

## 人間review必須

| check | review question |
| --- | --- |
| contradictory claims | scope/time差か、本当の矛盾か |
| raw fact / interpretation混同 | sourceに直接書かれているか |
| validated without adequate evidence | evidence量・独立性・scopeは十分か |
| management pattern | sample選択と反例を隠していないか |
| value trap claim | valuation narrativeを結果で後付けしていないか |
| source license | 保存、AI処理、引用、共有が許可されるか |
| cross-sector transfer | 同じruleを別sectorへ適用できる根拠があるか |
| confidence | calibrationされた意味か、主観ラベルか |
| failure mode | 実際の失敗と単なる悪い結果を区別したか |
| deprecated replacement | historical contextを失っていないか |
| ticker/name conflict | identity registry未導入の間、同一企業・別企業・aliasのどれか |
| KPI spelling variation | KPI alias registry未導入の間、同義語・単位差・別KPIのどれか |

`ticker/name conflict` と `KPI spelling variation` は、identity registryおよびKPI alias registryが存在するまで機械検査に含めない。各registryのcontrolled vocabularyと更新手順が承認された後、機械検査へ戻す。

## Future leakage audit

Earnings Event noteとpre-event knowledgeについて次を確認する。

1. ERS event timestampを取得する。
2. baseline `as_of_datetime` と `locked_at` を取得する。
3. scoreへ使ったsourceのpublished/observed/recorded timeを比較する。
4. event後に追加されたCompany Patternがpre-event sectionへ逆流していないか確認する。
5. historical reconstructionをprospective baselineと表示していないか確認する。

Vault noteのfile creation timeは研究時点の証拠に使わない。

## Audit report

```text
audit_id
vault_commit
ers_commit
run_at
machine_checks
human_review_items
errors
warnings
accepted_exceptions
reviewer
follow_up
```

audit findingはmarket evidenceではなくprocess evidenceとして扱う。

## Pilot acceptance

- 3社すべてでCompanyからEvent/sourceへ辿れる。
- ERS ID mismatchがない。
- historical reconstruction labelが消えない。
- validated noteにsourceなしがない。
- index/hotを除き孤立noteがない。
- 同じsourceのduplicate ingestを検出できる。
- Vault全体を読まずに1社contextを再構成できる。
