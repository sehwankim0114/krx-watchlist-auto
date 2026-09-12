from __future__ import annotations

import contextlib
import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pykrx import stock
from pykrx.website.krx.market.core import 전종목기본정보

NARROW_INDUSTRY = {f"{x:04d}" for x in range(1005, 1027)} | {"1045", "1046", "1047"}
MANUFACTURING_FALLBACK = "1027"
TABLES = ("kospi", "decliners", "decliners24")
OLD_COLUMNS = [
    "name", "ticker", "official_close", "run", "streak", "range_3m", "swing", "ma",
    "returns", "rs_kospi_pp", "atr14", "activity", "analysis", "sector_theme",
]
NEW_COLUMNS = [
    "name", "ticker", "official_close", "run", "streak", "range_3m", "swing", "ma",
    "returns", "rs_kospi_pp", "atr14", "activity", "analysis", "rs_sector_pp", "sector_theme",
]
CONTRACT_VERSION = "2026-09-12-v8.7.0-official-krx-sector-rs"


def require(ok, message):
    if not ok:
        raise ValueError("SECTOR_RS_" + message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def issuer_stem(name):
    value = (name or "").strip()
    for pattern in (
        r"\s*보통주$",
        r"\s*\d+우선주\(신형\)$",
        r"\s*\d+우선주$",
        r"\s*우선주\(신형\)$",
        r"\s*우선주$",
    ):
        normalized = re.sub(pattern, "", value)
        if normalized != value:
            return normalized.strip()
    return value


def fetch_official_sources(basis_iso):
    require(bool(os.getenv("KRX_ID")) and bool(os.getenv("KRX_PW")), "KRX_SECRETS_REQUIRED")
    basis = basis_iso.replace("-", "")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        index_tickers = list(map(str, stock.get_index_ticker_list(basis, market="KOSPI") or []))
    require(bool(index_tickers), "KOSPI_INDEX_LIST_EMPTY")

    names, members = {}, {}
    for idx in index_tickers:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                names[idx] = stock.get_index_ticker_name(idx)
                rows = stock.get_index_portfolio_deposit_file(idx, date=basis) or []
            members[idx] = {str(x).zfill(6) for x in rows}
        except Exception as exc:
            raise ValueError(f"SECTOR_RS_INDEX_SOURCE_FAILED:{idx}:{exc!r}") from exc
        time.sleep(0.08)

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            basic_df = 전종목기본정보().fetch(mktId="STK")
    except Exception as exc:
        raise ValueError(f"SECTOR_RS_BASIC_INFO_FAILED:{exc!r}") from exc

    basic = {}
    for _, row in basic_df.iterrows():
        ticker = str(row.get("ISU_SRT_CD") or "").zfill(6)
        if re.fullmatch(r"\d{6}", ticker):
            basic[ticker] = {
                "isu_nm": str(row.get("ISU_NM") or "").strip(),
                "abbr": str(row.get("ISU_ABBRV") or "").strip(),
                "security_type": str(row.get("KIND_STKCERT_TP_NM") or "").strip(),
            }
    require(len(basic) >= 800, "KOSPI_BASIC_INFO_TOO_SMALL")
    return basis, names, members, basic


def choose_direct(ticker, names, members):
    candidates = sorted(idx for idx in NARROW_INDUSTRY if ticker in members.get(idx, set()))
    if "1021" in candidates:
        children = [x for x in ("1024", "1025") if x in candidates]
        if len(children) == 1:
            return children[0], "DIRECT_CHILD_OVER_FINANCE"
    if len(candidates) == 1:
        return candidates[0], "DIRECT_NARROW"
    if len(candidates) > 1:
        return None, "AMBIGUOUS_MULTIPLE_NARROW"
    if ticker in members.get(MANUFACTURING_FALLBACK, set()):
        return MANUFACTURING_FALLBACK, "DIRECT_MANUFACTURING_FALLBACK_NO_NARROWER"
    return None, "NO_DIRECT_INDUSTRY"


def build_mapping(tickers, names, members, basic):
    common_by_stem = {}
    for ticker, info in basic.items():
        if info["security_type"] == "보통주":
            common_by_stem.setdefault(issuer_stem(info["isu_nm"]), []).append(ticker)

    mapping = {}
    for ticker in sorted(tickers):
        benchmark, mode = choose_direct(ticker, names, members)
        common_ticker = None
        if benchmark is None:
            info = basic.get(ticker)
            if info and "우선주" in info["security_type"]:
                candidates = sorted(common_by_stem.get(issuer_stem(info["isu_nm"]), []))
                require(len(candidates) == 1, f"PREFERRED_COMMON_NOT_UNIQUE:{ticker}:{candidates}")
                common_ticker = candidates[0]
                benchmark, inherited = choose_direct(common_ticker, names, members)
                require(benchmark is not None, f"PREFERRED_COMMON_INDUSTRY_NOT_READY:{ticker}:{common_ticker}")
                mode = "PREFERRED_INHERIT_" + inherited
        require(benchmark is not None, f"UNMATCHED:{ticker}:{mode}")
        mapping[ticker] = {
            "benchmark_ticker": benchmark,
            "benchmark_name": names.get(benchmark),
            "selection_mode": mode,
            "common_ticker": common_ticker,
        }
    return mapping


def enrich_bundle(staging, basis_iso, repo=None):
    staging = Path(staging)
    payloads = {table: read(staging / f"{table}.json") for table in TABLES}

    records = {}
    for table, payload in payloads.items():
        for row in payload.get("rows") or []:
            ticker = str(row.get("ticker") or "").zfill(6)
            metrics = row.get("metrics") or {}
            signature = {
                p: {
                    "pct": ((metrics.get("returns") or {}).get(p) or {}).get("pct"),
                    "start_date": ((metrics.get("returns") or {}).get(p) or {}).get("start_date"),
                    "status": ((metrics.get("returns") or {}).get(p) or {}).get("status"),
                }
                for p in ("1", "3")
            }
            if ticker in records:
                require(records[ticker]["signature"] == signature, f"DUPLICATE_RETURN_MISMATCH:{ticker}")
            else:
                records[ticker] = {"signature": signature, "name": row.get("name")}

    basis, names, members, basic = fetch_official_sources(basis_iso)
    mapping = build_mapping(records, names, members, basic)

    starts = [
        rec["signature"][p]["start_date"]
        for rec in records.values()
        for p in ("1", "3")
        if rec["signature"][p].get("start_date")
    ]
    require(bool(starts), "RETURN_START_DATES_EMPTY")
    earliest = min(starts).replace("-", "")

    closes_by_index = {}
    for idx in sorted({m["benchmark_ticker"] for m in mapping.values()}):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = stock.get_index_ohlcv_by_date(earliest, basis, idx)
        except Exception as exc:
            raise ValueError(f"SECTOR_RS_INDEX_OHLCV_FAILED:{idx}:{exc!r}") from exc
        require(df is not None and not df.empty and "종가" in df.columns, f"INDEX_OHLCV_EMPTY:{idx}")
        closes_by_index[idx] = {
            (dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]): float(value)
            for dt, value in df["종가"].items()
        }
        time.sleep(0.10)

    ready_values = 0
    for ticker, rec in records.items():
        idx = mapping[ticker]["benchmark_ticker"]
        closes = closes_by_index[idx]
        values = {}
        for p in ("1", "3"):
            src = rec["signature"][p]
            start = src.get("start_date")
            require(src.get("status") == "OK" and src.get("pct") is not None and start,
                    f"STOCK_RETURN_NOT_READY:{ticker}:{p}")
            require(start in closes and basis_iso in closes, f"INDEX_RETURN_DATE_MISSING:{ticker}:{idx}:{p}:{start}")
            start_close, end_close = closes[start], closes[basis_iso]
            require(start_close > 0, f"INDEX_START_CLOSE_INVALID:{idx}:{start}")
            index_return = 100.0 * (end_close / start_close - 1.0)
            values[p] = round(float(src["pct"]) - index_return, 4)
            ready_values += 1
        rec["rs_sector_pp"] = values

    row_count = 0
    for table, payload in payloads.items():
        for row in payload["rows"]:
            ticker = row["ticker"]
            metrics = row["metrics"]
            metrics["rs_sector_pp"] = dict(records[ticker]["rs_sector_pp"])
            missing = dict(metrics.get("missing") or {})
            missing.pop("rs_sector", None)
            metrics["missing"] = missing
            metrics["sector_benchmark"] = dict(mapping[ticker])
            row_count += 1
        (staging / f"{table}.json").write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8"
        )

    compact_rows = 0
    for table in TABLES:
        canonical_by_ticker = {r["ticker"]: r for r in payloads[table]["rows"]}
        page_no = 1
        while True:
            path = staging / f"{table}.compact.{page_no}.json"
            if not path.exists():
                break
            payload = read(path)
            require(payload.get("columns") in (OLD_COLUMNS, NEW_COLUMNS), f"COMPACT_COLUMNS_UNEXPECTED:{path.name}")
            new_rows = []
            for row in payload["rows"]:
                ticker = row[1]
                require(ticker in canonical_by_ticker, f"COMPACT_TICKER_NOT_CANONICAL:{ticker}")
                values = records[ticker]["rs_sector_pp"]
                pair = [values["1"], values["3"]]
                if payload["columns"] == OLD_COLUMNS:
                    row = row[:-1] + [pair, row[-1]]
                else:
                    row = list(row)
                    row[13] = pair
                require(len(row) == 15, f"COMPACT_WIDTH:{path.name}:{ticker}")
                new_rows.append(row)
                compact_rows += 1
            payload["columns"] = NEW_COLUMNS
            payload["rows"] = new_rows
            path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
            page_no += 1

    audit = {
        "version": CONTRACT_VERSION,
        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "basis_date": basis_iso,
        "unique_ticker_count": len(records),
        "table_row_count": row_count,
        "compact_row_count": compact_rows,
        "rs_values_ready": ready_values,
        "rs_values_expected": len(records) * 2,
        "mapping": [
            {"ticker": ticker, "name": records[ticker]["name"], **mapping[ticker],
             "rs_sector_pp": records[ticker]["rs_sector_pp"]}
            for ticker in sorted(records)
        ],
        "policy": {
            "narrow_industry_indices": sorted(NARROW_INDUSTRY),
            "manufacturing_fallback": MANUFACTURING_FALLBACK,
            "finance_child_preference": ["1024", "1025"],
            "preferred_share_inheritance": "UNIQUE_COMMON_SHARE_BY_EXACT_NORMALIZED_OFFICIAL_KRX_ISU_NM_STEM",
            "fuzzy_mapping": False,
            "ticker_prefix_guess": False,
            "sector_theme_fallback": False,
            "period_alignment": "EXACT_EXISTING_STOCK_RETURN_START_DATE_TO_COMMON_OFFICIAL_BASIS_DATE",
            "unit": "PERCENTAGE_POINTS",
        },
    }
    require(audit["rs_values_ready"] == audit["rs_values_expected"], "RS_COVERAGE_INCOMPLETE")
    if repo is not None:
        write(Path(repo) / "latest/sector_rs_source_latest.json", audit)
    return audit
