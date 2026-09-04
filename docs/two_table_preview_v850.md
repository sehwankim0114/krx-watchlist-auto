# V8.5.0 stage one: KOSPI and consecutive-decliners preview

This is a read-only engineering preview, not a production API or investment
recommendation. The standalone swing-analysis table is explicitly deferred;
the two selected tables still include their swing-direction fields.

## Inputs and outputs

Reads only `api/status.json`, `api/kospi_watchlist.json`,
`latest/universe_raw_history_latest.csv`,
`latest/kospi_universe_summary_latest.csv`, and
`latest/official_index_history_latest.csv`. It does not query live prices,
collect external data, write into the repository, commit or push.

Run `python build_stock_table_preview_v850.py --repo REPOSITORY --output-dir NEW_EXTERNAL_DIRECTORY`.
The output includes canonical JSON, compact development pages, and reports.
General decliners use the previous default of at least three consecutive
declines. The separate 2.4 filter uses two through four declines and the
additional explicitly versioned mean-run and bottom-rebound conditions.
All matches are retained. Compact preview pages contain at most 30 rows and
must remain below 30,000 UTF-8 bytes; pages are not yet live Action routes.

## Calculation definitions

- Returns use calendar months. The start is the first official market session
  on or after the month-shifted date. Stock and KOSPI use the same dates.
- Relative strength is stock return minus official KOSPI return, in percentage
  points. An industry-relative number is not inferred from KOSPI or a theme.
- Mean direction runs use 60 close-to-close changes. Flats extend the previous
  nonzero direction. The left-censored and current unfinished runs are included
  for compatibility with the existing generator. Current streaks stop at flat.
- SMA direction compares the current mean with the mean five sessions earlier;
  changes within plus/minus 0.1% are flat. SMA120 direction needs 125 closes.
- ATR14 seeds the first 14 true ranges with their arithmetic mean, then uses
  Wilder's recurrence `(previous*13 + current_TR)/14`, using at most the last
  126 bars. True range includes prior-close gaps. Invalid OHLC leaves ATR null.
  Reference: [TA-Lib ATR documentation](https://ta-lib.github.io/ta-doc/indicator/ATR.htm).
- Average daily range is the 20-session mean of `(high-low)/close`, not half
  that value, not a plus/minus prediction, and not an alternative name for ATR.
- Swing phase is an initial descriptive heuristic using the order of 3-month
  closing-price extrema, SMA20 direction, five-session momentum and a new
  20-session-low guard. It is not a fitted parabola, PSAR, or a price forecast.
- The strict 2.4 filter requires unrounded mean run `2 <= value < 4`, current
  decline days 2..4, confirmed `BOTTOM_REBOUND`, and no new 20-session low.
  `UPTREND_PULLBACK` alone is not automatically a confirmed bottom rebound.

These thresholds are transparent initial implementation settings, not a claim
that every numerical detail was specified in the user's earlier conversation.

## Safety and incomplete inputs

The confirmed official basis date caps all history. Identical duplicates are
deduplicated; conflicting duplicates, invalid closes, non-market dates, or
missing sessions are not silently repaired. New listings with short history
retain per-indicator missing reasons. Missing latest selected-stock bars block
the 30-stock preview. Individual invalid universe members are counted and
excluded from decliner selection with an explicit reason.

Source freshness is preserved verbatim. Even a fresh-source development result
has `production_activation_allowed=false`; a stale-source result never claims
fresh investment analysis. Main API build ID, errors and synchronization are
checked. Input hashes must remain unchanged through the run.

The 100-point investment score, consensus revisions, sector relative strength,
and a confirmed swing-low trailing stop are NOT fabricated. They remain null
with explicit reasons pending a sourced and tested contract. The legacy score
is retained separately and never relabelled as a score out of 100. SMA20 is
provided as an official-close reference, not a trade order.

## Next release stages

Validate the preview on the current repository; finish remaining sourced
fields and the 100-point scoring contract; integrate builders, rule versions,
manifest and health checks; validate Worker compact payloads; deploy Worker;
replace the exact matching GPT Action schema and instructions; test actual
`코피표`, `연속하락표` and `2.4연속하락표` output in new GPT conversations.
No standalone swing Action, instruction, or workflow is part of this release.
