#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
KOSPI 월사이클표 생성기
- 기존 latest/universe_raw_history_latest.csv 를 읽어서
- 코스피 전체 보통주 중 최근 약 6개월 동안
  잔파동이 아닌 큰 고점·저점 반복 사이클이 한 달 전후로 나타나는 종목을 산출한다.

생성 파일
- latest/kospi_monthly_cycle_latest.csv
- latest/kospi_monthly_cycle_candidates_latest.csv
- latest/monthly_cycle_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


SCRIPT_VERSION = "monthly_cycle.py v1.0_big_swing_monthly_cycle"


CYCLE_COLUMNS = [
    "rank",
    "cycle_marker",
    "status_flag",
    "code",
    "name",
    "market",
    "asof_date",
    "close",
    "cycle_count_6m",
    "avg_cycle_days",
    "avg_swing_pct",
    "latest_position",
    "buy_range",
    "sell_range",
    "avg_daily_move_text",
    "stop_price",
    "low_6m",
    "high_6m",
    "range_6m_pct",
    "position_in_6m_range_pct",
    "avg_trading_value",
    "liquidity_flag",
    "score",
    "reason",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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
    m = re.search(r"\d{1,6}", s)
    return m.group(0).zfill(6) if m else ""


def kr_tick_round(x):
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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_log(lines: List[str], path: Path) -> None:
    ensure_dir(path.parent)
    path.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def is_excluded_stock(name: str, ticker: str) -> bool:
    name = str(name).strip()
    name_upper = name.upper()

    if not re.fullmatch(r"\d{6}", ticker):
        return True

    # 우선주 제외
    if "우선주" in name:
        return True
    if re.search(r"(\d우B|\d우|우B|우C|우)$", name):
        return True

    # 스팩, 리츠, ETF/ETN 성격 제외
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

    return any(k in name_upper for k in exclude_keywords)


def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    required = ["date", "market", "ticker", "name", "high", "low", "close"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"raw history missing columns: {missing}")

    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["market"] = out["market"].astype(str).str.upper().str.strip()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["name"] = out["name"].astype(str)

    for col in ["open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = out[col].map(clean_number)

    out = out.dropna(subset=["date", "ticker", "close"])
    out = out[out["ticker"].str.fullmatch(r"\d{6}", na=False)]
    out = out.sort_values(["market", "ticker", "date"]).reset_index(drop=True)
    return out


def find_pivots(g: pd.DataFrame, order: int = 5) -> List[Dict[str, object]]:
    """
    큰 파동 후보 피벗 탐지.
    order=5는 앞뒤 5거래일 범위에서의 의미 있는 고점/저점을 찾는 기준.
    """
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].astype(float).reset_index(drop=True)

    pivots: List[Dict[str, object]] = []

    if len(g) < order * 2 + 5:
        return pivots

    for i in range(order, len(g) - order):
        window = close.iloc[i - order : i + order + 1]
        price = close.iloc[i]

        if price == window.max() and price > close.iloc[i - 1] and price >= close.iloc[i + 1]:
            pivots.append(
                {
                    "idx": i,
                    "date": g.loc[i, "date"],
                    "price": float(price),
                    "kind": "H",
                }
            )
        elif price == window.min() and price < close.iloc[i - 1] and price <= close.iloc[i + 1]:
            pivots.append(
                {
                    "idx": i,
                    "date": g.loc[i, "date"],
                    "price": float(price),
                    "kind": "L",
                }
            )

    if not pivots:
        return []

    # 같은 종류의 피벗이 연속되면 더 극단적인 값만 남긴다.
    cleaned: List[Dict[str, object]] = []
    for p in pivots:
        if not cleaned:
            cleaned.append(p)
            continue

        last = cleaned[-1]
        if p["kind"] == last["kind"]:
            if p["kind"] == "H":
                if p["price"] > last["price"]:
                    cleaned[-1] = p
            else:
                if p["price"] < last["price"]:
                    cleaned[-1] = p
        else:
            cleaned.append(p)

    return cleaned


def count_monthly_big_cycles(
    pivots: List[Dict[str, object]],
    min_leg_pct: float = 10.0,
    min_cycle_days: int = 18,
    max_cycle_days: int = 50,
) -> Tuple[int, Optional[float], Optional[float], List[Dict[str, object]]]:
    """
    L-H-L 또는 H-L-H 구조를 한 번의 대형 반복사이클로 본다.
    - 양쪽 다리 변동폭이 min_leg_pct 이상
    - 처음 피벗부터 세 번째 피벗까지 기간이 18~50거래일이면 한 달 전후 반복으로 인정
    """
    cycles: List[Dict[str, object]] = []

    if len(pivots) < 3:
        return 0, None, None, cycles

    for i in range(len(pivots) - 2):
        p0, p1, p2 = pivots[i], pivots[i + 1], pivots[i + 2]

        if p0["kind"] != p2["kind"]:
            continue
        if p0["kind"] == p1["kind"] or p1["kind"] == p2["kind"]:
            continue

        days = int(p2["idx"] - p0["idx"])
        if days < min_cycle_days or days > max_cycle_days:
            continue

        leg1 = abs(float(p1["price"]) / float(p0["price"]) - 1) * 100
        leg2 = abs(float(p2["price"]) / float(p1["price"]) - 1) * 100

        if leg1 < min_leg_pct or leg2 < min_leg_pct:
            continue

        cycles.append(
            {
                "start_date": p0["date"],
                "mid_date": p1["date"],
                "end_date": p2["date"],
                "days": days,
                "leg1_pct": leg1,
                "leg2_pct": leg2,
                "avg_swing_pct": (leg1 + leg2) / 2,
                "pattern": f"{p0['kind']}-{p1['kind']}-{p2['kind']}",
            }
        )

    if not cycles:
        return 0, None, None, cycles

    avg_days = round(float(np.mean([c["days"] for c in cycles])), 1)
    avg_swing = round(float(np.mean([c["avg_swing_pct"] for c in cycles])), 2)

    return len(cycles), avg_days, avg_swing, cycles


def classify_position(pos_pct: Optional[float], last_pivot_kind: str) -> str:
    if pos_pct is None or pd.isna(pos_pct):
        return "위치확인 제한"

    pos_pct = float(pos_pct)

    if pos_pct <= 25:
        return "저점권"
    if pos_pct <= 42:
        return "저점권 반등 초입"
    if pos_pct <= 68:
        return "중간권"
    if pos_pct <= 85:
        return "상단권"
    return "고점권"


def cycle_marker(cycle_count: int) -> str:
    if cycle_count >= 5:
        return "🔵"
    if cycle_count >= 4:
        return "🟢"
    if cycle_count >= 2:
        return "🟡"
    return ""


def add_underline_if_needed(flag: str, liquidity_flag: bool) -> str:
    # 표에서 밑줄 표시 = 저유동성·매매곤란 주의
    if liquidity_flag and flag:
        return flag + "\u0332"
    return flag


def status_flag_for(
    cycle_count: int,
    position_pct: Optional[float],
    liquidity_flag: bool,
    avg_swing_pct: Optional[float],
) -> str:
    pos = float(position_pct) if position_pct is not None and not pd.isna(position_pct) else np.nan
    swing = float(avg_swing_pct) if avg_swing_pct is not None and not pd.isna(avg_swing_pct) else np.nan

    if cycle_count >= 4:
        if not pd.isna(pos) and pos >= 82:
            flag = "⚠️"
        elif liquidity_flag:
            flag = "🟡"
        else:
            flag = "✅"
    elif cycle_count >= 2:
        if not pd.isna(pos) and pos >= 82:
            flag = "⚠️"
        else:
            flag = "🟡"
    else:
        flag = "⚠️"

    return add_underline_if_needed(flag, liquidity_flag)


def calc_score(
    cycle_count: int,
    avg_cycle_days: Optional[float],
    avg_swing_pct: Optional[float],
    position_pct: Optional[float],
    liquidity_flag: bool,
    avg_trading_value: Optional[float],
) -> float:
    score = 0.0

    score += min(cycle_count, 6) * 22

    if avg_cycle_days is not None and not pd.isna(avg_cycle_days):
        # 한 달 전후 22~35거래일에 가까울수록 가점
        if 22 <= avg_cycle_days <= 35:
            score += 18
        elif 18 <= avg_cycle_days <= 50:
            score += 10

    if avg_swing_pct is not None and not pd.isna(avg_swing_pct):
        if 12 <= avg_swing_pct <= 35:
            score += 15
        elif avg_swing_pct > 35:
            score += 5

    if position_pct is not None and not pd.isna(position_pct):
        pos = float(position_pct)
        if 20 <= pos <= 60:
            score += 15
        elif pos < 20:
            score += 5
        elif pos >= 85:
            score -= 15

    if liquidity_flag:
        score -= 20
    elif avg_trading_value is not None and not pd.isna(avg_trading_value):
        if avg_trading_value >= 100_000_000_000:
            score += 12
        elif avg_trading_value >= 30_000_000_000:
            score += 7

    return round(float(score), 2)


def build_reason(
    cycle_count: int,
    avg_cycle_days: Optional[float],
    avg_swing_pct: Optional[float],
    latest_position: str,
    liquidity_flag: bool,
    position_pct: Optional[float],
) -> str:
    parts: List[str] = []

    if cycle_count >= 4:
        parts.append(f"6개월 대형 월간 반복사이클 {cycle_count}회 확인")
    elif cycle_count >= 2:
        parts.append(f"대형 반복 후보 {cycle_count}회")
    else:
        parts.append("반복성 약함")

    if avg_cycle_days is not None and not pd.isna(avg_cycle_days):
        parts.append(f"평균 {avg_cycle_days}거래일 주기")

    if avg_swing_pct is not None and not pd.isna(avg_swing_pct):
        parts.append(f"평균 파동폭 {avg_swing_pct}%")

    parts.append(latest_position)

    if position_pct is not None and not pd.isna(position_pct) and float(position_pct) >= 82:
        parts.append("고점권 추격주의")

    if liquidity_flag:
        parts.append("저유동성/매매곤란 주의")

    return "; ".join(parts)


def build_monthly_cycle_table(
    hist: pd.DataFrame,
    summary: pd.DataFrame,
    lookback_months: int,
    top_n: int,
    low_liq_krw: float,
    log_lines: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    hist = normalize_history(hist)

    if hist.empty:
        return pd.DataFrame(columns=CYCLE_COLUMNS), pd.DataFrame(columns=CYCLE_COLUMNS)

    kospi = hist[hist["market"].eq("KOSPI")].copy()

    if kospi.empty:
        return pd.DataFrame(columns=CYCLE_COLUMNS), pd.DataFrame(columns=CYCLE_COLUMNS)

    last_date = kospi["date"].max()
    cutoff = last_date - pd.DateOffset(months=lookback_months)
    kospi = kospi[kospi["date"] >= cutoff].copy()

    log_lines.append(f"monthly_cycle_actual_data_last_date={last_date.date().isoformat()}")
    log_lines.append(f"monthly_cycle_period={cutoff.date().isoformat()}~{last_date.date().isoformat()}")
    log_lines.append(f"monthly_cycle_input_rows={len(kospi)}")
    log_lines.append(f"monthly_cycle_input_tickers={kospi['ticker'].nunique()}")

    summary_map = pd.DataFrame()
    if summary is not None and not summary.empty:
        summary_map = summary.copy()
        summary_map["ticker"] = summary_map["ticker"].map(normalize_ticker)

    rows: List[Dict[str, object]] = []

    for ticker, g in kospi.groupby("ticker", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < 70:
            continue

        name = str(g["name"].iloc[-1])
        if is_excluded_stock(name, ticker):
            continue

        close = float(g["close"].iloc[-1])
        if close <= 0:
            continue

        low_6m = float(g["low"].min())
        high_6m = float(g["high"].max())
        if low_6m <= 0 or high_6m <= low_6m:
            continue

        range_6m_pct = round((high_6m / low_6m - 1) * 100, 2)
        position_pct = round((close - low_6m) / (high_6m - low_6m) * 100, 2)

        pivots = find_pivots(g, order=5)
        count, avg_days, avg_swing, cycles = count_monthly_big_cycles(
            pivots,
            min_leg_pct=10.0,
            min_cycle_days=18,
            max_cycle_days=50,
        )

        # 월사이클표는 최소 2회 이상 후보만 리스트업한다.
        if count < 2:
            continue

        last_pivot_kind = pivots[-1]["kind"] if pivots else ""
        latest_position = classify_position(position_pct, last_pivot_kind)

        avg_trading_value = g["trading_value"].tail(20).mean()
        liquidity_flag = bool(not pd.isna(avg_trading_value) and avg_trading_value < low_liq_krw)

        avg_abs = g["close"].diff().abs().dropna().mean()
        avg_pct = (g["close"].pct_change().abs() * 100).dropna().mean()

        # 기존 kospi_universe_summary_latest.csv가 있으면 그 가격구간을 우선 사용
        sm = pd.DataFrame()
        if not summary_map.empty:
            sm = summary_map[summary_map["ticker"].eq(ticker)]

        if not sm.empty:
            srow = sm.iloc[-1]
            buy_range = build_range_text(srow.get("split_buy_low_ref"), srow.get("split_buy_high_ref"))
            sell_range = build_range_text(srow.get("target1_ref"), srow.get("target2_ref"))
            avg_daily_move_text = build_avg_daily_move_text(
                srow.get("avg_daily_move_abs"),
                srow.get("avg_daily_move_pct"),
            )
            stop_price = srow.get("stop_ref")
        else:
            move = avg_abs if not pd.isna(avg_abs) and avg_abs > 0 else close * 0.03
            buy_low = kr_tick_round(max(low_6m * 1.02, close - move * 2.5))
            buy_high = kr_tick_round(min(close * 0.99, close - move * 0.3))
            sell1 = kr_tick_round(max(close * 1.04, close + move * 2.0))
            sell2 = kr_tick_round(max(sell1 * 1.03, close + move * 3.5))
            stop_price = kr_tick_round(max(low_6m * 0.97, close - move * 3.0))
            buy_range = build_range_text(buy_low, buy_high)
            sell_range = build_range_text(sell1, sell2)
            avg_daily_move_text = build_avg_daily_move_text(kr_tick_round(avg_abs), round(float(avg_pct), 2))

        score = calc_score(
            count,
            avg_days,
            avg_swing,
            position_pct,
            liquidity_flag,
            avg_trading_value,
        )

        reason = build_reason(
            count,
            avg_days,
            avg_swing,
            latest_position,
            liquidity_flag,
            position_pct,
        )

        rows.append(
            {
                "rank": 0,
                "cycle_marker": cycle_marker(count),
                "status_flag": status_flag_for(count, position_pct, liquidity_flag, avg_swing),
                "code": ticker,
                "name": name,
                "market": "KOSPI",
                "asof_date": last_date.date().isoformat(),
                "close": kr_tick_round(close),
                "cycle_count_6m": int(count),
                "avg_cycle_days": avg_days,
                "avg_swing_pct": avg_swing,
                "latest_position": latest_position,
                "buy_range": buy_range,
                "sell_range": sell_range,
                "avg_daily_move_text": avg_daily_move_text,
                "stop_price": kr_tick_round(stop_price),
                "low_6m": kr_tick_round(low_6m),
                "high_6m": kr_tick_round(high_6m),
                "range_6m_pct": range_6m_pct,
                "position_in_6m_range_pct": position_pct,
                "avg_trading_value": int(avg_trading_value) if not pd.isna(avg_trading_value) else None,
                "liquidity_flag": liquidity_flag,
                "score": score,
                "reason": reason,
            }
        )

    all_candidates = pd.DataFrame(rows, columns=CYCLE_COLUMNS)

    if all_candidates.empty:
        return pd.DataFrame(columns=CYCLE_COLUMNS), pd.DataFrame(columns=CYCLE_COLUMNS)

    all_candidates = all_candidates.sort_values(
        ["cycle_count_6m", "score", "avg_trading_value"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    all_candidates["rank"] = range(1, len(all_candidates) + 1)

    latest = all_candidates.head(top_n).copy()
    latest["rank"] = range(1, len(latest) + 1)

    log_lines.append(f"monthly_cycle_candidates_all={len(all_candidates)}")
    log_lines.append(f"monthly_cycle_latest_rows={len(latest)}")
    log_lines.append(f"monthly_cycle_4plus={int((all_candidates['cycle_count_6m'] >= 4).sum())}")

    return latest, all_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Build KOSPI monthly big-swing cycle table")
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-months", type=int, default=6)
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--low-liq-krw", type=float, default=5_000_000_000)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    latest_dir = root / args.output_dir
    ensure_dir(latest_dir)

    raw_path = latest_dir / "universe_raw_history_latest.csv"
    summary_path = latest_dir / "kospi_universe_summary_latest.csv"

    out_latest_path = latest_dir / "kospi_monthly_cycle_latest.csv"
    out_candidates_path = latest_dir / "kospi_monthly_cycle_candidates_latest.csv"
    log_path = latest_dir / "monthly_cycle_run_log_latest.txt"

    log_lines: List[str] = []
    log_lines.append(f"script={SCRIPT_VERSION}")
    log_lines.append(f"started_at={datetime.now().isoformat(timespec='seconds')}")
    log_lines.append(f"raw_path={raw_path.as_posix()}")
    log_lines.append(f"summary_path={summary_path.as_posix()}")

    try:
        hist = read_csv(raw_path)
        summary = read_csv(summary_path)

        log_lines.append(f"raw_rows={len(hist)}")
        log_lines.append(f"summary_rows={len(summary)}")

        latest, candidates = build_monthly_cycle_table(
            hist=hist,
            summary=summary,
            lookback_months=args.lookback_months,
            top_n=args.top_n,
            low_liq_krw=args.low_liq_krw,
            log_lines=log_lines,
        )

        write_csv(latest, out_latest_path)
        write_csv(candidates, out_candidates_path)

        log_lines.append(f"output_latest={out_latest_path.as_posix()}, rows={len(latest)}")
        log_lines.append(f"output_candidates={out_candidates_path.as_posix()}, rows={len(candidates)}")
        log_lines.append(f"finished_at={datetime.now().isoformat(timespec='seconds')}")
        write_log(log_lines, log_path)

        print("\n".join(log_lines))
        return 0

    except Exception as exc:
        log_lines.append(f"ERROR={repr(exc)}")
        log_lines.append(f"failed_at={datetime.now().isoformat(timespec='seconds')}")
        write_log(log_lines, log_path)
        print("\n".join(log_lines))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
