# V8.15.8B target-only financial cache shadow refresh

- Corrects the original V8.15.8 full-refresh row-count assumption.
- Production financial cache rows preserved: 271.
- Fresh current-target refresh rows: 228.
- Merged shadow rows after adding only 28 targets: 299.
- Target financial blockers: 221 -> 8.
- Total scorer blockers: 688 -> 475.
- READY / LIMITED: 21/99 -> 21/99.
- Newly READY target tickers: 0.
- Fully financial-resolved targets: 27.
- Non-target score drift: 0; lost READY: 0.
- No production cache/API/policy file is modified.

Next: STAGE_CURRENT_PRODUCTION_FINANCIAL_CACHE_REFRESH_V8159
