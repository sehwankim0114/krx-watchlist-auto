# V8.7.18 Standalone Swing Readiness Synchronization

## Purpose
Synchronize the preproduction and request-time display-merge readiness layers with the V8.7.17 integrated return-basis source.

## Newly resolved blockers
- `REQUEST_TIME_DISPLAY_MERGE_CONTRACT_NOT_FROZEN_FOR_STANDALONE`
- `1W_YTD_52W_FORMULAS_NOT_APPROVED`

## Approved return contracts
- 1W: 7 calendar days, then first official KRX session on/after.
- 1M/3M/6M: existing calendar-month official-session contracts.
- YTD: prior-calendar-year final official KRX session close.
- 52W: 52 calendar weeks, then first official KRX session on/after.

## Remaining pending metrics
- RSI
- MACD
- 100-point investment score
- earnings-outlook change
- confirmed swing-low stop

## Remaining activation blockers
1. final standalone-table header contract
2. standalone command/route contract
3. RSI/MACD formulas
4. confirmed swing-low stop policy
5. investment-score thresholds/sources
6. earnings-outlook source
7. official KOSDAQ sector-RS contract

## Safety
V8.7.18 does not enable the standalone table, add a command, create a route, change the Worker, alter the Action schema, change production tables, or recompute confirmed metrics from request-time current prices.
