# V8.16.5 controlled production source-cache apply

- Production source cache is promoted from 254 to 281 rows.
- Exact V8.16.4 staged candidate bytes are applied.
- Scorer blockers are reduced from 475 to 322.
- READY / LIMITED remains 21 / 99.
- No READY ticker is lost and no non-selected score row changes.
- The existing V8.5.4 workflow file remains unchanged.
- Gate compatibility is repaired by restoring the audited RUN_AT_KST contract to the V8.16.0 financial log and the promoted source log.
- The current scheduled gate now resolves to NEED_REFRESH=false because the promoted source run is newer than the financial run.
- Manual workflow_dispatch forced refresh behavior remains unchanged.

Next: POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8166
