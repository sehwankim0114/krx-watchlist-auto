#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.5.7 active-stock compact 260-session history builder.

Purpose:
- Maintain a compact official KRX daily OHLCV/value/market-cap history cache
  only for Korean tickers that currently appear in active stock-table APIs.
- Keep the latest 260 distinct KRX market sessions.
- Reuse the exact normalized schema already used by collect_universe.py.

Hard guards:
- This is SOURCE DATA ONLY.
- It does not calculate sector RS, confirmed-swing-low trailing stops,
  standalone swing metrics, or investment_score_100.
- It must never be used as a substitute for request-time current price.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

SCRIPT_VERSION = "active_stock_long_history_builder_v857.py v1.0.0-source-cache-only"
CONTRACT_VERSION = "2026-09-11-v8.5.7-compact-active-stock-260-session-history"
KST = ZoneInfo("Asia/Seoul")

OPENAPI_STOCK_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
}

CACHE_COLUMNS = [
    "date",
    "market",
    "ticker",
    "name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "market_cap",
    "listed_shares",
]

TICKER_KEYS = {"ticker", "code", "quote_key", "stock_code", "종목코드"}

FORBIDDEN_METRIC_COLUMNS = {
    "sector_rs",
    "rs_sector",
    "rs_1m",
    "rs_3m",
    "confirmed_swing_low_stop",
    "trailing_stop",
    "trailing_stop_price",
    "standalone_swing_metric",
    "investment_score_100",
    "score_total",
}

DEFAULT_CACHE_NAME = "active_stock_long_history_260d_latest.csv"
DEFAULT_META_NAME = "active_stock_long_history_260d_meta_latest.json"
DEFAULT_LOG_NAME = "active_stock_long_history_260d_run_log_latest.txt"

MAX_CACHE_BYTES = 20 * 1024 * 1024


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def target_hash(tickers: Sequence[str]) -> str:
    return sha256_bytes(("\n".join(sorted(tickers)) + "\n").encode("utf-8"))


def normalize_ticker(value) -> Optional[str]:
    s = str(value or "").strip().replace("'", "")
    if re.fullmatch(r"\d{1,6}", s):
        return s.zfill(6)
    if s.startswith("KR") and len(s) >= 9:
        cand = s[3:9]
        if re.fullmatch(r"\d{6}", cand):
            return cand
    m = re.search(r"(?<!\d)(\d{6})(?!\d)", s)
    return m.group(1) if m else None


