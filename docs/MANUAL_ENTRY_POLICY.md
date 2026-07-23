# 手入力暫定運用ルール

## 適用範囲

外部price APIを実装する前の3〜5件pilotに適用する。手入力は、欠損値を推測で埋めるためではなく、取得した価格と選択ruleを監査可能に記録するために使う。

## 共通原則

- `announcement_session` とactual announcement datetimeを先に確定する。
- 価格を探す前にsession別selection ruleを選び、later returnを見て変更しない。
- market timezoneは `Asia/Tokyo`、regular sessionとPTSを区別する。
- `return_reference_price_type` が異なるcaseを同一cohortに混ぜない。
- source画面またはdatasetにadjusted/unadjustedの別がある場合は必ず記録し、同じprice fieldで混同しない。
- correctionはappend-onlyとし、旧referenceを上書きしない。

## 価格の2層管理

- event直後のmarket reaction計算には、原則として当時実際に取引されたunadjusted priceを使う。
- adjusted priceはcorporate actionをまたぐ期間横断比較用として別途保持し、event returnのraw referenceと混同しない。
- 現行schemaでは `post_earnings_review.return_reference_price` にunadjusted raw priceを記録する。対応するadjusted price、adjustment factor、basis、sourceはlinkした `evidence.notes` または `evidence.summary` に記録する。
- 将来のschema候補は `return_reference_price_raw`, `return_reference_price_adjusted`, `corporate_action_adjustment_factor` とする。pilot終了前には追加しない。
- adjusted priceしか確認できない場合、それをraw priceとして扱わない。unadjustedへ戻すfactorと計算根拠を監査可能に記録できる場合のみ `manual` とし、それ以外は `unknown` とする。

## `before_open`

- 原則は直前営業日のregular-session unadjusted closeを `previous_close` として使う。
- corporate actionの権利落ち・split等がannouncement日までに効力発生する場合、raw event reactionとadjusted comparisonを別々に計算し、adjustment factorとsource説明をevidenceに残す。
- 夜間PTS priceはprimary referenceに含めない。必要ならsupplemental evidenceとして保存し、regular-session cohortと分離する。
- announcementが実際にはmarket open後だった場合は `intraday` へ分類し直す。

## `intraday`

- 原則はactual announcement datetimeより厳密に前に終了した最後の完全な1-minute barのunadjusted closeを `pre_announcement_price` とする。
- announcementと同じminuteに含まれるbar、またはpost-announcement tradeを含むbarは使わない。
- minute barを取得できない場合のみ `manual` を許容し、price種別、bar終了時刻、sourceを記録する。
- daily closeを代用しない。daily OHLCだけの場合はdescriptive observationに留め、return fieldsを入力しない。
- 売買停止中でもannouncement前の最後の完全なbarが存在する場合はそのbarを候補にできるが、halt開始時刻と「発表直前に取引可能ではなかった」事実をnotesへ記録する。
- 特別気配は約定価格ではない。quoteを使う場合は `manual` とし、`selection_reason` にquoteであることを明記する。trade priceと混在させない。
- actual announcement datetimeが不明、予定時刻しかない、またはsource間で矛盾する場合は `unknown` とする。

## `after_close`

- 原則はannouncement後の次regular sessionの最初のunadjusted成立価格を `next_open` として使う。
- 寄付に約定がなく特別気配またはhaltが継続した場合、単純な気配値を `next_open` としない。
- 最初のregular-session成立価格を採用する場合は、現行enumに専用typeがないため `manual` とし、成立時刻、halt/特別気配、selection ruleを記録する。成立価格も確認できなければ `unknown` とする。
- 夜間PTSはprimary referenceに含めない。PTS reactionを研究する場合は別cohort・別policyとして将来設計する。
- `previous_close` はovernight market reactionの補助evidenceとして保持できるが、first-tradable returnのbaseと混同しない。

## `manual reference price` 必須項目

| field | required | storage location in current schema | rule |
| --- | --- | --- | --- |
| `return_reference_price_type` | yes | `post_earnings_review` | `manual` を指定 |
| `return_reference_price` | yes | `post_earnings_review` | positive numeric。currency/unitをevidenceへ記録 |
| `return_reference_price_datetime` | yes | `post_earnings_review` | timezone付きdatetime |
| `source_name` | yes | `evidence` | providerまたはofficial service名 |
| `source_url_or_identifier` | yes | `evidence.source_url` または `source_title` | URL、screen名、dataset/file identifierのいずれか |
| `observed_at` | yes | `evidence` | 人間が価格を確認した時刻 |
| `recorded_at` | yes | both review/evidence | ERSへ記録した時刻 |
| `selection_reason` | yes | `evidence.notes` 暫定 | 選択ruleとstandard referenceを使えなかった理由 |
| `verified_status` | yes | `evidence` | 初回は原則 `unverified` または `partially_verified` |
| `entered_by` | yes | `evidence.created_by` 暫定 | 入力者を識別できる値 |

現行schemaに専用列がない `selection_reason`, `entered_by`, `source_url_or_identifier` は、pilot中は上表の既存fieldへ記録する。専用schema列の追加はpilot結果を見て別判断とする。

## `unknown` の扱い

`return_reference_price_type=unknown` の場合、次を空欄にする。

- `return_reference_price`
- `return_reference_price_datetime`
- `open_gap_pct`
- `day0_return_pct`
- `day1_return_pct`
- `day5_return_pct`
- `day20_return_pct`
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`

価格不足を理由に、daily close、最も都合のよいquote、後から見つけた高値・安値で補完しない。

## Review checklist

- announcement datetimeはactual disclosureで確認したか。
- bar終了時刻はannouncementより厳密に前か。
- raw referenceとadjusted comparisonを分離し、adjustment factorとbasisを記録したか。
- regular session、PTS、quote、tradeを区別したか。
- source、observed_at、entered_by、selection_reasonがあるか。
- later outcomeを見た後のreference変更ではないか。
