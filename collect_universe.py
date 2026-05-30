#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기 v4.3_simple_summary

핵심 원칙
- KRX Open API 주식 일별매매정보만 사용한다.
- 수집 직후 이미 표준화된 hist에서 곧바로 summary/gainers를 만든다.
- 복잡한 fallback/시장명 재판별을 제거해 0행 요약 문제를 줄인다.
- 새 데이터가 0행이면 기존 정상 CSV를 빈 파일로 덮어쓰지 않는다.

필수 GitHub Secret
- KRX_AUTH_KEY

생성/갱신 파일
- latest/universe_raw_history_latest.csv
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv
- latest/kospi_gainers_1m_latest.csv
- latest/market_index_summary_latest.csv   # 이번 버전은 지수 수집 생략, 기존 파일 보호
- latest/universe_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import os
import re
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

SCRIPT_VERSION = "collect_universe.py v4.3_simple_summary"

OPENAPI_STOCK_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
}

SUMMARY_COLUMNS = [
    "name", "ticker", "market", "status", "last_date",
    "current_close", "split_buy_low_ref", "split_buy_high_ref",
    "target1_ref", "target2_ref", "stop_ref",
    "avg_daily_move_abs", "avg_daily_move_pct", "avg_wave_days",
    "low_3m_intraday", "high_3m_intraday", "low_3m_close", "high_3m_close",
    "range_3m_pct", "position_in_3m_range_pct",
    "return_1m_pct", "return_3m_pct",
    "last_volume", "last_trading_value", "avg20_trading_value",
    "low_liquidity", "market_cap", "listed_shares",
    "data_rows", "source_used",
]


def ymd(d) -> str:
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y%m%d")


def iso(d) -> str:
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def kr_tick_round(x):
    if x is None or pd.isna(x) or float(x) <= 0:
        return None
    x = float(x)
    if x < 2000:
        unit = 1
    elif x < 5000:
        unit = 5
    elif x < 20000:
        unit = 10
    elif x < 50000:
        unit = 50
    elif x < 200000:
        unit = 100
    elif x < 500000:
        unit = 500
    else:
        unit = 1000
    return int(round(x / unit) * unit)


def clean_number(x):
    if x is None or pd.isna(x):
        return np.nan
    s = str(x).strip().replace(",", "").replace("'", "").replace(" ", "")
    if s in ["", "-", "nan", "None"]:
        return np.nan
    return pd.to_numeric(s, errors="coerce")


def normalize_ticker(x) -> str:
    if x is None or pd.isna(x):
        return ""
    s = str(x).strip().replace("'", "")
    if re.fullmatch(r"\d{6}", s):
        return s
    # ISIN 예: KR7005930003 -> 005930
    if s.startswith("KR") and len(s) >= 9:
        cand = s[3:9]
        if re.fullmatch(r"\d{6}", cand):
            return cand
    m = re.search(r"\d{6}", s)
    return m.group(0) if m else ""


def calc_wave_period(close: pd.Series) -> Optional[float]:
    s = pd.Series(close).dropna()
    if len(s) < 10:
        return None
    signs = np.sign(s.diff()).replace(0, np.nan).ffill().dropna()
    if len(signs) < 8:
        return None
    turns = []
    prev = signs.iloc[0]
    for i, val in enumerate(signs.iloc[1:], start=1):
        if val != prev:
            turns.append(i)
        prev = val
    if len(turns) < 2:
        return None
    return round(float(np.mean(np.diff(turns))), 1)


def safe_return_pct(last_close: float, ref_close: Optional[float]) -> Optional[float]:
    if ref_close is None or pd.isna(ref_close) or float(ref_close) <= 0:
        return None
    return round((float(last_close) / float(ref_close) - 1) * 100, 2)


def find_close_on_or_after(g: pd.DataFrame, target_date: pd.Timestamp) -> Optional[float]:
    part = g[g["date"] >= target_date].sort_values("date")
    if part.empty:
        return None
    return float(part["close"].iloc[0])


def empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS)


