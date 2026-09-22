# V8.16.4 source-cache refresh and gate-repair stage

- Exact V8.16.3 281-row source-cache candidate is staged.
- Production source cache remains 254 rows in this step.
- Scorer blockers reproduce 475 -> 322 (-153).
- READY / LIMITED remains 21 / 99.
- 28 selected score rows change; no other score row changes.
- No READY ticker is lost.
- Git last-modifying commit ancestry reproduces NEED_REFRESH=true.
- Production V8.5.4 workflow is not modified in this stage.

Next: CONTROLLED_SOURCE_CACHE_APPLY_AND_GATE_REPAIR_V8165
