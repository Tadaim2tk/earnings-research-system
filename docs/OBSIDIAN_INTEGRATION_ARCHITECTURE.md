# Obsidian Integration Architecture

## 目的

ERSの機械処理可能な研究記録と、Obsidianの再利用可能な研究知識を、正本を混同せず相互参照できるようにする。本設計は文書上の `Proposed` architectureであり、schema変更、Vault変更、自動同期、外部plugin導入は行わない。

## 確認した既存Vault

- Vault root: `/Users/maruyamayuuki/Documents/TacticalSwingOS`
- Research hub: `Maruyama AI Research Lab/00_Hub/Maruyama AI Research Lab.md`
- 既存taxonomy: `Facts -> Hypotheses -> Lessons`。Protocolは検証計画でありknowledge layerではない。
- 既存research flow: `Evidence -> Fact -> Hypothesis -> Protocol -> Observation -> Lesson -> Knowledge`
- 既存入口: root `Agent Handoff.md` とResearch Labの `AI Onboarding Guide.md`
- 既存機能: Hypothesis、Protocol、Observation、Learning、Asset、Meaning Space、Decision Journalのfolderとtemplate
- 未導入: `index.md`, `hot.md`, `.raw/`, domain index, ingest/lint command、claude-obsidian plugin固有file
- Vaultには既存の未commit変更があるため、本作業では読み取りのみとした。

## 正本の境界

| concern | authoritative system | rule |
| --- | --- | --- |
| schema、validator、tests | ERS Git repository | Obsidianから変更しない |
| production/sample CSV | ERS Git repository | Vault noteを直接importしない |
| baseline lock、timestamps | ERS Git repository | Vault編集時刻で代替しない |
| evidence ID、source lineage | ERS Git repository | VaultはIDを参照する |
| scoring version、formal ADR | ERS Git repository | Chat/Vault上の提案だけで発効しない |
| 企業特性、業種知識、失敗条件 | Obsidian | claim classとreview statusを明示する |
| 仮説、関連企業、KPI意味 | Obsidian | ERS IDとsource evidenceへlink可能にする |
| 実装・決定履歴 | Git commit / Issue / PR | `ers_commit` は補助参照 |
| TSO研究知識 | 既存TSO Research Lab | ERS folderへ複製せずlinkする |

Obsidianの `reviewed` または `validated` は、そのnote全体がERSのverified factになったことを意味しない。ERSへ正式採用するclaimは、該当する `evidence_id`、時刻、source lineage、人間承認を別途満たす。

## 知識循環

```text
Source
  -> raw保管またはURL/source manifest
  -> Observed Fact / Derived Metricの抽出
  -> Obsidian知識note
  -> Interpretation / Hypothesis / link候補
  -> 人間review
  -> ERS evidence / hypothesis / ADRへの正式採用
  -> 決算後Outcomeと検証
  -> Lesson / Validated Finding / Failure Mode更新
```

各矢印は状態遷移であり、自動昇格ではない。とくに `raw -> fact`、`interpretation -> validated`、`Vault -> ERS` は人間review gateを持つ。

## 双方向参照

### ERSからObsidian

初期段階は文書・運用上の参照とし、CSV schemaへWikilinkを追加しない。将来は `ers_knowledge_link` tableを検討する。

### ObsidianからERS

frontmatterに次を保持できるようにする。

- `repository_remote`
- `company_id`
- `earnings_event_ids`
- `source_evidence_ids`
- `hypothesis_ids`
- `ers_commit`
- `knowledge_version`

ERSの永続参照は `repository_remote` + `ers_commit` とする。local repository pathは環境依存の実行補助であり、正本identityにしない。Vault pathは人間向け、stable IDは整合性検査向けとし、note renameで関係が失われないようpathだけをidentityにしない。

### 将来のlink schema候補

直接列を各ERS tableへ追加する案は単純だが、1 entity対複数note、relation type、note rename、version historyを扱いにくい。

候補列:

