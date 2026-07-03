#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
us_sp500_watchlist.py v1.0.0

S&P500 표준화 유니버스 자료에서 코피표형 미관종표를 만든다.

출력
- latest/us_sp500_watchlist_latest.csv       후보 30개, 추천 7개 표시
- latest/us_sp500_recommend_7_latest.csv     명시 요청용 추천 7개
- latest/us_sp500_status_latest.json
- latest/us_sp500_run_log_latest.txt

중요
- 전체 S&P500을 먼저 기술·유동성·가치·성장 기준으로 점수화한다.
- 추천 7개는 후보 30개 안에서만 선택한다.
- 확인되지 않은 실적·가이던스·밸류에이션을 임의 생성하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "us_sp500_watchlist.py "
    "v1.0.0-sp500-candidate30-recommend7"
)
POLICY_VERSION = (
    "2026-07-03-v6.0-us-sp500-kospi-style"
)
KST = timezone(timedelta(hours=9))

DEFAULT_CANDIDATE_N = 30
DEFAULT_RECOMMEND_N = 7

REQUIRED_COLUMNS = {
    "symbol",
    "name",
    "market",
    "sector",
    "industry",
    "status",
    "data_date",
    "current_price",
    "low_3m",
    "high_3m",
    "return_1m_pct",
    "return_3m_pct",
    "avg_volume_20d",
    "avg_trading_value_20d",
    "avg_daily_range_pct",
    "sma20",
    "sma60",
    "rsi14",
    "data_rows",
    "fundamentals_status",
}

OPTIONAL_NUMERIC_COLUMNS = (
    "market_cap",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "peg_ratio",
    "revenue_growth",
    "earnings_growth",
    "profit_margin",
    "return_on_equity",
    "debt_to_equity",
    "analyst_target_mean",
    "beta",
    "short_percent_float",
)

DISPLAY_COLUMNS = [
    "recommend_display",
    "current_price_display",
    "value_buy_range",
    "target1_range",
    "three_month_range",
    "return_1m_display",
    "liquidity_display",
    "current_position",
    "avg_daily_range_display",
    "earnings_guidance_event",
    "valuation_growth",
    "score_recommendation_reason",
    "market_ticker",
    "sector_theme",
]

RAW_COLUMNS = [
    "recommend_flag",
    "symbol",
    "name",
    "market",
    "sector",
    "industry",
    "data_date",
    "current_price",
    "value_buy_low",
    "value_buy_high",
    "target1_low",
    "target1_high",
    "low_3m",
    "high_3m",
    "return_1m_pct",
    "return_3m_pct",
    "avg_volume_20d",
    "avg_trading_value_20d",
    "liquidity_label",
    "position_in_3m_range_pct",
    "position_label",
    "avg_daily_range_amount",
    "avg_daily_range_pct",
    "earnings_event_risk",
    "next_earnings_date",
    "fundamentals_status",
    "market_cap",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "peg_ratio",
    "revenue_growth",
    "earnings_growth",
    "profit_margin",
    "return_on_equity",
    "debt_to_equity",
    "analyst_target_mean",
    "analyst_target_upside_pct",
    "beta",
    "short_percent_float",
    "rsi14",
    "sma20",
    "sma60",
    "score",
    "hard_red_flag",
    "warning_count",
    "recommendation_reason",
]

OUTPUT_COLUMNS = DISPLAY_COLUMNS + RAW_COLUMNS


@dataclass(frozen=True)
class BuildSummary:
    input_rows: int
    valid_rows: int
    candidate_rows: int
    recommend_rows: int
    checkmark_count: int
    unique_candidate_symbols: int
    unique_recommend_symbols: int
    recommend_outside_candidates: int
    hard_red_recommended: int
    incomplete_rows_excluded: int
    fundamentals_ready_candidates: int
    fundamentals_limited_candidates: int
    min_candidate_score: float
    max_candidate_score: float


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def clean_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if text.lower() in {"", "nan", "none"}:
        return ""
    return text.replace(".", "-")


