#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''V8.0 anchor-fix patch for request-time price-position alignment.'''

from __future__ import annotations

import re
from pathlib import Path
from typing import Match

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "request_time_explanation_refresher.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

VERSION = "2026-07-14-v8.0-request-time-position-alignment"
SCRIPT_VERSION = (
    "request_time_explanation_refresher.py "
    "v2.0.2-price-position-self-test-fix"
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
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags,
    )
    if count != 1:
        raise PatchError(f"{label} replacement count: {count}")
    return updated


def replace_once_func(
    text: str,
    pattern: str,
    replacement,
    *,
    label: str,
    flags: int = 0,
) -> str:
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags,
    )
    if count != 1:
        raise PatchError(f"{label} replacement count: {count}")
    return updated


def patch_price_field_priority(text: str) -> str:
    low_fields = '''LOW_FIELDS = (
    "low_3m",
    "low_3m_intraday",
    "recent_3m_low",
    "range_low_3m",
    "low_1m",
    "low_1m_intraday",
)'''
    high_fields = '''HIGH_FIELDS = (
    "high_3m",
    "high_3m_intraday",
    "recent_3m_high",
    "range_high_3m",
    "high_1m",
    "high_1m_intraday",
)'''

    text = replace_once(
        text,
        r"^LOW_FIELDS\s*=\s*\(.*?^\)",
        low_fields,
        label="LOW_FIELDS",
        flags=re.M | re.S,
    )
    text = replace_once(
        text,
        r"^HIGH_FIELDS\s*=\s*\(.*?^\)",
        high_fields,
        label="HIGH_FIELDS",
        flags=re.M | re.S,
    )
    return text


def patch_position_functions(text: str) -> str:
    if "def range_break_status(" in text:
        return text

    block = r'''def position_pct(
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

    return replace_once(
        text,
        r"^def position_pct\(.*?(?=^def price_zone\()",
        block + "\n\n",
        label="position function block",
        flags=re.M | re.S,
    )


def patch_refresh_position_block(text: str) -> str:
    if "pos_display = position_display(" in text:
        return text

    pattern = (
        r"(?P<indent>^[ \t]*)"
        r"pos_pct\s*=\s*position_pct\(\s*"
        r"request_price\s*,\s*period_low\s*,\s*period_high\s*,?\s*\)"
        r"\s*"
        r"(?P=indent)pos_label\s*=\s*position_label\(\s*pos_pct\s*\)"
        r"\s*"
        r"(?P=indent)zone\s*=\s*price_zone\("
    )

    def repl(match: Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}pos_pct = position_pct(\n"
            f"{indent}    request_price,\n"
            f"{indent}    period_low,\n"
            f"{indent}    period_high,\n"
            f"{indent})\n"
            f"{indent}pos_label = position_label(pos_pct)\n"
            f"{indent}pos_display = position_display(\n"
            f"{indent}    request_price,\n"
            f"{indent}    period_low,\n"
            f"{indent}    period_high,\n"
            f"{indent}    pos_pct,\n"
            f"{indent})\n"
            f"{indent}break_status = range_break_status(\n"
            f"{indent}    request_price,\n"
            f"{indent}    period_low,\n"
            f"{indent}    period_high,\n"
            f"{indent})\n"
            f"{indent}break_pct = range_break_pct(\n"
            f"{indent}    request_price,\n"
            f"{indent}    period_low,\n"
            f"{indent}    period_high,\n"
            f"{indent})\n"
            f"{indent}zone = price_zone("
        )

    return replace_once_func(
        text,
        pattern,
        repl,
        label="refresh position block",
        flags=re.M | re.S,
    )


def patch_position_explanation(text: str) -> str:
    function = r'''def position_explanation(
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
        r"^def position_explanation\(.*?(?=^def score_text\()",
        function + "\n\n",
        label="position_explanation function",
        flags=re.M | re.S,
    )

    if re.search(
        r"position_reason\s*=\s*position_explanation\(\s*pos_display\s*\)",
        text,
        flags=re.S,
    ):
        return text

    return replace_once(
        text,
        r"position_reason\s*=\s*position_explanation\(\s*"
        r"pos_pct\s*,\s*pos_label\s*,?\s*\)",
        "position_reason = position_explanation(\n"
        "        pos_display,\n"
        "    )",
        label="position_explanation call",
        flags=re.S,
    )


