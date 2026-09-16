# V8.11.6 staged source-contract candidate

- Version: `2026-09-16-v8.11.6-freeze-v8115-stage-production-candidate`
- Frozen V8.11.5 result commit: `c6758c8f9a269d2907ee17fb1726fb3de37362dc`
- Production `investment_score_source_enricher_v854.py` is unchanged.
- Candidate is generated as a separate staged file.
- Scope is exactly five audited tickers.
- Exact selector: `CIS` / `ifrs-full_RevenueFromInterest`.
- Duplicate exact rows fail closed.
- No exact hit falls back to unchanged V8.5.4 revenue selection.
- Non-audited tickers always use unchanged V8.5.4 logic.

## Frozen V8.11.5 proof

- Source RAW ready: 222 → 226 (+4).
- Scorer READY: 5 → 8 (+3).
- Blockers: 2178 → 2166 (-12).
- Non-target source/score drift: 0.
