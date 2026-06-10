#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
KRX universe 산출물 보호 장치
v1.1_row_count_first_log_warn

목적
- KRX OpenAPI 403, empty, 행 수 급감 발생 시 축소된 최신 파일이 그대로 사용되는 것을 막는다.
- 단, 현재 산출물의 핵심 행 수가 정상 기준을 통과하면 로그의 empty/403 문구는 ERROR가 아니라 WARN으로만 기록한다.
- collect_universe/run_universe 실행 전 백업해둔 파일을 이용해 비정상 파일을 복구한다.

생성/갱신 파일
- latest/universe_output_guard_latest.txt
- latest/universe_output_guard_latest.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

SCRIPT_NAME = "universe_output_guard.py v1.1_row_count_first_log_warn"
KST = ZoneInfo("Asia/Seoul")

PROTECTED_FILES = [
    "universe_raw_history_latest.csv",
    "kospi_universe_summary_latest.csv",
    "kosdaq_universe_summary_latest.csv",
    "kospi_candidates_30_latest.csv",
    "kospi_recommend_7_latest.csv",
    "kosdaq_candidates_10_latest.csv",
    "kosdaq_recommend_5_latest.csv",
    "kospi_gainers_1m_latest.csv",
]

LOG_FILES_TO_SCAN = [
    "universe_run_log_latest.txt",
    "krx_official_retry_status_latest.txt",
]

BAD_PATTERNS = [
    "OPENAPI_HTTP_FAIL",
    "status=403",
    "Access Denied",
    "empty after normalize",
    "fresh=0",
    "KOSPI_OFFICIAL_FAILED",
    "KOSDAQ_OFFICIAL_FAILED",
    "EMPTY",
]


def now_kst() -> datetime:
    return datetime.now(KST)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


def count_rows(path: Path) -> Optional[int]:
    if not path.exists():
        return None

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        return int(len(df))
    except Exception:
        return None


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False

    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return True


def scan_bad_patterns(output_dir: Path, log_lines: List[str]) -> List[str]:
    hits: List[str] = []

    for log_name in LOG_FILES_TO_SCAN:
        text = read_text(output_dir / log_name)

        if not text:
            continue

        for pattern in BAD_PATTERNS:
            if pattern in text:
                hit = f"{log_name}:{pattern}"
                hits.append(hit)

    for hit in hits[:50]:
        log_lines.append(f"LOG_WARN_PATTERN_HIT {hit}")

    if len(hits) > 50:
        log_lines.append(f"LOG_WARN_PATTERN_HIT_MORE count={len(hits) - 50}")

    return hits


def validate_current_outputs(
    output_dir: Path,
    kospi_min_rows: int,
    kosdaq_min_rows: int,
    gainers_min_rows: int,
    log_lines: List[str],
) -> Dict[str, Any]:
    row_counts = {
        "kospi_universe_summary_latest.csv": count_rows(output_dir / "kospi_universe_summary_latest.csv"),
        "kosdaq_universe_summary_latest.csv": count_rows(output_dir / "kosdaq_universe_summary_latest.csv"),
        "kospi_gainers_1m_latest.csv": count_rows(output_dir / "kospi_gainers_1m_latest.csv"),
        "kospi_candidates_30_latest.csv": count_rows(output_dir / "kospi_candidates_30_latest.csv"),
        "kospi_recommend_7_latest.csv": count_rows(output_dir / "kospi_recommend_7_latest.csv"),
        "kosdaq_candidates_10_latest.csv": count_rows(output_dir / "kosdaq_candidates_10_latest.csv"),
        "kosdaq_recommend_5_latest.csv": count_rows(output_dir / "kosdaq_recommend_5_latest.csv"),
    }

    for name, rows in row_counts.items():
        log_lines.append(f"CURRENT_ROWS {name}: {rows}")

    row_failures: List[str] = []

    kospi_rows = row_counts["kospi_universe_summary_latest.csv"]
    kosdaq_rows = row_counts["kosdaq_universe_summary_latest.csv"]
    gainers_rows = row_counts["kospi_gainers_1m_latest.csv"]
    kospi_candidates_rows = row_counts["kospi_candidates_30_latest.csv"]
    kospi_recommend_rows = row_counts["kospi_recommend_7_latest.csv"]
    kosdaq_candidates_rows = row_counts["kosdaq_candidates_10_latest.csv"]
    kosdaq_recommend_rows = row_counts["kosdaq_recommend_5_latest.csv"]

    if kospi_rows is None:
        row_failures.append("KOSPI summary missing_or_unreadable")
    elif kospi_rows < kospi_min_rows:
        row_failures.append(f"KOSPI summary rows too low: {kospi_rows} < {kospi_min_rows}")

    if kosdaq_rows is None:
        row_failures.append("KOSDAQ summary missing_or_unreadable")
    elif kosdaq_rows < kosdaq_min_rows:
        row_failures.append(f"KOSDAQ summary rows too low: {kosdaq_rows} < {kosdaq_min_rows}")

    if gainers_rows is None:
        row_failures.append("KOSPI gainers missing_or_unreadable")
    elif gainers_rows < gainers_min_rows:
        row_failures.append(f"KOSPI gainers rows too low: {gainers_rows} < {gainers_min_rows}")

    if kospi_candidates_rows is None or kospi_candidates_rows < 30:
        row_failures.append(f"KOSPI candidates rows invalid: {kospi_candidates_rows}")

    if kospi_recommend_rows is None or kospi_recommend_rows < 7:
        row_failures.append(f"KOSPI recommend rows invalid: {kospi_recommend_rows}")

    if kosdaq_candidates_rows is None or kosdaq_candidates_rows < 10:
        row_failures.append(f"KOSDAQ candidates rows invalid: {kosdaq_candidates_rows}")

    if kosdaq_recommend_rows is None or kosdaq_recommend_rows < 5:
        row_failures.append(f"KOSDAQ recommend rows invalid: {kosdaq_recommend_rows}")

    log_warn_hits = scan_bad_patterns(output_dir, log_lines)

    rows_valid = len(row_failures) == 0

    return {
        "rows_valid": rows_valid,
        "is_valid": rows_valid,
        "row_counts": row_counts,
        "row_failures": row_failures,
        "log_warn_hits": log_warn_hits,
        "log_warn_hit_count": len(log_warn_hits),
    }