def patch_return_fields(text: str) -> str:
    if '"request_time_position_display": pos_display' in text:
        return text

    pattern = (
        r'(?P<indent>^[ \t]*)'
        r'"request_time_position_pct"\s*:\s*pos_pct\s*,\s*'
        r'(?P=indent)"request_time_position_label"\s*:\s*pos_label\s*,'
    )

    def repl(match: Match[str]) -> str:
        indent = match.group("indent")
        return (
            f'{indent}"request_time_position_pct": pos_pct,\n'
            f'{indent}"request_time_position_label": pos_label,\n'
            f'{indent}"request_time_position_display": pos_display,\n'
            f'{indent}"request_time_range_break_status": break_status,\n'
            f'{indent}"request_time_range_break_pct": break_pct,'
        )

    return replace_once_func(
        text,
        pattern,
        repl,
        label="refresh return fields",
        flags=re.M | re.S,
    )


def patch_policy_payload(text: str) -> str:
    if '"request_time_position_display",' not in text:
        pattern = (
            r'(?P<indent>^[ \t]*)'
            r'"request_time_position_pct"\s*,\s*'
            r'(?P=indent)"request_time_position_label"\s*,\s*'
            r'(?P=indent)"request_time_price_zone"\s*,'
        )

        def repl(match: Match[str]) -> str:
            indent = match.group("indent")
            return (
                f'{indent}"request_time_position_pct",\n'
                f'{indent}"request_time_position_label",\n'
                f'{indent}"request_time_position_display",\n'
                f'{indent}"request_time_range_break_status",\n'
                f'{indent}"request_time_range_break_pct",\n'
                f'{indent}"request_time_price_zone",'
            )

        text = replace_once_func(
            text,
            pattern,
            repl,
            label="policy refresh fields",
            flags=re.M | re.S,
        )

    thresholds = '''"position_thresholds_pct": {
            "3개월 저가 하회": "<0",
            "저점권": ">=0 and <20",
            "저점권~중간권": ">=20 and <40",
            "중간권": ">=40 and <60",
            "중간권~고점권": ">=60 and <80",
            "고점권": ">=80 and <=100",
            "3개월 고가 돌파": ">100",
        },'''
    return replace_once(
        text,
        r'"position_thresholds_pct"\s*:\s*\{.*?^\s*\},',
        thresholds,
        label="position thresholds",
        flags=re.M | re.S,
    )


def patch_zone_labels(text: str) -> str:
    block = '''ZONE_LABELS = {
    "BELOW_BUY_ZONE": "가치매수구간 아래",
    "BUY_ZONE": "가치매수구간 안",
    "ABOVE_BUY_ZONE": "가치매수구간 위 · 1차 익절구간 전",
    "TAKE_PROFIT_ZONE": "1차 익절구간 진입",
    "ABOVE_TARGET": "1차 익절구간 상단 돌파",
    "RANGE_UNAVAILABLE": "가격구간 확인 불가",
    "QUOTE_FAILED": "요청시점 현재가 확인 불가",
}'''
    return replace_once(
        text,
        r"^ZONE_LABELS\s*=\s*\{.*?^\}",
        block,
        label="ZONE_LABELS",
        flags=re.M | re.S,
    )