def request_krx_openapi(url: str, auth_key: str, bas_dd: str, log_lines: List[str], label: str) -> pd.DataFrame:
    try:
        r = requests.get(url, params={"basDd": bas_dd}, headers={"AUTH_KEY": auth_key}, timeout=40)
    except Exception as e:
        log_lines.append(f"OPENAPI_REQUEST_FAIL {label} {bas_dd}: {repr(e)}")
        return pd.DataFrame()

    if r.status_code != 200:
        log_lines.append(f"OPENAPI_HTTP_FAIL {label} {bas_dd}: status={r.status_code}, body={r.text[:200]}")
        return pd.DataFrame()

    try:
        data = r.json()
    except Exception as e:
        log_lines.append(f"OPENAPI_JSON_FAIL {label} {bas_dd}: {repr(e)}, body={r.text[:200]}")
        return pd.DataFrame()

    rows = data.get("OutBlock_1")
    if not rows:
        log_lines.append(f"OPENAPI_EMPTY {label} {bas_dd}: keys={list(data.keys())}")
        return pd.DataFrame()

    return pd.DataFrame(rows)


def normalize_stock_rows(raw: pd.DataFrame, market: str, bas_dd: str, log_lines: List[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    required = ["ISU_CD", "ISU_NM", "TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        log_lines.append(f"NORMALIZE_FAIL {market} {bas_dd}: missing={missing}, cols={list(raw.columns)}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "date": pd.to_datetime(bas_dd, format="%Y%m%d", errors="coerce"),
        "market": market,
        "ticker": raw["ISU_CD"].map(normalize_ticker),
        "name": raw["ISU_NM"].astype(str),
        "open": raw["TDD_OPNPRC"].map(clean_number),
        "high": raw["TDD_HGPRC"].map(clean_number),
        "low": raw["TDD_LWPRC"].map(clean_number),
        "close": raw["TDD_CLSPRC"].map(clean_number),
        "volume": raw.get("ACC_TRDVOL", pd.Series(index=raw.index, dtype=object)).map(clean_number),
        "trading_value": raw.get("ACC_TRDVAL", pd.Series(index=raw.index, dtype=object)).map(clean_number),
        "market_cap": raw.get("MKTCAP", pd.Series(index=raw.index, dtype=object)).map(clean_number),
        "listed_shares": raw.get("LIST_SHRS", pd.Series(index=raw.index, dtype=object)).map(clean_number),
    })

    out = out.dropna(subset=["date", "ticker", "close"])
    out = out[out["ticker"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    return out


def collect_history(start_dt: date, end_dt: date, auth_key: str, log_lines: List[str]) -> pd.DataFrame:
    if not auth_key:
        log_lines.append("KRX_AUTH_KEY_MISSING")
        return pd.DataFrame()

    frames = []
    for d in pd.date_range(start_dt, end_dt, freq="B"):
        bas_dd = ymd(d)
        for market, url in OPENAPI_STOCK_URLS.items():
            raw = request_krx_openapi(url, auth_key, bas_dd, log_lines, f"{market}_stock")
            one = normalize_stock_rows(raw, market, bas_dd, log_lines)
            if not one.empty:
                frames.append(one)
                log_lines.append(f"OPENAPI {market} {bas_dd}: rows={len(one)}")
                print(f"[OPENAPI] {market} {bas_dd}: rows={len(one)}")
            else:
                log_lines.append(f"OPENAPI {market} {bas_dd}: empty after normalize")
                print(f"[OPENAPI_EMPTY] {market} {bas_dd}")
            time.sleep(0.08)

    if not frames:
        return pd.DataFrame()

    hist = pd.concat(frames, ignore_index=True)
    # 중복 방지: 같은 날짜/시장/종목은 마지막 값만 사용
    hist = hist.drop_duplicates(subset=["date", "market", "ticker"], keep="last")
    return hist.sort_values(["market", "ticker", "date"]).reset_index(drop=True)


def build_market_summary(hist: pd.DataFrame, market: str, low_liq_krw: float, log_lines: List[str]) -> pd.DataFrame:
    if hist is None or hist.empty:
        log_lines.append(f"SUMMARY {market}: hist empty")
        return empty_summary()

    df = hist[hist["market"].eq(market)].copy()
    log_lines.append(f"SUMMARY {market}: input rows={len(df)}")
    if df.empty:
        return empty_summary()

    # 혹시 CSV 왕복 후 문자화되어도 다시 숫자형 보정
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = df[col].map(clean_number)

    df = df.dropna(subset=["date", "ticker", "close"])
    df = df[df["ticker"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    df = df.sort_values(["ticker", "date"])
    log_lines.append(f"SUMMARY {market}: cleaned rows={len(df)}, tickers={df['ticker'].nunique() if not df.empty else 0}")

    if df.empty:
        return empty_summary()

    last_date = df["date"].max()
    one_month_ago = last_date - relativedelta(months=1)
    three_months_ago = last_date - relativedelta(months=3)

    rows = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date")
        if g.empty:
            continue

        last = g.iloc[-1]
        last_close = float(last["close"])
        low = float(g["low"].min()) if g["low"].notna().any() else float(g["close"].min())
        high = float(g["high"].max()) if g["high"].notna().any() else float(g["close"].max())
        close_low = float(g["close"].min())
        close_high = float(g["close"].max())
        avg_abs = g["close"].diff().abs().dropna().mean()
        avg_pct = (g["close"].pct_change().abs() * 100).dropna().mean()
        wave = calc_wave_period(g["close"])
        range_pct = ((high - low) / low * 100) if low > 0 else np.nan
        position = ((last_close - low) / (high - low) * 100) if high > low else np.nan
        ref_1m = find_close_on_or_after(g, one_month_ago)
        ref_3m = find_close_on_or_after(g, three_months_ago)
        ret_1m = safe_return_pct(last_close, ref_1m)
        ret_3m = safe_return_pct(last_close, ref_3m)

        price_range = high - low
        move = float(avg_abs) if not pd.isna(avg_abs) and avg_abs > 0 else last_close * 0.03
        if price_range > 0:
            split_low = max(low * 1.01, last_close - move * 2.5)
            split_high = min(last_close * 0.99, last_close - move * 0.3)
            if split_low > split_high:
                split_low = min(last_close * 0.94, low + price_range * 0.45)
                split_high = min(last_close * 0.99, low + price_range * 0.62)
            target1 = min(last_close + move * 2.2, low + price_range * 0.78)
            target2 = min(last_close + move * 4.0, low + price_range * 0.90)
            stop = max(low * 0.97, last_close - move * 3.0)
        else:
            split_low = last_close * 0.94
            split_high = last_close * 0.99
            target1 = last_close * 1.08
            target2 = last_close * 1.15
            stop = last_close * 0.92

        avg20_tv = g["trading_value"].tail(20).mean()
        last_tv = last["trading_value"]
        rows.append({
            "name": str(last.get("name", ticker)),
            "ticker": ticker,
            "market": market,
            "status": "OK",
            "last_date": iso(last_date),
            "current_close": kr_tick_round(last_close),
            "split_buy_low_ref": kr_tick_round(split_low),
            "split_buy_high_ref": kr_tick_round(split_high),
            "target1_ref": kr_tick_round(target1),
            "target2_ref": kr_tick_round(target2),
            "stop_ref": kr_tick_round(stop),
            "avg_daily_move_abs": kr_tick_round(avg_abs) if not pd.isna(avg_abs) else None,
            "avg_daily_move_pct": round(float(avg_pct), 2) if not pd.isna(avg_pct) else None,
            "avg_wave_days": wave,
            "low_3m_intraday": kr_tick_round(low),
            "high_3m_intraday": kr_tick_round(high),
            "low_3m_close": kr_tick_round(close_low),
            "high_3m_close": kr_tick_round(close_high),
            "range_3m_pct": round(float(range_pct), 2) if not pd.isna(range_pct) else None,
            "position_in_3m_range_pct": round(float(position), 2) if not pd.isna(position) else None,
            "return_1m_pct": ret_1m,
            "return_3m_pct": ret_3m,
            "last_volume": int(last["volume"]) if not pd.isna(last["volume"]) else None,
            "last_trading_value": int(last_tv) if not pd.isna(last_tv) else None,
            "avg20_trading_value": int(avg20_tv) if not pd.isna(avg20_tv) else None,
            "low_liquidity": bool(not pd.isna(avg20_tv) and avg20_tv < low_liq_krw),
            "market_cap": int(last["market_cap"]) if not pd.isna(last["market_cap"]) else None,
            "listed_shares": int(last["listed_shares"]) if not pd.isna(last["listed_shares"]) else None,
            "data_rows": int(len(g)),
            "source_used": "krx_openapi_v43",
        })

    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    log_lines.append(f"SUMMARY {market}: output rows={len(out)}")
    if out.empty:
        return empty_summary()
    return out.sort_values(["name", "ticker"]).reset_index(drop=True)


def save_if_not_empty(df: pd.DataFrame, path: Path, log_lines: List[str], label: str) -> None:
    if df is not None and not df.empty:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        log_lines.append(f"{label}={path}, rows={len(df)}")
        print(f"[SAVE] {path} rows={len(df)}")
    else:
        log_lines.append(f"{label} not overwritten: new data rows=0")
        print(f"[SKIP_SAVE] {path} new rows=0")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-months", type=int, default=3)
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD. 생략하면 오늘 기준.")
    args = parser.parse_args()

    load_dotenv()
    auth_key = os.getenv("KRX_AUTH_KEY", "").strip()
    low_liq_krw = float(os.getenv("LOW_LIQUIDITY_KRW", "10000000000"))

    outdir = Path(args.output_dir)
    ensure_dir(outdir)

    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else date.today()
    start_dt = end_dt - relativedelta(months=args.lookback_months)

    log_lines = [
        f"run_at={datetime.now().isoformat(timespec='seconds')}",
        f"period={start_dt.isoformat()}~{end_dt.isoformat()}",
        f"script={SCRIPT_VERSION}",
        f"KRX_AUTH_KEY_present={bool(auth_key)}",
    ]

    try:
        hist = collect_history(start_dt, end_dt, auth_key, log_lines)
        save_if_not_empty(hist, outdir / "universe_raw_history_latest.csv", log_lines, "universe_raw_history")

        kospi = build_market_summary(hist, "KOSPI", low_liq_krw, log_lines)
        kosdaq = build_market_summary(hist, "KOSDAQ", low_liq_krw, log_lines)
        save_if_not_empty(kospi, outdir / "kospi_universe_summary_latest.csv", log_lines, "KOSPI_summary")
        save_if_not_empty(kosdaq, outdir / "kosdaq_universe_summary_latest.csv", log_lines, "KOSDAQ_summary")

        if kospi is not None and not kospi.empty and "return_1m_pct" in kospi.columns:
            gainers = (
                kospi.dropna(subset=["return_1m_pct"])
                .sort_values(["return_1m_pct", "avg20_trading_value"], ascending=[False, False])
                .head(20)
                .reset_index(drop=True)
            )
            if not gainers.empty:
                gainers.insert(0, "rank_1m", range(1, len(gainers) + 1))
        else:
            gainers = pd.DataFrame()
        save_if_not_empty(gainers, outdir / "kospi_gainers_1m_latest.csv", log_lines, "kospi_gainers_1m")

        # 지수 요약은 이번 버전에서 생략한다. 코피/코닥/코급 핵심 파일 성공을 우선한다.
        log_lines.append("market_index_summary skipped in v4.3_simple_summary")
        log_lines.append("DONE universe collection finished")
        print("[DONE] universe collection finished")

    except Exception as e:
        log_lines.append(f"FATAL_ERROR: {repr(e)}")
        log_lines.append(traceback.format_exc())
        print(f"[FATAL_ERROR] {e}")

    finally:
        (outdir / "universe_run_log_latest.txt").write_text("\n".join(log_lines), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
