# V8.11.1 Daegu Department Store source-only extension

- Version: `2026-09-16-v8.11.1-validation-fix-preserve-daegu-baseline-row`
- Ticker: 006370 대구백화점
- Evidence: V8.11.0 current V8.5.4 contract fully recovered all three source-cache missing-input reasons.
- Only validated annual/Q2 revenue and operating-profit fields are exposed to the shadow scorer.
- Deep cash/debt/D&A fields are deliberately blanked in the shadow row.
- No production cache is changed.
