# V8.13.3 controlled production OCF refresh

- Promotes only the V8.13.2B candidate after re-running scorer regression.
- Production OCF cache is replaced only after candidate guards pass.
- Production score outputs, API files, scoring policy, financial cache, and raw source cache are not modified.
- CR홀딩스(000480) and 한국수출포장(002200) remain unresolved rather than being force-mapped.

- Production OCF rows: 112 -> 149
- OCF READY/LIMITED: 147/2
- Scorer READY: 19 -> 23
- Blockers: 796 -> 732

Next: `POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8134`
