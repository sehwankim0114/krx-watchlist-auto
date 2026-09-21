# V8.13.9 controlled production supply source integration

The verified eight-ticker V8.13.8B supply source is promoted to
`latest/investment_score_supply_source_latest.csv`.

The two-table builder now gives this verified source precedence
over legacy whole-market supply scan values for matching tickers.

This step does not rebuild or modify the current production API.
The read-only preview validates only the persistent supply overlay path.
The 100-point regression starts from the real production 149-row API
and overlays only the eight verified supply fields; it must reproduce
READY 27 / LIMITED 122 and 724 blocker occurrences.

Next: `REBUILD_TWO_TABLE_WITH_PRODUCTION_SUPPLY_SOURCE_V8140`
