#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기 v4.4_with_candidates

핵심 원칙
- KRX Open API 주식 일별매매정보만 사용한다.
- 수집 직후 이미 표준화된 hist에서 곧바로 summary/gainers를 만든다.
- 복잡한 fallback/시장명 재판별을 제거해 0행 요약 문제를 줄인다.
- 새 데이터가 0행이면 기존 정상 CSV를 빈 파일로 덮어쓰지 않는다.
- kospi_candidates_30과 kospi_recommend_7을 생성한다.

필수 GitHub Secret
- KRX_AUTH_KEY

생성/갱신 파일
- latest/universe_raw_history_latest.csv
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv
- latest/kospi_gainers_1m_latest.csv
- latest/market_index_summary_latest.csv   # 이번 버전은 지수 수집 생략, 기존 파일 보호
- latest/kospi_candidates_30_latest.csv
- latest/kospi_recommend_7_latest.csv
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

SCRIPT_VERSION = "collect_universe.py v4.4_with_candidates"

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

CANDIDATES_COLUMNS = [
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
            "source_used": "krx_openapi_v44",
        })

    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    log_lines.append(f"SUMMARY {market}: output rows={len(out)}")
    if out.empty:
        return empty_summary()
    return out.sort_values(["name", "ticker"]).reset_index(drop=True)


def is_excluded_stock(row: pd.Series) -> bool:
    """우선주, 스팩, 리츠, ETF/ETN, 거래정지 또는 거래량 0 종목 판별"""
    name = str(row.get("name", "")).upper()
    ticker = str(row.get("ticker", ""))
    
    # 우선주 판별
    if "우" in name or "우선주" in name:
        return True
    
    # 스팩, 리츠, ETF/ETN 판별
    if any(keyword in name for keyword in ["SPAC", "스팩", "REIT", "리츠", "ETF", "ETN"]):
        return True
    
    # 거래정지 또는 거래량 0
    last_volume = row.get("last_volume")
    if pd.isna(last_volume) or last_volume == 0:
        return True
    
    return False


def calculate_candidate_score(row: pd.Series) -> dict:
    """
    점수 계산 및 플래그 설정
    score: 기본 100점에서 출발
    - return_1m_pct와 position_in_3m_range_pct를 바탕으로 과열도 판별
    - avg20_trading_value 또는 low_liquidity로 유동성 판별
    """
    score = 100.0
    overheat_flag = False
    liquidity_flag = False
    reason_list = []
    
    # 1. 과열도(Overheat) 판별: 1개월 수익률이 과도하거나 현재가가 3m 고점 근처
    return_1m = row.get("return_1m_pct")
    position_in_range = row.get("position_in_3m_range_pct")
    
    if not pd.isna(return_1m):
        if return_1m > 30:  # 1개월 수익률 30% 이상
            overheat_flag = True
            score -= 15
            reason_list.append(f"1m_return={return_1m}%")
        elif return_1m > 20:
            score -= 10
            reason_list.append(f"1m_return={return_1m}%")
    
    if not pd.isna(position_in_range):
        if position_in_range > 90:  # 3m 고점 90% 이상
            overheat_flag = True
            score -= 15
            reason_list.append(f"high_pos={position_in_range}%")
        elif position_in_range > 80:
            score -= 10
            reason_list.append(f"high_pos={position_in_range}%")
    
    # 2. 유동성 판별
    avg20_tv = row.get("avg20_trading_value")
    low_liq = row.get("low_liquidity", False)
    
    if low_liq or (not pd.isna(avg20_tv) and avg20_tv < 5000000000):  # 50억 이하
        liquidity_flag = True
        score -= 20
        reason_list.append("low_liquidity")
    
    # 3. 긍정 요소: 평균 거래대금, 변동성
    if not pd.isna(avg20_tv) and avg20_tv > 100000000000:  # 1000억 이상
        score += 10
        reason_list.append("high_trading_value")
    
    avg_daily_move_pct = row.get("avg_daily_move_pct")
    if not pd.isna(avg_daily_move_pct):
        if 1.5 < avg_daily_move_pct < 3.5:  # 적절한 변동성
            score += 5
        elif avg_daily_move_pct > 5:  # 과도한 변동성
            score -= 5
            reason_list.append("high_volatility")
    
    # 4. 3m 범위 위치 선호도
    if not pd.isna(position_in_range):
        if 35 <= position_in_range <= 65:  # 적절한 범위
            score += 8
        elif 20 <= position_in_range <= 35:
            score += 3
    
    return {
        "score": round(score, 2),
        "overheat_flag": overheat_flag,
        "liquidity_flag": liquidity_flag,
        "reason": "|".join(reason_list) if reason_list else "normal"
    }