def patch_self_test(text: str) -> str:
    legacy_pattern = (
        r'assert\s+buy\["request_time_position_label"\]\s*'
        r'==\s*"저점권반등초입"'
    )
    aligned_assertion = (
        'assert buy["request_time_position_label"] '
        '== "저점권~중간권"'
    )

    if re.search(legacy_pattern, text, flags=re.S):
        text, legacy_count = re.subn(
            legacy_pattern,
            aligned_assertion,
            text,
            count=1,
            flags=re.S,
        )
        if legacy_count != 1:
            raise PatchError(
                "legacy self-test label replacement count: "
                f"{legacy_count}"
            )
    elif aligned_assertion not in text:
        raise PatchError(
            "legacy self-test position-label assertion not found"
        )

    if "V80_OUT_OF_RANGE_POSITION=PASS" in text:
        return text

    pattern = r'(?P<indent>^[ \t]*)print\("SELF_TEST_STATUS=OK"\)'

    def repl(match: Match[str]) -> str:
        indent = match.group("indent")
        return f'''{indent}below_period = refresh(
{indent}    base,
{indent}    {{"status": "OK", "price": 70, "change_pct": -1.0}},
{indent})
{indent}assert below_period["request_time_position_pct"] == -16.67
{indent}assert below_period[
{indent}    "request_time_range_break_status"
{indent}] == "BELOW_PERIOD_LOW"
{indent}assert below_period["request_time_range_break_pct"] == 12.5
{indent}assert below_period["request_time_position_display"] == (
{indent}    "3개월 저가 대비 12.5% 하회 · 범위위치 -16.7%"
{indent})

{indent}above_period = refresh(
{indent}    base,
{indent}    {{"status": "OK", "price": 150, "change_pct": 1.0}},
{indent})
{indent}assert above_period["request_time_position_pct"] == 116.67
{indent}assert above_period[
{indent}    "request_time_range_break_status"
{indent}] == "ABOVE_PERIOD_HIGH"
{indent}assert above_period["request_time_range_break_pct"] == 7.14
{indent}assert above_period["request_time_position_display"] == (
{indent}    "3개월 고가 대비 7.1% 돌파 · 범위위치 116.7%"
{indent})

{indent}print("V80_LEGACY_SELF_TEST_ALIGNMENT=PASS")
{indent}print("V80_OUT_OF_RANGE_POSITION=PASS")
{indent}print("SELF_TEST_STATUS=OK")'''

    return replace_once_func(
        text,
        pattern,
        repl,
        label="self-test marker",
        flags=re.M,
    )


def patch_target() -> None:
    if not TARGET.exists():
        raise FileNotFoundError(TARGET)

    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        r'SCRIPT_VERSION\s*=\s*\(\s*'
        r'"request_time_explanation_refresher\.py "\s*"[^"]+"\s*\)',
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

    text = patch_price_field_priority(text)
    text = patch_zone_labels(text)
    text = patch_position_functions(text)
    text = patch_refresh_position_block(text)
    text = patch_position_explanation(text)
    text = patch_return_fields(text)
    text = patch_policy_payload(text)
    text = patch_self_test(text)

    required = (
        VERSION,
        "v2.0.2-price-position-self-test-fix",
        "request_time_position_display",
        "request_time_range_break_status",
        "request_time_range_break_pct",
        "V80_LEGACY_SELF_TEST_ALIGNMENT=PASS",
        "V80_OUT_OF_RANGE_POSITION=PASS",
    )
    for token in required:
        if token not in text:
            raise PatchError(f"required token missing: {token}")

    low_block = re.search(
        r"^LOW_FIELDS\s*=\s*\(.*?^\)",
        text,
        flags=re.M | re.S,
    )
    high_block = re.search(
        r"^HIGH_FIELDS\s*=\s*\(.*?^\)",
        text,
        flags=re.M | re.S,
    )
    if not low_block or not high_block:
        raise PatchError("price range field blocks missing")
    if low_block.group(0).index('"low_3m"') > low_block.group(0).index('"low_1m"'):
        raise PatchError("3-month low priority was not applied")
    if high_block.group(0).index('"high_3m"') > high_block.group(0).index('"high_1m"'):
        raise PatchError("3-month high priority was not applied")

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
        appendix = r'''

---

## 23. 요청시점 현재위치 정합성 V8.0

<!-- REQUEST_TIME_POSITION_V80 -->

요청시점 현재가 조회 성공 후에는 정적 현재위치를 복사하지 않고
요청가격으로 현재위치·저가하회율·고가돌파율·가격구간을 다시 계산한다.

3개월 저가·고가 필드를 1개월 필드보다 우선 사용한다.

- 저가 아래: `3개월 저가 대비 X.X% 하회 · 범위위치 -Y.Y%`
- 범위 안: `저점권/중간권/고점권 + 범위위치`
- 고가 위: `3개월 고가 대비 X.X% 돌파 · 범위위치 1YY.Y%`

표의 현재위치에는 `request_time_position_display`를 우선 사용한다.
'''
        text = text.rstrip() + appendix + "\n"

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_target()
    patch_rules()
    print("PATCH_REQUEST_TIME_POSITION_V80=OK")
    print("PATCH_ANCHOR_MODE=REGEX_IDENTIFIER_BASED")
    print("LEGACY_SELF_TEST_EXPECTATION_PATCHED=PASS")
    print("THREE_MONTH_RANGE_PRIORITY=PASS")
    print(f"RULES_VERSION={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
