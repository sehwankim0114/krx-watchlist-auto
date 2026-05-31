#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
관종표·분석표용 KRX/미국 시세 자동 수집기
v4.7_return_anomaly_flag

주요 기능
- 국내: pykrx를 우선 사용합니다. pykrx 실패 시 KRX CSV-OTP 최신 일별시세 수집을 보조로 사용할 수 있습니다.
- 미국: yfinance를 사용합니다.
- 관종표/분석표 원자료에 상승률 이상치 경고 컬럼을 추가합니다.

산출물
- outputs/watchlist_summary_YYYYMMDD.csv
- outputs/watchlist_summary_latest.csv
- outputs/raw_history_YYYYMMDD.csv
- outputs/raw_history_latest.csv
- outputs/run_log_latest.txt
- outputs/watchlist_latest.xlsx

주의
- 투자 판단 자동화 도구가 아니라, 관종표 작성을 위한 원자료 수집/요약 도구입니다.
- KRX CSV-OTP 방식은 KRX 화면 구조 변경/세션/차단에 따라 실패할 수 있습니다.
"""

from __future__ import annotations

import argparse
import io
import os
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return False


SCRIPT_VERSION = "collect_watchlist.py v4.7_return_anomaly_flag"

SUMMARY_COLUMNS = [
    "name",
    "ticker",
    "country",
    "currency",
    "exchange",
    "status",
    "last_date",
    "current_close",
    "split_buy_ref",
    "target1_ref",
    "stop_ref",
    "avg_daily_move_abs",
    "avg_daily_move_pct",
    "avg_wave_days",
    "low_3m_intraday",
    "high_3m_intraday",
    "low_3m_close",
    "high_3m_close",
    "range_3m_pct",
    "position_in_3m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "return_anomaly_flag",
    "return_anomaly_reason",
    "last_volume",
    "last_trading_value",
    "avg20_trading_value",
    "low_liquidity",
    "foreign_net_5d_value",
    "foreign_net_20d_value",
    "foreign_net_60d_value",
    "institution_net_5d_value",
    "institution_net_20d_value",
    "institution_net_60d_value",
    "data_rows",
    "source_used",
    "error",
]


# -----------------------------------------------------------------------------
# 기본 유틸
# -----------------------------------------------------------------------------


def ymd(d: date | datetime | pd.Timestamp) -> str:
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y%m%d")


def iso(d: date | datetime | pd.Timestamp) -> str:
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def clean_number(x):
    if x is None or pd.isna(x):
        return np.nan
    s = str(x).strip().replace(",", "").replace("'", "").replace(" ", "")
    if s in ["", "-", "nan", "None", "NaN"]:
        return np.nan
    return pd.to_numeric(s, errors="coerce")


def safe_float(x, default=np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def kr_tick_round(x: float) -> Optional[int]:
    if x is None or pd.isna(x) or x <= 0:
        return None
    x = float(x)
    if x < 2_000:
        unit = 1
    elif x < 5_000:
        unit = 5
    elif x < 20_000:
        unit = 10
    elif x < 50_000:
        unit = 50
    elif x < 200_000:
        unit = 100
    elif x < 500_000:
        unit = 500
    else:
        unit = 1_000
    return int(round(x / unit) * unit)


def us_round(x: float) -> Optional[float]:
    if x is None or pd.isna(x) or x <= 0:
        return None
    return round(float(x), 2)


def calc_wave_period(close: pd.Series) -> Optional[float]:
    """종가 방향 전환점 간 평균 일수. 자료가 부족하면 None."""
    s = pd.Series(close).dropna()
    if len(s) < 10:
        return None
    diff = s.diff().dropna()
    signs = np.sign(diff).replace(0, np.nan).ffill().dropna()
    if len(signs) < 8:
        return None

    turning_idx = []
    prev = signs.iloc[0]
    for i, val in enumerate(signs.iloc[1:], start=1):
        if val != prev:
            turning_idx.append(i)
            prev = val

    if len(turning_idx) < 2:
        return None

    gaps = np.diff(turning_idx)
    if len(gaps) == 0:
        return None
    return round(float(np.mean(gaps)), 1)


def safe_pct(a: float, b: float) -> Optional[float]:
    if b is None or pd.isna(b) or b == 0:
        return None
    return round((float(a) / float(b)) * 100, 2)


def safe_return_pct(last_close: float, ref_close: Optional[float]) -> Optional[float]:
    if ref_close is None or pd.isna(ref_close) or float(ref_close) <= 0:
        return None
    return round((float(last_close) / float(ref_close) - 1.0) * 100.0, 2)


def find_close_on_or_after(df: pd.DataFrame, target_date: pd.Timestamp) -> Optional[float]:
    if df is None or df.empty or "close" not in df.columns:
        return None
    target_date = pd.Timestamp(target_date)
    part = df[df.index >= target_date].sort_index()
    if part.empty:
        return None
    value = part["close"].iloc[0]
    if pd.isna(value):
        return None
    return float(value)


def detect_return_anomaly(return_1m_pct, return_3m_pct, data_rows: int) -> Tuple[bool, str]:
    """
    관종표/분석표용 상승률 이상치 경고.
    관종표는 사용자가 지정한 종목을 유지해야 하므로 제외하지 않고 경고 컬럼만 남긴다.
    """
    reasons: List[str] = []
    r1 = safe_float(return_1m_pct)
    r3 = safe_float(return_3m_pct)
    rows = int(data_rows) if data_rows is not None and not pd.isna(data_rows) else 0

    if rows < 40:
        reasons.append(f"3개월 데이터 부족 {rows}행")

    if not pd.isna(r1):
        if r1 > 300:
            reasons.append(f"1개월 수익률 이상치 +{r1:.2f}%")
        elif r1 < -80:
            reasons.append(f"1개월 수익률 급락 이상치 {r1:.2f}%")

    if not pd.isna(r3):
        if r3 > 500:
            reasons.append(f"3개월 수익률 이상치 +{r3:.2f}%")
        elif r3 < -90:
            reasons.append(f"3개월 수익률 급락 이상치 {r3:.2f}%")

    return bool(reasons), "; ".join(reasons)


def reorder_summary_columns(summary: pd.DataFrame) -> pd.DataFrame:
    if summary is None or summary.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    df = summary.copy()
    for col in SUMMARY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    extra_cols = [c for c in df.columns if c not in SUMMARY_COLUMNS]
    return df[SUMMARY_COLUMNS + extra_cols]


# -----------------------------------------------------------------------------
# 요약 산출
# -----------------------------------------------------------------------------


def summarize_history(
    name: str,
    ticker: str,
    country: str,
    currency: str,
    exchange: str,
    hist: pd.DataFrame,
    flow: Optional[pd.DataFrame] = None,
    low_liq_krw: float = 10_000_000_000,
    low_liq_usd: float = 50_000_000,
) -> Dict:
    """표준 OHLCV 데이터에서 관종표 기초 요약값 생성."""
    if hist is None or hist.empty:
        return {
            "name": name,
            "ticker": ticker,
            "country": country,
            "currency": currency,
            "exchange": exchange,
            "status": "NO_DATA",
            "error": "history empty",
            "source_used": SCRIPT_VERSION,
        }

    df = hist.copy()
    df = df.sort_index()

    # 컬럼 표준화
    colmap = {}
    for c in df.columns:
        cs = str(c).lower()
        if c in ["시가", "Open"] or cs == "open":
            colmap[c] = "open"
        elif c in ["고가", "High"] or cs == "high":
            colmap[c] = "high"
        elif c in ["저가", "Low"] or cs == "low":
            colmap[c] = "low"
        elif c in ["종가", "Close"] or cs == "close":
            colmap[c] = "close"
        elif c in ["거래량", "Volume"] or cs == "volume":
            colmap[c] = "volume"
        elif c in ["거래대금", "Amount"] or cs in ["amount", "trading_value"]:
            colmap[c] = "trading_value"
    df = df.rename(columns=colmap)

    if "close" not in df.columns:
        return {
            "name": name,
            "ticker": ticker,
            "country": country,
            "currency": currency,
            "exchange": exchange,
            "status": "NO_CLOSE",
            "error": f"columns={list(hist.columns)}",
            "source_used": SCRIPT_VERSION,
        }

    for col in ["open", "high", "low", "close", "volume", "trading_value"]:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = df[col].map(clean_number)

    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].copy()
    df = df.dropna(subset=["close"])
    if df.empty:
        return {
            "name": name,
            "ticker": ticker,
            "country": country,
            "currency": currency,
            "exchange": exchange,
            "status": "NO_CLOSE_ROWS",
            "error": "close rows empty",
            "source_used": SCRIPT_VERSION,
        }

    last_date = df.index[-1]
    current = float(df["close"].iloc[-1])
    low = float(df["low"].dropna().min()) if not df["low"].dropna().empty else float(df["close"].min())
    high = float(df["high"].dropna().max()) if not df["high"].dropna().empty else float(df["close"].max())
    close_low = float(df["close"].min())
    close_high = float(df["close"].max())

    prev_close = df["close"].shift(1)
    abs_move = (df["close"] - prev_close).abs().dropna()
    pct_move = (df["close"].pct_change().abs() * 100).dropna()
    avg_abs_move = float(abs_move.mean()) if not abs_move.empty else np.nan
    avg_pct_move = float(pct_move.mean()) if not pct_move.empty else np.nan

    range_pct = ((high - low) / low * 100) if low else np.nan
    position_pct = ((current - low) / (high - low) * 100) if high > low else np.nan
    wave = calc_wave_period(df["close"])

    # 신규: 1개월/3개월 수익률과 이상치 경고
    one_month_ago = pd.Timestamp(last_date) - relativedelta(months=1)
    three_months_ago = pd.Timestamp(last_date) - relativedelta(months=3)
    ref_1m = find_close_on_or_after(df, one_month_ago)
    ref_3m = find_close_on_or_after(df, three_months_ago)
    return_1m_pct = safe_return_pct(current, ref_1m)
    return_3m_pct = safe_return_pct(current, ref_3m)
    return_anomaly_flag, return_anomaly_reason = detect_return_anomaly(
        return_1m_pct,
        return_3m_pct,
        len(df),
    )

    # 단순 산정값: ChatGPT 관종표에서 최종 판단 전 원자료 기준점으로 사용
    price_range = high - low
    if price_range > 0:
        split_buy = min(current * 0.97, low + price_range * 0.38)
        target1 = min(
            current + avg_abs_move * 2.2 if not pd.isna(avg_abs_move) else current * 1.08,
            low + price_range * 0.78,
        )
        stop = max(
            low * 0.97,
            current - avg_abs_move * 3.0 if not pd.isna(avg_abs_move) else current * 0.90,
        )
    else:
        split_buy, target1, stop = current * 0.97, current * 1.08, current * 0.92

    if country == "KR":
        split_buy = kr_tick_round(split_buy)
        target1 = kr_tick_round(target1)
        stop = kr_tick_round(stop)
        current_out = kr_tick_round(current)
        avg_abs_out = kr_tick_round(avg_abs_move) if not pd.isna(avg_abs_move) else None
        low_out = kr_tick_round(low)
        high_out = kr_tick_round(high)
        close_low_out = kr_tick_round(close_low)
        close_high_out = kr_tick_round(close_high)
    else:
        split_buy = us_round(split_buy)
        target1 = us_round(target1)
        stop = us_round(stop)
        current_out = us_round(current)
        avg_abs_out = us_round(avg_abs_move) if not pd.isna(avg_abs_move) else None
        low_out = us_round(low)
        high_out = us_round(high)
        close_low_out = us_round(close_low)
        close_high_out = us_round(close_high)

    last_volume = float(df["volume"].iloc[-1]) if not pd.isna(df["volume"].iloc[-1]) else np.nan
    if "trading_value" in df.columns and not df["trading_value"].dropna().empty:
        last_trading_value = float(df["trading_value"].iloc[-1]) if not pd.isna(df["trading_value"].iloc[-1]) else np.nan
        avg20_trading_value = float(df["trading_value"].tail(20).mean())
    else:
        # 미국: 거래대금 = 종가 * 거래량 근사
        tv = df["close"] * df["volume"]
        last_trading_value = float(tv.iloc[-1]) if not pd.isna(tv.iloc[-1]) else np.nan
        avg20_trading_value = float(tv.tail(20).mean()) if not tv.dropna().empty else np.nan

    threshold = low_liq_krw if country == "KR" else low_liq_usd
    low_liquidity = bool(not pd.isna(avg20_trading_value) and avg20_trading_value < threshold)

    f5 = f20 = f60 = i5 = i20 = i60 = np.nan
    if flow is not None and not flow.empty:
        ff = flow.copy().sort_index()
        foreign_cols = [c for c in ff.columns if "외국인" in str(c)]
        inst_cols = [c for c in ff.columns if "기관" in str(c)]
        if foreign_cols:
            s = pd.to_numeric(ff[foreign_cols[0]], errors="coerce")
            f5, f20, f60 = s.tail(5).sum(), s.tail(20).sum(), s.tail(60).sum()
        if inst_cols:
            s = pd.to_numeric(ff[inst_cols[0]], errors="coerce")
            i5, i20, i60 = s.tail(5).sum(), s.tail(20).sum(), s.tail(60).sum()

    return {
        "name": name,
        "ticker": ticker,
        "country": country,
        "currency": currency,
        "exchange": exchange,
        "status": "OK",
        "last_date": iso(last_date),
        "current_close": current_out,
        "split_buy_ref": split_buy,
        "target1_ref": target1,
        "stop_ref": stop,
        "avg_daily_move_abs": avg_abs_out,
        "avg_daily_move_pct": round(avg_pct_move, 2) if not pd.isna(avg_pct_move) else None,
        "avg_wave_days": wave,
        "low_3m_intraday": low_out,
        "high_3m_intraday": high_out,
        "low_3m_close": close_low_out,
        "high_3m_close": close_high_out,
        "range_3m_pct": round(range_pct, 2) if not pd.isna(range_pct) else None,
        "position_in_3m_range_pct": round(position_pct, 2) if not pd.isna(position_pct) else None,
        "return_1m_pct": return_1m_pct,
        "return_3m_pct": return_3m_pct,
        "return_anomaly_flag": bool(return_anomaly_flag),
        "return_anomaly_reason": return_anomaly_reason,
        "last_volume": round(last_volume, 0) if not pd.isna(last_volume) else None,
        "last_trading_value": round(last_trading_value, 0) if not pd.isna(last_trading_value) else None,
        "avg20_trading_value": round(avg20_trading_value, 0) if not pd.isna(avg20_trading_value) else None,
        "low_liquidity": low_liquidity,
        "foreign_net_5d_value": round(float(f5), 0) if not pd.isna(f5) else None,
        "foreign_net_20d_value": round(float(f20), 0) if not pd.isna(f20) else None,
        "foreign_net_60d_value": round(float(f60), 0) if not pd.isna(f60) else None,
        "institution_net_5d_value": round(float(i5), 0) if not pd.isna(i5) else None,
        "institution_net_20d_value": round(float(i20), 0) if not pd.isna(i20) else None,
        "institution_net_60d_value": round(float(i60), 0) if not pd.isna(i60) else None,
        "data_rows": int(len(df)),
        "source_used": SCRIPT_VERSION,
        "error": None,
    }


# -----------------------------------------------------------------------------
# 데이터 수집
# -----------------------------------------------------------------------------


def fetch_kr_pykrx(ticker: str, start: str, end: str) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    from pykrx import stock

    # adjusted=True: 국내 종목은 pykrx가 제공하는 수정주가 기반 OHLCV를 우선 사용한다.
    hist = stock.get_market_ohlcv_by_date(start, end, ticker, adjusted=True)
    flow = None
    try:
        flow = stock.get_market_trading_value_by_date(start, end, ticker)
    except Exception:
        flow = None
    return hist, flow


def fetch_us_yfinance(ticker: str, start_date: date, end_date: date) -> pd.DataFrame:
    import yfinance as yf

    # yfinance end는 exclusive 성격이라 하루 추가
    df = yf.download(
        ticker,
        start=start_date.isoformat(),
        end=(end_date + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        # 단일 티커인데도 멀티인덱스가 나오는 경우 보정
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    # Adj Close 대신 Close 사용. 관종표 현재가/고저는 실제 거래가격 기준.
    return df


def fetch_krx_otp_daily_all(trd_dd: str) -> pd.DataFrame:
    """
    KRX 정보데이터시스템 CSV-OTP 보조 수집.
    전종목 일별시세 화면(MDCSTAT01501)을 기준으로 시도합니다.
    KRX 화면 구조가 바뀌면 실패할 수 있습니다.
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
        raise RuntimeError(f"OTP 생성 실패: {trd_dd}, response={otp[:100]}")
    r = session.post(down_url, data={"code": otp}, headers=headers, timeout=30)
    r.raise_for_status()
    # KRX CSV는 보통 EUC-KR/CP949
    return pd.read_csv(io.BytesIO(r.content), encoding="cp949")


