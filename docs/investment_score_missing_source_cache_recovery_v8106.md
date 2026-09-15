# V8.10.6 missing source-cache official recovery audit

- Version: `2026-09-15-v8.10.6-missing-source-cache-official-recovery-audit`
- Status: AUDIT_ONLY
- Targets: the 13 V8.10.5 SOURCE_CACHE_ROW_MISSING tickers / 43 blocker occurrences.
- Issuer identity uses only current DART exact stock-code, V8.9.2 exact-stock evidence, or pre-existing V8.8.3 PREFERRED_COMMON aliases.
- New preferred/common aliases are prohibited.
- Official annual/H1/Q1 data are probed and each existing scorer blocker is evaluated for recoverability.

## Safety

- No production/API/cache mutation.
- No score-policy change.
- No guessed issuer mapping.
- No imputation.
- Q2 remains H1 cumulative minus Q1 cumulative.

## Next

`FREEZE_V8106_RECOVERABLE_OFFICIAL_SOURCE_ONLY_THEN_COMBINED_SHADOW_DRY_RUN`
