#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# patch_output_order_and_price_retry_v65.py

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
EXPLANATION_PATCH = ROOT / "patch_explanation_manual_policy_v62.py"

RULES_VERSION = "2026-07-07-v6.5-output-order-price-retry"
PATCH_MARKER = "OUTPUT_ORDER_PRICE_RETRY_V65"


class PatchError(RuntimeError):
    pass


PRESENTATION_BLOCK = r'''PRESENTATION_POLICY: Dict[str, Any] = {
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
    "output_sequence": [
        "title",
        "metadata_two_column_table",
        "main_stock_table",
        "minimal_required_notes",
    ],
    "metadata_table_complete_before_main_table": True,
    "minimal_notes_position": "after_main_table_only",
    "forbid_notes_inside_metadata_table": True,
    "forbid_metadata_rows_after_notes": True,
    "explanation_default_mode": (
        "main_table_plus_minimal_required_notes_only"
    ),
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
        "notes_between_metadata_rows",
        "metadata_rows_after_notes",
    ],
}
# EXPLANATION_MANUAL_POLICY_V62
# OUTPUT_ORDER_PRICE_RETRY_V65'''


REQUEST_PRICE_BLOCK = r'''# REQUEST_TIME_PRICE_POLICY_V51_BEGIN
REQUEST_TIME_PRICE_POLICY: Dict[str, Any] = {
    "enabled": True,
    "mode": "request_time_dynamic_overlay",
    "lookup_scope": "all_rows_in_requested_table",
    "action_operation_id": "getRequestTimePrices",
    "health_operation_id": "getRequestTimePriceHealth",
    "api_base_url": "https://krx-live-price-ksh.diaconos.workers.dev",
    "max_batch_size": 10,
    "initial_batch_size": 10,
    "batch_execution_mode": "sequential",
    "max_parallel_batches": 1,
    "retry_failed_quotes": True,
    "retry_only_failed": True,
    "retry_rounds": 2,
    "retry_batch_sizes": [5, 2],
    "retry_execution_mode": "sequential",
    "merge_results_by_quote_key": True,
    "preserve_input_order": True,
    "deduplicate_quote_keys": True,
    "final_success_count_after_retries": True,
    "quote_key_fields": [
        "ticker",
        "symbol",
        "code",
        "종목코드",
        "stock_code",
    ],
    "quote_key_aliases": {
        "us": ["ticker", "symbol"],
        "kr": ["code", "종목코드", "stock_code"],
    },
    "market_fields": ["market", "시장", "exchange", "country"],
    "preserve_official_history": True,
    "allow_last_confirmed_official_when_delayed": True,
    "failed_quote_behavior": (
        "after_all_retries_keep_row_mark_white_circle_do_not_fake_price"
    ),
    "large_table_behavior": (
        "split_into_sequential_batches_until_all_rows_attempted"
    ),
    "execution_steps": [
        "extract_all_quote_keys_in_table_order",
        "call_initial_sequential_batches_of_at_most_10",
        "collect_only_failed_quote_keys",
        "retry_failed_keys_in_batches_of_at_most_5",
        "retry_still_failed_keys_in_batches_of_at_most_2",
        "merge_all_successes_and_preserve_original_row_order",
        "mark_only_final_failures_with_white_circle",
    ],
}
# REQUEST_TIME_PRICE_POLICY_V51_END
# QUOTE_KEY_ALIASES_V64
# OUTPUT_ORDER_PRICE_RETRY_V65'''