def fetch_kr_otp_range(tickers: List[str], start_date: date, end_date: date) -> pd.DataFrame:
    """최근 3개월 전종목 일별시세를 날짜별로 받아 관심종목만 필터. 수급자료는 포함되지 않습니다."""
    frames = []
    d = start_date
    wanted = set(str(t).zfill(6) for t in tickers)
    while d <= end_date:
        if d.weekday() < 5:
            trd = ymd(d)
            try:
                raw = fetch_krx_otp_daily_all(trd)
                code_col = next((c for c in raw.columns if "종목코드" in str(c)), None)
                if code_col:
                    raw[code_col] = raw[code_col].astype(str).str.replace("'", "", regex=False).str.zfill(6)
                    raw = raw[raw[code_col].isin(wanted)].copy()
                    raw["date"] = pd.to_datetime(d)
                    frames.append(raw)
                    print(f"[OTP] {trd}: {len(raw)} rows")
            except Exception as e:
                print(f"[OTP_SKIP] {trd}: {e}")
            time.sleep(0.25)
        d += timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def normalize_otp_for_ticker(otp_all: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if otp_all.empty:
        return pd.DataFrame()
    df = otp_all.copy()
    col_code = next((c for c in df.columns if "종목코드" in str(c)), None)
    if col_code is None:
        return pd.DataFrame()

    df[col_code] = df[col_code].astype(str).str.replace("'", "", regex=False).str.zfill(6)
    df = df[df[col_code] == str(ticker).zfill(6)].copy()
    if df.empty:
        return pd.DataFrame()

    mapping = {}
    candidates = {
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
        "거래대금": "trading_value",
    }
    for c in df.columns:
        for key, out in candidates.items():
            if key == c or key in str(c):
                mapping[c] = out

    df = df.rename(columns=mapping)
    for col in ["open", "high", "low", "close", "volume", "trading_value"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("-", "", regex=False)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.set_index("date").sort_index()
    return df[[c for c in ["open", "high", "low", "close", "volume", "trading_value"] if c in df.columns]]


def reset_index_as_date(df: pd.DataFrame) -> pd.DataFrame:
    h = df.copy()
    h = h.reset_index()
    if "date" not in h.columns:
        first_col = h.columns[0]
        h = h.rename(columns={first_col: "date"})
    return h


# -----------------------------------------------------------------------------
# 메인 실행
# -----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", default="watchlist.csv")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--lookback-months", type=int, default=3)
    parser.add_argument("--source", default="auto", choices=["auto", "pykrx", "otp"])
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD. 생략하면 오늘 기준.")
    args = parser.parse_args()

    load_dotenv()
    low_liq_krw = float(os.getenv("LOW_LIQUIDITY_KRW", "10000000000"))
    low_liq_usd = float(os.getenv("LOW_LIQUIDITY_USD", "50000000"))

    watch_path = Path(args.watchlist)
    outdir = Path(args.output_dir)
    ensure_dir(outdir)

    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else date.today()
    start_dt = end_dt - relativedelta(months=args.lookback_months)
    start_s, end_s = ymd(start_dt), ymd(end_dt)
    run_id = ymd(end_dt)

    watch = pd.read_csv(watch_path, dtype={"ticker": str})
    summaries = []
    raw_frames = []
    log_lines = [
        f"script={SCRIPT_VERSION}",
        f"run_at={datetime.now().isoformat(timespec='seconds')}",
        f"period={start_dt.isoformat()}~{end_dt.isoformat()}",
        f"source={args.source}",
        "return_anomaly_rules=1m>300 or 1m<-80 or 3m>500 or 3m<-90 or data_rows<40",
    ]

    otp_all = None
    kr_tickers = watch.loc[watch["country"].eq("KR"), "ticker"].astype(str).str.zfill(6).tolist()
    if args.source == "otp":
        otp_all = fetch_kr_otp_range(kr_tickers, start_dt, end_dt)

    for _, row in watch.iterrows():
        name = str(row["name"])
        ticker = str(row["ticker"]).strip()
        country = str(row["country"]).strip().upper()
        currency = str(row.get("currency", "KRW" if country == "KR" else "USD"))
        exchange = str(row.get("exchange", ""))
        source_used = ""

        try:
            if country == "KR":
                ticker6 = ticker.zfill(6)
                hist = pd.DataFrame()
                flow = None

                if args.source in ["auto", "pykrx"]:
                    try:
                        hist, flow = fetch_kr_pykrx(ticker6, start_s, end_s)
                        source_used = "pykrx_adjusted"
                    except Exception as e:
                        log_lines.append(f"[PYKRX_FAIL] {name} {ticker6}: {repr(e)}")
                        if args.source == "pykrx":
                            raise
                        source_used = "pykrx_fail"

                if hist is None or hist.empty:
                    if otp_all is None:
                        otp_all = fetch_kr_otp_range(kr_tickers, start_dt, end_dt)
                    hist = normalize_otp_for_ticker(otp_all, ticker6)
                    flow = None
                    source_used = "krx_otp_unadjusted"

                s = summarize_history(name, ticker6, country, currency, exchange, hist, flow, low_liq_krw, low_liq_usd)
                s["source_used"] = source_used

                if hist is not None and not hist.empty:
                    h = reset_index_as_date(hist)
                    h["name"] = name
                    h["ticker"] = ticker6
                    h["country"] = country
                    h["source_used"] = source_used
                    raw_frames.append(h)

            elif country == "US":
                hist = fetch_us_yfinance(ticker, start_dt, end_dt)
                source_used = "yfinance_close"
                s = summarize_history(name, ticker, country, currency, exchange, hist, None, low_liq_krw, low_liq_usd)
                s["source_used"] = source_used

                if hist is not None and not hist.empty:
                    h = reset_index_as_date(hist)
                    h["name"] = name
                    h["ticker"] = ticker
                    h["country"] = country
                    h["source_used"] = source_used
                    raw_frames.append(h)

            else:
                s = {
                    "name": name,
                    "ticker": ticker,
                    "country": country,
                    "currency": currency,
                    "exchange": exchange,
                    "status": "UNSUPPORTED_COUNTRY",
                    "error": f"country={country}",
                    "source_used": SCRIPT_VERSION,
                }

            summaries.append(s)
            print(
                f"[OK] {name} {ticker}: {s.get('status')} {s.get('last_date','')} "
                f"anomaly={s.get('return_anomaly_flag','')}"
            )

        except Exception as e:
            err = traceback.format_exc(limit=2)
            summaries.append(
                {
                    "name": name,
                    "ticker": ticker,
                    "country": country,
                    "currency": currency,
                    "exchange": exchange,
                    "status": "ERROR",
                    "error": repr(e),
                    "source_used": SCRIPT_VERSION,
                }
            )
            log_lines.append(f"[ERROR] {name} {ticker}: {repr(e)}\n{err}")
            print(f"[ERROR] {name} {ticker}: {e}")

    summary = pd.DataFrame(summaries)
    summary = reorder_summary_columns(summary)

    # 표시명 기준 정렬: 영문은 그대로, 한글은 유니코드 정렬. ChatGPT 표 재정렬 전 기초자료.
    summary = summary.sort_values(["name"]).reset_index(drop=True)

    anomaly_count = 0
    if "return_anomaly_flag" in summary.columns:
        anomaly_count = int(summary["return_anomaly_flag"].fillna(False).astype(bool).sum())
    log_lines.append(f"summary_rows={len(summary)}")
    log_lines.append(f"return_anomaly_rows={anomaly_count}")

    dated_summary = outdir / f"watchlist_summary_{run_id}.csv"
    latest_summary = outdir / "watchlist_summary_latest.csv"
    summary.to_csv(dated_summary, index=False, encoding="utf-8-sig")
    summary.to_csv(latest_summary, index=False, encoding="utf-8-sig")

    if raw_frames:
        raw = pd.concat(raw_frames, ignore_index=True)
    else:
        raw = pd.DataFrame()

    dated_raw = outdir / f"raw_history_{run_id}.csv"
    latest_raw = outdir / "raw_history_latest.csv"
    raw.to_csv(dated_raw, index=False, encoding="utf-8-sig")
    raw.to_csv(latest_raw, index=False, encoding="utf-8-sig")

    # 엑셀도 함께 생성
    try:
        xlsx = outdir / "watchlist_latest.xlsx"
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="summary", index=False)
            raw.to_excel(writer, sheet_name="raw_history", index=False)
    except Exception as e:
        log_lines.append(f"[XLSX_FAIL] {repr(e)}")

    log_lines.append(f"summary={dated_summary}")
    log_lines.append(f"raw={dated_raw}")
    log_lines.append(f"latest_summary={latest_summary}")
    log_lines.append(f"latest_raw={latest_raw}")
    (outdir / "run_log_latest.txt").write_text("\n".join(log_lines), encoding="utf-8")

    print(f"\nSaved: {dated_summary}")
    print(f"Saved: {dated_raw}")
    print(f"Saved: {latest_summary}")
    print(f"Return anomaly rows: {anomaly_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
