# V8.5.2: guarded two-table Worker transport

Worker build: `1.4.0-two-table-guarded-preview`.
Existing 30 Actions, 13 command routes, quote handling and ten legacy compact
table paths remain unchanged. No GPT schema/instructions or dataset activation
flags change in this stage. A standalone swing table remains deferred.

## New routes and interpretation

- `/tables/v1/kospi?mode=preview&page=1`
- `/tables/v1/decliners?mode=preview&page=1`
- `/tables/v1/decliners24?mode=preview&page=1`

Only explicit `mode=preview` reads the inactive scheduled dataset. Omitted mode
means production, which fails with `TWO_TABLE_NOT_ACTIVATED` while the source
flags remain false. This is intentional. Do not use preview pages as the new
production GPT table or install an Action schema pointing to them yet.

Source compact pages are passed through unchanged, with a separate `transport`
object. No indicator, score, price or recommendation is recalculated. Current
prices still require the existing quote Action later. Source fields marked
missing remain missing; the legacy score is not relabelled as out of 100.

The worker returns at most 30 rows and 30,000 UTF-8 bytes including added
metadata. Complete candidate lists require every page. The response supplies
`transport.next_page_url`; pages after the first require the same `build_id`.
If the build changes between pages, restart at page one, never join builds.
Canonical large JSON and unguarded nested raw paths remain blocked.

## Controls

Each request reads current status, the shadow manifest and repository holiday
calendar without using Worker Cache API. It verifies build/rules/date identity,
the three freshness gates, and the existing repository 08:30 KST publication
rule. Stored fresh booleans alone cannot make an old basis date current.
Missing or out-of-year calendar coverage fails closed; holidays are not guessed.
The calculation follows the configured repository calendar, not an independently
verified announcement feed.

The requested page must match its exact manifest byte count and SHA-256. Page
number/count, total rows, column mapping and unique six-digit tickers are checked.
Status, manifest and calendar are fetched again before returning. Mid-request
changes cause a retry error, without old rows or static-price substitution.

Bodies are bounded while streaming, and timeouts include body reads. The only
fallback is the already configured public GitHub Contents endpoint for a raw
fetch failure or retryable HTTP response. Invalid JSON, wrong hashes or row
contracts are not repaired. Error responses contain no upstream body or input
query values. Both success and failure use `Cache-Control: no-store`.

## Deployment and health transition

1. Apply the reviewed non-workflow source package in GitHub.
2. Manually deploy the exact updated `worker/krx-live-price-worker.js` to the
   existing Cloudflare service; do not create a new Worker or change its domain.
3. Check live health and all preview pages, including default-mode rejection.
4. Replace the matching read-only safety audit workflow and remove the completed
   one-time installer. Nine permanent workflows should remain.
5. Complete production display/data contracts, then update the corresponding
   Worker/Action/GPT release and run actual new-format output tests.

During the short source/deployment transition the daily health checker accepts
the exact old V1.3.9 build only if the entire V8.5.1 dataset is explicitly
inactive. It reports `LEGACY_ALLOWED_SHADOW_ONLY`, not new-route validation.
Any production activation removes that allowance. The V1.4.0 build must
advertise the new guarded transport contract. Full output testing remains a
separate check. The old V8.4.1 safety workflow must not be run against V1.4.0
sources; its replacement is required before the next full audit.

Local checks: the existing Worker regression, the new transport regression,
the V8.5.0/V8.5.1 Python tests, and rollout-health tests. Live Cloudflare and
actual GPT output must be checked separately after manual deployment.
