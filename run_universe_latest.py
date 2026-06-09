#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_universe_latest.py

KRX 공식 전종목 확정자료 수집 실행기

핵심 원칙
- 공식판은 KRX 공식 일별매매정보 기준이다.
- KRX 공식자료가 fresh=True일 때만 "최신 공식판"으로 표시한다.
- fresh=False이면 "KRX 공식자료 미확정/이전 기준일 사용"으로 표시한다.
- 공휴일/휴장일 가능성이 있을 때도 실제 summary 파일의 last_date를 기준일로 기록한다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "run_universe_latest.py v1.2_official_fresh_gate"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def previous_weekday_before(d: date) -> date:
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:
        cur = cur - timedelta(days=1)
    return cur


def expected_official_trading_date(now_kst: datetime) -> date:
    """
    KRX OpenAPI 공식 일별매매정보는 당일 확정자료가 아니라
    전 영업일 자료를 익일 오전에 확인하는 구조로 운용한다.

    공휴일/휴장일은 여기서 완전 판정하지 않고,
    실제 summary 파일의 last_date를 함께 기록해 표시 단계에서 확인한다.
    """
    return previous_weekday_before(now_kst.date())


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

    date_col = None
    for c in ["last_date", "date", "basDt", "trading_date"]:
        if c in df.columns:
            date_col = c
            break

    if date_col is None:
        return None, len(df)

    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, len(df)

    return dates.max().date(), len(df)


def build_official_status(output_dir: Path, expected: date) -> Dict[str, object]:
    kospi_date, kospi_rows = read_summary_date(output_dir / "kospi_universe_summary_latest.csv")
    kosdaq_date, kosdaq_rows = read_summary_date(output_dir / "kosdaq_universe_summary_latest.csv")

    actual_dates = [d for d in [kospi_date, kosdaq_date] if d is not None]
    actual_min = min(actual_dates) if actual_dates else None
    actual_max = max(actual_dates) if actual_dates else None

    kospi_fresh = kospi_date is not None and kospi_date >= expected
    kosdaq_fresh = kosdaq_date is not None and kosdaq_date >= expected
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
        reason = "KOSPI/KOSDAQ official summaries are updated to the expected official trading date."
    elif actual_dates:
        status = "STALE_KRX_EMPTY_OR_DELAY"
        display_label = "KRX 공식자료 미확정/이전 기준일 사용"
        warning = "KRX 공식자료 미확정/이전 기준일 사용"
        reason = (
            "Official KRX summary date is behind the expected previous trading day. "
            "This can happen because of KRX delay, empty response, public holiday, or market closure. "
            "Use actual summary last_date as the displayed basis date."
        )
    else:
        status = "NO_VALID_OUTPUT"
        display_label = "KRX 공식자료 없음"
        warning = "KRX 공식자료 미확정/이전 기준일 사용"
        reason = "No valid KOSPI/KOSDAQ official summary date was found."

    return {
        "script": SCRIPT_VERSION,
        "run_at_kst": kst_now().isoformat(timespec="seconds"),
        "expected_official_trading_date": expected.isoformat(),
        "status": status,
        "fresh": fresh,
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
        "holiday_or_market_closure_possible": bool(
            actual_min is not None and actual_min < expected
        ),
    }


def write_status_files(output_dir: Path, status: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "krx_official_retry_status_latest.json"
    txt_path = output_dir / "krx_official_retry_status_latest.txt"

    json_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"script={status.get('script')}",
        f"run_at_kst={status.get('run_at_kst')}",
        f"expected_official_trading_date={status.get('expected_official_trading_date')}",
        f"status={status.get('status')}",
        f"fresh={status.get('fresh')}",
        f"display_label={status.get('display_label')}",
        f"warning={status.get('warning')}",
        f"kospi_actual_date={status.get('kospi_actual_date')}",
        f"kosdaq_actual_date={status.get('kosdaq_actual_date')}",
        f"actual_min_date={status.get('actual_min_date')}",
        f"actual_max_date={status.get('actual_max_date')}",
        f"basis_date_for_display={status.get('basis_date_for_display')}",
        f"same_market_date={status.get('same_market_date')}",
        f"holiday_or_market_closure_possible={status.get('holiday_or_market_closure_possible')}",
        f"kospi_summary_rows={status.get('kospi_summary_rows')}",
        f"kosdaq_summary_rows={status.get('kosdaq_summary_rows')}",
        f"reason={status.get('reason')}",
    ]

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_universe_log(output_dir: Path, status: Dict[str, object], stage: str) -> None:
    log_path = output_dir / "universe_run_log_latest.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    block = [
        "",
        "----- KRX_OFFICIAL_FRESHNESS_STATUS -----",
        f"stage={stage}",
        f"script={status.get('script')}",
        f"run_at_kst={status.get('run_at_kst')}",
        f"expected_official_trading_date={status.get('expected_official_trading_date')}",
        f"status={status.get('status')}",
        f"fresh={status.get('fresh')}",
        f"display_label={status.get('display_label')}",
        f"warning={status.get('warning')}",
        f"kospi_actual_date={status.get('kospi_actual_date')}",
        f"kosdaq_actual_date={status.get('kosdaq_actual_date')}",
        f"basis_date_for_display={status.get('basis_date_for_display')}",
        f"same_market_date={status.get('same_market_date')}",
        f"holiday_or_market_closure_possible={status.get('holiday_or_market_closure_possible')}",
        f"reason={status.get('reason')}",
        "-----------------------------------------",
        "",
    ]

    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(block))


def run_collect_universe(days: int, keep_months: int, output_dir: Path) -> int:
    cmd = [
        sys.executable,
        "collect_universe.py",
        "--days",
        str(days),
        "--keep-months",
        str(keep_months),
        "--output-dir",
        str(output_dir),
    ]

    print("RUN:", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd)
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
    print(f"[EXPECTED_OFFICIAL_TRADING_DATE] {expected.isoformat()}", flush=True)

    before = build_official_status(output_dir, expected)
    write_status_files(output_dir, before)
    append_universe_log(output_dir, before, stage="before_collect")

    print(json.dumps(before, ensure_ascii=False, indent=2), flush=True)

    if before["fresh"] and not args.force:
        skipped = dict(before)
        skipped["status"] = "SKIPPED_ALREADY_FRESH"
        skipped["fresh"] = True
        skipped["display_label"] = "최신 공식판"
        skipped["warning"] = ""
        skipped["reason"] = "Official previous trading day data already exists. Collection skipped."
        skipped["run_at_kst"] = kst_now().isoformat(timespec="seconds")
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
