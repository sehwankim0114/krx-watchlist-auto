#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
market_status.py

KRX 전체시장 원자료(universe_raw_history_latest.csv)를 기반으로
국내 증시 과열·시장폭·쏠림·최신거래일 상태를 점검하기 위한 보조 파일을 생성한다.

v1.1 보완
1) 첫 실행을 새 거래일로 착각하지 않도록 BOOTSTRAP_BASELINE 상태 추가
2) 닷컴버블형 위험 신호를 자동 점수화하여 bubble_risk_latest.json 생성
3) 위험 신호 상세표 bubble_risk_signals_latest.csv 생성

생성 파일
- latest/data_status_latest.json
- latest/market_breadth_history_latest.csv
- latest/market_index_history_latest.csv
- latest/market_index_summary_latest.csv
- latest/bubble_risk_latest.json
- latest/bubble_risk_signals_latest.csv
- latest/market_status_run_log_latest.txt

주의
- 이 스크립트는 기존 collect_universe.py를 수정하지 않는다.
- KRX 전종목 원자료를 우선 사용한다.
- market_index_history는 공식 KOSPI/KOSDAQ 지수값이 아니라,
  전종목 시가총액 가중 수익률로 만든 시장 프록시 지수다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "market_status.py v1.1_bootstrap_bubble_risk"

RAW_FILENAME = "universe_raw_history_latest.csv"

SAMSUNG_ELECTRONICS = "005930"
SK_HYNIX = "000660"


