#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch the repository for V7.2 Korean sector/theme enrichment."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
REQUIREMENTS = ROOT / "requirements.txt"

RULES_VERSION = "2026-07-09-v7.2-kr-sector-theme"
BEGIN = "# KR_SECTOR_THEME_V72_BEGIN"
END = "# KR_SECTOR_THEME_V72_END"
RULES_MARKER = "<!-- KR_SECTOR_THEME_V72 -->"


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
        'SCRIPT_VERSION = "build_api_json.py v4.8_kr_sector_theme_v72"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"SCRIPT_VERSION 교체 수 오류: {count}")

    if '"kr_sector_theme_source": "KRX_KIND_LISTED_COMPANY"' not in text:
        anchor = '    "bold_price_ranges": True,'
        injection = "\n".join(
            [
                anchor,
                '    "kr_sector_theme_source": "KRX_KIND_LISTED_COMPANY",',
                '    "kr_sector_theme_missing_display": "자료 미제공",',
                '    "kr_average_volume_per_minute_value_column_label": "평균거래량·분당거래금",',
                '    "kr_regular_session_minutes": 390,',
            ]
        )
        text = replace_once(
            text,
            anchor,
            injection,
            "PRESENTATION_POLICY",
        )

    if BEGIN not in text:
        anchor = "    # FINAL_DISPLAY_CONTRACT_V71_END"
        block = "\n".join(
            [
                anchor,
                "",
                f"    {BEGIN}",
                "    from apply_kr_sector_theme_v72 import (",
                "        apply_kr_sector_theme,",
                "    )",
                "    kr_sector_entries = apply_kr_sector_theme(API, LATEST)",
                "    print(",
                '        "KR_SECTOR_THEME_ENTRIES="',
                "        + \",\".join(",
                "            f\"{item['table_id']}:{item['sector_theme_matched']}\"",
                "            for item in kr_sector_entries",
                "        )",
                "    )",
                f"    {END}",
            ]
        )
        text = replace_once(
            text,
            anchor,
            block,
            "V7.1 종료 블록",
        )

    required = (
        'build_api_json.py v4.8_kr_sector_theme_v72',
        BEGIN,
        END,
        "apply_kr_sector_theme_v72",
        '"kr_sector_theme_source": "KRX_KIND_LISTED_COMPANY"',
        '"kr_average_volume_per_minute_value_column_label": "평균거래량·분당거래금"',
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

## 16. 한국표 업종·테마 및 거래표시 V7.2

<!-- KR_SECTOR_THEME_V72 -->

### 16-1. 공식 업종·주요제품 자료

- 코피표와 코닥표의 `섹터/테마`는 한국거래소 KIND
  상장법인목록의 `업종`과 `주요제품`을 종목코드로 연결한다.
- 자료 출처는 `KRX_KIND_LISTED_COMPANY`로 기록한다.
- 종목명만 보고 업종이나 테마를 임의로 추정하지 않는다.
- 공식 자료에서 찾지 못한 경우에만 `자료 미제공`이라고 표시한다.
- `시장·티커`와 `섹터/테마`는 본표 맨 오른쪽에 둔다.

### 16-2. 평균거래량·분당거래금

- 한국표의 해당 열 이름은 `평균거래량·분당거래금`으로 통일한다.
- 평균거래량은 API의 `avg_volume`을 사용한다.
- 분당거래금은 API의 일평균 거래대금을 한국 정규장 390분으로
  나눈 참고값을 사용한다.
- 분당거래금은 체결 강도나 특정 시각의 실시간 거래금이 아니라
  과거 일평균 거래대금의 분당 환산값임을 각주에서 밝힌다.

### 16-3. 가격범위와 열 배치

- 현재가 열 이름은 `요청시점 현재가`를 유지한다.
- 가치매수구간과 1차 매도·익절가는 Markdown 전용 필드를 우선하고
  가격범위 문자열 전체를 굵게 표시한다.
- `시장·티커`, `섹터/테마`는 마지막 두 열로 유지한다.
"""
        text = text.rstrip() + section + "\n"

    if RULES_MARKER not in text:
        raise PatchError("규칙 V7.2 마커 삽입 실패")

    RULES.write_text(text, encoding="utf-8")


def patch_requirements() -> None:
    if not REQUIREMENTS.exists():
        raise FileNotFoundError(REQUIREMENTS)
    lines = [
        line.rstrip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    ]
    if not any(line.lower().startswith("lxml") for line in lines):
        lines.append("lxml>=5.0")
    REQUIREMENTS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    patch_build()
    patch_rules()
    patch_requirements()
    print("PATCH_KR_SECTOR_THEME_V72=OK")
    print(f"RULES_VERSION={RULES_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
