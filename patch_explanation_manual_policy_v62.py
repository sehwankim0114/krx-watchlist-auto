#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# patch_explanation_manual_policy_v62.py
#
# 목적
# - 모든 주식표를 개선안2 최종형으로 명시한다.
# - 기본 표 출력에서 월요일/주간 자동 설명을 제거한다.
# - 기본 출력은 상단 기준정보 표 + 본표 1개 + 최소 필수 각주만 허용한다.
# - 사용자가 "설명서"라고 입력했을 때만 8단계 전체 설명서를 출력하도록
#   GitHub 규칙과 API의 presentation_policy를 함께 갱신한다.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
BUILD = ROOT / "build_api_json.py"

RULES_VERSION = "2026-07-06-v6.2-explanation-manual-only"
PATCH_MARKER = "EXPLANATION_MANUAL_POLICY_V62"


class PatchError(RuntimeError):
    pass


def replace_once(
    text: str,
    pattern: str,
    replacement: str,
    *,
    flags: int = 0,
    label: str,
) -> str:
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags,
    )
    if count != 1:
        raise PatchError(f"{label} 교체 수 오류: {count}")
    return updated


def replace_section(
    text: str,
    start_heading: str,
    next_heading: str,
    replacement: str,
) -> str:
    start = text.find(start_heading)
    if start < 0:
        raise PatchError(f"시작 섹션 누락: {start_heading}")
    end = text.find(next_heading, start)
    if end < 0:
        raise PatchError(f"다음 섹션 누락: {next_heading}")
    return (
        text[:start]
        + replacement.rstrip()
        + "\n\n---\n\n"
        + text[end:]
    )


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")

    text = replace_once(
        text,
        r"(- 최종 업데이트:\s*)[0-9]{4}-[0-9]{2}-[0-9]{2}",
        r"\g<1>2026-07-06",
        label="최종 업데이트일",
    )
    text = replace_once(
        text,
        r"(- 규칙 버전:\s*`)[^`]+(`)",
        rf"\g<1>{RULES_VERSION}\g<2>",
        label="규칙 버전",
    )

    old_role = "- 모든 표를 최신 개선형으로 작성한다."
    new_role = (
        "- 모든 표를 **개선안2 최종형(최신 개선형)**으로 작성하며, "
        "표별 최종 헤더·열 순서·표시 규칙을 임의로 줄이거나 바꾸지 않는다."
    )
    if old_role in text:
        text = text.replace(old_role, new_role, 1)
    elif new_role not in text:
        raise PatchError("기본 역할 기준점 누락")

    old_term_note = "- 어려운 용어는 표 아래 `*` 각주로 쉽게 설명한다."
    new_term_note = (
        "- 기본 표 아래 각주는 실제 사용된 생소한 표시, 현재가 조회 실패·부분성공 같은 "
        "데이터 제한, 투자 참고 고지만 최소한으로 쓴다. "
        "전체 용어집·명령어 안내·주간 안내는 붙이지 않는다."
    )
    if old_term_note in text:
        text = text.replace(old_term_note, new_term_note, 1)
    elif new_term_note not in text:
        raise PatchError("각주 기준점 누락")

    scope_old = (
        "- 적용 범위: 관종표·분석표·코피표·코닥표·코급표·월사이클표·"
        "환율약세표·단상표 및 명시 요청 전용 표의 모든 종목 행"
    )
    scope_new = (
        "- 적용 범위: 관종표·분석표·코피표·코피표1개월·코닥표·코닥표1개월·"
        "코급표·월사이클표·환율약세표·단상표·보유종목표·미관종표 및 "
        "명시 요청 전용 표의 모든 종목 행"
    )
    if scope_old in text:
        text = text.replace(scope_old, scope_new, 1)
    elif scope_new not in text:
        raise PatchError("현재가 적용범위 기준점 누락")

    explanation_section = r'''## 12. 설명서·각주 출력 정책

### 12-1. 기본 주식표 출력

사용자가 `코피표 줘`, `코닥표 줘`, `미관종표 줘`처럼 표만 요청하면 다음만 출력한다.

1. 표 제목
2. 상단 기준정보를 2열 표로 표시
3. 개선안2 최종형 본표 1개
4. 실제로 필요한 최소 각주
   - 현재 출력에서 사용된 생소한 기호
   - 현재가 조회 실패·부분성공·시간외 미반영 등 데이터 제한
   - 투자 참고용이라는 짧은 고지

별도 요청이 없으면 다음은 자동으로 붙이지 않는다.

- 월요일 첫 표 안내
- 주간 표 사용 안내
- 전체 명령어 목록
- 모든 표시·항목의 장문 해설
- 전체 용어집
- 동일 추천종목을 반복한 별도 추천표
- 매 행의 내용을 다시 풀어 쓴 장문 해설

요일과 관계없이 기본 출력 원칙은 같다. `자동 주간 설명`은 사용하지 않는다.

### 12-2. 전체 설명서 호출 조건

사용자가 단독으로 또는 명확한 요청으로 `설명서`라고 입력했을 때만 전체 사용설명서를 제공한다.

전체 설명서는 다음 순서를 고정한다.

1. **30초 사용법**
2. **표시 읽는 법**
3. **어떤 표를 사용할지**
4. **항목 읽는 법**
5. **점수·추천·주의사유 해석**
6. **여러 표 연결 방법**
7. **꼭 기억할 원칙**
8. **주요 용어**

전체 설명서는 표를 다시 대량 출력하지 않고, 주식 초보자가 실제 표를 읽는 데 필요한 내용만 쉽고 간결하게 설명한다.

### 12-3. 부분 설명 요청

사용자가 `사용법`, `이 표 해석해줘`, `표시 설명`, `항목 설명`, `현재위치가 뭐야`처럼
특정 설명을 요청하면 요청한 부분만 설명한다. 이 경우에도 전체 8단계 설명서를 자동으로 붙이지 않는다.

### 12-4. 최소 각주와 전체 설명서의 구분

- `⚪ 현재가 확인 실패`, 요청시점 가격 `PARTIAL`, 시간외 미반영 등은 투자판단에 직접 영향을 주므로 기본 표의 최소 각주로 허용한다.
- `✅·🟡·⚠️·🔻`, 하이픈 `-`, 언더바 `_`처럼 실제 표에서 오해 가능성이 큰 표시도 해당 표에서 사용됐을 때만 짧게 설명할 수 있다.
- `밸류에이션`, `가이던스`, `오버행` 등의 전체 용어 설명은 기본적으로 `설명서` 또는 명시적 용어 질문 때 제공한다.
- 최소 각주는 1~4개를 원칙으로 하며, 본표보다 길어지지 않게 한다.
- 가격 구간인 `가치매수구간`과 `1차 매도/익절가`는 모든 표에서 **굵은 가격~가격 범위**로 표시한다.
- 상단 기준정보는 문장 나열이 아니라 `구분 | 내용`의 간결한 2열 표로 표시한다.

<!-- EXPLANATION_MANUAL_POLICY_V62 -->'''

    text = replace_section(
        text,
        "## 12. 설명 섹션",
        "## 13. 응답 전 최종 검증",
        explanation_section,
    )

    checklist_anchor = (
        "- 확인하지 않은 뉴스·가격·공시를 만들어내지 않았는가?"
    )
    checklist_extra = '''- 확인하지 않은 뉴스·가격·공시를 만들어내지 않았는가?
- 상단 기준정보를 2열 표로 표시했는가?
- 가치매수구간과 1차 매도/익절가를 굵은 범위로 표시했는가?
- 표만 요청했는데 월요일·주간 안내나 장문 설명서를 자동으로 붙이지 않았는가?
- 사용자가 `설명서`를 요청했을 때만 8단계 전체 설명서를 제공했는가?
- 기본 각주가 실제 표시·데이터 제한·투자 참고 고지에 필요한 최소 범위인가?'''
    if (
        checklist_anchor in text
        and "8단계 전체 설명서를 제공했는가?" not in text
    ):
        text = text.replace(
            checklist_anchor,
            checklist_extra,
            1,
        )

    old_overlay_version = (
        "- 규칙 버전: `2026-06-30-v5.1-request-time-price-overlay`"
    )
    new_overlay_version = f"- 규칙 버전: `{RULES_VERSION}`"
    if old_overlay_version in text:
        text = text.replace(
            old_overlay_version,
            new_overlay_version,
            1,
        )

    forbidden = [
        "매주 월요일 첫 표에는",
        "같은 주 나머지 요청은",
    ]
    for phrase in forbidden:
        if phrase in text:
            raise PatchError(
                f"구형 자동 설명 문구가 남음: {phrase}"
            )

    required = [
        "개선안2 최종형",
        "자동 주간 설명",
        "30초 사용법",
        "표시 읽는 법",
        "어떤 표를 사용할지",
        "항목 읽는 법",
        "점수·추천·주의사유 해석",
        "여러 표 연결 방법",
        "꼭 기억할 원칙",
        "주요 용어",
        PATCH_MARKER,
    ]
    for phrase in required:
        if phrase not in text:
            raise PatchError(
                f"필수 규칙 문구 누락: {phrase}"
            )

    RULES.write_text(
        text.rstrip() + "\n",
        encoding="utf-8",
    )


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")

    text = replace_once(
        text,
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        (
            'SCRIPT_VERSION = '
            '"build_api_json.py v4.2_v6.2_explanation_manual_only"'
        ),
        label="build_api_json 버전",
    )

    policy_start = text.find(
        "PRESENTATION_POLICY: Dict[str, Any] = {"
    )
    policy_end_marker = "# REQUEST_TIME_PRICE_POLICY"
    policy_end = text.find(
        policy_end_marker,
        policy_start,
    )
    if policy_start < 0 or policy_end < 0:
        raise PatchError(
            "PRESENTATION_POLICY 경계 누락"
        )

    policy_block = '''PRESENTATION_POLICY: Dict[str, Any] = {
    "format_contract": "improvement_plan_2_final",
    "default_output_mode": "single_main_table",
    "separate_recommendation_table_default": False,
    "recommendation_markings_embedded_in_main_table": True,
    "explicit_shortlist_request": (
        "filter main candidate rows and output only the shortlist table"
    ),
    "duplicate_rows_across_main_and_shortlist_tables": False,
    "metadata_display_mode": "compact_two_column_table",
    "bold_price_ranges": True,
    "explanation_default_mode": "main_table_plus_minimal_required_notes_only",
    "automatic_weekly_guide": False,
    "full_manual_trigger": "설명서",
    "partial_help_trigger_phrases": [
        "사용법",
        "해석해줘",
        "표시 설명",
        "항목 설명",
        "용어 설명",
    ],
    "full_manual_section_order": [
        "30초 사용법",
        "표시 읽는 법",
        "어떤 표를 사용할지",
        "항목 읽는 법",
        "점수·추천·주의사유 해석",
        "여러 표 연결 방법",
        "꼭 기억할 원칙",
        "주요 용어",
    ],
    "minimal_notes_allowed": [
        "symbols_used_in_current_table",
        "request_time_price_failures_or_partial_results",
        "after_hours_not_reflected",
        "short_investment_reference_disclaimer",
    ],
    "prohibited_default_extras": [
        "monday_first_table_guide",
        "weekly_usage_guide",
        "full_command_catalog",
        "full_glossary",
        "long_explanation_section",
    ],
}
# EXPLANATION_MANUAL_POLICY_V62
'''

    text = (
        text[:policy_start]
        + policy_block
        + text[policy_end:]
    )

    usage_pattern = re.compile(
        r'(?P<indent>[ \t]*)"usage_rule":\s*\(\s*\n'
        r'.*?'
        r'(?P=indent)\),',
        flags=re.DOTALL,
    )
    usage_replacement = '''        "usage_rule": (
            "Custom GPT must call this endpoint first. "
            "Only when api_sync_ok and official_fresh_now are both true may it "
            "describe the data as the latest official dataset. "
            "Default output must use the improvement-plan-2 final format: "
            "one compact metadata table, one main stock table, bold buy/target "
            "price ranges, and only minimal necessary notes. "
            "Never add a Monday or weekly usage guide automatically. "
            "Output the full eight-section manual only when the user requests "
            "'설명서'. If api_sync_ok is false, stop table analysis."
        ),'''
    text, usage_count = usage_pattern.subn(
        usage_replacement,
        text,
        count=1,
    )
    if usage_count != 1:
        raise PatchError(
            f"usage_rule 교체 수 오류: {usage_count}"
        )

    required_build = [
        '"format_contract": "improvement_plan_2_final"',
        '"automatic_weekly_guide": False',
        '"full_manual_trigger": "설명서"',
        '"bold_price_ranges": True',
        PATCH_MARKER,
    ]
    for phrase in required_build:
        if phrase not in text:
            raise PatchError(
                f"build 정책 문구 누락: {phrase}"
            )

    BUILD.write_text(
        text,
        encoding="utf-8",
    )


def main() -> int:
    patch_rules()
    patch_build()
    print("EXPLANATION_MANUAL_POLICY_V62=APPLIED")
    print(f"RULES_VERSION={RULES_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
