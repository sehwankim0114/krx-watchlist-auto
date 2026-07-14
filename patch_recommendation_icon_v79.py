#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''Install V7.9 recommendation-icon integrity into build and rules.'''

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
DAILY_HEALTH = ROOT / "validate_daily_integrated_health_v731.py"

VERSION = "2026-07-14-v7.9-recommendation-icon-integrity"
BUILD_BEGIN = "# RECOMMENDATION_ICON_V79_BEGIN"
BUILD_END = "# RECOMMENDATION_ICON_V79_END"
RULE_MARKER = "<!-- RECOMMENDATION_ICON_V79 -->"
HEALTH_BEGIN = "# RECOMMENDATION_ICON_HEALTH_V79_BEGIN"
HEALTH_END = "# RECOMMENDATION_ICON_HEALTH_V79_END"


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")
    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"[^"]+"',
        'SCRIPT_VERSION = "build_api_json.py v5.0_recommendation_icon_v79"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"SCRIPT_VERSION replacement count: {count}")

    if BUILD_BEGIN not in text:
        anchor = "    # DISPLAY_NORMALIZATION_V74_END"
        if text.count(anchor) != 1:
            raise PatchError(
                f"build anchor count: {text.count(anchor)}"
            )

        block = "\n".join(
            [
                anchor,
                "",
                f"    {BUILD_BEGIN}",
                "    from apply_recommendation_icon_v79 import (",
                "        apply_recommendation_icon_v79,",
                "    )",
                "    recommendation_icon_result = (",
                "        apply_recommendation_icon_v79(",
                "            ROOT,",
                "            api_dir=API,",
                "        )",
                "    )",
                "    print(",
                '        "RECOMMENDATION_ICON_V79=PASS:"',
                '        + "rows="',
                '        + str(recommendation_icon_result.get("rows_checked"))',
                '        + ":defaulted="',
                '        + str(recommendation_icon_result.get("defaulted_rows"))',
                '        + ":errors="',
                '        + str(recommendation_icon_result.get("error_count"))',
                "    )",
                f"    {BUILD_END}",
            ]
        )
        text = text.replace(anchor, block, 1)

    for token in (
        BUILD_BEGIN,
        BUILD_END,
        "apply_recommendation_icon_v79",
        "recommendation_icon_result",
    ):
        if token not in text:
            raise PatchError(f"build token missing: {token}")

    BUILD.write_text(text, encoding="utf-8")


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
        text = text.rstrip() + r'''

---

## 22. 추천 아이콘 완전성 V7.9

<!-- RECOMMENDATION_ICON_V79 -->

### 22-1. 추천/종목 표시 형식

모든 본표 후보 행은 추천/종목 앞에 다음 아이콘 중 정확히 하나를
반드시 표시한다.

- `✅`: 핵심 추천
- `🟡`: 관찰·눌림 대기 후보
- `⚠️`: 주의가 필요한 후보
- `🔻`: 약세·보수적 접근 후보
- `⚪`: 요청시점 가격 최종 조회 실패 등으로 판정 보류

기존 유효 아이콘이 있으면 그대로 보존한다. 유효 아이콘이 없는 후보는
빈칸으로 두지 않고 기본 관찰 아이콘 `🟡`를 부여한다.

### 22-2. 영업손실·수급부담 표시 순서

표시 순서는 다음으로 고정한다.

`영업손실 하이픈 → 추천 아이콘 → 수급부담 언더바 → 종목명`

예:

- 일반 관찰: `🟡 종목명`
- 수급부담 관찰: `🟡_ 종목명`
- 영업손실 관찰: `-🟡 종목명`
- 영업손실·수급부담: `-🟡_ 종목명`

`_ 종목명`, `-_ 종목명`처럼 추천 아이콘이 빠진 표시는 금지한다.

### 22-3. 순위번호 금지

`rank`는 정렬에만 사용한다. 추천/종목 표시 앞에 `1.`, `2.` 같은
자동 번호를 붙이지 않는다.

### 22-4. 자동 검증

API 생성 때 코피표·코닥표·미국 본표의 모든 행을 검사하여
`api/recommendation_icon_validation.json`에 결과를 저장한다.

다음은 빌드 실패 사유다.

- 추천 아이콘 누락
- 허용되지 않은 추천 아이콘
- 한 행에 추천 아이콘이 둘 이상 존재
- 영업손실 `-` 또는 수급부담 `_` 위치 오류
- 종목명 앞 자동 순위번호
''' + "\n"

    RULES.write_text(text, encoding="utf-8")


def patch_daily_health() -> None:
    if not DAILY_HEALTH.exists():
        print("DAILY_HEALTH_PATCH=SKIPPED_NOT_FOUND")
        return

    text = DAILY_HEALTH.read_text(encoding="utf-8")
    if HEALTH_BEGIN in text:
        print("DAILY_HEALTH_PATCH=ALREADY_INSTALLED")
        return

    anchor = "    if not args.skip_remote and local:"
    if text.count(anchor) != 1:
        raise PatchError(
            f"daily health anchor count: {text.count(anchor)}"
        )

    block = "\n".join(
        [
            f"    {HEALTH_BEGIN}",
            "    try:",
            "        from apply_recommendation_icon_v79 import (",
            "            VERSION as RECOMMENDATION_ICON_VERSION,",
            "            audit_recommendation_icons,",
            "        )",
            "        recommendation_icons = audit_recommendation_icons(",
            '            root / "api",',
            "            write_report=False,",
            "        )",
            '        if recommendation_icons.get("status") == "PASS":',
            "            report.pass_check(",
            '                "recommendation_icon_v79",',
            '                "추천 아이콘과 손실·수급 표시 순서가 정상입니다.",',
            "                {",
            '                    "version": RECOMMENDATION_ICON_VERSION,',
            '                    "rows_checked": recommendation_icons.get("rows_checked"),',
            '                    "icon_counts": recommendation_icons.get("icon_counts"),',
            "                },",
            "            )",
            "        else:",
            "            report.fail(",
            '                "recommendation_icon_v79",',
            '                "추천 아이콘 누락 또는 표시 순서 오류가 있습니다.",',
            "                {",
            '                    "errors": recommendation_icons.get("errors", [])[:20],',
            "                },",
            "            )",
            "    except Exception as exc:",
            "        report.fail(",
            '            "recommendation_icon_v79_exception",',
            '            "V7.9 추천 아이콘 검사 중 예외가 발생했습니다.",',
            '            {"error": str(exc)},',
            "        )",
            f"    {HEALTH_END}",
            "",
            anchor,
        ]
    )

    text = text.replace(anchor, block, 1)
    DAILY_HEALTH.write_text(text, encoding="utf-8")
    print("DAILY_HEALTH_PATCH=OK")


def main() -> int:
    patch_build()
    patch_rules()
    patch_daily_health()
    print("PATCH_RECOMMENDATION_ICON_V79=OK")
    print(f"RULES_VERSION={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
