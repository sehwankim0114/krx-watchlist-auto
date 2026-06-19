#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
validate_latest_sync.py

latest 폴더의 KRX 공식 상태파일과 후보 CSV가 서로 일치하는지 검증한다.

검증 원칙
- stale 자체는 실패가 아니다.
- 상태파일끼리 날짜·fresh·status가 다르면 실패한다.
- fresh=True이면 기대 거래일과 KOSPI/KOSDAQ 실제 기준일이 같아야 한다.
- 후보 CSV가 비어 있으면 실패한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCRIPT_VERSION = "validate_latest_sync.py v1.1_status_alias"

STATUS_JSON_FILES = (
    "official_data_status_latest.json",
    "krx_official_retry_status_latest.json",
    "data_freshness_notice_latest.json",
)

STATUS_TXT_FILES = (
    "krx_official_retry_status_latest.txt",
    "data_freshness_notice_latest.txt",
)

SYNC_FIELDS = (
    "run_at_kst",
    "expected_official_trading_date",
    "kospi_actual_date",
    "kosdaq_actual_date",
    "basis_date_for_display",
    "fresh",
    "official_fresh",
    "status",
    "official_status",
    "run_mode",
    "final_run_mode",
)

REQUIRED_CSV_FILES = (
    "kospi_candidates_30_latest.csv",
    "kospi_recommend_7_latest.csv",
)

