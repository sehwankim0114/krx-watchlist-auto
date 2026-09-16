# V8.11.5 temp source-enricher full-refresh regression

- Version: `2026-09-16-v8.11.5-temp-source-enricher-full-refresh-regression`
- Production V8.5.4 source enricher is unchanged.
- Control and patched refreshes both run end-to-end from the same current financial/source-cache seed.
- Patched refresh adds full-account exact CIS interest-revenue evidence only for audited active tickers.
- Exact-ID unique selection only; no fuzzy match and no inactive-target insertion.
- Active source targets: 000810, 005830, 029780, 105560
- Source rows: 242 → 242
- RAW ready: 222 → 226
- Scorer READY: 5 → 8
- Scorer blockers: 2178 → 2166

## Next

`FREEZE_V8115_TEMP_SOURCE_REFRESH_EVIDENCE_AND_PREPARE_STAGED_PRODUCTION_SOURCE_CONTRACT_PATCH`
