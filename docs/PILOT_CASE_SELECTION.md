# 手入力パイロット対象3件

## 位置づけ

2026-07-23時点で、session別ruleを検証するhistorical reconstruction caseを3件選定した。これは過去資料を現在入力する再構成作業であり、発表前にlockされた正式な `pre_earnings_baseline` ではない。実際の `recorded_at` を過去へ遡及させず、future leakage防止ruleを維持する。

## 選定結果

| pilot_case_id | company | ticker | event | actual disclosure datetime | session | reference policy | selection purpose | timestamp verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `PILOT-01` | 任天堂株式会社 | `7974` | 2025年3月期通期決算 | 2025-05-08 15:30 JST | `after_close` | `next_open` | 引け後のfirst-tradable reaction、raw prior close、adjusted comparison | TDnet metadataのmirrorで確認。Listed Company Searchでhuman再確認要 |
| `PILOT-02` | トヨタ自動車株式会社 | `7203` | FY2025通期決算 | 2025-05-08 13:55 JST | `intraday` | `pre_announcement_price` | 発表前に終了した最後の完全な1-minute bar、同一minute除外 | TDnet metadataのmirrorで確認。Listed Company Searchでhuman再確認要 |
| `PILOT-03` | 株式会社Olympicグループ | `8289` | 2026年2月期通期連結業績予想の修正 | 2026-04-06 08:30 JST | `before_open` | `previous_close` | raw previous close、adjusted comparison、announcement-day open | company IRとTDnet metadataのmirrorで確認。Listed Company Searchでhuman再確認要 |

3件はsessionを各1件含む。`PILOT-03` は定例決算ではなく `guidance_revision` だが、before-open event return ruleの検証対象として採用する。

## Event source

### `PILOT-01`

- event document: [任天堂 2025年3月期決算関連資料](https://www.nintendo.co.jp/ir/pdf/2025/250508.pdf)
- pre-event source: [任天堂 2025年3月期第3四半期決算短信](https://www.nintendo.co.jp/ir/pdf/2025/250204.pdf)
- pre-event company forecast: revenue JPY 1,190,000 million、operating income JPY 280,000 million、EPS JPY 231.91
- accounting standard: `JGAAP`

### `PILOT-02`

- event document: [Toyota FY2025 Financial Summary](https://global.toyota/pages/global_toyota/ir/financial-results/2025_4q_summary_en.pdf)
- pre-event source: [Toyota FY2025 Third Quarter Financial Summary](https://global.toyota/pages/global_toyota/ir/financial-results/2025_3q_summary_en.pdf)
- pre-event company forecast: sales revenues JPY 47,000,000 million、operating income JPY 4,700,000 million、basic EPS JPY 340.87
- accounting standard: `IFRS`

### `PILOT-03`

- event source index: [Olympic Group IR news](https://www.olympic-corp.co.jp/ir/news/)
- pre-event source: [Olympic Group 2026年2月期第3四半期決算短信](https://www.olympic-corp.co.jp/ir/earnings_report/y2026/)
- pre-event company forecast: operating revenue JPY 98,000 million、operating loss JPY 980 million、net loss attributable to owners JPY 1,450 million
- accounting standard: `JGAAP`

## 価格取得状態

| pilot_case_id | raw reference | adjusted comparison | adjustment factor | status |
| --- | --- | --- | --- | --- |
| `PILOT-01` | not acquired | not acquired | unknown | J-Quants storage termsのhuman確認待ち |
| `PILOT-02` | not acquired | not acquired | unknown | minute dataのstorage/agent処理条件確認待ち |
| `PILOT-03` | not acquired | not acquired | unknown | J-Quants storage termsのhuman確認待ち |

日足終値を `PILOT-02` の発表前価格として代用しない。価格sourceが承認されるまでreturn fieldsは空欄とする。

## 正式baseline化の条件

historical reconstructionを現行 `pre_earnings_baseline` CSVへ入れると、現在の `recorded_at` がannouncement後になりvalidatorにより拒否される。過去時刻を入力して通過させることはしない。

正式baseline pilotは、将来eventについてannouncement前に作成・lockする。historical reconstructionを研究対象として残す場合は、次のいずれかを別途承認する。

- `baseline_mode=prospective|retrospective_reconstruction` の追加
- reconstruction専用tableの追加
- baselineとは別のpilot worksheetとして非authoritative保存

本パイロットでは3番目を採用し、schema変更は行わない。
