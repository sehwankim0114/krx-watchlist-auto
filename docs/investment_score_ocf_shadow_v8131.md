# V8.13.1 recoverable OCF freeze and shadow score

- Four exact annual OCF values audited in V8.13.0 are frozen as source-only candidates.
- Production OCF cache is not modified.
- Each target must be baseline LIMITED only by MISSING_OCF_MARGIN_INPUT.
- Each target must become READY under the shadow OCF cache.
- Non-target scorer row drift must be zero.

- Baseline READY/LIMITED: 19/130
- Shadow READY/LIMITED: 23/126
- Baseline/shadow blockers: 796/792
- READY delta: 4
- Blocker reduction: 4

Next: `STAGE_CURRENT_UNIVERSE_OCF_REFRESH_V8132`
