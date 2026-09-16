# V8.11.1 Daegu Department Store combined shadow dry-run

- Version: `2026-09-16-v8.11.1-validation-fix-preserve-daegu-baseline-row`
- Exact baseline: `2026-09-16-v8.10.9-freeze-v8106-source-against-frozen-v8102-validation-fix` / commit `703a902f546b257d5e2aac3fcc4f37636bc72ec3`
- Only 006370 receives V8.11.0 validated annual/Q2 revenue and operating-profit fields.
- The exact V8.10.9 target raw row is preserved; only the 12 V8.11.0-validated annual/Q2 fields are overlaid.
- Cash/debt/D&A/net-cash/EV-EBITDA fields are not reconstructed or altered.
- The three V8.11.0 source-gap reasons must disappear.
- If validated negative annual operating profit exposes `ANNUAL_OP_DENOM_NONPOSITIVE`, it is recorded as an unchanged V880 policy-semantic blocker rather than treated as a source failure.
- Other 111 score rows must remain byte-equivalent at CSV-row level.
