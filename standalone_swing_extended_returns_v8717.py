#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from stock_table_metrics_v850 import (
    VERSION as METRIC_VERSION,
    normalize_bars,
    period_return,
)

SCRIPT_VERSION = "standalone_swing_extended_returns_v8717.py v1.0.0-source-only"
CONTRACT_VERSION = "2026-09-13-v8.7.17-standalone-swing-return-basis-source"

HISTORY_CSV = Path("latest/active_stock_long_history_260d_latest.csv")
HISTORY_META = Path("latest/active_stock_long_history_260d_meta_latest.json")
HISTORY_BUILDER = Path("active_stock_long_history_builder_v857.py")
INDEX_CSV = Path("latest/official_index_history_latest.csv")
KOSPI_PROD = Path("api/two_table_v1/kospi.json")
SWING_META = Path("latest/standalone_swing_source_meta_latest.json")
OLD_EXTENDED = Path("latest/standalone_swing_extended_returns_latest.json")

OUT_JSON = Path("latest/standalone_swing_extended_returns_latest.json")
OUT_CSV = Path("latest/standalone_swing_extended_returns_latest.csv")
OUT_META = Path("latest/standalone_swing_extended_returns_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_extended_returns_run_log_latest.txt")

RETURN_BASIS = {
    "1w": "CALENDAR_DAYS_7_FIRST_MARKET_SESSION_ON_OR_AFTER",
    "1m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
    "3m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
    "6m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
    "ytd": "PRIOR_YEAR_FINAL_MARKET_SESSION_CLOSE",
    "52w": "CALENDAR_WEEKS_52_FIRST_MARKET_SESSION_ON_OR_AFTER",
}

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

def exact_return(bars, basis, start_date):
    prices = {b["date"]: b["close"] for b in bars}
    if basis not in prices:
        return {
            "pct": None,
            "start_date": start_date,
            "status": "BASIS_DATE_MISSING",
        }
    if start_date not in prices:
        return {
            "pct": None,
            "start_date": start_date,
            "status": "HISTORY_SHORT_OR_DATE_MISSING",
        }
    start = prices[start_date]
    end = prices[basis]
    return {
        "pct": round(100.0 * (end / start - 1.0), 4),
        "start_date": start_date,
        "status": "OK",
    }

