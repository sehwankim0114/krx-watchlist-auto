#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
request_time_explanation_refresher.py v1.0.0-deterministic-refresh

요청시점 현재가가 조회된 뒤 가격 의존 항목을 결정적으로 다시 계산한다.

보존하는 정적 항목
- 공식 분석 점수 및 레거시 시장점수
- 재무·실적·밸류에이션
- 수급·공시·영업손실 상태
- 공식 기준 저가·고가
- 공식 분석에서 산출된 가치매수구간과 1차 매도/익절가 범위

요청 때마다 다시 만드는 동적 항목
- 요청시점 현재가
- 공식 기준가격 대비 괴리율
- 공식 기간 저가~고가 대비 현재위치
- 가치매수구간 도달 여부
- 익절구간 접근/진입 여부
- 당일 급등락 해석
- 가격을 반영한 최종 표시등급
- 가격 관련 설명문

중요
- 기존 reason 문장에 보정 메모를 덧붙이지 않는다.
- 가격 관련 설명문은 요청시점 현재가로 처음부터 다시 작성한다.
- 가격 조회 실패 시 정적 GitHub 가격을 요청시점 가격처럼 사용하지 않는다.
- 가격은 기업가치·수급 위험을 개선시키지 못한다. 가격 때문에 등급은 유지 또는 하향만 가능하다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


SCRIPT_VERSION = (
    "request_time_explanation_refresher.py "
    "v1.0.0-deterministic-refresh"
)
POLICY_VERSION = "2026-07-01-v6.0-request-time-explanation-refresh"

PRICE_STATUS_OK = "OK"
PRICE_STATUS_FAILED = "FAILED"
PRICE_STATUS_LIMITED = "LIMITED"

POSITION_LABELS = {
    "LOW": "저점권",
    "LOW_REBOUND": "저점권반등초입",
    "MIDDLE": "중간권",
    "MID_UPPER": "중상단권",
    "UPPER_BURDEN": "상단권부담",
    "HIGH_OVERHEATED": "고점권과열",
}

ZONE_LABELS = {
    "BELOW_BUY_ZONE": "매수구간 아래",
    "BUY_ZONE": "가치매수구간",
    "ABOVE_BUY_ZONE": "매수구간 위·익절구간 전",
    "TAKE_PROFIT_ZONE": "1차 매도·익절구간",
    "ABOVE_TARGET": "1차 익절가 위",
    "RANGE_UNAVAILABLE": "가격구간 확인 불가",
    "QUOTE_FAILED": "요청시점 현재가 확인 불가",
}

BASE_MARK_PRIORITY = {
    "✅": 0,
    "🟡": 1,
    "⚠️": 2,
    "🔻": 3,
}

PRICE_MARK_PRIORITY = {
    "✅": 0,
    "🟡": 1,
    "⚠️": 2,
    "🔻": 3,
}

PRICE_FIELDS = (
    "request_time_price",
    "price",
    "current_price",
    "quote_price",
    "last",
)

OFFICIAL_PRICE_FIELDS = (
    "official_price",
    "current_close",
    "close",
    "current_price",
    "price",
)

CHANGE_PCT_FIELDS = (
    "change_pct",
    "change_percent",
    "pct_change",
    "day_change_pct",
)

LOW_FIELDS = (
    "low_1m",
    "low_1m_intraday",
    "low_3m",
    "low_3m_intraday",
    "recent_3m_low",
    "range_low_3m",
)

HIGH_FIELDS = (
    "high_1m",
    "high_1m_intraday",
    "high_3m",
    "high_3m_intraday",
    "recent_3m_high",
    "range_high_3m",
)

BUY_LOW_FIELDS = (
    "value_buy_low",
    "buy_low",
    "value_buy_zone_low",
    "value_buy_range_low",
)

BUY_HIGH_FIELDS = (
    "value_buy_high",
    "buy_high",
    "value_buy_zone_high",
    "value_buy_range_high",
)

BUY_TEXT_FIELDS = (
    "value_buy_range",
    "value_buy_zone",
    "value_buy_range_text",
    "가치매수구간",
)

TARGET_LOW_FIELDS = (
    "take_profit_low",
    "target_low",
    "first_sell_low",
    "first_take_profit_low",
)

TARGET_HIGH_FIELDS = (
    "take_profit_high",
    "target_high",
    "first_sell_high",
    "first_take_profit_high",
)

TARGET_TEXT_FIELDS = (
    "take_profit_range",
    "target_range",
    "first_sell_range",
    "first_take_profit_range",
    "1차 매도/익절가",
)