def build_candidates_from_kospi(kospi: pd.DataFrame, log_lines: List[str]) -> pd.DataFrame:
    """
    KOSPI 전체 종목에서 후보 30개, 추천 7개를 생성
    """
    if kospi is None or kospi.empty:
        log_lines.append("CANDIDATES: kospi empty")
        return pd.DataFrame(columns=CANDIDATES_COLUMNS)
    
    # 제외 조건 필터링
    kospi_filtered = kospi[~kospi.apply(is_excluded_stock, axis=1)].copy()
    log_lines.append(f"CANDIDATES: filtered from {len(kospi)} to {len(kospi_filtered)} (excluded stocks)")
    
    if kospi_filtered.empty:
        log_lines.append("CANDIDATES: no stocks after filtering")
        return pd.DataFrame(columns=CANDIDATES_COLUMNS)
    
    # 각 종목에 대해 score 계산
    candidate_data = []
    for idx, row in kospi_filtered.iterrows():
        score_info = calculate_candidate_score(row)
        
        # 포맷팅
        close = row.get("current_close")
        avg_move_abs = row.get("avg_daily_move_abs")
        avg_move_pct = row.get("avg_daily_move_pct")
        
        if not pd.isna(avg_move_abs) and not pd.isna(avg_move_pct):
            avg_daily_move_text = f"약 ±{int(avg_move_abs):,}원 내외 (±{avg_move_pct}%)"
        else:
            avg_daily_move_text = ""
        
        split_low = row.get("split_buy_low_ref")
        split_high = row.get("split_buy_high_ref")
        buy_range = f"{int(split_low):,}~{int(split_high):,}" if not pd.isna(split_low) and not pd.isna(split_high) else ""
        
        target1 = row.get("target1_ref")
        target2 = row.get("target2_ref")
        sell_range = f"{int(target1):,}~{int(target2):,}" if not pd.isna(target1) and not pd.isna(target2) else ""
        
        candidate_data.append({
            "code": row.get("ticker"),
            "name": row.get("name"),
            "market": row.get("market"),
            "asof_date": row.get("last_date"),
            "close": int(close) if not pd.isna(close) else None,
            "buy_range": buy_range,
            "sell_range": sell_range,
            "avg_daily_move_text": avg_daily_move_text,
            "avg_wave_days": row.get("avg_wave_days"),
            "stop_price": int(row.get("stop_ref")) if not pd.isna(row.get("stop_ref")) else None,
            "low_3m": int(row.get("low_3m_intraday")) if not pd.isna(row.get("low_3m_intraday")) else None,
            "high_3m": int(row.get("high_3m_intraday")) if not pd.isna(row.get("high_3m_intraday")) else None,
            "range_pct": row.get("range_3m_pct"),
            "position_in_3m_range_pct": row.get("position_in_3m_range_pct"),
            "return_1m_pct": row.get("return_1m_pct"),
            "return_3m_pct": row.get("return_3m_pct"),
            "avg_volume": int(row.get("last_volume")) if not pd.isna(row.get("last_volume")) else None,
            "avg_trading_value": int(row.get("avg20_trading_value")) if not pd.isna(row.get("avg20_trading_value")) else None,
            "liquidity_flag": score_info["liquidity_flag"],
            "overheat_flag": score_info["overheat_flag"],
            "score": score_info["score"],
            "reason": score_info["reason"],
        })
    
    candidates_df = pd.DataFrame(candidate_data)
    
    # score 내림차순 정렬
    candidates_df = candidates_df.sort_values("score", ascending=False).reset_index(drop=True)
    
    # 상위 30개 추출 (kospi_candidates_30)
    candidates_30 = candidates_df.head(30).copy()
    candidates_30.insert(0, "rank", range(1, len(candidates_30) + 1))
    candidates_30.insert(1, "recommend_flag", "🟡")  # 기본값
    
    log_lines.append(f"CANDIDATES: top 30 selected, rows={len(candidates_30)}")
    
    # 추천 7개 선정 (kospi_recommend_7)
    # score, 유동성, 과열도, 변동성을 종합
    # liquidity_flag=False, overheat_flag=False인 종목 우선
    # 변동성(avg_daily_move_pct)이 적당한 범위인 종목 우선
    
    def recommend_score(row):
        base = row["score"]
        # 유동성이 좋으면 가산
        if not row["liquidity_flag"]:
            base += 20
        # 과열 없으면 가산
        if not row["overheat_flag"]:
            base += 15
        # 변동성 체크
        vol = row["avg_daily_move_pct"]
        if not pd.isna(vol) and 1.5 < vol < 3.5:
            base += 10
        return base
    
    candidates_30["recommend_score"] = candidates_30.apply(recommend_score, axis=1)
    recommend_7 = candidates_30.nsmallest(7, "recommend_score").copy()
    recommend_7 = recommend_7.sort_values("score", ascending=False).reset_index(drop=True)
    recommend_7["rank"] = range(1, len(recommend_7) + 1)
    recommend_7["recommend_flag"] = "✅"
    
    log_lines.append(f"RECOMMEND: top 7 selected, rows={len(recommend_7)}")
    
    # 다시 candidates_30의 recommend_flag 업데이트
    recommend_codes = set(recommend_7["code"].values)
    candidates_30.loc[candidates_30["code"].isin(recommend_codes), "recommend_flag"] = "✅"
    
    # recommend_score 컬럼 제거
    candidates_30 = candidates_30.drop(columns=["recommend_score"])
    recommend_7 = recommend_7.drop(columns=["recommend_score"])
    
    # 컬럼 순서 정리
    candidates_30 = candidates_30[CANDIDATES_COLUMNS]
    recommend_7 = recommend_7[CANDIDATES_COLUMNS]
    
    return candidates_30, recommend_7


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

        # 코피표 후보 및 추천 생성
        if kospi is not None and not kospi.empty:
            candidates_30, recommend_7 = build_candidates_from_kospi(kospi, log_lines)
            save_if_not_empty(candidates_30, outdir / "kospi_candidates_30_latest.csv", log_lines, "kospi_candidates_30")
            save_if_not_empty(recommend_7, outdir / "kospi_recommend_7_latest.csv", log_lines, "kospi_recommend_7")
        else:
            log_lines.append("kospi_candidates_30 and kospi_recommend_7 skipped: kospi empty")

        # 지수 요약은 이번 버전에서 생략한다. 코피/코닥/코급 핵심 파일 성공을 우선한다.
        log_lines.append("market_index_summary skipped in v4.4_with_candidates")
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
