#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from stock_table_metrics_v850 import (
    VERSION as METRIC_VERSION,
    normalize_bars,
    period_return,
)

SCRIPT_VERSION = "standalone_swing_extended_returns_v872.py v1.0.0-source-only"
CONTRACT_VERSION = "2026-09-12-v8.7.2-standalone-swing-6m-return-source"

HISTORY_CSV = Path("latest/active_stock_long_history_260d_latest.csv")
HISTORY_META = Path("latest/active_stock_long_history_260d_meta_latest.json")
INDEX_CSV = Path("latest/official_index_history_latest.csv")
KOSPI_PROD = Path("api/two_table_v1/kospi.json")
SWING_META = Path("latest/standalone_swing_source_meta_latest.json")

OUT_JSON = Path("latest/standalone_swing_extended_returns_latest.json")
OUT_CSV = Path("latest/standalone_swing_extended_returns_latest.csv")
OUT_META = Path("latest/standalone_swing_extended_returns_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_extended_returns_run_log_latest.txt")

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

def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

def main():
    required = [
        HISTORY_CSV, HISTORY_META, INDEX_CSV, KOSPI_PROD, SWING_META,
        Path("stock_table_metrics_v850.py"),
    ]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    hist_meta = read_json(HISTORY_META)
    swing_meta = read_json(SWING_META)
    prod = read_json(KOSPI_PROD)

    if hist_meta.get("status") != "READY":
        raise SystemExit("LONG_HISTORY_NOT_READY")
    if hist_meta.get("source_only") is not True:
        raise SystemExit("LONG_HISTORY_NOT_SOURCE_ONLY")
    if hist_meta.get("request_time_price_eligible") is not False:
        raise SystemExit("LONG_HISTORY_REQUEST_TIME_GUARD_FAILED")
    if swing_meta.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("SWING_SOURCE_NOT_READY")
    if swing_meta.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("SWING_TABLE_ALREADY_ENABLED_UNEXPECTEDLY")

    basis = str(hist_meta.get("cache_max_date") or "")
    if swing_meta.get("basis_date") != basis:
        raise SystemExit("SWING_SOURCE_BASIS_MISMATCH")
    if prod.get("basis_date") != basis:
        raise SystemExit("PRODUCTION_BASIS_MISMATCH")
    if prod.get("status") != "READY":
        raise SystemExit("PRODUCTION_NOT_READY")

    target = [str(x).zfill(6) for x in hist_meta.get("target_tickers", [])]
    if len(target) != int(hist_meta.get("target_ticker_count") or 0):
        raise SystemExit("TARGET_META_COUNT_MISMATCH")

    history = read_csv(HISTORY_CSV)
    target_set = set(target)
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
        missing = sorted(target_set - set(by_ticker))
        raise SystemExit("TARGET_HISTORY_MISSING:" + ",".join(missing[:20]))

    index_rows = read_csv(INDEX_CSV)
    sessions = sorted({
        str(r["date"])
        for r in index_rows
        if str(r.get("market")) == "KOSPI" and str(r.get("date")) <= basis
    })
    if not sessions or sessions[-1] != basis:
        raise SystemExit("KOSPI_SESSION_CALENDAR_NOT_CURRENT")

    # Regression gate: generic period_return(months=N) must reproduce the
    # current production 1M/3M values before it is reused for 6M.
    prod_rows = prod.get("rows") or []
    if len(prod_rows) != 30:
        raise SystemExit("PRODUCTION_KOSPI_NOT_30")

    regression_matches = 0
    regression_mismatches = []
    for row in prod_rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        bars = normalize_bars(by_ticker[ticker], basis)
        expected = (row.get("metrics") or {}).get("returns") or {}
        actual = {
            "1": period_return(bars, basis, 1, sessions),
            "3": period_return(bars, basis, 3, sessions),
        }
        if actual == {"1": expected.get("1"), "3": expected.get("3")}:
            regression_matches += 1
        else:
            regression_mismatches.append({
                "ticker": ticker,
                "name": row.get("name"),
                "expected": {"1": expected.get("1"), "3": expected.get("3")},
                "actual": actual,
            })

    if regression_matches != 30 or regression_mismatches:
        raise SystemExit(
            "PERIOD_RETURN_REGRESSION_FAILED:"
            + json.dumps(regression_mismatches, ensure_ascii=False)[:6000]
        )

    rows = []
    ready_6m = 0
    short_6m = []
    for ticker in sorted(target):
        bars = normalize_bars(by_ticker[ticker], basis)
        ret6 = period_return(bars, basis, 6, sessions)
        if ret6.get("status") == "OK":
            ready_6m += 1
        else:
            short_6m.append({
                "ticker": ticker,
                "name": identity[ticker]["name"],
                "history_rows": len(bars),
                "history_min_date": bars[0]["date"] if bars else None,
                "status": ret6.get("status"),
            })
        rows.append({
            "ticker": ticker,
            "name": identity[ticker]["name"],
            "market": identity[ticker]["market"],
            "basis_date": basis,
            "return_6m": ret6,
            "return_1w": None,
            "return_ytd": None,
            "return_52w": None,
            "pending_reason": {
                "return_1w": "FINAL_BASIS_CONTRACT_NOT_DEFINED",
                "return_ytd": "FINAL_BASIS_CONTRACT_NOT_DEFINED",
                "return_52w": "FINAL_BASIS_CONTRACT_NOT_DEFINED_52W_CALENDAR_VS_252_SESSIONS_DIFFERS",
            },
        })

    if ready_6m != len(target) - 1:
        raise SystemExit(f"UNEXPECTED_6M_READY_COUNT:{ready_6m}/{len(target)}")
    if len(short_6m) != 1 or short_6m[0]["ticker"] != "439960":
        raise SystemExit("UNEXPECTED_6M_SHORT_SET:" + json.dumps(short_6m, ensure_ascii=False))

    payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "metric_contract_version": METRIC_VERSION,
        "return_basis": {
            "6m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
            "1w": None,
            "ytd": None,
            "52w": None,
        },
        "row_count": len(rows),
        "return_6m_ready_count": ready_6m,
        "return_6m_short_count": len(short_6m),
        "return_6m_short": short_6m,
        "production_1m_3m_regression_exact_matches": regression_matches,
        "rows": rows,
        "safety": {
            "return_6m_calculated": True,
            "return_1w_calculated": False,
            "return_ytd_calculated": False,
            "return_52w_calculated": False,
            "rsi_calculated": False,
            "macd_calculated": False,
            "investment_score_100_calculated": False,
            "earnings_outlook_change_calculated": False,
            "confirmed_swing_low_stop_calculated": False,
            "metric_formula_changed": False,
            "production_table_changed": False,
            "request_time_price_substitution": False,
        },
        "source_sha256": {str(p): sha256(p) for p in required},
    }
    write_json(OUT_JSON, payload)

    flat_fields = [
        "basis_date", "market", "ticker", "name",
        "return_6m_pct", "return_6m_start_date", "return_6m_status",
        "return_1w", "return_ytd", "return_52w",
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
                "return_6m_pct": r["return_6m"].get("pct"),
                "return_6m_start_date": r["return_6m"].get("start_date"),
                "return_6m_status": r["return_6m"].get("status"),
                "return_1w": None,
                "return_ytd": None,
                "return_52w": None,
            })

    out_meta = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "target_ticker_count": len(target),
        "return_6m_ready_count": ready_6m,
        "return_6m_short_count": len(short_6m),
        "return_6m_short": short_6m,
        "production_1m_3m_regression_exact_matches": regression_matches,
        "pending_returns": ["1w", "ytd", "52w"],
        "safety": payload["safety"],
        "source_sha256": payload["source_sha256"],
    }
    write_json(OUT_META, out_meta)

    log = [
        "V872_EXTENDED_RETURN_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        f"TARGET_TICKERS={len(target)}",
        f"RETURN_6M_READY={ready_6m}",
        f"RETURN_6M_SHORT={len(short_6m)}",
        "RETURN_6M_SHORT_TICKER=439960",
        f"PRODUCTION_1M_3M_REGRESSION_EXACT_MATCHES={regression_matches}",
        "RETURN_1W_CALCULATED=false",
        "RETURN_YTD_CALCULATED=false",
        "RETURN_52W_CALCULATED=false",
        "RSI_CALCULATED=false",
        "MACD_CALCULATED=false",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "EARNINGS_OUTLOOK_CHANGE_CALCULATED=false",
        "CONFIRMED_SWING_LOW_STOP_CALCULATED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "METRIC_FORMULA_CHANGED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V872_EXTENDED_RETURN_SOURCE_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))

if __name__ == "__main__":
    main()
