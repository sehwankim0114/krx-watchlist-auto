# V8.10.4 next single-source recoverability audit

- Version: `2026-09-15-v8.10.4-next-single-source-recoverability-audit`
- Status: AUDIT_ONLY
- Targets: 001020 페이퍼코리아, 357250 미래에셋맵스리츠

## 001020

- Rebuild ATR14 only from confirmed official KRX daily OHLC.
- Re-fetch only missing/invalid official sessions in memory.
- Do not substitute average daily range for ATR.

## 357250

- Audit the approved OpenDART full-account path.
- Q2 is H1 cumulative minus Q1 cumulative, exactly following V8.5.4 source semantics.
- Do not use H1 directly as Q2 and do not impute missing values.

## Safety

- No production/API/cache/history mutation.
- No score-policy change.
- No automatic promotion.

## Next

`DEFER_V8104_EXHAUSTED_SINGLE_SOURCES_AND_MOVE_TO_NEXT_MULTI_BLOCKER_GROUP`
