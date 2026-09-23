# V8.18.0 current actionable price-elasticity audit

- Targets: 동원산업(006040), HDC(012630), GS(078930).
- Source: official KRX daily close only.
- Production basis date: 2026-09-22.
- Metric: latest 20 close-to-close absolute returns mean.
- 21 valid official closes are required per ticker.
- ATR substitution and non-official price substitution are forbidden.
- Production caches and API are not modified.

- 동원산업 (006040): valid closes 30, classification OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE, avg_daily_move_pct 0.9959.
- HDC (012630): valid closes 30, classification OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE, avg_daily_move_pct 2.5720.
- GS (078930): valid closes 30, classification OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE, avg_daily_move_pct 2.2485.

- Next: `FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8181`