def validate_backup(
    backup_dir: Path,
    kospi_min_rows: int,
    kosdaq_min_rows: int,
    gainers_min_rows: int,
    log_lines: List[str],
) -> Dict[str, Any]:
    row_counts = {
        "kospi_universe_summary_latest.csv": count_rows(backup_dir / "kospi_universe_summary_latest.csv"),
        "kosdaq_universe_summary_latest.csv": count_rows(backup_dir / "kosdaq_universe_summary_latest.csv"),
        "kospi_gainers_1m_latest.csv": count_rows(backup_dir / "kospi_gainers_1m_latest.csv"),
        "kospi_candidates_30_latest.csv": count_rows(backup_dir / "kospi_candidates_30_latest.csv"),
        "kospi_recommend_7_latest.csv": count_rows(backup_dir / "kospi_recommend_7_latest.csv"),
        "kosdaq_candidates_10_latest.csv": count_rows(backup_dir / "kosdaq_candidates_10_latest.csv"),
        "kosdaq_recommend_5_latest.csv": count_rows(backup_dir / "kosdaq_recommend_5_latest.csv"),
    }

    for name, rows in row_counts.items():
        log_lines.append(f"BACKUP_ROWS {name}: {rows}")

    failures: List[str] = []

    kospi_rows = row_counts["kospi_universe_summary_latest.csv"]
    kosdaq_rows = row_counts["kosdaq_universe_summary_latest.csv"]
    gainers_rows = row_counts["kospi_gainers_1m_latest.csv"]
    kospi_candidates_rows = row_counts["kospi_candidates_30_latest.csv"]
    kospi_recommend_rows = row_counts["kospi_recommend_7_latest.csv"]
    kosdaq_candidates_rows = row_counts["kosdaq_candidates_10_latest.csv"]
    kosdaq_recommend_rows = row_counts["kosdaq_recommend_5_latest.csv"]

    if kospi_rows is None or kospi_rows < kospi_min_rows:
        failures.append(f"backup KOSPI invalid: {kospi_rows}")

    if kosdaq_rows is None or kosdaq_rows < kosdaq_min_rows:
        failures.append(f"backup KOSDAQ invalid: {kosdaq_rows}")

    if gainers_rows is None or gainers_rows < gainers_min_rows:
        failures.append(f"backup gainers invalid: {gainers_rows}")

    if kospi_candidates_rows is None or kospi_candidates_rows < 30:
        failures.append(f"backup KOSPI candidates invalid: {kospi_candidates_rows}")

    if kospi_recommend_rows is None or kospi_recommend_rows < 7:
        failures.append(f"backup KOSPI recommend invalid: {kospi_recommend_rows}")

    if kosdaq_candidates_rows is None or kosdaq_candidates_rows < 10:
        failures.append(f"backup KOSDAQ candidates invalid: {kosdaq_candidates_rows}")

    if kosdaq_recommend_rows is None or kosdaq_recommend_rows < 5:
        failures.append(f"backup KOSDAQ recommend invalid: {kosdaq_recommend_rows}")

    return {
        "is_valid": len(failures) == 0,
        "failures": failures,
        "row_counts": row_counts,
    }