RISK_THRESHOLDS = {
    "kospi_1m_overheat_pct": 20.0,
    "kospi_3m_overheat_pct": 35.0,
    "kospi_3m_extreme_pct": 50.0,
    "weak_breadth_up_ratio_pct": 35.0,
    "weak_breadth_down_ratio_pct": 60.0,
    "samsung_hynix_concentration_pct": 45.0,
    "samsung_hynix_extreme_pct": 50.0,
    "kospi_kosdaq_1m_gap_pct": 25.0,
    "kosdaq_1m_weak_pct": -8.0,
    "trading_value_spike_ratio": 1.5,
}


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def read_json_safely(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()

    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        if pd.isna(value):
            return None
        return float(value)

    if isinstance(value, float):
        if pd.isna(value):
            return None
        return value

    if value is pd.NA:
        return None

    return value


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_ticker(x: Any) -> str:
    if x is None or pd.isna(x):
        return ""
    s = str(x).strip().replace("'", "")
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(6) if s.isdigit() else s


def clean_number_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace({"": np.nan, "-": np.nan, "nan": np.nan, "None": np.nan}),
        errors="coerce",
    )


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def normalize_raw_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()

    required_cols = ["date", "market", "ticker", "close"]
    for col in required_cols:
        if col not in df.columns:
            return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["market"] = df["market"].astype(str).str.upper().str.strip()
    df["ticker"] = df["ticker"].map(normalize_ticker)

    if "name" not in df.columns:
        df["name"] = df["ticker"].astype(str)

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trading_value",
        "market_cap",
        "listed_shares",
    ]

    for col in numeric_cols:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = clean_number_series(df[col])

    df = df.dropna(subset=["date", "market", "ticker", "close"])
    df = df[df["ticker"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    df = df[df["market"].isin(["KOSPI", "KOSDAQ"])]

    return df.sort_values(["market", "ticker", "date"]).reset_index(drop=True)


def build_breadth_history(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty:
        return pd.DataFrame()

    df = hist.copy()
    df = df.sort_values(["market", "ticker", "date"]).reset_index(drop=True)
    df["prev_close"] = df.groupby(["market", "ticker"])["close"].shift(1)
    df["daily_return_pct"] = (df["close"] / df["prev_close"] - 1) * 100

    rows: List[Dict[str, Any]] = []

    for (market, dt), g in df.groupby(["market", "date"], sort=True):
        valid = g.dropna(subset=["daily_return_pct"])

        total_count = int(len(valid))
        up_count = int((valid["daily_return_pct"] > 0).sum())
        down_count = int((valid["daily_return_pct"] < 0).sum())
        flat_count = int((valid["daily_return_pct"] == 0).sum())

        total_trading_value = g["trading_value"].sum(skipna=True)
        total_market_cap = g["market_cap"].sum(skipna=True)

        cap_sorted = g.dropna(subset=["market_cap"]).sort_values("market_cap", ascending=False)
        top2_cap = cap_sorted["market_cap"].head(2).sum(skipna=True)
        top10_cap = cap_sorted["market_cap"].head(10).sum(skipna=True)

        samsung_hynix_ratio = np.nan

        if market == "KOSPI":
            samsung_hynix_cap = g[g["ticker"].isin([SAMSUNG_ELECTRONICS, SK_HYNIX])]["market_cap"].sum(skipna=True)
            if total_market_cap and total_market_cap > 0:
                samsung_hynix_ratio = samsung_hynix_cap / total_market_cap * 100

        rows.append(
            {
                "date": pd.to_datetime(dt).date().isoformat(),
                "market": market,
                "total_count": total_count,
                "up_count": up_count,
                "down_count": down_count,
                "flat_count": flat_count,
                "up_ratio_pct": round(up_count / total_count * 100, 2) if total_count else None,
                "down_ratio_pct": round(down_count / total_count * 100, 2) if total_count else None,
                "up_down_ratio": round(up_count / down_count, 3) if down_count else None,
                "total_trading_value": int(total_trading_value) if pd.notna(total_trading_value) else None,
                "total_market_cap": int(total_market_cap) if pd.notna(total_market_cap) else None,
                "top2_market_cap_ratio_pct": round(top2_cap / total_market_cap * 100, 2) if total_market_cap and total_market_cap > 0 else None,
                "top10_market_cap_ratio_pct": round(top10_cap / total_market_cap * 100, 2) if total_market_cap and total_market_cap > 0 else None,
                "samsung_hynix_market_cap_ratio_pct": round(samsung_hynix_ratio, 2) if pd.notna(samsung_hynix_ratio) else None,
            }
        )

    return pd.DataFrame(rows)


def build_proxy_index_history(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty:
        return pd.DataFrame()

    df = hist.copy()
    df = df.sort_values(["market", "ticker", "date"]).reset_index(drop=True)

    df["prev_close"] = df.groupby(["market", "ticker"])["close"].shift(1)
    df["prev_market_cap"] = df.groupby(["market", "ticker"])["market_cap"].shift(1)
    df["daily_return"] = df["close"] / df["prev_close"] - 1

    rows: List[Dict[str, Any]] = []

    for (market, dt), g in df.groupby(["market", "date"], sort=True):
        valid = g.dropna(subset=["daily_return", "prev_market_cap"])
        valid = valid[valid["prev_market_cap"] > 0]

        if valid.empty:
            daily_return = 0.0
        else:
            daily_return = np.average(valid["daily_return"], weights=valid["prev_market_cap"])

        rows.append(
            {
                "date": pd.to_datetime(dt),
                "market": market,
                "proxy_daily_return_pct": round(float(daily_return * 100), 4),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    index_rows: List[pd.DataFrame] = []

    for market, g in out.groupby("market", sort=False):
        g = g.sort_values("date").copy()
        g["proxy_index_close"] = 1000 * (1 + g["proxy_daily_return_pct"] / 100).cumprod()
        g["proxy_index_close"] = g["proxy_index_close"].round(2)
        index_rows.append(g)

    result = pd.concat(index_rows, ignore_index=True)
    result["date"] = result["date"].dt.date.astype(str)

    return result.sort_values(["market", "date"]).reset_index(drop=True)


def get_first_value_on_or_after(g: pd.DataFrame, date_col: str, value_col: str, target_date: pd.Timestamp):
    part = g[pd.to_datetime(g[date_col]) >= target_date]
    if part.empty:
        return np.nan
    return part.iloc[0][value_col]


def get_trading_value_20d_stats(breadth: pd.DataFrame, market: str, last_date: pd.Timestamp) -> Dict[str, Any]:
    if breadth.empty:
        return {
            "total_trading_value_20d_avg": None,
            "trading_value_vs_20d_avg": None,
        }

    b = breadth.copy()
    b["date_dt"] = pd.to_datetime(b["date"], errors="coerce")
    b = b[(b["market"].eq(market)) & (b["date_dt"] <= last_date)].sort_values("date_dt")

    last_20 = b.tail(20)
    if last_20.empty:
        return {
            "total_trading_value_20d_avg": None,
            "trading_value_vs_20d_avg": None,
        }

    avg_20 = safe_float(last_20["total_trading_value"].mean())
    latest = safe_float(last_20.iloc[-1]["total_trading_value"])

    ratio = None
    if avg_20 and avg_20 > 0 and latest is not None:
        ratio = round(latest / avg_20, 3)

    return {
        "total_trading_value_20d_avg": int(avg_20) if avg_20 is not None else None,
        "trading_value_vs_20d_avg": ratio,
    }


def build_market_index_summary(index_hist: pd.DataFrame, breadth_hist: pd.DataFrame) -> pd.DataFrame:
    if index_hist.empty:
        return pd.DataFrame()

    idx = index_hist.copy()
    idx["date_dt"] = pd.to_datetime(idx["date"], errors="coerce")
    idx = idx.dropna(subset=["date_dt"])
    idx = idx.sort_values(["market", "date_dt"])

    breadth = breadth_hist.copy()
    if not breadth.empty:
        breadth["date_dt"] = pd.to_datetime(breadth["date"], errors="coerce")

    rows: List[Dict[str, Any]] = []

    for market, g in idx.groupby("market", sort=False):
        g = g.sort_values("date_dt").copy()
        last = g.iloc[-1]
        last_date = last["date_dt"]
        last_close = float(last["proxy_index_close"])

        one_month_ago = last_date - relativedelta(months=1)
        three_months_ago = last_date - relativedelta(months=3)

        close_1m = get_first_value_on_or_after(g, "date_dt", "proxy_index_close", one_month_ago)
        close_3m = get_first_value_on_or_after(g, "date_dt", "proxy_index_close", three_months_ago)

        ret_1m = round((last_close / float(close_1m) - 1) * 100, 2) if pd.notna(close_1m) and float(close_1m) > 0 else None
        ret_3m = round((last_close / float(close_3m) - 1) * 100, 2) if pd.notna(close_3m) and float(close_3m) > 0 else None

        b_row: Dict[str, Any] = {}
        if not breadth.empty:
            b = breadth[(breadth["market"].eq(market)) & (breadth["date_dt"].eq(last_date))]
            if not b.empty:
                b_row = b.iloc[0].to_dict()

        value_stats = get_trading_value_20d_stats(breadth_hist, market, last_date)

        rows.append(
            {
                "market": market,
                "asof_date": last_date.date().isoformat(),
                "index_source": "stock_market_cap_weighted_proxy",
                "proxy_index_close": round(last_close, 2),
                "proxy_daily_return_pct": last.get("proxy_daily_return_pct"),
                "proxy_return_1m_pct": ret_1m,
                "proxy_return_3m_pct": ret_3m,
                "up_count": b_row.get("up_count"),
                "down_count": b_row.get("down_count"),
                "up_ratio_pct": b_row.get("up_ratio_pct"),
                "down_ratio_pct": b_row.get("down_ratio_pct"),
                "up_down_ratio": b_row.get("up_down_ratio"),
                "total_trading_value": b_row.get("total_trading_value"),
                "total_trading_value_20d_avg": value_stats.get("total_trading_value_20d_avg"),
                "trading_value_vs_20d_avg": value_stats.get("trading_value_vs_20d_avg"),
                "total_market_cap": b_row.get("total_market_cap"),
                "top2_market_cap_ratio_pct": b_row.get("top2_market_cap_ratio_pct"),
                "top10_market_cap_ratio_pct": b_row.get("top10_market_cap_ratio_pct"),
                "samsung_hynix_market_cap_ratio_pct": b_row.get("samsung_hynix_market_cap_ratio_pct"),
            }
        )

    return pd.DataFrame(rows)


def decide_status(actual_data_last_date: pd.Timestamp, previous_actual_date: Optional[str], run_date: datetime) -> Dict[str, Any]:
    if actual_data_last_date is None or pd.isna(actual_data_last_date):
        return {
            "status": "NO_VALID_DATA",
            "new_confirmed_trading_day": False,
            "freshness_days": None,
            "status_reason": "유효한 원자료 날짜가 없습니다.",
        }

    actual_day = pd.Timestamp(actual_data_last_date.date())
    run_date_only = pd.Timestamp(run_date.date())
    freshness_days = int((run_date_only - actual_day).days)

    if not previous_actual_date:
        return {
            "status": "BOOTSTRAP_BASELINE",
            "new_confirmed_trading_day": False,
            "freshness_days": freshness_days,
            "status_reason": "첫 실행 기준값을 세운 상태입니다. 새 거래일 알림 판단에는 사용하지 않습니다.",
        }

    prev_day = pd.to_datetime(previous_actual_date, errors="coerce")

    if pd.isna(prev_day):
        return {
            "status": "BOOTSTRAP_BASELINE",
            "new_confirmed_trading_day": False,
            "freshness_days": freshness_days,
            "status_reason": "이전 기준일 형식을 읽지 못해 기준값을 다시 세웠습니다.",
        }

    prev_day = pd.Timestamp(prev_day.date())

    if actual_day > prev_day:
        status = "OK_NEW_CONFIRMED_TRADING_DAY"
        new_confirmed = True
        reason = "이전 실행보다 최신 확정 거래일이 새로 확인되었습니다."
    elif actual_day == prev_day:
        status = "STALE_BUT_VALID"
        new_confirmed = False
        reason = "새 확정 거래일은 아니지만 기존 원자료는 유효합니다."
    else:
        status = "DATA_DATE_REGRESSION"
        new_confirmed = False
        reason = "현재 원자료 기준일이 이전 기록보다 과거입니다. 원자료 갱신 상태 점검이 필요합니다."

    return {
        "status": status,
        "new_confirmed_trading_day": bool(new_confirmed),
        "freshness_days": freshness_days,
        "status_reason": reason,
    }


def row_by_market(summary: pd.DataFrame, market: str) -> Dict[str, Any]:
    if summary.empty:
        return {}
    part = summary[summary["market"].eq(market)]
    if part.empty:
        return {}
    row = part.iloc[0].to_dict()
    return {k: to_jsonable(v) for k, v in row.items()}


def add_signal(
    signals: List[Dict[str, Any]],
    code: str,
    title: str,
    market: str,
    value: Any,
    threshold: Any,
    severity: str,
    detail: str,
) -> None:
    signals.append(
        {
            "code": code,
            "title": title,
            "market": market,
            "value": to_jsonable(value),
            "threshold": threshold,
            "severity": severity,
            "detail": detail,
        }
    )


def classify_bubble_risk(summary: pd.DataFrame, data_status: Dict[str, Any]) -> Dict[str, Any]:
    kospi = row_by_market(summary, "KOSPI")
    kosdaq = row_by_market(summary, "KOSDAQ")

    signals: List[Dict[str, Any]] = []

    kospi_1m = safe_float(kospi.get("proxy_return_1m_pct"))
    kospi_3m = safe_float(kospi.get("proxy_return_3m_pct"))
    kospi_up = safe_float(kospi.get("up_ratio_pct"))
    kospi_down = safe_float(kospi.get("down_ratio_pct"))
    kospi_daily = safe_float(kospi.get("proxy_daily_return_pct"))
    sh_ratio = safe_float(kospi.get("samsung_hynix_market_cap_ratio_pct"))
    kospi_value_ratio = safe_float(kospi.get("trading_value_vs_20d_avg"))

    kosdaq_1m = safe_float(kosdaq.get("proxy_return_1m_pct"))
    kosdaq_up = safe_float(kosdaq.get("up_ratio_pct"))

    if kospi_1m is not None and kospi_1m >= RISK_THRESHOLDS["kospi_1m_overheat_pct"]:
        add_signal(
            signals,
            "KOSPI_1M_OVERHEAT",
            "KOSPI 1개월 급등 과열",
            "KOSPI",
            kospi_1m,
            f">= {RISK_THRESHOLDS['kospi_1m_overheat_pct']}%",
            "주의",
            "최근 1개월 프록시 지수 상승률이 과열 기준을 넘었습니다.",
        )

    if kospi_3m is not None and kospi_3m >= RISK_THRESHOLDS["kospi_3m_overheat_pct"]:
        severity = "강함" if kospi_3m >= RISK_THRESHOLDS["kospi_3m_extreme_pct"] else "주의"
        add_signal(
            signals,
            "KOSPI_3M_OVERHEAT",
            "KOSPI 3개월 급등 과열",
            "KOSPI",
            kospi_3m,
            f">= {RISK_THRESHOLDS['kospi_3m_overheat_pct']}%",
            severity,
            "최근 3개월 프록시 지수 상승률이 과열 기준을 넘었습니다.",
        )

    if kospi_up is not None and kospi_down is not None:
        if kospi_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"] and kospi_down >= RISK_THRESHOLDS["weak_breadth_down_ratio_pct"]:
            add_signal(
                signals,
                "KOSPI_BREADTH_WEAKNESS",
                "KOSPI 시장폭 악화",
                "KOSPI",
                f"상승 {kospi_up}%, 하락 {kospi_down}%",
                f"상승 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%, 하락 >= {RISK_THRESHOLDS['weak_breadth_down_ratio_pct']}%",
                "주의",
                "지수 흐름에 비해 상승 종목 비율이 낮고 하락 종목 비율이 높습니다.",
            )

    if kospi_daily is not None and kospi_up is not None:
        if kospi_daily > 0 and kospi_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"]:
            add_signal(
                signals,
                "KOSPI_DISTRIBUTION_STYLE_BREADTH",
                "지수 상승 중 내부 종목 약세",
                "KOSPI",
                f"일간 {kospi_daily}%, 상승종목 {kospi_up}%",
                f"일간 상승 & 상승종목 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%",
                "주의",
                "지수는 올랐지만 다수 종목이 따라오지 못하는 분배형 시장폭 신호입니다.",
            )

    if sh_ratio is not None and sh_ratio >= RISK_THRESHOLDS["samsung_hynix_concentration_pct"]:
        severity = "강함" if sh_ratio >= RISK_THRESHOLDS["samsung_hynix_extreme_pct"] else "주의"
        add_signal(
            signals,
            "SAMSUNG_HYNIX_CONCENTRATION",
            "삼성전자·SK하이닉스 시총 쏠림",
            "KOSPI",
            sh_ratio,
            f">= {RISK_THRESHOLDS['samsung_hynix_concentration_pct']}%",
            severity,
            "KOSPI 시가총액이 삼성전자·SK하이닉스에 과도하게 집중되어 있습니다.",
        )

    if kospi_1m is not None and kosdaq_1m is not None:
        gap = round(kospi_1m - kosdaq_1m, 2)
        if gap >= RISK_THRESHOLDS["kospi_kosdaq_1m_gap_pct"]:
            add_signal(
                signals,
                "KOSPI_KOSDAQ_DIVERGENCE",
                "KOSPI·KOSDAQ 1개월 괴리",
                "ALL",
                gap,
                f">= {RISK_THRESHOLDS['kospi_kosdaq_1m_gap_pct']}%p",
                "주의",
                "대형주 중심 KOSPI와 성장주 중심 KOSDAQ 간 괴리가 확대되었습니다.",
            )

    if kosdaq_1m is not None and kosdaq_up is not None:
        if kosdaq_1m <= RISK_THRESHOLDS["kosdaq_1m_weak_pct"] and kosdaq_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"]:
            add_signal(
                signals,
                "KOSDAQ_WEAKNESS",
                "KOSDAQ 약세와 시장폭 악화",
                "KOSDAQ",
                f"1개월 {kosdaq_1m}%, 상승종목 {kosdaq_up}%",
                f"1개월 <= {RISK_THRESHOLDS['kosdaq_1m_weak_pct']}%, 상승종목 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%",
                "주의",
                "KOSDAQ이 이미 약세 흐름에 들어가 있고 내부 시장폭도 약합니다.",
            )

    if kospi_value_ratio is not None and kospi_value_ratio >= RISK_THRESHOLDS["trading_value_spike_ratio"]:
        add_signal(
            signals,
            "KOSPI_TRADING_VALUE_SPIKE",
            "KOSPI 거래대금 급증",
            "KOSPI",
            kospi_value_ratio,
            f">= {RISK_THRESHOLDS['trading_value_spike_ratio']}배",
            "주의",
            "최근 거래대금이 20일 평균 대비 빠르게 증가했습니다.",
        )

    signal_count = len(signals)
    strong_signal_count = sum(1 for s in signals if s.get("severity") == "강함")

    if signal_count >= 5 or (strong_signal_count >= 1 and signal_count >= 4):
        risk_level = "위험"
    elif signal_count >= 3 or strong_signal_count >= 1:
        risk_level = "경계"
    elif signal_count >= 1:
        risk_level = "관찰"
    else:
        risk_level = "정상"

    alert_by_signals = risk_level in ["경계", "위험"]
    alert_required = bool(alert_by_signals and data_status.get("status") == "OK_NEW_CONFIRMED_TRADING_DAY")

    if alert_required:
        action_hint = "신용추가매수 중단, 현금확보, 고비중 주도주 일부 이익보호 검토가 필요합니다."
    elif alert_by_signals:
        action_hint = "위험 신호는 기준을 충족하지만 새 확정 거래일이 아니므로 자동 경고 알림은 보류합니다."
    else:
        action_hint = "경고 기준 미충족입니다. 정규 경고 알림은 보내지 않습니다."

    return {
        "script": SCRIPT_VERSION,
        "run_at": data_status.get("run_at"),
        "actual_data_last_date": data_status.get("actual_data_last_date"),
        "data_status": data_status.get("status"),
        "new_confirmed_trading_day": data_status.get("new_confirmed_trading_day"),
        "risk_level": risk_level,
        "signal_count": signal_count,
        "strong_signal_count": strong_signal_count,
        "alert_by_signals": bool(alert_by_signals),
        "alert_required": bool(alert_required),
        "signals": signals,
        "market_snapshot": {
            "KOSPI": kospi,
            "KOSDAQ": kosdaq,
        },
        "thresholds": RISK_THRESHOLDS,
        "action_hint": action_hint,
        "note": "위험등급은 KRX 전종목 원자료 기반 프록시 지수·시장폭·시총쏠림만으로 산출합니다. 신용융자, 환율, 금리, 외국인/기관 수급은 별도 확인이 필요합니다.",
    }


def empty_status(run_at: datetime, raw: pd.DataFrame, outdir: Path) -> None:
    data_status = {
        "script": SCRIPT_VERSION,
        "run_at": run_at.isoformat(timespec="seconds"),
        "requested_end_date": run_at.date().isoformat(),
        "actual_data_last_date": None,
        "previous_actual_data_last_date": None,
        "new_confirmed_trading_day": False,
        "freshness_days": None,
        "raw_rows": int(len(raw)) if raw is not None else 0,
        "normalized_rows": 0,
        "status": "NO_VALID_DATA",
        "status_reason": "universe_raw_history_latest.csv를 읽지 못했거나 필수 컬럼이 없습니다.",
        "note": "원자료 생성 상태를 먼저 확인해야 합니다.",
    }

    bubble_risk = {
        "script": SCRIPT_VERSION,
        "run_at": data_status["run_at"],
        "actual_data_last_date": None,
        "data_status": "NO_VALID_DATA",
        "risk_level": "판단불가",
        "signal_count": 0,
        "strong_signal_count": 0,
        "alert_by_signals": False,
        "alert_required": False,
        "signals": [],
        "action_hint": "원자료가 없어 위험 판단을 하지 않습니다.",
    }

    write_json(outdir / "data_status_latest.json", data_status)
    write_json(outdir / "bubble_risk_latest.json", bubble_risk)
    write_csv(pd.DataFrame(), outdir / "bubble_risk_signals_latest.csv")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-months", type=int, default=7)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    raw_path = outdir / RAW_FILENAME

    run_at = now_kst()
    log_lines: List[str] = []
    log_lines.append(f"script={SCRIPT_VERSION}")
    log_lines.append(f"run_at={run_at.isoformat(timespec='seconds')}")
    log_lines.append(f"raw_path={raw_path}")

    raw = read_csv_safely(raw_path)
    hist = normalize_raw_history(raw)

    if hist.empty:
        empty_status(run_at, raw, outdir)
        log_lines.append("status=NO_VALID_DATA")
        log_path = outdir / "market_status_run_log_latest.txt"
        ensure_dir(log_path.parent)
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        print("\n".join(log_lines))
        return

    max_date = hist["date"].max()
    cutoff = max_date - relativedelta(months=args.lookback_months)
    hist = hist[hist["date"] >= cutoff].copy()

    previous_status = read_json_safely(outdir / "data_status_latest.json")
    previous_actual = previous_status.get("actual_data_last_date")

    breadth = build_breadth_history(hist)
    index_hist = build_proxy_index_history(hist)
    summary = build_market_index_summary(index_hist, breadth)

    status_decision = decide_status(max_date, previous_actual, run_at)

    data_status = {
        "script": SCRIPT_VERSION,
        "run_at": run_at.isoformat(timespec="seconds"),
        "requested_end_date": run_at.date().isoformat(),
        "actual_data_last_date": max_date.date().isoformat(),
        "previous_actual_data_last_date": previous_actual,
        "new_confirmed_trading_day": status_decision["new_confirmed_trading_day"],
        "freshness_days": status_decision["freshness_days"],
        "raw_rows": int(len(raw)),
        "normalized_rows": int(len(hist)),
        "kospi_rows": int((hist["market"] == "KOSPI").sum()),
        "kosdaq_rows": int((hist["market"] == "KOSDAQ").sum()),
        "market_breadth_rows": int(len(breadth)),
        "market_index_history_rows": int(len(index_hist)),
        "market_index_summary_rows": int(len(summary)),
        "status": status_decision["status"],
        "status_reason": status_decision["status_reason"],
        "note": "market_index는 공식 지수가 아니라 KRX 전종목 원자료 기반 시가총액 가중 프록시 지수입니다.",
    }

    bubble_risk = classify_bubble_risk(summary, data_status)
    signals_df = pd.DataFrame(bubble_risk.get("signals", []))

    write_csv(breadth, outdir / "market_breadth_history_latest.csv")
    write_csv(index_hist, outdir / "market_index_history_latest.csv")
    write_csv(summary, outdir / "market_index_summary_latest.csv")
    write_csv(signals_df, outdir / "bubble_risk_signals_latest.csv")

    write_json(outdir / "data_status_latest.json", data_status)
    write_json(outdir / "bubble_risk_latest.json", bubble_risk)

    log_lines.append(f"actual_data_last_date={data_status['actual_data_last_date']}")
    log_lines.append(f"previous_actual_data_last_date={data_status['previous_actual_data_last_date']}")
    log_lines.append(f"new_confirmed_trading_day={data_status['new_confirmed_trading_day']}")
    log_lines.append(f"status={data_status['status']}")
    log_lines.append(f"freshness_days={data_status['freshness_days']}")
    log_lines.append(f"market_breadth_rows={data_status['market_breadth_rows']}")
    log_lines.append(f"market_index_summary_rows={data_status['market_index_summary_rows']}")
    log_lines.append(f"bubble_risk_level={bubble_risk['risk_level']}")
    log_lines.append(f"bubble_signal_count={bubble_risk['signal_count']}")
    log_lines.append(f"bubble_alert_by_signals={bubble_risk['alert_by_signals']}")
    log_lines.append(f"bubble_alert_required={bubble_risk['alert_required']}")

    log_path = outdir / "market_status_run_log_latest.txt"
    ensure_dir(log_path.parent)
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
