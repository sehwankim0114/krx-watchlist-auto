#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install V7.7 runtime freshness gate into the full API build and rules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
VERSION = "2026-07-14-v7.7-runtime-freshness-gate"
BEGIN = "# RUNTIME_FRESHNESS_V77_BEGIN"
END = "# RUNTIME_FRESHNESS_V77_END"
RULE_MARKER = "<!-- RUNTIME_FRESHNESS_V77 -->"


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)
    text = BUILD.read_text(encoding="utf-8")

    if BEGIN not in text:
        anchor = "    print(f\"BUILD_ID={build_id}\")"
        if text.count(anchor) != 1:
            raise PatchError(f"build 삽입 기준점 오류: {text.count(anchor)}")
        block = "\n".join(
            [
                f"    {BEGIN}",
                "    from refresh_runtime_freshness_v77 import (",
                "        refresh_runtime_freshness,",
                "    )",
                "    runtime_gate = refresh_runtime_freshness(",
                "        ROOT,",
                "        now=now,",
                "        persist=True,",
                "    )",
                "    print(",
                "        \"RUNTIME_FRESHNESS_GATE=\"",
                "        + str(runtime_gate.get(\"status\"))",
                "        + \":expected=\"",
                "        + str(runtime_gate.get(\"expected_official_trading_date\"))",
                "        + \":lag=\"",
                "        + str(runtime_gate.get(\"data_lag_trading_days\"))",
                "    )",
                f"    {END}",
                "",
                anchor,
            ]
        )
        text = text.replace(anchor, block, 1)

    required = (
        BEGIN,
        END,
        "refresh_runtime_freshness_v77",
        "runtime_gate = refresh_runtime_freshness(",
    )
    for token in required:
        if token not in text:
            raise PatchError(f"build 필수 토큰 누락: {token}")
    BUILD.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)
    text = RULES.read_text(encoding="utf-8")
    # V822_GLOBAL_RULES_VERSION_PROTECTION
    version_match = re.search(
        r"- 규칙 버전:\s*`([^`]+)`",
        text,
    )
    current_version = version_match.group(1) if version_match else ""

    def version_tuple(value: str):
        match = re.search(r"-v(\d+)\.(\d+)", value)
        return tuple(map(int, match.groups())) if match else (0, 0)

    if version_tuple(current_version) > (7, 7):
        print(
            "PRESERVE_NEWER_GLOBAL_RULES_VERSION="
            + current_version
        )
    else:
        text, count = re.subn(
            r"(- 규칙 버전:\s*`)[^`]+(`)",
            rf"\g<1>{VERSION}\g<2>",
            text,
            count=1,
        )
        if count != 1:
            raise PatchError(f"규칙 버전 교체 수 오류: {count}")
    if RULE_MARKER not in text:
        text = text.rstrip() + r'''

---

## 20. 현재시각 기준 공식자료 최신성 게이트 V7.7

<!-- RUNTIME_FRESHNESS_V77 -->

### 20-1. 최신 공식자료 표시 조건

다음 세 조건이 모두 참일 때만 `최신 공식자료 기준`이라고 표시한다.

- `api_sync_ok=true`
- `runtime_freshness_gate.official_fresh_now=true`
- `runtime_freshness_gate.safe_to_analyze_as_latest=true`

API 생성 당시 저장된 `official_fresh_now`만으로 현재 최신성을 단정하지 않는다.
현재 KST 시각의 기대 공식 거래일과 KOSPI·KOSDAQ 실제 기준일을 다시 비교한다.

### 20-2. 오래된 공식자료 처리

최신성 게이트가 거짓이면 표를 삭제하지 않고 `직전 확정 공식자료`로만 제공한다.
상단에는 기대 거래일, 실제 기준일, 거래일 지연 수를 표시하고 `최신 공식자료`라는
문구를 사용하지 않는다.

요청시점 현재가가 분석자료보다 최신이면 다음을 명확히 알린다.

- 현재가만 더 최신인 혼합 상태
- 점수·가치매수구간·익절가는 직전 확정 분석 기준
- 현재가가 과거 3개월 범위를 이탈하면 기준자료 재수집 필요

### 20-3. 자동 재판정 시각

최신성 상태는 전체 데이터 재수집과 별도로 다음 시각에 가볍게 재판정한다.

- 매일 00:45 KST
- 평일 08:35 KST
- 평일 17:30 KST

이 재판정은 시장자료를 새로 만들지 않으며, 오래된 자료를 최신으로 바꾸지 않는다.
오직 현재 날짜 기준의 안전한 최신성 표시만 갱신한다.
''' + "\n"

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_build()
    patch_rules()
    print("PATCH_RUNTIME_FRESHNESS_V77=OK")
    print(f"RULES_VERSION={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
