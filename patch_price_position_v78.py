#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install V7.8 into API build, rules, and daily health."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
DAILY_HEALTH = ROOT / "validate_daily_integrated_health_v731.py"

VERSION = "2026-07-14-v7.8-price-range-position"
BUILD_BEGIN = "# PRICE_POSITION_V78_BEGIN"
BUILD_END = "# PRICE_POSITION_V78_END"
RULE_MARKER = "<!-- PRICE_POSITION_V78 -->"
HEALTH_BEGIN = "# PRICE_POSITION_HEALTH_V78_BEGIN"
HEALTH_END = "# PRICE_POSITION_HEALTH_V78_END"


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)
    text = BUILD.read_text(encoding="utf-8")

    if BUILD_BEGIN not in text:
        anchor = '    print(f"BUILD_ID={build_id}")'
        if text.count(anchor) != 1:
            raise PatchError(
                f"build insertion anchor count: {text.count(anchor)}"
            )
        block = "\n".join([
            f"    {BUILD_BEGIN}",
            "    from apply_price_position_v78 import (",
            "        apply_price_position_v78,",
            "    )",
            "    price_position_result = apply_price_position_v78(",
            "        ROOT,",
            "        api_dir=API,",
            "    )",
            "    print(",
            '        "PRICE_POSITION_V78=PASS:"',
            '        + "rows="',
            '        + str(price_position_result.get("eligible_rows"))',
            '        + ":below="',
            '        + str(price_position_result.get("below_low_rows"))',
            '        + ":above="',
            '        + str(price_position_result.get("above_high_rows"))',
            "    )",
            f"    {BUILD_END}",
            "",
            anchor,
        ])
        text = text.replace(anchor, block, 1)

    for token in (
        BUILD_BEGIN,
        BUILD_END,
        "apply_price_position_v78",
        "price_position_result = apply_price_position_v78(",
    ):
        if token not in text:
            raise PatchError(f"build required token missing: {token}")
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

## 21. 3개월 가격범위 이탈·현재위치 표시 V7.8

<!-- PRICE_POSITION_V78 -->

### 21-1. 요청시점 가격 우선순위

`getRequestTimePrices` 조회에 성공한 종목은 요청시점 가격을 사용하여
`현재위치`, `current_position_pct`, `price_zone`을 반드시 다시 계산한다.
요청시점 가격 조회가 최종 실패한 종목만 정적 `static_price`를 사용한다.

정적 API의 위치 필드는 정적 기준가격 참고값이다. 요청시점 가격이 성공한 뒤
정적 위치값을 그대로 복사하지 않는다.

### 21-2. 범위위치 계산식

`(유효 현재가 - 3개월 저가) / (3개월 고가 - 3개월 저가) * 100`

계산값을 0~100%로 강제 제한하지 않는다.

- 3개월 저가 아래: 음수 유지
- 3개월 저가~고가 안: 0~100%
- 3개월 고가 위: 100% 초과 유지

### 21-3. 가격범위 이탈 표시

저가 아래:
`3개월 저가 대비 X.X% 하회 · 범위위치 -Y.Y%`

고가 위:
`3개월 고가 대비 X.X% 돌파 · 범위위치 1YY.Y%`

금지 표현:
- `3개월 저가 하회 0%`
- `3개월 고가 돌파 100%`

범위 안 구간:
- 0~20% 미만: 저점권
- 20~40% 미만: 저점권~중간권
- 40~60% 미만: 중간권
- 60~80% 미만: 중간권~고점권
- 80~100%: 고점권

### 21-4. 가치매수·익절 위치

- 가치매수구간 하단 미만: `가치매수구간 아래`
- 가치매수구간 안: `가치매수구간 안`
- 가치매수구간 위·익절구간 전: `가치매수구간 위 · 1차 익절구간 전`
- 1차 익절구간 안: `1차 익절구간 진입`
- 1차 익절구간 상단 초과: `1차 익절구간 상단 돌파`

### 21-5. 자동 검증

API 생성 때 `api/price_position_validation.json`을 저장한다.
저가 아래인데 위치가 0 이상이거나, 고가 위인데 위치가 100 이하이면
빌드를 실패 처리한다. 일일 통합 건강검사도 같은 모순을 재검사한다.
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
            f"daily health insertion anchor count: {text.count(anchor)}"
        )

    block = "\n".join([
        f"    {HEALTH_BEGIN}",
        "    try:",
        "        from apply_price_position_v78 import (",
        "            VERSION as PRICE_POSITION_VERSION,",
        "            audit_api_directory,",
        "        )",
        "        price_position = audit_api_directory(",
        '            root / "api",',
        "            write_report=False,",
        "        )",
        '        if price_position.get("status") == "PASS":',
        "            report.pass_check(",
        '                "price_position_v78",',
        '                "3개월 범위 이탈 위치표시가 정상입니다.",',
        "                {",
        '                    "version": PRICE_POSITION_VERSION,',
        '                    "files_checked": price_position.get("files_checked"),',
        '                    "eligible_rows": price_position.get("eligible_rows"),',
        '                    "below_low_rows": price_position.get("below_low_rows"),',
        '                    "above_high_rows": price_position.get("above_high_rows"),',
        "                },",
        "            )",
        "        else:",
        "            report.fail(",
        '                "price_position_v78",',
        '                "3개월 범위 이탈 위치표시에 모순이 있습니다.",',
        '                {"errors": price_position.get("errors", [])[:20]},',
        "            )",
        "    except Exception as exc:",
        "        report.fail(",
        '            "price_position_v78_exception",',
        '            "V7.8 가격위치 검사 중 예외가 발생했습니다.",',
        '            {"error": str(exc)},',
        "        )",
        f"    {HEALTH_END}",
        "",
        anchor,
    ])
    text = text.replace(anchor, block, 1)
    DAILY_HEALTH.write_text(text, encoding="utf-8")
    print("DAILY_HEALTH_PATCH=OK")


def main() -> int:
    patch_build()
    patch_rules()
    patch_daily_health()
    print("PATCH_PRICE_POSITION_V78=OK")
    print(f"RULES_VERSION={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
