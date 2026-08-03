# 未決事項

## TSO_LOG契約とERS mapping

- formal TSO_LOG contractとversion identifierを誰が所有・承認するか。
- TSOの28列inputと `origin` 付き29列ledgerのどちらをERS import contractのversion単位とするか。
- non-company instrument向けのraw `tso_asset` relationを追加し、`asset` を `company_master.ticker` へ直接mapしない設計にするか。
- categorical TSO rank fieldを追加し、現行integer `tso_snapshot.rank` を廃止またはrenameするか。
- free-form `regime` raw値を保持しつつ、normalized ERS regime categoryをどう併設するか。
- `ems`, `ffs`, `cds`, `ias`, `cbs`, `mes` の承認済みsemantic expansionとversion別定義。
- `rr`, `win_prob`, `tq_score`, `opp_score`, `no_trade_score` をhistorical generator行とmanual行で比較可能か。
- `invalidation`, `verification_target` を専用TSO snapshot field、hypothesis link、evaluation-plan recordのどこへ置くか。
- TSO row-level `verified_status` とERS evidence verificationをscopeを失わず関連付ける方法。
- 将来 `ingestion_origin` 専用fieldを作るか。歴史的な空欄は `manual` ではなく `unknown` と解釈するか。
- TSO `date` を `tso_snapshot.as_of_datetime` に変換する時刻・timezone rule。
- 同一timestampの複数TSO signalをどう選択・集約するか。

## 価格データ取得元と粒度

- J-Quantsは第1号prospective pilotのscope外とする。将来採用する場合、local保存、解約後retention、agent処理、二次利用条件を契約画面またはaccount文書でHuman確認する。
- raw price rowsをGit trackingせずlocal-only保存とする運用で十分か。
- calculated return、VWAP、chart screenshotを保存・共有できる範囲はどこまでか。
- broker chartからの数値転記・screenshot保存・再利用がterms上許容されるか。
- authoritativeなexchange calendar、timezone database、corporate-action adjustment policyは何か。
- after-close/before-open announcementにextended-hours tradeが必要か。
- correctionやdelayを含む信頼できるpublic announcement timestampをどこから取得するか。
- `announcement_session=intraday` では常にone-minute dataを必須にするか、最初のhand-entry cohortではreview済みmanual referenceを許容するか。
- minute/manual referenceがないintraday caseを全return calibrationから除外するか、別provisional cohortに残すか。
- 承認するVWAP windowは何分か。market liquidityやevent session別に変えるか。
- VWAPに含めるtrade/quote condition、auction、halt、correction、zero-volume barのrule。
- raw minute barsと計算inputの保存期間。
- `market_reaction_reference_price` と `trade_entry_reference_price` を将来別fieldへ分けるか。
- `return_reference_price_raw`, `return_reference_price_adjusted`, `corporate_action_adjustment_factor` をpilot後に正式schema列へ追加するか。

## 人間承認が必要な手入力暫定rule

- `before_open`, `after_close` の最低datasetをunadjusted/adjustedを識別できるdaily OHLCとする。
- before-openの主referenceをunadjusted `previous_close` とし、adjusted comparisonとannouncement-day openを別保存する。
- after-closeのfirst-tradable主referenceをunadjusted `next_open` とし、raw prior closeとadjusted comparisonを別保存する。
- `intraday` はannouncement前に終了した最後の完全なminute barを使い、取得不能時のみtimestamp・source付き `manual` を許容する。
- minute/manual referenceがなければ `unknown` とし、依存するreturn fieldsを空欄にする。
- `announcement_session` と `return_reference_price_type` ごとにcohortを分離する。
- manual referenceとdaily-only intraday reactionはhuman reviewまでprovisionalとする。
- later outcome確認後のreference変更は、理由付きappend-only correction以外では行わない。

## プロジェクト全体

