# V8.19.1A recoverable OCF freeze and shadow

- Seven exact annual OCF values audited in V8.19.0A are frozen as source-only candidates.
- Production OCF cache remains 149 rows; shadow candidate is 156 rows.
- READY / LIMITED: 15 / 183 -> 22 / 176.
- Blockers: 1625 -> 1618 (-7).
- Each target was a single OCF blocker and becomes READY in shadow.
- Existing production OCF rows changed: 0.
- Non-target score drift: 0.
- Production cache, API, score, and policy remain unchanged.

Next: STAGE_CURRENT_OCF_PATCH_V8192A
