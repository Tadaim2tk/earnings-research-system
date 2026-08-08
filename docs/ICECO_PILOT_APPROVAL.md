# ICECO Pilot Human Approval Packet

## Status

本書は株式会社アイスコを第1号prospective pilotへ正式採用する前のHuman判断資料である。技術的に取得可能であることと、対象sourceへの自動accessを許可することを分離する。

```text
candidate_status = human_approval_pending
event_identity = pending_formal_record
terms_review_state = candidate_specific_review_pending
decision = pending
```

本書だけでcompany、event、evidence、baseline、monitor targetを作成またはactivationしない。運用契約の正本は [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md)、append-only判断履歴は [PROSPECTIVE_PILOT_LOG.md](PROSPECTIVE_PILOT_LOG.md) とする。

## Candidate

| field | proposed value | status |
| --- | --- | --- |
| `company_name` | 株式会社アイスコ | Human candidate selection済み、正式pilot採用はpending |
| `ticker` | `7698` | candidate metadata |
| `market` | TSE Standard | candidate metadata |
| `earnings_event_type` | quarterly earnings | proposed |
| `accounting_period` | 2027年3月期 第1四半期 | official calendar記載に基づく候補 |
| `scheduled_date` | `2026-08-13` | official calendar記載、変更可能性あり |
| `scheduled_session` | `unknown` | 時刻を推測しない |
| `event_identity` | `pending_formal_record` | schemaへ投入するIDではない |
| `schedule_profile` | `prospective_event_v1` | Human approval pending |

公式IR calendarには2026年8月13日の「2027年3月期 第1四半期決算発表」が掲載されている。日程は予告なく変更され得るため、calendar監視は予定日の確定を意味しない。

## Proposed Official Source Targets

| proposed target ID | URL | proposed use | approval state |
| --- | --- | --- | --- |
| `ICECO_IR_CALENDAR` | https://www.iceco.co.jp/ir/calendar/ | 決算予定日の確認と変更候補検知 | pending |
| `ICECO_IR_LIBRARY` | https://www.iceco.co.jp/ir/library/ | 新規IR資料への導線候補検知 | pending |
| `ICECO_IR_ROOT` | https://www.iceco.co.jp/ir/ | IRニュース・IR情報全体の補助的な変更候補検知 | pending |

より直接的なIRニュース一覧URLは未確認であり、推測追加しない。上記はdocumentation上の候補で、production registry rowではない。

```text
primary_calendar_source = ICECO_IR_CALENDAR (pending Human approval)
primary_occurrence_source = ICECO_IR_LIBRARY (pending Human approval)
secondary_confirmation_source = ICECO_IR_ROOT (pending Human approval)
```

TDnetは今回activationせず、candidate固有termsが未承認の間はLevel 2 source assignmentへ含めない。

## Disclosure Policy Review Material

Humanから提供された公式ディスクロージャーポリシーの確認結果を、次の判断材料として保持する。

- 法令および東京証券取引所の適時開示規則に基づいて情報を開示する。
- 適時開示はTDnetを通じて行う。
- TDnet公開後、速やかに会社Webサイトへ掲載する方針である。
- 適時開示規則の対象外でも、重要または有益と判断した情報をWeb等で広く開示する。
- 決算期末日の翌日から決算発表日までを沈黙期間とする。

```text
source_owner = 株式会社アイスコ
source_page = official disclosure policy
source_url = pending_human_confirmation
review_material_origin = Human-provided official-site review result
```

正確な個別URLは今回のno-network作業材料に含まれていないため推測しない。Human承認時に公式IR rootから到達したURLを記録する。

## Disclaimer Review Material

Humanから提供された公式IR免責事項の確認結果を、次の判断材料として保持する。

- 掲載情報は投資勧誘を目的としない。
- 投資判断は利用者自身の責任で行う。
- 掲載情報は予告なく変更または掲載中止となる可能性がある。
- Webサイトを正常に利用できない場合がある。
- 情報の誤り、第三者による改ざん、データのdownload等から生じる損害について会社は責任を負わない旨が示されている。

```text
source_owner = 株式会社アイスコ
source_page = official IR disclaimer
source_url = pending_human_confirmation
review_material_origin = Human-provided official-site review result
```

正確な個別URLはHuman承認時に記録する。免責事項の存在は自動accessの許可を意味しない。

## Automated-Access Terms Assessment

確認済み材料からは次の状態だけを記録できる。

```text
explicit automated access prohibition = not_found_in_reviewed_pages
explicit automated access permission = not_found
absence_of_prohibition_is_affirmative_permission = false
automated_access_permitted = false
terms_review_state = candidate_specific_review_pending
decision = pending
```

`automated_access_permitted=false` は現時点のfail-closed値であり、恒久的な不許可判断ではない。Humanが対象URLと低負荷条件を特定して承認するまで `true` に変更しない。

## Terms Review Records

[PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) の13 fieldsをsourceごとに省略せず使用する。

### ICECO_IR_CALENDAR

