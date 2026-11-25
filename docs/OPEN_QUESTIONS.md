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

## IRカレンダーの見出し行を、続く月の数で見分けている

2026-09-06。`live.py::_monthly_schedule` は「続く月が4つ以上なら見出し行」として
対象から外す。四半期が3か月であることに上限を合わせてあるが、**これは長さという
代用で見出しかどうかを決めている。**

未解決の前提:

- ラベルの無い四半期が2つ続くと月が6つ並び、その並びは見出しとして落ちる。
  公表されている月が黙って消える。
- 段の折り返し方が変われば（1行6か月×2段など）同じことが起きる。
- 節の並びだけからは、見出し行の最後の月と、ラベルを持つ月を見分けられない。
  どちらも直後に `決算発表` が来る。

いま採っている根拠は「見出し行は12か月が続けて並ぶ」という、アイスコの現ページの
実測だけである。**他の会社のIRカレンダーでも成り立つかは確かめていない。**

決めていないこと: 長さ以外の判別軸を持つか（CSSクラスは装飾の変更で壊れるため
使わないと決めてある）、それとも見出しらしき並びを落とすときに観測を失敗させて
人の判断を求めるか。後者は正しく読めているページを止める副作用がある。

関連: ERS-ADR-0080 Amendment (2026-09-06)。

## 失敗を知らせる job が、知らせる対象と同じ準備に依存している

2026-11-17。`level2_monitor.yml` の `report-pipeline-failure` は、`plan` や `monitor` が
何も観測せずに終わったことを Issue に書く。2026-11-15〜11-17 の停止では、`plan` と同じ
`setup-python` で先に落ち、1件も書けなかった（ERS-ADR-0083）。

未解決の前提:

- 通知の job は、checkout・`setup-python`・`pip install -e .` が全部通ることを前提に
  している。この3つのどれかが落ちる障害（runner image の変更、依存の取得失敗）は、
  通知ごと消える。
- 残った手がかりは Actions の赤い実行と GitHub が既定で送る失敗通知で、本システムの
  通知の契約の外にある。それを見なければ気付かない。

決めていないこと: 通知の job を project の install に依存しない形にするか。そうすると
通知の本文を組み立てる code が二か所になり、`monitor-notify-workflow-failure` の dedup と
receipt の契約から外れる。もう一つの案は、workflow の外から run の結果を見る watchdog を
置くことで、`AI_MONITORING_IMPLEMENTATION_DESIGN.md` が「別のwatchdogまたはHuman dashboard」
と書いているものに当たるが、どちらもまだ無い。

関連: ERS-ADR-0083。

## 固定した runner image の廃止を、止まる前に知る方法が無い

2026-11-17。Python を patch まで固定している job の image を `ubuntu-24.04` に固定した
（ERS-ADR-0083）。GitHub は古い image を廃止するので、いつかは同じ形で止まる。

決めていないこと: 廃止の予告をどこで見るか。image を上げる判断を、止まってからではなく
前もって行う手順を持つか。

関連: ERS-ADR-0083。

## レビューゲートが、Codex の側の書式と event の時刻に寄りかかっている

2026-11-25。ゲートは Codex の要約コメントの機械可読な状態（`codex-review-state:v1` の JSON）を
読んで「指摘なし」を知り、push のあとに人が依頼したかどうかを event の `updated_at` と
コメントの `created_at` の比較で決める（ERS-ADR-0084）。

未解決の前提:

- **要約コメントの書式は Codex の側のもので、予告なく変わりうる。** 2026-09 には要約という形が
  無く、2026-11 にはあった。変わって読めなくなると、ゲートは「20分待つ」に戻る。緑にはしない側へ
  倒れるが、**読めなくなったこと自体を知らせる仕組みは無い。** 気付くのは、きれいな PR が
  20分待たされるようになってからである。
