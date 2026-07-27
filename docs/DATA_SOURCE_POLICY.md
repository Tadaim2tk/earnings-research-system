# Data Source Policy

Do not scrape, store, or automate collection from sources whose terms have not been reviewed. Store citations or source URLs where needed, and keep observed time separate from publication time.

## First Prospective Pilot Override

第1号prospective pilotでは [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) を優先する。会社公式IRとTDnet適時開示情報閲覧サービスの手動閲覧を、candidate固有terms確認後の最小metadata用途に限定する。raw保存、再配布、AIへのraw入力、自動取得はdefault禁止である。J-Quants API、J-Quants Pro、TDnet API、TDnet DBSはscope外とする。

| source_name | data_type | official_or_unofficial | expected_reliability | terms_review_required | automation_status | storage_policy | citation_required | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TDnet | Earnings releases and timely disclosure | official | high | yes | manual viewing only for first pilot | minimum metadata only after Human terms review; no raw PDF | yes | Secondary occurrence confirmation candidate; public availability does not imply unrestricted reuse |
| EDINET | Securities filings | official | high | yes | not implemented | store filing identifiers and extracted facts | yes | Useful for annual and quarterly filings |
| JPX | Listing and market reference data | official | high | yes | not implemented | store reference metadata | yes | Market classification and listing checks |
| Company IR | Releases, guidance, presentations | official | high | yes | manual viewing only for first pilot | minimum metadata only by default; no raw document | yes | Primary calendar/occurrence candidate after issuer-specific terms review |
| Price Data | OHLCV and returns | mixed | medium to high | yes | manual entry only for first pilot | provider-specific approved metadata only | yes | Concrete display source must be approved before baseline start |
| Margin and Short Data | Credit balance and short interest | official or vendor | medium to high | yes | not implemented | store source and effective date | yes | Definitions differ by market |
| Analyst Consensus | Revenue, profit, EPS estimates | vendor | medium | yes | not implemented | store licensed fields only | yes | Paid data availability undecided |
| Minkabu | Retail sentiment and forecasts | unofficial | medium | yes | not implemented | metadata only until terms reviewed | yes | Do not scrape before review |
| SNS | Attention and overheat indicators | unofficial | low to medium | yes | not implemented | no real posts in initial milestone | yes | Use for imbalance, not factual verification |
| Message Boards | Retail narrative and crowding | unofficial | low | yes | not implemented | no raw posts until policy approval | yes | High misinformation and privacy risk |
| News | Event context | mixed | medium to high | yes | not implemented | store title metadata and citation where licensed | yes | Publication time is critical |
