# V8.11.2 financial revenue semantic alignment audit

- Version: `2026-09-16-v8.11.2-financial-revenue-semantic-alignment-audit`
- Status: AUDIT_ONLY
- Targets: 삼성화재, DB손해보험, 삼성카드, KB금융, BNK금융지주.
- Candidate: CIS / `ifrs-full_RevenueFromInterest` / 이자수익.
- The candidate is not newly approved by this workflow.
- The audit checks whether current financial-cache revenue, previous revenue and revenue YoY are exact matches to this official account.
- It also verifies annual 3-year values and Q2 derivation inputs across current/prior H1 and Q1.
- Q2 is always H1 cumulative minus Q1 cumulative.

## Safety

- No source-contract change.
- No financial-sector exception is created.
- No production/cache mutation.
- No imputation or ambiguous account promotion.

## Next

`SHADOW_TEST_EXPLICIT_NARROW_CIS_INTEREST_REVENUE_EXTENSION_FOR_FIVE_FINANCIAL_TICKERS`
