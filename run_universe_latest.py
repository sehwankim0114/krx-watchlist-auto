#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_universe_latest.py

KRX 공식 전종목 확정자료 수집 실행기.

핵심 원칙
- 오늘이 정상 거래일이면 전 영업일을 공식자료 기대 기준일로 사용한다.
- 주말과 config/krx_market_holidays.json의 휴장일을 제외한다.
- KOSPI와 KOSDAQ이 모두 기대 기준일까지 갱신되어야 fresh=True이다.
- 공식자료가 비거나 지연되면 기존 summary의 실제 기준일을 표시한다.
- KRX 수집은 run_collect_universe_retry.py를 우선 사용한다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_VERSION = "run_universe_latest.py v1.3_retry_holiday_sync"
HOLIDAY_FILE = Path("config/krx_market_holidays.json")


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def load_market_holidays(path: Path = HOLIDAY_FILE) -> Set[date]:
    """휴장일 JSON을 읽는다. 파일 오류 시 빈 집합으로 안전하게 fallback한다."""
    if not path.exists():
        return set()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    values: Any = raw
    if isinstance(raw, dict):
        values = (
            raw.get("holidays")
            or raw.get("dates")
            or raw.get("market_holidays")
            or []
        )

    if not isinstance(values, list):
        return set()

    holidays: Set[date] = set()
    for item in values:
        value: Any = item
        if isinstance(item, dict):
            value = item.get("date") or item.get("day")
        if not value:
            continue
        try:
            holidays.add(date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue

    return holidays


def previous_trading_day_before(
    base_date: date,
    holidays: Optional[Set[date]] = None,
) -> date:
    holidays = holidays or set()
    cursor = base_date - timedelta(days=1)

    while cursor.weekday() >= 5 or cursor in holidays:
        cursor -= timedelta(days=1)

    return cursor


def expected_official_trading_date(now_kst: datetime) -> date:
    """현재 KST 날짜를 기준으로 직전 실제 거래일을 계산한다."""
    holidays = load_market_holidays()
    return previous_trading_day_before(now_kst.date(), holidays)


def read_summary_date(path: Path) -> Tuple[Optional[date], int]:
    if not path.exists():
        return None, 0

    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype={"ticker": str})
    except Exception:
        return None, 0

    if df.empty:
        return None, 0

    date_col = next(
        (
            column
            for column in ("last_date", "date", "basDt", "trading_date")
            if column in df.columns
        ),
        None,
    )

    if date_col is None:
        return None, len(df)

    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, len(df)

    return dates.max().date(), len(df)


def build_official_status(
    output_dir: Path,
    expected: date,
) -> Dict[str, object]:
    kospi_date, kospi_rows = read_summary_date(
        output_dir / "kospi_universe_summary_latest.csv"
    )
    kosdaq_date, kosdaq_rows = read_summary_date(
        output_dir / "kosdaq_universe_summary_latest.csv"
    )

    actual_dates = [
        actual_date
        for actual_date in (kospi_date, kosdaq_date)
        if actual_date is not None
    ]
    actual_min = min(actual_dates) if actual_dates else None
    actual_max = max(actual_dates) if actual_dates else None

    kospi_fresh = kospi_date == expected
    kosdaq_fresh = kosdaq_date == expected
    fresh = bool(kospi_fresh and kosdaq_fresh)
    same_market_date = bool(
        kospi_date is not None
        and kosdaq_date is not None
        and kospi_date == kosdaq_date
    )

    if fresh:
        status = "FRESH"
        display_label = "최신 공식판"
        warning = ""
        reason = (
            "KOSPI/KOSDAQ official summaries match the expected "
            "official trading date."
        )
    elif actual_dates:
        status = "STALE_KRX_EMPTY_OR_DELAY"
        display_label = "KRX 공식자료 미확정/이전 기준일 사용"
        warning = "KRX 공식자료 미확정/이전 기준일 사용"
        reason = (
            "Official KRX summary date is behind or different from the "
            "expected trading date. Existing valid output is retained."
        )
    else:
        status = "NO_VALID_OUTPUT"
        display_label = "KRX 공식자료 없음"
        warning = "KRX 공식자료 미확정/이전 기준일 사용"
        reason = "No valid KOSPI/KOSDAQ official summary date was found."

    run_mode = os.environ.get("RUN_MODE", "official")
    final_run_mode = os.environ.get("FINAL_RUN_MODE", run_mode)

    return {
        "script": SCRIPT_VERSION,
        "run_at_kst": kst_now().isoformat(timespec="seconds"),
        "run_mode": run_mode,
        "final_run_mode": final_run_mode,
        "expected_official_trading_date": expected.isoformat(),
        "status": status,
        "official_status": status,
        "fresh": fresh,
        "official_fresh": fresh,
        "display_label": display_label,
        "warning": warning,
        "reason": reason,
        "kospi_actual_date": kospi_date.isoformat() if kospi_date else None,
        "kosdaq_actual_date": kosdaq_date.isoformat() if kosdaq_date else None,
        "actual_min_date": actual_min.isoformat() if actual_min else None,
        "actual_max_date": actual_max.isoformat() if actual_max else None,
        "same_market_date": same_market_date,
        "basis_date_for_display": actual_min.isoformat() if actual_min else None,
        "kospi_summary_rows": int(kospi_rows),
        "kosdaq_summary_rows": int(kosdaq_rows),
        "holiday_file": str(HOLIDAY_FILE),
        "holiday_file_exists": HOLIDAY_FILE.exists(),
    }


