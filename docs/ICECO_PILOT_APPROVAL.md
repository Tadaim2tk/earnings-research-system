# ICECO Autonomous Pilot Activation

## Status

株式会社アイスコ（7698）を第1号の自律監視pilotとして有効化する。本書は旧Human approval packetを置き換える。過去のappend-only運用記録は変更せず、方針変更を訂正entryで追跡する。

```text
candidate_status = activated
authorization_basis = system_policy:public-web-low-frequency-v1
terms_review_state = candidate_specific_review_completed
monitoring_level = level_2
raw_storage_status = metadata_only
```

このactivationはmonitoringに限る。company/event/evidence/baseline row、価格取得、売買判断、注文は作成しない。

## Autonomous Public Web Policy

次をすべて満たす情報収集は個別Human承認を待たず開始できる。

- 公開Web情報で認証不要
- 低頻度のHTTPS GETだけを使用
- 保存はURL、時刻、title、header、fingerprint、差分情報等の必要最小限
- 自動accessの明示禁止が確認されない
- 外部契約、課金、個人情報、非公開情報、実売買、不可逆な外部操作を伴わない

明示禁止、実質的に判断困難な利用条件、login/authentication、有料契約、個人情報・非公開情報、実売買、金銭的または不可逆な外部操作を検出した場合だけ停止し、Humanへ例外案件として報告する。単に明示的許可がないことは停止理由にしない。

## Official Review

2026-08-09に次を確認した。

- [Disclosure Policy](https://www.iceco.co.jp/ir/policy/): 法令・東証規則に従い、TDnet公開後は速やかに会社Webへ掲載する方針。
- [Disclaimer](https://www.iceco.co.jp/ir/disclaimer/): 投資勧誘ではないこと、自己責任、掲載変更・中止、利用不能等の免責を記載。
- [robots.txt](https://www.iceco.co.jp/robots.txt): `/wp_corp/wp-admin/` を除き、今回の `/ir/` 対象を禁止していない。

上記確認範囲に自動accessの明示禁止はない。毎回page取得前にrobots規則を確認し、明示禁止または確認不能ならpage取得へ進まずfail-closedとする。

## Activated Target Correction (2026-08-15)

| target | URL | role |
| --- | --- | --- |
| `ICECO_RESULTS` | https://www.xj-storage.jp/public-list/GetList2.aspx?company=AS04527&len=10000&output=json | XJ Storage資料一覧の最新1件を検知 |

旧3 targetの静的HTMLには動的に埋め込まれるPDF資料情報がなく、2026-08-13の決算短信を検知できなかったため1 targetへ置換した。重複した無効な取得を残さず、資料追加を直接表す公開JSONだけを低頻度で確認する。`automated_access_permitted`、`activation_state`、`terms_review_state` その他のHuman／system-policy承認欄は旧 `ICECO_RESULTS` rowの値をそのまま継承し、新しいHuman承認を記録しない。

```text
company_name = 株式会社アイスコ
ticker = 7698
market = TSE Standard
accounting_period = 2027年3月期 第1四半期
scheduled_date = 2026-08-13
scheduled_session = unknown
schedule_profile = prospective_event_v1
```

## Frequency And Isolation

workflowはJST 01:17、05:17、09:17、13:17、17:17、21:17に起動する。通常日は09:17の1回だけを実行し、event windowとevent dayは最大6枠を実行する。4時間間隔により、隣接runの欠落や遅延が重ならない場合は単発の最大8時間遅延まで前回成功から12時間以内となる。8時間超または連続欠落では従来どおりstale停止する。36h / 24h / 12hの閾値は変更しない。高頻度polling、crawl、bulk downloadは行わない。

各targetは独立jobと独立 `LiveSourceAdapter` instanceで処理する。ICECO以外の会社とDNS timeout stateやmonitor stateを共有しない。

## Storage And Change Detection

raw HTML、JSON、PDF、screenshot、response bodyをartifactまたはrepositoryへ保存しない。XJ Storage一覧では先頭の最新1件のtitle、publishDate、最初のPDF URLだけをmetadataとして保持し、全件一覧や本文digestをfingerprintへ含めない。timezone表記のない `YYYY/MM/DD HH:MM:SS` のpublishDateは、このsource categoryに限りJSTとして解釈する。空一覧、title／publishDate欠落、timestamp不正は推測せずparse failureとする。このSHA-256はmonitoring用fingerprintであり、formal evidenceのcontent hashではない。

新しい資料が先頭へ追加されると最新1件metadataのSHA-256 fingerprintが変わり、`change_detected` とする。headerだけが変わりfingerprintが同じ場合は `content_ambiguous` とし、`no_change`へ落とさない。

## Failure And Handoff

通信失敗、DNS/TLS異常、timeout、rate limit、parse failure、robots確認不能、state破損は `no_change` にしない。限定retry後も失敗する場合はstateを保持して停止し、例外通知を作る。

自律targetで変更を検知した場合はHuman approval待ちへ移さず、次のmachine-readable handoffを生成する。

```text
document discovery
content acquisition under the same policy gate
financial metric extraction
pre-event comparison
earnings evaluation
price reaction tracking
```

PR #16ではhandoff生成までを実装する。決算資料本文の取得・指標抽出・価格反応追跡は責務とprovider条件が異なるため、後続実装へ分離する。

## Initial Observation

2026-08-09に3 targetへ低頻度の初回確認を実行し、robots許可、HTTP取得、parse、checkpoint作成、bundle validationに成功した。local確認結果はraw本文を含まない一時bundleで検証し、repositoryへ保存しない。定期運用のmachine stateはmain merge後のGitHub Actions初回runで作成する。
