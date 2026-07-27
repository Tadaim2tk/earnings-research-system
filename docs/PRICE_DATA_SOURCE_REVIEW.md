# 価格データ取得元レビュー

## 目的と調査境界

日本株の決算後return検証に必要なdaily OHLC、minute bar、corporate action、announcement timestampの候補を比較する。本書は2026-07-23時点の公開情報による一次調査であり、契約、account作成、API接続、有料申込み、scrapingは行っていない。

価格データを技術的に取得できることと、ERSへ保存・再利用できることは別問題である。`storage_allowed` や `redistribution_allowed` が公開情報だけで確定しない場合は、利用規約またはproviderへの問い合わせ完了まで `unknown` とする。

## 第1号Prospective Pilot Override

本書の候補比較は技術調査として保持するが、第1号prospective pilotでは [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) を優先する。J-Quants API、J-Quants Pro、TDnet API、TDnet DBSを使用せず、具体的な表示元をHumanが個別承認した `manual price entry` だけを候補とする。表示元がbaseline開始前に確定しないcandidateは見送る。

## 候補比較

| provider_name | official_or_third_party | daily_ohlc_available | minute_bar_available | historical_minute_retention | adjusted_price_support | announcement_timestamp_compatibility | api_or_manual | authentication_required | cost | license_review_required | storage_allowed | redistribution_allowed | known_limitations | recommended_use | review_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `J-Quants API Free` | official / JPXI | yes | no | not_applicable | yes。adjusted/unadjusted OHLC | medium。TDnet時刻は別sourceが必要 | API | yes / API key | JPY 0 | yes | private analysisはlikely。raw保存条件はterms確認要 | no。raw dataの配布・共有禁止 | 2年分だが直近12週間を除く。recent pilotには不向き | historical技術調査候補のみ。第1号prospectiveでは使用しない | excluded_from_first_prospective |
| `J-Quants API Light + Tick/Minute Add-on` | official / JPXI | yes | yes | 2 years | daily OHLCはyes。minute/tickのadjustment仕様は要確認 | high。TDnetの実開示時刻とJSTでjoin可能。ただしprice dataはdaily deliveryでreal-timeではない | API / CSV | yes / API key | JPY 1,650 + JPY 5,500 per month, tax included | yes | personal internal researchはlikely。raw retention範囲をterms確認要 | no。raw dataの第三者共有禁止 | individual/private use限定。derivatives対象外。minute/tickはadd-on | 契約条件確認後の将来候補。第1号prospectiveでは使用しない | excluded_from_first_prospective |
| `JPX TDnet public viewing service` | official / JPX | no | no | not_applicable | not_applicable | highest。実開示日時が掲載時刻 | manual viewing | no for public viewing | free | yes | disclosure metadataの記録範囲をterms確認要 | source document再配布は別途確認 | 価格sourceではない。公開閲覧は31日、Listed Company Searchは過去10年閲覧 | terms確認後のmanual secondary occurrence confirmationのみ | conditional_manual_secondary |
| `Monex Trader chart` | third-party market data via broker | yes / display | yes / display | official tablet pageは最大200 bars。長期保持は不明 | unknown | medium。画面上の1-minute OHLCをTDnet時刻と手動照合 | manual | yes / brokerage account | tool is shown as free; account条件あり | yes | unknown | unknown | API/export前提ではない。表示期間・corporate action・licenseが研究DB要件を満たすか不明 | audit付き `manual reference price` のfallbackのみ | manual_fallback_pending_terms |
| `JPX FLEX Historical` | official / JPXI | daily market information plus tick-derived OHLC | tick data。minuteは利用者側集計 | last 30 days / all-period / specified one-month spot。data since 2011 | no automatic adjusted series confirmed。base/issue informationとの別処理が必要 | high。exchange timestamp付きtick | Web API / S3 files | yes / contract | regular single entity JPY 100,000 monthly; all-period JPY 300,000 monthly, tax excluded | yes | internal use under contract | no unless separately approved | PCAP中心で大容量。個人pilotには費用・処理とも過剰 | 将来、tick-level再現性が必須になった場合のみ再検討 | deferred_overkill |
| `J-Quants Pro` | official / JPXI | yes | minute/tickは個別dataset・契約確認要 | daily OHLC since 2008-05-07 | yes。unadjusted/adjusted/factor | high。TDnet/Snowflake等の法人向けdataと連携可能 | API / SFTP / Snowflake | yes / corporate contract | dataset別見積り | yes | internal use under license | no unless approved external-distribution contract | corporate users only。現在の個人pilotには不適合 | ERSが法人運用へ移行した場合の将来候補 | deferred_corporate_only |

## 暫定推奨

1. 第1号prospective pilotからJ-Quants APIとJ-Quants Proを除外する。
2. announcement occurrenceは会社公式IRをprimary候補とし、TDnet手動閲覧をsecondary候補にできる。候補固有terms確認前に正式採用しない。
3. priceは具体的な表示元1つをHumanが選び、viewingとmetadata記録条件を確認したmanual entryに限定する。
4. screenshot、raw chart data、raw price row、derived VWAPは許可条件確認と別承認なしに保存しない。
5. API、scraping、automatic captureは第1号で実装しない。

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