def normalize_date(value) -> Optional[str]:
    s = str(value or "").strip()
    if not s:
        return None
    s = s[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except Exception:
        return None


def clean_number(value) -> str:
    if value is None:
        return ""
    s = str(value).strip().replace(",", "").replace("'", "").replace(" ", "")
    if s in {"", "-", "nan", "NaN", "None", "null"}:
        return ""
    return s


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def extract_tickers(node) -> Set[str]:
    found: Set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in TICKER_KEYS:
                ticker = normalize_ticker(value)
                if ticker:
                    found.add(ticker)
            if isinstance(value, (dict, list)):
                found.update(extract_tickers(value))
    elif isinstance(node, list):
        for item in node:
            found.update(extract_tickers(item))
    return found


def resolve_active_api_tickers(root: Path) -> Tuple[Set[str], List[str]]:
    registry_path = root / "latest" / "table_route_registry_latest.json"
    if not registry_path.exists():
        raise RuntimeError(f"ROUTE_REGISTRY_MISSING:{registry_path}")

    registry = read_json(registry_path)
    api_paths: Set[Path] = set()

    for route in registry.get("routes", []):
        for value in route.get("api_files", []) or []:
            path = root / str(value)
            if path.exists() and path.is_file():
                api_paths.add(path)

    # Production two-table family is newer than the legacy route registry.
    for name in ("kospi.json", "decliners.json", "decliners24.json"):
        path = root / "api" / "two_table_v1" / name
        if path.exists() and path.is_file():
            api_paths.add(path)

    tickers: Set[str] = set()
    scanned: List[str] = []

    for path in sorted(api_paths):
        try:
            payload = read_json(path)
        except Exception:
            continue
        one = extract_tickers(payload)
        if one:
            tickers.update(one)
            scanned.append(path.relative_to(root).as_posix())

    if not tickers:
        raise RuntimeError("ACTIVE_API_TICKERS_EMPTY")
    return tickers, scanned


def normalize_source_row(raw: dict) -> Optional[dict]:
    ticker = normalize_ticker(raw.get("ticker"))
    d = normalize_date(raw.get("date"))
    close = clean_number(raw.get("close"))
    if not ticker or not d or not close:
        return None

    market = str(raw.get("market") or "").strip().upper()
    if market not in {"KOSPI", "KOSDAQ"}:
        return None

    return {
        "date": d,
        "market": market,
        "ticker": ticker,
        "name": str(raw.get("name") or "").strip(),
        "open": clean_number(raw.get("open")),
        "high": clean_number(raw.get("high")),
        "low": clean_number(raw.get("low")),
        "close": close,
        "volume": clean_number(raw.get("volume")),
        "trading_value": clean_number(raw.get("trading_value")),
        "market_cap": clean_number(raw.get("market_cap")),
        "listed_shares": clean_number(raw.get("listed_shares")),
    }


def read_history_rows(path: Path, allowed_tickers: Optional[Set[str]] = None) -> List[dict]:
    if not path.exists():
        return []

    rows: List[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = [c for c in CACHE_COLUMNS if c not in fields]
        if missing:
            raise RuntimeError(f"HISTORY_SCHEMA_MISSING:{path}:{','.join(missing)}")
        if fields & FORBIDDEN_METRIC_COLUMNS:
            raise RuntimeError(f"FORBIDDEN_METRIC_COLUMN_PRESENT:{path}")

        for raw in reader:
            row = normalize_source_row(raw)
            if not row:
                continue
            if allowed_tickers is not None and row["ticker"] not in allowed_tickers:
                continue
            rows.append(row)
    return rows


def rows_to_map(rows: Iterable[dict]) -> Dict[Tuple[str, str, str], dict]:
    out: Dict[Tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["date"], row["market"], row["ticker"])
        out[key] = row
    return out


def date_set(rows: Iterable[dict]) -> Set[str]:
    return {row["date"] for row in rows if row.get("date")}


def cache_ticker_set(rows: Iterable[dict]) -> Set[str]:
    return {row["ticker"] for row in rows if row.get("ticker")}


def official_row_to_cache(raw: dict, market: str, bas_date: str, wanted: Set[str]) -> Optional[dict]:
    ticker = normalize_ticker(raw.get("ISU_CD"))
    if not ticker or ticker not in wanted:
        return None

    close = clean_number(raw.get("TDD_CLSPRC"))
    if not close:
        return None

    return {
        "date": bas_date,
        "market": market,
        "ticker": ticker,
        "name": str(raw.get("ISU_NM") or "").strip(),
        "open": clean_number(raw.get("TDD_OPNPRC")),
        "high": clean_number(raw.get("TDD_HGPRC")),
        "low": clean_number(raw.get("TDD_LWPRC")),
        "close": close,
        "volume": clean_number(raw.get("ACC_TRDVOL")),
        "trading_value": clean_number(raw.get("ACC_TRDVAL")),
        "market_cap": clean_number(raw.get("MKTCAP")),
        "listed_shares": clean_number(raw.get("LIST_SHRS")),
    }


class OfficialStats:
    def __init__(self):
        self.http_attempts = 0
        self.http_successes = 0
        self.empty_market_responses = 0
        self.transport_retries = 0
        self.partial_market_day_retries = 0
        self.official_days_with_data = 0
        self.official_rows_added = 0

    def as_dict(self):
        return {
            "http_attempts": self.http_attempts,
            "http_successes": self.http_successes,
            "empty_market_responses": self.empty_market_responses,
            "transport_retries": self.transport_retries,
            "partial_market_day_retries": self.partial_market_day_retries,
            "official_days_with_data": self.official_days_with_data,
            "official_rows_added": self.official_rows_added,
        }


def request_krx_market(
    url: str,
    auth_key: str,
    bas_dd: str,
    timeout: int,
    stats: OfficialStats,
    retries: int = 3,
) -> List[dict]:
    if not auth_key:
        raise RuntimeError("KRX_AUTH_KEY_MISSING")

    full_url = url + "?" + urllib.parse.urlencode({"basDd": bas_dd})
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        stats.http_attempts += 1
        req = urllib.request.Request(
            full_url,
            headers={
                "AUTH_KEY": auth_key,
                "User-Agent": "krx-watchlist-v857-compact-history",
                "Accept": "application/json",
                "Connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read(40_000_000).decode("utf-8"))
            rows = payload.get("OutBlock_1") or []
            if not isinstance(rows, list):
                raise RuntimeError(f"KRX_INVALID_ROWS:{bas_dd}")
            stats.http_successes += 1
            if not rows:
                stats.empty_market_responses += 1
            time.sleep(0.06)
            return rows
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                stats.transport_retries += 1
                time.sleep(0.7 * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(
                f"KRX_REQUEST_FAILED:{bas_dd}:{type(exc).__name__}:{exc}"
            ) from exc

    raise RuntimeError(f"KRX_REQUEST_FAILED:{bas_dd}:{last_exc}")


def fetch_official_day(
    d: date,
    wanted: Set[str],
    auth_key: str,
    timeout: int,
    stats: OfficialStats,
) -> List[dict]:
    if d.weekday() >= 5:
        return []

    bas_dd = d.strftime("%Y%m%d")

    def one_round():
        market_raw = {}
        for market, url in OPENAPI_STOCK_URLS.items():
            market_raw[market] = request_krx_market(
                url=url,
                auth_key=auth_key,
                bas_dd=bas_dd,
                timeout=timeout,
                stats=stats,
            )
        return market_raw

    market_raw = one_round()
    nonempty = {m: bool(rows) for m, rows in market_raw.items()}

    # KOSPI/KOSDAQ share the same trading calendar. A one-sided empty response
    # is treated as a source-integrity problem, not silently accepted.
    if len(set(nonempty.values())) > 1:
        stats.partial_market_day_retries += 1
        time.sleep(0.8)
        market_raw = one_round()
        nonempty = {m: bool(rows) for m, rows in market_raw.items()}
        if len(set(nonempty.values())) > 1:
            raise RuntimeError(f"PARTIAL_MARKET_DAY:{d.isoformat()}:{nonempty}")

    if not any(nonempty.values()):
        return []

    out: List[dict] = []
    for market, raw_rows in market_raw.items():
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            row = official_row_to_cache(raw, market, d.isoformat(), wanted)
            if row:
                out.append(row)

    if out:
        stats.official_days_with_data += 1
        stats.official_rows_added += len(out)
    return out


def sorted_rows(row_map: Dict[Tuple[str, str, str], dict]) -> List[dict]:
    return sorted(
        row_map.values(),
        key=lambda r: (r["market"], r["ticker"], r["date"]),
    )


def trim_latest_sessions(
    row_map: Dict[Tuple[str, str, str], dict],
    target_sessions: int,
) -> Dict[Tuple[str, str, str], dict]:
    dates = sorted({k[0] for k in row_map})
    if len(dates) <= target_sessions:
        return row_map
    keep_dates = set(dates[-target_sessions:])
    return {k: v for k, v in row_map.items() if k[0] in keep_dates}


def write_cache_atomic(path: Path, rows: List[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    size = tmp.stat().st_size
    if size > MAX_CACHE_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"CACHE_SIZE_GATE_FAILED:{size}>{MAX_CACHE_BYTES}"
        )
    os.replace(tmp, path)
    return size


def load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def source_context(root: Path):
    source_path = root / "latest" / "universe_raw_history_latest.csv"
    if not source_path.exists():
        raise RuntimeError(f"SOURCE_HISTORY_MISSING:{source_path}")

    raw_active, scanned_files = resolve_active_api_tickers(root)
    all_source_rows = read_history_rows(source_path)
    source_tickers = cache_ticker_set(all_source_rows)
    target = sorted(raw_active & source_tickers)
    if not target:
        raise RuntimeError("TARGET_TICKERS_EMPTY_AFTER_HISTORY_INTERSECTION")

    target_set = set(target)
    source_rows = [r for r in all_source_rows if r["ticker"] in target_set]
    source_dates = sorted(date_set(source_rows))
    if not source_dates:
        raise RuntimeError("TARGET_SOURCE_HISTORY_EMPTY")

    return {
        "source_path": source_path,
        "raw_active": raw_active,
        "scanned_files": scanned_files,
        "target": target,
        "target_set": target_set,
        "source_rows": source_rows,
        "source_dates": source_dates,
        "source_min_date": source_dates[0],
        "source_max_date": source_dates[-1],
    }


def validate_cache(
    root: Path,
    output_dir: Path,
    target_sessions: int,
    require_meta_match: bool = True,
) -> dict:
    ctx = source_context(root)
    cache_path = output_dir / DEFAULT_CACHE_NAME
    meta_path = output_dir / DEFAULT_META_NAME

    if not cache_path.exists():
        raise RuntimeError("CACHE_MISSING")

    rows = read_history_rows(cache_path)
    dates = sorted(date_set(rows))
    if len(dates) != target_sessions:
        raise RuntimeError(
            f"CACHE_DISTINCT_DATE_COUNT_INVALID:{len(dates)}!={target_sessions}"
        )
    if dates[-1] != ctx["source_max_date"]:
        raise RuntimeError(
            f"CACHE_MAX_DATE_MISMATCH:{dates[-1]}!={ctx['source_max_date']}"
        )

    cache_tickers = cache_ticker_set(rows)
    extra = sorted(cache_tickers - ctx["target_set"])
    if extra:
        raise RuntimeError(f"CACHE_HAS_INACTIVE_TICKERS:{extra[:10]}")

    with cache_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    if header != CACHE_COLUMNS:
        raise RuntimeError(f"CACHE_HEADER_MISMATCH:{header}")
    if set(header) & FORBIDDEN_METRIC_COLUMNS:
        raise RuntimeError("CACHE_CONTAINS_FORBIDDEN_METRIC_COLUMNS")

    size = cache_path.stat().st_size
    if size > MAX_CACHE_BYTES:
        raise RuntimeError(f"CACHE_SIZE_GATE_FAILED:{size}")

    meta = load_meta(meta_path)
    expected_target_hash = target_hash(ctx["target"])
    actual_cache_sha = sha256_file(cache_path)

    if require_meta_match:
        if not meta:
            raise RuntimeError("META_MISSING_OR_INVALID")
        if meta.get("contract_version") != CONTRACT_VERSION:
            raise RuntimeError("META_CONTRACT_VERSION_MISMATCH")
        if meta.get("target_ticker_sha256") != expected_target_hash:
            raise RuntimeError("META_TARGET_HASH_MISMATCH")
        if meta.get("source_max_date") != ctx["source_max_date"]:
            raise RuntimeError("META_SOURCE_MAX_DATE_MISMATCH")
        if meta.get("cache_sha256") != actual_cache_sha:
            raise RuntimeError("META_CACHE_SHA256_MISMATCH")
        if int(meta.get("distinct_market_dates") or 0) != target_sessions:
            raise RuntimeError("META_DISTINCT_DATE_COUNT_MISMATCH")

    per_ticker = {}
    for row in rows:
        per_ticker[row["ticker"]] = per_ticker.get(row["ticker"], 0) + 1

    counts = list(per_ticker.values())
    return {
        "rows": len(rows),
        "dates": dates,
        "ticker_count_with_rows": len(per_ticker),
        "target_ticker_count": len(ctx["target"]),
        "target_hash": expected_target_hash,
        "cache_sha256": actual_cache_sha,
        "cache_bytes": size,
        "min_rows_per_ticker": min(counts) if counts else 0,
        "max_rows_per_ticker": max(counts) if counts else 0,
        "tickers_with_260_rows": sum(1 for n in counts if n >= target_sessions),
        "source_max_date": ctx["source_max_date"],
        "source_min_date": ctx["source_min_date"],
        "scanned_files": ctx["scanned_files"],
    }


def print_hard_guards() -> None:
    print("SECTOR_RS_CALCULATED=false")
    print("CONFIRMED_SWING_LOW_STOP_CALCULATED=false")
    print("STANDALONE_SWING_METRICS_CALCULATED=false")
    print("INVESTMENT_SCORE_100_CALCULATED=false")
    print("REQUEST_TIME_PRICE_SUBSTITUTION=false")


def run_self_test() -> int:
    assert normalize_ticker("005930") == "005930"
    assert normalize_ticker("5930") == "005930"
    assert normalize_ticker("KR7005930003") == "005930"
    assert normalize_date("2026-09-11 00:00:00") == "2026-09-11"
    assert set(CACHE_COLUMNS).isdisjoint(FORBIDDEN_METRIC_COLUMNS)
    assert len(CACHE_COLUMNS) == len(set(CACHE_COLUMNS))
    print("SELF_TEST=PASS")
    print("SCRIPT_VERSION=" + SCRIPT_VERSION)
    print("CONTRACT_VERSION=" + CONTRACT_VERSION)
    print_hard_guards()
    return 0


def run_validate(root: Path, output_dir: Path, target_sessions: int) -> int:
    result = validate_cache(root, output_dir, target_sessions, require_meta_match=True)
    print("V857_VALIDATION=PASS")
    print(f"DISTINCT_MARKET_DATES={len(result['dates'])}")
    print(f"MIN_DATE={result['dates'][0]}")
    print(f"MAX_DATE={result['dates'][-1]}")
    print(f"ROWS={result['rows']}")
    print(f"TARGET_TICKERS={result['target_ticker_count']}")
    print(f"CACHE_TICKERS_WITH_ROWS={result['ticker_count_with_rows']}")
    print(f"TICKERS_WITH_260_ROWS={result['tickers_with_260_rows']}")
    print(f"MIN_ROWS_PER_TICKER={result['min_rows_per_ticker']}")
    print(f"MAX_ROWS_PER_TICKER={result['max_rows_per_ticker']}")
    print(f"CACHE_BYTES={result['cache_bytes']}")
    print(f"CACHE_MIB={result['cache_bytes'] / (1024 * 1024):.3f}")
    print_hard_guards()
    return 0


def build(
    root: Path,
    output_dir: Path,
    target_sessions: int,
    timeout: int,
    max_lookback_days: int,
) -> int:
    run_at = now_kst()
    ctx = source_context(root)
    target = ctx["target"]
    target_set = ctx["target_set"]
    t_hash = target_hash(target)

    cache_path = output_dir / DEFAULT_CACHE_NAME
    meta_path = output_dir / DEFAULT_META_NAME
    log_path = output_dir / DEFAULT_LOG_NAME

    meta_old = load_meta(meta_path)

    # Fast no-op path for automatic workflow_run invocations where official
    # universe source and active ticker contract have not changed.
    if cache_path.exists() and meta_old:
        try:
            validated = validate_cache(
                root=root,
                output_dir=output_dir,
                target_sessions=target_sessions,
                require_meta_match=True,
            )
            if (
                meta_old.get("target_ticker_sha256") == t_hash
                and meta_old.get("source_max_date") == ctx["source_max_date"]
            ):
                print("V857_COMPACT_HISTORY_STATUS=READY")
                print("CACHE_REFRESH_NEEDED=false")
                print("REPOSITORY_WRITE_NEEDED=false")
                print(f"TARGET_TICKERS={len(target)}")
                print(f"DISTINCT_MARKET_DATES={len(validated['dates'])}")
                print(f"MIN_DATE={validated['dates'][0]}")
                print(f"MAX_DATE={validated['dates'][-1]}")
                print(f"ROWS={validated['rows']}")
                print(f"CACHE_MIB={validated['cache_bytes'] / (1024 * 1024):.3f}")
                print_hard_guards()
                return 0
        except Exception:
            # Rebuild/repair below; never silently accept invalid cache.
            pass

    auth_key = os.environ.get("KRX_AUTH_KEY", "").strip()
    if not auth_key:
        raise RuntimeError("KRX_AUTH_KEY_MISSING")

    stats = OfficialStats()

    # Existing compact cache contributes older sessions. Current universe
    # history then overrides overlapping keys, so latest official collection
    # remains authoritative for recent dates.
    row_map: Dict[Tuple[str, str, str], dict] = {}

    existing_rows = []
    if cache_path.exists():
        try:
            existing_rows = read_history_rows(cache_path, target_set)
        except Exception:
            existing_rows = []
    row_map.update(rows_to_map(existing_rows))
    row_map.update(rows_to_map(ctx["source_rows"]))

    old_targets = set(meta_old.get("target_tickers") or [])
    new_targets = target_set - old_targets if meta_old else set()

    # If the active ticker set changed, fill the older dates already present
    # in the compact cache for newly active names once. This avoids leaving an
    # established stock with only the recent universe window.
    new_target_backfill_dates = 0
    if new_targets and existing_rows:
        source_min = ctx["source_min_date"]
        older_dates = sorted(
            d for d in date_set(existing_rows)
            if d < source_min
        )
        for ds in older_dates:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            day_rows = fetch_official_day(
                d=d,
                wanted=new_targets,
                auth_key=auth_key,
                timeout=timeout,
                stats=stats,
            )
            for row in day_rows:
                row_map[(row["date"], row["market"], row["ticker"])] = row
            new_target_backfill_dates += 1

    # Initial bootstrap or repair: walk backward from the oldest known market
    # date until the cache contains 260 distinct official market sessions.
    dates = date_set(row_map.values())
    if not dates:
        raise RuntimeError("NO_BASE_HISTORY_ROWS")

    cursor = datetime.strptime(min(dates), "%Y-%m-%d").date() - timedelta(days=1)
    scanned_calendar_days = 0
    backfill_market_dates_added = 0

    while len(dates) < target_sessions and scanned_calendar_days < max_lookback_days:
        if cursor.weekday() < 5:
            day_rows = fetch_official_day(
                d=cursor,
                wanted=target_set,
                auth_key=auth_key,
                timeout=timeout,
                stats=stats,
            )
            if day_rows:
                ds = cursor.isoformat()
                for row in day_rows:
                    row_map[(row["date"], row["market"], row["ticker"])] = row
                if ds not in dates:
                    dates.add(ds)
                    backfill_market_dates_added += 1
        cursor -= timedelta(days=1)
        scanned_calendar_days += 1

    if len(dates) < target_sessions:
        raise RuntimeError(
            f"INSUFFICIENT_OFFICIAL_HISTORY_DATES:{len(dates)}<{target_sessions}"
        )

    row_map = trim_latest_sessions(row_map, target_sessions)
    output_rows = sorted_rows(row_map)
    final_dates = sorted(date_set(output_rows))

    if len(final_dates) != target_sessions:
        raise RuntimeError(
            f"FINAL_DISTINCT_DATE_COUNT_INVALID:{len(final_dates)}!={target_sessions}"
        )
    if final_dates[-1] != ctx["source_max_date"]:
        raise RuntimeError(
            f"FINAL_MAX_DATE_MISMATCH:{final_dates[-1]}!={ctx['source_max_date']}"
        )

    final_tickers = cache_ticker_set(output_rows)
    if not final_tickers.issubset(target_set):
        raise RuntimeError("FINAL_CACHE_CONTAINS_INACTIVE_TICKER")

    cache_bytes = write_cache_atomic(cache_path, output_rows)
    cache_sha = sha256_file(cache_path)

    per_ticker: Dict[str, int] = {}
    for row in output_rows:
        per_ticker[row["ticker"]] = per_ticker.get(row["ticker"], 0) + 1

    counts = list(per_ticker.values())
    tickers_260 = sum(1 for n in counts if n >= target_sessions)
    tickers_240 = sum(1 for n in counts if n >= 240)
    tickers_lt_200 = sum(1 for n in counts if n < 200)

    meta = {
        "script_version": SCRIPT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "generated_at_kst": run_at,
        "status": "READY",
        "source_only": True,
        "request_time_price_eligible": False,
        "source_universe_history": "latest/universe_raw_history_latest.csv",
        "source_min_date": ctx["source_min_date"],
        "source_max_date": ctx["source_max_date"],
        "active_api_files_scanned": ctx["scanned_files"],
        "active_api_file_count": len(ctx["scanned_files"]),
        "raw_active_six_digit_ticker_count": len(ctx["raw_active"]),
        "target_ticker_count": len(target),
        "target_ticker_sha256": t_hash,
        "target_tickers": target,
        "target_sessions": target_sessions,
        "distinct_market_dates": len(final_dates),
        "cache_min_date": final_dates[0],
        "cache_max_date": final_dates[-1],
        "cache_rows": len(output_rows),
        "cache_tickers_with_rows": len(per_ticker),
        "tickers_with_260_rows": tickers_260,
        "tickers_with_at_least_240_rows": tickers_240,
        "tickers_with_less_than_200_rows": tickers_lt_200,
        "min_rows_per_ticker": min(counts) if counts else 0,
        "max_rows_per_ticker": max(counts) if counts else 0,
        "cache_bytes": cache_bytes,
        "cache_mib": round(cache_bytes / (1024 * 1024), 3),
        "cache_sha256": cache_sha,
        "new_active_tickers_since_previous_meta": sorted(new_targets),
        "new_target_backfill_existing_dates_queried": new_target_backfill_dates,
        "backfill_market_dates_added": backfill_market_dates_added,
        "calendar_days_scanned_for_bootstrap": scanned_calendar_days,
        "official_request_stats": stats.as_dict(),
        "hard_guards": {
            "sector_rs_calculated": False,
            "confirmed_swing_low_stop_calculated": False,
            "standalone_swing_metrics_calculated": False,
            "investment_score_100_calculated": False,
            "request_time_price_substitution": False,
        },
    }
    write_json_atomic(meta_path, meta)

    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"CONTRACT_VERSION={CONTRACT_VERSION}",
        f"RUN_AT_KST={run_at}",
        "V857_COMPACT_HISTORY_STATUS=READY",
        "CACHE_REFRESH_NEEDED=true",
        "REPOSITORY_WRITE_NEEDED=true",
        f"SOURCE_MIN_DATE={ctx['source_min_date']}",
        f"SOURCE_MAX_DATE={ctx['source_max_date']}",
        f"ACTIVE_API_FILES_SCANNED={len(ctx['scanned_files'])}",
        f"RAW_ACTIVE_SIX_DIGIT_TICKERS={len(ctx['raw_active'])}",
        f"TARGET_TICKERS={len(target)}",
        f"DISTINCT_MARKET_DATES={len(final_dates)}",
        f"MIN_DATE={final_dates[0]}",
        f"MAX_DATE={final_dates[-1]}",
        f"ROWS={len(output_rows)}",
        f"CACHE_TICKERS_WITH_ROWS={len(per_ticker)}",
        f"TICKERS_WITH_260_ROWS={tickers_260}",
        f"TICKERS_WITH_AT_LEAST_240_ROWS={tickers_240}",
        f"TICKERS_WITH_LESS_THAN_200_ROWS={tickers_lt_200}",
        f"MIN_ROWS_PER_TICKER={min(counts) if counts else 0}",
        f"MAX_ROWS_PER_TICKER={max(counts) if counts else 0}",
        f"CACHE_BYTES={cache_bytes}",
        f"CACHE_MIB={cache_bytes / (1024 * 1024):.3f}",
        f"CACHE_SHA256={cache_sha}",
        f"NEW_ACTIVE_TICKERS={len(new_targets)}",
        f"NEW_TARGET_BACKFILL_EXISTING_DATES_QUERIED={new_target_backfill_dates}",
        f"BACKFILL_MARKET_DATES_ADDED={backfill_market_dates_added}",
        f"CALENDAR_DAYS_SCANNED_FOR_BOOTSTRAP={scanned_calendar_days}",
        f"HTTP_ATTEMPTS={stats.http_attempts}",
        f"HTTP_SUCCESSES={stats.http_successes}",
        f"EMPTY_MARKET_RESPONSES={stats.empty_market_responses}",
        f"TRANSPORT_RETRIES={stats.transport_retries}",
        f"PARTIAL_MARKET_DAY_RETRIES={stats.partial_market_day_retries}",
        f"OFFICIAL_DAYS_WITH_DATA={stats.official_days_with_data}",
        f"OFFICIAL_ROWS_ADDED={stats.official_rows_added}",
        "SOURCE_ONLY=true",
        "REQUEST_TIME_PRICE_ELIGIBLE=false",
        "SECTOR_RS_CALCULATED=false",
        "CONFIRMED_SWING_LOW_STOP_CALCULATED=false",
        "STANDALONE_SWING_METRICS_CALCULATED=false",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
    ]
    write_text_atomic(log_path, "\n".join(log_lines) + "\n")

    # Validate the just-written cache and metadata from disk.
    validated = validate_cache(
        root=root,
        output_dir=output_dir,
        target_sessions=target_sessions,
        require_meta_match=True,
    )

    print("V857_COMPACT_HISTORY_STATUS=READY")
    print("CACHE_REFRESH_NEEDED=true")
    print("REPOSITORY_WRITE_NEEDED=true")
    print(f"TARGET_TICKERS={len(target)}")
    print(f"DISTINCT_MARKET_DATES={len(validated['dates'])}")
    print(f"MIN_DATE={validated['dates'][0]}")
    print(f"MAX_DATE={validated['dates'][-1]}")
    print(f"ROWS={validated['rows']}")
    print(f"TICKERS_WITH_260_ROWS={validated['tickers_with_260_rows']}")
    print(f"MIN_ROWS_PER_TICKER={validated['min_rows_per_ticker']}")
    print(f"MAX_ROWS_PER_TICKER={validated['max_rows_per_ticker']}")
    print(f"CACHE_MIB={validated['cache_bytes'] / (1024 * 1024):.3f}")
    print(f"BACKFILL_MARKET_DATES_ADDED={backfill_market_dates_added}")
    print(f"HTTP_ATTEMPTS={stats.http_attempts}")
    print(f"HTTP_SUCCESSES={stats.http_successes}")
    print_hard_guards()
    return 0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output-dir", default="latest")
    p.add_argument("--target-sessions", type=int, default=260)
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument("--max-lookback-days", type=int, default=500)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--validate-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_sessions < 252:
        raise RuntimeError("TARGET_SESSIONS_TOO_SMALL_FOR_52W_BUFFER")

    if args.self_test:
        return run_self_test()

    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.validate_only:
        return run_validate(root, output_dir, args.target_sessions)

    return build(
        root=root,
        output_dir=output_dir,
        target_sessions=args.target_sessions,
        timeout=args.timeout,
        max_lookback_days=args.max_lookback_days,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"V857_COMPACT_HISTORY_STATUS=FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
