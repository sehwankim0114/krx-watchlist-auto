#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# patch_request_time_quote_keys_v63.py
#
# 미국 표에는 ticker, 국내 표에는 6자리 code를 추가하고
# 요청시점 현재가 조회 키를 모든 행에서 검증한다.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_api_json.py"
VALIDATOR = ROOT / "validate_api_sync.py"

PATCH_MARKER = "REQUEST_TIME_QUOTE_KEYS_V63"
BUILD_VERSION = (
    'SCRIPT_VERSION = '
    '"build_api_json.py v4.3_quote_keys_v63_explanation_manual_v62"'
)
VALIDATOR_VERSION = (
    'SCRIPT_VERSION = '
    '"validate_api_sync.py v1.4_quote_key_rows_v63"'
)


class PatchError(RuntimeError):
    pass


NORMALIZER_BLOCK = r"""
def normalize_live_lookup_columns(
    df: pd.DataFrame,
    spec: TableSpec,
) -> pd.DataFrame:
    result = df.copy()

    def first_existing(candidates: Sequence[str]) -> Optional[str]:
        return next(
            (name for name in candidates if name in result.columns),
            None,
        )

    def clean_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        return text

    def normalize_code_value(value: Any) -> Optional[str]:
        text = clean_text(value)
        if text is None:
            return None
        if re.fullmatch(r"\d+\.0", text):
            text = text[:-2]
        digits = re.sub(r"\D", "", text)
        if digits:
            return digits[-6:].zfill(6)
        return text

    def normalize_ticker_value(value: Any) -> Optional[str]:
        text = clean_text(value)
        if text is None:
            return None
        if "·" in text:
            text = text.rsplit("·", 1)[-1].strip()
        elif ":" in text:
            text = text.rsplit(":", 1)[-1].strip()
        return text.upper() or None

    ticker_source = first_existing(
        ("ticker", "symbol", "티커", "market_ticker")
    )
    code_source = first_existing(
        ("code", "종목코드", "stock_code")
    )

    is_us_table = spec.table_id.startswith("us_")

    if is_us_table:
        if "ticker" not in result.columns and ticker_source is not None:
            result["ticker"] = result[ticker_source].map(
                normalize_ticker_value
            )
        elif "ticker" in result.columns:
            result["ticker"] = result["ticker"].map(
                normalize_ticker_value
            )
    else:
        if "code" not in result.columns and code_source is not None:
            result["code"] = result[code_source].map(
                normalize_code_value
            )
        elif "code" in result.columns:
            result["code"] = result["code"].map(
                normalize_code_value
            )

    if "market" not in result.columns:
        if is_us_table:
            result["market"] = "USA"
        elif spec.table_id.startswith("kosdaq"):
            result["market"] = "KOSDAQ"
        elif spec.table_id.startswith("kospi"):
            result["market"] = "KOSPI"

    return result


# REQUEST_TIME_QUOTE_KEYS_V63
""".strip("\n")


VALIDATOR_BLOCK = r"""
row_count = int(table_payload.get("row_count") or 0)
columns = set(table_payload.get("columns") or [])
available_quote_keys = sorted(
    columns & quote_key_candidates
)
if row_count > 0 and not available_quote_keys:
    errors.append(
        f"{table_id}: ticker/code column missing for live lookup"
    )
elif row_count > 0:
    rows = table_payload.get("rows") or []
    if not isinstance(rows, list):
        errors.append(
            f"{table_id}: rows must be a list for live lookup"
        )
    else:
        missing_key_rows = []
        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                missing_key_rows.append(row_number)
                continue
            has_key = any(
                row.get(key) not in (None, "")
                for key in available_quote_keys
            )
            if not has_key:
                missing_key_rows.append(row_number)
        if missing_key_rows:
            preview = ",".join(
                str(number)
                for number in missing_key_rows[:10]
            )
            errors.append(
                f"{table_id}: live lookup key missing in rows "
                f"{preview}"
            )
""".strip("\n")


def replace_script_version(
    text: str,
    replacement: str,
    label: str,
) -> str:
    updated, count = re.subn(
        r'SCRIPT_VERSION\s*=\s*"[^"]+"',
        replacement,
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(
            f"{label} SCRIPT_VERSION 교체 수 오류: {count}"
        )
    return updated


def patch_build() -> None:
    if not BUILD.exists():
        raise FileNotFoundError(BUILD)

    text = BUILD.read_text(encoding="utf-8")
    text = replace_script_version(
        text,
        BUILD_VERSION,
        "build_api_json.py",
    )

    if PATCH_MARKER not in text:
        anchor = (
            "def dataframe_records("
            "df: pd.DataFrame"
            ") -> List[Dict[str, Any]]:"
        )
        index = text.find(anchor)
        if index < 0:
            raise PatchError(
                "dataframe_records 삽입 기준점 누락"
            )
        text = (
            text[:index]
            + NORMALIZER_BLOCK
            + "\n\n"
            + text[index:]
        )

    if "normalize_live_lookup_columns(df, spec)" not in text:
        match = re.search(
            r'(?P<indent>[ \t]+)'
            r'df,\s*overlay_used\s*=\s*'
            r'overlay_dataframe\(\s*df,\s*overlay_path\s*\)\s*\n',
            text,
        )
        if match is None:
            raise PatchError(
                "normalize 호출 삽입 기준점 누락"
            )
        indent = match.group("indent")
        text = (
            text[:match.end()]
            + f"{indent}df = "
            "normalize_live_lookup_columns(df, spec)\n"
            + text[match.end():]
        )

    required = [
        "def normalize_live_lookup_columns(",
        'result["ticker"]',
        'result["code"]',
        'result["market"] = "USA"',
        'result["market"] = "KOSPI"',
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
    text = replace_script_version(
        text,
        VALIDATOR_VERSION,
        "validate_api_sync.py",
    )

    old_pattern = re.compile(
        r'(?P<indent>[ \t]+)'
        r'row_count\s*=\s*int\('
        r'table_payload\.get\("row_count"\)\s*or\s*0'
        r'\)\s*\n'
        r'(?P=indent)columns\s*=\s*set\('
        r'table_payload\.get\("columns"\)\s*or\s*\[\]'
        r'\)\s*\n'
        r'(?P=indent)if\s+row_count\s*>\s*0\s+and\s+not\s+'
        r'\(columns\s*&\s*quote_key_candidates\):\s*\n'
        r'(?P=indent)[ \t]+errors\.append\(\s*\n'
        r'(?P=indent)[ \t]+'
        r'f"\{table_id\}: ticker/code column missing for live lookup"'
        r'\s*\n'
        r'(?P=indent)[ \t]+\)\s*\n',
        flags=re.MULTILINE,
    )

    if "available_quote_keys = sorted(" not in text:
        match = old_pattern.search(text)
        if match is None:
            raise PatchError(
                "validate_api_sync.py quote-key 기준점 누락"
            )
        indent = match.group("indent")
        replacement = "\n".join(
            indent + line if line else ""
            for line in VALIDATOR_BLOCK.splitlines()
        ) + "\n"
        text = (
            text[:match.start()]
            + replacement
            + text[match.end():]
        )

    required = [
        'quote_key_candidates = {"ticker", "code", "종목코드"}',
        "available_quote_keys = sorted(",
        "live lookup key missing in rows",
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
    print("REQUEST_TIME_QUOTE_KEYS_V63=APPLIED")
    print("US_QUOTE_KEY=ticker")
    print("KR_QUOTE_KEY=code")
    print("KR_CODE_FORMAT=6_DIGITS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
