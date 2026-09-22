# V8.14.7A narrow production price-elasticity patch

- Added only LS (006260) and HD현대 (267250) to the production elasticity cache.
- Existing 149 elasticity rows were preserved field-for-field.
- The original full-refresh basis remains 2026-09-18.
- The two narrow-patched rows carry their own 2026-09-21 basis dates.
- Post-apply scorer output exactly equals the pre-tested V8.14.6 candidate state.
- READY: 16 -> 18.
- LIMITED: 104 -> 102.
- Blockers: 794 -> 792.
- API and scoring policy were not modified.

Next: `POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8148`
