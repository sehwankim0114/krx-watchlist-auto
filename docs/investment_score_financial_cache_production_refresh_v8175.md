# V8.17.5 controlled production financial cache refresh

- Promotes the exact V8.17.4 staged candidate into production.
- Financial cache rows: 240 -> 308.
- Existing 240 rows remain unchanged; 68 rows are added.
- Total blockers: 1388 -> 906 (-482).
- Target financial blockers: 536 -> 54 (-482).
- READY/LIMITED remains 14/143; lost READY is 0.
- 61 target score rows change exactly as staged.
- Post-apply scorer output exactly matches the staged scorer output.
- Financial RUN_AT_KST is refreshed so V8.5.4 can detect that the source cache must refresh.
- Rollback restores the prior financial cache and run log on post-apply failure.
- API, policy, source cache and production score remain unchanged in this step.

Next: POST_FINANCIAL_APPLY_SOURCE_REFRESH_REAUDIT_V8176
