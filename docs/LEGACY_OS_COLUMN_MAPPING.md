# Legacy Earnings Research OS Column Mapping

## Rules

Source: `earnings-research-os/data/records.csv`

All fields remain available under `raw_record`. A normalized value never replaces the raw value. `ERS destination` is the implemented legacy-only destination, not an assertion that the current strict prospective ERS schema accepts the value.

| legacy column | meaning in old pipeline | phase | type / unit | ERS destination | status | migration rule |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | Japanese equity code | selection | string | `normalized_identity.ticker_candidate` | `normalized_legacy` | Preserve leading zeros; do not create `company_master` automatically |
| `name` | Company name returned by AI | selection | string | `normalized_identity.company_name_candidate` | `reference_only` | Preserve raw name; company identity resolution must detect ticker/name conflict |
| `date` | Date passed to the daily selection and price lookup | selection | date | `normalized_identity.legacy_event_date` | `normalized_legacy` | It is not a verified announcement timestamp or session |
| `quarter` | AI-generated quarter label | selection | string | `normalized_classifications.quarter_raw` | `reference_only` | Preserve variants; map only recognized values and retain warning for the rest |
| `rank` | Old AI rank | selection | string | `normalized_classifications.legacy_rank` | `normalized_legacy` | Legacy aggregation only; never map to `pre_event_grade` |
| `surprise` | Old AI surprise category | selection | string | `normalized_classifications.legacy_surprise` | `normalized_legacy` | Normalize typography only when unambiguous; do not treat as measured surprise |
| `company_forecast` | AI summary of guidance state | selection | string | `normalized_classifications.company_forecast_label` | `reference_only` | No numeric guidance or formal source; do not map to evaluation guidance result |
| `rc1` | First reason code | selection | string | `normalized_classifications.reason_codes[0]` | `normalized_legacy` | Preserve unknown code as raw |
| `rc2` | Second reason code | selection | string | `normalized_classifications.reason_codes[1]` | `normalized_legacy` | Empty remains missing |
| `rc3` | Third reason code | selection | string | `normalized_classifications.reason_codes[2]` | `normalized_legacy` | Empty remains missing |
| `narrative` | Old narrative alignment class | selection | string | `normalized_classifications.legacy_narrative` | `normalized_legacy` | Legacy aggregation only; preserve noncanonical variants |
| `judge` | Old AI judgment label | selection | string | `normalized_classifications.legacy_judge` | `reference_only` | Never map to trade decision or current overall assessment |
| `buy_condition` | Old AI-generated entry-condition text | selection | string | `raw_record.buy_condition` | `reference_only` | Retain as historical research text; do not operationalize |
| `exit_condition` | Old AI-generated withdrawal/exit text | selection | string | `raw_record.exit_condition` | `reference_only` | Do not map to locked hypothesis invalidation without formal reconstruction |
| `memo` | Old AI summary of earnings and guidance | selection | string | `raw_record.memo` | `reference_only` | Not formal evidence; URLs inside text remain unverified text |
| `prev_close` | Close on the row's `date` in yfinance series | post-event enrichment | decimal / JPY | `normalized_prices.legacy_date_close` | `normalized_legacy` | Misnamed for some sessions; never assume pre-event close |
| `next_open` | Open of next trading row after `date` | post-event enrichment | decimal / JPY | `normalized_prices.next_session_open` | `normalized_legacy` | Calendar and session were not stored |
| `next_close` | Close of next trading row after `date` | post-event enrichment | decimal / JPY | `normalized_prices.next_session_close` | `normalized_legacy` | Keep provider and adjustment limitations in warning |
| `d5_close` | Close five trading rows after `date` | post-event enrichment | decimal / JPY | `normalized_prices.fifth_session_close` | `normalized_legacy` | Not equivalent to validated fifth-business-day milestone without calendar proof |
| `d20_close` | Close twenty trading rows after `date` | post-event enrichment | decimal / JPY | `normalized_prices.twentieth_session_close` | `normalized_legacy` | Preserve missing values; current ERS need not add a 20-day prospective milestone |
| `gap` | `(next_open - prev_close) / prev_close` | derived | decimal fraction | `normalized_prices.legacy_gap_return` | `normalized_legacy` | Recalculate for parity and compare with stored raw value |
| `ret_d1` | `(next_close - prev_close) / prev_close` | derived | decimal fraction | `normalized_prices.legacy_d1_return` | `normalized_legacy` | Do not mix with current market-reaction return unless bases match |
| `ret_d5` | `(d5_close - prev_close) / prev_close` | derived | decimal fraction | `normalized_prices.legacy_d5_return` | `normalized_legacy` | Recalculate for parity; retain stored rounding |
| `ret_d20` | `(d20_close - prev_close) / prev_close` | derived | decimal fraction | `normalized_prices.legacy_d20_return` | `normalized_legacy` | Legacy-only horizon |
| `shodo` | Gap category: `GU`, `GD`, or flat | derived | enum-like string | `normalized_classifications.initial_reaction` | `normalized_legacy` | Reproduce old 1% threshold; keep separate from current reaction assessment |
| `reaction` | Intraday continuation/reversal category | derived | enum-like string | `normalized_classifications.legacy_reaction` | `normalized_legacy` | Derived from `shodo`, next open, and next close |
| `result` | Human review result | manual review | string | `raw_record.result` | `unmapped` | All current rows are empty; no meaning or enum is documented |
| `error_type` | Human review error category | manual review | string | `raw_record.error_type` | `unmapped` | All current rows are empty; do not invent a taxonomy |
| `review_note` | Human review note | manual review | string | `raw_record.review_note` | `unmapped` | All current rows are empty; preserve future source values verbatim |

## Direct Mapping Prohibitions

The following mappings are prohibited even when labels look similar.

```text
rank -> pre_event_grade
judge -> pre_event_decision
surprise -> earnings_evaluation.overall_assessment
memo -> evidence.evidence_summary
exit_condition -> hypothesis_log.invalidation_reason
prev_close -> market_reaction pre-event reference
result -> post_event_learning overall result
```

Formal reconstruction may create a separate ERS record later, but it must cite the legacy record, add independent evidence, use actual reconstruction time, and remain `historical_reconstruction`. The migration itself does not perform that reconstruction.
