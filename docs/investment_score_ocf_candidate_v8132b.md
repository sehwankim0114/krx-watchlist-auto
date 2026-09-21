# V8.13.2 current-universe OCF refresh candidate

- Current scorer universe: 149 tickers.
- Reuse only current production OCF rows already READY.
- Add four V8.13.1 exact OCF frozen rows.
- Resolve remaining identities only through approved financial identity, exact DART stock-code/name identity, or verified preferred-common mapping.
- CR홀딩스(000480) and 한국수출포장(002200) remain LIMITED because identity is not forced.
- Accepted OCF account ID only: ifrs-full_CashFlowsFromUsedInOperatingActivities.
- Missing OCF is never imputed as zero.
- Candidate is shadow-tested; production OCF is not modified.

- Candidate OCF READY/LIMITED: 147/2
- Scorer READY baseline/candidate: 19/23
- Blockers baseline/candidate: 796/732
- OCF reasons removed: 64
- Newly READY: 4

Next: `CONTROLLED_PRODUCTION_OCF_REFRESH_V8133`
