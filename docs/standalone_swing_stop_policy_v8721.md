# V8.7.21 Standalone Swing Confirmed-Stop Policy

## Status
Policy-only / preproduction. No numeric confirmed swing-low stop is created.

## Confirmed swing-low stop
- Current numeric source: not provided.
- Display when unavailable: `자료 미제공`.
- Do not derive, infer, backfill, estimate, or fabricate a numeric stop.
- Request-time current price must not create or recompute this stop.

## MA20
- MA20 is a reference line only.
- Display label: `20일선 참고선`.
- MA20 is not a guaranteed stop price.
- MA20 must not be copied into `confirmed_swing_low_stop`.

## Source behavior
All 235 current rows keep `confirmed_swing_low_stop = null` and receive status `NOT_PROVIDED_CURRENT_CONTRACT`. The already-confirmed MA20 level remains available separately as a reference.

## Safety
This policy does not change the production two-table output, Worker, Action schema, existing command count, standalone route, user command, or final table header.
