#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# patch_quote_key_aliases_v64.py
#
# 실제 API 원본 열을 요청시점 현재가 조회 키로 공식 인정한다.
# - 미국: ticker 또는 symbol
# - 국내: code, 종목코드 또는 stock_code

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
VALIDATOR = ROOT / "validate_api_sync.py"

PATCH_VERSION = "v6.4-quote-key-aliases"
PATCH_MARKER = "QUOTE_KEY_ALIASES_V64"


class PatchError(RuntimeError):
    pass


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")

    # 요청시점 조회 정책에 실제 원본 열 별칭을 추가한다.
    pattern = re.compile(
        r'"quote_key_fields"\s*:\s*\[\s*'
        r'"ticker"\s*,\s*"code"\s*,\s*"종목코드"\s*'
        r'\]\s*,'
    )
    replacement = (
        '"quote_key_fields": [\n'
        '        "ticker",\n'
        '        "symbol",\n'
        '        "code",\n'
        '        "종목코드",\n'
        '        "stock_code",\n'
        '    ],\n'
        '    "quote_key_aliases": {\n'
        '        "us": ["ticker", "symbol"],\n'
        '        "kr": ["code", "종목코드", "stock_code"],\n'
        '    },'
    )

    if '"stock_code"' not in text or '"quote_key_aliases"' not in text:
        text, count = pattern.subn(replacement, text, count=1)
        if count != 1:
            raise PatchError(
                f"build_api_json.py quote_key_fields 교체 수 오류: {count}"
            )

    # 스크립트 버전만 최신화한다.
    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = '
        '"build_api_json.py v4.4_explanation_manual_v62_quote_aliases_v64"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"build_api_json.py SCRIPT_VERSION 교체 수 오류: {count}"
        )

    if PATCH_MARKER not in text:
        anchor = "# REQUEST_TIME_PRICE_POLICY_V51_END"
        if anchor not in text:
            raise PatchError(
                "REQUEST_TIME_PRICE_POLICY 종료 기준점 누락"
            )
        text = text.replace(
            anchor,
            anchor + "\n# " + PATCH_MARKER,
            1,
        )

    required = [
        '"symbol"',
        '"stock_code"',
        '"quote_key_aliases"',
        PATCH_MARKER,
    ]
    for token in required:
        if token not in text:
            raise PatchError(
                f"build_api_json.py 필수 토큰 누락: {token}"
            )

    BUILD.write_text(text, encoding="utf-8")


def patch_validator() -> None:
    if not VALIDATOR.exists():
        raise FileNotFoundError(VALIDATOR)

    text = VALIDATOR.read_text(encoding="utf-8")

    # 실제 API 열 이름을 검증 후보로 인정한다.
    old_set = (
        'quote_key_candidates = '
        '{"ticker", "code", "종목코드"}'
    )
    new_set = (
        'quote_key_candidates = {\n'
        '        "ticker",\n'
        '        "symbol",\n'
        '        "code",\n'
        '        "종목코드",\n'
        '        "stock_code",\n'
        '    }'
    )

    if '"symbol"' not in text or '"stock_code"' not in text:
        if old_set not in text:
            raise PatchError(
                "validate_api_sync.py quote_key_candidates 기준점 누락"
            )
        text = text.replace(old_set, new_set, 1)

    text, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"validate_api_sync\.py [^"]+"',
        'SCRIPT_VERSION = '
        '"validate_api_sync.py v1.4_quote_key_aliases_v64"',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"validate_api_sync.py SCRIPT_VERSION 교체 수 오류: {count}"
        )

    # 오류 문구도 실제 별칭 구조에 맞게 명확히 한다.
    text = text.replace(
        "ticker/code column missing for live lookup",
        "quote key column missing for live lookup "
        "(ticker/symbol/code/종목코드/stock_code)",
    )

    required = [
        '"ticker"',
        '"symbol"',
        '"stock_code"',
        "quote key column missing for live lookup",
    ]
    for token in required:
        if token not in text:
            raise PatchError(
                f"validate_api_sync.py 필수 토큰 누락: {token}"
            )

    VALIDATOR.write_text(text, encoding="utf-8")


def main() -> int:
    patch_build()
    patch_validator()
    print("QUOTE_KEY_ALIASES_V64=APPLIED")
    print("US_KEYS=ticker,symbol")
    print("KR_KEYS=code,종목코드,stock_code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
