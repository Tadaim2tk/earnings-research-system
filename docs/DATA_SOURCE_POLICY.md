# Data Source Policy

Do not scrape, store, or automate collection from sources whose terms have not been reviewed. Store citations or source URLs where needed, and keep observed time separate from publication time.

## First Prospective Pilot Override

第1号prospective pilotでは [PROSPECTIVE_OPERATIONS.md](PROSPECTIVE_OPERATIONS.md) を優先する。approval-gated Level 2 monitoringを推奨するが、AIによる定期accessはsourceごとにHumanが `automated_access_permitted=true` と記録した場合だけ許可する。未承認sourceはLevel 1へ落とす。raw保存、再配布、AIへのraw入力、自動取得はdefault禁止であり、各用途を個別承認する。J-Quants API、J-Quants Pro、TDnet API、TDnet DBSは正式採用済みではない。

| source_name | data_type | official_or_unofficial | expected_reliability | terms_review_required | automation_status | storage_policy | citation_required | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TDnet | Earnings releases and timely disclosure | official | high | yes | Level 1 unless automated access is Human-approved | minimum metadata only after Human terms review; no raw PDF by default | yes | Secondary occurrence confirmation candidate; public availability does not imply unrestricted reuse |
| EDINET | Securities filings | official | high | yes | not implemented | store filing identifiers and extracted facts | yes | Useful for annual and quarterly filings |
| JPX | Listing and market reference data | official | high | yes | not implemented | store reference metadata | yes | Market classification and listing checks |
| Company IR | Releases, guidance, presentations | official | high | yes | Level 2 only after issuer-specific automated access approval | minimum metadata only by default; no raw document | yes | Primary calendar/occurrence candidate after issuer-specific terms review |
| Price Data | OHLCV and returns | mixed | medium to high | yes | AI acquisition only after provider-specific approval; otherwise manual fallback | approved minimum fields only; no raw dataset by default | yes | Concrete source and acquisition method must be approved before baseline start |
| Margin and Short Data | Credit balance and short interest | official or vendor | medium to high | yes | not implemented | store source and effective date | yes | Definitions differ by market |
| Analyst Consensus | Revenue, profit, EPS estimates | vendor | medium | yes | not implemented | store licensed fields only | yes | Paid data availability undecided |
| Minkabu | Retail sentiment and forecasts | unofficial | medium | yes | not implemented | metadata only until terms reviewed | yes | Do not scrape before review |
| SNS | Attention and overheat indicators | unofficial | low to medium | yes | not implemented | no real posts in initial milestone | yes | Use for imbalance, not factual verification |
| Message Boards | Retail narrative and crowding | unofficial | low | yes | not implemented | no raw posts until policy approval | yes | High misinformation and privacy risk |
| News | Event context | mixed | medium to high | yes | not implemented | store title metadata and citation where licensed | yes | Publication time is critical |
