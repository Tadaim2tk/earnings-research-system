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

| target | URL | state |
| --- | --- | --- |
| `ICECO_TDNET_INDEX` | https://webapi.yanoshin.jp/webapi/tdnet/list/7698.json2?limit=10 | activated: 適時開示indexの最新1件を検知 |
| `ICECO_IR_CALENDAR` | https://www.iceco.co.jp/ir/calendar/ | retired (2026-08-15) |
| `ICECO_IR_ROOT` | https://www.iceco.co.jp/ir/ | retired (2026-08-15) |
| `ICECO_RESULTS` | https://www.iceco.co.jp/ir/results/ | retired (2026-08-15) |

旧3 targetの静的HTMLには動的に埋め込まれる資料情報がなく、2026-08-13 15:30の第1四半期決算短信を検知できなかった。行を削除するとcheckpointとartifactが孤児化するため `retired` として残し、`active_until` に終了時刻を記録する。旧行の承認欄は当時の事実として変更しない。

### 新sourceのcandidate-specific terms review (2026-08-15)

- [robots.txt](https://webapi.yanoshin.jp/robots.txt): `User-Agent: *` に `Allow: /`。対象パス `/webapi/tdnet/list/` を禁止していない（実測）。
- [llms.txt](https://webapi.yanoshin.jp/llms.txt): 2026-02-09公開のAI agent向け仕様。"No authentication required"、"No rate limit is explicitly enforced, but please be reasonable with request frequency" を明示。
- [サービス説明](https://webapi.yanoshin.jp/tdnet/): 「インターネットを利用した情報収集、分析を目的」「インデックス情報を提供するもの」と明記。login、有料契約、個人情報、非公開情報は無い。

`system_policy:public-web-low-frequency-v1` の条件をすべて満たすため、個別Human承認を待たずに開始する。`automated_access_permitted`、`activation_state`、`terms_review_state` は本reviewの結果として同policyを承認根拠に記録し、Human承認は捏造しない。

### 明示禁止を検出したsource（Human例外案件）

| host | robots.txt (`User-Agent: *`) | 実測日 |
| --- | --- | --- |
| `www.xj-storage.jp` | `Disallow: /` | 2026-08-15 |
| `contents.xj-storage.jp` | `Disallow: /` | 2026-08-15 |
| `www.release.tdnet.info` | `Disallow: /` | 2026-08-15 |

本方針の「明示禁止を検出した場合だけ停止し、Humanへ例外案件として報告する」に該当するため、この3 hostへは自動accessしない。決算短信PDF本体はこの範囲にしか存在せず、**開示の検知は自動化されるがdocument本体の自動取得は現時点で許可されたsourceが無い**。Human判断が要るのは次の一点に限られ、一度決めれば以降は自動で動く。

- 法定開示のdocument URLを、許可されたindexから受け取った1件に限り、`www.release.tdnet.info` から低頻度で取得することを例外として認めるか。認める場合はhost・上限回数・crawl禁止を明記した例外recordを追加する。認めない場合、pipelineは検知とmetadataまでで止まる。

現状の実装は後者に倒してある。`analyze-earnings-handoff` は `tdnet_index_json` のhandoffに対してdocument discoveryを実行せず `no_target_documents` を返す。`last_seen_document_url` はcheckpointとhandoffへ渡すだけで、そこからfetchする経路はコード上存在しない。

### 既取得documentのprovenance record (2026-08-15)

`data/research/iceco/EDA-7698-20260813.json` の元PDFは、2026-08-15T10:04:17+09:00 にassistantが見逃しinquiryの一環として `contents.xj-storage.jp` から1回取得したものである。取得は上記robots実測（同日10:20以降）より前であり、当時この明示禁止は認識していなかった。事実として次を記録する。

- 自動監視pipelineによる取得ではない。pipelineは当該hostへ一度もaccessしていない。
- 同hostへの再取得は行わない。将来の取得可否は上記Human例外案件の判断に従う。
- 本recordを消さずに残し、以後 `data/research/` へ追加するdocumentは出所hostと取得根拠を明記する。

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

workflowはJST 01:17、05:17、09:17、13:17、17:17、21:17に起動する。通常日は引け後の17:17の1回だけを実行し、event windowとevent dayは最大6枠を実行する。robots.txtと合わせても通常日は2 requestに留まる。4時間間隔により、隣接runの欠落や遅延が重ならない場合は単発の最大8時間遅延まで前回成功から12時間以内となる。8時間超または連続欠落では従来どおりstale停止する。36h / 24h / 12hの閾値は変更しない。高頻度polling、crawl、bulk downloadは行わない。

各targetは独立jobと独立 `LiveSourceAdapter` instanceで処理する。ICECO以外の会社とDNS timeout stateやmonitor stateを共有しない。

## Storage And Change Detection

raw HTML、JSON、PDF、screenshot、response bodyをartifactまたはrepositoryへ保存しない。TDnet index (`tdnet_index_json`) では先頭の最新1件の `id`、`title`、`pubdate`、`document_url` と一覧 `total_count` だけをmetadataとして保持し、2件目以降の内容や本文digestをfingerprintへ含めない。`total_count` はproviderが返した件数であり `limit` に達すると定数になるため、これ自体は沈黙防止にならない。先頭以外の変化は `observed_content_length` の差で `content_ambiguous` として表面化する（byte長まで一致する変化は検知できない）。timezone表記のない `YYYY-MM-DD HH:MM:SS` の `pubdate` は、このsource categoryに限りJSTとして解釈する。空一覧、`id`／`title`／`pubdate` 欠落、timestamp不正、非https document URLは推測せずparse failureとする。`document_url` はcheckpointとresearch handoffへ渡すが、document本体は取得も保存もしない。このSHA-256はmonitoring用fingerprintであり、formal evidenceのcontent hashではない。

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

2026-08-09に旧3 targetへ低頻度の初回確認を実行し、robots許可、HTTP取得、parse、checkpoint作成、bundle validationに成功した。2026-08-15に `ICECO_TDNET_INDEX` で同じ確認を実行し、robots許可、初回observation（`id=1275226`、`2027年３月期第１四半期決算短信〔日本基準〕(非連結)`、`2026-08-13T15:30:00+09:00`）、2回目の `no_change` を実測した。local確認結果はraw本文を含まない一時bundleで検証し、repositoryへ保存しない。定期運用のmachine stateはmain merge後のGitHub Actions初回runで作成する。
