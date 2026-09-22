# V8.14.0B scheduled production supply apply adoption

- The eight verified supply-source rows were already applied by the scheduled synchronized API rebuild.
- Current production scorer is READY 27 / LIMITED 122 with 724 blocker occurrences.
- This workflow does not rebuild or mutate `api/two_table_v1`; it validates and records the already-applied production state.
- Runtime official freshness is separately stale by one trading day (basis 2026-09-18 vs expected 2026-09-21).
- The stale runtime state does not invalidate the supply-source integration proof, but the table must not be described as latest official until freshness recovers.

Next: `POST_SUPPLY_APPLY_CURRENT_BLOCKER_REAUDIT_V8141`