def status_to_text(status: Dict[str, object]) -> str:
    keys = (
        "script",
        "run_at_kst",
        "run_mode",
        "final_run_mode",
        "expected_official_trading_date",
        "status",
        "official_status",
        "fresh",
        "official_fresh",
        "display_label",
        "warning",
        "kospi_actual_date",
        "kosdaq_actual_date",
        "actual_min_date",
        "actual_max_date",
        "basis_date_for_display",
        "same_market_date",
        "kospi_summary_rows",
        "kosdaq_summary_rows",
        "holiday_file",
        "holiday_file_exists",
        "reason",
    )
    return "\n".join(f"{key}={status.get(key)}" for key in keys) + "\n"


def write_status_files(
    output_dir: Path,
    status: Dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
    txt_text = status_to_text(status)

    targets = {
        output_dir / "official_data_status_latest.json": json_text,
        output_dir / "krx_official_retry_status_latest.json": json_text,
        output_dir / "krx_official_retry_status_latest.txt": txt_text,
    }

    for target, content in targets.items():
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)


def append_universe_log(
    output_dir: Path,
    status: Dict[str, object],
    stage: str,
) -> None:
    log_path = output_dir / "universe_run_log_latest.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    block = [
        "",
        "----- KRX_OFFICIAL_FRESHNESS_STATUS -----",
        f"stage={stage}",
        status_to_text(status).rstrip(),
        "-----------------------------------------",
        "",
    ]

    with log_path.open("a", encoding="utf-8") as file:
        file.write("\n".join(block))


def run_collect_universe(
    days: int,
    keep_months: int,
    output_dir: Path,
) -> int:
    retry_runner = Path("run_collect_universe_retry.py")
    collector = retry_runner if retry_runner.exists() else Path("collect_universe.py")

    command = [
        sys.executable,
        str(collector),
        "--days",
        str(days),
        "--keep-months",
        str(keep_months),
        "--output-dir",
        str(output_dir),
    ]

    print("RUN:", " ".join(command), flush=True)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--keep-months", type=int, default=7)
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    now = kst_now()
    expected = expected_official_trading_date(now)

    print(f"[KST] now={now.isoformat(timespec='seconds')}", flush=True)
    print(
        f"[EXPECTED_OFFICIAL_TRADING_DATE] {expected.isoformat()}",
        flush=True,
    )

    before = build_official_status(output_dir, expected)
    write_status_files(output_dir, before)
    append_universe_log(output_dir, before, stage="before_collect")
    print(json.dumps(before, ensure_ascii=False, indent=2), flush=True)

    if before["fresh"] and not args.force:
        skipped = dict(before)
        skipped.update(
            {
                "status": "SKIPPED_ALREADY_FRESH",
                "official_status": "FRESH",
                "fresh": True,
                "official_fresh": True,
                "display_label": "최신 공식판",
                "warning": "",
                "reason": "Official previous trading day data already exists.",
                "run_at_kst": kst_now().isoformat(timespec="seconds"),
            }
        )
        write_status_files(output_dir, skipped)
        append_universe_log(output_dir, skipped, stage="skip")
        print("[SKIP] Official data is already fresh.", flush=True)
        return 0

    return_code = run_collect_universe(
        days=args.days,
        keep_months=args.keep_months,
        output_dir=output_dir,
    )

    after = build_official_status(output_dir, expected)
    after["collector_return_code"] = return_code
    after["run_at_kst"] = kst_now().isoformat(timespec="seconds")
    write_status_files(output_dir, after)
    append_universe_log(output_dir, after, stage="after_collect")
    print(json.dumps(after, ensure_ascii=False, indent=2), flush=True)

    if after.get("status") == "NO_VALID_OUTPUT" and return_code != 0:
        return return_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
