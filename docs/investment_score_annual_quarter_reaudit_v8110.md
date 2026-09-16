# V8.11.0 annual + quarter official revenue recovery audit

- Version: `2026-09-16-v8.11.0-annual-quarter-official-revenue-recovery-audit`
- Status: AUDIT_ONLY
- Targets: 삼성화재, DB손해보험, 대구백화점, 삼성카드, KB금융, BNK금융지주.
- Existing 18 source-cache blockers only.
- Reuses the current V8.5.4 `ACCOUNT_SPECS['revenue']` contract exactly.
- Fresh OpenDART full-account data are checked for 2025 annual, 2026 H1/Q1 and 2025 H1/Q1.
- Q2 remains H1 cumulative minus Q1 cumulative.
- Revenue-like official accounts outside the current contract are evidence only; they are never promoted automatically.

## Safety

- No account-spec change.
- No financial-sector exception.
- No production/cache mutation.
- No imputation.
- No ambiguous account promotion.

## Next

`FREEZE_V8110_CURRENT_CONTRACT_RECOVERABLE_FIELDS_SOURCE_ONLY_THEN_SHADOW_DRY_RUN`
