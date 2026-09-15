# V8.9.9 PER loss semantics and earnings-trend wiring audit

- Version: `2026-09-15-v8.9.9-per-loss-earnings-trend-wiring-audit`
- Status: audit + shadow dry-run only
- Production mutation: none

## Purpose

- Verify whether `earnings_trend` matches the approved meaning `순이익 흐름`.
- Recompute trend from net income only in a temporary shadow cache.
- Reuse the approved V8.8.2 scorer and V8.9.5 D&A shadow inputs.
- Measure READY/LIMITED and score impact before any source patch.

## Safety

- No scoring threshold changes.
- No PER imputation for loss companies.
- No production score write.
- No persistent financial/source cache mutation.

## Next

`PATCH_EARNINGS_TREND_SOURCE_WIRING_AND_REBUILD_FINANCIAL_CACHE_THEN_RERUN_DRY_RUN`
