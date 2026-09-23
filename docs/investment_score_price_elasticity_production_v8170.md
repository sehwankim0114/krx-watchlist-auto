# V8.17.0 controlled narrow production price-elasticity patch

- Added only 롯데지주 (004990) to production elasticity cache.
- Cache rows: 151 -> 152.
- Existing 151 rows are preserved field-for-field.
- READY / LIMITED: 21/99 -> 22/98.
- Blockers: 322 -> 321.
- Post-apply score equals the tested V8.16.9 staged state.
- API, scoring policy, and production score are not modified.
- Rollback guard covers cache, metadata, and run log.

Next: POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8171
