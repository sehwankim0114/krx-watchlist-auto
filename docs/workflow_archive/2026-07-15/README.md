# Archived GitHub Actions workflows

Archive date: 2026-07-15 KST

Only workflows whose top-level trigger was exactly
`workflow_dispatch` were moved out of `.github/workflows`.
Scheduled and operational workflows remain active.

## Active operational workflows retained

- `build_api_json.yml`
- `collect-krx-watchlist.yml`
- `dart-fx-exposure-safe.yml`
- `maintenance-repair.yml`
- `safe-repository-cleanup.yml`
- `v6-apply-us-sp500-production.yml`
- `v731-daily-integrated-health.yml`
- `v77-runtime-freshness-gate.yml`

## Archived manual workflows

- `apply-custom-gpt-v5-hardening.yml`
- `apply-request-time-price-v51.yml`
- `dart-fx-exposure.yml`
- `fix-rules-version-contract.yml`
- `v6-apply-explanation-manual-policy.yml`
- `v6-apply-explanation-policy-and-quote-keys.yml`
- `v6-apply-holdings-private-runtime.yml`
- `v6-apply-lightweight-kospi-kosdaq-watchlists-v66.yml`
- `v6-apply-one-month-production-routes.yml`
- `v6-apply-one-month-routes-no-workflow-write.yml`
- `v6-apply-one-month-universe-metrics-patch.yml`
- `v6-apply-output-order-and-price-retry-v65.yml`
- `v6-apply-quote-key-aliases-v64.yml`
- `v6-financial-valuation-enricher-test.yml`
- `v6-holdings-generator-test.yml`
- `v6-kosdaq-one-month-generator-test.yml`
- `v6-kospi-one-month-generator-test.yml`
- `v6-legacy-market-score-alias-test.yml`
- `v6-market-metric-standards-test.yml`
- `v6-request-time-explanation-refresh-test.yml`
- `v6-supply-burden-status-separation-test.yml`
- `v6-thirteen-table-route-registry-test.yml`
- `v6-us-sp500-live-collector-test.yml`
- `v6-us-sp500-watchlist-generator-test.yml`
- `v7-apply-final-display-contract-v71.yml`
- `v72-apply-korean-sector-theme.yml`
- `v75-restore-activity-elasticity.yml`
- `v76-link-financial-valuation.yml`
- `v761-compact-financial-payload.yml`
- `v762-complete-financial-link-after-manual-workflow-update.yml`
- `v78-price-range-position-upgrade.yml`
- `v79-recommendation-icon-integrity.yml`
- `v80-request-time-position-alignment.yml`
- `v81-archive-obsolete-workflows.yml`
- `v811-inspect-workflow-triggers.yml`
- `v812-archive-manual-workflows.yml`

Source Python patch and validation files remain in the
repository for auditability. They do not run automatically.
