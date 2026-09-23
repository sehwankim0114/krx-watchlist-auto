# V8.17.2 financial valuation multi-blocker root-cause audit

- Selected group: FINANCIAL_VALUATION_CACHE.
- Targets: 73 tickers / 561 blocker occurrences.
- 68 tickers / 536 blockers are absent from both the current financial cache and downstream source cache.
- The financial refresh used a 120-ticker two-table target set; the current scorer universe is 157.
- Refresh order is financial -> source -> current API, so the dominant gap is a dependency refresh-order issue after universe expansion.
- 2 tickers / 15 blockers are official NO_CORP_CODE cases.
- 1 ticker / 8 blockers is the LS ELECTRIC identity mismatch review lane.
- 2 tickers / 2 blockers are intentional loss-PER N/A cases.
- No production cache, API, score, policy, identity rule, or issuer alias is modified.

Next: SHADOW_REFRESH_CURRENT_FINANCIAL_CACHE_V8173
