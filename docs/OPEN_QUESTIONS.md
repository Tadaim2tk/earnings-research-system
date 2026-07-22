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

- 各target marketのadjusted daily OHLCとminute barsをどのvendorまたはofficial sourceから取得するか。
- source termsがlocal storage、derived VWAP、Git tracking、reviewer accessを許可するか。
- authoritativeなexchange calendar、timezone database、corporate-action adjustment policyは何か。
- after-close/before-open announcementにextended-hours tradeが必要か。
- correctionやdelayを含む信頼できるpublic announcement timestampをどこから取得するか。
- `announcement_session=intraday` では常にone-minute dataを必須にするか、最初のhand-entry cohortではreview済みmanual referenceを許容するか。
- minute/manual referenceがないintraday caseを全return calibrationから除外するか、別provisional cohortに残すか。
- 承認するVWAP windowは何分か。market liquidityやevent session別に変えるか。
- VWAPに含めるtrade/quote condition、auction、halt、correction、zero-volume barのrule。
- raw minute barsと計算inputの保存期間。

## 人間承認が必要な手入力暫定rule

- `before_open`, `after_close` の最低datasetをadjusted daily OHLCとする。
- before-openの主referenceを `previous_close` とし、announcement-day openを別保存する。
- after-closeのfirst-tradable主referenceを `next_open` とし、prior closeを別保存する。
- `intraday` はannouncement前に終了した最後の完全なminute barを使い、取得不能時のみtimestamp・source付き `manual` を許容する。
- minute/manual referenceがなければ `unknown` とし、依存するreturn fieldsを空欄にする。
- `announcement_session` と `return_reference_price_type` ごとにcohortを分離する。
- manual referenceとdaily-only intraday reactionはhuman reviewまでprovisionalとする。
- later outcome確認後のreference変更は、理由付きappend-only correction以外では行わない。

## プロジェクト全体

- 最初のreal research universeは何社にするか。
- 対象marketはJapan only、US only、mixedのどれから始めるか。
- 決算前後のupdate frequencyをどうするか。
- 長期source of truthをCSV、SQLite、PostgreSQLのどれにするか。
- Excel/Google Sheetsをmanual entry、review、non-authoritative exportのどこに使うか。
- 法的・運用上許容できるSNS collection methodは何か。
- paid consensus dataをどのlicense条件で利用できるか。
- trade decisionとresearch evaluationをどう分離するか。
- score calibrationをcredibleとするreview済みhistorical case数はいくつか。
- correctionされた新baseline versionにhuman approvalを必須とするか。
- SNS overheatとmisinformation riskのformal definitionは何か。
- hypothesisをverifiedにするminimum evidenceは何か。
- `baseline_record_hash` の計算・独立検証方法。
- TSO `source_row_hash` のsource rowからの計算方法。
- loss-makingまたはnear-zero denominatorでsurprise percentageの範囲を +/-100超まで許容するか。
- `unknown` return policyやexpired score version向けwarning tierを追加するか。
- `score_definition` に `approval_status`, `approved_by`, `approved_at` を追加するか。
- stored score rowからcomponent weightをどう再構成するか。
- hand-entry trial後にKPI unitをcontrolled enum化するか。
