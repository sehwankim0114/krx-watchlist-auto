#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Patch repository for compact KOSPI/KOSDAQ Custom GPT Actions.

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
SCHEMA = ROOT / "docs" / "custom_gpt_action_schema.yaml"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

RULES_VERSION = "2026-07-08-v6.6-lightweight-watchlists"
MARKER = "LIGHTWEIGHT_WATCHLIST_BUILD_V66"

KOSPI_PATH = (
    "/sehwankim0114/krx-watchlist-auto/main/"
    "api/kospi_watchlist.json"
)
KOSDAQ_PATH = (
    "/sehwankim0114/krx-watchlist-auto/main/"
    "api/kosdaq_watchlist.json"
)
LEGACY_KOSPI_PATH = (
    "/sehwankim0114/krx-watchlist-auto/main/"
    "api/kospi_candidates_30.json"
)
LEGACY_KOSDAQ_PATH = (
    "/sehwankim0114/krx-watchlist-auto/main/"
    "api/kosdaq_candidates_10.json"
)


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)
    text = BUILD.read_text(encoding="utf-8")

    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = '
        '"build_api_json.py v4.6_lightweight_watchlists_v66"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"build_api_json.py SCRIPT_VERSION 교체 수 오류: {count}"
        )

    if MARKER not in text:
        anchor = 'write_json(API / "manifest.json", manifest_payload)'
        if text.count(anchor) != 1:
            raise PatchError(
                f"manifest 저장 기준점 오류: {text.count(anchor)}"
            )
        injection = "\n".join(
            [
                'write_json(API / "manifest.json", manifest_payload)',
                "",
                "    # LIGHTWEIGHT_WATCHLIST_BUILD_V66_BEGIN",
                "    from build_lightweight_watchlist_api_v66 import (",
                "        build_lightweight_watchlists,",
                "    )",
                "    lightweight_entries = build_lightweight_watchlists(API)",
                "    print(",
                '        "LIGHTWEIGHT_WATCHLISTS="',
                "        + \",\".join(",
                "            f\"{item['table_id']}:{item['row_count']}:\"",
                "            f\"{item['payload_size_bytes']}\"",
                "            for item in lightweight_entries",
                "        )",
                "    )",
                "    # LIGHTWEIGHT_WATCHLIST_BUILD_V66_END",
            ]
        )
        text = text.replace(anchor, injection, 1)

    required = [
        "build_lightweight_watchlist_api_v66",
        "LIGHTWEIGHT_WATCHLIST_BUILD_V66_BEGIN",
        "LIGHTWEIGHT_WATCHLIST_BUILD_V66_END",
    ]
    for token in required:
        if token not in text:
            raise PatchError(f"build_api_json.py 필수 토큰 누락: {token}")

    BUILD.write_text(text, encoding="utf-8")


def action_entry(
    operation_id: str,
    summary: str,
    description: str,
) -> Dict[str, Any]:
    return {
        "get": {
            "operationId": operation_id,
            "summary": summary,
            "description": description,
            "responses": {
                "200": {
                    "description": summary,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/AnyObject"
                            }
                        }
                    },
                }
            },
        }
    }


