#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코피표·코닥표·코급표용 KRX 전체시장 자동 수집기 v4

v4 핵심 변경
- KRX CSV-OTP 스크래핑과 pykrx fallback 의존 제거
- 공식 KRX Open API 사용
- GitHub Actions Secret: KRX_AUTH_KEY 필요
- 신청 필요 API
  1) 유가증권 일별매매정보: stk_bydd_trd
  2) 코스닥 일별매매정보: ksq_bydd_trd
  3) 선택: KOSPI 지수 일별시세정보: kospi_dd_trd
  4) 선택: KOSDAQ 지수 일별시세정보: kosdaq_dd_trd
- 새 데이터가 0행이면 기존 정상 CSV를 빈 파일로 덮어쓰지 않음

생성/갱신 파일
- latest/universe_raw_history_latest.csv
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv
- latest/kospi_gainers_1m_latest.csv
- latest/market_index_summary_latest.csv
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
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv


OPENAPI_STOCK_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
}

OPENAPI_INDEX_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/idx/kosdaq_dd_trd",
}


# -----------------------------
# 기본 유틸
# -----------------------------

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


def clean_number(x):
    if x is None or pd.isna(x):
        return np.nan
    s = str(x).strip()
    s = s.replace(",", "").replace("'", "").replace(" ", "")
    if s in ["", "-", "nan", "None"]:
        return np.nan
    return pd.to_numeric(s, errors="coerce")


def clean_number_series(s: pd.Series) -> pd.Series:
    return s.map(clean_number)


def normalize_ticker(x) -> str:
    """
    KRX Open API 출력의 ISU_CD가 6자리 단축코드일 때도 있고,
    ISIN 형태일 때도 있어 최대한 안전하게 6자리 종목코드로 변환한다.
    예: 005930 -> 005930
        KR7005930003 -> 005930
    """
    if x is None or pd.isna(x):
        return ""
    s = str(x).strip().replace("'", "")
    if re.fullmatch(r"\d{6}", s):
        return s
    if s.startswith("KR") and len(s) >= 9:
        cand = s[3:9]
        if re.fullmatch(r"\d{6}", cand):
            return cand
    m = re.search(r"\d{6}", s)
    if m:
        return m.group(0)
    return s.zfill(6)[-6:]


def find_col(columns: List[str], candidates: List[str]) -> Optional[str]:
    normalized = {str(c).upper(): c for c in columns}
    for cand in candidates:
        cand_u = cand.upper()
        if cand_u in normalized:
            return normalized[cand_u]
    for cand in candidates:
        cand_u = cand.upper()
        for c in columns:
            if cand_u in str(c).upper():
                return c
    return None


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
    if g is None or g.empty or "date" not in g.columns:
        return None
    part = g[g["date"] >= target_date].sort_values("date")
    if part.empty:
        return None
    return float(part["close"].iloc[0])


