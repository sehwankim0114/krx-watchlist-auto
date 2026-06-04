#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
market_status.py

KRX 전체시장 원자료(universe_raw_history_latest.csv)를 기반으로
국내 증시 과열·시장폭·쏠림·최신거래일 상태를 점검하기 위한 보조 파일을 생성한다.

생성 파일
- latest/data_status_latest.json
- latest/market_breadth_history_latest.csv
- latest/market_index_history_latest.csv
- latest/market_index_summary_latest.csv

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
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "market_status.py v1.0_status_breadth_proxy_index"

RAW_FILENAME = "universe_raw_history_latest.csv"

SAMSUNG_ELECTRONICS = "005930"
SK_HYNIX = "000660"


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


def json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if pd.isna(value):
            return None
        return float(value)
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    safe = {k: json_safe(v) for k, v in data.items()}
    path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2),
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

        samsung_hynix_cap = np.nan
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
                "total_market_cap": b_row.get("total_market_cap"),
                "top2_market_cap_ratio_pct": b_row.get("top2_market_cap_ratio_pct"),
                "top10_market_cap_ratio_pct": b_row.get("top10_market_cap_ratio_pct"),
                "samsung_hynix_market_cap_ratio_pct": b_row.get("samsung_hynix_market_cap_ratio_pct"),
            }
        )

    return pd.DataFrame(rows)


def decide_status(actual_data_last_date: pd.Timestamp, previous_actual_date: str | None, run_date: datetime) -> Dict[str, Any]:
    if actual_data_last_date is None or pd.isna(actual_data_last_date):
        return {
            "status": "NO_VALID_DATA",
            "new_confirmed_trading_day": False,
            "freshness_days": None,
        }

    actual_str = actual_data_last_date.date().isoformat()
    run_date_only = pd.Timestamp(run_date.date())
    freshness_days = int((run_date_only - pd.Timestamp(actual_data_last_date.date())).days)

    if previous_actual_date:
        new_confirmed = actual_str != str(previous_actual_date)
    else:
        new_confirmed = True

    if new_confirmed:
        status = "OK_NEW_CONFIRMED_TRADING_DAY"
    else:
        status = "STALE_BUT_VALID"

    return {
        "status": status,
        "new_confirmed_trading_day": bool(new_confirmed),
        "freshness_days": freshness_days,
    }


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
        status = {
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
            "note": "universe_raw_history_latest.csv를 읽지 못했거나 필수 컬럼이 없습니다.",
        }
        write_json(outdir / "data_status_latest.json", status)
        print("NO_VALID_DATA")
        return

    max_date = hist["date"].max()
    cutoff = max_date - relativedelta(months=args.lookback_months)
    hist = hist[hist["date"] >= cutoff].copy()

    previous_status = read_json_safely(outdir / "data_status_latest.json")
    previous_actual = previous_status.get("actual_data_last_date")

    breadth = build_breadth_history(hist)
    index_hist = build_proxy_index_history(hist)
    summary = build_market_index_summary(index_hist, breadth)

    write_csv(breadth, outdir / "market_breadth_history_latest.csv")
    write_csv(index_hist, outdir / "market_index_history_latest.csv")
    write_csv(summary, outdir / "market_index_summary_latest.csv")

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
        "note": "market_index는 공식 지수가 아니라 KRX 전종목 원자료 기반 시가총액 가중 프록시 지수입니다.",
    }

    write_json(outdir / "data_status_latest.json", data_status)

    log_lines.append(f"actual_data_last_date={data_status['actual_data_last_date']}")
    log_lines.append(f"previous_actual_data_last_date={data_status['previous_actual_data_last_date']}")
    log_lines.append(f"new_confirmed_trading_day={data_status['new_confirmed_trading_day']}")
    log_lines.append(f"status={data_status['status']}")
    log_lines.append(f"market_breadth_rows={data_status['market_breadth_rows']}")
    log_lines.append(f"market_index_summary_rows={data_status['market_index_summary_rows']}")

    log_path = outdir / "market_status_run_log_latest.txt"
    ensure_dir(log_path.parent)
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