BASE_RECOMMENDATION_FIELDS = (
    "base_recommendation",
    "recommendation",
    "recommendation_mark",
    "signal",
    "추천",
)

SCORE_FIELDS = (
    "final_score",
    "score",
    "legacy_market_score",
)

STATIC_REASON_FIELDS = (
    "static_non_price_reason",
    "fundamental_reason",
    "financial_reason",
    "legacy_market_reason",
)


def parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    if text.lower() in {"", "-", "nan", "none", "null", "n/a"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    text = (
        text.replace(",", "")
        .replace("원", "")
        .replace("KRW", "")
        .replace("%", "")
        .replace("+", "")
        .strip()
    )
    text = re.sub(r"[^0-9eE.\-]", "", text)

    if text in {"", "-", ".", "-."}:
        return None

    try:
        number = float(text)
    except ValueError:
        return None

    if not math.isfinite(number):
        return None

    return -abs(number) if negative else number


def first_number(
    row: Mapping[str, Any],
    fields: Iterable[str],
) -> Tuple[Optional[float], str]:
    for field in fields:
        if field not in row:
            continue
        number = parse_number(row.get(field))
        if number is not None:
            return number, field
    return None, ""


def first_text(
    row: Mapping[str, Any],
    fields: Iterable[str],
) -> Tuple[str, str]:
    for field in fields:
        if field not in row:
            continue
        text = str(row.get(field, "")).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text, field
    return "", ""


def parse_price_range(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if value is None:
        return None, None

    text = str(value).strip()
    if not text:
        return None, None

    cleaned = (
        text.replace("**", "")
        .replace(",", "")
        .replace("원", "")
        .replace("KRW", "")
    )

    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if len(numbers) < 2:
        return None, None

    try:
        first = float(numbers[0])
        second = float(numbers[1])
    except ValueError:
        return None, None

    low, high = sorted((first, second))
    return low, high


def extract_range(
    row: Mapping[str, Any],
    low_fields: Sequence[str],
    high_fields: Sequence[str],
    text_fields: Sequence[str],
) -> Tuple[Optional[float], Optional[float], str]:
    low, low_source = first_number(row, low_fields)
    high, high_source = first_number(row, high_fields)

    if low is not None and high is not None and high >= low:
        return low, high, f"{low_source}+{high_source}"

    for field in text_fields:
        if field not in row:
            continue
        parsed_low, parsed_high = parse_price_range(row.get(field))
        if parsed_low is not None and parsed_high is not None:
            return parsed_low, parsed_high, field

    return None, None, ""


def position_pct(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    if (
        price is None
        or low is None
        or high is None
        or high <= low
    ):
        return None

    return round((price - low) / (high - low) * 100.0, 2)


def position_label(value: Optional[float]) -> str:
    if value is None:
        return "확인 불가"
    if value <= 20:
        return POSITION_LABELS["LOW"]
    if value <= 35:
        return POSITION_LABELS["LOW_REBOUND"]
    if value <= 65:
        return POSITION_LABELS["MIDDLE"]
    if value <= 80:
        return POSITION_LABELS["MID_UPPER"]
    if value <= 92:
        return POSITION_LABELS["UPPER_BURDEN"]
    return POSITION_LABELS["HIGH_OVERHEATED"]


def price_zone(
    price: Optional[float],
    buy_low: Optional[float],
    buy_high: Optional[float],
    target_low: Optional[float],
    target_high: Optional[float],
) -> str:
    if price is None:
        return "QUOTE_FAILED"

    if (
        buy_low is None
        or buy_high is None
        or target_low is None
        or target_high is None
    ):
        return "RANGE_UNAVAILABLE"

    if price < buy_low:
        return "BELOW_BUY_ZONE"
    if price <= buy_high:
        return "BUY_ZONE"
    if price < target_low:
        return "ABOVE_BUY_ZONE"
    if price <= target_high:
        return "TAKE_PROFIT_ZONE"
    return "ABOVE_TARGET"


def normalize_mark(value: Any) -> str:
    text = str(value or "")
    for mark in ("🔻", "⚠️", "🟡", "✅"):
        if mark in text:
            return mark
    return "🟡"


def price_mark_for_zone(
    zone: str,
    change_pct: Optional[float],
    position: Optional[float],
) -> str:
    if zone == "QUOTE_FAILED":
        return "🟡"
    if zone == "RANGE_UNAVAILABLE":
        return "🟡"
    if zone in {"TAKE_PROFIT_ZONE", "ABOVE_TARGET"}:
        return "🔻"

    # 당일 급락 위험은 매수구간 위치보다 우선한다.
    if change_pct is not None and change_pct <= -5.0:
        return "⚠️"

    if zone in {"ABOVE_BUY_ZONE", "BELOW_BUY_ZONE"}:
        return "🟡"

    # BUY_ZONE
    if change_pct is not None and change_pct >= 5.0:
        return "🟡"
    if position is not None and position > 80:
        return "🟡"
    return "✅"


def combine_marks(base_mark: str, price_mark: str) -> str:
    base = normalize_mark(base_mark)
    price = normalize_mark(price_mark)

    # 가격은 정적 위험등급을 개선할 수 없고 유지 또는 하향만 가능하다.
    if BASE_MARK_PRIORITY[base] >= PRICE_MARK_PRIORITY[price]:
        return base
    return price


def gap_pct(
    request_price: Optional[float],
    official_price: Optional[float],
) -> Optional[float]:
    if (
        request_price is None
        or official_price is None
        or official_price == 0
    ):
        return None
    return round(
        (request_price - official_price)
        / official_price
        * 100.0,
        2,
    )


def format_price(value: Optional[float]) -> str:
    if value is None:
        return "확인 불가"
    return f"{int(round(value)):,}원"


def format_range(
    low: Optional[float],
    high: Optional[float],
) -> str:
    if low is None or high is None:
        return "확인 불가"
    return f"{int(round(low)):,}~{int(round(high)):,}원"


def day_move_text(change_pct: Optional[float]) -> str:
    if change_pct is None:
        return "당일 등락률은 확인되지 않았습니다."
    if change_pct >= 5.0:
        return (
            f"당일 {change_pct:+.2f}% 급등 구간이므로 "
            "가격이 매수범위 안이어도 추격매수는 피하는 편이 안전합니다."
        )
    if change_pct >= 2.0:
        return (
            f"당일 {change_pct:+.2f}% 상승 중이므로 "
            "분할 접근과 눌림 확인이 필요합니다."
        )
    if change_pct <= -5.0:
        return (
            f"당일 {change_pct:+.2f}% 급락 구간이므로 "
            "가격 매력보다 하락 원인 확인이 우선입니다."
        )
    if change_pct <= -2.0:
        return (
            f"당일 {change_pct:+.2f}% 하락 중이므로 "
            "지지 확인 후 접근하는 편이 안전합니다."
        )
    return f"당일 등락은 {change_pct:+.2f}%로 급격한 움직임은 아닙니다."


def zone_explanation(
    zone: str,
    request_price: Optional[float],
    buy_low: Optional[float],
    buy_high: Optional[float],
    target_low: Optional[float],
    target_high: Optional[float],
) -> str:
    price_text = format_price(request_price)
    buy_text = format_range(buy_low, buy_high)
    target_text = format_range(target_low, target_high)

    if zone == "QUOTE_FAILED":
        return (
            "요청시점 현재가를 확인하지 못해 매수구간·익절구간 "
            "도달 여부를 판단할 수 없습니다."
        )
    if zone == "RANGE_UNAVAILABLE":
        return (
            f"요청시점 현재가는 {price_text}이지만 가치매수구간 또는 "
            "익절구간 자료가 부족해 가격 적합성 판정은 제한됩니다."
        )
    if zone == "BELOW_BUY_ZONE":
        return (
            f"요청시점 현재가 {price_text}은 가치매수구간 "
            f"{buy_text}보다 낮습니다. 싸 보이는 것만으로 매수하지 말고 "
            "하락 원인과 지지 여부를 먼저 확인해야 합니다."
        )
    if zone == "BUY_ZONE":
        return (
            f"요청시점 현재가 {price_text}은 가치매수구간 "
            f"{buy_text} 안입니다. 기업가치·수급 위험이 허용되는 종목만 "
            "분할 접근을 검토할 수 있습니다."
        )
    if zone == "ABOVE_BUY_ZONE":
        return (
            f"요청시점 현재가 {price_text}은 가치매수구간 "
            f"{buy_text} 위이지만 1차 익절구간 {target_text} 전입니다. "
            "신규 추격보다 눌림 대기가 적절합니다."
        )
    if zone == "TAKE_PROFIT_ZONE":
        return (
            f"요청시점 현재가 {price_text}은 1차 매도·익절구간 "
            f"{target_text} 안입니다. 신규매수보다 보유분 분할매도 여부를 "
            "검토할 위치입니다."
        )
    return (
        f"요청시점 현재가 {price_text}은 1차 익절구간 "
        f"{target_text} 위입니다. 과열·되돌림 위험 때문에 신규매수는 "
        "부적합합니다."
    )


def position_explanation(
    value: Optional[float],
    label: str,
) -> str:
    if value is None:
        return "공식 저가·고가 자료가 부족해 현재위치는 확인할 수 없습니다."
    return (
        f"공식 기간 저가~고가 대비 현재위치는 "
        f"{value:.2f}%({label})입니다."
    )


def score_text(row: Mapping[str, Any]) -> str:
    value, source = first_number(row, SCORE_FIELDS)
    if value is None:
        return ""
    if float(value).is_integer():
        shown = str(int(value))
    else:
        shown = f"{value:.1f}"
    return f"{shown}점"


def static_reason_text(row: Mapping[str, Any]) -> str:
    text, _ = first_text(row, STATIC_REASON_FIELDS)
    if not text:
        return ""

    # 정적 사유에 과거 가격판정 표현이 섞여 있으면 그대로 복사하지 않는다.
    forbidden_fragments = (
        "매수구간",
        "익절구간",
        "현재가",
        "저점권",
        "중간권",
        "상단권",
        "고점권",
        "추격",
        "눌림",
    )
    if any(fragment in text for fragment in forbidden_fragments):
        return ""
    return text.strip(" ;")


def refresh(
    static_row: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> dict[str, Any]:
    quote_status = str(
        quote.get("status")
        or quote.get("quote_status")
        or quote.get("fetch_status")
        or ""
    ).upper()

    request_price, request_price_source = first_number(
        quote,
        PRICE_FIELDS,
    )

    quote_ok = (
        request_price is not None
        and quote_status not in {"FAILED", "FAIL", "ERROR", "UNAVAILABLE"}
    )

    if not quote_ok:
        request_price = None
        normalized_quote_status = PRICE_STATUS_FAILED
    else:
        normalized_quote_status = PRICE_STATUS_OK

    official_price, official_price_source = first_number(
        static_row,
        OFFICIAL_PRICE_FIELDS,
    )
    change, change_source = first_number(
        quote,
        CHANGE_PCT_FIELDS,
    )

    period_low, period_low_source = first_number(
        static_row,
        LOW_FIELDS,
    )
    period_high, period_high_source = first_number(
        static_row,
        HIGH_FIELDS,
    )

    buy_low, buy_high, buy_source = extract_range(
        static_row,
        BUY_LOW_FIELDS,
        BUY_HIGH_FIELDS,
        BUY_TEXT_FIELDS,
    )
    target_low, target_high, target_source = extract_range(
        static_row,
        TARGET_LOW_FIELDS,
        TARGET_HIGH_FIELDS,
        TARGET_TEXT_FIELDS,
    )

    pos_pct = position_pct(
        request_price,
        period_low,
        period_high,
    )
    pos_label = position_label(pos_pct)

    zone = price_zone(
        request_price,
        buy_low,
        buy_high,
        target_low,
        target_high,
    )

    base_mark_text, base_mark_source = first_text(
        static_row,
        BASE_RECOMMENDATION_FIELDS,
    )
    base_mark = normalize_mark(base_mark_text)
    price_mark = price_mark_for_zone(
        zone,
        change,
        pos_pct,
    )
    final_mark = combine_marks(
        base_mark,
        price_mark,
    )

    price_reason = zone_explanation(
        zone,
        request_price,
        buy_low,
        buy_high,
        target_low,
        target_high,
    )
    position_reason = position_explanation(
        pos_pct,
        pos_label,
    )
    move_reason = day_move_text(change)

    dynamic_explanation = " ".join(
        [
            price_reason,
            position_reason,
            move_reason,
        ]
    )

    score = score_text(static_row)
    static_reason = static_reason_text(static_row)

    combined_parts = []
    if score:
        combined_parts.append(score)
    if static_reason:
        combined_parts.append(static_reason)
    combined_parts.append(dynamic_explanation)

    final_reason = " · ".join(
        part.strip()
        for part in combined_parts
        if part.strip()
    )

    return {
        "policy_version": POLICY_VERSION,
        "request_time_quote_status": normalized_quote_status,
        "request_time_price": request_price,
        "request_time_price_source": request_price_source,
        "official_reference_price": official_price,
        "official_reference_price_source": official_price_source,
        "request_time_gap_pct": gap_pct(
            request_price,
            official_price,
        ),
        "request_time_change_pct": change,
        "request_time_change_source": change_source,
        "request_time_period_low": period_low,
        "request_time_period_high": period_high,
        "request_time_period_source": (
            f"{period_low_source}+{period_high_source}"
            if period_low_source and period_high_source
            else ""
        ),
        "request_time_position_pct": pos_pct,
        "request_time_position_label": pos_label,
        "request_time_buy_low": buy_low,
        "request_time_buy_high": buy_high,
        "request_time_buy_range_source": buy_source,
        "request_time_target_low": target_low,
        "request_time_target_high": target_high,
        "request_time_target_range_source": target_source,
        "request_time_price_zone": zone,
        "request_time_price_zone_label": ZONE_LABELS[zone],
        "base_recommendation_mark": base_mark,
        "base_recommendation_source": base_mark_source,
        "request_time_price_mark": price_mark,
        "request_time_final_recommendation_mark": final_mark,
        "request_time_price_explanation": price_reason,
        "request_time_position_explanation": position_reason,
        "request_time_day_move_explanation": move_reason,
        "request_time_dynamic_explanation": dynamic_explanation,
        "request_time_final_reason": final_reason,
        "old_price_dependent_reason_reused": False,
        "static_score_preserved": True,
        "static_financial_data_preserved": True,
        "static_supply_data_preserved": True,
    }


def policy_payload() -> dict[str, Any]:
    return {
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "purpose": (
            "요청시점 현재가 적용 뒤 가격 의존 설명을 "
            "기존 문장에 덧붙이지 않고 처음부터 다시 생성"
        ),
        "preserve_fields": [
            "final_score",
            "legacy_market_score",
            "financial_*",
            "valuation_*",
            "supply_*",
            "operating_loss_*",
            "official period low/high",
            "value buy range",
            "take profit range",
        ],
        "refresh_fields": [
            "request_time_price",
            "request_time_gap_pct",
            "request_time_position_pct",
            "request_time_position_label",
            "request_time_price_zone",
            "request_time_price_mark",
            "request_time_final_recommendation_mark",
            "request_time_price_explanation",
            "request_time_position_explanation",
            "request_time_day_move_explanation",
            "request_time_final_reason",
        ],
        "position_thresholds_pct": {
            "저점권": "<=20",
            "저점권반등초입": ">20 and <=35",
            "중간권": ">35 and <=65",
            "중상단권": ">65 and <=80",
            "상단권부담": ">80 and <=92",
            "고점권과열": ">92",
        },
        "price_zone_order": [
            "BELOW_BUY_ZONE",
            "BUY_ZONE",
            "ABOVE_BUY_ZONE",
            "TAKE_PROFIT_ZONE",
            "ABOVE_TARGET",
        ],
        "recommendation_policy": {
            "principle": (
                "가격은 정적 기업위험 등급을 개선할 수 없고 "
                "유지 또는 하향만 가능"
            ),
            "buy_zone": "기본등급 유지 가능",
            "below_buy_zone": "🟡 또는 기존보다 보수적",
            "above_buy_zone": "🟡 눌림대기",
            "take_profit_zone": "🔻 신규매수 부적합",
            "above_target": "🔻 신규매수 부적합",
            "quote_failed": "현재가 의존 판정 확인 불가",
        },
        "quote_failure_policy": {
            "use_static_price_as_request_time_price": False,
            "delete_failed_row": False,
            "price_dependent_judgment": "확인 불가",
        },
        "text_policy": {
            "append_old_reason_note": False,
            "reuse_old_price_dependent_sentence": False,
            "rewrite_dynamic_explanation_from_scratch": True,
            "final_reason_order": [
                "static score",
                "verified static non-price reason",
                "new request-time dynamic explanation",
            ],
        },
    }


def run_self_test() -> int:
    base = {
        "official_price": 100,
        "low_3m": 80,
        "high_3m": 140,
        "value_buy_low": 95,
        "value_buy_high": 105,
        "take_profit_low": 120,
        "take_profit_high": 130,
        "base_recommendation": "✅",
        "score": 82,
        "static_non_price_reason": "영업이익과 재무안정성이 양호합니다.",
    }

    buy = refresh(
        base,
        {"status": "OK", "price": 100, "change_pct": 0.5},
    )
    assert buy["request_time_price_zone"] == "BUY_ZONE"
    assert buy["request_time_final_recommendation_mark"] == "✅"
    assert buy["request_time_position_label"] == "저점권반등초입"
    assert "가치매수구간" in buy["request_time_price_explanation"]
    assert buy["old_price_dependent_reason_reused"] is False

    above_buy = refresh(
        base,
        {"status": "OK", "price": 110, "change_pct": 1.0},
    )
    assert above_buy["request_time_price_zone"] == "ABOVE_BUY_ZONE"
    assert above_buy["request_time_final_recommendation_mark"] == "🟡"
    assert "눌림 대기" in above_buy["request_time_price_explanation"]

    target = refresh(
        base,
        {"status": "OK", "price": 125, "change_pct": 2.5},
    )
    assert target["request_time_price_zone"] == "TAKE_PROFIT_ZONE"
    assert target["request_time_final_recommendation_mark"] == "🔻"
    assert "분할매도" in target["request_time_price_explanation"]

    above_target = refresh(
        base,
        {"status": "OK", "price": 135, "change_pct": 6.0},
    )
    assert above_target["request_time_price_zone"] == "ABOVE_TARGET"
    assert above_target["request_time_final_recommendation_mark"] == "🔻"
    assert "추격매수" in above_target["request_time_day_move_explanation"]

    below_buy = refresh(
        base,
        {"status": "OK", "price": 90, "change_pct": -6.0},
    )
    assert below_buy["request_time_price_zone"] == "BELOW_BUY_ZONE"
    assert below_buy["request_time_final_recommendation_mark"] == "⚠️"
    assert "하락 원인" in below_buy["request_time_price_explanation"]

    risky_base = dict(base)
    risky_base["base_recommendation"] = "⚠️"
    risky = refresh(
        risky_base,
        {"status": "OK", "price": 100, "change_pct": 0},
    )
    assert risky["request_time_price_mark"] == "✅"
    assert risky["request_time_final_recommendation_mark"] == "⚠️"

    failed = refresh(
        base,
        {"status": "FAILED"},
    )
    assert failed["request_time_quote_status"] == "FAILED"
    assert failed["request_time_price"] is None
    assert failed["request_time_price_zone"] == "QUOTE_FAILED"
    assert "확인하지 못해" in failed["request_time_price_explanation"]

    text_range = {
        "close": "10,000",
        "low_3m": "8,000",
        "high_3m": "14,000",
        "가치매수구간": "**9,500~10,500원**",
        "1차 매도/익절가": "**12,000~13,000원**",
        "recommendation": "✅",
    }
    parsed = refresh(
        text_range,
        {"status": "OK", "quote_price": "10,200"},
    )
    assert parsed["request_time_buy_low"] == 9500
    assert parsed["request_time_buy_high"] == 10500
    assert parsed["request_time_target_low"] == 12000
    assert parsed["request_time_target_high"] == 13000
    assert parsed["request_time_price_zone"] == "BUY_ZONE"

    contaminated = dict(base)
    contaminated.pop("static_non_price_reason")
    contaminated["legacy_market_reason"] = (
        "현재가가 매수구간 위이며 중간권입니다."
    )
    rebuilt = refresh(
        contaminated,
        {"status": "OK", "price": 100},
    )
    assert "현재가가 매수구간 위" not in rebuilt[
        "request_time_final_reason"
    ]
    assert "가치매수구간" in rebuilt[
        "request_time_final_reason"
    ]

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "buy_zone,above_buy_zone,take_profit_zone,"
        "above_target,below_buy_zone,static_risk_not_upgraded,"
        "quote_failure,text_range_parsing,"
        "old_price_reason_not_reused"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--static-row-json")
    parser.add_argument("--quote-json")
    parser.add_argument("--output-json")
    parser.add_argument("--write-policy-json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    if args.write_policy_json:
        path = Path(args.write_policy_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                policy_payload(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if args.static_row_json and args.quote_json:
        static_row = json.loads(
            Path(args.static_row_json).read_text(
                encoding="utf-8"
            )
        )
        quote = json.loads(
            Path(args.quote_json).read_text(
                encoding="utf-8"
            )
        )
        result = refresh(static_row, quote)
        rendered = json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )

        if args.output_json:
            output = Path(args.output_json)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                rendered + "\n",
                encoding="utf-8",
            )
        print(rendered)

    if not (
        args.write_policy_json
        or (args.static_row_json and args.quote_json)
    ):
        raise SystemExit(
            "Use --self-test, --write-policy-json, or "
            "--static-row-json with --quote-json."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
