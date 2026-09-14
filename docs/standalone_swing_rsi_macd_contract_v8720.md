# V8.7.20 Standalone Swing RSI / MACD Contract

## Status
Source-only / preproduction. Standalone table, command, route and final header remain disabled.

## RSI
Approved contract: Wilder RSI(14).

- Input: confirmed daily close only
- Period: 14
- Initial average gain/loss: simple average of first 14 changes
- Subsequent smoothing: Wilder recursion, alpha = 1/14
- RSI = 100 - 100 / (1 + RS)
- >=70: overbought reference
- <=30: oversold reference

## MACD
Approved contract: standard period-EMA MACD 12/26/9.

- Input: confirmed daily close only
- Fast EMA: 12
- Slow EMA: 26
- Signal EMA: 9
- EMA alpha = 2/(period+1)
- EMA seed = SMA of first period values
- MACD line = EMA12 - EMA26
- Signal = EMA9(MACD line)
- Histogram = MACD line - Signal

The fixed 0.15 / 0.075 fast/slow factors belong to the separate MACDFIX-style variant and are not selected for this project's ordinary MACD field.

## V8.7.19 evidence
- Run: 34790950755
- Job: 103814938056
- Artifact: 10328676199
- Artifact SHA256: 7bcaf1c9bf5d8d2626b8cda02838032d316aa75714ab2ae71b06556c8d49c432
- RSI candidate zone mismatch: 31 / 235
- MACD line-sign mismatch: 1 / 235
- MACD histogram-sign mismatch: 1 / 235
- MACD crossover-state mismatch: 1 / 235

## Safety
RSI and MACD are confirmed-daily-bar metrics. Request-time current price never recomputes them. This release does not enable the standalone table, create a route, add a user command, change production two-table outputs, modify the Worker, or select a final table header.
