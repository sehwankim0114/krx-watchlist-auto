# V8.5.1: scheduled, inactive two-table data

This release connects the tested V8.5.0 computations to the end of
`build_api_json.py`, after all existing normalization and freshness steps.
It adds an independently validated bundle in `api/two_table_v1/`.
It does not change an existing table, the legacy decliners generator, Worker,
Action schema, GPT instructions, rules version, or a workflow file.

## Data and safety

- KOSPI retains the existing 30 selected stocks and their order.
- General decliners and the separate strict 2.4 filter retain all matches.
- Canonical JSON retains complete metrics and missing reasons. Compact JSON
  uses up to 30 rows per page, checked against 30,000 UTF-8 bytes **after**
  adding source/build/rollout metadata. The canonical files are not Action
  responses and must not be served directly as one oversized GPT response.
- Each file has matching source build ID, rule version/hash and basis date;
  the shadow manifest has file sizes and SHA-256 digests. The validator checks
  pages, full row coverage, exact tickers, KOSPI order and compact values.
- The normal API validator now also checks this separate dataset. It does not
  claim that legacy Action or Worker tests cover a new route.
- `production_activation_allowed=false`, `custom_gpt_route_enabled=false`,
  `safe_to_analyze_as_latest=false` are unconditional at this release stage.
  Source freshness at generation is a snapshot, not a current-time guarantee.
  Later consumers must recheck current main API status, build and rules.
- Unsynchronized upstream data emits a blocked manifest with no table files.
  A structurally consistent but old source emits `SHADOW_STALE`, never latest.
  Other unexpected builder/validation errors fail the job before a push.
- No live quote, network collection or personal portfolio data is introduced.
  Missing 100-point score, sector RS, consensus revision and confirmed swing
  stop remain missing. Existing legacy scores are not scores out of 100.
- Standalone swing analysis remains deferred. Swing direction inside these
  two tables remains included.

## Generated-file lifecycle

The existing `Build API JSON` workflow already commits `api` recursively, so
no workflow permission change is needed. The generator owns only the fixed
`api/two_table_v1/` directory and refuses symlinks, unknown names or another
owner/version. It replaces generated JSON and removes only obsolete owned
pages when the number of matches decreases. Git history retains old data.
The manifest is written last. CI validates before committing the bundle in a
single Git commit; a local partially written bundle cannot pass validation.

The old `api/kospi_consecutive_decliners.json` and its manual workflow remain
untouched and do not serve the new data. The new Worker release must read the
new, synchronized path explicitly; legacy decliners are not a fallback.

## Checks and remaining deployment

Run the V8.5.0 unit tests, `test_two_table_shadow_v851.py`, the normal API
validator, and the existing Worker regression. `--check-only` is read-only:

    python build_two_table_shadow_v851.py --repo . --check-only

The installer commits only reviewed Python/docs and the generated shadow
bundle. It aborts if main advances during its tests; rerun on current main,
never rebase an old data snapshot onto new inputs or force-push it.
Its one-time workflow is manually uploaded because the GitHub App lacks
workflow-write permission. While temporary workflows remain, do not run the
old safety audit expecting exactly nine permanent workflows.

Next: finalize the remaining sourced display fields and score contract,
connect Worker routes and payloads, update corresponding Action/GPT
contracts, then test actual new-format output and update the safety audit.
Do not replace GPT instructions or deploy Worker for this stage alone.
