#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기
v4.6_kosdaq_candidates_gainer_filter

생성/갱신 파일
- latest/universe_raw_history_latest.csv
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv
- latest/kospi_gainers_1m_latest.csv
- latest/kospi_candidates_30_latest.csv
- latest/kospi_recommend_7_latest.csv
- latest/kosdaq_candidates_10_latest.csv
- latest/kosdaq_recommend_5_latest.csv
- latest/universe_run_log_latest.txt

필수 GitHub Secret
- KRX_AUTH_KEY
"""

from __future__ import annotations

import argparse
import os
import re
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

try:
    from dotenv import load_dotenv
except Exception:  # GitHub Actions에 dotenv가 없어도 실행되게 처리
    def load_dotenv(*args, **kwargs):
        return False


SCRIPT_VERSION = "collect_universe.py v4.6.1_kosdaq_candidates_gainer_filter_actual_date_log"

OPENAPI_STOCK_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
}

SUMMARY_COLUMNS = [
    "name",
    "ticker",
    "market",
    "status",
    "last_date",
    "current_close",
    "split_buy_low_ref",
    "split_buy_high_ref",
    "target1_ref",
    "target2_ref",
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
    "last_volume",
    "last_trading_value",
    "avg20_trading_value",
    "low_liquidity",
    "market_cap",
    "listed_shares",
    "data_rows",
    "source_used",
]

CANDIDATE_COLUMNS = [
    "rank",
    "recommend_flag",
    "code",
    "name",
    "market",
    "asof_date",
    "close",
    "buy_range",
    "sell_range",
    "avg_daily_move_text",
    "avg_wave_days",
    "stop_price",
    "low_3m",
    "high_3m",
    "range_pct",
    "position_in_3m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "avg_volume",
    "avg_trading_value",
    "liquidity_flag",
    "overheat_flag",
    "score",
    "reason",
]

GAINER_COLUMNS = [
    "rank",
    "recommend_flag",
    "code",
    "name",
    "market",
    "asof_date",
    "close",
    "return_1m_pct",
    "buy_range",
    "sell_range",
    "avg_daily_move_text",
    "avg_wave_days",
    "stop_price",
    "low_3m",
    "high_3m",
    "range_pct",
    "avg_volume",
    "avg_trading_value",
    "liquidity_flag",
    "overheat_flag",
    "score",
    "reason",
]


# -----------------------------------------------------------------------------
# 기본 유틸
# -----------------------------------------------------------------------------


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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


def clean_number(x):
    if x is None or pd.isna(x):
        return np.nan
    s = str(x).strip().replace(",", "").replace("'", "").replace(" ", "")
    if s in ["", "-", "nan", "None", "NaN"]:
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


def kr_tick_round(x):
    """한국거래소 호가 단위에 가깝게 반올림한다."""
    if x is None or pd.isna(x) or float(x) <= 0:
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


def fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return ""
    try:
        return f"{int(round(float(x))):,}"
    except Exception:
        return ""


def fmt_won(x) -> str:
    s = fmt_int(x)
    return f"{s}원" if s else ""


def safe_float(x, default=np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def safe_bool(x) -> bool:
    if isinstance(x, bool):
        return x
    if x is None or pd.isna(x):
        return False
    return str(x).strip().lower() in ["true", "1", "yes", "y"]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


# -----------------------------------------------------------------------------
# KRX OpenAPI 수집
# -----------------------------------------------------------------------------


def request_krx_openapi(url: str, auth_key: str, bas_dd: str, log_lines: List[str], label: str) -> pd.DataFrame:
    try:
        response = requests.get(
            url,
            params={"basDd": bas_dd},
            headers={"AUTH_KEY": auth_key},
            timeout=40,
        )
    except Exception as exc:
        log_lines.append(f"OPENAPI_REQUEST_FAIL {label} {bas_dd}: {repr(exc)}")
        return pd.DataFrame()

    if response.status_code != 200:
        body = response.text[:300].replace("\n", " ")
        log_lines.append(f"OPENAPI_HTTP_FAIL {label} {bas_dd}: status={response.status_code}, body={body}")
        return pd.DataFrame()

    try:
        data = response.json()
    except Exception as exc:
        body = response.text[:300].replace("\n", " ")
        log_lines.append(f"OPENAPI_JSON_FAIL {label} {bas_dd}: {repr(exc)}, body={body}")
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
    missing = [col for col in required if col not in raw.columns]
    if missing:
        log_lines.append(f"NORMALIZE_FAIL {market} {bas_dd}: missing={missing}, cols={list(raw.columns)}")
        return pd.DataFrame()

    idx = raw.index
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(bas_dd, format="%Y%m%d", errors="coerce"),
            "market": market,
            "ticker": raw["ISU_CD"].map(normalize_ticker),
            "name": raw["ISU_NM"].astype(str),
            "open": raw["TDD_OPNPRC"].map(clean_number),
            "high": raw["TDD_HGPRC"].map(clean_number),
            "low": raw["TDD_LWPRC"].map(clean_number),
            "close": raw["TDD_CLSPRC"].map(clean_number),
            "volume": raw.get("ACC_TRDVOL", pd.Series(index=idx, dtype=object)).map(clean_number),
            "trading_value": raw.get("ACC_TRDVAL", pd.Series(index=idx, dtype=object)).map(clean_number),
            "market_cap": raw.get("MKTCAP", pd.Series(index=idx, dtype=object)).map(clean_number),
            "listed_shares": raw.get("LIST_SHRS", pd.Series(index=idx, dtype=object)).map(clean_number),
        }
    )

    out = out.dropna(subset=["date", "ticker", "close"])
    out = out[out["ticker"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    return out.reset_index(drop=True)


def collect_history(start_dt: date, end_dt: date, auth_key: str, log_lines: List[str]) -> pd.DataFrame:
    if not auth_key:
        log_lines.append("KRX_AUTH_KEY_MISSING")
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
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
    hist = hist.drop_duplicates(subset=["date", "market", "ticker"], keep="last")
    return hist.sort_values(["market", "ticker", "date"]).reset_index(drop=True)


def normalize_history_dtypes(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    df = hist.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["ticker", "name", "market"]:
        if col not in df.columns:
            df[col] = ""
    df["ticker"] = df["ticker"].map(normalize_ticker)
    df["market"] = df["market"].astype(str).str.upper().str.strip()
    for col in ["open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = df[col].map(clean_number)
    df = df.dropna(subset=["date", "ticker", "close"])
    df = df[df["ticker"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    return df.sort_values(["market", "ticker", "date"]).reset_index(drop=True)


def combine_with_existing(fresh: pd.DataFrame, existing_path: Path, keep_months: int, log_lines: List[str]) -> pd.DataFrame:
    existing = read_csv_if_exists(existing_path)
    existing = normalize_history_dtypes(existing)
    fresh = normalize_history_dtypes(fresh)

    if fresh.empty and existing.empty:
        log_lines.append("HISTORY_COMBINE: fresh=0, existing=0")
        return pd.DataFrame()

    if fresh.empty:
        log_lines.append(f"HISTORY_COMBINE: fresh=0, using existing rows={len(existing)}")
        return existing

    frames = [fresh]
    if not existing.empty:
        frames.append(existing)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "market", "ticker"], keep="first")

    max_date = combined["date"].max()
    cutoff = max_date - relativedelta(months=keep_months)
    combined = combined[combined["date"] >= cutoff]
    combined = combined.sort_values(["market", "ticker", "date"]).reset_index(drop=True)
    log_lines.append(f"HISTORY_COMBINE: fresh={len(fresh)}, existing={len(existing)}, combined={len(combined)}")
    return combined


# -----------------------------------------------------------------------------
# 요약 산출
# -----------------------------------------------------------------------------


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


def build_market_summary(hist: pd.DataFrame, market: str, low_liq_krw: float, log_lines: List[str]) -> pd.DataFrame:
    hist = normalize_history_dtypes(hist)
    if hist.empty:
        log_lines.append(f"SUMMARY {market}: hist empty")
        return empty_summary()

    df = hist[hist["market"].eq(market)].copy()
    log_lines.append(f"SUMMARY {market}: input rows={len(df)}")
    if df.empty:
        return empty_summary()

    last_date = df["date"].max()
    three_months_ago = last_date - relativedelta(months=3)
    one_month_ago = last_date - relativedelta(months=1)
    df = df[df["date"] >= three_months_ago].copy()
    df = df.sort_values(["ticker", "date"])
    log_lines.append(f"SUMMARY {market}: 3m rows={len(df)}, tickers={df['ticker'].nunique()}")

    rows = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date")
        if g.empty:
            continue

        last = g.iloc[-1]
        last_close = safe_float(last["close"])
        if pd.isna(last_close) or last_close <= 0:
            continue

        low = safe_float(g["low"].min(), last_close)
        high = safe_float(g["high"].max(), last_close)
        close_low = safe_float(g["close"].min(), last_close)
        close_high = safe_float(g["close"].max(), last_close)

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
        move = safe_float(avg_abs, last_close * 0.03)
        if pd.isna(move) or move <= 0:
            move = last_close * 0.03

        if price_range > 0:
            split_low = max(low * 1.01, last_close - move * 2.5)
            split_high = min(last_close * 0.99, last_close - move * 0.3)
            if split_low > split_high:
                split_low = min(last_close * 0.94, low + price_range * 0.45)
                split_high = min(last_close * 0.99, low + price_range * 0.62)
            target1 = max(last_close * 1.03, min(last_close + move * 2.2, low + price_range * 0.78))
            target2 = max(target1 * 1.03, min(last_close + move * 4.0, low + price_range * 0.90))
            stop = max(low * 0.97, last_close - move * 3.0)
        else:
            split_low = last_close * 0.94
            split_high = last_close * 0.99
            target1 = last_close * 1.08
            target2 = last_close * 1.15
            stop = last_close * 0.92

        avg20_tv = g["trading_value"].tail(20).mean()
        avg20_vol = g["volume"].tail(20).mean()
        last_tv = last["trading_value"]

        rows.append(
            {
                "name": str(last.get("name", ticker)),
                "ticker": ticker,
                "market": market,
                "status": "OK",
                "last_date": iso(last["date"]),
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
                "source_used": SCRIPT_VERSION,
            }
        )

    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    log_lines.append(f"SUMMARY {market}: output rows={len(out)}")
    if out.empty:
        return empty_summary()
    return out.sort_values(["name", "ticker"]).reset_index(drop=True)


# -----------------------------------------------------------------------------
# 코피표 후보 30 / 추천 7 / 코닥표 후보 10 / 추천 5 / 코급표 20 산출
# -----------------------------------------------------------------------------


def is_excluded_stock(row: pd.Series) -> bool:
    """보통주 분석에서 제외할 종목을 판별한다."""
    name = str(row.get("name", "")).strip()
    name_upper = name.upper()
    ticker = str(row.get("ticker", ""))

    if not re.fullmatch(r"\d{6}", ticker):
        return True

    # 우선주: 삼성전자우, 현대차2우B, 1우/2우B/3우B 등
    if "우선주" in name:
        return True
    if re.search(r"(\d우B|\d우|우B|우C|우)$", name):
        return True

    # 스팩, 리츠, ETF/ETN 성격 이름 제외
    exclude_keywords = [
        "SPAC",
        "스팩",
        "REIT",
        "리츠",
        "ETF",
        "ETN",
        "KODEX",
        "TIGER",
        "ACE",
        "KBSTAR",
        "SOL ",
        "HANARO",
        "ARIRANG",
        "KOSEF",
        "히어로즈",
        "인버스",
        "레버리지",
        "선물",
    ]
    if any(keyword in name_upper for keyword in exclude_keywords):
        return True

    last_volume = row.get("last_volume")
    if pd.isna(last_volume) or safe_float(last_volume, 0) <= 0:
        return True

    close = row.get("current_close")
    if pd.isna(close) or safe_float(close, 0) <= 0:
        return True

    return False


def calculate_candidate_score(row: pd.Series) -> Dict[str, object]:
    """코피표 후보 선정용 점수 계산."""
    score = 100.0
    overheat_flag = False
    liquidity_flag = False
    reasons: List[str] = []

    return_1m = safe_float(row.get("return_1m_pct"))
    position = safe_float(row.get("position_in_3m_range_pct"))
    range_pct = safe_float(row.get("range_3m_pct"))
    avg_tv = safe_float(row.get("avg20_trading_value"))
    avg_move_pct = safe_float(row.get("avg_daily_move_pct"))
    market_cap = safe_float(row.get("market_cap"))
    low_liq = safe_bool(row.get("low_liquidity"))

    # 과열 감점: 최근 1개월 급등 + 3개월 고점권
    if not pd.isna(return_1m):
        if return_1m > 40:
            score -= 22
            overheat_flag = True
            reasons.append(f"1개월 급등 {return_1m:.1f}%")
        elif return_1m > 30:
            score -= 15
            overheat_flag = True
            reasons.append(f"1개월 상승 과열 {return_1m:.1f}%")
        elif return_1m > 20:
            score -= 8
            reasons.append(f"1개월 상승 {return_1m:.1f}%")
        elif 3 <= return_1m <= 18:
            score += 7
            reasons.append(f"1개월 추세 양호 {return_1m:.1f}%")
        elif return_1m < -10:
            score -= 8
            reasons.append(f"1개월 약세 {return_1m:.1f}%")

    if not pd.isna(position):
        if position >= 92:
            score -= 18
            overheat_flag = True
            reasons.append(f"3개월 고점권 {position:.1f}%")
        elif position >= 82:
            score -= 9
            reasons.append(f"상단권 {position:.1f}%")
        elif 35 <= position <= 70:
            score += 8
            reasons.append(f"매수위치 중립 {position:.1f}%")
        elif position < 18:
            score -= 5
            reasons.append(f"하단권 약세 {position:.1f}%")

    # 유동성 감점 / 가점
    if low_liq or (not pd.isna(avg_tv) and avg_tv < 5_000_000_000):
        score -= 22
        liquidity_flag = True
        reasons.append("저유동성")
    elif not pd.isna(avg_tv) and avg_tv >= 100_000_000_000:
        score += 10
        reasons.append("거래대금 우수")
    elif not pd.isna(avg_tv) and avg_tv >= 30_000_000_000:
        score += 5
        reasons.append("거래대금 양호")

    # 변동성: 너무 낮아도 탄력 부족, 너무 높으면 위험
    if not pd.isna(avg_move_pct):
        if 1.5 <= avg_move_pct <= 3.8:
            score += 5
            reasons.append(f"변동성 적정 {avg_move_pct:.2f}%")
        elif avg_move_pct > 6.0:
            score -= 10
            reasons.append(f"고변동 {avg_move_pct:.2f}%")
        elif avg_move_pct > 4.8:
            score -= 5
            reasons.append(f"변동성 큼 {avg_move_pct:.2f}%")

    # 3개월 구간 변동폭이 너무 과하면 감점
    if not pd.isna(range_pct):
        if range_pct > 120:
            score -= 10
            reasons.append(f"3개월 변동폭 과대 {range_pct:.1f}%")
        elif 20 <= range_pct <= 80:
            score += 3
            reasons.append(f"3개월 변동폭 유효 {range_pct:.1f}%")

    # 시가총액 너무 작으면 보수적으로 감점
    if not pd.isna(market_cap):
        if market_cap < 300_000_000_000:
            score -= 5
            reasons.append("소형주")
        elif market_cap > 5_000_000_000_000:
            score += 4
            reasons.append("대형주 안정성")

    return {
        "score": round(float(score), 2),
        "overheat_flag": bool(overheat_flag),
        "liquidity_flag": bool(liquidity_flag),
        "reason": "; ".join(reasons[:5]) if reasons else "가격·거래대금·변동성 기준 중립",
    }


def build_range_text(low, high) -> str:
    lo = fmt_won(low)
    hi = fmt_won(high)
    if lo and hi:
        return f"{lo}~{hi}"
    return lo or hi or ""


def build_avg_daily_move_text(abs_move, pct_move) -> str:
    won = fmt_won(abs_move)
    pct = "" if pct_move is None or pd.isna(pct_move) else f"±{float(pct_move):.2f}%"
    if won and pct:
        return f"약 ±{won} 내외 ({pct})"
    if won:
        return f"약 ±{won} 내외"
    if pct:
        return f"약 {pct}"
    return ""


def row_to_candidate(row: pd.Series, rank: int, recommend_flag: str, scoring: Dict[str, object]) -> Dict[str, object]:
    return {
        "rank": rank,
        "recommend_flag": recommend_flag,
        "code": str(row.get("ticker", "")).zfill(6),
        "name": row.get("name", ""),
        "market": row.get("market", ""),
        "asof_date": row.get("last_date", ""),
        "close": row.get("current_close"),
        "buy_range": build_range_text(row.get("split_buy_low_ref"), row.get("split_buy_high_ref")),
        "sell_range": build_range_text(row.get("target1_ref"), row.get("target2_ref")),
        "avg_daily_move_text": build_avg_daily_move_text(row.get("avg_daily_move_abs"), row.get("avg_daily_move_pct")),
        "avg_wave_days": row.get("avg_wave_days"),
        "stop_price": row.get("stop_ref"),
        "low_3m": row.get("low_3m_intraday"),
        "high_3m": row.get("high_3m_intraday"),
        "range_pct": row.get("range_3m_pct"),
        "position_in_3m_range_pct": row.get("position_in_3m_range_pct"),
        "return_1m_pct": row.get("return_1m_pct"),
        "return_3m_pct": row.get("return_3m_pct"),
        "avg_volume": row.get("last_volume"),
        "avg_trading_value": row.get("avg20_trading_value"),
        "liquidity_flag": scoring["liquidity_flag"],
        "overheat_flag": scoring["overheat_flag"],
        "score": scoring["score"],
        "reason": scoring["reason"],
    }


def build_market_candidates(
    summary: pd.DataFrame,
    log_lines: List[str],
    market_label: str,
    candidate_n: int,
    recommend_n: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    코피표/코닥표 공통 후보 선정 함수.
    - KOSPI: 후보 30개, 추천 7개
    - KOSDAQ: 후보 10개, 추천 5개
    """
    if summary is None or summary.empty:
        log_lines.append(f"{market_label}_CANDIDATES: summary empty")
        return pd.DataFrame(columns=CANDIDATE_COLUMNS), pd.DataFrame(columns=CANDIDATE_COLUMNS)

    df = summary.copy()
    df = df[~df.apply(is_excluded_stock, axis=1)].copy()
    log_lines.append(f"{market_label}_CANDIDATES: after exclusion rows={len(df)}")

    if df.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS), pd.DataFrame(columns=CANDIDATE_COLUMNS)

    score_rows = []
    for _, row in df.iterrows():
        scoring = calculate_candidate_score(row)
        score_rows.append({**row.to_dict(), **scoring})

    scored = pd.DataFrame(score_rows)

    scored = scored.sort_values(
        ["score", "avg20_trading_value", "return_1m_pct"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    top_base = scored.head(candidate_n).copy()

    # 추천 종목은 저유동성/과열이 아닌 종목을 우선 선정한다.
    stable = scored[
        (~scored["liquidity_flag"].astype(bool))
        & (~scored["overheat_flag"].astype(bool))
    ].copy()

    rec_base = stable.head(recommend_n)

    # 안정 후보가 부족하면 점수순으로 채운다.
    if len(rec_base) < recommend_n:
        fill = scored[~scored.index.isin(rec_base.index)].head(recommend_n - len(rec_base))
        rec_base = pd.concat([rec_base, fill], ignore_index=False)

    rec_codes = set(rec_base["ticker"].astype(str).tolist())

    candidates = []
    for i, (_, row) in enumerate(top_base.iterrows(), start=1):
        is_rec = str(row.get("ticker")) in rec_codes
        has_warning = bool(row.get("overheat_flag")) or bool(row.get("liquidity_flag"))

        if is_rec:
            flag = "✅"
        elif has_warning:
            flag = "⚠️"
        else:
            flag = "🟡"

        scoring = {
            "score": row.get("score"),
            "overheat_flag": bool(row.get("overheat_flag")),
            "liquidity_flag": bool(row.get("liquidity_flag")),
            "reason": row.get("reason", ""),
        }
        candidates.append(row_to_candidate(row, i, flag, scoring))

    recommends = []
    rec_base = rec_base.sort_values(
        ["score", "avg20_trading_value"],
        ascending=[False, False],
        na_position="last",
    ).head(recommend_n)

    for i, (_, row) in enumerate(rec_base.iterrows(), start=1):
        scoring = {
            "score": row.get("score"),
            "overheat_flag": bool(row.get("overheat_flag")),
            "liquidity_flag": bool(row.get("liquidity_flag")),
            "reason": row.get("reason", ""),
        }
        recommends.append(row_to_candidate(row, i, "✅", scoring))

    cand_df = pd.DataFrame(candidates, columns=CANDIDATE_COLUMNS)
    rec_df = pd.DataFrame(recommends, columns=CANDIDATE_COLUMNS)

    log_lines.append(
        f"{market_label}_CANDIDATES: candidates={len(cand_df)}, recommend={len(rec_df)}"
    )

    return cand_df, rec_df


def build_kospi_candidates(summary: pd.DataFrame, log_lines: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    return build_market_candidates(
        summary=summary,
        log_lines=log_lines,
        market_label="KOSPI",
        candidate_n=30,
        recommend_n=7,
    )


def build_kosdaq_candidates(summary: pd.DataFrame, log_lines: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    return build_market_candidates(
        summary=summary,
        log_lines=log_lines,
        market_label="KOSDAQ",
        candidate_n=10,
        recommend_n=5,
    )


def build_kospi_gainers(summary: pd.DataFrame, log_lines: List[str], top_n: int = 20) -> pd.DataFrame:
    """
    코급표 생성 함수.
    최근 1개월 상승률 상위 20개를 만들되,
    액면병합·거래재개·데이터 결측 등으로 추정되는 비정상 상승률은 제외한다.
    """
    if summary is None or summary.empty:
        log_lines.append("KOSPI_GAINERS: summary empty")
        return pd.DataFrame(columns=GAINER_COLUMNS)

    df = summary.copy()
    df = df[~df.apply(is_excluded_stock, axis=1)].copy()

    df["return_1m_pct_num"] = df["return_1m_pct"].map(clean_number)
    df["data_rows_num"] = df["data_rows"].map(clean_number)

    before_count = len(df)

    df = df.dropna(subset=["return_1m_pct_num"])
    df = df[df["data_rows_num"] >= 40]

    # 비정상 상승률 방지:
    # 1개월 +300% 초과는 실제 급등 가능성도 있지만,
    # 자동 표에서는 액면병합·거래재개·데이터 왜곡 가능성이 커서 제외한다.
    anomaly_df = df[df["return_1m_pct_num"] > 300].copy()
    if not anomaly_df.empty:
        names = ", ".join(anomaly_df["name"].astype(str).head(10).tolist())
        log_lines.append(
            f"KOSPI_GAINERS_ANOMALY_EXCLUDED: rows={len(anomaly_df)}, examples={names}"
        )

    df = df[
        (df["return_1m_pct_num"] >= 5)
        & (df["return_1m_pct_num"] <= 300)
    ].copy()

    log_lines.append(
        f"KOSPI_GAINERS_FILTER: before={before_count}, after_valid={len(df)}"
    )

    if df.empty:
        log_lines.append("KOSPI_GAINERS: no valid return_1m_pct after anomaly filter")
        return pd.DataFrame(columns=GAINER_COLUMNS)

    # 먼저 1개월 상승률 상위 20개를 확정한다.
    df = df.sort_values("return_1m_pct_num", ascending=False).head(top_n).reset_index(drop=True)

    scored_rows = []
    for _, row in df.iterrows():
        scoring = calculate_candidate_score(row)
        scored_rows.append({**row.to_dict(), **scoring})

    scored = pd.DataFrame(scored_rows)

    # 투자적합 7개는 단순 상승률이 아니라 점수·유동성·과열 여부를 함께 반영한다.
    stable = scored[
        (~scored["liquidity_flag"].astype(bool))
        & (~scored["overheat_flag"].astype(bool))
    ].copy()

    rec_base = stable.sort_values(
        ["score", "avg20_trading_value", "return_1m_pct_num"],
        ascending=[False, False, False],
        na_position="last",
    ).head(7)

    if len(rec_base) < 7:
        fill = scored[~scored.index.isin(rec_base.index)].sort_values(
            ["score", "avg20_trading_value", "return_1m_pct_num"],
            ascending=[False, False, False],
            na_position="last",
        ).head(7 - len(rec_base))
        rec_base = pd.concat([rec_base, fill], ignore_index=False)

    rec_codes = set(rec_base["ticker"].astype(str).tolist())

    rows = []
    for i, (_, row) in enumerate(scored.iterrows(), start=1):
        scoring = {
            "score": row.get("score"),
            "overheat_flag": bool(row.get("overheat_flag")),
            "liquidity_flag": bool(row.get("liquidity_flag")),
            "reason": row.get("reason", ""),
        }

        is_rec = str(row.get("ticker")) in rec_codes
        has_warning = bool(row.get("overheat_flag")) or bool(row.get("liquidity_flag"))

        if is_rec:
            flag = "✅"
        elif has_warning:
            flag = "⚠️"
        else:
            flag = "🟡"

        cand = row_to_candidate(row, i, flag, scoring)

        rows.append(
            {
                "rank": cand["rank"],
                "recommend_flag": cand["recommend_flag"],
                "code": cand["code"],
                "name": cand["name"],
                "market": cand["market"],
                "asof_date": cand["asof_date"],
                "close": cand["close"],
                "return_1m_pct": cand["return_1m_pct"],
                "buy_range": cand["buy_range"],
                "sell_range": cand["sell_range"],
                "avg_daily_move_text": cand["avg_daily_move_text"],
                "avg_wave_days": cand["avg_wave_days"],
                "stop_price": cand["stop_price"],
                "low_3m": cand["low_3m"],
                "high_3m": cand["high_3m"],
                "range_pct": cand["range_pct"],
                "avg_volume": cand["avg_volume"],
                "avg_trading_value": cand["avg_trading_value"],
                "liquidity_flag": cand["liquidity_flag"],
                "overheat_flag": cand["overheat_flag"],
                "score": cand["score"],
                "reason": cand["reason"],
            }
        )

    out = pd.DataFrame(rows, columns=GAINER_COLUMNS)
    log_lines.append(f"KOSPI_GAINERS: rows={len(out)}")
    return out


# -----------------------------------------------------------------------------
# 메인 실행
# -----------------------------------------------------------------------------


def write_log(log_lines: Iterable[str], log_path: Path) -> None:
    ensure_dir(log_path.parent)
    text = "\n".join(str(x) for x in log_lines) + "\n"
    log_path.write_text(text, encoding="utf-8")


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="KRX universe collector for watchlist tables")
    parser.add_argument("--days", type=int, default=100, help="수집할 최근 영업일 범위. 기본 100일")
    parser.add_argument("--keep-months", type=int, default=4, help="raw history 보존 개월 수. 기본 4개월")
    parser.add_argument("--low-liq-krw", type=float, default=5_000_000_000, help="저유동성 기준 평균 거래대금")
    parser.add_argument("--output-dir", default="latest", help="출력 폴더. 기본 latest")
    parser.add_argument("--start-date", default="", help="YYYY-MM-DD 직접 지정 시 이 날짜부터 수집")
    parser.add_argument("--end-date", default="", help="YYYY-MM-DD 직접 지정 시 이 날짜까지 수집")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    latest_dir = root / args.output_dir
    ensure_dir(latest_dir)

    log_lines: List[str] = []
    started_at = datetime.now().isoformat(timespec="seconds")
    log_lines.append(f"script={SCRIPT_VERSION}")
    log_lines.append(f"started_at={started_at}")

    today = date.today()
    if args.end_date:
        end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        end_dt = today

    if args.start_date:
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        # 넉넉하게 3개월 이상을 확보한다.
        start_dt = (pd.Timestamp(end_dt) - pd.tseries.offsets.BDay(args.days)).date()

    log_lines.append(f"collection_period={start_dt.isoformat()}~{end_dt.isoformat()}")

    raw_history_path = latest_dir / "universe_raw_history_latest.csv"
    kospi_summary_path = latest_dir / "kospi_universe_summary_latest.csv"
    kosdaq_summary_path = latest_dir / "kosdaq_universe_summary_latest.csv"
    kospi_gainers_path = latest_dir / "kospi_gainers_1m_latest.csv"
    kospi_candidates_path = latest_dir / "kospi_candidates_30_latest.csv"
    kospi_recommend_path = latest_dir / "kospi_recommend_7_latest.csv"
    kosdaq_candidates_path = latest_dir / "kosdaq_candidates_10_latest.csv"
    kosdaq_recommend_path = latest_dir / "kosdaq_recommend_5_latest.csv"
    market_index_path = latest_dir / "market_index_summary_latest.csv"
    log_path = latest_dir / "universe_run_log_latest.txt"

    try:
        auth_key = os.getenv("KRX_AUTH_KEY", "").strip()
        fresh = collect_history(start_dt, end_dt, auth_key, log_lines)
        hist = combine_with_existing(fresh, raw_history_path, args.keep_months, log_lines)

        if not hist.empty:
            write_csv(hist, raw_history_path)
            log_lines.append(f"raw_history={raw_history_path.as_posix()}, rows={len(hist)}")
        else:
            log_lines.append("raw_history=not_written_empty")

        # 요약 생성: 새 raw가 없어도 기존 raw가 있으면 기존 raw로 재생성한다.
        kospi_summary = build_market_summary(hist, "KOSPI", args.low_liq_krw, log_lines)
        kosdaq_summary = build_market_summary(hist, "KOSDAQ", args.low_liq_krw, log_lines)

        # 실제 데이터 기준일을 명확히 남긴다.
        # 예: 휴장일/장마감 전 실행이면 collection end date와 실제 가격 데이터 기준일이 다를 수 있다.
        actual_dates = []
        for _summary in [kospi_summary, kosdaq_summary]:
            if _summary is not None and not _summary.empty and "last_date" in _summary.columns:
                _d = pd.to_datetime(_summary["last_date"], errors="coerce").max()
                if pd.notna(_d):
                    actual_dates.append(_d)
        if actual_dates:
            actual_data_last_date = max(actual_dates).date().isoformat()
            log_lines.append(f"actual_data_last_date={actual_data_last_date}")
        else:
            log_lines.append("actual_data_last_date=unknown")

        if not kospi_summary.empty:
            write_csv(kospi_summary, kospi_summary_path)
            log_lines.append(f"KOSPI_summary={kospi_summary_path.as_posix()}, rows={len(kospi_summary)}")
        else:
            log_lines.append("KOSPI_summary=not_written_empty")

        if not kosdaq_summary.empty:
            write_csv(kosdaq_summary, kosdaq_summary_path)
            log_lines.append(f"KOSDAQ_summary={kosdaq_summary_path.as_posix()}, rows={len(kosdaq_summary)}")
        else:
            log_lines.append("KOSDAQ_summary=not_written_empty")

        if not kospi_summary.empty:
            gainers = build_kospi_gainers(kospi_summary, log_lines, top_n=20)
            candidates, recommends = build_kospi_candidates(kospi_summary, log_lines)

            if not gainers.empty:
                write_csv(gainers, kospi_gainers_path)
                log_lines.append(f"kospi_gainers_1m={kospi_gainers_path.as_posix()}, rows={len(gainers)}")
            else:
                log_lines.append("kospi_gainers_1m=not_written_empty")

            if not candidates.empty:
                write_csv(candidates, kospi_candidates_path)
                log_lines.append(f"kospi_candidates_30={kospi_candidates_path.as_posix()}, rows={len(candidates)}")
            else:
                log_lines.append("kospi_candidates_30=not_written_empty")

            if not recommends.empty:
                write_csv(recommends, kospi_recommend_path)
                log_lines.append(f"kospi_recommend_7={kospi_recommend_path.as_posix()}, rows={len(recommends)}")
            else:
                log_lines.append("kospi_recommend_7=not_written_empty")


        if not kosdaq_summary.empty:
            kosdaq_candidates, kosdaq_recommends = build_kosdaq_candidates(kosdaq_summary, log_lines)

            if not kosdaq_candidates.empty:
                write_csv(kosdaq_candidates, kosdaq_candidates_path)
                log_lines.append(
                    f"kosdaq_candidates_10={kosdaq_candidates_path.as_posix()}, rows={len(kosdaq_candidates)}"
                )
            else:
                log_lines.append("kosdaq_candidates_10=not_written_empty")

            if not kosdaq_recommends.empty:
                write_csv(kosdaq_recommends, kosdaq_recommend_path)
                log_lines.append(
                    f"kosdaq_recommend_5={kosdaq_recommend_path.as_posix()}, rows={len(kosdaq_recommends)}"
                )
            else:
                log_lines.append("kosdaq_recommend_5=not_written_empty")
        else:
            log_lines.append("KOSDAQ_CANDIDATES_SKIPPED: kosdaq_summary empty")

        # 시장지수 파일은 이번 스크립트에서 새 수집하지 않는다. 기존 파일이 없을 때만 안내용으로 만든다.
        if not market_index_path.exists():
            market_index_df = pd.DataFrame(
                [
                    {
                        "asof_date": iso(end_dt),
                        "note": "market index collection skipped in this script; stock universe files generated",
                    }
                ]
            )
            write_csv(market_index_df, market_index_path)
            log_lines.append(f"market_index_summary={market_index_path.as_posix()}, rows={len(market_index_df)}, note=placeholder")
        else:
            log_lines.append(f"market_index_summary=kept_existing:{market_index_path.as_posix()}")

        finished_at = datetime.now().isoformat(timespec="seconds")
        log_lines.append(f"finished_at={finished_at}")
        write_log(log_lines, log_path)
        print("\n".join(log_lines[-20:]))
        return 0

    except Exception as exc:
        log_lines.append(f"FATAL_ERROR={repr(exc)}")
        log_lines.append(traceback.format_exc())
        try:
            write_log(log_lines, log_path)
        except Exception:
            pass
        print("\n".join(log_lines))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
