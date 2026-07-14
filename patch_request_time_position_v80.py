#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''Patch request-time position refresh logic to V8.0.'''

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "request_time_explanation_refresher.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

VERSION = "2026-07-14-v8.0-request-time-position-alignment"
SCRIPT_VERSION = (
    "request_time_explanation_refresher.py "
    "v2.0.0-price-position-alignment"
)
RULE_MARKER = "<!-- REQUEST_TIME_POSITION_V80 -->"


class PatchError(RuntimeError):
    pass


def replace_once(
    text: str,
    pattern: str,
    replacement: str,
    *,
    label: str,
    flags: int = 0,
) -> str:
    changed, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags,
    )
    if count != 1:
        raise PatchError(f"{label} replacement count: {count}")
    return changed


def patch_target() -> None:
    if not TARGET.exists():
        raise FileNotFoundError(TARGET)

    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        r'SCRIPT_VERSION\s*=\s*\(\s*"request_time_explanation_refresher\.py "\s*"[^"]+"\s*\)',
        f'SCRIPT_VERSION = "{SCRIPT_VERSION}"',
        label="SCRIPT_VERSION",
        flags=re.S,
    )
    text = replace_once(
        text,
        r'POLICY_VERSION\s*=\s*"[^"]+"',
        f'POLICY_VERSION = "{VERSION}"',
        label="POLICY_VERSION",
    )

    zone_labels = '''ZONE_LABELS = {
    "BELOW_BUY_ZONE": "가치매수구간 아래",
    "BUY_ZONE": "가치매수구간 안",
    "ABOVE_BUY_ZONE": "가치매수구간 위 · 1차 익절구간 전",
    "TAKE_PROFIT_ZONE": "1차 익절구간 진입",
    "ABOVE_TARGET": "1차 익절구간 상단 돌파",
    "RANGE_UNAVAILABLE": "가격구간 확인 불가",
    "QUOTE_FAILED": "요청시점 현재가 확인 불가",
}'''
    text = replace_once(
        text,
        r"ZONE_LABELS\s*=\s*\{.*?\n\}",
        zone_labels,
        label="ZONE_LABELS",
        flags=re.S,
    )

    position_block = r'''def position_pct(
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


def range_break_status(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> str:
    if (
        price is None
        or low is None
        or high is None
        or high <= low
    ):
        return "RANGE_UNAVAILABLE"
    if price < low:
        return "BELOW_PERIOD_LOW"
    if price > high:
        return "ABOVE_PERIOD_HIGH"
    return "IN_PERIOD_RANGE"


def range_break_pct(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    status = range_break_status(price, low, high)
    if status == "BELOW_PERIOD_LOW" and low:
        return round((low - price) / low * 100.0, 2)
    if status == "ABOVE_PERIOD_HIGH" and high:
        return round((price - high) / high * 100.0, 2)
    if status == "IN_PERIOD_RANGE":
        return 0.0
    return None


def position_label(value: Optional[float]) -> str:
    if value is None:
        return "확인 불가"
    if value < 0:
        return "3개월 저가 하회"
    if value < 20:
        return "저점권"
    if value < 40:
        return "저점권~중간권"
    if value < 60:
        return "중간권"
    if value < 80:
        return "중간권~고점권"
    if value <= 100:
        return "고점권"
    return "3개월 고가 돌파"


def position_display(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
    value: Optional[float],
) -> str:
    if (
        price is None
        or low is None
        or high is None
        or value is None
        or high <= low
    ):
        return "확인 불가"

    if price < low:
        below = (low - price) / low * 100.0
        return (
            f"3개월 저가 대비 {below:.1f}% 하회"
            f" · 범위위치 {value:.1f}%"
        )

    if price > high:
        above = (price - high) / high * 100.0
        return (
            f"3개월 고가 대비 {above:.1f}% 돌파"
            f" · 범위위치 {value:.1f}%"
        )

    return f"{position_label(value)} {value:.1f}%"
'''

    text = replace_once(
        text,
        r"def position_pct\(.*?(?=\ndef price_zone\()",
        position_block + "\n",
        label="position functions",
        flags=re.S,
    )

    position_explanation = r'''def position_explanation(
    display: str,
) -> str:
    if display == "확인 불가":
        return (
            "공식 저가·고가 자료가 부족해 "
            "현재위치는 확인할 수 없습니다."
        )
    return (
        "공식 3개월 저가~고가 대비 현재위치는 "
        f"{display}입니다."
    )
'''
    text = replace_once(
        text,
        r"def position_explanation\(.*?(?=\ndef score_text\()",
        position_explanation + "\n",
        label="position_explanation",
        flags=re.S,
    )

    refresh_anchor = '''    pos_pct = position_pct(
        request_price,
        period_low,
        period_high,
    )
    pos_label = position_label(pos_pct)
    zone = price_zone(
'''
    refresh_replacement = '''    pos_pct = position_pct(
        request_price,
        period_low,
        period_high,
    )
    pos_label = position_label(pos_pct)
    pos_display = position_display(
        request_price,
        period_low,
        period_high,
        pos_pct,
    )
    break_status = range_break_status(
        request_price,
        period_low,
        period_high,
    )
    break_pct = range_break_pct(
        request_price,
        period_low,
        period_high,
    )
    zone = price_zone(
'''
    if text.count(refresh_anchor) != 1:
        raise PatchError(
            f"refresh position anchor count: {text.count(refresh_anchor)}"
        )
    text = text.replace(refresh_anchor, refresh_replacement, 1)

    call_anchor = '''    position_reason = position_explanation(
        pos_pct,
        pos_label,
    )
'''
    call_replacement = '''    position_reason = position_explanation(
        pos_display,
    )
'''
    if text.count(call_anchor) != 1:
        raise PatchError(
            f"position explanation call count: {text.count(call_anchor)}"
        )
    text = text.replace(call_anchor, call_replacement, 1)

    return_anchor = '''        "request_time_position_pct": pos_pct,
        "request_time_position_label": pos_label,
'''
    return_replacement = '''        "request_time_position_pct": pos_pct,
        "request_time_position_label": pos_label,
        "request_time_position_display": pos_display,
        "request_time_range_break_status": break_status,
        "request_time_range_break_pct": break_pct,
'''
    if text.count(return_anchor) != 1:
        raise PatchError(
            f"return fields anchor count: {text.count(return_anchor)}"
        )
    text = text.replace(return_anchor, return_replacement, 1)

    refresh_fields_anchor = '''            "request_time_position_pct",
            "request_time_position_label",
            "request_time_price_zone",
'''
    refresh_fields_replacement = '''            "request_time_position_pct",
            "request_time_position_label",
            "request_time_position_display",
            "request_time_range_break_status",
            "request_time_range_break_pct",
            "request_time_price_zone",
'''
    if text.count(refresh_fields_anchor) != 1:
        raise PatchError(
            "policy refresh fields anchor count: "
            f"{text.count(refresh_fields_anchor)}"
        )
    text = text.replace(
        refresh_fields_anchor,
        refresh_fields_replacement,
        1,
    )

    thresholds_replacement = '''"position_thresholds_pct": {
            "3개월 저가 하회": "<0",
            "저점권": ">=0 and <20",
            "저점권~중간권": ">=20 and <40",
            "중간권": ">=40 and <60",
            "중간권~고점권": ">=60 and <80",
            "고점권": ">=80 and <=100",
            "3개월 고가 돌파": ">100",
        },'''
    text = replace_once(
        text,
        r'"position_thresholds_pct":\s*\{.*?\n\s*\},',
        thresholds_replacement,
        label="position thresholds",
        flags=re.S,
    )

    self_test_anchor = '    print("SELF_TEST_STATUS=OK")\n'
    self_test_insert = '''    below_period = refresh(
        base,
        {"status": "OK", "price": 70, "change_pct": -1.0},
    )
    assert below_period["request_time_position_pct"] == -16.67
    assert below_period[
        "request_time_range_break_status"
    ] == "BELOW_PERIOD_LOW"
    assert below_period["request_time_range_break_pct"] == 12.5
    assert below_period["request_time_position_display"] == (
        "3개월 저가 대비 12.5% 하회 · 범위위치 -16.7%"
    )

    above_period = refresh(
        base,
        {"status": "OK", "price": 150, "change_pct": 1.0},
    )
    assert above_period["request_time_position_pct"] == 116.67
    assert above_period[
        "request_time_range_break_status"
    ] == "ABOVE_PERIOD_HIGH"
    assert above_period["request_time_range_break_pct"] == 7.14
    assert above_period["request_time_position_display"] == (
        "3개월 고가 대비 7.1% 돌파 · 범위위치 116.7%"
    )

    print("V80_OUT_OF_RANGE_POSITION=PASS")
    print("SELF_TEST_STATUS=OK")
'''
    if text.count(self_test_anchor) != 1:
        raise PatchError(
            f"self-test anchor count: {text.count(self_test_anchor)}"
        )
    text = text.replace(self_test_anchor, self_test_insert, 1)

    for token in (
        VERSION,
        "request_time_position_display",
        "request_time_range_break_status",
        "request_time_range_break_pct",
        "V80_OUT_OF_RANGE_POSITION=PASS",
    ):
        if token not in text:
            raise PatchError(f"required token missing: {token}")

    TARGET.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")
    text, count = re.subn(
        r"(- 규칙 버전:\s*`)[^`]+(`)",
        rf"\g<1>{VERSION}\g<2>",
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"rules version replacement count: {count}")

    if RULE_MARKER not in text:
        rules_appendix = r'''

---

## 23. 요청시점 현재위치 정합성 V8.0

<!-- REQUEST_TIME_POSITION_V80 -->

요청시점 현재가 조회 성공 후에는 정적 `현재위치`를 복사하지 않고
다음 동적 필드를 다시 계산한다.

- `request_time_position_pct`
- `request_time_position_label`
- `request_time_position_display`
- `request_time_range_break_status`
- `request_time_range_break_pct`
- `request_time_price_zone`
- `request_time_price_zone_label`

범위위치 계산값은 0~100으로 제한하지 않는다.

- 3개월 저가 아래:
  `3개월 저가 대비 X.X% 하회 · 범위위치 -Y.Y%`
- 3개월 범위 안:
  `저점권/중간권/고점권 + 범위위치`
- 3개월 고가 위:
  `3개월 고가 대비 X.X% 돌파 · 범위위치 1YY.Y%`

가치매수·익절 위치 문구는 다음으로 통일한다.

- `가치매수구간 아래`
- `가치매수구간 안`
- `가치매수구간 위 · 1차 익절구간 전`
- `1차 익절구간 진입`
- `1차 익절구간 상단 돌파`

표의 `현재위치`에는 `request_time_position_display`를 우선 사용한다.
'''
        text = text.rstrip() + rules_appendix + "\n"

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_target()
    patch_rules()
    print("PATCH_REQUEST_TIME_POSITION_V80=OK")
    print(f"RULES_VERSION={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