- **push の時刻を、`synchronize` の event が運ぶ PR の `updated_at` で代用している。**
  実測は3回で、push の時刻と同じか1秒後だった（tactical-swing-os で1回、本リポジトリの
  PR #92 で2回）。GitHub がそう定めている文書は確かめていない。event が組み立てられる前に別の更新
  （コメントなど）が入ると `updated_at` は後ろへずれ、push の直後に書いた依頼が「push より前」と
  読まれて、頼んであるのに赤になる。そのときは依頼をもう一度書いて再実行すれば進む。
  **余裕は無い。** PR #92 の3回目では、push の2秒後に書いた依頼の `created_at` と event の
  `updated_at` が同じ秒（21:23:55Z）だった。同じ秒は「push より後」に数えるので通ったが、
  1秒ずれれば数えない。このずれが結果を変えるのは、Codex がまったく応えなかったときだけである
  （応えれば要約が動くので、依頼の数は見ない）。前へ余裕を取ると、今度は前の head への依頼を
  数えてしまうので、取っていない。
- 要約の `has_unresolved_findings` は読んでいない。レビューした時点の値で、あとで指摘スレッドを
  resolve しても書き換わらなかった（PR #92: 21:35:39Z に resolve、要約は 21:25:33Z の true のまま）。
  未解決かどうかは、前からのとおり GraphQL のスレッドで数える。
- **Codex の指摘は、レビューした commit への行コメントとして付く、と置いている。** 要約が
  「指摘あり」と言うとき、ゲートはその head への Codex の行コメントが見えるまで通さない。
  行に付かない指摘（レビューの本文だけ、など）が出ると、スレッドを resolve するものが無いまま
  赤になり、push するか依頼し直すまで進まない。そういう指摘は見たことが無いが、無いと
  確かめたわけでもない。
- 「要約が指摘ありと言う前の姿」は、その実行の中でしか分からない。外れ方が2つある。
  (1) 要約が先に「指摘あり」になり、指摘がまだ見えない瞬間に実行が**始まった**場合、前の姿が
  無いので、同じ head への前の回のレビュー（解決済み）で通る。この PR で見えた順番（結果が先、
  要約があと）では、その瞬間は存在しない。
  (2) 読み始めを最初に見た周回が、結果が置かれてから要約が変わるまでの数秒に当たると、
  前の姿に新しい指摘が入ってしまい、「増えていない」と読んで赤になる。再実行すれば通る。
- 依頼かどうかは、コメントの先頭が依頼の文言であることで見ている。Codex が受け付ける書き方の
  全部を知っているわけではない。
- 依頼を書いた人がこのリポジトリの人かどうかは、コメントの `author_association`
  （OWNER / MEMBER / COLLABORATOR）で見ている。**これは GitHub が付ける関係の札で、いまの
  書き込み権限を照会した結果ではない。** Codex がその人の依頼を受け付けるか（Codex に接続した
  アカウントか）も、ゲートからは見えない。受け付けられなかった依頼は「頼んだのに来なかった」
  として fail-open へ流れる。

決めていないこと:

- **push された head を、誰も頼んでいないときに赤にするか、通して知らせるだけにするか。**
  本リポジトリは ERS-ADR-0082 Amendment の決定（頼めていない回を fail-open で通さない）に従って
  赤にした。tactical-swing-os は、毎朝の自動取込の PR が詰まるのを避けるために、通したうえで
  PR に通知を書く形を採っている。同じ事実から別の扱いになっているので、Human が見比べて
  どちらかへ寄せる余地がある。本リポジトリには PR を自動で作る workflow が無い。
- **ゲートに依頼を書かせ直すか。** 人のアカウントの鍵を Secrets に置けば、依頼は人の
  アカウントから届く形になる。鍵を作るのは Human で、Codex がそれに応えるかは未確認。
  入れるなら PR の上で実際に応えることを確かめてからにする。
- Codex の利用上限に達しているとき（「usage limits for code reviews」と返る）を、ほかの
  沈黙と区別して扱うか。いまは区別せず、20分後に fail-open で通る。

関連: ERS-ADR-0039、ERS-ADR-0040、ERS-ADR-0082、ERS-ADR-0084。
