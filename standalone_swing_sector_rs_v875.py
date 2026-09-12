#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib, csv, io, json, time
from pathlib import Path
from pykrx import stock
import sector_rs_source_v870 as sector

SCRIPT_VERSION = "standalone_swing_sector_rs_v875.py v1.0.0-source-only"
CONTRACT_VERSION = "2026-09-12-v8.7.5-standalone-swing-sector-rs-source"

SWING = Path("latest/standalone_swing_source_latest.json")
GLOSSARY = Path("latest/stock_table_metric_glossary_latest.json")
TABLE_DIR = Path("api/two_table_v1")
TABLES = ("kospi", "decliners", "decliners24")

OUT_JSON = Path("latest/standalone_swing_sector_rs_latest.json")
OUT_CSV = Path("latest/standalone_swing_sector_rs_latest.csv")
OUT_META = Path("latest/standalone_swing_sector_rs_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_sector_rs_run_log_latest.txt")

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

def main():
    for p in (SWING, GLOSSARY, Path("sector_rs_source_v870.py")):
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    swing = read(SWING)
    glossary = read(GLOSSARY)
    if swing.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("SWING_SOURCE_NOT_READY")
    if swing.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("STANDALONE_SWING_ALREADY_ENABLED")

    basis = swing.get("basis_date")
    footer = glossary.get("compact_footer_text")
    if not basis:
        raise SystemExit("SWING_BASIS_MISSING")
    if not footer:
        raise SystemExit("GLOSSARY_COMPACT_FOOTER_TEXT_MISSING")

    swing_rows = {str(r["ticker"]).zfill(6): r for r in swing.get("rows") or []}
    if len(swing_rows) != int(swing.get("row_count") or 0):
        raise SystemExit("SWING_ROW_COUNT_MISMATCH")

    kospi = sorted(t for t,r in swing_rows.items() if r.get("market") == "KOSPI")
    kosdaq = sorted(t for t,r in swing_rows.items() if r.get("market") == "KOSDAQ")
    if len(kospi) + len(kosdaq) != len(swing_rows):
        raise SystemExit("UNSUPPORTED_MARKET_PRESENT")

    production = {}
    for name in TABLES:
        p = TABLE_DIR / f"{name}.json"
        if not p.is_file():
            raise SystemExit("MISSING_PRODUCTION_TABLE:" + str(p))
        data = read(p)
        if data.get("status") != "READY" or data.get("basis_date") != basis:
            raise SystemExit("PRODUCTION_TABLE_NOT_ALIGNED:" + name)
        for row in data.get("rows") or []:
            ticker = str(row.get("ticker") or "").zfill(6)
            metrics = row.get("metrics") or {}
            rs = metrics.get("rs_sector_pp")
            bench = metrics.get("sector_benchmark")
            if not isinstance(rs, dict) or rs.get("1") is None or rs.get("3") is None:
                raise SystemExit("PRODUCTION_RS_NOT_READY:" + ticker)
            snap = {
                "rs_sector_pp": {"1": rs["1"], "3": rs["3"]},
                "sector_benchmark": bench,
                "name": row.get("name"),
            }
            if ticker in production and production[ticker] != snap:
                raise SystemExit("PRODUCTION_DUPLICATE_MISMATCH:" + ticker)
            production[ticker] = snap

    basis_compact, names, members, basic = sector.fetch_official_sources(basis)
    if basis_compact != basis.replace("-", ""):
        raise SystemExit("OFFICIAL_BASIS_MISMATCH")

    mapping = {}
    errors = {}
    for ticker in kospi:
        try:
            mapping[ticker] = sector.build_mapping({ticker}, names, members, basic)[ticker]
        except Exception as exc:
            errors[ticker] = repr(exc)
    if errors or len(mapping) != len(kospi):
        raise SystemExit("KOSPI_MAPPING_INCOMPLETE:" + json.dumps(errors, ensure_ascii=False)[:6000])

    starts = []
    for ticker in kospi:
        returns = swing_rows[ticker].get("returns") or {}
        for p in ("1", "3"):
            item = returns.get(p) or {}
            if item.get("status") != "OK" or item.get("start_date") is None or item.get("pct") is None:
                raise SystemExit(f"STOCK_RETURN_NOT_READY:{ticker}:{p}")
            starts.append(item["start_date"])
    earliest = min(starts).replace("-", "")

    index_closes = {}
    for idx in sorted({m["benchmark_ticker"] for m in mapping.values()}):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = stock.get_index_ohlcv_by_date(earliest, basis.replace("-", ""), idx)
        if df is None or df.empty or "종가" not in df.columns:
            raise SystemExit("INDEX_OHLCV_EMPTY:" + idx)
        index_closes[idx] = {
            (dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]): float(value)
            for dt, value in df["종가"].items()
        }
        time.sleep(0.08)

    rows = []
    for ticker in sorted(swing_rows):
        s = swing_rows[ticker]
        if s.get("market") == "KOSDAQ":
            rows.append({
                "ticker": ticker, "name": s.get("name"), "market": "KOSDAQ",
                "basis_date": basis, "status": "NOT_SUPPORTED_CURRENT_CONTRACT",
                "sector_benchmark": None,
                "rs_sector_pp": {"1": None, "3": None},
                "missing_reason": "CURRENT_OFFICIAL_SECTOR_RS_CONTRACT_IS_KOSPI_ONLY",
            })
            continue

        m = mapping[ticker]
        closes = index_closes[m["benchmark_ticker"]]
        values = {}
        for p in ("1", "3"):
            src = (s.get("returns") or {})[p]
            start = src["start_date"]
            if start not in closes or basis not in closes:
                raise SystemExit(f"INDEX_DATE_MISSING:{ticker}:{p}:{start}")
            start_close = closes[start]
            if start_close <= 0:
                raise SystemExit(f"INDEX_START_CLOSE_INVALID:{ticker}:{p}")
            idx_ret = 100.0 * (closes[basis] / start_close - 1.0)
            values[p] = round(float(src["pct"]) - idx_ret, 4)

        rows.append({
            "ticker": ticker, "name": s.get("name"), "market": "KOSPI",
            "basis_date": basis, "status": "READY",
            "sector_benchmark": m, "rs_sector_pp": values,
            "missing_reason": None,
        })

    by_ticker = {r["ticker"]: r for r in rows}
    matches, mismatches = 0, []
    for ticker, expected in sorted(production.items()):
        actual = by_ticker.get(ticker)
        if actual is None:
            mismatches.append({"ticker": ticker, "reason": "SOURCE_MISSING"})
            continue
        eb = expected.get("sector_benchmark") or {}
        ab = actual.get("sector_benchmark") or {}
        ok_b = (
            str(eb.get("benchmark_ticker")) == str(ab.get("benchmark_ticker"))
            and eb.get("benchmark_name") == ab.get("benchmark_name")
        )
        ok_rs = actual.get("rs_sector_pp") == expected.get("rs_sector_pp")
        if ok_b and ok_rs:
            matches += 1
        else:
            mismatches.append({
                "ticker": ticker,
                "expected_rs": expected.get("rs_sector_pp"),
                "actual_rs": actual.get("rs_sector_pp"),
                "expected_benchmark": eb,
                "actual_benchmark": ab,
            })

    if mismatches or matches != len(production):
        raise SystemExit("PRODUCTION_REGRESSION_FAILED:" + json.dumps(mismatches, ensure_ascii=False)[:6000])

    kospi_ready = sum(1 for r in rows if r["market"] == "KOSPI" and r["status"] == "READY")
    kosdaq_null = sum(
        1 for r in rows
        if r["market"] == "KOSDAQ" and r["rs_sector_pp"] == {"1": None, "3": None}
    )

    safety = {
        "new_sector_contract_defined": False,
        "kosdaq_sector_mapping_invented": False,
        "production_table_changed": False,
        "worker_changed": False,
        "metric_formula_changed": False,
        "request_time_price_substitution": False,
    }

    payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "row_count": len(rows),
        "market_counts": {"KOSPI": len(kospi), "KOSDAQ": len(kosdaq)},
        "kospi_sector_rs_ready_count": kospi_ready,
        "kosdaq_sector_rs_null_count": kosdaq_null,
        "production_unique_ticker_count": len(production),
        "production_regression_exact_matches": matches,
        "production_regression_mismatches": 0,
        "glossary_footer_text": footer,
        "rows": rows,
        "safety": safety,
    }
    write_json(OUT_JSON, payload)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "basis_date","market","ticker","name","status",
            "benchmark_ticker","benchmark_name",
            "rs_sector_1m_pp","rs_sector_3m_pp","missing_reason"
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            b = r.get("sector_benchmark") or {}
            rs = r.get("rs_sector_pp") or {}
            w.writerow({
                "basis_date": basis, "market": r["market"], "ticker": r["ticker"],
                "name": r["name"], "status": r["status"],
                "benchmark_ticker": b.get("benchmark_ticker"),
                "benchmark_name": b.get("benchmark_name"),
                "rs_sector_1m_pp": rs.get("1"),
                "rs_sector_3m_pp": rs.get("3"),
                "missing_reason": r.get("missing_reason"),
            })

    meta = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "row_count": len(rows),
        "kospi_ticker_count": len(kospi),
        "kosdaq_ticker_count": len(kosdaq),
        "kospi_sector_rs_ready_count": kospi_ready,
        "kosdaq_sector_rs_null_count": kosdaq_null,
        "production_unique_ticker_count": len(production),
        "production_regression_exact_matches": matches,
        "production_regression_mismatches": 0,
        "glossary_footer_key": "compact_footer_text",
        "safety": safety,
    }
    write_json(OUT_META, meta)

    log = [
        "V875_STANDALONE_SECTOR_RS_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        f"SOURCE_TICKERS={len(rows)}",
        f"KOSPI_TICKERS={len(kospi)}",
        f"KOSDAQ_TICKERS={len(kosdaq)}",
        f"KOSPI_SECTOR_RS_READY={kospi_ready}",
        f"KOSDAQ_SECTOR_RS_NULL={kosdaq_null}",
        f"PRODUCTION_UNIQUE_TICKERS={len(production)}",
        f"PRODUCTION_REGRESSION_EXACT_MATCHES={matches}",
        "PRODUCTION_REGRESSION_MISMATCHES=0",
        "GLOSSARY_FOOTER_KEY=compact_footer_text",
        "GLOSSARY_FOOTER_READY=true",
        "KOSDAQ_SECTOR_MAPPING_INVENTED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_SOURCE_CHANGED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V875_STANDALONE_SECTOR_RS_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))

if __name__ == "__main__":
    main()
