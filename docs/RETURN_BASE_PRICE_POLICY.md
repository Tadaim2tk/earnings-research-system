# Return Base Price Policy

## Why The Base Price Matters

Post-earnings returns are only comparable when the reference price is explicit. A strong day-zero return can mean very different things depending on whether it is measured from the previous close, the price immediately before an intraday announcement, the announcement-day close, the next open, or VWAP after the release.

If this policy is vague, later win-rate and reaction studies will mix incompatible cases and introduce look-ahead bias.

`earnings_event.return_base_price_policy` records the intended policy. `post_earnings_review.return_reference_price_type`, `return_reference_price`, and `return_reference_price_datetime` record the actual price used for return calculations. Return windows must not be filled without those review-side reference fields.

## before_open

Candidate base prices:

- `previous_close`: simple and available from daily data.
- `next_open`: useful for tradable gap measurement, but not known before the open.
- `manual`: allowed when the market was halted or a special quote applies.

Initial policy: use `previous_close` for research surprise reaction, and record `next_open` separately when price data is available.

## intraday

Candidate base prices:

- `pre_announcement_price`: preferred when a reliable timestamped price is available.
- `vwap_after_announcement`: useful for event-window studies, but requires intraday data.
- `announcement_day_close`: available from daily data but can hide the immediate reaction.
- `manual`: allowed when only a reviewed manually captured quote is available.

Initial policy: use `pre_announcement_price` for intraday events when available. If not available, set `return_base_price_policy=manual` or `unknown` and keep return interpretation conservative.

## after_close

Candidate base prices:

- `previous_close`: clean measure of overnight gap from the last regular session.
- `next_open`: useful for practical next-session reaction.
- `manual`: allowed for special sessions.

Initial policy: use `next_open` for first tradable reaction and preserve `previous_close` in price evidence when available.

## Manual Entry Notes

- Record the event session before entering return windows.
- Do not fill intraday reaction fields from daily close alone without noting the limitation.
- If the base price is unknown, keep `return_base_price_policy=unknown` and treat reaction scores as provisional.
- Do not revise the base price after seeing day5/day20 results unless the change is appended and justified.

## Future Automation Requirements

- Timestamped announcement feed.
- Intraday price or quote data for `pre_announcement_price`.
- VWAP calculation window definition.
- Corporate action adjusted OHLCV.
- Market halt and special quote flags.

## Look-Ahead Bias Risks

- Using announcement-day close as if it were known at 13:00.
- Choosing the most favorable base price after seeing the reaction.
- Mixing next-open returns with intraday returns in the same calibration bucket.
- Updating baseline decisions with price data observed after the baseline lock.