def patch_schema() -> None:
    if not SCHEMA.exists():
        raise FileNotFoundError(SCHEMA)

    data = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PatchError("Action 스키마 최상위 객체 오류")

    info = data.setdefault("info", {})
    info["version"] = "6.1.0"
    info["description"] = (
        "Read-only synchronized KRX strict-contract API. "
        "For default KOSPI/KOSDAQ tables, use the compact "
        "getKospiWatchlist/getKosdaqWatchlist operations, never reconstruct "
        "rows from CSV, and use the legacy full candidate endpoints only for "
        "explicit diagnostics."
    )

    paths = data.get("paths")
    if not isinstance(paths, dict):
        raise PatchError("Action 스키마 paths 누락")

    compact_entries = {
        KOSPI_PATH: action_entry(
            "getKospiWatchlist",
            "Get compact KOSPI watchlist candidate rows",
            (
                "Preferred default endpoint for 코피표. Returns exactly "
                "30 compact rows with quote keys, price ranges, current "
                "position, liquidity, financial, supply burden, score, "
                "and source metadata. Do not fall back to CSV or the "
                "legacy full endpoint if this call fails."
            ),
        ),
        KOSDAQ_PATH: action_entry(
            "getKosdaqWatchlist",
            "Get compact KOSDAQ watchlist candidate rows",
            (
                "Preferred default endpoint for 코닥표. Returns exactly "
                "10 compact rows with quote keys, price ranges, current "
                "position, liquidity, financial, supply burden, score, "
                "and source metadata. Do not fall back to CSV or the "
                "legacy full endpoint if this call fails."
            ),
        ),
    }

    rebuilt: Dict[str, Any] = {}
    inserted = False
    for path, value in paths.items():
        if path == LEGACY_KOSPI_PATH and not inserted:
            rebuilt.update(compact_entries)
            inserted = True
        rebuilt[path] = value

    if not inserted:
        compact_entries.update(rebuilt)
        rebuilt = compact_entries

    for legacy_path, legacy_name in (
        (LEGACY_KOSPI_PATH, "KOSPI"),
        (LEGACY_KOSDAQ_PATH, "KOSDAQ"),
    ):
        entry = rebuilt.get(legacy_path)
        if isinstance(entry, dict) and isinstance(entry.get("get"), dict):
            entry["get"]["summary"] = (
                f"Legacy full {legacy_name} candidate payload for diagnostics"
            )
            entry["get"]["description"] = (
                "Large legacy payload. Do not use for the default stock "
                "table when the compact watchlist endpoint is available."
            )

    data["paths"] = rebuilt

    rendered = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    required = [
        "operationId: getKospiWatchlist",
        "operationId: getKosdaqWatchlist",
        "api/kospi_watchlist.json",
        "api/kosdaq_watchlist.json",
        "version: 6.1.0",
    ]
    for token in required:
        if token not in rendered:
            raise PatchError(f"Action 스키마 필수 토큰 누락: {token}")

    SCHEMA.write_text(rendered, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")
    text, count = re.subn(
        r'(- 최종 업데이트:\s*)\d{4}-\d{2}-\d{2}',
        r'\g<1>2026-07-08',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"규칙 최종 업데이트 교체 수 오류: {count}")

    text = re.sub(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{RULES_VERSION}\g<2>',
        text,
    )

    if "<!-- LIGHTWEIGHT_WATCHLIST_POLICY_V66 -->" not in text:
        section = r'''

---

## 14. 코피·코닥 경량 Action 정책

### 14-1. 기본 Action

- `코피표 줘`, `코스피 줘`의 기본 후보 Action은
  `getKospiWatchlist`이다.
- `코닥표 줘`, `코스닥 줘`의 기본 후보 Action은
  `getKosdaqWatchlist`이다.
- 코피표는 경량 API의 후보 30개 전체를 사용한다.
- 코닥표는 경량 API의 후보 10개 전체를 사용한다.
- 기존 `getKospiCandidates`, `getKosdaqCandidates`는 진단용 대형
  원본으로만 남기며 기본 표 작성에는 사용하지 않는다.

### 14-2. 응답 실패 처리

- 경량 Action이 실패하거나 행 수가 맞지 않으면 CSV, GitHub 원본,
  기존 대형 후보 API에서 표를 임의 복원하지 않는다.
- 실패 사실과 누락 범위를 명확히 표시하고 분석을 중단한다.
- 성공한 경량 API의 행 순서를 그대로 유지한다.

### 14-3. 날짜 표시

- 후보 분석자료 기준일은 `candidate_analysis_date`를 사용한다.
- `valuation_basis_date_min`, `valuation_basis_date_max`는 재무·밸류에이션
  계산 기준일로 별도 표시할 수 있다.
- 재무·밸류에이션 기준일을 후보 분석자료 기준일로 대신 쓰지 않는다.
- 공식 KRX 최신성은 `official_data`의 기대 거래일과 실제 기준일을
  별도로 확인한다.

### 14-4. 요청시점 현재가 연결

- 각 행의 `quote_key`와 `quote_market`으로 요청시점 현재가를 조회한다.
- 10개씩 순차 조회하고 실패 종목만 5개, 2개 순서로 재시도한다.
- 경량 API의 `static_price`는 정적 참고가격이며 요청시점 현재가로
  위장하지 않는다.

### 14-5. 경량 응답 검증

- 코피표는 정확히 30행, 코닥표는 정확히 10행이어야 한다.
- `build_id`, `rules_version`, `rules_sha256`은 상태·규칙·매니페스트와
  일치해야 한다.
- 각 행에는 `name`, `code`, `quote_key`, `quote_market`,
  `value_buy_range`, `first_sell_target_range`, `current_position`,
  `score_reason`이 있어야 한다.
- 경량 API 파일은 각각 65,000바이트 이하를 유지한다.

<!-- LIGHTWEIGHT_WATCHLIST_POLICY_V66 -->
'''
        text = text.rstrip() + section + "\n"

    required = [
        "getKospiWatchlist",
        "getKosdaqWatchlist",
        "CSV, GitHub 원본",
        "candidate_analysis_date",
        "65,000바이트",
        "LIGHTWEIGHT_WATCHLIST_POLICY_V66",
    ]
    for token in required:
        if token not in text:
            raise PatchError(f"규칙 필수 문구 누락: {token}")

    RULES.write_text(text, encoding="utf-8")


def main() -> int:
    patch_build()
    patch_schema()
    patch_rules()
    print("LIGHTWEIGHT_WATCHLIST_PATCH_V66=APPLIED")
    print(f"RULES_VERSION={RULES_VERSION}")
    print("OPERATIONS=getKospiWatchlist,getKosdaqWatchlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
