# Data Source Policy

Do not scrape, store, or automate collection from sources whose terms have not been reviewed. Store citations or source URLs where needed, and keep observed time separate from publication time.

| source_name | data_type | official_or_unofficial | expected_reliability | terms_review_required | automation_status | storage_policy | citation_required | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TDnet | Earnings releases and timely disclosure | official | high | yes | not implemented | store metadata and citation, raw files only after policy approval | yes | Primary Japanese disclosure source candidate |
| EDINET | Securities filings | official | high | yes | not implemented | store filing identifiers and extracted facts | yes | Useful for annual and quarterly filings |
| JPX | Listing and market reference data | official | high | yes | not implemented | store reference metadata | yes | Market classification and listing checks |
| Company IR | Releases, guidance, presentations | official | high | yes | not implemented | store URL, published_at, extracted facts | yes | Company-specific format variance |
| Price Data | OHLCV and returns | mixed | medium to high | yes | not implemented | store vendor, timestamp, adjustment policy | yes | Return benchmark is undecided |
| Margin and Short Data | Credit balance and short interest | official or vendor | medium to high | yes | not implemented | store source and effective date | yes | Definitions differ by market |
| Analyst Consensus | Revenue, profit, EPS estimates | vendor | medium | yes | not implemented | store licensed fields only | yes | Paid data availability undecided |
| Minkabu | Retail sentiment and forecasts | unofficial | medium | yes | not implemented | metadata only until terms reviewed | yes | Do not scrape before review |
| SNS | Attention and overheat indicators | unofficial | low to medium | yes | not implemented | no real posts in initial milestone | yes | Use for imbalance, not factual verification |
| Message Boards | Retail narrative and crowding | unofficial | low | yes | not implemented | no raw posts until policy approval | yes | High misinformation and privacy risk |
| News | Event context | mixed | medium to high | yes | not implemented | store title metadata and citation where licensed | yes | Publication time is critical |
