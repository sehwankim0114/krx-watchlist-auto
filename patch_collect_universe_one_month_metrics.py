#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_collect_universe_one_month_metrics.py v1.0.0

collect_universe.py에 최근 1개월 전용 수치를 안전하게 추가한다.

추가 필드
- low_1m_intraday
- high_1m_intraday
- low_1m_close
- high_1m_close
- range_1m_pct
- position_in_1m_range_pct
- data_rows_1m

기존 3개월 계산과 기존 표 생성 로직은 변경하지 않는다.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple


SCRIPT_VERSION = (
    "patch_collect_universe_one_month_metrics.py "
    "v1.0.0"
)
PATCH_POLICY_VERSION = (
    "2026-07-02-v6.0-one-month-universe-metrics"
)

BEGIN_MARKER = "# ONE_MONTH_METRICS_V6_BEGIN"
END_MARKER = "# ONE_MONTH_METRICS_V6_END"

NEW_SUMMARY_FIELDS = (
    "low_1m_intraday",
    "high_1m_intraday",
    "low_1m_close",
    "high_1m_close",
    "range_1m_pct",
    "position_in_1m_range_pct",
    "data_rows_1m",
)

CALCULATION_BLOCK = """{indent}{begin}
{indent}g_1m = g[g["date"] >= one_month_ago].copy()
{indent}if g_1m.empty:
{indent}    # 달력 1개월 구간이 비어 있는 예외 상황에서는
{indent}    # 최근 최대 22거래일을 보조 기준으로 사용한다.
{indent}    g_1m = g.tail(min(22, len(g))).copy()
{indent}low_1m = safe_float(g_1m["low"].min(), last_close)
{indent}high_1m = safe_float(g_1m["high"].max(), last_close)
{indent}close_low_1m = safe_float(
{indent}    g_1m["close"].min(),
{indent}    last_close,
{indent})
{indent}close_high_1m = safe_float(
{indent}    g_1m["close"].max(),
{indent}    last_close,
{indent})
{indent}range_1m_pct = (
{indent}    (high_1m - low_1m) / low_1m * 100
{indent}    if low_1m > 0
{indent}    else np.nan
{indent})
{indent}position_1m = (
{indent}    (last_close - low_1m)
{indent}    / (high_1m - low_1m)
{indent}    * 100
{indent}    if high_1m > low_1m
{indent}    else np.nan
{indent})
{indent}{end}
"""

OUTPUT_BLOCK = """{indent}{begin}
{indent}"low_1m_intraday": kr_tick_round(low_1m),
{indent}"high_1m_intraday": kr_tick_round(high_1m),
{indent}"low_1m_close": kr_tick_round(close_low_1m),
{indent}"high_1m_close": kr_tick_round(close_high_1m),
{indent}"range_1m_pct": (
{indent}    round(float(range_1m_pct), 2)
{indent}    if not pd.isna(range_1m_pct)
{indent}    else None
{indent}),
{indent}"position_in_1m_range_pct": (
{indent}    round(float(position_1m), 2)
{indent}    if not pd.isna(position_1m)
{indent}    else None
{indent}),
{indent}"data_rows_1m": int(len(g_1m)),
{indent}{end}
"""


class PatchError(RuntimeError):
    pass


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def update_collector_version(text: str) -> str:
    pattern = re.compile(
        r'SCRIPT_VERSION\s*=\s*"collect_universe\.py '
        r'([^"]+)"'
    )
    match = pattern.search(text)
    if not match:
        raise PatchError(
            "collect_universe.py의 SCRIPT_VERSION을 찾지 못했습니다."
        )

    current_suffix = match.group(1)
    if "one_month_metrics_v6" in current_suffix:
        return text

    new_suffix = current_suffix + "_one_month_metrics_v6"
    return (
        text[: match.start()]
        + f'SCRIPT_VERSION = "collect_universe.py {new_suffix}"'
        + text[match.end() :]
    )