def main():
    required = [
        HISTORY_CSV,
        HISTORY_META,
        HISTORY_BUILDER,
        INDEX_CSV,
        KOSPI_PROD,
        SWING_META,
        OLD_EXTENDED,
        Path("stock_table_metrics_v850.py"),
    ]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    hist_meta = read_json(HISTORY_META)
    swing_meta = read_json(SWING_META)
    prod = read_json(KOSPI_PROD)
    old_extended = read_json(OLD_EXTENDED)

    if hist_meta.get("status") != "READY":
        raise SystemExit("LONG_HISTORY_NOT_READY")
    if hist_meta.get("source_only") is not True:
        raise SystemExit("LONG_HISTORY_NOT_SOURCE_ONLY")
    if hist_meta.get("request_time_price_eligible") is not False:
        raise SystemExit("LONG_HISTORY_REQUEST_TIME_GUARD_FAILED")
    if hist_meta.get("contract_version") != "2026-09-11-v8.5.7-compact-active-stock-260-session-history":
        raise SystemExit("LONG_HISTORY_CONTRACT_MISMATCH")
    if int(hist_meta.get("distinct_market_dates") or 0) != 260:
        raise SystemExit("LONG_HISTORY_NOT_260_SESSIONS")

    if swing_meta.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("SWING_SOURCE_NOT_READY")
    if swing_meta.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("SWING_TABLE_ALREADY_ENABLED_UNEXPECTEDLY")

    if old_extended.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("OLD_EXTENDED_SOURCE_NOT_READY")
    if old_extended.get("return_basis", {}).get("6m") != "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER":
        raise SystemExit("OLD_6M_CONTRACT_MISMATCH")

    builder_text = HISTORY_BUILDER.read_text(encoding="utf-8")
    for marker in (
        "data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
        "data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
        "until the cache contains 260 distinct official market sessions",
    ):
        if marker not in builder_text:
            raise SystemExit("OFFICIAL_KRX_HISTORY_PROVENANCE_MISSING:" + marker)

    basis = str(hist_meta.get("cache_max_date") or "")
    if not basis:
        raise SystemExit("BASIS_EMPTY")
    if swing_meta.get("basis_date") != basis:
        raise SystemExit("SWING_SOURCE_BASIS_MISMATCH")
    if prod.get("basis_date") != basis:
        raise SystemExit("PRODUCTION_BASIS_MISMATCH")
    if prod.get("status") != "READY":
        raise SystemExit("PRODUCTION_NOT_READY")
    if old_extended.get("basis_date") != basis:
        raise SystemExit("OLD_EXTENDED_BASIS_MISMATCH")

    target = [str(x).zfill(6) for x in hist_meta.get("target_tickers", [])]
    target_set = set(target)
    if len(target) != 235 or len(target_set) != 235:
        raise SystemExit("TARGET_UNIVERSE_NOT_235")

    history = read_csv(HISTORY_CSV)
    by_ticker = defaultdict(list)
    identity = {}
    for row in history:
        ticker = str(row.get("ticker") or "").zfill(6)
        if ticker in target_set:
            by_ticker[ticker].append(row)
            identity[ticker] = {
                "name": str(row.get("name") or ""),
                "market": str(row.get("market") or ""),
            }

    if set(by_ticker) != target_set:
        raise SystemExit(
            "TARGET_HISTORY_MISSING:"
            + ",".join(sorted(target_set - set(by_ticker))[:30])
        )

    sessions = sorted({
        str(row.get("date") or "")
        for row in history
        if str(row.get("date") or "")
    })
    if len(sessions) != 260:
        raise SystemExit(f"CACHE_SESSION_COUNT_MISMATCH:{len(sessions)}")
    if sessions[0] != str(hist_meta.get("cache_min_date") or ""):
        raise SystemExit("CACHE_MIN_DATE_META_MISMATCH")
    if sessions[-1] != basis:
        raise SystemExit("CACHE_MAX_DATE_MISMATCH")

    # Independent recent-calendar cross-check against official KOSPI/KOSDAQ index cache.
    index_rows = read_csv(INDEX_CSV)
    index_dates = {}
    for market in ("KOSPI", "KOSDAQ"):
        ds = sorted({
            str(r.get("date") or "")
            for r in index_rows
            if str(r.get("market") or "") == market
            and str(r.get("date") or "") <= basis
        })
        if not ds:
            raise SystemExit("INDEX_HISTORY_EMPTY:" + market)
        index_dates[market] = ds

    if index_dates["KOSPI"] != index_dates["KOSDAQ"]:
        raise SystemExit("INDEX_MARKET_SESSION_CALENDARS_DIFFER")
    if index_dates["KOSPI"][-1] != basis:
        raise SystemExit("INDEX_HISTORY_NOT_CURRENT_TO_BASIS")

    idx_min = index_dates["KOSPI"][0]
    overlap = [s for s in sessions if idx_min <= s <= basis]
    if overlap != index_dates["KOSPI"]:
        raise SystemExit("OFFICIAL_INDEX_OVERLAP_MISMATCH")

    normalized = {
        ticker: normalize_bars(by_ticker[ticker], basis)
        for ticker in sorted(target)
    }

    # Production 1M/3M regression remains exact.
    prod_rows = prod.get("rows") or []
    if len(prod_rows) != 30:
        raise SystemExit("PRODUCTION_KOSPI_NOT_30")
    regression_matches = 0
    regression_mismatches = []
    for row in prod_rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        expected = (row.get("metrics") or {}).get("returns") or {}
        actual = {
            "1": period_return(normalized[ticker], basis, 1, sessions),
            "3": period_return(normalized[ticker], basis, 3, sessions),
        }
        if actual == {"1": expected.get("1"), "3": expected.get("3")}:
            regression_matches += 1
        else:
            regression_mismatches.append({
                "ticker": ticker,
                "expected": {"1": expected.get("1"), "3": expected.get("3")},
                "actual": actual,
            })
    if regression_matches != 30 or regression_mismatches:
        raise SystemExit(
            "PRODUCTION_1M_3M_REGRESSION_FAILED:"
            + json.dumps(regression_mismatches, ensure_ascii=False)[:6000]
        )

    # Existing approved 6M source must be reproduced exactly for all 235.
    old_6m = {
        str(r.get("ticker") or "").zfill(6): r.get("return_6m")
        for r in (old_extended.get("rows") or [])
    }
    if set(old_6m) != target_set:
        raise SystemExit("OLD_6M_TICKER_SET_MISMATCH")

    old_6m_exact = 0
    for ticker in sorted(target):
        actual = period_return(normalized[ticker], basis, 6, sessions)
        if actual == old_6m[ticker]:
            old_6m_exact += 1
    if old_6m_exact != 235:
        raise SystemExit(f"OLD_6M_REGRESSION_FAILED:{old_6m_exact}/235")

    basis_d = date.fromisoformat(basis)

    def first_session_on_or_after(target_day: date):
        target_iso = target_day.isoformat()
        eligible = [s for s in sessions if target_iso <= s <= basis]
        return eligible[0] if eligible else None

    prior_year_sessions = [
        s for s in sessions if date.fromisoformat(s).year == basis_d.year - 1
    ]
    if not prior_year_sessions:
        raise SystemExit("PRIOR_YEAR_SESSIONS_EMPTY")

    start_1w = first_session_on_or_after(basis_d - timedelta(days=7))
    start_ytd = prior_year_sessions[-1]
    start_52w = first_session_on_or_after(basis_d - timedelta(weeks=52))
    if not all((start_1w, start_ytd, start_52w)):
        raise SystemExit("RETURN_START_DATE_RESOLUTION_FAILED")

    rows = []
    counts = {"1w": 0, "6m": 0, "ytd": 0, "52w": 0}
    missing = {"1w": [], "6m": [], "ytd": [], "52w": []}

    for ticker in sorted(target):
        bars = normalized[ticker]
        ret1w = exact_return(bars, basis, start_1w)
        ret6m = period_return(bars, basis, 6, sessions)
        retytd = exact_return(bars, basis, start_ytd)
        ret52w = exact_return(bars, basis, start_52w)

        values = {
            "1w": ret1w,
            "6m": ret6m,
            "ytd": retytd,
            "52w": ret52w,
        }
        for key, value in values.items():
            if value.get("status") == "OK":
                counts[key] += 1
            else:
                missing[key].append({
                    "ticker": ticker,
                    "name": identity[ticker]["name"],
                    "market": identity[ticker]["market"],
                    "history_rows": len(bars),
                    "history_min_date": bars[0]["date"] if bars else None,
                    "start_date": value.get("start_date"),
                    "status": value.get("status"),
                })

        rows.append({
            "ticker": ticker,
            "name": identity[ticker]["name"],
            "market": identity[ticker]["market"],
            "basis_date": basis,
            "return_1w": ret1w,
            "return_6m": ret6m,
            "return_ytd": retytd,
            "return_52w": ret52w,
            "pending_reason": {
                "return_1w": None if ret1w.get("status") == "OK" else ret1w.get("status"),
                "return_ytd": None if retytd.get("status") == "OK" else retytd.get("status"),
                "return_52w": None if ret52w.get("status") == "OK" else ret52w.get("status"),
            },
        })

    if counts != {"1w": 235, "6m": 234, "ytd": 234, "52w": 233}:
        raise SystemExit("UNEXPECTED_RETURN_READY_COUNTS:" + json.dumps(counts))

    expected_missing = {
        "1w": [],
        "6m": ["439960"],
        "ytd": ["439960"],
        "52w": ["217590", "439960"],
    }
    actual_missing = {
        key: sorted(x["ticker"] for x in items)
        for key, items in missing.items()
    }
    if actual_missing != expected_missing:
        raise SystemExit(
            "UNEXPECTED_RETURN_MISSING_SETS:"
            + json.dumps(actual_missing, ensure_ascii=False)
        )

    payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "metric_contract_version": METRIC_VERSION,
        "return_basis": RETURN_BASIS,
        "return_start_dates": {
            "1w": start_1w,
            "ytd": start_ytd,
            "52w": start_52w,
        },
        "row_count": len(rows),
        "return_ready_count": counts,
        "return_missing_count": {
            key: len(items) for key, items in missing.items()
        },
        "return_missing": missing,
        "production_1m_3m_regression_exact_matches": regression_matches,
        "previous_approved_6m_regression_exact_matches": old_6m_exact,
        "official_session_contract": {
            "source": str(HISTORY_CSV),
            "session_count": len(sessions),
            "min_date": sessions[0],
            "max_date": sessions[-1],
            "recent_index_crosscheck_min_date": idx_min,
            "recent_index_crosscheck_exact": True,
            "post_listing_start_substitution": False,
        },
        "rows": rows,
        "safety": {
            "return_1w_calculated": True,
            "return_6m_calculated": True,
            "return_ytd_calculated": True,
            "return_52w_calculated": True,
            "rsi_calculated": False,
            "macd_calculated": False,
            "investment_score_100_calculated": False,
            "earnings_outlook_change_calculated": False,
            "confirmed_swing_low_stop_calculated": False,
            "core_metric_formula_changed": False,
            "production_table_changed": False,
            "worker_changed": False,
            "request_time_price_substitution": False,
            "new_command_defined": False,
            "route_enabled": False,
        },
        "source_sha256": {str(p): sha256(p) for p in required},
    }
    write_json(OUT_JSON, payload)

    flat_fields = [
        "basis_date", "market", "ticker", "name",
        "return_1w_pct", "return_1w_start_date", "return_1w_status",
        "return_6m_pct", "return_6m_start_date", "return_6m_status",
        "return_ytd_pct", "return_ytd_start_date", "return_ytd_status",
        "return_52w_pct", "return_52w_start_date", "return_52w_status",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=flat_fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "basis_date": basis,
                "market": r["market"],
                "ticker": r["ticker"],
                "name": r["name"],
                "return_1w_pct": r["return_1w"].get("pct"),
                "return_1w_start_date": r["return_1w"].get("start_date"),
                "return_1w_status": r["return_1w"].get("status"),
                "return_6m_pct": r["return_6m"].get("pct"),
                "return_6m_start_date": r["return_6m"].get("start_date"),
                "return_6m_status": r["return_6m"].get("status"),
                "return_ytd_pct": r["return_ytd"].get("pct"),
                "return_ytd_start_date": r["return_ytd"].get("start_date"),
                "return_ytd_status": r["return_ytd"].get("status"),
                "return_52w_pct": r["return_52w"].get("pct"),
                "return_52w_start_date": r["return_52w"].get("start_date"),
                "return_52w_status": r["return_52w"].get("status"),
            })

    meta = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "target_ticker_count": len(target),
        "return_basis": RETURN_BASIS,
        "return_start_dates": payload["return_start_dates"],
        "return_ready_count": counts,
        "return_missing_count": payload["return_missing_count"],
        "return_missing": missing,
        "production_1m_3m_regression_exact_matches": regression_matches,
        "previous_approved_6m_regression_exact_matches": old_6m_exact,
        "pending_returns": [],
        "safety": payload["safety"],
        "source_sha256": payload["source_sha256"],
    }
    write_json(OUT_META, meta)

    log = [
        "V8717_EXTENDED_RETURN_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        f"TARGET_TICKERS={len(target)}",
        f"RETURN_1W_START_DATE={start_1w}",
        f"RETURN_YTD_START_DATE={start_ytd}",
        f"RETURN_52W_START_DATE={start_52w}",
        f"RETURN_1W_READY={counts['1w']}",
        f"RETURN_6M_READY={counts['6m']}",
        f"RETURN_YTD_READY={counts['ytd']}",
        f"RETURN_52W_READY={counts['52w']}",
        "RETURN_1W_MISSING=NONE",
        "RETURN_6M_MISSING=439960",
        "RETURN_YTD_MISSING=439960",
        "RETURN_52W_MISSING=217590,439960",
        f"PRODUCTION_1M_3M_REGRESSION_EXACT_MATCHES={regression_matches}",
        f"PREVIOUS_APPROVED_6M_REGRESSION_EXACT_MATCHES={old_6m_exact}",
        "RETURN_1W_CONTRACT=CALENDAR_DAYS_7_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "RETURN_YTD_CONTRACT=PRIOR_YEAR_FINAL_MARKET_SESSION_CLOSE",
        "RETURN_52W_CONTRACT=CALENDAR_WEEKS_52_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "POST_LISTING_START_SUBSTITUTION=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "NEW_COMMAND_DEFINED=false",
        "V8717_EXTENDED_RETURN_SOURCE_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))

if __name__ == "__main__":
    main()
