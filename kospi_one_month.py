#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kospi_one_month.py v1.1.0-candidate-contained-recommendations

코스피 전체 최근 1개월 가치후보 생성기.

입력
- latest/kospi_universe_summary_latest.csv

출력
- latest/kospi_1m_candidates_30_latest.csv
- latest/kospi_1m_recommend_7_latest.csv
- latest/kospi_1m_run_log_latest.txt
- latest/kospi_1m_status_latest.json

핵심 원칙
- 1개월 저가·고가·변동폭·현재위치를 실제 1개월 필드로 계산한다.
- 기존 코피표의 3개월 위치를 대신 사용하지 않는다.
- 후보 30개 본표 안에 추천 7개를 ✅로 표시한다.
- 별도 추천 7개 파일은 명시적 요청용 내부 산출물이다.
- 시장 점수는 기업가치 종합점수와 구분해
  one_month_market_score / legacy_market_score로 명시한다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


SCRIPT_VERSION = "kospi_one_month.py v1.2.0-complete-one-month-fields-only"
POLICY_VERSION = "2026-07-03-v6.0-kospi-one-month-value-candidates-v3"
KST = timezone(timedelta(hours=9))

OUTPUT_COLUMNS = [
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
    "low_1m",
    "high_1m",
    "range_1m_pct",
    "position_in_1m_range_pct",
    "current_position_period",
    "return_1m_pct",
    "return_3m_pct",
    "avg_volume",
    "avg_trading_value",
    "liquidity_flag",
    "overheat_flag",
    "data_rows_1m",
    "one_month_market_score",
    "one_month_market_reason",
    "score",
    "reason",
    "legacy_market_score",
    "legacy_market_reason",
]

REQUIRED_INPUT_COLUMNS = {
    "name",
    "ticker",
    "market",
    "status",
    "last_date",
    "current_close",
    "avg_daily_move_abs",
    "avg_daily_move_pct",
    "avg_wave_days",
    "low_1m_intraday",
    "high_1m_intraday",
    "range_1m_pct",
    "position_in_1m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "last_volume",
    "avg20_trading_value",
    "low_liquidity",
    "market_cap",
    "data_rows_1m",
}