RULES_SECTION_12 = r'''## 12. 설명서·각주 출력 정책

### 12-1. 기본 주식표 출력

사용자가 `코피표 줘`, `코닥표 줘`, `미관종표 줘`처럼 표만 요청하면
다음 순서를 정확히 지킨다.

1. 표 제목
2. 상단 기준정보를 `구분 | 내용` 2열 표로 **완전히 종료**
3. 개선안2 최종형 본표 1개
4. 본표가 끝난 뒤 최소 필수 각주 1~4개

각주를 상단 기준정보 표의 행 사이에 넣지 않는다.
각주를 출력한 뒤 `시간외 반영 여부`, `공식자료 최신성`, `분석범위`,
`구조 검증` 같은 상단 기준정보 행을 다시 출력하지 않는다.

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

사용자가 단독으로 또는 명확한 요청으로 `설명서`라고 입력했을 때만
전체 사용설명서를 제공한다.

전체 설명서는 다음 순서를 고정한다.

1. **30초 사용법**
2. **표시 읽는 법**
3. **어떤 표를 사용할지**
4. **항목 읽는 법**
5. **점수·추천·주의사유 해석**
6. **여러 표 연결 방법**
7. **꼭 기억할 원칙**
8. **주요 용어**

전체 설명서는 표를 다시 대량 출력하지 않고, 주식 초보자가 실제 표를
읽는 데 필요한 내용만 쉽고 간결하게 설명한다.

### 12-3. 부분 설명 요청

사용자가 `사용법`, `이 표 해석해줘`, `표시 설명`, `항목 설명`,
`현재위치가 뭐야`처럼 특정 설명을 요청하면 요청한 부분만 설명한다.
이 경우에도 전체 8단계 설명서를 자동으로 붙이지 않는다.

### 12-4. 최소 각주와 전체 설명서의 구분

- `⚪ 현재가 확인 실패`, 요청시점 가격 `PARTIAL`, 시간외 미반영 등은
  투자판단에 직접 영향을 주므로 기본 표의 최소 각주로 허용한다.
- `✅·🟡·⚠️·🔻`, 하이픈 `-`, 언더바 `_`처럼 실제 표에서 오해
  가능성이 큰 표시도 해당 표에서 사용됐을 때만 짧게 설명할 수 있다.
- `밸류에이션`, `가이던스`, `오버행` 등의 전체 용어 설명은 기본적으로
  `설명서` 또는 명시적 용어 질문 때 제공한다.
- 최소 각주는 1~4개를 원칙으로 하며, 본표보다 길어지지 않게 한다.
- 가격 구간인 `가치매수구간`과 `1차 매도/익절가`는 모든 표에서
  **굵은 가격~가격 범위**로 표시한다.
- 상단 기준정보는 문장 나열이 아니라 `구분 | 내용`의 간결한 2열 표로
  표시한다.

### 12-5. 요청시점 현재가 배치·재시도

요청 표의 모든 종목을 처음부터 한 번에 30~50개로 보내지 않는다.

1. 원래 본표 순서대로 종목키를 추출하고 중복을 제거한다.
2. 최대 10개씩 나누어 `getRequestTimePrices`를 **순차 호출**한다.
3. 첫 조회에서 실패한 종목키만 모아 최대 5개씩 한 번 재시도한다.
4. 그래도 실패한 종목키만 최대 2개씩 마지막으로 재시도한다.
5. 각 호출 결과를 종목키로 병합하고 본표의 원래 순서를 유지한다.
6. 모든 재시도 후에도 실패한 종목만 `⚪ 현재가 확인 실패`로 표시한다.
7. 성공·실패 수는 재시도까지 끝난 **최종 결과**로 계산한다.
8. 실패 종목에 정적 GitHub 가격을 요청시점 현재가처럼 대신 넣지 않는다.

<!-- OUTPUT_ORDER_PRICE_RETRY_V65 -->'''


