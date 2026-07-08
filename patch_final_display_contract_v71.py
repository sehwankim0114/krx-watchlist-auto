#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch the repository to apply the v7.1 display contract on every build."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

RULES_VERSION = "2026-07-09-v7.1-final-display-cleanup"
BEGIN = "# FINAL_DISPLAY_CONTRACT_V71_BEGIN"
END = "# FINAL_DISPLAY_CONTRACT_V71_END"
RULES_MARKER = "<!-- FINAL_DISPLAY_CONTRACT_V71 -->"


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")

    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = "build_api_json.py v4.7_final_display_contract_v71"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"SCRIPT_VERSION 교체 수 오류: {count}")

    if '"current_price_column_label": "요청시점 현재가"' not in text:
        anchor = '"bold_price_ranges": True,'
        if text.count(anchor) != 1:
            raise PatchError(
                f"PRESENTATION_POLICY 삽입 기준점 오류: {text.count(anchor)}"
            )
        injection = "\n".join(
            [
                '"bold_price_ranges": True,',
                '    "current_price_column_label": "요청시점 현재가",',
                '    "price_range_markdown_required": True,',
                '    "preferred_buy_range_field": "value_buy_range_markdown",',
                '    "preferred_first_sell_range_field": "first_sell_target_range_markdown",',
                '    "price_timestamp_label_policy": "use_price_data_time_unless_actual_trade_time_is_guaranteed",',
                '    "market_specific_metadata": True,',
                '    "us_table_omit_kr_market_metadata_by_default": True,',
            ]
        )
        text = text.replace(anchor, injection, 1)

    if BEGIN not in text:
        anchor = "    # LIGHTWEIGHT_WATCHLIST_BUILD_V66_END"
        if text.count(anchor) != 1:
            raise PatchError(
                f"V6.6 경량 빌드 종료 기준점 오류: {text.count(anchor)}"
            )
        block = "\n".join(
            [
                anchor,
                "",
                f"    {BEGIN}",
                "    from apply_final_display_contract_v71 import (",
                "        apply_final_display_contract,",
                "    )",
                "    final_display_entries = apply_final_display_contract(API)",
                "    print(",
                '        "FINAL_DISPLAY_ENTRIES="',
                "        + \",\".join(",
                "            f\"{item['filename']}:{item['row_count']}\"",
                "            for item in final_display_entries",
                "        )",
                "    )",
                f"    {END}",
            ]
        )
        text = text.replace(anchor, block, 1)

    required = (
        "build_api_json.py v4.7_final_display_contract_v71",
        BEGIN,
        END,
        "apply_final_display_contract_v71",
        '"current_price_column_label": "요청시점 현재가"',
        '"price_range_markdown_required": True',
        '"us_table_omit_kr_market_metadata_by_default": True',
    )
    for token in required:
        if token not in text:
            raise PatchError(f"build_api_json.py 필수 토큰 누락: {token}")

    BUILD.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")

    text = re.sub(
        r'(- 최종 업데이트:\s*)\d{4}-\d{2}-\d{2}',
        r'\g<1>2026-07-09',
        text,
        count=1,
    )
    text = re.sub(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{RULES_VERSION}\g<2>',
        text,
        count=1,
    )

    if RULES_MARKER not in text:
        section = """

---

## 15. 최종 표시계약 V7.1

<!-- FINAL_DISPLAY_CONTRACT_V71 -->

### 15-1. 가격 열과 가격범위

- 본표의 현재가격 열 이름은 반드시 `요청시점 현재가`로 쓴다.
- 가치매수구간과 1차 매도·익절가는 가격범위 문자열 전체를 굵게 표시한다.
- API에 `value_buy_range_markdown`과
  `first_sell_target_range_markdown`이 있으면 그 필드를 우선 사용한다.
- 출력 예시는 `**375,000원~406,000원**`,
  `**$979.99~$989.24**` 형식이다.

### 15-2. 가격 시각 명칭

- 가격 API의 시각이 실제 체결시각임이 보장되지 않으면
  `가격 거래시각`이라고 단정하지 않는다.
- 이 경우 `가격 자료시각` 또는 `가격 갱신시각`이라고 표시한다.

### 15-3. 시장별 상단 기준정보

- 한국표는 KRX 기대 거래일과 KOSPI·KOSDAQ 실제 기준일을 표시할 수 있다.
- 미국표에서는 KRX 기대 거래일과 KOSPI·KOSDAQ 실제 기준일을
  기본 상단정보에서 제외한다.
- 미국표에는 미국 분석 기준 거래일, 요청가격 시장상태,
  정규장·시간외 반영 상태를 우선 표시한다.
- 사용자가 전체 자동화 상태를 명시적으로 요청한 경우에만
  미국표에도 한국시장 동기화 정보를 추가할 수 있다.

### 15-4. 섹터·테마

- `시장·티커`와 `섹터/테마`는 표 맨 오른쪽에 둔다.
- 원본 API에 섹터·테마가 없으면 임의로 추정하거나 생성하지 않는다.
- 자료가 없으면 `자료 미제공`이라고 명확히 표시한다.
"""
        text = text.rstrip() + section + "\n"

    if RULES_MARKER not in text:
        raise PatchError("규칙 V7.1 마커 삽입 실패")

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_build()
    patch_rules()
    print("PATCH_FINAL_DISPLAY_CONTRACT_V71=OK")
    print(f"RULES_VERSION={RULES_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