```text
source_name: ICECO_IR_CALENDAR
source_category: company_ir_calendar
viewing_permitted: pending
metadata_recording_permitted: pending
raw_storage_permitted: false
redistribution_permitted: false
ai_raw_input_permitted: false
automated_access_permitted: false
terms_checked_at: pending
terms_checked_by: pending
terms_reference: https://www.iceco.co.jp/ir/calendar/; official disclosure policy exact URL pending; official IR disclaimer exact URL pending
recheck_trigger: terms change suspicion, source URL change, operating method change, raw storage proposal, or automation scope change
terms_review_state: candidate_specific_review_pending
```

### ICECO_IR_LIBRARY

```text
source_name: ICECO_IR_LIBRARY
source_category: company_ir_disclosure_index
viewing_permitted: pending
metadata_recording_permitted: pending
raw_storage_permitted: false
redistribution_permitted: false
ai_raw_input_permitted: false
automated_access_permitted: false
terms_checked_at: pending
terms_checked_by: pending
terms_reference: https://www.iceco.co.jp/ir/library/; official disclosure policy exact URL pending; official IR disclaimer exact URL pending
recheck_trigger: terms change suspicion, source URL change, operating method change, raw storage proposal, or automation scope change
terms_review_state: candidate_specific_review_pending
```

### ICECO_IR_ROOT

```text
source_name: ICECO_IR_ROOT
source_category: company_ir_news_index
viewing_permitted: pending
metadata_recording_permitted: pending
raw_storage_permitted: false
redistribution_permitted: false
ai_raw_input_permitted: false
automated_access_permitted: false
terms_checked_at: pending
terms_checked_by: pending
terms_reference: https://www.iceco.co.jp/ir/; official disclosure policy exact URL pending; official IR disclaimer exact URL pending
recheck_trigger: terms change suspicion, source URL change, operating method change, raw storage proposal, or automation scope change
terms_review_state: candidate_specific_review_pending
```

## Proposed Low-Impact Operating Conditions

Humanが自動accessを承認する場合も、承認範囲は次に限定する。

- public pages only
- HTTPS only
- authentication、cookies、session login、form submissionなし
- PDF bulk downloadなし
- redistributionなし
- metadata-only persistence
- bounded response size、DNS timeout、request timeout、workflow job timeout
- one target at a time
- low-frequency schedule
- explicitly approved URL／origin以外をcrawlしない
- redirectはapproved origin内だけ
- `1 target = 1 LiveSourceAdapter instance`
- raw HTML、PDF、screenshotを永続保存しない

## Proposed Monitoring Schedule

```text
schedule_profile = prospective_event_v1
normal_stale_gap = 36h
event_window_stale_gap = 24h
event_day_stale_gap = 12h
scheduled_session = unknown
```

- 通常期間はbusiness dayに1回を候補とする。
- 予定日の5営業日前からbusiness dayに1回以上とする。
- 前日はHuman-approved windowで追加確認できる。
- 2026年8月13日のevent dayはsessionを推測せず、12時間のstale上限を使用する。
- workflow cronの具体値は本approval packetの判断対象にしない。

## Raw Storage Policy

```text
raw_storage_status = metadata_only
raw_location = empty
content_hash_status = not_recorded
content_hash = empty
content_hash_algorithm = empty
```

Humanが別途承認しない限りraw HTML、PDF、download file、screenshotを永続保存しない。source URLは `raw_location` ではない。

## Human Reviewer Identifier

repository内のfictional sample identifierは実pilotへ再利用しない。正式なstable Human reviewer identifierは未設定である。

```text
reviewer_identifier = pending_human_assignment
```

## CP-1 Adapter Lifetime

PR #15時点の `LiveSourceAdapter` はDNS timeoutをinstanceへstickyに保持する。第1号pilotでは次を必須のoperational assumptionとする。

```text
1 target = 1 LiveSourceAdapter instance
```

1 instanceを複数targetで共有しない。複数target対応前に、timeout stateをtarget scopeへ分離する修正と独立監査を必須とする。

## Approval Decision Block

| decision | Human question | initial state |
| --- | --- | --- |
| A | ICECO公式IRページへの低頻度自動GETを許可するか | `pending` |
| B | 許可対象URL／originをどこまでとするか | `pending` |
| C | `raw_storage_status=metadata_only`を承認するか | `pending` |
| D | `schedule_profile=prospective_event_v1`を承認するか | `pending` |
| E | stable reviewer identifierを何にするか | `pending` |
| F | 次のPRでactivationを実施してよいか | `pending` |

全項目をHumanが記録するまでE2-Bへ進まない。承認後もregistry変更、initialization、初回live runは次PRの独立差分とする。

## Current Boundary

- production registry target countは0を維持する。
- ICECO、TDnet、その他実sourceへHTTP requestを送らない。
- company、event、formal evidence、baseline、initialization runを作成しない。
- workflowへlive adapterを接続しない。
- `enabled=true`、`automated_access_permitted=true`、`activation_state=activated`を記録しない。