def replace_block(
    text: str,
    start_pattern: str,
    end_pattern: str,
    replacement: str,
    label: str,
) -> str:
    pattern = re.compile(
        start_pattern + r".*?" + end_pattern,
        flags=re.DOTALL,
    )
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise PatchError(f"{label} 교체 수 오류: {count}")
    return updated


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")

    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = '
        '"build_api_json.py v4.5_output_order_price_retry_v65"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"build_api_json.py SCRIPT_VERSION 교체 수 오류: {count}"
        )

    text = replace_block(
        text,
        r'PRESENTATION_POLICY:\s*Dict\[str,\s*Any\]\s*=\s*\{',
        r'#\s*EXPLANATION_MANUAL_POLICY_V62',
        PRESENTATION_BLOCK,
        "PRESENTATION_POLICY",
    )

    text = replace_block(
        text,
        r'#\s*REQUEST_TIME_PRICE_POLICY_V51_BEGIN',
        r'#\s*REQUEST_TIME_PRICE_POLICY_V51_END'
        r'(?:\s*#\s*QUOTE_KEY_ALIASES_V64)?'
        r'(?:\s*#\s*OUTPUT_ORDER_PRICE_RETRY_V65)?',
        REQUEST_PRICE_BLOCK,
        "REQUEST_TIME_PRICE_POLICY",
    )

    required = [
        '"minimal_notes_position": "after_main_table_only"',
        '"forbid_notes_inside_metadata_table": True',
        '"max_batch_size": 10',
        '"retry_rounds": 2',
        '"retry_batch_sizes": [5, 2]',
        '"preserve_input_order": True',
        PATCH_MARKER,
    ]
    for token in required:
        if token not in text:
            raise PatchError(
                f"build_api_json.py 필수 정책 누락: {token}"
            )

    BUILD.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")

    text, count = re.subn(
        r'(- 최종 업데이트:\s*)\d{4}-\d{2}-\d{2}',
        r'\g<1>2026-07-07',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"규칙 최종 업데이트 교체 수 오류: {count}"
        )

    text = re.sub(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{RULES_VERSION}\g<2>',
        text,
        count=1,
    )

    start = text.find("## 12. 설명서·각주 출력 정책")
    end = text.find("## 13. 응답 전 최종 검증", start)
    if start < 0 or end < 0:
        raise PatchError("규칙 12~13 섹션 경계 누락")

    text = (
        text[:start]
        + RULES_SECTION_12.rstrip()
        + "\n\n---\n\n"
        + text[end:]
    )

    text = re.sub(
        r'- 한 번에 최대 50개 종목을 조회하고,'
        r'\s*초과하면 모든 종목이 시도될 때까지'
        r'\s*여러 배치로 나눈다\.',
        (
            "- 처음 조회는 최대 10개씩 순차 호출한다. "
            "실패 종목만 최대 5개씩 재시도하고, "
            "그래도 실패한 종목은 최대 2개씩 마지막 재시도한다."
        ),
        text,
        count=1,
    )

    text = re.sub(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{RULES_VERSION}\g<2>',
        text,
    )

    checklist_anchor = (
        "- 기본 각주가 실제 표시·데이터 제한·투자 참고 고지에 "
        "필요한 최소 범위인가?"
    )
    checklist_extra = (
        checklist_anchor
        + "\n- 상단 기준정보 표를 완전히 끝낸 뒤 본표를 시작했는가?"
        + "\n- 최소 각주는 본표가 끝난 뒤에만 배치했는가?"
        + "\n- 각주 뒤에 상단 기준정보 행을 다시 출력하지 않았는가?"
        + "\n- 현재가를 10개씩 순차 조회하고 실패 종목만 재시도했는가?"
    )
    if checklist_anchor in text and (
        "현재가를 10개씩 순차 조회" not in text
    ):
        text = text.replace(
            checklist_anchor,
            checklist_extra,
            1,
        )

    if "한 번에 최대 50개 종목을 조회" in text:
        raise PatchError(
            "구형 현재가 50개 일괄 호출 문구가 남음"
        )

    required = [
        "### 12-5. 요청시점 현재가 배치·재시도",
        "최대 10개씩",
        "최대 5개씩",
        "최대 2개씩",
        "본표가 끝난 뒤 최소 필수 각주",
        PATCH_MARKER,
    ]
    for token in required:
        if token not in text:
            raise PatchError(
                f"규칙 필수 문구 누락: {token}"
            )

    RULES.write_text(
        text.rstrip() + "\n",
        encoding="utf-8",
    )


def patch_future_explanation_patch() -> None:
    if not EXPLANATION_PATCH.exists():
        return

    text = EXPLANATION_PATCH.read_text(encoding="utf-8")

    text = re.sub(
        r'RULES_VERSION\s*=\s*"[^"]+"',
        f'RULES_VERSION = "{RULES_VERSION}"',
        text,
        count=1,
    )

    policy_pattern = re.compile(
        r"policy_block\s*=\s*'''PRESENTATION_POLICY:"
        r".*?"
        r"# EXPLANATION_MANUAL_POLICY_V62\n'''",
        flags=re.DOTALL,
    )
    new_policy_literal = (
        "policy_block = '''"
        + PRESENTATION_BLOCK
        + "\n'''"
    )
    text, _ = policy_pattern.subn(
        new_policy_literal,
        text,
        count=1,
    )

    marker = "<!-- EXPLANATION_MANUAL_POLICY_V62 -->"
    if PATCH_MARKER not in text and marker in text:
        extra = r'''
### 12-5. 요청시점 현재가 배치·재시도

- 출력 순서는 제목 → 상단 기준정보 2열 표 → 본표 → 최소 각주다.
- 각주는 본표 뒤에만 두며 상단 기준정보 표 사이에 넣지 않는다.
- 현재가는 최대 10개씩 순차 조회한다.
- 실패 종목만 최대 5개씩, 다시 최대 2개씩 재시도한다.
- 모든 재시도 후 실패한 종목만 `⚪ 현재가 확인 실패`로 표시한다.

<!-- OUTPUT_ORDER_PRICE_RETRY_V65 -->

'''
        text = text.replace(
            marker,
            extra + marker,
            1,
        )

    EXPLANATION_PATCH.write_text(
        text,
        encoding="utf-8",
    )


def main() -> int:
    patch_build()
    patch_rules()
    patch_future_explanation_patch()

    print("OUTPUT_ORDER_PRICE_RETRY_V65=APPLIED")
    print(f"RULES_VERSION={RULES_VERSION}")
    print("OUTPUT_SEQUENCE=TITLE_METADATA_MAIN_NOTES")
    print("INITIAL_BATCH_SIZE=10")
    print("RETRY_BATCH_SIZES=5,2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
