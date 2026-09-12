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
    indicators,
)

SCRIPT_VERSION = "standalone_swing_source_v861.py v1.0.0-source-only"
CONTRACT_VERSION = "2026-09-11-v8.6.1-standalone-swing-source-cache"

HISTORY_CSV = Path("latest/active_stock_long_history_260d_latest.csv")
HISTORY_META = Path("latest/active_stock_long_history_260d_meta_latest.json")
INDEX_CSV = Path("latest/official_index_history_latest.csv")
KOSPI_PROD = Path("api/two_table_v1/kospi.json")

OUT_JSON = Path("latest/standalone_swing_source_latest.json")
OUT_CSV = Path("latest/standalone_swing_source_latest.csv")
OUT_META = Path("latest/standalone_swing_source_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_source_run_log_latest.txt")

PHASE_KO = {
    "BOTTOM_REBOUND": "저점반등",
    "UPTREND": "상승중",
    "UPTREND_PULLBACK": "상승중 눌림",
    "TOP_DECLINE": "고점후하락",
    "NEW_LOW": "최근 신저점",
    "EARLY_REBOUND_UNCONFIRMED": "초기반등·확인부족",
    "SIDEWAYS_OR_UNCONFIRMED": "횡보·방향미확인",
    "INSUFFICIENT": "자료부족",
}

PENDING_KEYS = [
    "rsi",
    "macd",
    "return_1w",
    "return_6m",
    "return_ytd",
    "return_52w",
    "rs_sector",
    "confirmed_swing_low_stop",
    "investment_score_100",
    "earnings_outlook_change",
]

COMPARE_KEYS = [
    "official_close",
    "run",
    "streak",
    "ma",
    "returns",
    "rs_kospi_pp",
    "atr14",
    "avg_daily_range_20_pct",
    "range_3m",
    "swing",
    "trailing_reference",
    "matches_decliners_24",
]

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

def exact_subset(metrics):
    return {key: metrics.get(key) for key in COMPARE_KEYS}

def safe_row(ticker, market, name, total_rows, metric_rows, metrics, basis):
    result = {
        "ticker": ticker,
        "name": name,
        "market": market,
        "basis_date": basis,
        "long_history_rows": total_rows,
        "metric_input_rows": metric_rows,
        "metric_status": metrics.get("status"),
        "metric_contract_version": METRIC_VERSION,
        "official_close": metrics.get("official_close"),
        "run": metrics.get("run"),
        "streak": metrics.get("streak"),
        "ma": metrics.get("ma"),
        "returns": metrics.get("returns"),
        "rs_kospi_pp": metrics.get("rs_kospi_pp"),
        "atr14": metrics.get("atr14"),
        "avg_daily_range_20_pct": metrics.get("avg_daily_range_20_pct"),
        "range_3m": metrics.get("range_3m"),
        "swing": metrics.get("swing"),
        "trailing_reference": metrics.get("trailing_reference"),
        "matches_decliners_24": metrics.get("matches_decliners_24"),
        "missing": metrics.get("missing", {}),
        "pending_metrics": {key: None for key in PENDING_KEYS},
    }
    swing = result.get("swing")
    if isinstance(swing, dict):
        swing = dict(swing)
        swing["phase_ko"] = PHASE_KO.get(swing.get("phase"), "자료부족")
        result["swing"] = swing
    return result

def flatten(row):
    def g(path, default=None):
        cur = row
        for key in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return cur if cur is not None else default

    return {
        "basis_date": row["basis_date"],
        "market": row["market"],
        "ticker": row["ticker"],
        "name": row["name"],
        "long_history_rows": row["long_history_rows"],
        "metric_input_rows": row["metric_input_rows"],
        "metric_status": row["metric_status"],
        "official_close": row.get("official_close"),
        "swing_phase": g(["swing", "phase"]),
        "swing_phase_ko": g(["swing", "phase_ko"]),
        "swing_trough_date": g(["swing", "trough_date"]),
        "swing_peak_date": g(["swing", "peak_date"]),
        "from_trough_pct": g(["swing", "from_trough_pct"]),
        "from_peak_pct": g(["swing", "from_peak_pct"]),
        "momentum_5d_pct": g(["swing", "momentum_5d_pct"]),
        "ma5_value": g(["ma", "5", "value"]),
        "ma5_direction": g(["ma", "5", "direction"]),
        "ma20_value": g(["ma", "20", "value"]),
        "ma20_direction": g(["ma", "20", "direction"]),
        "ma60_value": g(["ma", "60", "value"]),
        "ma60_direction": g(["ma", "60", "direction"]),
        "ma120_value": g(["ma", "120", "value"]),
        "ma120_direction": g(["ma", "120", "direction"]),
        "return_1m_pct": g(["returns", "1", "pct"]),
        "return_3m_pct": g(["returns", "3", "pct"]),
        "rs_kospi_1m_pp": g(["rs_kospi_pp", "1"]),
        "rs_kospi_3m_pp": g(["rs_kospi_pp", "3"]),
        "atr14_krw": g(["atr14", "krw"]),
        "atr14_pct": g(["atr14", "pct"]),
        "avg_daily_range_20_pct": row.get("avg_daily_range_20_pct"),
        "mean_run_days": g(["run", "average"]),
        "up_run_days": g(["run", "up_average"]),
        "down_run_days": g(["run", "down_average"]),
        "streak_direction": g(["streak", "direction"]),
        "streak_days": g(["streak", "days"]),
        "streak_change_pct": g(["streak", "change_pct"]),
        "ma20_reference_only": g(["trailing_reference", "ma20_close_level"]),
        "confirmed_swing_low_stop": g(["trailing_reference", "confirmed_swing_low_stop"]),
        "rsi": None,
        "macd": None,
        "return_1w": None,
        "return_6m": None,
        "return_ytd": None,
        "return_52w": None,
        "rs_sector": None,
        "investment_score_100": None,
        "earnings_outlook_change": None,
    }

