# 価格データ粒度方針

## 目的と位置づけ

本書は、決算後returnを再現可能に検証するための暫定価格データ方針を定める。vendor選定、API接続、return自動計算、backtestは行わない。

`earnings_event.return_base_price_policy` は意図した方式を記録し、`post_earnings_review.return_reference_price_type`, `return_reference_price`, `return_reference_price_datetime` は実際に使用した価格を記録する。監査可能なreference priceがないreturn windowは入力しない。

## 粒度比較

評価は現在のmanual-first ERSフェーズを基準とする。

| price data option | 取得しやすさ | 場中決算への対応 | ルックアヘッドバイアスリスク | 保存コスト | 手入力運用との相性 | 将来の自動化しやすさ | 検証精度 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `daily close only` | 高 | 不可 | 場中では高 | 非常に低 | 高 | 高 | 低。open/high/lowと発表時点の状態を失う |
| `daily OHLC` | 高 | 限定的。発表前後を分離不可 | 場中では中から高 | 低 | 高 | 高 | before/afterでは中、intradayでは低 |
| `minute bar` | 中 | 高。timestamp・timezone・session・volumeの信頼性が条件 | 中。境界ルールの事前固定が必要 | 中 | 中 | 高 | event-window研究には高 |
| `tick data` | 低 | 非常に高 | 中。trade/quote選択と時系列順序が複雑 | 非常に高 | 低 | 中 | 潜在的に最高だが現段階では過剰 |
| `manual reference price` | 運用上は高。ただしevidence採取が必要 | 正しい時刻で取得できれば中から高 | source・時刻・timezone・選択ruleがなければ高 | 非常に低 | 高 | 低 | 監査可能な暫定値としてのみ許容 |
| `VWAP after announcement` | 中。intraday priceとvolumeが必要 | 高 | windowを結果後に選ぶと中から高 | 中 | 低から中 | 高 | 定義済みpost-release windowには高。ただしpre-announcement reactionとは別指標 |

## 暫定の最低データセット

- `before_open` と `after_close` の一般データはcorporate-action-adjusted `daily OHLC` を最低要件とする。
- `intraday` の再現可能な `pre_announcement_price` または `vwap_after_announcement` には `minute bar` を要求する。
- `manual` はevidenceと変更不能な選択理由を持つ例外としてのみ許容する。
- `tick data` は、実在手入力caseで必要性が確認されるまで延期する。
- `announcement_session` と `return_reference_price_type` が異なるcaseを、同一calibration cohortに混在させない。

## 発表session別reference policy

### `before_open`

主referenceは `previous_close`。直前regular sessionのadjusted closeと定義する。

announcement-day openは別値で記録し、overnight gapとregular-session内の動きを分離する。`next_open` はfirst-tradable-priceを測る別の問いなので、`previous_close` の代替として黙って使用しない。

最低要件はadjusted daily OHLCと、regular-session open前であることを確認できるannouncement timestamp。

### `intraday`

主referenceは `pre_announcement_price`。暫定的に「公開announcement timestampより厳密に前に終了した最後の完全な1-minute barのclose」と定義する。announcement timestamp、market timezone、daylight-saving、bar interval convention、halt stateを記録する。

発表がminute境界と一致する場合も、終了時刻が発表時刻より厳密に前のbarを使う。post-announcement tradeを含むbarをpre-announcement referenceにしない。

最低要件はminute barsと信頼できるtimestamp。取得不能なら監査可能な `manual` を使うか `unknown` としてreturn fieldsを空欄にする。daily OHLCだけでは確定的な場中reactionを算出しない。

### `after_close`

first-tradable reactionの主referenceは `next_open`。announcement後の次regular session opening priceと定義する。announcement-day adjusted closeは別のprice evidenceとして保持し、overnight gapを再構成可能にする。

close-to-closeのannouncement impactを測る分析では `previous_close` を使い、`next_open` cohortと分離する。

最低要件はadjusted daily OHLCと、regular-session close後であることを確認できるannouncement timestamp。extended-hours releaseやdelayed announcementは明記する。

## `pre_announcement_price` を取得できない場合

結果を見て有利な価格へ置き換えず、次の順で扱う。

1. timestamp・session ruleを満たすvendor minute barを使う。
2. 事前定義ruleで取得したtimestamp付き価格とsourceがある場合のみ `return_reference_price_type=manual` を使う。
3. どちらもなければpolicyまたはreview reference typeを `unknown` とし、`return_reference_price` と依存する全return windowを空欄にする。

`announcement_day_close` はdescriptive outcomeとして保存できるが、`pre_announcement_price` と呼び替えない。

## `return_reference_price_type=manual` の扱い

manual referenceはreviewとlinkされたevidenceで次を保持する。

- numeric priceとcurrencyまたはprice unit
- timezone付きexact datetime
- source nameと、許可される場合はURL/pathまたはscreenshot/archive参照
- trade、quote、bar close、official close、calculated valueの別
- capture/observation timeとrecorder
- standard referenceを利用できなかった理由
- day1/day5/day20 outcomeを見ずに固定したselection rule

manual値はreview完了までprovisionalとする。later returnを見た後の訂正はappend-only correctionで行い、旧referenceを上書きしない。

## VWAP利用時の注意点

計算前に次を固定する。

- public announcement timestampに対するwindow start
- 5分、15分、30分等のwindow duration
- regular、extended、auction sessionの含有
- trade condition filterとcorrection/cancellationの扱い
- 使用するprice・volume field
- market haltとzero-volume intervalの扱い
- timezoneとdaylight-saving rule
- corporate-action adjustment policy
- session close直前発表の扱い

`vwap_after_announcement` はpost-release execution benchmarkであり、`pre_announcement_price`, `previous_close`, `next_open` と同一基準として比較しない。

## 日足だけで場中決算を検証する危険性

daily candleは発表前後の価格を混在させる。発表時に利用可能だった価格、high/lowの発生順、haltの有無、close-to-close moveのうち発表前に起きた割合を判別できない。daily closeを発表時価格として使うとlook-aheadが入り、見かけのreturn方向すら逆転しうる。

daily OHLCによるintraday caseの粗いdescriptive labelは許容できるが、validなintradayまたはmanual referenceが追加されるまでprovisionalとし、精密reaction calibrationから除外する。

## 将来自動化に必要なprovenance

将来のprice sourceはsymbol/instrument mapping、exchange calendar、timezone、adjustment flags、bar timestamp convention、ingestion time、source/vendor、raw-row identityまたはhashを保持する。vendor、license、retention、redistributionは未決事項とする。