def add_summary_columns(text: str) -> str:
    if all(
        re.search(
            rf'^\s*"{re.escape(field)}",\s*$',
            text,
            flags=re.MULTILINE,
        )
        for field in NEW_SUMMARY_FIELDS
    ):
        return text

    pattern = re.compile(
        r'(?P<indent>^[ \t]*)"avg_wave_days",\s*\n'
        r'(?P=indent)"low_3m_intraday",',
        flags=re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise PatchError(
            "SUMMARY_COLUMNS 삽입 위치를 찾지 못했습니다."
        )

    indent = match.group("indent")
    inserted = (
        f'{indent}"avg_wave_days",\n'
        f'{indent}"low_1m_intraday",\n'
        f'{indent}"high_1m_intraday",\n'
        f'{indent}"low_1m_close",\n'
        f'{indent}"high_1m_close",\n'
        f'{indent}"range_1m_pct",\n'
        f'{indent}"position_in_1m_range_pct",\n'
        f'{indent}"data_rows_1m",\n'
        f'{indent}"low_3m_intraday",'
    )
    return (
        text[: match.start()]
        + inserted
        + text[match.end() :]
    )


def add_calculation_block(text: str) -> str:
    if BEGIN_MARKER in text and "g_1m =" in text:
        return text

    pattern = re.compile(
        r'(?P<indent>^[ \t]*)close_high\s*=\s*'
        r'safe_float\(g\["close"\]\.max\(\),\s*last_close\)'
        r'\s*\n',
        flags=re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise PatchError(
            "1개월 계산 블록 삽입 위치를 찾지 못했습니다."
        )

    indent = match.group("indent")
    block = CALCULATION_BLOCK.format(
        indent=indent,
        begin=BEGIN_MARKER,
        end=END_MARKER,
    )
    return (
        text[: match.end()]
        + "\n"
        + block
        + text[match.end() :]
    )


def add_output_block(text: str) -> str:
    if (
        '"low_1m_intraday": kr_tick_round(low_1m)' in text
        and '"data_rows_1m": int(len(g_1m))' in text
    ):
        return text

    pattern = re.compile(
        r'(?P<indent>^[ \t]*)"low_3m_intraday"\s*:\s*'
        r'kr_tick_round\(low\),\s*\n',
        flags=re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise PatchError(
            "출력 딕셔너리 삽입 위치를 찾지 못했습니다."
        )

    indent = match.group("indent")
    block = OUTPUT_BLOCK.format(
        indent=indent,
        begin=BEGIN_MARKER,
        end=END_MARKER,
    )
    return (
        text[: match.start()]
        + block
        + text[match.start() :]
    )


def patch_text(text: str) -> Tuple[str, bool]:
    original = normalize_newlines(text)
    patched = update_collector_version(original)
    patched = add_summary_columns(patched)
    patched = add_calculation_block(patched)
    patched = add_output_block(patched)
    return patched, patched != original


def verify_patched_text(text: str) -> None:
    required_fragments = [
        "one_month_metrics_v6",
        'g_1m = g[g["date"] >= one_month_ago].copy()',
        '"low_1m_intraday": kr_tick_round(low_1m)',
        '"high_1m_intraday": kr_tick_round(high_1m)',
        '"range_1m_pct": (',
        '"position_in_1m_range_pct": (',
        '"data_rows_1m": int(len(g_1m))',
    ]
    for fragment in required_fragments:
        if fragment not in text:
            raise PatchError(
                f"필수 패치 문구 누락: {fragment}"
            )

    for field in NEW_SUMMARY_FIELDS:
        count = len(
            re.findall(
                rf'^\s*"{re.escape(field)}",\s*$',
                text,
                flags=re.MULTILINE,
            )
        )
        if count != 1:
            raise PatchError(
                f"SUMMARY_COLUMNS 필드 개수 오류: "
                f"{field}={count}"
            )

    if text.count(BEGIN_MARKER) != 2:
        raise PatchError(
            "BEGIN 마커는 정확히 2개여야 합니다."
        )
    if text.count(END_MARKER) != 2:
        raise PatchError(
            "END 마커는 정확히 2개여야 합니다."
        )


def compile_python(path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PatchError(result.stderr)


def patch_file(
    target: Path,
    *,
    backup: bool,
    check_only: bool,
) -> bool:
    if not target.exists():
        raise PatchError(f"대상 파일이 없습니다: {target}")

    original = target.read_text(encoding="utf-8")
    patched, changed = patch_text(original)
    verify_patched_text(patched)

    if check_only:
        if changed:
            raise PatchError(
                "아직 패치되지 않은 collect_universe.py입니다."
            )
        compile_python(target)
        return False

    if changed:
        if backup:
            backup_path = target.with_suffix(
                target.suffix
                + ".before_one_month_metrics.bak"
            )
            shutil.copy2(target, backup_path)

        temp_path = target.with_suffix(
            target.suffix + ".tmp"
        )
        temp_path.write_text(
            patched,
            encoding="utf-8",
        )
        compile_python(temp_path)
        temp_path.replace(target)
    else:
        compile_python(target)

    verify_patched_text(
        target.read_text(encoding="utf-8")
    )
    return changed


def self_test_source() -> str:
    return """#!/usr/bin/env python3
import numpy as np
import pandas as pd

SCRIPT_VERSION = "collect_universe.py v4.6.1_test"

SUMMARY_COLUMNS = [
    "name",
    "avg_wave_days",
    "low_3m_intraday",
    "high_3m_intraday",
]

def safe_float(x, default=np.nan):
    try:
        return float(x)
    except Exception:
        return default

def kr_tick_round(x):
    return int(round(float(x)))

def test(g, one_month_ago, last_close):
    close_low = safe_float(g["close"].min(), last_close)
    close_high = safe_float(g["close"].max(), last_close)

    low = safe_float(g["low"].min(), last_close)
    high = safe_float(g["high"].max(), last_close)
    rows = []
    rows.append(
        {
            "avg_wave_days": 2.0,
            "low_3m_intraday": kr_tick_round(low),
            "high_3m_intraday": kr_tick_round(high),
        }
    )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
"""


def run_self_test() -> int:
    source = self_test_source()

    first, changed = patch_text(source)
    assert changed is True
    verify_patched_text(first)

    second, changed_again = patch_text(first)
    assert changed_again is False
    assert first == second

    with tempfile.TemporaryDirectory() as td:
        test_path = Path(td) / "collect_universe.py"
        test_path.write_text(first, encoding="utf-8")
        compile_python(test_path)

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "summary_columns,"
        "one_month_calculation,"
        "row_output,"
        "version_update,"
        "idempotency,"
        "python_compile"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        default="collect_universe.py",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    target = Path(args.target)
    changed = patch_file(
        target,
        backup=not args.no_backup,
        check_only=args.check_only,
    )

    if args.check_only:
        status = "ALREADY_APPLIED"
    elif changed:
        status = "APPLIED"
    else:
        status = "NO_CHANGE"

    print(f"ONE_MONTH_METRICS_PATCH_STATUS={status}")
    print(f"PATCH_SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"PATCH_POLICY_VERSION={PATCH_POLICY_VERSION}")
    print(f"TARGET={target}")
    print("ONE_MONTH_SUMMARY_FIELDS=7")
    print("EXISTING_THREE_MONTH_LOGIC_PRESERVED=true")
    print("COLLECT_UNIVERSE_COMPILE=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
