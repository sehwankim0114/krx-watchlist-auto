# V8.10.7 V8.10.6 source extension combined dry-run

- Version: `2026-09-16-v8.10.9-freeze-v8106-source-against-frozen-v8102-validation-fix`
- Exact baseline: `2026-09-15-v8.10.2-combined-validated-source-reconciliation`
- The V8.10.2 combined score CSV is reproduced row-for-row from its immutable commit snapshot before any new overlay.
- Only 001530 and 066575 receive V8.10.6 validated source fields.
- 066575 keeps its existing raw inheritance from 066570; only the missing official revenue YoY financial field is shadow-patched.
- No READY increase is assumed; actual blocker reduction is measured from the scorer output.
- Current production may contain more tickers; the comparison is intentionally pinned to the immutable 112-ticker V8.10.2 lineage.
