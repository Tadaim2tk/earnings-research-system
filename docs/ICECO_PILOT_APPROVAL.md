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

## Activated Targets

| target | URL | role |
| --- | --- | --- |
| `ICECO_IR_CALENDAR` | https://www.iceco.co.jp/ir/calendar/ | 発表予定日と日程変更の検知 |
| `ICECO_IR_ROOT` | https://www.iceco.co.jp/ir/ | IR新着導線の検知 |
| `ICECO_RESULTS` | https://www.iceco.co.jp/ir/results/ | 決算短信の追加・差替え検知 |

[IR Library](https://www.iceco.co.jp/ir/library/) は上記への入口が重複するため、初回構成では独立targetにしない。取りこぼしが実測された場合に追加する。

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

workflowは平日09:17、15:17、21:17 JSTに起動する。通常日は09:17の1回だけを実行し、event dayは3枠を実行する。event接近時も少なくとも営業日1回を維持する。終了日は固定せず、例外検知または明示停止まで低頻度で継続する。高頻度polling、crawl、bulk downloadは行わない。

各targetは独立jobと独立 `LiveSourceAdapter` instanceで処理する。ICECO以外の会社とDNS timeout stateやmonitor stateを共有しない。

## Storage And Change Detection

raw HTML、PDF、screenshot、response bodyをartifactまたはrepositoryへ保存しない。保存対象は監視契約、URL、取得時刻、title、公開metadata、HTTP header、content length、SHA-256比較値、run/checkpoint、差分状態だけである。このSHA-256はmonitoring用fingerprintであり、formal evidenceのcontent hashではない。

同じtitleのまま資料が追加された場合も、page responseのSHA-256比較値が変わるため `change_detected` とする。headerだけが変わり本文比較値が同じ場合は `content_ambiguous` とし、`no_change`へ落とさない。

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
