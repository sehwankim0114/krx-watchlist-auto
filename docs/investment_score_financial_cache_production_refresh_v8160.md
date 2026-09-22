# V8.16.0 controlled production financial cache refresh

- Promotes the exact V8.15.9 staged financial cache candidate into production.
- Production financial cache rows: 271 -> 299.
- Existing 271 production rows remain field-for-field unchanged; 28 rows are added.
- Target financial blockers: 221 -> 8 (-213).
- Total scorer blockers: 688 -> 475 (-213).
- READY/LIMITED remains 21/99; lost READY is 0.
- 27 target score rows change exactly as staged; 014825 remains NO_CORP_CODE.
- Post-apply scorer output exactly matches the staged scorer output.
- Rollback restores the prior cache and run log if post-apply validation fails.
- API, policy, raw-score cache and other source caches remain unchanged.

Next: POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8161
