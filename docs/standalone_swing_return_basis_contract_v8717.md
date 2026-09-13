# Standalone Swing Return Basis Contract V8.7.17

## Status
- Source-only contract.
- Standalone swing table remains disabled.
- No Action route or new user command is enabled.
- No production table or Worker is changed.

## Approved return bases
- 1W: basis date minus 7 calendar days, then the first official KRX market session on or after that date.
- 1M: existing approved calendar-month contract.
- 3M: existing approved calendar-month contract.
- 6M: existing approved calendar-month contract.
- YTD: final official KRX market-session close of the prior calendar year to the basis-date close.
- 52W: basis date minus 52 calendar weeks, then the first official KRX market session on or after that date.

## Official-session source
- `latest/active_stock_long_history_260d_latest.csv`
- The V8.5.7 builder backfills this cache through official KRX KOSPI/KOSDAQ daily OpenAPI until 260 distinct official market sessions are present.
- The recent overlap must exactly match KOSPI and KOSDAQ dates in `latest/official_index_history_latest.csv`.

## No IPO-date substitution
A stock must have a close on the globally resolved start session. If it was not yet listed or otherwise has no bar for that session, the return remains missing with `HISTORY_SHORT_OR_DATE_MISSING`. The first available post-listing bar must never be substituted.

## Expected basis-date coverage (2026-09-11)
- 1W: 235/235
- 6M: 234/235; missing `439960`
- YTD: 234/235; missing `439960`
- 52W: 233/235; missing `217590`, `439960`

## Safety
RSI, MACD, investment score, earnings-outlook change, confirmed swing-low stop, KOSDAQ sector RS, request-time current-price composition, user-facing route activation, and final display header are outside this contract.
