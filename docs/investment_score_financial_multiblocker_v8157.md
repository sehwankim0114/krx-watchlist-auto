# V8.15.7 financial valuation multi-blocker root-cause audit

- Selected group: `FINANCIAL_VALUATION_CACHE`.
- Targets: 35 tickers / 262 blocker occurrences.
- 28 tickers / 221 blockers: current production tickers missing from both financial cache and raw score-source cache.
- 4 preferred shares / 31 blockers: no separate OpenDART stock-code corp mapping; no alias is inferred.
- 1 ticker / 8 blockers: LS ELECTRIC name-identity mismatch requires a separate identity-policy review.
- 2 tickers / 2 blockers: complete financial data but PER intentionally undefined because annualized net income is non-positive.

- Financial cache run: 2026-09-22T11:00:06+09:00
- Raw score cache run: 2026-09-22T13:46:01+09:00
- Current production API build: 2026-09-22T14:23:05+09:00

The dominant 28-ticker gap is a dependency-refresh ordering problem, not 28 independently proven issuer failures.
No production cache, API, score, identity policy, or scoring policy is modified in this audit.

Next: `REFRESH_CURRENT_PRODUCTION_FINANCIAL_CACHE_AND_SHADOW_V8158`
