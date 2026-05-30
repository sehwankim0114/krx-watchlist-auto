#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기 v2

v2 수정점:
- pykrx 전체시장 by_ticker 조회가 GitHub Actions에서 0행으로 끝나는 경우가 있어,
  KRX CSV-OTP 일별 전종목 시세를 우선 사용합니다.
- KOSPI/KOSDAQ 요약이 비어도 kospi_gainers_1m_latest.csv 파일을 빈 파일로라도 생성합니다.
- universe_run_log_latest.txt에 성공/실패 원인을 더 자세히 남깁니다.

생성 파일:
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv
- latest/kospi_gainers_1m_latest.csv
- latest/market_index_summary_latest.csv
- latest/universe_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import io
import os
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np
import pandas as pd
import requests
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


def find_close_on_or_after(g: pd.DataFrame, target_date: pd.Timestamp) -> Optional[float]:
    part = g[g["date"] >= target_date].sort_values("date")
    if part.empty:
        return None
    return float(part["close"].iloc[0])


def clean_number_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace({"": np.nan, "-": np.nan, "nan": np.nan}),
        errors="coerce",
    )


def find_col(columns: List[str], keywords: List[str]) -> Optional[str]:
    for key in keywords:
        for c in columns:
            if key in str(c):
                return c
    return None


def fetch_krx_otp_daily_all(trd_dd: str) -> pd.DataFrame:
    """
    KRX 정보데이터시스템 CSV-OTP 전종목 일별시세.
    KRX 화면 구조 변경/접속차단 시 실패할 수 있습니다.
    """
    session = requests.Session()
    gen_url = "https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
    down_url = "https://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
    }
    payload = {
        "locale": "ko_KR",
        "mktId": "ALL",
        "trdDd": trd_dd,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
        "name": "fileDown",
        "url": "dbms/MDC/STAT/standard/MDCSTAT01501",
    }
    otp = session.post(gen_url, data=payload, headers=headers, timeout=20).text
    if not otp or len(otp) < 10:
        raise RuntimeError(f"OTP 생성 실패: {trd_dd}, response={otp[:80]}")
    r = session.post(down_url, data={"code": otp}, headers=headers, timeout=40)
    r.raise_for_status()
    try:
        return pd.read_csv(io.BytesIO(r.content), encoding="cp949")
    except Exception:
        return pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig")


