# V8.17.4 staged financial cache candidate

- Production financial cache remains unchanged at 240 rows.
- Adds the exact 68-row V8.17.3A source candidate to form a 308-row staged cache.
- Scorer universe remains 157.
- READY/LIMITED remains 14/143.
- Total blockers reproduce exactly: 1388 -> 906 (-482).
- Target financial blockers reproduce exactly: 536 -> 54 (-482).
- 61 targets fully resolve financial blockers; 7 remain partial.
- Non-target score drift: 0; newly READY: 0; lost READY: 0.
- V8.17.3A's v8172_result_commit field contains a provenance-only metadata typo; the actual V8.17.2 commit is recorded here and lineage is verified by git ancestry.
- No production cache/API/score/policy file is modified.

Next: CONTROLLED_PRODUCTION_FINANCIAL_CACHE_REFRESH_V8175