def as_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def clipped(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def usd(value: float | None, decimals: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "자료제한"
    if value >= 1000:
        return f"${value:,.0f}"
    return f"${value:,.{decimals}f}"


def percent_text(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "자료제한"
    return f"{value:+.{digits}f}%"


def percent_plain(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "자료제한"
    return f"{value:.{digits}f}%"


def compact_usd(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "자료제한"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def price_range_text(
    low: float | None,
    high: float | None,
) -> str:
    if (
        low is None
        or high is None
        or low <= 0
        or high <= 0
        or high < low
    ):
        return "자료제한"
    return f"{usd(low)}~{usd(high)}"


def liquidity_label(value: float | None) -> str:
    if value is None:
        return "유동성 확인제한"
    if value >= 1_000_000_000:
        return "매우활발"
    if value >= 300_000_000:
        return "활발"
    if value >= 100_000_000:
        return "보통"
    if value >= 30_000_000:
        return "부족"
    return "매우부족"


def position_label(value: float | None) -> str:
    if value is None:
        return "위치확인제한"
    if value <= 20:
        return "저점권"
    if value <= 35:
        return "저점권반등초입"
    if value <= 65:
        return "중간권"
    if value <= 80:
        return "중상단권"
    if value <= 92:
        return "상단권부담"
    return "고점권과열"


def position_pct(
    current: float | None,
    low: float | None,
    high: float | None,
) -> float | None:
    if (
        current is None
        or low is None
        or high is None
        or high <= low
    ):
        return None
    raw = (current - low) / (high - low) * 100
    return round(clipped(raw, 0.0, 100.0), 2)


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat"}:
        return None
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def load_universe(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"미국 유니버스 파일이 없습니다: {path}")

    frame = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"symbol": str},
    )
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            "미국 유니버스 필수열 누락: "
            + ",".join(sorted(missing))
        )

    frame = frame.copy()
    frame["symbol"] = frame["symbol"].map(clean_symbol)
    frame["market"] = frame["market"].astype(str).str.upper()
    frame["status"] = frame["status"].astype(str).str.upper()
    frame["fundamentals_status"] = (
        frame["fundamentals_status"].astype(str).str.upper()
    )

    numeric_columns = (
        "current_price",
        "low_3m",
        "high_3m",
        "return_1m_pct",
        "return_3m_pct",
        "avg_volume_20d",
        "avg_trading_value_20d",
        "avg_daily_range_pct",
        "sma20",
        "sma60",
        "rsi14",
        "data_rows",
    ) + OPTIONAL_NUMERIC_COLUMNS

    for column in numeric_columns:
        frame[column] = numeric(frame, column)

    if "next_earnings_date" not in frame.columns:
        frame["next_earnings_date"] = ""
    if "guidance_note" not in frame.columns:
        frame["guidance_note"] = ""
    if "event_note" not in frame.columns:
        frame["event_note"] = ""

    frame = frame.drop_duplicates(
        subset=["market", "symbol"],
        keep="last",
    )
    return frame


def valid_universe(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    status_ok = frame["status"].eq("OK")
    basic = (
        frame["symbol"].ne("")
        & frame["current_price"].gt(0)
        & frame["low_3m"].gt(0)
        & frame["high_3m"].gt(frame["low_3m"])
        & frame["avg_trading_value_20d"].gt(0)
        & frame["avg_daily_range_pct"].gt(0)
        & frame["data_rows"].ge(60)
    )
    valid_mask = status_ok & basic
    excluded = int((~valid_mask).sum())
    return frame.loc[valid_mask].copy(), excluded


def score_position(value: float | None) -> float:
    if value is None:
        return 0.0
    if 20 <= value <= 45:
        return 24.0
    if value < 20:
        return 19.0
    if value <= 65:
        return 20.0
    if value <= 80:
        return 11.0
    if value <= 92:
        return 4.0
    return 0.0


def score_trend(
    current: float | None,
    sma20: float | None,
    sma60: float | None,
    ret1: float | None,
    ret3: float | None,
) -> float:
    score = 0.0
    if current is not None and sma20 is not None:
        score += 5.0 if current >= sma20 else 1.0
    if sma20 is not None and sma60 is not None:
        score += 7.0 if sma20 >= sma60 else 1.0
    if ret1 is not None:
        if 0 <= ret1 <= 15:
            score += 5.0
        elif -8 <= ret1 < 0:
            score += 3.0
        elif 15 < ret1 <= 25:
            score += 2.0
    if ret3 is not None:
        if 0 <= ret3 <= 35:
            score += 3.0
        elif -10 <= ret3 < 0:
            score += 1.0
    return min(score, 20.0)


def score_liquidity(value: float | None) -> float:
    label = liquidity_label(value)
    return {
        "매우활발": 10.0,
        "활발": 8.0,
        "보통": 6.0,
        "부족": 3.0,
        "매우부족": 1.0,
        "유동성 확인제한": 0.0,
    }[label]


def score_fundamentals(row: pd.Series) -> float:
    score = 0.0
    forward_pe = as_number(row.get("forward_pe"))
    trailing_pe = as_number(row.get("trailing_pe"))
    revenue_growth = as_number(row.get("revenue_growth"))
    earnings_growth = as_number(row.get("earnings_growth"))
    margin = as_number(row.get("profit_margin"))
    roe = as_number(row.get("return_on_equity"))
    target_upside = as_number(
        row.get("analyst_target_upside_pct")
    )

    pe = forward_pe if forward_pe is not None else trailing_pe
    if pe is not None and pe > 0:
        if pe <= 18:
            score += 7.0
        elif pe <= 28:
            score += 5.0
        elif pe <= 40:
            score += 2.5

    if revenue_growth is not None:
        if revenue_growth >= 0.20:
            score += 6.0
        elif revenue_growth >= 0.10:
            score += 4.5
        elif revenue_growth >= 0:
            score += 2.0

    if earnings_growth is not None:
        if earnings_growth >= 0.20:
            score += 6.0
        elif earnings_growth >= 0.10:
            score += 4.5
        elif earnings_growth >= 0:
            score += 2.0

    if margin is not None:
        if margin >= 0.20:
            score += 2.0
        elif margin >= 0.10:
            score += 1.0

    if roe is not None:
        if roe >= 0.20:
            score += 2.0
        elif roe >= 0.10:
            score += 1.0

    if target_upside is not None:
        if target_upside >= 15:
            score += 2.0
        elif target_upside >= 5:
            score += 1.0

    return min(score, 25.0)


def score_risk_quality(row: pd.Series) -> float:
    score = 0.0
    rsi = as_number(row.get("rsi14"))
    range_pct = as_number(row.get("avg_daily_range_pct"))
    beta = as_number(row.get("beta"))
    short_float = as_number(row.get("short_percent_float"))
    fundamentals_status = str(
        row.get("fundamentals_status", "")
    ).upper()

    if rsi is not None:
        if 38 <= rsi <= 66:
            score += 5.0
        elif 30 <= rsi < 38 or 66 < rsi <= 72:
            score += 2.5

    if range_pct is not None:
        if range_pct <= 2.5:
            score += 4.0
        elif range_pct <= 4.0:
            score += 2.5
        elif range_pct <= 6.0:
            score += 1.0

    if fundamentals_status == "READY":
        score += 5.0
    elif fundamentals_status in {"PARTIAL", "LIMITED"}:
        score += 2.0

    if beta is not None:
        if beta <= 1.2:
            score += 2.0
        elif beta <= 1.6:
            score += 1.0

    if short_float is not None:
        normalized = (
            short_float * 100
            if 0 <= short_float <= 1
            else short_float
        )
        if normalized <= 3:
            score += 2.0
        elif normalized <= 7:
            score += 1.0
    else:
        score += 1.0

    return min(score, 20.0)


def hard_red_flag(row: pd.Series) -> bool:
    position = as_number(row.get("position_in_3m_range_pct"))
    ret1 = as_number(row.get("return_1m_pct"))
    range_pct = as_number(row.get("avg_daily_range_pct"))
    rsi = as_number(row.get("rsi14"))
    liquidity = str(row.get("liquidity_label", ""))
    earnings_growth = as_number(row.get("earnings_growth"))

    return any(
        (
            position is not None and position >= 96,
            ret1 is not None and ret1 >= 35,
            range_pct is not None and range_pct >= 8,
            rsi is not None and rsi >= 80,
            liquidity == "매우부족",
            (
                earnings_growth is not None
                and earnings_growth <= -0.50
            ),
        )
    )


def warning_parts(row: pd.Series) -> list[str]:
    parts: list[str] = []
    position = as_number(row.get("position_in_3m_range_pct"))
    ret1 = as_number(row.get("return_1m_pct"))
    range_pct = as_number(row.get("avg_daily_range_pct"))
    rsi = as_number(row.get("rsi14"))
    pe = as_number(row.get("forward_pe"))
    revenue_growth = as_number(row.get("revenue_growth"))
    earnings_growth = as_number(row.get("earnings_growth"))
    target_upside = as_number(row.get("analyst_target_upside_pct"))
    fundamentals_status = str(
        row.get("fundamentals_status", "")
    ).upper()
    event_risk = bool(row.get("earnings_event_risk", False))

    if position is not None and position >= 80:
        parts.append("3개월 상단권 부담")
    if ret1 is not None and ret1 >= 20:
        parts.append("1개월 단기과열")
    if range_pct is not None and range_pct >= 5:
        parts.append("일간 변동성 큼")
    if rsi is not None and rsi >= 72:
        parts.append("RSI 과열권")
    if pe is not None and pe >= 45:
        parts.append("선행PER 부담")
    if revenue_growth is not None and revenue_growth < 0:
        parts.append("매출 성장률 둔화")
    if earnings_growth is not None and earnings_growth < 0:
        parts.append("이익 성장률 둔화")
    if target_upside is not None and target_upside < 0:
        parts.append("평균 목표가보다 현재가 높음")
    if event_risk:
        parts.append("실적발표 임박")
    if fundamentals_status not in {"READY", "PARTIAL"}:
        parts.append("펀더멘털 자료제한")
    return parts


def recommendation_reason(row: pd.Series) -> str:
    positives: list[str] = []
    warnings = warning_parts(row)

    position = as_number(row.get("position_in_3m_range_pct"))
    ret1 = as_number(row.get("return_1m_pct"))
    revenue_growth = as_number(row.get("revenue_growth"))
    earnings_growth = as_number(row.get("earnings_growth"))
    forward_pe = as_number(row.get("forward_pe"))
    liquidity = str(row.get("liquidity_label", ""))
    current = as_number(row.get("current_price"))
    sma20 = as_number(row.get("sma20"))
    sma60 = as_number(row.get("sma60"))

    if position is not None and position <= 45:
        positives.append("3개월 가치구간")
    elif position is not None and position <= 65:
        positives.append("3개월 중간권")

    if (
        current is not None
        and sma20 is not None
        and sma60 is not None
        and current >= sma20 >= sma60
    ):
        positives.append("중기 상승추세 유지")

    if ret1 is not None and 0 <= ret1 <= 15:
        positives.append("1개월 상승폭 안정적")

    if revenue_growth is not None and revenue_growth >= 0.10:
        positives.append("매출 성장 양호")
    if earnings_growth is not None and earnings_growth >= 0.10:
        positives.append("이익 성장 양호")
    if forward_pe is not None and 0 < forward_pe <= 28:
        positives.append("선행 밸류 부담 제한")
    if liquidity in {"매우활발", "활발"}:
        positives.append("거래유동성 우수")

    if not positives:
        positives.append("기술·유동성 종합점수 상위")

    positive_text = " · ".join(positives[:3])
    warning_text = (
        " / 주의: " + " · ".join(warnings[:3])
        if warnings
        else " / 뚜렷한 단기 경고 제한"
    )
    return positive_text + warning_text


def price_ranges(row: pd.Series) -> tuple[float, float, float, float]:
    current = float(row["current_price"])
    low = float(row["low_3m"])
    high = float(row["high_3m"])
    span = high - low

    buy_low = low + span * 0.20
    buy_high = low + span * 0.38

    if buy_low > current:
        buy_low = current * 0.92
    if buy_high > current:
        buy_high = current * 0.98

    buy_low = max(low, buy_low)
    buy_high = max(buy_low, buy_high)

    target1_low = max(current * 1.06, high * 0.94)
    target1_high = max(target1_low, current * 1.13, high * 1.02)

    return (
        round(buy_low, 2),
        round(buy_high, 2),
        round(target1_low, 2),
        round(target1_high, 2),
    )


def earnings_event_text(row: pd.Series) -> str:
    date = parse_date(row.get("next_earnings_date"))
    guidance = str(row.get("guidance_note", "")).strip()
    event = str(row.get("event_note", "")).strip()

    parts: list[str] = []
    if date is not None:
        parts.append(f"실적발표 예정 {date.date().isoformat()}")
    else:
        parts.append("다음 실적일 자료제한")

    if guidance and guidance.lower() not in {"nan", "none"}:
        parts.append(guidance)
    else:
        parts.append("가이던스 확인 필요")

    if event and event.lower() not in {"nan", "none"}:
        parts.append(event)

    return " · ".join(parts[:3])


def valuation_growth_text(row: pd.Series) -> str:
    forward_pe = as_number(row.get("forward_pe"))
    trailing_pe = as_number(row.get("trailing_pe"))
    revenue_growth = as_number(row.get("revenue_growth"))
    earnings_growth = as_number(row.get("earnings_growth"))
    target_upside = as_number(row.get("analyst_target_upside_pct"))
    status = str(row.get("fundamentals_status", "")).upper()

    parts: list[str] = []
    if forward_pe is not None and forward_pe > 0:
        parts.append(f"선행PER {forward_pe:.1f}배")
    elif trailing_pe is not None and trailing_pe > 0:
        parts.append(f"후행PER {trailing_pe:.1f}배")
    else:
        parts.append("PER 자료제한")

    if revenue_growth is not None:
        parts.append(f"매출성장 {revenue_growth * 100:+.1f}%")
    else:
        parts.append("매출성장 자료제한")

    if earnings_growth is not None:
        parts.append(f"이익성장 {earnings_growth * 100:+.1f}%")
    else:
        parts.append("이익성장 자료제한")

    if target_upside is not None:
        parts.append(f"평균목표가 여력 {target_upside:+.1f}%")

    if status not in {"READY", "PARTIAL"}:
        parts.append("펀더멘털 확인제한")

    return " · ".join(parts[:4])


def enrich_rows(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()

    positions = []
    liquidity_labels = []
    avg_range_amounts = []
    target_upsides = []
    event_risks = []

    now_utc = datetime.now(timezone.utc)

    for _, row in result.iterrows():
        current = as_number(row.get("current_price"))
        low = as_number(row.get("low_3m"))
        high = as_number(row.get("high_3m"))
        avg_range_pct = as_number(row.get("avg_daily_range_pct"))
        target = as_number(row.get("analyst_target_mean"))
        earnings_date = parse_date(row.get("next_earnings_date"))

        positions.append(position_pct(current, low, high))
        liquidity_labels.append(
            liquidity_label(
                as_number(row.get("avg_trading_value_20d"))
            )
        )
        avg_range_amounts.append(
            (
                current * avg_range_pct / 100
                if current is not None
                and avg_range_pct is not None
                else np.nan
            )
        )
        target_upsides.append(
            (
                (target / current - 1) * 100
                if target is not None
                and current is not None
                and current > 0
                else np.nan
            )
        )
        event_risks.append(
            bool(
                earnings_date is not None
                and -1
                <= (earnings_date - now_utc).days
                <= 10
            )
        )

    result["position_in_3m_range_pct"] = positions
    result["position_label"] = result[
        "position_in_3m_range_pct"
    ].map(position_label)
    result["liquidity_label"] = liquidity_labels
    result["avg_daily_range_amount"] = avg_range_amounts
    result["analyst_target_upside_pct"] = target_upsides
    result["earnings_event_risk"] = event_risks

    scores = []
    hard_flags = []
    reasons = []
    warning_counts = []

    for _, row in result.iterrows():
        score = (
            score_position(
                as_number(
                    row.get("position_in_3m_range_pct")
                )
            )
            + score_trend(
                as_number(row.get("current_price")),
                as_number(row.get("sma20")),
                as_number(row.get("sma60")),
                as_number(row.get("return_1m_pct")),
                as_number(row.get("return_3m_pct")),
            )
            + score_liquidity(
                as_number(row.get("avg_trading_value_20d"))
            )
            + score_fundamentals(row)
            + score_risk_quality(row)
        )
        hard = hard_red_flag(row)
        if hard:
            score = min(score, 59.0)

        scores.append(round(clipped(score, 0.0, 100.0), 1))
        hard_flags.append(hard)
        warnings = warning_parts(row)
        warning_counts.append(len(warnings))
        reasons.append(recommendation_reason(row))

    result["score"] = scores
    result["hard_red_flag"] = hard_flags
    result["warning_count"] = warning_counts
    result["recommendation_reason"] = reasons

    buy_lows = []
    buy_highs = []
    target_lows = []
    target_highs = []
    for _, row in result.iterrows():
        buy_low, buy_high, target_low, target_high = (
            price_ranges(row)
        )
        buy_lows.append(buy_low)
        buy_highs.append(buy_high)
        target_lows.append(target_low)
        target_highs.append(target_high)

    result["value_buy_low"] = buy_lows
    result["value_buy_high"] = buy_highs
    result["target1_low"] = target_lows
    result["target1_high"] = target_highs
    return result


def choose_candidates(
    frame: pd.DataFrame,
    *,
    candidate_n: int,
    recommend_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(frame) < candidate_n:
        raise ValueError(
            f"유효 S&P500 종목이 후보 수보다 적습니다: "
            f"{len(frame)} < {candidate_n}"
        )

    sorted_frame = frame.sort_values(
        by=[
            "score",
            "hard_red_flag",
            "warning_count",
            "avg_trading_value_20d",
            "symbol",
        ],
        ascending=[False, True, True, False, True],
        kind="stable",
    )

    candidates = sorted_frame.head(candidate_n).copy()

    eligible = candidates.loc[
        ~candidates["hard_red_flag"].astype(bool)
    ].copy()
    if len(eligible) < recommend_n:
        raise ValueError(
            "후보 30개 안의 비위험 추천 가능 종목이 "
            f"{recommend_n}개보다 적습니다."
        )

    recommend_symbols = set(
        eligible.head(recommend_n)["symbol"].tolist()
    )
    candidates["recommend_flag"] = np.where(
        candidates["symbol"].isin(recommend_symbols),
        "✅",
        np.where(
            candidates["hard_red_flag"],
            "🔻",
            np.where(
                candidates["score"].ge(65),
                "🟡",
                "⚠️",
            ),
        ),
    )
    recommends = candidates.loc[
        candidates["symbol"].isin(recommend_symbols)
    ].copy()

    candidate_order = {
        symbol: index
        for index, symbol in enumerate(
            candidates["symbol"].tolist()
        )
    }
    recommends["_order"] = recommends["symbol"].map(
        candidate_order
    )
    recommends = recommends.sort_values(
        "_order",
        kind="stable",
    ).drop(columns=["_order"])

    return candidates, recommends


def display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()

    output["recommend_display"] = (
        output["recommend_flag"]
        + " "
        + output["name"].astype(str)
    )
    output["current_price_display"] = output[
        "current_price"
    ].map(lambda value: usd(as_number(value)))
    output["value_buy_range"] = output.apply(
        lambda row: price_range_text(
            as_number(row.get("value_buy_low")),
            as_number(row.get("value_buy_high")),
        ),
        axis=1,
    )
    output["target1_range"] = output.apply(
        lambda row: price_range_text(
            as_number(row.get("target1_low")),
            as_number(row.get("target1_high")),
        ),
        axis=1,
    )
    output["three_month_range"] = output.apply(
        lambda row: price_range_text(
            as_number(row.get("low_3m")),
            as_number(row.get("high_3m")),
        ),
        axis=1,
    )
    output["return_1m_display"] = output[
        "return_1m_pct"
    ].map(lambda value: percent_text(as_number(value)))
    output["liquidity_display"] = output.apply(
        lambda row: (
            f"{compact_usd(as_number(row.get('avg_trading_value_20d')))}"
            f"/일 · {row.get('liquidity_label')}"
        ),
        axis=1,
    )
    output["current_position"] = output.apply(
        lambda row: (
            f"{row.get('position_label')} "
            f"({percent_plain(as_number(row.get('position_in_3m_range_pct')))})"
        ),
        axis=1,
    )
    output["avg_daily_range_display"] = output.apply(
        lambda row: (
            f"약±{usd(as_number(row.get('avg_daily_range_amount')) / 2 if as_number(row.get('avg_daily_range_amount')) is not None else None)}"
            f"(±{(as_number(row.get('avg_daily_range_pct')) or 0) / 2:.2f}%)"
        ),
        axis=1,
    )
    output["earnings_guidance_event"] = output.apply(
        earnings_event_text,
        axis=1,
    )
    output["valuation_growth"] = output.apply(
        valuation_growth_text,
        axis=1,
    )
    output["score_recommendation_reason"] = output.apply(
        lambda row: (
            f"{as_number(row.get('score')):.1f}점 · "
            f"{row.get('recommendation_reason')}"
        ),
        axis=1,
    )
    output["market_ticker"] = output.apply(
        lambda row: f"{row.get('market')} · {row.get('symbol')}",
        axis=1,
    )
    output["sector_theme"] = output.apply(
        lambda row: (
            f"{row.get('sector')} / {row.get('industry')}"
        ),
        axis=1,
    )

    for column in OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = np.nan

    return output[OUTPUT_COLUMNS]


def build(
    *,
    input_path: Path,
    output_dir: Path,
    candidate_n: int,
    recommend_n: int,
) -> dict[str, Any]:
    raw = load_universe(input_path)
    valid, excluded = valid_universe(raw)
    enriched = enrich_rows(valid)
    candidates, recommends = choose_candidates(
        enriched,
        candidate_n=candidate_n,
        recommend_n=recommend_n,
    )

    candidate_output = display_frame(candidates)
    recommend_output = display_frame(recommends)

    candidate_symbols = set(candidate_output["symbol"])
    recommend_symbols = set(recommend_output["symbol"])
    outside = recommend_symbols - candidate_symbols

    summary = BuildSummary(
        input_rows=int(len(raw)),
        valid_rows=int(len(valid)),
        candidate_rows=int(len(candidate_output)),
        recommend_rows=int(len(recommend_output)),
        checkmark_count=int(
            candidate_output["recommend_flag"].eq("✅").sum()
        ),
        unique_candidate_symbols=int(
            candidate_output["symbol"].nunique()
        ),
        unique_recommend_symbols=int(
            recommend_output["symbol"].nunique()
        ),
        recommend_outside_candidates=int(len(outside)),
        hard_red_recommended=int(
            recommend_output["hard_red_flag"].astype(bool).sum()
        ),
        incomplete_rows_excluded=excluded,
        fundamentals_ready_candidates=int(
            candidate_output["fundamentals_status"]
            .eq("READY")
            .sum()
        ),
        fundamentals_limited_candidates=int(
            candidate_output["fundamentals_status"]
            .isin(["LIMITED", "MISSING", "FAILED"])
            .sum()
        ),
        min_candidate_score=float(
            candidate_output["score"].min()
        ),
        max_candidate_score=float(
            candidate_output["score"].max()
        ),
    )

    if summary.candidate_rows != candidate_n:
        raise RuntimeError("후보 행 수 계약 위반")
    if summary.recommend_rows != recommend_n:
        raise RuntimeError("추천 행 수 계약 위반")
    if summary.checkmark_count != recommend_n:
        raise RuntimeError("후보표 추천표시 수 계약 위반")
    if summary.recommend_outside_candidates != 0:
        raise RuntimeError("후보 밖 추천 종목 발견")
    if summary.hard_red_recommended != 0:
        raise RuntimeError("비적격 종목이 추천됨")

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = (
        output_dir / "us_sp500_watchlist_latest.csv"
    )
    recommend_path = (
        output_dir / "us_sp500_recommend_7_latest.csv"
    )
    status_path = (
        output_dir / "us_sp500_status_latest.json"
    )
    log_path = (
        output_dir / "us_sp500_run_log_latest.txt"
    )

    candidate_output.to_csv(
        candidate_path,
        index=False,
        encoding="utf-8-sig",
    )
    recommend_output.to_csv(
        recommend_path,
        index=False,
        encoding="utf-8-sig",
    )

    generated_at = now_kst()
    status = {
        "status": "OK",
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": generated_at,
        "table_id": "us_watchlist",
        "display_name": "미관종표",
        "market_scope": "S&P500 entire universe",
        "candidate_file": str(candidate_path),
        "recommend_file": str(recommend_path),
        "candidate_n": candidate_n,
        "recommend_n": recommend_n,
        "recommend_source": "candidate_top_30",
        "single_table_policy": True,
        "header_contract": [
            "추천/종목",
            "현재가",
            "가치매수구간",
            "1차 매도/익절가",
            "3개월저~고",
            "1개월 등락률",
            "평균거래대금/유동성",
            "현재위치",
            "하루평균 변동폭",
            "실적·가이던스/이벤트",
            "밸류에이션·성장성",
            "점수·추천·주의사유",
            "시장·티커",
            "섹터/테마",
        ],
        "summary": asdict(summary),
        "data_date_min": str(
            candidate_output["data_date"].min()
        ),
        "data_date_max": str(
            candidate_output["data_date"].max()
        ),
        "disclaimer": (
            "후보·추천은 자동화 참고자료이며 확정적 매수·매도 "
            "지시가 아니다. 확인되지 않은 실적·가이던스는 "
            "자료제한으로 표시한다."
        ),
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={generated_at}",
        "TABLE_ID=us_watchlist",
        "DISPLAY_NAME=미관종표",
        "MARKET_SCOPE=S&P500 entire universe",
        f"INPUT_FILE={input_path}",
        f"INPUT_ROWS={summary.input_rows}",
        f"VALID_ROWS={summary.valid_rows}",
        (
            "INCOMPLETE_ROWS_EXCLUDED="
            f"{summary.incomplete_rows_excluded}"
        ),
        f"CANDIDATE_ROWS={summary.candidate_rows}",
        f"RECOMMEND_ROWS={summary.recommend_rows}",
        f"CANDIDATE_CHECKMARK_COUNT={summary.checkmark_count}",
        "RECOMMEND_SOURCE=candidate_top_30",
        (
            "RECOMMEND_OUTSIDE_CANDIDATES="
            f"{summary.recommend_outside_candidates}"
        ),
        (
            "HARD_RED_RECOMMENDED="
            f"{summary.hard_red_recommended}"
        ),
        "SINGLE_TABLE_POLICY=true",
        (
            "FUNDAMENTALS_READY_CANDIDATES="
            f"{summary.fundamentals_ready_candidates}"
        ),
        (
            "FUNDAMENTALS_LIMITED_CANDIDATES="
            f"{summary.fundamentals_limited_candidates}"
        ),
        f"MIN_CANDIDATE_SCORE={summary.min_candidate_score}",
        f"MAX_CANDIDATE_SCORE={summary.max_candidate_score}",
        f"OUTPUT_CANDIDATE={candidate_path}",
        f"OUTPUT_RECOMMEND={recommend_path}",
        "US_WATCHLIST_STATUS=OK",
    ]
    log_path.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    return {
        "candidate_path": candidate_path,
        "recommend_path": recommend_path,
        "status_path": status_path,
        "log_path": log_path,
        "summary": summary,
    }


def synthetic_universe(rows: int = 120) -> pd.DataFrame:
    base_date = datetime(2026, 7, 2, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []

    sectors = [
        "Information Technology",
        "Health Care",
        "Financials",
        "Industrials",
        "Consumer Discretionary",
    ]

    for index in range(rows):
        current = 50 + index * 1.25
        low = current * (0.72 + (index % 5) * 0.01)
        high = current * (1.18 + (index % 4) * 0.01)
        ret1 = -5 + (index % 18) * 1.1
        ret3 = -8 + (index % 22) * 1.7
        revenue_growth = 0.04 + (index % 16) * 0.015
        earnings_growth = 0.03 + (index % 18) * 0.017
        forward_pe = 14 + (index % 20) * 1.1
        market_cap = 8_000_000_000 + index * 250_000_000
        target = current * (1.08 + (index % 6) * 0.015)

        records.append(
            {
                "symbol": f"T{index:03d}",
                "name": f"미국테스트기업{index:03d}",
                "market": (
                    "NASDAQ" if index % 2 == 0 else "NYSE"
                ),
                "sector": sectors[index % len(sectors)],
                "industry": f"테스트산업{index % 9}",
                "status": "OK",
                "data_date": "2026-07-02",
                "current_price": current,
                "low_3m": low,
                "high_3m": high,
                "return_1m_pct": ret1,
                "return_3m_pct": ret3,
                "avg_volume_20d": 2_000_000 + index * 15_000,
                "avg_trading_value_20d": (
                    120_000_000 + index * 25_000_000
                ),
                "avg_daily_range_pct": 1.4 + (index % 8) * 0.25,
                "sma20": current * 0.985,
                "sma60": current * 0.955,
                "rsi14": 43 + index % 24,
                "data_rows": 130,
                "fundamentals_status": "READY",
                "market_cap": market_cap,
                "trailing_pe": forward_pe + 2,
                "forward_pe": forward_pe,
                "price_to_book": 2.0 + index % 5,
                "peg_ratio": 1.1 + (index % 5) * 0.2,
                "revenue_growth": revenue_growth,
                "earnings_growth": earnings_growth,
                "profit_margin": 0.12 + (index % 10) * 0.012,
                "return_on_equity": 0.14 + (index % 10) * 0.015,
                "debt_to_equity": 40 + index % 80,
                "analyst_target_mean": target,
                "beta": 0.8 + (index % 8) * 0.08,
                "short_percent_float": 0.01 + (index % 4) * 0.008,
                "next_earnings_date": (
                    base_date + timedelta(days=20 + index % 40)
                ).date().isoformat(),
                "guidance_note": (
                    "최근 가이던스 유지"
                    if index % 3
                    else "가이던스 상향 여부 확인"
                ),
                "event_note": "",
            }
        )

    return pd.DataFrame(records)


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        input_path = root / "us_universe.csv"
        output_dir = root / "latest"

        synthetic_universe().to_csv(
            input_path,
            index=False,
            encoding="utf-8-sig",
        )

        result = build(
            input_path=input_path,
            output_dir=output_dir,
            candidate_n=30,
            recommend_n=7,
        )

        candidates = pd.read_csv(
            result["candidate_path"],
            encoding="utf-8-sig",
        )
        recommends = pd.read_csv(
            result["recommend_path"],
            encoding="utf-8-sig",
        )
        status = json.loads(
            result["status_path"].read_text(
                encoding="utf-8"
            )
        )
        log_text = result["log_path"].read_text(
            encoding="utf-8"
        )

        assert len(candidates) == 30
        assert len(recommends) == 7
        assert candidates["recommend_flag"].eq("✅").sum() == 7
        assert set(recommends["symbol"]).issubset(
            set(candidates["symbol"])
        )
        assert candidates["symbol"].nunique() == 30
        assert recommends["symbol"].nunique() == 7
        assert not recommends["hard_red_flag"].astype(bool).any()
        assert candidates["value_buy_low"].notna().all()
        assert candidates["value_buy_high"].notna().all()
        assert candidates["target1_low"].notna().all()
        assert candidates["target1_high"].notna().all()
        assert candidates[
            "position_in_3m_range_pct"
        ].between(0, 100).all()
        assert candidates["score"].between(0, 100).all()
        assert status["summary"]["recommend_outside_candidates"] == 0
        assert status["single_table_policy"] is True
        assert "RECOMMEND_SOURCE=candidate_top_30" in log_text
        assert "US_WATCHLIST_STATUS=OK" in log_text

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "sp500_candidate_30,"
        "recommend_7,"
        "recommend_subset,"
        "single_table_policy,"
        "three_month_position,"
        "value_buy_range,"
        "target_range,"
        "liquidity_labels,"
        "fundamental_score,"
        "hard_red_exclusion,"
        "output_files"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="latest/us_sp500_universe_summary_latest.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="latest",
    )
    parser.add_argument(
        "--candidate-n",
        type=int,
        default=DEFAULT_CANDIDATE_N,
    )
    parser.add_argument(
        "--recommend-n",
        type=int,
        default=DEFAULT_RECOMMEND_N,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    result = build(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        candidate_n=args.candidate_n,
        recommend_n=args.recommend_n,
    )
    summary: BuildSummary = result["summary"]

    print("US_WATCHLIST_STATUS=OK")
    print(f"INPUT_ROWS={summary.input_rows}")
    print(f"VALID_ROWS={summary.valid_rows}")
    print(f"CANDIDATE_ROWS={summary.candidate_rows}")
    print(f"RECOMMEND_ROWS={summary.recommend_rows}")
    print(
        "CANDIDATE_CHECKMARK_COUNT="
        f"{summary.checkmark_count}"
    )
    print("RECOMMEND_SOURCE=candidate_top_30")
    print(
        "RECOMMEND_OUTSIDE_CANDIDATES="
        f"{summary.recommend_outside_candidates}"
    )
    print(
        "HARD_RED_RECOMMENDED="
        f"{summary.hard_red_recommended}"
    )
    print("SINGLE_TABLE_POLICY=true")
    print(f"OUTPUT_CANDIDATE={result['candidate_path']}")
    print(f"OUTPUT_RECOMMEND={result['recommend_path']}")
    print(f"OUTPUT_STATUS={result['status_path']}")
    print(f"OUTPUT_LOG={result['log_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
