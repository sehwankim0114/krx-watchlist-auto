#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch the repository for V7.4 display normalization."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

RULES_VERSION = "2026-07-09-v7.4-display-normalization"
BEGIN = "# DISPLAY_NORMALIZATION_V74_BEGIN"
END = "# DISPLAY_NORMALIZATION_V74_END"
RULES_MARKER = "<!-- DISPLAY_NORMALIZATION_V74 -->"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label} 기준점 오류: {count}")
    return text.replace(old, new, 1)


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")

    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = "build_api_json.py v4.9_display_normalization_v74"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"SCRIPT_VERSION 교체 수 오류: {count}")

    if '"show_rank_numbers_default": False' not in text:
        anchor = '    "kr_regular_session_minutes": 390,'
        injection = "\n".join(
            [
                anchor,
                '    "recommendation_column_label": "추천/종목",',
                '    "show_rank_numbers_default": False,',
                '    "rank_field_use": "sorting_only",',
                '    "supply_keyword_alias_deduplication": True,',
                '    "supply_keyword_display_separator": "·",',
            ]
        )
        text = replace_once(
            text,
            anchor,
            injection,
            "PRESENTATION_POLICY V7.2",
        )

    if BEGIN not in text:
        anchor = "    # KR_SECTOR_THEME_V72_END"
        block = "\n".join(
            [
                anchor,
                "",
                f"    {BEGIN}",
                "    from apply_display_normalization_v74 import (",
                "        apply_display_normalization,",
                "    )",
                "    display_normalization_entries = (",
                "        apply_display_normalization(API)",
                "    )",
                "    print(",
                '        "DISPLAY_NORMALIZATION_ENTRIES="',
                "        + \",\".join(",
                "            f\"{item['table_id']}:{item['row_count']}\"",
                "            for item in display_normalization_entries",
                "        )",
                "    )",
                f"    {END}",
            ]
        )
        text = replace_once(
            text,
            anchor,
            block,
            "V7.2 종료 블록",
        )

    required = (
        "build_api_json.py v4.9_display_normalization_v74",
        BEGIN,
        END,
        "apply_display_normalization_v74",
        '"show_rank_numbers_default": False',
        '"supply_keyword_alias_deduplication": True',
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

## 17. 추천·수급 표시 정규화 V7.4

<!-- DISPLAY_NORMALIZATION_V74 -->

### 17-1. 추천/종목 열

- 첫 열 이름은 `추천/종목`으로 유지한다.
- API의 `rank`는 종목 순서를 유지하는 정렬용 값으로만 사용한다.
- 사용자가 별도로 순위표를 요청하지 않으면 종목명 앞에
  `1.`, `2.` 같은 자동 번호를 붙이지 않는다.
- 영업손실 `-`는 추천표시 왼쪽에, 수급부담 `_`는 추천표시
  오른쪽에 붙인다.
- 표시는 `-✅_ 종목명`, `✅_ 종목명`, `🟡 종목명`처럼
  한 가지 형식으로 통일한다.

### 17-2. 수급부담 키워드

- 같은 의미의 수급 키워드는 한 번만 표시한다.
- `CB`와 `CB발행`은 `CB`로, `BW`와 `BW발행`은 `BW`로,
  `EB`와 `EB발행`은 `EB`로 통일한다.
- `전환청구`, `신주인수권`, `대량보유`, `주요주주변동`처럼
  서로 다른 의미는 삭제하지 않는다.
- 사용자 표에서는 수급 키워드를 `·`로 구분한다.
- API의 기계 판독용 `supply_burden_keywords`는 중복 제거 후
  쉼표 구분 문자열로 유지하고, 표 출력용으로
  `supply_burden_display`를 우선 사용한다.

### 17-3. 출력 우선순위

- `recommendation_display`를 추천/종목 셀의 우선 필드로 사용한다.
- `supply_burden_display`가 있으면 수급부담 셀에 그대로 사용한다.
- API 원본에 이미 제공된 표시 필드를 종목명이나 공시문구를 보고
  다시 추정해 덧붙이지 않는다.
"""
        text = text.rstrip() + section + "\n"

    if RULES_MARKER not in text:
        raise PatchError("규칙 V7.4 마커 삽입 실패")

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_build()
    patch_rules()
    print("PATCH_DISPLAY_NORMALIZATION_V74=OK")
    print(f"RULES_VERSION={RULES_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