def normalize_krx_daily(raw: pd.DataFrame, trd_dd: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    cols = list(raw.columns)

    code_col = find_col(cols, ["종목코드", "단축코드"])
    name_col = find_col(cols, ["종목명", "한글 종목명", "한글종목명"])
    market_col = find_col(cols, ["시장구분", "시장", "MKT"])
    open_col = find_col(cols, ["시가"])
    high_col = find_col(cols, ["고가"])
    low_col = find_col(cols, ["저가"])
    close_col = find_col(cols, ["종가"])
    volume_col = find_col(cols, ["거래량"])
    trading_value_col = find_col(cols, ["거래대금"])
    market_cap_col = find_col(cols, ["시가총액"])
    shares_col = find_col(cols, ["상장주식수"])

    if code_col is None or close_col is None:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(trd_dd)
    out["ticker"] = raw[code_col].astype(str).str.replace("'", "", regex=False).str.zfill(6)
    out["name"] = raw[name_col].astype(str) if name_col else out["ticker"]

    if market_col:
        m = raw[market_col].astype(str)
        out["market"] = np.where(
            m.str.contains("KOSDAQ|코스닥", case=False, na=False),
            "KOSDAQ",
            np.where(m.str.contains("KOSPI|유가", case=False, na=False), "KOSPI", m),
        )
    else:
        out["market"] = ""

    for source_col, dest_col in [
        (open_col, "open"),
        (high_col, "high"),
        (low_col, "low"),
        (close_col, "close"),
        (volume_col, "volume"),
        (trading_value_col, "trading_value"),
        (market_cap_col, "market_cap"),
        (shares_col, "listed_shares"),
    ]:
        if source_col:
            out[dest_col] = clean_number_series(raw[source_col])
        else:
            out[dest_col] = np.nan

    # 우선주, ETF 등도 원자료에는 섞일 수 있으나 코피표/코닥표 후보군 필터는 ChatGPT 분석단에서 보완합니다.
    return out.dropna(subset=["close"])


def collect_history_by_otp(start_dt: date, end_dt: date, log_lines: List[str]) -> pd.DataFrame:
    frames = []
    for d in pd.date_range(start_dt, end_dt, freq="B"):
        ds = ymd(d)
        try:
            raw = fetch_krx_otp_daily_all(ds)
            one = normalize_krx_daily(raw, ds)
            if not one.empty:
                frames.append(one)
                log_lines.append(f"OTP {ds}: rows={len(one)}")
                print(f"[OTP] {ds}: rows={len(one)}")
            else:
                log_lines.append(f"OTP {ds}: empty after normalize")
                print(f"[OTP_EMPTY] {ds}")
        except Exception as e:
            log_lines.append(f"OTP_FAIL {ds}: {repr(e)}")
            print(f"[OTP_FAIL] {ds}: {e}")
        time.sleep(0.15)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def collect_history_by_pykrx_fallback(start_dt: date, end_dt: date, log_lines: List[str]) -> pd.DataFrame:
    """
    OTP가 모두 실패한 경우의 보조 방식.
    이전 v1과 같은 전체시장 by_ticker 방식이지만, 로그를 자세히 남깁니다.
    """
    try:
        from pykrx import stock
    except Exception as e:
        log_lines.append(f"PYKRX_IMPORT_FAIL: {repr(e)}")
        return pd.DataFrame()

    frames = []
    for market in ["KOSPI", "KOSDAQ"]:
        for d in pd.date_range(start_dt, end_dt, freq="B"):
            ds = ymd(d)
            try:
                raw = stock.get_market_ohlcv_by_ticker(ds, market=market)
                if raw is None or raw.empty:
                    log_lines.append(f"PYKRX {market} {ds}: empty")
                    continue
                df = raw.copy()
                df.index = df.index.astype(str).str.zfill(6)
                df = df.reset_index().rename(columns={"티커": "ticker", "index": "ticker"})
                if "ticker" not in df.columns:
                    df = df.rename(columns={df.columns[0]: "ticker"})

                colmap = {
                    "시가": "open",
                    "고가": "high",
                    "저가": "low",
                    "종가": "close",
                    "거래량": "volume",
                    "거래대금": "trading_value",
                }
                df = df.rename(columns={c: colmap.get(c, c) for c in df.columns})
                for col in ["open", "high", "low", "close", "volume", "trading_value"]:
                    if col not in df.columns:
                        df[col] = np.nan
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                df["date"] = pd.to_datetime(ds)
                df["market"] = market
                df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                try:
                    df["name"] = df["ticker"].map(lambda x: stock.get_market_ticker_name(x))
                except Exception:
                    df["name"] = df["ticker"]

                df["market_cap"] = np.nan
                df["listed_shares"] = np.nan
                frames.append(df[["date", "market", "ticker", "name", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]])
                log_lines.append(f"PYKRX {market} {ds}: rows={len(df)}")
            except Exception as e:
                log_lines.append(f"PYKRX_FAIL {market} {ds}: {repr(e)}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def summarize_market(hist: pd.DataFrame, market: str, low_liq_krw: float) -> pd.DataFrame:
    if hist is None or hist.empty:
        return empty_summary_columns()

    df = hist[hist["market"].eq(market)].copy()
    if df.empty:
        return empty_summary_columns()

    df = df.dropna(subset=["close"]).sort_values(["ticker", "date"])
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
        last_name = str(last["name"]) if "name" in g.columns else ticker

        rows.append({
            "name": last_name,
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
            "market_cap": int(last["market_cap"]) if "market_cap" in g.columns and not pd.isna(last["market_cap"]) else None,
            "listed_shares": int(last["listed_shares"]) if "listed_shares" in g.columns and not pd.isna(last["listed_shares"]) else None,
            "data_rows": int(len(g)),
            "source_used": "krx_otp_or_pykrx",
        })

    if not rows:
        return empty_summary_columns()
    return pd.DataFrame(rows).sort_values(["name", "ticker"]).reset_index(drop=True)


def empty_summary_columns() -> pd.DataFrame:
    cols = [
        "name", "ticker", "market", "status", "last_date", "current_close",
        "split_buy_ref", "target1_ref", "stop_ref", "avg_daily_move_abs",
        "avg_daily_move_pct", "avg_wave_days", "low_3m_intraday",
        "high_3m_intraday", "low_3m_close", "high_3m_close",
        "range_3m_pct", "position_in_3m_range_pct", "return_1m_pct",
        "return_3m_pct", "last_volume", "last_trading_value",
        "avg20_trading_value", "low_liquidity", "market_cap",
        "listed_shares", "data_rows", "source_used"
    ]
    return pd.DataFrame(columns=cols)


def collect_index_summary(start_dt: date, end_dt: date, log_lines: List[str]) -> pd.DataFrame:
    try:
        from pykrx import stock
    except Exception as e:
        log_lines.append(f"INDEX_PYKRX_IMPORT_FAIL: {repr(e)}")
        return pd.DataFrame(columns=["index_name", "index_code", "last_date", "current_close", "low_3m", "high_3m", "range_3m_pct", "return_1m_pct", "return_3m_pct", "avg_daily_move_pct", "data_rows", "source_used"])

    index_map = {
        "KOSPI": "1001",
        "KOSDAQ": "2001",
        "KOSPI200": "1028",
    }
    rows = []
    for name, code in index_map.items():
        try:
            idx = stock.get_index_ohlcv_by_date(ymd(start_dt), ymd(end_dt), code)
            if idx is None or idx.empty:
                log_lines.append(f"INDEX {name}: empty")
                continue
            idx = idx.copy().sort_index().rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "trading_value"})
            last = float(idx["close"].iloc[-1])
            low = float(idx["low"].min()) if "low" in idx.columns else float(idx["close"].min())
            high = float(idx["high"].max()) if "high" in idx.columns else float(idx["close"].max())
            avg_pct = (idx["close"].pct_change().abs() * 100).dropna().mean()
            idx_reset = idx.reset_index(names="date")
            ref_1m = find_close_on_or_after(idx_reset, pd.Timestamp(idx.index[-1]) - relativedelta(months=1))
            rows.append({
                "index_name": name,
                "index_code": code,
                "last_date": iso(idx.index[-1]),
                "current_close": round(last, 2),
                "low_3m": round(low, 2),
                "high_3m": round(high, 2),
                "range_3m_pct": round((high - low) / low * 100, 2) if low else None,
                "return_1m_pct": safe_return_pct(last, ref_1m),
                "return_3m_pct": safe_return_pct(last, float(idx["close"].iloc[0])),
                "avg_daily_move_pct": round(float(avg_pct), 2) if not pd.isna(avg_pct) else None,
                "data_rows": len(idx),
                "source_used": "pykrx",
            })
        except Exception as e:
            log_lines.append(f"INDEX_FAIL {name}: {repr(e)}")
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
        "script=collect_universe.py v2",
    ]

    hist = collect_history_by_otp(start_dt, end_dt, log_lines)
    if hist.empty:
        log_lines.append("OTP 전체 실패 또는 0행. pykrx fallback 시작.")
        hist = collect_history_by_pykrx_fallback(start_dt, end_dt, log_lines)

    # 원자료 저장
    try:
        hist.to_csv(outdir / "universe_raw_history_latest.csv", index=False, encoding="utf-8-sig")
        log_lines.append(f"universe_raw_history rows={len(hist)}")
    except Exception as e:
        log_lines.append(f"RAW_SAVE_FAIL: {repr(e)}")

    kospi = summarize_market(hist, "KOSPI", low_liq_krw)
    kosdaq = summarize_market(hist, "KOSDAQ", low_liq_krw)

    kospi_path = outdir / "kospi_universe_summary_latest.csv"
    kosdaq_path = outdir / "kosdaq_universe_summary_latest.csv"
    kospi.to_csv(kospi_path, index=False, encoding="utf-8-sig")
    kosdaq.to_csv(kosdaq_path, index=False, encoding="utf-8-sig")
    log_lines.append(f"KOSPI_summary={kospi_path}, rows={len(kospi)}")
    log_lines.append(f"KOSDAQ_summary={kosdaq_path}, rows={len(kosdaq)}")
    print(f"[SAVE] {kospi_path} rows={len(kospi)}")
    print(f"[SAVE] {kosdaq_path} rows={len(kosdaq)}")

    # 코급표용 최근 1개월 상승률 상위 20개. 비어도 파일은 반드시 생성.
    gainers_cols = list(kospi.columns)
    if "rank_1m" not in gainers_cols:
        gainers_cols = ["rank_1m"] + gainers_cols

    if not kospi.empty and "return_1m_pct" in kospi.columns:
        gainers = (
            kospi.dropna(subset=["return_1m_pct"])
            .sort_values(["return_1m_pct", "avg20_trading_value"], ascending=[False, False])
            .head(20)
            .reset_index(drop=True)
        )
        gainers.insert(0, "rank_1m", range(1, len(gainers) + 1))
    else:
        gainers = pd.DataFrame(columns=gainers_cols)

    gainers_path = outdir / "kospi_gainers_1m_latest.csv"
    gainers.to_csv(gainers_path, index=False, encoding="utf-8-sig")
    log_lines.append(f"kospi_gainers_1m={gainers_path}, rows={len(gainers)}")
    print(f"[SAVE] {gainers_path} rows={len(gainers)}")

    idx = collect_index_summary(start_dt, end_dt, log_lines)
    idx_path = outdir / "market_index_summary_latest.csv"
    idx.to_csv(idx_path, index=False, encoding="utf-8-sig")
    log_lines.append(f"market_index_summary={idx_path}, rows={len(idx)}")
    print(f"[SAVE] {idx_path} rows={len(idx)}")

    (outdir / "universe_run_log_latest.txt").write_text("\n".join(log_lines), encoding="utf-8")
    print("[DONE] universe collection finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