def restore_from_backup(output_dir: Path, backup_dir: Path, log_lines: List[str]) -> Dict[str, Any]:
    restored: List[str] = []
    missing: List[str] = []

    for filename in PROTECTED_FILES:
        src = backup_dir / filename
        dst = output_dir / filename

        if copy_file(src, dst):
            restored.append(filename)
            log_lines.append(f"RESTORE_FILE {filename}: OK")
        else:
            missing.append(filename)
            log_lines.append(f"RESTORE_FILE {filename}: MISSING_BACKUP")

    return {
        "restored": restored,
        "missing": missing,
    }


def write_outputs(output_dir: Path, log_lines: List[str], payload: Dict[str, Any]) -> None:
    log_path = output_dir / "universe_output_guard_latest.txt"
    json_path = output_dir / "universe_output_guard_latest.json"

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--backup-dir", default="/tmp/latest_universe_backup")
    parser.add_argument("--kospi-min-rows", type=int, default=800)
    parser.add_argument("--kosdaq-min-rows", type=int, default=1500)
    parser.add_argument("--gainers-min-rows", type=int, default=15)
    parser.add_argument("--restore-on-fail", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    backup_dir = Path(args.backup_dir)
    ensure_dir(output_dir)

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at_kst={now_kst().isoformat(timespec='seconds')}",
        f"output_dir={output_dir}",
        f"backup_dir={backup_dir}",
        f"kospi_min_rows={args.kospi_min_rows}",
        f"kosdaq_min_rows={args.kosdaq_min_rows}",
        f"gainers_min_rows={args.gainers_min_rows}",
        f"restore_on_fail={args.restore_on_fail}",
        "decision_rule=row_count_first_log_patterns_are_warn_only_when_rows_valid",
    ]

    current = validate_current_outputs(
        output_dir,
        args.kospi_min_rows,
        args.kosdaq_min_rows,
        args.gainers_min_rows,
        log_lines,
    )

    action = "ACCEPT_CURRENT"
    restore_result: Dict[str, Any] = {"restored": [], "missing": []}
    backup_status: Dict[str, Any] = {}

    if current["rows_valid"]:
        if current["log_warn_hit_count"] > 0:
            status = "OK_WITH_LOG_WARN"
            log_lines.append("guard_decision=ACCEPT_CURRENT_WITH_LOG_WARN")
            log_lines.append(
                f"log_warn_hit_count={current['log_warn_hit_count']}"
            )
        else:
            status = "OK"
            log_lines.append("guard_decision=ACCEPT_CURRENT")

        action = "ACCEPT_CURRENT"

    else:
        status = "CURRENT_INVALID"
        action = "CURRENT_INVALID"
        log_lines.append("guard_decision=CURRENT_INVALID")

        for failure in current["row_failures"]:
            log_lines.append(f"CURRENT_FAILURE {failure}")

        if args.restore_on_fail:
            backup_status = validate_backup(
                backup_dir,
                args.kospi_min_rows,
                args.kosdaq_min_rows,
                args.gainers_min_rows,
                log_lines,
            )

            if backup_status.get("is_valid"):
                restore_result = restore_from_backup(output_dir, backup_dir, log_lines)
                action = "RESTORED_FROM_BACKUP"
                status = "RESTORED_FROM_BACKUP"
                log_lines.append("guard_decision=RESTORED_FROM_BACKUP")
            else:
                action = "BACKUP_INVALID_KEEP_CURRENT"
                status = "ERROR_BACKUP_INVALID"
                log_lines.append("guard_decision=BACKUP_INVALID_KEEP_CURRENT")

                for failure in backup_status.get("failures", []):
                    log_lines.append(f"BACKUP_FAILURE {failure}")
        else:
            action = "KEEP_CURRENT_RESTORE_DISABLED"
            status = "ERROR_RESTORE_DISABLED"
            log_lines.append("guard_decision=KEEP_CURRENT_RESTORE_DISABLED")

    payload = {
        "script": SCRIPT_NAME,
        "run_at_kst": now_kst().isoformat(timespec="seconds"),
        "status": status,
        "action": action,
        "current": current,
        "backup_status": backup_status,
        "restore_result": restore_result,
    }

    log_lines.append(f"status={status}")
    log_lines.append(f"action={action}")

    write_outputs(output_dir, log_lines, payload)

    print(f"UNIVERSE_OUTPUT_GUARD_STATUS={status}")
    print(f"UNIVERSE_OUTPUT_GUARD_ACTION={action}")


if __name__ == "__main__":
    main()
