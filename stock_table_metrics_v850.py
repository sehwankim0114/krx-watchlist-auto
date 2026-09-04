"""V8.5.0 stage-one indicators; pure functions, no live quotes or I/O.

This is NOT a standalone swing-analysis product or an investment-score model.
Periods and heuristic thresholds are versioned in CONTRACT. ATR uses Wilder's
TR smoothing; reference: https://ta-lib.github.io/ta-doc/indicator/ATR.htm .
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from math import isfinite
from statistics import mean


VERSION = "2026-09-04-v8.5.0-two-table-indicators-preview"
CONTRACT = {
    "version": VERSION,
    "release_stage": "PREVIEW_ONLY",
    "standalone_swing_table_enabled": False,
    "price_basis": "CONFIRMED_OFFICIAL_DAILY_CLOSE",
    "mean_run_changes": 60,
    "mean_run_flat_policy": "EXTEND_PREVIOUS_DIRECTION",
    "mean_run_includes_open_and_left_censored_runs": True,
    "current_streak_flat_policy": "STOP",
    "ma_periods": [5, 20, 60, 120],
    "ma_slope_sessions": 5,
    "ma_flat_band_pct": 0.1,
    "return_period": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
    "relative_strength_unit": "PERCENTAGE_POINTS_VS_KRX_KOSPI",
    "atr": "WILDER_14_LAST_126_BARS",
    "average_daily_range": "MEAN_20_(HIGH-LOW)/CLOSE; NOT_PLUS_MINUS",
    "swing_method": "RULE_BASED_3M_EXTREMA_MA20_AND_5D_MOMENTUM_V1",
    "swing_is_fitted_parabola_or_forecast": False,
    "decliners_24": "2<=mean_run<4 AND 2<=decline_days<=4 AND bottom_rebound AND NOT new_20d_low",
    "mean_run_filter_uses_unrounded_value": True,
    "investment_score_100": "PENDING_VALIDATED_SCORING_CONTRACT",
}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return n if isfinite(n) else None


def pct(end, start):
    return 100 * (end / start - 1) if start and start > 0 else None


def rounded(value, digits=4):
    return round(value, digits) if value is not None else None


def shift_months(day: str, count: int) -> str:
    d = date.fromisoformat(day)
    m = d.year * 12 + d.month - 1 - count
    year, month0 = divmod(m, 12)
    month = month0 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1])).isoformat()


def normalize_bars(rows, basis):
    """Reject conflicting duplicates and invalid closes; never fabricate bars."""
    date.fromisoformat(basis)
    by_date = {}
    for r in rows:
        day = str(r["date"])
        date.fromisoformat(day)
        if day > basis:
            continue
        close = number(r.get("close"))
        if close is None or close <= 0:
            raise ValueError("INVALID_CLOSE:" + day)
        bar = {"date": day, "close": close}
        for field in ("high", "low", "volume", "trading_value"):
            bar[field] = number(r.get(field))
        h, l = bar["high"], bar["low"]
        if h is None or l is None or l <= 0 or not l <= close <= h:
            bar["high"] = bar["low"] = None
        if day in by_date and by_date[day] != bar:
            raise ValueError("CONFLICTING_DAILY_BAR:" + day)
        by_date[day] = bar
    return [by_date[k] for k in sorted(by_date)]


def direction_runs(closes, lookback=60):
    closes = closes[-(lookback + 1):]
    runs, sign, size = [], 0, 0
    for a, b in zip(closes, closes[1:]):
        new = (b > a) - (b < a)
        if new == 0:
            if sign:
                size += 1
        elif sign == new:
            size += 1
        else:
            if sign:
                runs.append((sign, size))
            sign, size = new, 1
    if sign:
        runs.append((sign, size))
    avg = lambda xs: mean(xs) if xs else None
    return {
        "average": avg([n for _, n in runs]),
        "up_average": avg([n for s, n in runs if s > 0]),
        "down_average": avg([n for s, n in runs if s < 0]),
        "run_count": len(runs),
        "observed_changes": max(0, len(closes) - 1),
    }


def current_streak(closes):
    if len(closes) < 2:
        return {"direction": None, "days": None, "change_pct": None}
    sign = (closes[-1] > closes[-2]) - (closes[-1] < closes[-2])
    days = 0
    if sign:
        for i in range(len(closes) - 1, 0, -1):
            if (closes[i] > closes[i - 1]) - (closes[i] < closes[i - 1]) != sign:
                break
            days += 1
    return {"direction": sign, "days": days,
            "change_pct": rounded(pct(closes[-1], closes[-days - 1])) if days else 0.0}


def ma_info(closes, period):
    value = mean(closes[-period:]) if len(closes) >= period else None
    previous = mean(closes[-period-5:-5]) if len(closes) >= period + 5 else None
    slope = pct(value, previous) if value is not None else None
    direction = None if slope is None else (1 if slope > .1 else -1 if slope < -.1 else 0)
    return {"value": rounded(value), "slope_5d_pct": rounded(slope), "direction": direction}


def atr_wilder(bars, period=14):
    bars = bars[-126:]
    if len(bars) < period + 1:
        return None
    tr = []
    for previous, bar in zip(bars, bars[1:]):
        if bar["high"] is None or bar["low"] is None:
            return None
        tr.append(max(bar["high"]-bar["low"], abs(bar["high"]-previous["close"]),
                      abs(bar["low"]-previous["close"])))
    value = mean(tr[:period])
    for v in tr[period:]:
        value = ((period-1) * value + v) / period
    return value


def period_return(bars, basis, months, sessions):
    cutoff = shift_months(basis, months)
    eligible = [s for s in sessions if cutoff <= s <= basis]
    if not eligible or sessions[0] > cutoff:
        return {"pct": None, "start_date": None, "status": "CALENDAR_HISTORY_SHORT"}
    start = eligible[0]
    prices = {b["date"]: b["close"] for b in bars}
    if start not in prices or basis not in prices:
        return {"pct": None, "start_date": start, "status": "HISTORY_SHORT_OR_DATE_MISSING"}
    return {"pct": rounded(pct(prices[basis], prices[start])), "start_date": start, "status": "OK"}


def swing_phase(bars, ma20, streak, basis):
    """Conservative descriptive heuristic, not a profitability prediction."""
    window = [b for b in bars if b["date"] >= shift_months(basis, 3)]
    if len(window) < 20:
        return {"phase": "INSUFFICIENT", "bottom_rebound": False, "new_20d_low": None}
    c = [b["close"] for b in window]
    low, high = min(c), max(c)
    lo_i = max(i for i, x in enumerate(c) if x == low)
    hi_i = max(i for i, x in enumerate(c) if x == high)
    momentum = pct(c[-1], c[-6])
    new_low = c[-1] <= min(c[-20:-1])
    rebound = pct(c[-1], low)
    falling_from_top = pct(c[-1], high)
    if new_low and low != high:
        phase = "NEW_LOW"
    elif lo_i > hi_i and rebound >= 2 and momentum > 0 and ma20["direction"] == 1:
        phase = "BOTTOM_REBOUND"
    elif ma20["direction"] == 1 and c[-1] >= ma20["value"] and rebound >= 2:
        phase = "UPTREND_PULLBACK" if streak["direction"] == -1 else "UPTREND"
    elif hi_i > lo_i and falling_from_top <= -2 and (momentum < 0 or ma20["direction"] == -1):
        phase = "TOP_DECLINE"
    elif lo_i > hi_i and rebound > 0 and momentum > 0:
        phase = "EARLY_REBOUND_UNCONFIRMED"
    else:
        phase = "SIDEWAYS_OR_UNCONFIRMED"
    # The strict 2.4 filter accepts only a confirmed low-after-high rebound.
    # A general uptrend/pullback is not silently promoted to this category.
    return {"phase": phase, "bottom_rebound": phase == "BOTTOM_REBOUND",
            "new_20d_low": new_low, "trough_date": window[lo_i]["date"],
            "peak_date": window[hi_i]["date"], "from_trough_pct": rounded(rebound),
            "from_peak_pct": rounded(falling_from_top), "momentum_5d_pct": rounded(momentum)}


def matches_decliners24(metrics):
    run = metrics["run"]["average"]
    st, swing = metrics["streak"], metrics["swing"]
    return bool(run is not None and 2 <= run < 4 and st["direction"] == -1
        and st["days"] is not None and 2 <= st["days"] <= 4
        and swing.get("phase") == "BOTTOM_REBOUND" and swing.get("bottom_rebound")
        and swing.get("new_20d_low") is False)


def indicators(rows, basis, sessions, benchmark_rows):
    bars = normalize_bars(rows, basis)
    result = {"basis_date": basis, "observation_count": len(bars), "missing": {}}
    if not bars or bars[-1]["date"] != basis:
        return {**result, "status": "LATEST_OFFICIAL_BAR_MISSING"}
    sessions = sorted({d for d in sessions if d <= basis})
    if not sessions or sessions[-1] != basis:
        return {**result, "status": "BENCHMARK_CALENDAR_NOT_CURRENT"}
    expected = {d for d in sessions if bars[0]["date"] <= d <= basis}
    observed = {b["date"] for b in bars}
    if observed - set(sessions):
        return {**result, "status": "NON_MARKET_SESSION_BAR"}
    if expected - observed:
        return {**result, "status": "HISTORY_SESSION_GAPS", "missing_sessions": sorted(expected-observed)}
    closes = [b["close"] for b in bars]
    result["status"] = "OK"
    result["official_close"] = closes[-1]
    result["run"] = direction_runs(closes)
    if len(closes) < 61:
        result["run"]["average"] = result["run"]["up_average"] = result["run"]["down_average"] = None
        result["missing"]["run"] = "NEED_61_CLOSES"
    result["streak"] = current_streak(closes)
    result["ma"] = {str(p): ma_info(closes, p) for p in (5, 20, 60, 120)}
    for period, info in result["ma"].items():
        if info["direction"] is None:
            result["missing"]["ma"+period] = "NEED_"+str(int(period)+5)+"_CLOSES"
    bench = normalize_bars(benchmark_rows, basis)
    result["returns"], result["rs_kospi_pp"] = {}, {}
    for m in (1, 3):
        stock_r = period_return(bars, basis, m, sessions)
        index_r = period_return(bench, basis, m, sessions)
        result["returns"][str(m)] = stock_r
        result["rs_kospi_pp"][str(m)] = (rounded(stock_r["pct"]-index_r["pct"])
                                                if stock_r["pct"] is not None and index_r["pct"] is not None else None)
        if stock_r["pct"] is None:
            result["missing"]["return_"+str(m)+"m"] = stock_r["status"]
    atr = atr_wilder(bars)
    result["atr14"] = {"krw": rounded(atr), "pct": rounded(100*atr/closes[-1]) if atr is not None else None}
    if atr is None:
        result["missing"]["atr14"] = "OHLC_MISSING_OR_NEED_15_BARS"
    last20 = bars[-20:]
    result["avg_daily_range_20_pct"] = (rounded(mean(100*(b["high"]-b["low"])/b["close"] for b in last20))
        if len(last20) == 20 and all(b["high"] is not None and b["low"] is not None for b in last20) else None)
    window = [b for b in bars if b["date"] >= shift_months(basis, 3)]
    complete = all(b["high"] is not None and b["low"] is not None for b in window)
    complete = complete and result["returns"]["3"]["pct"] is not None
    low = min(b["low"] for b in window) if complete else None
    high = max(b["high"] for b in window) if complete else None
    result["range_3m"] = {"low": low, "high": high,
        "position_pct": rounded(100*(closes[-1]-low)/(high-low)) if low is not None and high > low else None}
    result["swing"] = swing_phase(bars, result["ma"]["20"], result["streak"], basis)
    if result["returns"]["3"]["pct"] is None:
        result["swing"].update(phase="INSUFFICIENT", bottom_rebound=False)
    volumes = [b["volume"] for b in last20]
    values = [b["trading_value"] for b in last20]
    result["activity"] = {
        "volume_vs_20d": rounded(volumes[-1]/mean(volumes)) if len(volumes)==20 and all(v is not None and v>=0 for v in volumes) and mean(volumes)>0 else None,
        "avg20_trading_value_krw": rounded(mean(values), 0) if len(values)==20 and all(v is not None and v>=0 for v in values) else None,
    }
    # Explicitly unfilled inputs cannot masquerade as real earnings/sector data.
    result["rs_sector_pp"] = {"1": None, "3": None}
    result["earnings_outlook_change"] = None
    result["investment_score_100"] = None
    result["missing"].update(rs_sector="OFFICIAL_SECTOR_BENCHMARK_NOT_CONNECTED",
        earnings_outlook_change="CONSENSUS_REVISION_SOURCE_NOT_CONNECTED",
        investment_score_100="SCORING_CONTRACT_PENDING")
    result["trailing_reference"] = {"ma20_close_level": result["ma"]["20"]["value"],
        "below_ma20_at_official_close": closes[-1] < result["ma"]["20"]["value"] if result["ma"]["20"]["value"] else None,
        "confirmed_swing_low_stop": None, "status": "REFERENCE_ONLY_NOT_ORDER"}
    result["matches_decliners_24"] = matches_decliners24(result)
    return result
