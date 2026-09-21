# V8.12.7 controlled production price-elasticity refresh

- Promoted the V8.12.6 validated candidate into the production price-elasticity cache.
- Production source rows: 112 -> 149.
- Basis date: 2026-09-11 -> 2026-09-18.
- Scorer READY: 7 -> 19.
- Blocker occurrences: 911 -> 796.
- READY regression: 0.
- Previously READY score/band drift: 0.
- Post-apply scorer output exactly matches the staged candidate scorer output.
- API, scoring policy, source cache, financial cache, OCF cache, and production score artifacts were not modified.

Next: POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8128
