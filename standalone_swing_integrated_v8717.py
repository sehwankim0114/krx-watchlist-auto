#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_integrated_v8717.py v1.0.0-source-only"
CONTRACT_VERSION = "2026-09-13-v8.7.17-standalone-swing-integrated-returns-source"
EXTENDED_CONTRACT = "2026-09-13-v8.7.17-standalone-swing-return-basis-source"

SWING = Path("latest/standalone_swing_source_latest.json")
EXTENDED = Path("latest/standalone_swing_extended_returns_latest.json")
SECTOR_RS = Path("latest/standalone_swing_sector_rs_latest.json")
GLOSSARY = Path("latest/stock_table_metric_glossary_latest.json")

OUT_JSON = Path("latest/standalone_swing_integrated_latest.json")
OUT_CSV = Path("latest/standalone_swing_integrated_latest.csv")
OUT_META = Path("latest/standalone_swing_integrated_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_integrated_run_log_latest.txt")

PENDING_KEYS = [
    "rsi",
    "macd",
    "investment_score_100",
    "earnings_outlook_change",
    "confirmed_swing_low_stop",
]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    for p in (SWING, EXTENDED, SECTOR_RS, GLOSSARY):
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    swing = read_json(SWING)
    extended = read_json(EXTENDED)
    sector = read_json(SECTOR_RS)
    glossary = read_json(GLOSSARY)

    for label, payload in (
        ("SWING", swing),
        ("EXTENDED", extended),
        ("SECTOR_RS", sector),
    ):
        if payload.get("status") != "READY_SOURCE_ONLY":
            raise SystemExit(f"{label}_SOURCE_NOT_READY")
        if payload.get("source_only") is not True:
            raise SystemExit(f"{label}_NOT_SOURCE_ONLY")
        if payload.get("standalone_swing_table_enabled") is not False:
            raise SystemExit(f"{label}_TABLE_ALREADY_ENABLED")

    if extended.get("contract_version") != EXTENDED_CONTRACT:
        raise SystemExit("EXTENDED_CONTRACT_MISMATCH")
    if extended.get("action_route_enabled") is not False:
        raise SystemExit("EXTENDED_ROUTE_ENABLED_UNEXPECTEDLY")
    if extended.get("request_time_price_eligible") is not False:
        raise SystemExit("EXTENDED_REQUEST_PRICE_GUARD_FAILED")

    basis = swing.get("basis_date")
    if not basis:
        raise SystemExit("BASIS_MISSING")
    if extended.get("basis_date") != basis or sector.get("basis_date") != basis:
        raise SystemExit("SOURCE_BASIS_MISMATCH")

    footer = glossary.get("compact_footer_text")
    if not footer or not footer.startswith("읽는 법:"):
        raise SystemExit("GLOSSARY_FOOTER_NOT_READY")

    swing_rows = {
        str(r["ticker"]).zfill(6): r
        for r in swing.get("rows") or []
    }
    ext_rows = {
        str(r["ticker"]).zfill(6): r
        for r in extended.get("rows") or []
    }
    sector_rows = {
        str(r["ticker"]).zfill(6): r
        for r in sector.get("rows") or []
    }

    if not swing_rows:
        raise SystemExit("SWING_ROWS_EMPTY")
    if set(swing_rows) != set(ext_rows):
        raise SystemExit("SWING_EXTENDED_TICKER_SET_MISMATCH")
    if set(swing_rows) != set(sector_rows):
        raise SystemExit("SWING_SECTOR_TICKER_SET_MISMATCH")
    if len(swing_rows) != 235:
        raise SystemExit("INTEGRATED_TARGET_NOT_235")

    integrated_rows = []
    ready = {"1w": 0, "1m": 0, "3m": 0, "6m": 0, "ytd": 0, "52w": 0}
    kospi_sector_ready = 0
    kosdaq_sector_null = 0

    for ticker in sorted(swing_rows):
        s = swing_rows[ticker]
        e = ext_rows[ticker]
        r = sector_rows[ticker]

        if s.get("name") != e.get("name") or s.get("name") != r.get("name"):
            raise SystemExit("NAME_MISMATCH:" + ticker)
        if s.get("market") != e.get("market") or s.get("market") != r.get("market"):
            raise SystemExit("MARKET_MISMATCH:" + ticker)
        if e.get("basis_date") != basis or r.get("basis_date") != basis:
            raise SystemExit("ROW_BASIS_MISMATCH:" + ticker)

        market = s.get("market")
        returns = s.get("returns") or {}
        one_m = returns.get("1") or {}
        three_m = returns.get("3") or {}
        if one_m.get("status") != "OK" or three_m.get("status") != "OK":
            raise SystemExit("CORE_RETURN_NOT_READY:" + ticker)

        perf = {
            "1w": e.get("return_1w") or {},
            "1m": one_m,
            "3m": three_m,
            "6m": e.get("return_6m") or {},
            "ytd": e.get("return_ytd") or {},
            "52w": e.get("return_52w") or {},
        }
        for key, value in perf.items():
            if value.get("status") == "OK":
                ready[key] += 1

        rs_sector = r.get("rs_sector_pp") or {"1": None, "3": None}
        sector_benchmark = r.get("sector_benchmark")
        if market == "KOSPI":
            if r.get("status") != "READY":
                raise SystemExit("KOSPI_SECTOR_STATUS_NOT_READY:" + ticker)
            if rs_sector.get("1") is None or rs_sector.get("3") is None:
                raise SystemExit("KOSPI_SECTOR_VALUE_MISSING:" + ticker)
            if not sector_benchmark:
                raise SystemExit("KOSPI_SECTOR_BENCHMARK_MISSING:" + ticker)
            kospi_sector_ready += 1
        elif market == "KOSDAQ":
            if r.get("status") != "NOT_SUPPORTED_CURRENT_CONTRACT":
                raise SystemExit("KOSDAQ_SECTOR_STATUS_UNEXPECTED:" + ticker)
            if rs_sector != {"1": None, "3": None}:
                raise SystemExit("KOSDAQ_SECTOR_VALUE_NOT_NULL:" + ticker)
            if sector_benchmark is not None:
                raise SystemExit("KOSDAQ_SECTOR_BENCHMARK_NOT_NULL:" + ticker)
            kosdaq_sector_null += 1
        else:
            raise SystemExit("UNKNOWN_MARKET:" + str(market))

        trailing = s.get("trailing_reference") or {}
        if trailing.get("confirmed_swing_low_stop") is not None:
            raise SystemExit("CONFIRMED_SWING_STOP_POPULATED:" + ticker)

        row = {
            "ticker": ticker,
            "name": s.get("name"),
            "market": market,
            "basis_date": basis,
            "official_close": s.get("official_close"),
            "metric_status": s.get("metric_status"),
            "price_performance": perf,
            "swing": s.get("swing"),
            "ma": s.get("ma"),
            "run": s.get("run"),
            "streak": s.get("streak"),
            "rs_kospi_pp": s.get("rs_kospi_pp"),
            "sector_benchmark": sector_benchmark,
            "rs_sector_pp": rs_sector,
            "atr14": s.get("atr14"),
            "avg_daily_range_20_pct": s.get("avg_daily_range_20_pct"),
            "range_3m": s.get("range_3m"),
            "trailing_reference": {
                "ma20_close_level": trailing.get("ma20_close_level"),
                "below_ma20_at_official_close": trailing.get("below_ma20_at_official_close"),
                "confirmed_swing_low_stop": None,
                "status": trailing.get("status"),
            },
            "matches_decliners_24": s.get("matches_decliners_24"),
            "pending_metrics": {key: None for key in PENDING_KEYS},
        }
        integrated_rows.append(row)

    expected_ready = {
        "1w": 235,
        "1m": 235,
        "3m": 235,
        "6m": 234,
        "ytd": 234,
        "52w": 233,
    }
    if ready != expected_ready:
        raise SystemExit(
            "INTEGRATED_RETURN_READY_COUNT_MISMATCH:"
            + json.dumps(ready, ensure_ascii=False)
        )
    if kospi_sector_ready != 210:
        raise SystemExit(f"KOSPI_SECTOR_READY_COUNT_MISMATCH:{kospi_sector_ready}")
    if kosdaq_sector_null != 25:
        raise SystemExit(f"KOSDAQ_SECTOR_NULL_COUNT_MISMATCH:{kosdaq_sector_null}")

    safety = {
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "production_table_changed": False,
        "worker_changed": False,
        "core_metric_formula_changed": False,
        "request_time_price_substitution": False,
        "return_1w_calculated": True,
        "return_ytd_calculated": True,
        "return_52w_calculated": True,
        "rsi_calculated": False,
        "macd_calculated": False,
        "investment_score_100_calculated": False,
        "earnings_outlook_change_calculated": False,
        "confirmed_swing_low_stop_calculated": False,
        "kosdaq_sector_mapping_invented": False,
        "new_command_defined": False,
    }

    payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "row_count": len(integrated_rows),
        "market_counts": sector.get("market_counts"),
        "return_basis": extended.get("return_basis"),
        "return_start_dates": extended.get("return_start_dates"),
        "return_ready_count": ready,
        "return_missing_count": extended.get("return_missing_count"),
        "kospi_sector_rs_ready_count": kospi_sector_ready,
        "kosdaq_sector_rs_null_count": kosdaq_sector_null,
        "pending_metrics": PENDING_KEYS,
        "metric_glossary_version": glossary.get("version"),
        "metric_glossary_footer": footer,
        "source_lineage": {
            "swing_contract_version": swing.get("contract_version"),
            "extended_returns_contract_version": extended.get("contract_version"),
            "sector_rs_contract_version": sector.get("contract_version"),
        },
        "source_sha256": {
            str(SWING): sha256(SWING),
            str(EXTENDED): sha256(EXTENDED),
            str(SECTOR_RS): sha256(SECTOR_RS),
            str(GLOSSARY): sha256(GLOSSARY),
        },
        "rows": integrated_rows,
        "safety": safety,
    }
    write_json(OUT_JSON, payload)

    csv_fields = [
        "basis_date", "market", "ticker", "name", "official_close",
        "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct",
        "return_ytd_pct", "return_52w_pct",
        "swing_phase", "swing_phase_ko", "swing_trough_date", "swing_peak_date",
        "from_trough_pct", "from_peak_pct", "momentum_5d_pct",
        "ma5_direction", "ma20_direction", "ma60_direction", "ma120_direction",
        "mean_run_days", "streak_direction", "streak_days", "streak_change_pct",
        "rs_kospi_1m_pp", "rs_kospi_3m_pp",
        "sector_benchmark_ticker", "sector_benchmark_name",
        "rs_sector_1m_pp", "rs_sector_3m_pp",
        "atr14_pct", "avg_daily_range_20_pct",
        "ma20_reference", "confirmed_swing_low_stop",
        "rsi", "macd", "investment_score_100", "earnings_outlook_change",
    ]

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for row in integrated_rows:
            perf = row["price_performance"]
            swing_info = row.get("swing") or {}
            ma = row.get("ma") or {}
            run = row.get("run") or {}
            streak = row.get("streak") or {}
            rsk = row.get("rs_kospi_pp") or {}
            rss = row.get("rs_sector_pp") or {}
            bench = row.get("sector_benchmark") or {}
            atr = row.get("atr14") or {}
            trailing = row.get("trailing_reference") or {}

            def ma_dir(period):
                return (ma.get(str(period)) or {}).get("direction")

            w.writerow({
                "basis_date": basis,
                "market": row["market"],
                "ticker": row["ticker"],
                "name": row["name"],
                "official_close": row["official_close"],
                "return_1w_pct": (perf["1w"] or {}).get("pct"),
                "return_1m_pct": (perf["1m"] or {}).get("pct"),
                "return_3m_pct": (perf["3m"] or {}).get("pct"),
                "return_6m_pct": (perf["6m"] or {}).get("pct"),
                "return_ytd_pct": (perf["ytd"] or {}).get("pct"),
                "return_52w_pct": (perf["52w"] or {}).get("pct"),
                "swing_phase": swing_info.get("phase"),
                "swing_phase_ko": swing_info.get("phase_ko"),
                "swing_trough_date": swing_info.get("trough_date"),
                "swing_peak_date": swing_info.get("peak_date"),
                "from_trough_pct": swing_info.get("from_trough_pct"),
                "from_peak_pct": swing_info.get("from_peak_pct"),
                "momentum_5d_pct": swing_info.get("momentum_5d_pct"),
                "ma5_direction": ma_dir(5),
                "ma20_direction": ma_dir(20),
                "ma60_direction": ma_dir(60),
                "ma120_direction": ma_dir(120),
                "mean_run_days": run.get("average"),
                "streak_direction": streak.get("direction"),
                "streak_days": streak.get("days"),
                "streak_change_pct": streak.get("change_pct"),
                "rs_kospi_1m_pp": rsk.get("1"),
                "rs_kospi_3m_pp": rsk.get("3"),
                "sector_benchmark_ticker": bench.get("benchmark_ticker"),
                "sector_benchmark_name": bench.get("benchmark_name"),
                "rs_sector_1m_pp": rss.get("1"),
                "rs_sector_3m_pp": rss.get("3"),
                "atr14_pct": atr.get("pct"),
                "avg_daily_range_20_pct": row.get("avg_daily_range_20_pct"),
                "ma20_reference": trailing.get("ma20_close_level"),
                "confirmed_swing_low_stop": None,
                "rsi": None,
                "macd": None,
                "investment_score_100": None,
                "earnings_outlook_change": None,
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
        "row_count": len(integrated_rows),
        "market_counts": sector.get("market_counts"),
        "return_basis": extended.get("return_basis"),
        "return_start_dates": extended.get("return_start_dates"),
        "return_ready_count": ready,
        "return_missing_count": extended.get("return_missing_count"),
        "kospi_sector_rs_ready_count": kospi_sector_ready,
        "kosdaq_sector_rs_null_count": kosdaq_sector_null,
        "pending_metrics": PENDING_KEYS,
        "metric_glossary_version": glossary.get("version"),
        "source_lineage": payload["source_lineage"],
        "source_sha256": payload["source_sha256"],
        "safety": safety,
    }
    write_json(OUT_META, meta)

    log = [
        "V8717_INTEGRATED_SWING_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        f"INTEGRATED_ROWS={len(integrated_rows)}",
        f"RETURN_1W_READY={ready['1w']}",
        f"RETURN_1M_READY={ready['1m']}",
        f"RETURN_3M_READY={ready['3m']}",
        f"RETURN_6M_READY={ready['6m']}",
        f"RETURN_YTD_READY={ready['ytd']}",
        f"RETURN_52W_READY={ready['52w']}",
        f"KOSPI_SECTOR_RS_READY={kospi_sector_ready}",
        f"KOSDAQ_SECTOR_RS_NULL={kosdaq_sector_null}",
        "PENDING_METRICS=rsi,macd,investment_score_100,earnings_outlook_change,confirmed_swing_low_stop",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "NEW_COMMAND_DEFINED=false",
        "V8717_INTEGRATED_SWING_SOURCE_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))

if __name__ == "__main__":
    main()
