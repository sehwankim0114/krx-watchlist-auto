#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기

생성 파일:
- latest/kospi_universe_summary_latest.csv       : 코피표용 코스피 전체 요약
- latest/kosdaq_universe_summary_latest.csv      : 코닥표/코종표용 코스닥 전체 요약
- latest/kospi_gainers_1m_latest.csv             : 코급표용 최근 1개월 코스피 상승률 상위 20개
- latest/market_index_summary_latest.csv         : 시장환경용 지수 요약

주의:
- 이 파일은 관종표 원자료가 아니라, 코피표/코닥표/코급표 원자료를 만드는 보조 스크립트입니다.
- GitHub Actions에서 실행되도록 만들었습니다.
"""

from __future__ import annotations

import argparse
import os
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv


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
    if x is None or pd.isna(x) or x <= 0:
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


def calc_wave_period(close: pd.Series) -> Optional[float]:
    s = pd.Series(close).dropna()
    if len(s) < 10:
        return None
    diff = s.diff().dropna()
    signs = np.sign(diff).replace(0, np.nan).ffill().dropna()
    if len(signs) < 8:
        return None
    turning = []
    prev = signs.iloc[0]
    for i, val in enumerate(signs.iloc[1:], start=1):
        if val != prev:
            turning.append(i)
            prev = val
    if len(turning) < 2:
        return None
    return round(float(np.mean(np.diff(turning))), 1)


def safe_return_pct(last_close: float, ref_close: Optional[float]) -> Optional[float]:
    if ref_close is None or pd.isna(ref_close) or ref_close <= 0:
        return None
    return round((float(last_close) / float(ref_close) - 1) * 100, 2)


def find_close_on_or_after(df: pd.DataFrame, target_date: pd.Timestamp) -> Optional[float]:
    part = df[df["date"] >= target_date].sort_values("date")
    if part.empty:
        return None
    return float(part["close"].iloc[0])


def normalize_ohlcv_by_ticker(raw: pd.DataFrame, market: str, run_date: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df.index = df.index.astype(str).str.zfill(6)
    df = df.reset_index().rename(columns={"티커": "ticker", "index": "ticker"})
    if "ticker" not in df.columns:
        first = df.columns[0]
        df = df.rename(columns={first: "ticker"})

    colmap = {
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
        "거래대금": "trading_value",
        "등락률": "change_pct",
    }
    df = df.rename(columns={c: colmap.get(c, c) for c in df.columns})

    for col in ["open", "high", "low", "close", "volume", "trading_value", "change_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["open", "high", "low", "close", "volume", "trading_value"]:
        if col not in df.columns:
            df[col] = np.nan

    df["date"] = pd.to_datetime(run_date)
    df["market"] = market
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    return df[["date", "market", "ticker", "open", "high", "low", "close", "volume", "trading_value"]]


def collect_market_history(market: str, start_dt: date, end_dt: date) -> pd.DataFrame:
    from pykrx import stock

    frames = []
    for d in pd.date_range(start_dt, end_dt, freq="B"):
        ds = ymd(d)
        try:
            raw = stock.get_market_ohlcv_by_ticker(ds, market=market)
            one = normalize_ohlcv_by_ticker(raw, market, ds)
            if not one.empty:
                frames.append(one)
                print(f"[{market}] {ds}: {len(one)} rows")
        except Exception as e:
            print(f"[SKIP] {market} {ds}: {e}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def add_market_cap(summary: pd.DataFrame, market: str, last_date: str) -> pd.DataFrame:
    from pykrx import stock

    try:
        cap = stock.get_market_cap_by_ticker(last_date, market=market)
        if cap is None or cap.empty:
            return summary
        cap = cap.copy()
        cap.index = cap.index.astype(str).str.zfill(6)
        cap = cap.reset_index().rename(columns={"티커": "ticker", "index": "ticker"})
        if "ticker" not in cap.columns:
            first = cap.columns[0]
            cap = cap.rename(columns={first: "ticker"})
        keep = ["ticker"]
        rename = {}
        for c in cap.columns:
            if c == "시가총액":
                rename[c] = "market_cap"
                keep.append(c)
            elif c == "상장주식수":
                rename[c] = "listed_shares"
                keep.append(c)
        cap = cap[keep].rename(columns=rename)
        cap["ticker"] = cap["ticker"].astype(str).str.zfill(6)
        return summary.merge(cap, on="ticker", how="left")
    except Exception as e:
        print(f"[WARN] market cap failed {market} {last_date}: {e}")
        return summary


def summarize_market(hist: pd.DataFrame, market: str, low_liq_krw: float) -> pd.DataFrame:
    from pykrx import stock

    if hist is None or hist.empty:
        return pd.DataFrame()

    hist = hist.dropna(subset=["close"]).copy()
    hist = hist.sort_values(["ticker", "date"])
    last_date = hist["date"].max()
    start_date = hist["date"].min()
    one_month_ago = last_date - relativedelta(months=1)
    three_months_ago = last_date - relativedelta(months=3)

    rows = []
    for ticker, g in hist.groupby("ticker", sort=False):
        g = g.sort_values("date")
        last = g.iloc[-1]
        last_close = float(last["close"])
        low = float(g["low"].min()) if g["low"].notna().any() else float(g["close"].min())
        high = float(g["high"].max()) if g["high"].notna().any() else float(g["close"].max())
        close_low = float(g["close"].min())
        close_high = float(g["close"].max())

        avg_abs = (g["close"].diff().abs()).dropna().mean()
        avg_pct = (g["close"].pct_change().abs() * 100).dropna().mean()
        wave = calc_wave_period(g["close"])

        range_pct = ((high - low) / low * 100) if low else np.nan
        position = ((last_close - low) / (high - low) * 100) if high > low else np.nan

        ref_1m = find_close_on_or_after(g, one_month_ago)
        ref_3m = find_close_on_or_after(g, three_months_ago)
        ret_1m = safe_return_pct(last_close, ref_1m)
        ret_3m = safe_return_pct(last_close, ref_3m)

        price_range = high - low
        if price_range > 0:
            split_buy = min(last_close * 0.97, low + price_range * 0.38)
            target1 = min(last_close + (avg_abs if not pd.isna(avg_abs) else last_close * 0.03) * 2.2,
                          low + price_range * 0.78)
            stop = max(low * 0.97, last_close - (avg_abs if not pd.isna(avg_abs) else last_close * 0.03) * 3.0)
        else:
            split_buy, target1, stop = last_close * 0.97, last_close * 1.08, last_close * 0.92

        avg20_tv = g["trading_value"].tail(20).mean()
        last_tv = last["trading_value"]

        try:
            name = stock.get_market_ticker_name(ticker)
        except Exception:
            name = ticker

        rows.append({
            "name": name,
            "ticker": ticker,
            "market": market,
            "status": "OK",
            "last_date": iso(last_date),
            "current_close": kr_tick_round(last_close),
            "split_buy_ref": kr_tick_round(split_buy),
            "target1_ref": kr_tick_round(target1),
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
            "data_rows": int(len(g)),
            "source_used": "pykrx",
        })

    out = pd.DataFrame(rows).sort_values(["name", "ticker"]).reset_index(drop=True)
    out = add_market_cap(out, market, ymd(last_date))
    return out


def collect_index_summary(start_dt: date, end_dt: date) -> pd.DataFrame:
    from pykrx import stock

    # 대표 지수 코드. pykrx 환경에 따라 일부 지수는 실패할 수 있으므로 성공한 것만 저장합니다.
    index_map = {
        "KOSPI": "1001",
        "KOSDAQ": "2001",
        "KOSPI200": "1028",
    }

    rows = []
    for name, code in index_map.items():
        try:
            df = stock.get_index_ohlcv_by_date(ymd(start_dt), ymd(end_dt), code)
            if df is None or df.empty:
                continue
            df = df.copy().sort_index()
            df = df.rename(columns={
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "trading_value",
            })
            last = float(df["close"].iloc[-1])
            low = float(df["low"].min()) if "low" in df.columns else float(df["close"].min())
            high = float(df["high"].max()) if "high" in df.columns else float(df["close"].max())
            avg_pct = (df["close"].pct_change().abs() * 100).dropna().mean()
            ret_1m = safe_return_pct(last, find_close_on_or_after(df.reset_index(names="date"), pd.Timestamp(df.index[-1]) - relativedelta(months=1)))
            ret_3m = safe_return_pct(last, float(df["close"].iloc[0]))
            rows.append({
                "index_name": name,
                "index_code": code,
                "last_date": iso(df.index[-1]),
                "current_close": round(last, 2),
                "low_3m": round(low, 2),
                "high_3m": round(high, 2),
                "range_3m_pct": round((high - low) / low * 100, 2) if low else None,
                "return_1m_pct": ret_1m,
                "return_3m_pct": ret_3m,
                "avg_daily_move_pct": round(float(avg_pct), 2) if not pd.isna(avg_pct) else None,
                "data_rows": len(df),
                "source_used": "pykrx",
            })
        except Exception as e:
            print(f"[INDEX_SKIP] {name}: {e}")

    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-months", type=int, default=3)
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD. 생략하면 오늘 기준.")
    args = parser.parse_args()

    load_dotenv()
    low_liq_krw = float(os.getenv("LOW_LIQUIDITY_KRW", "10000000000"))

    outdir = Path(args.output_dir)
    ensure_dir(outdir)

    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else date.today()
    start_dt = end_dt - relativedelta(months=args.lookback_months)

    log_lines = [
        f"run_at={datetime.now().isoformat(timespec='seconds')}",
        f"period={start_dt.isoformat()}~{end_dt.isoformat()}",
        "script=collect_universe.py",
    ]

    results = {}
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            hist = collect_market_history(market, start_dt, end_dt)
            raw_file = outdir / f"{market.lower()}_raw_history_latest.csv"
            hist.to_csv(raw_file, index=False, encoding="utf-8-sig")
            summary = summarize_market(hist, market, low_liq_krw)
            results[market] = summary

            if market == "KOSPI":
                path = outdir / "kospi_universe_summary_latest.csv"
            else:
                path = outdir / "kosdaq_universe_summary_latest.csv"
            summary.to_csv(path, index=False, encoding="utf-8-sig")
            log_lines.append(f"{market}_summary={path}, rows={len(summary)}")
            print(f"[SAVE] {path} rows={len(summary)}")

        except Exception as e:
            err = traceback.format_exc(limit=3)
            log_lines.append(f"[ERROR] {market}: {repr(e)}\n{err}")
            print(f"[ERROR] {market}: {e}")

    # 코급표용: 코스피 최근 1개월 상승률 상위 20개
    try:
        kospi = results.get("KOSPI", pd.DataFrame())
        if not kospi.empty and "return_1m_pct" in kospi.columns:
            gainers = (
                kospi.dropna(subset=["return_1m_pct"])
                .sort_values(["return_1m_pct", "avg20_trading_value"], ascending=[False, False])
                .head(20)
                .reset_index(drop=True)
            )
            gainers.insert(0, "rank_1m", range(1, len(gainers) + 1))
            path = outdir / "kospi_gainers_1m_latest.csv"
            gainers.to_csv(path, index=False, encoding="utf-8-sig")
            log_lines.append(f"kospi_gainers_1m={path}, rows={len(gainers)}")
            print(f"[SAVE] {path} rows={len(gainers)}")
    except Exception as e:
        log_lines.append(f"[ERROR] gainers: {repr(e)}")

    # 시장지수 요약
    try:
        idx = collect_index_summary(start_dt, end_dt)
        path = outdir / "market_index_summary_latest.csv"
        idx.to_csv(path, index=False, encoding="utf-8-sig")
        log_lines.append(f"market_index_summary={path}, rows={len(idx)}")
        print(f"[SAVE] {path} rows={len(idx)}")
    except Exception as e:
        log_lines.append(f"[ERROR] index: {repr(e)}")

    (outdir / "universe_run_log_latest.txt").write_text("\n".join(log_lines), encoding="utf-8")
    print("[DONE] universe collection finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
