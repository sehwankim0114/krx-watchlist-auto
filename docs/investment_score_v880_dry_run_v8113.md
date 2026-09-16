# V8.11.3 five-financial-ticker revenue shadow dry-run

- Version: `2026-09-16-v8.11.3-validation-fix2-hard-guard-types`
- Baseline: exact reproduction of V8.11.1.
- Evidence: V8.11.2 exact CIS `ifrs-full_RevenueFromInterest` alignment.
- Scope: only six revenue fields for five audited tickers.
- Operating-profit and all other raw-source fields are preserved exactly.
- Expected result verified by scorer: five newly READY tickers, 15 blockers removed.

## Safety

- No source-contract change.
- No production/source/financial cache mutation.
- No automatic account approval.
- No imputation.
- No non-target score drift.
