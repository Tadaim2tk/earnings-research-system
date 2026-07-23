# Obsidian Vault Structure

## 統合先

既存Vault root `/Users/maruyamayuuki/Documents/TacticalSwingOS` の `Maruyama AI Research Lab` 配下へ、次のdomainを追加する案とする。今回はfolderやnoteを作成しない。

```text
Maruyama AI Research Lab/
├── 00_Hub/
│   ├── Maruyama AI Research Lab.md
│   └── Knowledge Taxonomy.md
├── Tactical Swing OS v3 Self Learning/
└── Earnings Research/
    ├── index.md
    ├── hot.md
    ├── Companies/
    ├── Earnings Events/
    ├── Industries/
    ├── Peer Groups/
    ├── KPIs/
    ├── Management Patterns/
    ├── Accounting Quality/
    ├── Value Traps/
    ├── Market Expectations/
    ├── Market Reactions/
    ├── Hypotheses/
    ├── Decision Rules/
    ├── Failure Modes/
    ├── Validated Findings/
    ├── Open Questions/
    ├── Sources/
    ├── Workflows/
    ├── Templates/
    └── .raw/
```

## 既存構造との対応

| ERS concern | existing Vault structure | integration rule |
| --- | --- | --- |
| upper taxonomy | `00_Hub/Knowledge Taxonomy.md` | 新taxonomyを上書きしない |
| onboarding | `00_Hub/AI Onboarding Guide.md` | ERS domain indexから参照する |
| company/asset | TSO `Assets/` | company knowledgeはERS、market asset contextはTSO。相互linkする |
| hypothesis | TSO `Hypotheses/` | ID scopeを明示し、同じ仮説を複製しない |
| protocol/observation | TSO `Protocols/`, `Observations/` | cross-domain protocolは既存Research Lab flowを利用 |
| lesson | TSO `Learning/` | earnings固有findingはERS、横断lessonはhubへ昇格候補 |
| source/research | TSO `Research/` | raw sourceを共有folderへ無断移動しない |

## Index設計

`index.md` は全note本文の複製ではなくcatalogとrouting tableである。

- domain purposeと正本境界
- note type別sub-index
- active company/eventへのlink
- validated findingとopen questionの入口
- ERS `repository_remote` とlatest approved `ers_commit`
- TSO cross-domain links

pilotの `index.md` にはcompany identity registryを置き、少なくとも次の列を持たせる。

```text
ticker
company_id
note_id
company_name
market
TSO_asset_raw
identity_status
notes
```

これはpilot範囲のidentity正本候補であり、実際の `index.md` 作成と値の承認はVault導入時にHumanが行う。現時点では作成しない。

note数が増えた場合は `Companies/index.md`, `KPIs/index.md` 等のdomain indexを追加する。全noteの自動列挙はlint生成物として扱い、手書き知識と混同しない。

## `hot.md`

`hot.md` は再生成可能なcacheであり履歴の正本ではない。内容はcontext loading policyで定め、完了項目や過去decisionの唯一の保存場所にしない。

## `.raw/`

- source manifestと許可された原文だけを置く。
- 原則Git管理外とする。
- license、個人情報、secret、price raw dataをsource type別に判定する。
- original filenameではなくsource ID/hashを含むnameを推奨する。
- raw削除後も、許可される範囲でsource ID、URL、hash、要約、削除理由を残す。
- Vault導入と同じ変更単位でVault `.gitignore` に `Maruyama AI Research Lab/Earnings Research/.raw/` を追加する。今回は既存Vaultを変更しないため追加しない。

## 命名

- Company: `COMPANY-7974 Nintendo.md`
- Event: `EVENT-7974-2025-05-08-FY.md`
- Hypothesis: 既存ruleに合わせ `HYP-YYYYMMDD-### Title.md`
- Open Question: `KQ-YYYYMMDD-### Title.md`
- Source: `SRC-<hash-prefix> Short Title.md`

日本語titleを許容するが、stable IDを必ず併記する。

## Company identity

- pilotの `company_id` は `CMP-<TSE ticker>`、Company noteの `note_id` は `ERS-COMPANY-<TSE ticker>` とする。
- Nintendo: `CMP-7974` / `ERS-COMPANY-7974`
- Toyota: `CMP-7203` / `ERS-COMPANY-7203`
- Olympic Group: `CMP-8289` / `ERS-COMPANY-8289`
- ticker変更ではalias履歴を残す。上場廃止・再上場・entity再編がある場合、同一entityと確認できるまで旧 `company_id` を安易に再利用しない。

## 導入制約

- root levelへ別の `wiki/` を作らない。
- 既存noteを一括移動しない。
- plugin command `/wiki`, `/save`, `ingest`, `lint` を未確認のまま実行しない。
- `00_Hub` の既存文書を自動更新しない。
- 最初は3社pilotとdomain indexだけに限定する。
- pilot入口linkはVault導入時にHuman承認を得て、root `Agent Handoff.md` またはResearch Labの `AI Onboarding Guide.md` のどちらか一方へ追加する。既存dirty変更がある現時点では追加しない。
- pilot開始前に `.raw/` のGit除外と、domain `index.md` / `hot.md` の最小構成を同じreview単位で確認する。