COMPLETE_ONE_MONTH_NUMERIC_FIELDS = (
    "low_1m_intraday",
    "high_1m_intraday",
    "range_1m_pct",
    "position_in_1m_range_pct",
    "return_1m_pct",
)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        number = float(str(value).replace(",", "").strip())
        if not math.isfinite(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    number = safe_float(value, np.nan)
    if pd.isna(number):
        return default
    return int(round(number))


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def normalize_ticker(value: Any) -> str:
    text = str(value or "").strip().replace("'", "")
    match = re.search(r"\d{6}", text)
    return match.group(0) if match else ""


def kr_tick_round(value: Any) -> Optional[int]:
    number = safe_float(value, np.nan)
    if pd.isna(number) or number <= 0:
        return None

    if number < 2_000:
        unit = 1
    elif number < 5_000:
        unit = 5
    elif number < 20_000:
        unit = 10
    elif number < 50_000:
        unit = 50
    elif number < 200_000:
        unit = 100
    elif number < 500_000:
        unit = 500
    else:
        unit = 1_000

    return int(round(number / unit) * unit)


def fmt_won(value: Any) -> str:
    rounded = kr_tick_round(value)
    return f"{rounded:,}원" if rounded is not None else ""


def build_range_text(low: Any, high: Any) -> str:
    low_text = fmt_won(low)
    high_text = fmt_won(high)
    if low_text and high_text:
        return f"{low_text}~{high_text}"
    return low_text or high_text


def build_move_text(abs_move: Any, pct_move: Any) -> str:
    abs_number = safe_float(abs_move, np.nan)
    pct_number = safe_float(pct_move, np.nan)

    won = fmt_won(abs_number) if not pd.isna(abs_number) else ""
    pct = (
        f"±{pct_number:.2f}%"
        if not pd.isna(pct_number)
        else ""
    )

    if won and pct:
        return f"약 ±{won} 내외 ({pct})"
    if won:
        return f"약 ±{won} 내외"
    if pct:
        return f"약 {pct}"
    return ""


def is_excluded_stock(row: pd.Series) -> bool:
    name = str(row.get("name", "")).strip()
    name_upper = name.upper()
    ticker = normalize_ticker(row.get("ticker"))

    if not ticker:
        return True

    if "우선주" in name:
        return True
    if re.search(r"(\d우B|\d우|우B|우C|우)$", name):
        return True

    excluded_keywords = [
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
    if any(keyword in name_upper for keyword in excluded_keywords):
        return True

    if safe_float(row.get("current_close"), 0) <= 0:
        return True
    if safe_float(row.get("last_volume"), 0) <= 0:
        return True

    return False


def one_month_price_ranges(
    row: pd.Series,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    close = safe_float(row.get("current_close"), np.nan)
    low = safe_float(row.get("low_1m_intraday"), np.nan)
    high = safe_float(row.get("high_1m_intraday"), np.nan)
    move = safe_float(row.get("avg_daily_move_abs"), np.nan)

    if any(pd.isna(value) for value in (close, low, high)):
        return None, None, None, None
    if close <= 0 or low <= 0 or high < low:
        return None, None, None, None

    if pd.isna(move) or move <= 0:
        move = close * 0.025

    price_span = high - low

    if price_span > 0:
        buy_low = max(low * 1.01, close - move * 2.2)
        buy_high = min(close * 0.99, close - move * 0.2)

        if buy_low > buy_high:
            buy_low = min(close * 0.94, low + price_span * 0.35)
            buy_high = min(close * 0.99, low + price_span * 0.55)

        target_low = max(
            close * 1.03,
            min(close + move * 2.0, low + price_span * 0.78),
        )
        target_high = max(
            target_low * 1.03,
            min(close + move * 3.6, low + price_span * 0.92),
        )
    else:
        buy_low = close * 0.94
        buy_high = close * 0.99
        target_low = close * 1.06
        target_high = close * 1.12

    buy_low_r = kr_tick_round(buy_low)
    buy_high_r = kr_tick_round(buy_high)
    target_low_r = kr_tick_round(target_low)
    target_high_r = kr_tick_round(target_high)

    if (
        buy_low_r is not None
        and buy_high_r is not None
        and buy_low_r > buy_high_r
    ):
        buy_low_r, buy_high_r = buy_high_r, buy_low_r

    if (
        target_low_r is not None
        and target_high_r is not None
        and target_low_r > target_high_r
    ):
        target_low_r, target_high_r = target_high_r, target_low_r

    return buy_low_r, buy_high_r, target_low_r, target_high_r


def score_one_month_candidate(row: pd.Series) -> Dict[str, Any]:
    """
    최근 1개월 시장조건 점수 0~100.

    구성
    - 1개월 현재위치·가격매력: 30
    - 1개월 수익률·추세: 20
    - 거래활발도: 20
    - 가격탄력: 10
    - 1개월 변동폭: 10
    - 시가총액 안정성: 5
    - 자료충분도: 5
    """
    score = 0.0
    reasons: List[str] = []

    position = safe_float(
        row.get("position_in_1m_range_pct"),
        np.nan,
    )
    return_1m = safe_float(row.get("return_1m_pct"), np.nan)
    avg_tv = safe_float(row.get("avg20_trading_value"), np.nan)
    avg_move = safe_float(row.get("avg_daily_move_pct"), np.nan)
    range_1m = safe_float(row.get("range_1m_pct"), np.nan)
    market_cap = safe_float(row.get("market_cap"), np.nan)
    data_rows = safe_int(row.get("data_rows_1m"), 0)
    low_liquidity = safe_bool(row.get("low_liquidity"))

    overheat = False
    liquidity_burden = False
    severe_weakness = False

    # 1개월 현재위치·가격매력: 30
    if not pd.isna(position):
        if position <= 20:
            score += 23
            reasons.append(f"1개월 저점권 {position:.1f}%")
        elif position <= 35:
            score += 30
            reasons.append(f"1개월 반등초입 {position:.1f}%")
        elif position <= 65:
            score += 26
            reasons.append(f"1개월 중간권 {position:.1f}%")
        elif position <= 80:
            score += 18
            reasons.append(f"1개월 중상단 {position:.1f}%")
        elif position <= 92:
            score += 8
            reasons.append(f"1개월 상단부담 {position:.1f}%")
        else:
            score += 1
            overheat = True
            reasons.append(f"1개월 고점과열 {position:.1f}%")
    else:
        reasons.append("1개월 현재위치 확인제한")

    # 1개월 수익률·추세: 20
    if not pd.isna(return_1m):
        if return_1m < -15:
            score += 2
            severe_weakness = True
            reasons.append(f"1개월 급락 {return_1m:.1f}%")
        elif return_1m < -8:
            score += 7
            severe_weakness = True
            reasons.append(f"1개월 약세 {return_1m:.1f}%")
        elif return_1m < -3:
            score += 13
            reasons.append(f"1개월 조정 {return_1m:.1f}%")
        elif return_1m <= 12:
            score += 20
            reasons.append(f"1개월 흐름 양호 {return_1m:.1f}%")
        elif return_1m <= 20:
            score += 15
            reasons.append(f"1개월 상승 {return_1m:.1f}%")
        elif return_1m <= 30:
            score += 8
            overheat = True
            reasons.append(f"1개월 상승부담 {return_1m:.1f}%")
        else:
            score += 1
            overheat = True
            reasons.append(f"1개월 급등과열 {return_1m:.1f}%")
    else:
        reasons.append("1개월 수익률 확인제한")

    # 거래활발도: 20
    if low_liquidity or (
        not pd.isna(avg_tv) and avg_tv < 1_000_000_000
    ):
        score += 0
        liquidity_burden = True
        reasons.append("거래대금 매우부족")
    elif not pd.isna(avg_tv) and avg_tv >= 100_000_000_000:
        score += 20
        reasons.append("거래 매우활발")
    elif not pd.isna(avg_tv) and avg_tv >= 30_000_000_000:
        score += 17
        reasons.append("거래 활발")
    elif not pd.isna(avg_tv) and avg_tv >= 5_000_000_000:
        score += 12
        reasons.append("거래 보통")
    elif not pd.isna(avg_tv):
        score += 5
        liquidity_burden = True
        reasons.append("거래 부족")
    else:
        reasons.append("거래대금 확인제한")

    # 가격탄력: 10
    if not pd.isna(avg_move):
        if avg_move < 1.5:
            score += 5
            reasons.append(f"탄력 낮음 {avg_move:.2f}%")
        elif avg_move < 3.0:
            score += 10
            reasons.append(f"탄력 보통 {avg_move:.2f}%")
        elif avg_move < 5.0:
            score += 8
            reasons.append(f"탄력 높음 {avg_move:.2f}%")
        else:
            score += 2
            overheat = True
            reasons.append(f"탄력 불안정 {avg_move:.2f}%")
    else:
        reasons.append("가격탄력 확인제한")

    # 1개월 변동폭: 10
    if not pd.isna(range_1m):
        if range_1m < 8:
            score += 4
            reasons.append(f"1개월 변동폭 작음 {range_1m:.1f}%")
        elif range_1m <= 35:
            score += 10
            reasons.append(f"1개월 변동폭 적정 {range_1m:.1f}%")
        elif range_1m <= 55:
            score += 6
            reasons.append(f"1개월 변동폭 큼 {range_1m:.1f}%")
        else:
            score += 1
            overheat = True
            reasons.append(f"1개월 변동폭 과대 {range_1m:.1f}%")
    else:
        reasons.append("1개월 변동폭 확인제한")

    # 시가총액 안정성: 5
    if not pd.isna(market_cap):
        if market_cap >= 5_000_000_000_000:
            score += 5
            reasons.append("대형주 안정성")
        elif market_cap >= 1_000_000_000_000:
            score += 4
        elif market_cap >= 300_000_000_000:
            score += 3
        else:
            score += 1
            reasons.append("소형주 변동주의")

    # 자료충분도: 5
    if data_rows >= 18:
        score += 5
    elif data_rows >= 15:
        score += 3
        reasons.append(f"1개월 자료 {data_rows}일")
    else:
        reasons.append(f"1개월 자료부족 {data_rows}일")

    score = round(max(0.0, min(100.0, score)), 2)

    hard_red = (
        (not pd.isna(position) and position > 92)
        or (not pd.isna(return_1m) and return_1m > 35)
    )
    warning = (
        liquidity_burden
        or overheat
        or severe_weakness
        or data_rows < 15
    )
    recommendation_eligible = (
        not warning
        and score >= 65
        and (
            pd.isna(position)
            or position <= 80
        )
        and (
            pd.isna(return_1m)
            or -8 <= return_1m <= 20
        )
    )

    return {
        "score": score,
        "reason": "; ".join(reasons[:7]),
        "overheat_flag": bool(overheat),
        "liquidity_flag": bool(liquidity_burden),
        "hard_red": bool(hard_red),
        "warning": bool(warning),
        "recommendation_eligible": bool(
            recommendation_eligible
        ),
    }


def row_to_output(
    row: pd.Series,
    rank: int,
    recommend_flag: str,
) -> Dict[str, Any]:
    buy_low, buy_high, target_low, target_high = (
        one_month_price_ranges(row)
    )

    market_score = safe_float(
        row.get("_one_month_market_score"),
        0.0,
    )
    market_reason = str(
        row.get("_one_month_market_reason", "")
    )

    return {
        "rank": rank,
        "recommend_flag": recommend_flag,
        "code": normalize_ticker(row.get("ticker")).zfill(6),
        "name": str(row.get("name", "")),
        "market": "KOSPI",
        "asof_date": str(row.get("last_date", "")),
        "close": kr_tick_round(row.get("current_close")),
        "buy_range": build_range_text(buy_low, buy_high),
        "sell_range": build_range_text(target_low, target_high),
        "avg_daily_move_text": build_move_text(
            row.get("avg_daily_move_abs"),
            row.get("avg_daily_move_pct"),
        ),
        "avg_wave_days": row.get("avg_wave_days"),
        "low_1m": kr_tick_round(row.get("low_1m_intraday")),
        "high_1m": kr_tick_round(row.get("high_1m_intraday")),
        "range_1m_pct": safe_float(
            row.get("range_1m_pct"),
            np.nan,
        ),
        "position_in_1m_range_pct": safe_float(
            row.get("position_in_1m_range_pct"),
            np.nan,
        ),
        "current_position_period": "1개월",
        "return_1m_pct": safe_float(
            row.get("return_1m_pct"),
            np.nan,
        ),
        "return_3m_pct": safe_float(
            row.get("return_3m_pct"),
            np.nan,
        ),
        "avg_volume": safe_int(row.get("last_volume"), 0),
        "avg_trading_value": safe_int(
            row.get("avg20_trading_value"),
            0,
        ),
        "liquidity_flag": bool(
            row.get("_liquidity_flag", False)
        ),
        "overheat_flag": bool(
            row.get("_overheat_flag", False)
        ),
        "data_rows_1m": safe_int(
            row.get("data_rows_1m"),
            0,
        ),
        "one_month_market_score": market_score,
        "one_month_market_reason": market_reason,
        "score": market_score,
        "reason": market_reason,
        "legacy_market_score": market_score,
        "legacy_market_reason": market_reason,
    }


def build_candidates(
    summary: pd.DataFrame,
    candidate_n: int = 30,
    recommend_n: int = 7,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    if summary is None or summary.empty:
        raise ValueError("KOSPI summary is empty")

    missing = sorted(REQUIRED_INPUT_COLUMNS - set(summary.columns))
    if missing:
        raise ValueError(
            "KOSPI summary missing one-month columns: "
            + ",".join(missing)
        )

    frame = summary.copy()
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["market"] = (
        frame["market"].astype(str).str.upper().str.strip()
    )
    frame["status"] = (
        frame["status"].astype(str).str.upper().str.strip()
    )

    frame = frame[
        frame["market"].eq("KOSPI")
        & frame["status"].eq("OK")
    ].copy()

    before_exclusion = len(frame)
    frame = frame[
        ~frame.apply(is_excluded_stock, axis=1)
    ].copy()
    after_exclusion = len(frame)

    data_rows_1m = pd.to_numeric(
        frame["data_rows_1m"],
        errors="coerce",
    ).fillna(0)
    frame = frame[
        data_rows_1m >= 15
    ].copy()
    after_data_rows_filter = len(frame)

    # 후보 점수와 매수·익절구간에 필요한 1개월 수치가
    # 하나라도 비어 있으면 후보 모집단에서 명시적으로 제외한다.
    numeric_1m = {
        field: pd.to_numeric(
            frame[field],
            errors="coerce",
        )
        for field in COMPLETE_ONE_MONTH_NUMERIC_FIELDS
    }
    complete_mask = pd.Series(
        True,
        index=frame.index,
        dtype=bool,
    )
    for values in numeric_1m.values():
        complete_mask &= values.notna()

    complete_mask &= numeric_1m[
        "low_1m_intraday"
    ].gt(0)
    complete_mask &= numeric_1m[
        "high_1m_intraday"
    ].gt(
        numeric_1m["low_1m_intraday"]
    )
    complete_mask &= numeric_1m[
        "range_1m_pct"
    ].gt(0)
    complete_mask &= numeric_1m[
        "position_in_1m_range_pct"
    ].between(0, 100, inclusive="both")

    incomplete_one_month_rows = int(
        (~complete_mask).sum()
    )
    frame = frame[
        complete_mask
    ].copy()
    after_complete_filter = len(frame)

    if len(frame) < candidate_n:
        raise ValueError(
            "Complete KOSPI one-month rows are insufficient: "
            f"{len(frame)} < {candidate_n}"
        )

    scored_rows: List[Dict[str, Any]] = []
    for _, row in frame.iterrows():
        scoring = score_one_month_candidate(row)
        data = row.to_dict()
        data["_one_month_market_score"] = scoring["score"]
        data["_one_month_market_reason"] = scoring["reason"]
        data["_overheat_flag"] = scoring["overheat_flag"]
        data["_liquidity_flag"] = scoring["liquidity_flag"]
        data["_hard_red"] = scoring["hard_red"]
        data["_warning"] = scoring["warning"]
        data["_recommendation_eligible"] = scoring[
            "recommendation_eligible"
        ]
        scored_rows.append(data)

    scored = pd.DataFrame(scored_rows)
    scored = scored.sort_values(
        [
            "_one_month_market_score",
            "avg20_trading_value",
            "return_1m_pct",
        ],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    top = scored.head(candidate_n).copy()

    # 추천 7개는 반드시 후보 30개 안에서만 선정한다.
    # 전체 종목에서 따로 추천을 뽑으면 후보표 밖 종목이
    # 추천으로 들어갈 수 있으므로 top을 유일한 모집단으로 사용한다.
    eligible = top[
        top["_recommendation_eligible"].astype(bool)
    ].copy()
    recommend_base = eligible.head(recommend_n).copy()

    if len(recommend_base) < recommend_n:
        fallback_safe = top[
            (~top.index.isin(recommend_base.index))
            & (~top["_hard_red"].astype(bool))
            & (~top["_liquidity_flag"].astype(bool))
        ].head(recommend_n - len(recommend_base))
        recommend_base = pd.concat(
            [recommend_base, fallback_safe],
            ignore_index=False,
        )

    # 안전 후보가 부족한 극단적 시장에서도 추천행 수를 7개로
    # 유지하되, 후보 30개 밖으로는 절대 나가지 않는다.
    if len(recommend_base) < recommend_n:
        fallback_any = top[
            ~top.index.isin(recommend_base.index)
        ].head(recommend_n - len(recommend_base))
        recommend_base = pd.concat(
            [recommend_base, fallback_any],
            ignore_index=False,
        )

    recommend_base = recommend_base.head(recommend_n)
    recommend_codes = set(
        recommend_base["ticker"].astype(str)
    )

    candidate_rows = []
    for rank, (_, row) in enumerate(
        top.iterrows(),
        start=1,
    ):
        ticker = str(row.get("ticker", ""))
        if ticker in recommend_codes:
            flag = "✅"
        elif bool(row.get("_hard_red", False)):
            flag = "🔻"
        elif bool(row.get("_warning", False)):
            flag = "⚠️"
        else:
            flag = "🟡"

        candidate_rows.append(
            row_to_output(row, rank, flag)
        )

    recommend_rows = []
    recommend_sorted = recommend_base.sort_values(
        [
            "_one_month_market_score",
            "avg20_trading_value",
        ],
        ascending=[False, False],
        na_position="last",
    ).head(recommend_n)

    for rank, (_, row) in enumerate(
        recommend_sorted.iterrows(),
        start=1,
    ):
        recommend_rows.append(
            row_to_output(row, rank, "✅")
        )

    candidates = pd.DataFrame(
        candidate_rows,
        columns=OUTPUT_COLUMNS,
    )
    recommends = pd.DataFrame(
        recommend_rows,
        columns=OUTPUT_COLUMNS,
    )

    metadata = {
        "input_rows": int(len(summary)),
        "kospi_ok_rows_before_exclusion": int(before_exclusion),
        "rows_after_security_exclusion": int(after_exclusion),
        "rows_after_data_rows_filter": int(
            after_data_rows_filter
        ),
        "rows_excluded_incomplete_one_month": int(
            incomplete_one_month_rows
        ),
        "rows_after_one_month_data_filter": int(
            after_complete_filter
        ),
        "complete_one_month_fields_required": list(
            COMPLETE_ONE_MONTH_NUMERIC_FIELDS
        ),
        "candidate_rows": int(len(candidates)),
        "recommend_rows": int(len(recommends)),
        "candidate_n": int(candidate_n),
        "recommend_n": int(recommend_n),
        "minimum_data_rows_1m": 15,
        "position_period": "1개월",
        "recommend_source": "candidate_top_30",
        "recommend_outside_candidates": 0,
    }

    return candidates, recommends, metadata


def write_outputs(
    candidates: pd.DataFrame,
    recommends: pd.DataFrame,
    metadata: Dict[str, Any],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_path = (
        output_dir / "kospi_1m_candidates_30_latest.csv"
    )
    recommend_path = (
        output_dir / "kospi_1m_recommend_7_latest.csv"
    )
    log_path = output_dir / "kospi_1m_run_log_latest.txt"
    status_path = output_dir / "kospi_1m_status_latest.json"

    candidates.to_csv(
        candidate_path,
        index=False,
        encoding="utf-8-sig",
    )
    recommends.to_csv(
        recommend_path,
        index=False,
        encoding="utf-8-sig",
    )

    status = {
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "run_at_kst": now_kst(),
        "status": "OK",
        "table_id": "kospi_1m",
        "display_name": "코피표1개월",
        "analysis_scope": (
            "코스피 전체 최근 1개월 가치후보 "
            "30개·추천 7개"
        ),
        "position_period": "1개월",
        "candidate_file": candidate_path.name,
        "recommend_file": recommend_path.name,
        **metadata,
    }
    status_path.write_text(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={status['run_at_kst']}",
        "STATUS=OK",
        "TABLE_ID=kospi_1m",
        "DISPLAY_NAME=코피표1개월",
        "ANALYSIS_SCOPE=KOSPI_ALL_RECENT_ONE_MONTH",
        "POSITION_PERIOD=1개월",
        f"INPUT_ROWS={metadata['input_rows']}",
        (
            "ROWS_AFTER_SECURITY_EXCLUSION="
            f"{metadata['rows_after_security_exclusion']}"
        ),
        (
            "ROWS_AFTER_DATA_ROWS_FILTER="
            f"{metadata['rows_after_data_rows_filter']}"
        ),
        (
            "ROWS_EXCLUDED_INCOMPLETE_ONE_MONTH="
            f"{metadata['rows_excluded_incomplete_one_month']}"
        ),
        (
            "ROWS_AFTER_ONE_MONTH_DATA_FILTER="
            f"{metadata['rows_after_one_month_data_filter']}"
        ),
        (
            "COMPLETE_ONE_MONTH_FIELDS_REQUIRED="
            + ",".join(
                metadata[
                    "complete_one_month_fields_required"
                ]
            )
        ),
        f"CANDIDATE_ROWS={len(candidates)}",
        f"RECOMMEND_ROWS={len(recommends)}",
        "CANDIDATE_EXPECTED=30",
        "RECOMMEND_EXPECTED=7",
        "ONE_MONTH_LOW_HIGH_SOURCE=low_1m_intraday,high_1m_intraday",
        (
            "ONE_MONTH_POSITION_SOURCE="
            "position_in_1m_range_pct"
        ),
        "THREE_MONTH_POSITION_REUSED=false",
        "RECOMMEND_SOURCE=candidate_top_30",
        "RECOMMEND_OUTSIDE_CANDIDATES=0",
        "DEFAULT_OUTPUT=single_candidate_table",
        "SEPARATE_RECOMMEND_TABLE=explicit_request_only",
    ]
    log_path.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )


def run(
    input_path: Path,
    output_dir: Path,
    candidate_n: int,
    recommend_n: int,
) -> Dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input summary not found: {input_path}"
        )

    summary = pd.read_csv(
        input_path,
        encoding="utf-8-sig",
        dtype={"ticker": str},
    )

    candidates, recommends, metadata = build_candidates(
        summary,
        candidate_n=candidate_n,
        recommend_n=recommend_n,
    )

    if len(candidates) != candidate_n:
        raise RuntimeError(
            f"Candidate count mismatch: {len(candidates)}"
        )
    if len(recommends) != recommend_n:
        raise RuntimeError(
            f"Recommend count mismatch: {len(recommends)}"
        )
    if candidates["code"].duplicated().any():
        raise RuntimeError("Duplicate candidate code found")
    if recommends["code"].duplicated().any():
        raise RuntimeError("Duplicate recommend code found")
    if set(recommends["code"]) - set(candidates["code"]):
        raise RuntimeError(
            "Recommend rows must be included in candidate table"
        )
    if set(
        candidates.loc[
            candidates["recommend_flag"].eq("✅"),
            "code",
        ]
    ) != set(recommends["code"]):
        raise RuntimeError(
            "Candidate ✅ rows and recommend rows differ"
        )
    if not candidates["current_position_period"].eq(
        "1개월"
    ).all():
        raise RuntimeError(
            "All current_position_period values must be 1개월"
        )

    write_outputs(
        candidates,
        recommends,
        metadata,
        output_dir,
    )

    return metadata


def synthetic_summary(rows: int = 80) -> pd.DataFrame:
    records = []
    for index in range(rows):
        close = 10_000 + index * 250
        low = close * (0.78 + (index % 5) * 0.02)
        high = close * (1.08 + (index % 7) * 0.015)
        position = (
            (close - low) / (high - low) * 100
            if high > low
            else 50
        )

        return_1m = -7 + (index % 25) * 1.1
        avg_tv = (
            140_000_000_000
            if index % 4 == 0
            else 45_000_000_000
            if index % 4 == 1
            else 12_000_000_000
            if index % 4 == 2
            else 3_000_000_000
        )

        records.append(
            {
                "name": f"테스트종목{index:03d}",
                "ticker": f"{index + 100000:06d}",
                "market": "KOSPI",
                "status": "OK",
                "last_date": "2026-07-01",
                "current_close": round(close),
                "avg_daily_move_abs": round(close * 0.022),
                "avg_daily_move_pct": 2.2 + (index % 4) * 0.45,
                "avg_wave_days": 3.0 + (index % 4),
                "low_1m_intraday": round(low),
                "high_1m_intraday": round(high),
                "low_1m_close": round(low * 1.01),
                "high_1m_close": round(high * 0.99),
                "range_1m_pct": round(
                    (high - low) / low * 100,
                    2,
                ),
                "position_in_1m_range_pct": round(
                    position,
                    2,
                ),
                "return_1m_pct": round(return_1m, 2),
                "return_3m_pct": round(return_1m * 1.8, 2),
                "last_volume": 500_000 + index * 3_000,
                "avg20_trading_value": avg_tv,
                "low_liquidity": avg_tv < 5_000_000_000,
                "market_cap": (
                    8_000_000_000_000
                    if index % 5 == 0
                    else 1_500_000_000_000
                ),
                "listed_shares": 100_000_000,
                "data_rows_1m": 20,
            }
        )

    return pd.DataFrame(records)


def run_self_test() -> int:
    frame = synthetic_summary()

    # 높은 거래대금과 양호한 수익률을 가진 행이라도
    # 1개월 저가가 없으면 후보 모집단에서 제외되어야 한다.
    incomplete = frame.iloc[0].copy()
    incomplete["ticker"] = "999999"
    incomplete["name"] = "불완전1개월자료"
    incomplete["low_1m_intraday"] = np.nan
    incomplete["range_1m_pct"] = np.nan
    incomplete["avg20_trading_value"] = 500_000_000_000
    incomplete["return_1m_pct"] = 5.0
    frame = pd.concat(
        [
            frame,
            pd.DataFrame([incomplete]),
        ],
        ignore_index=True,
    )

    candidates, recommends, metadata = build_candidates(
        frame,
        candidate_n=30,
        recommend_n=7,
    )

    assert len(candidates) == 30
    assert len(recommends) == 7
    assert candidates["code"].is_unique
    assert recommends["code"].is_unique
    assert set(recommends["code"]).issubset(
        set(candidates["code"])
    )
    assert candidates["current_position_period"].eq(
        "1개월"
    ).all()
    assert candidates["low_1m"].notna().all()
    assert candidates["high_1m"].notna().all()
    assert candidates[
        "position_in_1m_range_pct"
    ].notna().all()
    assert (
        candidates["legacy_market_score"]
        == candidates["one_month_market_score"]
    ).all()
    assert (
        candidates["legacy_market_reason"]
        == candidates["one_month_market_reason"]
    ).all()
    assert set(
        candidates.loc[
            candidates["recommend_flag"].eq("✅"),
            "code",
        ]
    ) == set(recommends["code"])
    assert metadata["position_period"] == "1개월"
    assert metadata["recommend_source"] == "candidate_top_30"
    assert metadata["recommend_outside_candidates"] == 0
    assert metadata[
        "rows_excluded_incomplete_one_month"
    ] >= 1
    assert "999999" not in set(candidates["code"])
    assert set(recommends["code"]).issubset(
        set(candidates["code"])
    )

    score_values = candidates["one_month_market_score"]
    assert score_values.between(0, 100).all()

    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        input_path = output_dir / "summary.csv"
        frame.to_csv(
            input_path,
            index=False,
            encoding="utf-8-sig",
        )
        run(
            input_path=input_path,
            output_dir=output_dir,
            candidate_n=30,
            recommend_n=7,
        )

        expected = [
            "kospi_1m_candidates_30_latest.csv",
            "kospi_1m_recommend_7_latest.csv",
            "kospi_1m_run_log_latest.txt",
            "kospi_1m_status_latest.json",
        ]
        for name in expected:
            assert (output_dir / name).exists()

        log_text = (
            output_dir / "kospi_1m_run_log_latest.txt"
        ).read_text(encoding="utf-8")
        assert "CANDIDATE_ROWS=30" in log_text
        assert "RECOMMEND_ROWS=7" in log_text
        assert "THREE_MONTH_POSITION_REUSED=false" in log_text

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "candidate_30,"
        "recommend_7,"
        "one_month_low_high,"
        "one_month_position,"
        "incomplete_one_month_rows_excluded,"
        "score_0_100,"
        "recommend_subset,"
        "recommend_selected_only_from_top30,"
        "single_table_policy,"
        "output_files"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="latest/kospi_universe_summary_latest.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="latest",
    )
    parser.add_argument(
        "--candidate-n",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--recommend-n",
        type=int,
        default=7,
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

    metadata = run(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        candidate_n=args.candidate_n,
        recommend_n=args.recommend_n,
    )

    print(f"SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"POLICY_VERSION={POLICY_VERSION}")
    print("KOSPI_ONE_MONTH_STATUS=OK")
    print(
        f"ROWS_AFTER_DATA_ROWS_FILTER="
        f"{metadata['rows_after_data_rows_filter']}"
    )
    print(
        "ROWS_EXCLUDED_INCOMPLETE_ONE_MONTH="
        f"{metadata['rows_excluded_incomplete_one_month']}"
    )
    print(
        f"ROWS_AFTER_ONE_MONTH_DATA_FILTER="
        f"{metadata['rows_after_one_month_data_filter']}"
    )
    print(
        "COMPLETE_ONE_MONTH_FIELDS_REQUIRED="
        + ",".join(
            metadata[
                "complete_one_month_fields_required"
            ]
        )
    )
    print(f"CANDIDATE_ROWS={metadata['candidate_rows']}")
    print(f"RECOMMEND_ROWS={metadata['recommend_rows']}")
    print("POSITION_PERIOD=1개월")
    print("THREE_MONTH_POSITION_REUSED=false")
    print("RECOMMEND_SOURCE=candidate_top_30")
    print("RECOMMEND_OUTSIDE_CANDIDATES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
