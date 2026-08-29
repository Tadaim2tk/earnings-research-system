# 価格データ取得元レビュー

## 目的と調査境界

日本株の決算後return検証に必要なdaily OHLC、minute bar、corporate action、announcement timestampの候補を比較する。2026-08-29 に Evidence（開示本文）と Population（当日の決算発表企業一覧）の節を追加した — 本文は著作物であり、価格の数値とは保存・再利用の判断が違う。本書は2026-07-23時点の公開情報による一次調査であり、契約、account作成、API接続、有料申込み、scrapingは行っていない。

価格データを技術的に取得できることと、ERSへ保存・再利用できることは別問題である。`storage_allowed` や `redistribution_allowed` が公開情報だけで確定しない場合は、利用規約またはproviderへの問い合わせ完了まで `unknown` とする。

## 第1号Prospective Pilot Override

本書の候補比較はhistorical pilotで確定したprovider採用記録ではなく、prospective運用へ向けた技術調査として保持する。第1号prospective pilotでは [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) を優先し、Humanがsource、取得方法、保存、AI処理、自動accessを個別承認する。目標は承認済みsourceからAIが必要な価格項目だけを取得することだが、本書ではproviderを正式採用しない。sourceがbaseline開始前に確定しないcandidateは見送る。

## 候補比較

| provider_name | official_or_third_party | daily_ohlc_available | minute_bar_available | historical_minute_retention | adjusted_price_support | announcement_timestamp_compatibility | api_or_manual | authentication_required | cost | license_review_required | storage_allowed | redistribution_allowed | known_limitations | recommended_use | review_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `J-Quants API Free` | official / JPXI | yes | no | not_applicable | yes。adjusted/unadjusted OHLC | medium。TDnet時刻は別sourceが必要 | API | yes / API key | JPY 0 | yes | private analysisはlikely。raw保存条件はterms確認要 | no。raw dataの配布・共有禁止 | 2年分だが直近12週間を除く。recent pilotには不向き | historical調査と古いdaily dataの技術候補。recent eventには不足 | pending_candidate_terms_review |
| `J-Quants API Light + Tick/Minute Add-on` | official / JPXI | yes | yes | 2 years | daily OHLCはyes。minute/tickのadjustment仕様は要確認 | high。TDnetの実開示時刻とJSTでjoin可能。ただしprice dataはdaily deliveryでreal-timeではない | API / CSV | yes / API key | JPY 1,650 + JPY 5,500 per month, tax included | yes | personal internal researchはlikely。raw retention範囲をterms確認要 | no。raw dataの第三者共有禁止 | individual/private use限定。derivatives対象外。minute/tickはadd-on | 契約、保存、AI処理、自動取得のHuman承認後の技術候補 | pending_candidate_terms_review |
| `JPX TDnet public viewing service` | official / JPX | no | no | not_applicable | not_applicable | highest。実開示日時が掲載時刻 | manual viewing | no for public viewing | free | yes | disclosure metadataの記録範囲をterms確認要 | source document再配布は別途確認 | 価格sourceではない。公開閲覧は31日、Listed Company Searchは過去10年閲覧 | terms確認後のsecondary occurrence候補。自動accessは別途Human承認 | conditional_secondary_pending_automation_terms |
| `Monex Trader chart` | third-party market data via broker | yes / display | yes / display | official tablet pageは最大200 bars。長期保持は不明 | unknown | medium。画面上の1-minute OHLCをTDnet時刻と手動照合 | manual | yes / brokerage account | tool is shown as free; account条件あり | yes | unknown | unknown | API/export前提ではない。表示期間・corporate action・licenseが研究DB要件を満たすか不明 | audit付き `manual reference price` のfallbackのみ | manual_fallback_pending_terms |
| `JPX FLEX Historical` | official / JPXI | daily market information plus tick-derived OHLC | tick data。minuteは利用者側集計 | last 30 days / all-period / specified one-month spot。data since 2011 | no automatic adjusted series confirmed。base/issue informationとの別処理が必要 | high。exchange timestamp付きtick | Web API / S3 files | yes / contract | regular single entity JPY 100,000 monthly; all-period JPY 300,000 monthly, tax excluded | yes | internal use under contract | no unless separately approved | PCAP中心で大容量。個人pilotには費用・処理とも過剰 | 将来、tick-level再現性が必須になった場合のみ再検討 | deferred_overkill |
| `J-Quants Pro` | official / JPXI | yes | minute/tickは個別dataset・契約確認要 | daily OHLC since 2008-05-07 | yes。unadjusted/adjusted/factor | high。TDnet/Snowflake等の法人向けdataと連携可能 | API / SFTP / Snowflake | yes / corporate contract | dataset別見積り | yes | internal use under license | no unless approved external-distribution contract | corporate users only。現在の個人pilotには不適合 | ERSが法人運用へ移行した場合の将来候補 | deferred_corporate_only |

