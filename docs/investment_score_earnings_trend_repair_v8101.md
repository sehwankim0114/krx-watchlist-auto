# V8.10.1 earnings-trend source wiring repair

- Version: `2026-09-15-v8.10.1-repair-earnings-trend-wiring`
- Status: source wiring repaired; score remains dry-run only

## Repair

- `earnings_trend` now uses `net_income` and `previous_net_income`.
- The 17 V8.9.9-confirmed cache mismatches were repaired surgically.
- No other financial-cache fields were changed.
- A loss-company self-test now verifies `적자전환` semantics.

## Revalidation

- 112 score rows exactly match the V8.9.9 shadow dry-run.
- READY = 45, LIMITED = 67.
- 003490, 009420, 139480 are READY with no remaining PER blocker.

## Safety

- Production API untouched.
- Production investment score not written.
- Scoring policy unchanged.
- Raw source cache unchanged.
- No value imputation.

## Next

`REFRESH_REMAINING_INVESTMENT_SCORE_BLOCKERS_AFTER_V8101_REPAIR`
