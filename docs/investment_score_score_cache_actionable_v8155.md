# V8.15.5 Mastern Premier REIT Q2 score-cache audit

- Target: 마스턴프리미어리츠 (357430).
- Current sole blocker: `최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT`.
- Existing V8.11.7 multi-account contract is audited first.
- Official full-account endpoint is independently audited using the same account selector.
- Q2 is reconstructed only as H1 cumulative minus Q1 cumulative for 2026 and 2025.
- Revenue and operating profit are the scorer-required inputs; net-income completeness is reported separately.
- No Q2 value or source-contract change is promoted in this audit step.
- Exact-D&A exhausted union 67 is preserved and not queried.

Classification: `NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH`
Next: `MARK_MASTERN_Q2_PATH_EXHAUSTED_AND_DYNAMIC_REAUDIT_V8156`
