# V8.17.6 shadow post-financial source refresh

- Confirms V8.5.4 timestamp gate requires a source refresh.
- Production source cache remains 227 rows.
- Isolated refresh produces 288 rows, adding exactly the 61 newly financial-resolved tickers.
- Blockers: 906 -> 543.
- READY: 14 -> 14.
- Newly READY: 0.
- Expected preferred-share inherited score changes: 3 (000225, 002787, 078935).
- Unexpected non-added score drift: 0; lost READY: 0.
- Production source cache, API, policy and score remain unchanged.

Next: STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177