DATE_COLUMNS = (
    "asof_date",
    "basis_date",
    "last_date",
    "date",
    "trading_date",
    "basDt",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    return parser.parse_args()


def normalize_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return value


def normalize_status(value: Any) -> Any:
    """같은 의미의 공식 상태 표현을 하나의 값으로 정규화한다."""
    if value is None:
        return None

    text = str(value).strip().upper()
    aliases = {
        "SKIPPED_ALREADY_FRESH": "FRESH",
        "ALREADY_FRESH": "FRESH",
    }
    return aliases.get(text, text)


def normalize_value(field: str, value: Any) -> Any:
    if field in {"fresh", "official_fresh"}:
        return normalize_bool(value)
    if field in {"status", "official_status"}:
        return normalize_status(value)
    if value is None:
        return None
    return str(value).strip()


def read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value


def read_key_value_txt(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = normalize_bool(value.strip())
    if not result:
        raise ValueError("No key=value pairs found")
    return result


def load_status_files(
    output_dir: Path,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    loaded: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for filename in STATUS_JSON_FILES:
        path = output_dir / filename
        if not path.exists():
            errors.append(f"MISSING_STATUS_FILE={filename}")
            continue
        try:
            loaded[filename] = read_json(path)
        except Exception as exc:
            errors.append(
                f"STATUS_PARSE_FAIL={filename}:{type(exc).__name__}:{exc}"
            )

    for filename in STATUS_TXT_FILES:
        path = output_dir / filename
        if not path.exists():
            errors.append(f"MISSING_STATUS_FILE={filename}")
            continue
        try:
            loaded[filename] = read_key_value_txt(path)
        except Exception as exc:
            errors.append(
                f"STATUS_PARSE_FAIL={filename}:{type(exc).__name__}:{exc}"
            )

    return loaded, errors


def compare_status_fields(
    loaded: Dict[str, Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    if not loaded:
        return ["NO_STATUS_FILES_LOADED"]

    reference_name = (
        "official_data_status_latest.json"
        if "official_data_status_latest.json" in loaded
        else next(iter(loaded))
    )
    reference = loaded[reference_name]

    for field in SYNC_FIELDS:
        reference_value = normalize_value(field, reference.get(field))

        for filename, data in loaded.items():
            current_value = normalize_value(field, data.get(field))

            if current_value != reference_value:
                errors.append(
                    "STATUS_FIELD_MISMATCH="
                    f"field={field},reference={reference_name}:{reference_value},"
                    f"file={filename}:{current_value}"
                )

    return errors


def validate_fresh_logic(
    loaded: Dict[str, Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    if not loaded:
        return errors

    reference = loaded.get("official_data_status_latest.json")
    if reference is None:
        reference = next(iter(loaded.values()))

    fresh = normalize_bool(
        reference.get("official_fresh", reference.get("fresh", False))
    )
    expected = reference.get("expected_official_trading_date")
    kospi_actual = reference.get("kospi_actual_date")
    kosdaq_actual = reference.get("kosdaq_actual_date")
    status = str(
        reference.get("official_status")
        or reference.get("status")
        or ""
    )

    if fresh is True:
        if not expected:
            errors.append("FRESH_WITHOUT_EXPECTED_DATE")
        if kospi_actual != expected:
            errors.append(
                f"FRESH_KOSPI_DATE_MISMATCH=expected={expected},actual={kospi_actual}"
            )
        if kosdaq_actual != expected:
            errors.append(
                f"FRESH_KOSDAQ_DATE_MISMATCH=expected={expected},actual={kosdaq_actual}"
            )
        if status not in {"FRESH", "SKIPPED_ALREADY_FRESH"}:
            errors.append(f"FRESH_STATUS_INVALID={status}")
    else:
        if status in {"FRESH", "SKIPPED_ALREADY_FRESH"}:
            errors.append(f"STALE_BUT_STATUS_IS_FRESH={status}")

    if kospi_actual and kosdaq_actual and kospi_actual != kosdaq_actual:
        errors.append(
            "MARKET_DATE_MISMATCH="
            f"kospi={kospi_actual},kosdaq={kosdaq_actual}"
        )

    return errors


def read_csv_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    encodings = ("utf-8-sig", "utf-8", "cp949")
    last_error: Optional[Exception] = None

    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                return rows, list(reader.fieldnames or [])
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise ValueError("Unable to read CSV")


def find_candidate_date(
    rows: Iterable[Dict[str, str]],
    columns: Iterable[str],
) -> Optional[str]:
    column_set = set(columns)
    date_column = next(
        (column for column in DATE_COLUMNS if column in column_set),
        None,
    )
    if date_column is None:
        return None

    values = sorted(
        {
            str(row.get(date_column) or "").strip()[:10]
            for row in rows
            if str(row.get(date_column) or "").strip()
        }
    )
    return values[-1] if values else None


def validate_csv_files(
    output_dir: Path,
    loaded: Dict[str, Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []

    reference = loaded.get("official_data_status_latest.json")
    if reference is None and loaded:
        reference = next(iter(loaded.values()))
    basis_date = (reference or {}).get("basis_date_for_display")

    for filename in REQUIRED_CSV_FILES:
        path = output_dir / filename
        if not path.exists():
            errors.append(f"MISSING_REQUIRED_CSV={filename}")
            continue

        try:
            rows, columns = read_csv_rows(path)
        except Exception as exc:
            errors.append(
                f"CSV_READ_FAIL={filename}:{type(exc).__name__}:{exc}"
            )
            continue

        if not rows:
            errors.append(f"EMPTY_REQUIRED_CSV={filename}")
            continue

        expected_rows = 30 if "candidates_30" in filename else 7
        if len(rows) != expected_rows:
            errors.append(
                f"CSV_ROW_COUNT_MISMATCH={filename}:expected={expected_rows}:actual={len(rows)}"
            )

        candidate_date = find_candidate_date(rows, columns)
        if candidate_date and basis_date and candidate_date != str(basis_date)[:10]:
            errors.append(
                f"CSV_BASIS_DATE_MISMATCH={filename}:"
                f"status={basis_date}:csv={candidate_date}"
            )

    return errors


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)

    print(f"VALIDATOR_SCRIPT={SCRIPT_VERSION}")
    print(f"VALIDATOR_OUTPUT_DIR={output_dir}")

    errors: List[str] = []

    if not output_dir.exists():
        errors.append(f"OUTPUT_DIR_MISSING={output_dir}")
    else:
        loaded, load_errors = load_status_files(output_dir)
        errors.extend(load_errors)
        errors.extend(compare_status_fields(loaded))
        errors.extend(validate_fresh_logic(loaded))
        errors.extend(validate_csv_files(output_dir, loaded))

    if errors:
        print("LATEST_SYNC_VALIDATION=FAIL")
        for error in errors:
            print(f"VALIDATION_ERROR={error}")
        return 1

    print("LATEST_SYNC_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