def main():
    for path in (HISTORY_CSV, HISTORY_META, INDEX_CSV, KOSPI_PROD, Path("stock_table_metrics_v850.py")):
        if not path.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(path))

    meta = read_json(HISTORY_META)
    if meta.get("status") != "READY":
        raise SystemExit("LONG_HISTORY_NOT_READY")
    if meta.get("source_only") is not True:
        raise SystemExit("LONG_HISTORY_NOT_SOURCE_ONLY")
    if meta.get("request_time_price_eligible") is not False:
        raise SystemExit("LONG_HISTORY_REQUEST_TIME_PRICE_GUARD_FAILED")

    basis = str(meta.get("cache_max_date") or "")
    target = [str(x).zfill(6) for x in meta.get("target_tickers", [])]
    if len(target) != int(meta.get("target_ticker_count") or 0) or len(target) != len(set(target)):
        raise SystemExit("TARGET_TICKER_META_INVALID")

    history = read_csv(HISTORY_CSV)
    grouped = defaultdict(list)
    identity = {}
    for row in history:
        ticker = str(row.get("ticker") or "").zfill(6)
        if ticker not in set(target):
            continue
        grouped[ticker].append(row)
        identity[ticker] = {
            "market": str(row.get("market") or ""),
            "name": str(row.get("name") or ""),
        }

    if set(grouped) != set(target):
        missing = sorted(set(target) - set(grouped))
        raise SystemExit("TARGET_HISTORY_MISSING:" + ",".join(missing[:20]))

    index_rows = read_csv(INDEX_CSV)
    benchmark = [
        {"date": str(r["date"]), "close": r["official_index_close"]}
        for r in index_rows
        if str(r.get("market")) == "KOSPI" and str(r.get("date")) <= basis
    ]
    sessions = sorted({r["date"] for r in benchmark})
    if not sessions or sessions[-1] != basis:
        raise SystemExit("KOSPI_BENCHMARK_BASIS_MISMATCH")

    # The production metric contract currently uses the official-index history
    # calendar. Trim older long-history rows before calling indicators so the
    # validated V8.5.0 function receives exactly the same calendar horizon.
    metric_calendar_start = sessions[0]

    output_rows = []
    metric_ok = 0
    for ticker in sorted(target):
        rows_all = sorted(grouped[ticker], key=lambda x: str(x["date"]))
        metric_source_rows = [r for r in rows_all if metric_calendar_start <= str(r["date"]) <= basis]
        metrics = indicators(metric_source_rows, basis, sessions, benchmark)
        if metrics.get("status") == "OK":
            metric_ok += 1
        output_rows.append(
            safe_row(
                ticker=ticker,
                market=identity[ticker]["market"],
                name=identity[ticker]["name"],
                total_rows=len(rows_all),
                metric_rows=len(metric_source_rows),
                metrics=metrics,
                basis=basis,
            )
        )

    production = read_json(KOSPI_PROD)
    if production.get("basis_date") != basis:
        raise SystemExit("PRODUCTION_BASIS_MISMATCH")
    prod_rows = production.get("rows") or []
    if len(prod_rows) != 30:
        raise SystemExit("PRODUCTION_KOSPI_NOT_30")

    by_ticker = {row["ticker"]: row for row in output_rows}
    exact_matches = 0
    mismatches = []
    for prod in prod_rows:
        ticker = str(prod.get("ticker") or "").zfill(6)
        source = by_ticker.get(ticker)
        if source is None:
            mismatches.append({"ticker": ticker, "reason": "SOURCE_MISSING"})
            continue
        metrics = prod.get("metrics") or {}
        # phase_ko is V8.6.1 display metadata, not part of the production metric.
        source_swing = dict(source.get("swing") or {})
        source_swing.pop("phase_ko", None)
        source_for_compare = {
            "official_close": source.get("official_close"),
            "run": source.get("run"),
            "streak": source.get("streak"),
            "ma": source.get("ma"),
            "returns": source.get("returns"),
            "rs_kospi_pp": source.get("rs_kospi_pp"),
            "atr14": source.get("atr14"),
            "avg_daily_range_20_pct": source.get("avg_daily_range_20_pct"),
            "range_3m": source.get("range_3m"),
            "swing": source_swing,
            "trailing_reference": source.get("trailing_reference"),
            "matches_decliners_24": source.get("matches_decliners_24"),
        }
        if source_for_compare == exact_subset(metrics):
            exact_matches += 1
        else:
            mismatches.append({"ticker": ticker, "name": prod.get("name"), "reason": "METRIC_MISMATCH"})

    if exact_matches != 30 or mismatches:
        raise SystemExit("KOSPI30_REGRESSION_MISMATCH:" + json.dumps(mismatches, ensure_ascii=False))

    for row in output_rows:
        pending = row["pending_metrics"]
        if any(pending[key] is not None for key in PENDING_KEYS):
            raise SystemExit("PENDING_FIELD_POPULATED:" + row["ticker"])
        tr = row.get("trailing_reference") or {}
        if tr.get("confirmed_swing_low_stop") is not None:
            raise SystemExit("CONFIRMED_SWING_LOW_STOP_POPULATED:" + row["ticker"])

    source_sha = {
        str(path): sha256(path)
        for path in (HISTORY_CSV, HISTORY_META, INDEX_CSV, KOSPI_PROD, Path("stock_table_metrics_v850.py"))
    }

    payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "metric_calendar_start": metric_calendar_start,
        "metric_contract_version": METRIC_VERSION,
        "row_count": len(output_rows),
        "rows": output_rows,
        "pending_metrics": PENDING_KEYS,
        "source_sha256": source_sha,
        "safety": {
            "metric_formula_changed": False,
            "sector_rs_calculated": False,
            "confirmed_swing_low_stop_calculated": False,
            "investment_score_100_calculated": False,
            "earnings_outlook_change_calculated": False,
            "rsi_calculated": False,
            "macd_calculated": False,
            "request_time_price_substitution": False,
        },
    }
    write_json(OUT_JSON, payload)

    flat = [flatten(row) for row in output_rows]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat[0].keys()))
        writer.writeheader()
        writer.writerows(flat)

    phase_counts = {}
    for row in output_rows:
        phase = (row.get("swing") or {}).get("phase") or "MISSING"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    out_meta = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "history_contract_version": meta.get("contract_version"),
        "history_generated_at_kst": meta.get("generated_at_kst"),
        "history_target_ticker_count": meta.get("target_ticker_count"),
        "history_distinct_market_dates": meta.get("distinct_market_dates"),
        "history_cache_min_date": meta.get("cache_min_date"),
        "history_cache_max_date": meta.get("cache_max_date"),
        "metric_calendar_start": metric_calendar_start,
        "metric_contract_version": METRIC_VERSION,
        "output_rows": len(output_rows),
        "metric_ok_rows": metric_ok,
        "phase_counts": phase_counts,
        "kospi30_exact_matches": exact_matches,
        "kospi30_mismatches": len(mismatches),
        "pending_metrics": PENDING_KEYS,
        "source_sha256": source_sha,
        "safety": payload["safety"],
    }
    write_json(OUT_META, out_meta)

    log_lines = [
        "V861_STANDALONE_SWING_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        f"TARGET_TICKERS={len(target)}",
        f"OUTPUT_ROWS={len(output_rows)}",
        f"METRIC_OK_ROWS={metric_ok}",
        f"METRIC_CALENDAR_START={metric_calendar_start}",
        f"KOSPI30_EXACT_MATCHES={exact_matches}",
        f"KOSPI30_MISMATCHES={len(mismatches)}",
        "PENDING_RSI=true",
        "PENDING_MACD=true",
        "PENDING_1W_6M_YTD_52W=true",
        "SECTOR_RS_CALCULATED=false",
        "CONFIRMED_SWING_LOW_STOP_CALCULATED=false",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "EARNINGS_OUTLOOK_CHANGE_CALCULATED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V861_STANDALONE_SWING_SOURCE_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print("\n".join(log_lines))

if __name__ == "__main__":
    main()