def empty_summary_columns() -> pd.DataFrame:
    cols = [
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
    return pd.DataFrame(columns=cols)


# -----------------------------
# KRX Open API 수집
# -----------------------------

def request_krx_openapi(url: str, auth_key: str, bas_dd: str, log_lines: List[str], label: str) -> pd.DataFrame:
    headers = {"AUTH_KEY": auth_key}
    params = {"basDd": bas_dd}
    r = requests.get(url, params=params, headers=headers, timeout=40)

    if r.status_code != 200:
        log_lines.append(f"OPENAPI_FAIL {label} {bas_dd}: status={r.status_code}, body={r.text[:200]}")
        return pd.DataFrame()

    try:
        data = r.json()
    except Exception as e:
        log_lines.append(f"OPENAPI_JSON_FAIL {label} {bas_dd}: {repr(e)}, body={r.text[:200]}")
        return pd.DataFrame()

    # 정상 응답은 보통 OutBlock_1에 들어 있다.
    rows = data.get("OutBlock_1")
    if rows is None:
        # 혹시 구조가 바뀐 경우 list 타입 값을 찾아본다.
        for v in data.values():
            if isinstance(v, list):
                rows = v
                break

    if not rows:
        msg = data.get("message") or data.get("MSG") or data.get("errMsg") or ""
        log_lines.append(f"OPENAPI_EMPTY {label} {bas_dd}: keys={list(data.keys())}, message={msg}")
        return pd.DataFrame()

    return pd.DataFrame(rows)


def normalize_openapi_stock(raw: pd.DataFrame, market: str, bas_dd: str, log_lines: List[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    cols = list(raw.columns)
    log_lines.append(f"OPENAPI_COLS {market} {bas_dd}: {cols}")

    code_col = find_col(cols, ["ISU_SRT_CD", "ISU_CD", "종목코드", "단축코드"])
    name_col = find_col(cols, ["ISU_ABBRV", "ISU_NM", "종목명", "한글종목명"])
    open_col = find_col(cols, ["TDD_OPNPRC", "OPNPRC", "시가"])
    high_col = find_col(cols, ["TDD_HGPRC", "HGPRC", "고가"])
    low_col = find_col(cols, ["TDD_LWPRC", "LWPRC", "저가"])
    close_col = find_col(cols, ["TDD_CLSPRC", "CLSPRC", "종가", "현재가"])
    volume_col = find_col(cols, ["ACC_TRDVOL", "TRDVOL", "거래량"])
    trading_value_col = find_col(cols, ["ACC_TRDVAL", "TRDVAL", "거래대금"])
    market_cap_col = find_col(cols, ["MKTCAP", "시가총액"])
    shares_col = find_col(cols, ["LIST_SHRS", "상장주식수"])

    if code_col is None or close_col is None:
        log_lines.append(f"OPENAPI_NORMALIZE_FAIL {market} {bas_dd}: code_col={code_col}, close_col={close_col}, cols={cols}")
        return pd.DataFrame()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(bas_dd)
    out["market"] = market
    out["ticker"] = raw[code_col].map(normalize_ticker)
    out["name"] = raw[name_col].astype(str) if name_col else out["ticker"]

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

    out = out.dropna(subset=["close"])
    out = out[out["ticker"].astype(str).str.fullmatch(r"\d{6}")]
    return out


def collect_history_by_openapi(start_dt: date, end_dt: date, auth_key: str, log_lines: List[str]) -> pd.DataFrame:
    frames = []
    if not auth_key:
        log_lines.append("OPENAPI_AUTH_KEY_MISSING: GitHub Secret KRX_AUTH_KEY가 비어 있음")
        return pd.DataFrame()

    for d in pd.date_range(start_dt, end_dt, freq="B"):
        ds = ymd(d)
        for market, url in OPENAPI_STOCK_URLS.items():
            try:
                raw = request_krx_openapi(url, auth_key, ds, log_lines, f"{market}_stock")
                one = normalize_openapi_stock(raw, market, ds, log_lines)
                if not one.empty:
                    frames.append(one)
                    log_lines.append(f"OPENAPI {market} {ds}: rows={len(one)}")
                    print(f"[OPENAPI] {market} {ds}: rows={len(one)}")
                else:
                    log_lines.append(f"OPENAPI {market} {ds}: empty after normalize")
                    print(f"[OPENAPI_EMPTY] {market} {ds}")
            except Exception as e:
                log_lines.append(f"OPENAPI_FAIL {market} {ds}: {repr(e)}")
                print(f"[OPENAPI_FAIL] {market} {ds}: {e}")
            time.sleep(0.15)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# -----------------------------
# 시장별 요약 생성
# -----------------------------

def summarize_market(hist: pd.DataFrame, market: str, low_liq_krw: float) -> pd.DataFrame:
    """
    Open API 원자료를 시장별 요약표로 변환한다.
    v4.1 수정점
    - market 값이 KOSPI/KOSDAQ, 유가증권, 코스닥 등 어떤 형태여도 최대한 인식
    - date/가격/거래량 컬럼을 요약 직전에 다시 숫자형으로 정규화
    - 원자료가 있는데 summary가 0행으로 끝나는 문제 방지
    """
    if hist is None or hist.empty:
        return empty_summary_columns()

    df_all = hist.copy()

    if "date" not in df_all.columns:
        if "BAS_DD" in df_all.columns:
            df_all["date"] = pd.to_datetime(df_all["BAS_DD"].astype(str), errors="coerce")
        else:
            return empty_summary_columns()
    else:
        df_all["date"] = pd.to_datetime(df_all["date"], errors="coerce")

    if "market" not in df_all.columns:
        if "MKT_NM" in df_all.columns:
            df_all["market"] = df_all["MKT_NM"]
        else:
            df_all["market"] = ""

    m = df_all["market"].astype(str).str.upper().str.strip()
    df_all["market_norm"] = np.where(
        m.str.contains("KOSDAQ|코스닥", case=False, na=False),
        "KOSDAQ",
        np.where(m.str.contains("KOSPI|유가|유가증권", case=False, na=False), "KOSPI", m),
    )

    market_norm = market.upper().strip()
    df = df_all[df_all["market_norm"].eq(market_norm)].copy()

    if df.empty and "MKT_NM" in df_all.columns:
        mm = df_all["MKT_NM"].astype(str).str.upper().str.strip()
        if market_norm == "KOSPI":
            df = df_all[mm.str.contains("KOSPI|유가|유가증권", case=False, na=False)].copy()
        elif market_norm == "KOSDAQ":
            df = df_all[mm.str.contains("KOSDAQ|코스닥", case=False, na=False)].copy()

    if df.empty:
        return empty_summary_columns()

    if "ticker" not in df.columns:
        if "ISU_CD" in df.columns:
            df["ticker"] = df["ISU_CD"].map(normalize_ticker)
        elif "ISU_SRT_CD" in df.columns:
            df["ticker"] = df["ISU_SRT_CD"].map(normalize_ticker)
        else:
            return empty_summary_columns()
    df["ticker"] = df["ticker"].astype(str).map(normalize_ticker)

    if "name" not in df.columns:
        if "ISU_NM" in df.columns:
            df["name"] = df["ISU_NM"].astype(str)
        elif "ISU_ABBRV" in df.columns:
            df["name"] = df["ISU_ABBRV"].astype(str)
        else:
            df["name"] = df["ticker"]

    numeric_cols = ["open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]
    fallback_map = {
        "open": ["TDD_OPNPRC", "OPNPRC"],
        "high": ["TDD_HGPRC", "HGPRC"],
        "low": ["TDD_LWPRC", "LWPRC"],
        "close": ["TDD_CLSPRC", "CLSPRC"],
        "volume": ["ACC_TRDVOL", "TRDVOL"],
        "trading_value": ["ACC_TRDVAL", "TRDVAL"],
        "market_cap": ["MKTCAP"],
        "listed_shares": ["LIST_SHRS"],
    }
    for col in numeric_cols:
        if col not in df.columns:
            source = find_col(list(df.columns), fallback_map.get(col, []))
            df[col] = clean_number_series(df[source]) if source else np.nan
        else:
            df[col] = clean_number_series(df[col])

    df = df.dropna(subset=["date", "ticker", "close"])
    df = df[df["ticker"].astype(str).str.fullmatch(r"[0-9]{6}", na=False)]
    df = df.sort_values(["ticker", "date"])

    if df.empty:
        return empty_summary_columns()

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

        avg20_tv = g["trading_value"].tail(20).mean() if "trading_value" in g.columns else np.nan
        last_tv = last["trading_value"] if "trading_value" in g.columns else np.nan
        last_name = str(last["name"]) if "name" in g.columns else ticker

        rows.append({
            "name": last_name,
            "ticker": ticker,
            "market": market_norm,
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
            "last_volume": int(last["volume"]) if "volume" in g.columns and not pd.isna(last["volume"]) else None,
            "last_trading_value": int(last_tv) if not pd.isna(last_tv) else None,
            "avg20_trading_value": int(avg20_tv) if not pd.isna(avg20_tv) else None,
            "low_liquidity": bool(not pd.isna(avg20_tv) and avg20_tv < low_liq_krw),
            "market_cap": int(last["market_cap"]) if "market_cap" in g.columns and not pd.isna(last["market_cap"]) else None,
            "listed_shares": int(last["listed_shares"]) if "listed_shares" in g.columns and not pd.isna(last["listed_shares"]) else None,
            "data_rows": int(len(g)),
            "source_used": "krx_openapi",
        })

    if not rows:
        return empty_summary_columns()

    return pd.DataFrame(rows).sort_values(["name", "ticker"]).reset_index(drop=True)


# -----------------------------
# 시장지수 요약: 선택 기능
# -----------------------------

def normalize_openapi_index(raw: pd.DataFrame, label: str, bas_dd: str, log_lines: List[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    cols = list(raw.columns)
    log_lines.append(f"INDEX_OPENAPI_COLS {label} {bas_dd}: {cols}")

    name_col = find_col(cols, ["IDX_NM", "지수명", "지수명칭"])
    code_col = find_col(cols, ["IDX_CD", "지수코드"])
    close_col = find_col(cols, ["CLSPRC_IDX", "TDD_CLSPRC", "종가", "현재가"])
    high_col = find_col(cols, ["HGPRC_IDX", "TDD_HGPRC", "고가"])
    low_col = find_col(cols, ["LWPRC_IDX", "TDD_LWPRC", "저가"])

    if close_col is None:
        log_lines.append(f"INDEX_OPENAPI_NORMALIZE_FAIL {label} {bas_dd}: close_col missing, cols={cols}")
        return pd.DataFrame()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(bas_dd)
    out["index_group"] = label
    out["index_name"] = raw[name_col].astype(str) if name_col else label
    out["index_code"] = raw[code_col].astype(str) if code_col else label
    out["close"] = clean_number_series(raw[close_col])
    out["high"] = clean_number_series(raw[high_col]) if high_col else out["close"]
    out["low"] = clean_number_series(raw[low_col]) if low_col else out["close"]
    return out.dropna(subset=["close"])


def collect_index_summary(start_dt: date, end_dt: date, auth_key: str, log_lines: List[str]) -> pd.DataFrame:
    cols = [
        "index_name", "index_code", "last_date", "current_close",
        "low_3m", "high_3m", "range_3m_pct",
        "return_1m_pct", "return_3m_pct", "avg_daily_move_pct",
        "data_rows", "source_used",
    ]
    if not auth_key:
        return pd.DataFrame(columns=cols)

    frames = []
    for d in pd.date_range(start_dt, end_dt, freq="B"):
        ds = ymd(d)
        for label, url in OPENAPI_INDEX_URLS.items():
            raw = request_krx_openapi(url, auth_key, ds, log_lines, f"{label}_index")
            one = normalize_openapi_index(raw, label, ds, log_lines)
            if not one.empty:
                frames.append(one)
            time.sleep(0.05)

    if not frames:
        return pd.DataFrame(columns=cols)

    hist = pd.concat(frames, ignore_index=True)
    rows = []
    # 대표 지수만 우선: 이름에 KOSPI/KOSDAQ 또는 코스피/코스닥이 들어가는 첫 행 우선
    for label in ["KOSPI", "KOSDAQ"]:
        part = hist[hist["index_group"].eq(label)].copy()
        if part.empty:
            continue
        mask = part["index_name"].str.contains(label, case=False, na=False) | part["index_name"].str.contains("코스피|코스닥", regex=True, na=False)
        if mask.any():
            name = part[mask]["index_name"].iloc[0]
            part = part[part["index_name"].eq(name)]
        else:
            name = part["index_name"].iloc[0]
            part = part[part["index_name"].eq(name)]

        part = part.sort_values("date")
        last = float(part["close"].iloc[-1])
        low = float(part["low"].min())
        high = float(part["high"].max())
        avg_pct = (part["close"].pct_change().abs() * 100).dropna().mean()
        ref_1m = find_close_on_or_after(part.rename(columns={"close": "close"}), part["date"].max() - relativedelta(months=1))
        rows.append({
            "index_name": name,
            "index_code": part["index_code"].iloc[-1],
            "last_date": iso(part["date"].max()),
            "current_close": round(last, 2),
            "low_3m": round(low, 2),
            "high_3m": round(high, 2),
            "range_3m_pct": round((high - low) / low * 100, 2) if low else None,
            "return_1m_pct": safe_return_pct(last, ref_1m),
            "return_3m_pct": safe_return_pct(last, float(part["close"].iloc[0])),
            "avg_daily_move_pct": round(float(avg_pct), 2) if not pd.isna(avg_pct) else None,
            "data_rows": len(part),
            "source_used": "krx_openapi",
        })

    return pd.DataFrame(rows, columns=cols)


# -----------------------------
# 저장 유틸
# -----------------------------

def save_if_not_empty(df: pd.DataFrame, path: Path, log_lines: List[str], label: str) -> None:
    if df is not None and not df.empty:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        log_lines.append(f"{label}={path}, rows={len(df)}")
        print(f"[SAVE] {path} rows={len(df)}")
    else:
        log_lines.append(f"{label} not overwritten: new data rows=0")
        print(f"[SKIP_SAVE] {path} new rows=0")


# -----------------------------
# 메인 실행
# -----------------------------

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
        "script=collect_universe.py v4_openapi",
        f"KRX_AUTH_KEY_present={bool(auth_key)}",
    ]

    try:
        hist = collect_history_by_openapi(start_dt, end_dt, auth_key, log_lines)

        raw_path = outdir / "universe_raw_history_latest.csv"
        save_if_not_empty(hist, raw_path, log_lines, "universe_raw_history")

        kospi = summarize_market(hist, "KOSPI", low_liq_krw)
        kosdaq = summarize_market(hist, "KOSDAQ", low_liq_krw)

        kospi_path = outdir / "kospi_universe_summary_latest.csv"
        kosdaq_path = outdir / "kosdaq_universe_summary_latest.csv"
        save_if_not_empty(kospi, kospi_path, log_lines, "KOSPI_summary")
        save_if_not_empty(kosdaq, kosdaq_path, log_lines, "KOSDAQ_summary")

        # 코급표용 최근 1개월 상승률 상위 20개
        gainers_path = outdir / "kospi_gainers_1m_latest.csv"
        if not kospi.empty and "return_1m_pct" in kospi.columns:
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
        save_if_not_empty(gainers, gainers_path, log_lines, "kospi_gainers_1m")

        idx = collect_index_summary(start_dt, end_dt, auth_key, log_lines)
        idx_path = outdir / "market_index_summary_latest.csv"
        save_if_not_empty(idx, idx_path, log_lines, "market_index_summary")

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