```text
obsidian_note_path
obsidian_note_id
knowledge_version
knowledge_status
knowledge_last_reviewed_at
```

推奨候補は独立link tableである。

```text
ers_knowledge_link
- link_id
- entity_type
- entity_id
- obsidian_note_id
- obsidian_note_path
- relation_type
- knowledge_version
- knowledge_status
- created_at
- reviewed_at
```

| option | advantage | risk | current judgment |
| --- | --- | --- | --- |
| ERS各行へpath列 | 実装が単純 | 多値、rename、version、relationが弱い | pilot前は採用しない |
| `ers_knowledge_link` | 多対多、監査、version管理が可能 | 新schemaとvalidatorが必要 | pilot後の第一候補 |
| Obsidian側だけでERS ID保持 | schema変更不要 | ERSからの逆引きが弱い | 初期pilotで採用 |

## 自動同期を避ける理由

- Vaultのinterpretationをverified factへ誤昇格させるriskがある。
- baseline lock後の知識更新がpre-event recordへ逆流しうる。
- note rename、merge、deprecated処理とappend-only ERS semanticsが異なる。
- source licenseによりraw保存・agent処理条件が異なる。
- dirty Vaultでrecursive writerを動かすと既存作業と競合する。

初期運用は明示的な `save`, review, adoptの3段階とする。

## AIの読込順序

AIはVault全体を走査しない。`OBSIDIAN_CONTEXT_LOADING_POLICY.md` に従い、ERS domain index、`hot.md`、対象Company、対象Event、関連patternの順に必要noteだけ読む。source原文はclaim確認が必要な場合に限定する。

## TSO Vaultとの関係

ERS領域は既存 `Maruyama AI Research Lab` の新しいdomainとして設計する。TSOのAsset、Hypothesis、Protocol、Lessonを複製せず、stable IDとWikilinkで参照する。

- TSO: market regime、signal context、execution研究
- ERS: earnings expectation、company guidance、KPI、event reaction研究
- Shared: company identity、industry、evidence semantics、failure mode候補

用語衝突時は各systemのformal schemaを優先し、Vault側にaliasとscopeを記録する。

## 役割

| actor | responsibility | prohibited promotion |
| --- | --- | --- |
| ChatGPT | 企業・業種解釈、仮説、研究設計 | 単独でvalidated/score採用しない |
| Codex | ERS、Git、link/lint設計、整合性検査 | 投資判断やevidence承認を行わない |
| Claude Code | Vault読解、重複・矛盾・古さの監査 | review結果を自ら正式採用しない |
| Human | source terms、review、validated昇格、schema/score承認 | approvalをAIへ委譲しない |

## 導入段階

1. 本設計文書をreviewする。
2. Vaultのdirty変更を既存作業者が解消する。
3. `Maruyama AI Research Lab/Earnings Research/` の最小folderとtemplateだけを別PRで作る。
4. Nintendo、Toyota、Olympic Groupで最大5〜8 notes/companyのpilotを行う。
5. 手動linkとaudit結果をreviewする。
6. 必要性が確認された場合だけlink tableやlint scriptを提案する。

## claude-obsidian系仕組みの統合判断

既存Vaultにはplugin固有の `wiki/index.md`, `wiki/hot.md`, `.raw/`, ingest/lint workflowを確認できなかった。PDFが紹介する外部repositoryのinstall、license、maintenance状態は本作業では検証・導入していない。

将来pluginまたはscriptを評価する場合、導入前に次を記録する。

- repository URLとowner
- license fileと適用範囲
- latest commitとrelease date
- issue/PR activityとmaintenance status
- install/setup scriptの全内容
- 実行するshell commandとnetwork access
- file write scopeとrecursive modification
- telemetry
- environment variable、credential、secret access
- dependency lifecycleとsupply-chain risk
- dry-run、backup、rollback method

既存Vaultへ直接setup scriptを実行せず、使い捨てtest Vaultで検証してから人間承認を得る。