## Evidence / Population 取得元レビュー

2026-08-29 追加。上の表は価格データ用で、Evidence（決算短信・適時開示の本文）と
Population（その日の決算発表企業一覧）には別の観点が要る。本文は著作物であり、
価格の数値とは保存・再利用の判断が違う。

**本節は候補の比較であって、採用の記録ではない。** 上と同じ方法論に従い、公開情報
だけで書く。契約・account作成・API接続・scrapingは行っていない。公開情報だけで
確定しない欄は `unknown` とし、推測で埋めない。`unknown` のまま残っている欄がある
限り、その候補からの自動取得は開始しない。

### 判断すべき8項目

| 項目 | 何を確かめるか | 埋まらないと何が起きるか |
| --- | --- | --- |
| `automated_access_permitted` | 利用条件が自動取得を許すか。明示の禁止・許可・沈黙のどれか | `AGENTS.md` の source terms 確認を満たさない |
| `robots_and_rate_limit` | robots.txt の記述、公表されている頻度制限、API の有無 | 許可されていても迷惑をかける取得になる |
| `availability_window` | 当日分・過去分がそれぞれいつまで参照できるか | 「今日取らないと失われる」が本当か判断できない |
| `content_storage_allowed` | **本文**を保存してよいか。metadata・URLだけに制約があるか | Evidence Bundle の `content` を持てるかが決まらない |
| `primary_source_authority` | 一次資料としての正本性。発行者自身か、転載か | primary と fallback の区別が付かない |
| `published_at_fidelity` | 開示時刻をどこまで正確に取れるか。分単位か、日付だけか | Timing Provenance の `timing_class` が決まらない |
| `refetchable_later` | 同一イベントを将来また取得できるか | 取り直しが効くのか、一度きりなのかで運用が変わる |
| `fallback_allowed` | 取得失敗時に別sourceで代替してよいか | 代替を primary と同一扱いする事故が起きる |

### 候補

| source | 役割 | official | automated_access_permitted | robots_and_rate_limit | availability_window | content_storage_allowed | primary_source_authority | published_at_fidelity | refetchable_later | fallback_allowed | review_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `JPX TDnet public viewing service` | population / primary evidence | official / JPX | unknown。上表では `conditional_secondary_pending_automation_terms`、自動accessは別途Human承認 | unknown | 上表の記録では公開閲覧31日、Listed Company Searchは過去10年閲覧。**再確認要** | unknown。上表の `storage_allowed` は価格の話で、本文には及ばない | highest。開示の掲載そのもの | 上表では「実開示日時が掲載時刻」= high。分単位で取れるか要確認 | unknown。閲覧期間との関係で決まる | — | `pending_terms_review` |
| `会社公式IRページ` | fallback evidence | official / 発行会社 | unknown。会社ごとに異なる可能性 | unknown。会社ごと | unknown。会社ごと。掲載期間の統一規則は無い | unknown | high。発行会社自身。ただし掲載は開示より後になり得る | unknown。掲載日時が開示時刻とは限らない | unknown | fallback として位置づける候補 | `pending_terms_review` |
| `J-Quants API` | population 補助 | official / JPXI | 上表では契約・保存・AI処理・自動取得のHuman承認前は採用済みと扱わない | unknown | 上表の記録では2年分だが直近12週間を除く（Free） | 上表: private analysis は likely、raw保存条件は terms 確認要 | high。ただし価格dataが主で、開示本文は範囲外 | 上表: TDnet時刻は別sourceが必要 | unknown | — | `pending_candidate_terms_review`（上表から） |

**上の3候補はいずれも `review_status` が pending であり、どれからも取得していない。**

### 役割の分離

```
Population source   その日の決算発表企業一覧
Primary evidence    開示の一次資料
Fallback evidence   primary が取れなかったときの代替
```

**fallback で取れた資料を primary と同一扱いしない。** `EvidenceBundle` は既に
`source_type` と `discovery_method` を持つので、モデル側の変更は要らない。本レビュー
で `source_type` の値域を確定させれば足りる。

なお上の「暫定推奨」2項は announcement occurrence について「会社公式IRをprimary候補、
TDnetをsecondary候補」としている。**これは開示が起きた事実の確認元の話であり、本節の
Evidence（本文）の primary/fallback とは別の問題**なので、矛盾ではない。ただし両者が
別々に決まると混乱するため、Timing Provenance の設計時にどちらを使うか明示する。