- terminal event statusを誤記録した場合のappend-only correction／retraction schema。
- event lifecycleを複数CSVやDBへ移行した後のglobal current-status計算方法。
- historical reconstructionを `pre_earnings_baseline` と分離する専用tableまたは `baseline_mode` が必要か。
- 正式rubricで未採点のbaselineについて、required score componentを `unknown` として保存できるようにするか。
- 最初のreal research universeは何社にするか。
- 対象marketはJapan only、US only、mixedのどれから始めるか。
- 決算前後のupdate frequencyをどうするか。
- 長期source of truthをCSV、SQLite、PostgreSQLのどれにするか。
- Excel/Google Sheetsをmanual entry、review、non-authoritative exportのどこに使うか。
- 法的・運用上許容できるSNS collection methodは何か。
- paid consensus dataをどのlicense条件で利用できるか。
- trade decisionとresearch evaluationをどう分離するか。
- score calibrationをcredibleとするreview済みhistorical case数はいくつか。
- correctionされた新baseline versionはHuman approvalを必須とする。review再実施条件の詳細は未決。
- SNS overheatとmisinformation riskのformal definitionは何か。
- hypothesisをverifiedにするminimum evidenceは何か。
- `baseline_record_hash` のV1計算方法は固定field順、型別正規化、compact UTF-8 JSON、SHA-256として定義済み。Git以外のimmutable recordとの独立照合方法は未決。
- TSO `source_row_hash` のsource rowからの計算方法。
- loss-makingまたはnear-zero denominatorでsurprise percentageの範囲を +/-100超まで許容するか。
- `unknown` return policyやexpired score version向けwarning tierを追加するか。
- `score_definition` に `approval_status`, `approved_by`, `approved_at` を追加するか。
- stored score rowからcomponent weightをどう再構成するか。
- hand-entry trial後にKPI unitをcontrolled enum化するか。
- TSO raw fieldの `mapping_version` ownerと、TSO schema/version identifierの取得元をどう定めるか。

## Obsidian連携

- `Maruyama AI Research Lab/Earnings Research/` を既存Vaultへ追加することを誰が承認するか。
- ObsidianをERSの正本にせずknowledge layerとして運用する境界を正式採用するか。
- 初期pilot後に `ers_knowledge_link` tableを追加するか、Obsidian側参照だけを継続するか。
- `obsidian_note_id`, `knowledge_version`, `knowledge_status`, `knowledge_last_reviewed_at` のownerとvalidatorをどう定めるか。
- 自動双方向同期を将来も禁止するか、限定的なone-way exportを許可するか。
- formalなvalidated rubricとHuman roleをどう定義するか。反復patternの3 independent eventsはpilot暫定ruleであり、pilot後にcalibrateする。
- Vault全体の再編成、既存noteの一括移動、重複folder統合を行うか。
- external claude-obsidian pluginまたは同等scriptを導入するか。repository、license、install script、telemetry、write scopeのauditが必要。
- `.raw/` のGit除外、backup、retention、削除記録をどこで管理するか。
- 決算資料、news、SNS、message board、J-Quants raw dataのsource別保存条件を誰が確認するか。
- AIが外部providerへraw sourceを送信できる条件をどう制御するか。
- `index.md` / `hot.md` / domain indexを手動管理するか、review付き生成物にするか。
- lint automationのmachine check範囲とhuman audit範囲をどう分けるか。
- historical reconstruction noteをprospective baseline contextから機械的に除外する方法。
- TSOとERSのCompany/Asset/Hypothesis ID衝突をどう防ぐか。
- plugin、Vault再編、自動Web調査、自動validated昇格、J-Quants raw保存はいずれも未承認のままとするか。

## Prospective pilot運用

- 第1号candidate企業IRサイトのviewing、metadata記録、AI raw input、自動access条件。
- AI取得またはmanual fallbackに使う具体的なprice sourceとmetadata記録条件。
- pilot開始前に固定するreviewer identifier。
- primary calendar source、primary occurrence source、secondary confirmation source。
- Level 2 monitoringの詳細設計は [AI_MONITORING_IMPLEMENTATION_DESIGN.md](AI_MONITORING_IMPLEMENTATION_DESIGN.md) に記録済み。artifact APIでprevious committed stateを復元する制約、retention監視、恒久storage移行時期。
- 通常時、5営業日前、前日、当日のstale gap許容値とbackup notification経路。
- monitor target、checkpoint、runを専用schemaとvalidatorへ昇格する時期。ADR-0022のHuman acceptance前に実装を開始しない。
- effective locked baselineとworking draftを将来どう分離するか。
- cross-file baseline lineageをいつglobal registryへ移行するか。
- private hash helperをpublic `hash-baseline` CLIへ昇格するか。

## Historical reconstruction識別

- pilotではまずVault frontmatterの `origin_mode` を正本として記録し、`historical_reconstruction` をprospective contextとcalibrationから除外する。
- ERS tableにもreconstruction識別が必要と判明した場合、現行schemaへ暗黙追加せず、`baseline_mode` または専用tableを別ADRで判断する。
- historical caseとprospective caseをどのaudit reportで比較可能にするか。

## ERS repository恒久化

2026-07-23に次を決定・実施した。

- permanent local path: `/Users/maruyamayuuki/Documents/MaruyamaAIResearchLab/earnings-research-system`
- private remote: `https://github.com/Tadaim2tk/earnings-research-system`
- Obsidian永続参照: `repository_remote` + `ers_commit`
- local pathは環境依存の実行補助情報とする。

残る運用判断は、rollback用の旧pathをいつ削除可能と判定するかである。