### この節が埋まるまでにしないこと

- 候補からの自動取得
- 本文の保存
- capture adapter の実装

`data/evidence/` は0件のままにする。

## 暫定推奨

1. 第1号prospective pilotで使うproviderは未決であり、J-Quants APIとJ-Quants Proを採用済みとして扱わない。
2. announcement occurrenceは会社公式IRをprimary候補とし、TDnetをsecondary候補にできるが、sourceごとの自動accessはHuman承認を必須とする。
3. priceはHuman承認済みsourceからAIが必要項目だけ取得する方式を目標とし、未承認時は停止または限定的なmanual fallbackへ落とす。
4. Yahoo!ファイナンスは自動取得sourceにせず、Humanによる限定的なfallback候補とする。
5. screenshot、raw chart data、raw price row、derived VWAPは許可条件確認と別承認なしに保存しない。
6. scheduler、price adapter、scraping、automatic captureは本documentation PRでは実装しない。

## raw priceとadjusted priceの採用方針

- event gapとevent直後reactionはunadjusted actual traded priceで計算する。
- adjusted priceはcorporate actionをまたぐ期間横断比較用に別途保持する。
- J-Quantsのadjusted OHLC、unadjusted OHLC、adjustment factorを同一の意味として扱わない。
- minute/tick add-onのadjustment仕様は公式契約文書で確認できるまで `unknown` とする。
- 現行pilotでは `post_earnings_review.return_reference_price` にraw priceを記録し、adjusted priceとfactorはlinkしたevidenceへ記録する。
- 専用の3列追加はpilot後のschema reviewまで延期する。

## 確認が必要な契約事項

- J-Quants個人向けdataをlocal research CSVへ継続保存できる範囲
- Git repositoryへraw price rowsを含めてよいか。原則として含めない想定
- minute/tick add-on解約後の既取得data retention可否
- calculated return、VWAP、chart screenshotの保存・共有可否
- Codex、Claude Code等のagent processがprivate local dataを処理することの扱い
- broker chartの数値転記・screenshot保存・再利用条件

## 公開FAQによるlicense確認結果

2026-07-23時点のJ-Quants公式公開ページから、次を確認した。

| question | public evidence result | pilot judgment |
| --- | --- | --- |
| 個人の分析利用 | J-Quants APIは個人の私的利用に限定 | private manual pilotの技術候補にできる |
| AIによる利用 | 公式ページが生成AIとMCPによるdata accessを案内 | AI利用一般はsupported。ただし外部AI providerへraw dataを送信する契約上の扱いは `unknown` |
| CSV利用 | Light以上でCSV downloadを提供 | local処理の技術手段はあるが、長期retention権限とは別問題 |
| 分析結果・手法の公開 | 自身の分析結果と分析手法の公開は許容 | derived resultの公開余地はある |
| raw dataの配布・共有 | 取得dataそのものを閲覧可能な形で配布・shareすることは禁止 | public repositoryへraw row、raw CSV、可読screenshotを入れない |
| 継続的な第三者提供 | dataを用いた投資分析結果の継続反復提供は私的利用に該当しない | ERSを第三者向け配信serviceとして運用しない |
| 解約 | billing period終了までservice利用可能 | 解約後の既取得data retentionは記載を確認できず `unknown` |

公開FAQだけでは、local長期保存、解約後retention、Codex等の外部agent処理、VWAP等のderived value、screenshot、private Git repositoryへの格納可否を確定できない。問い合わせまたはaccount内に提示される契約文書の人間reviewが終わるまで、J-Quants raw dataを取得・保存・agentへ送信しない。

## 公式参照

- [J-Quants API data overview](https://www.jpx.co.jp/english/markets/other-data-services/j-quants-api/index.html)
- [J-Quants API minute/tick enhancement](https://www.jpx.co.jp/english/corporate/news/news-releases/6020/20260119.html)
- [J-Quants API plans and FAQ](https://jpx-jquants.com/)
- [TDnet overview](https://www.jpx.co.jp/equities/listing/disclosure/tdnet/index.html)
- [JPX FLEX Historical](https://www.jpx.co.jp/english/markets/paid-info-equities/historical/01.html)
- [J-Quants Pro](https://www.jpx.co.jp/markets/other-data-services/j-quants-pro/)
- [Monex Trader chart](https://info.monex.co.jp/tradetool/mtradersp/function/func04.html)

## Review limitation

本書は公開仕様の比較であり、法的判断ではない。`storage_allowed` が `likely` または `unknown` の候補は、terms本文のreviewまたはprovider回答なしにERSの正式sourceへ昇格させない。
