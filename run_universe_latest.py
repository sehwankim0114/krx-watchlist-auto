#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_universe_latest.py

KRX 전체시장 수집 보완 실행기
- collect_universe.py를 실행한다.
- KRX 당일 데이터가 아직 비어 있으면 지정 횟수만큼 재시도한다.
- 그래도 최신 확정일이 안 잡히면 실패로 몰지 않고, 지연/빈응답 상태를 별도 파일로 남긴다.

생성/갱신 파일
- latest/krx_latest_retry_status_latest.json
- latest/krx_latest_retry_status_latest.txt
- latest/universe_run_log_latest.txt 뒤쪽에 보완 로그 추가
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "run_universe_latest.py v1.0_retry_until_latest_krx_official"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def previous_business_day(d: date) -> date:
    cur = d
    while cur.weekday() >= 5:
        cur = cur - timedelta(days=1)
    return cur


def previous_weekday_before(d: date) -> date:
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:
        cur = cur - timedelta(days=1)
    return cur


def expected_trading_date(now_kst: datetime) -> date:
    """
    기대 최신 거래일 산정.
    - 평일 15:50 전: 아직 장마감 확정 전이므로 직전 영업일을 기대값으로 본다.
    - 평일 15:50 이후: 당일을 기대값으로 본다.
    - 토/일: 직전 금요일을 기대값으로 본다.

    공휴일은 별도 달력이 없으므로, 공휴일에는 latest status에서 지연으로 표시될 수 있다.
    """
    today = now_kst.date()

    if today.weekday() >= 5:
        return previous_business_day(today)

    if now_kst.time() < time(15, 50):
        return previous_weekday_before(today)

    return today


def read_summary_date(path: Path) -> Tuple[Optional[date], int]:
    if not path.exists():
        return None, 0

    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype={"ticker": str})
    except Exception:
        return None, 0

    if df.empty or "last_date" not in df.columns:
        return None, len(df)

    dates = pd.to_datetime(df["last_date"], errors="coerce").dropna()
    if dates.empty:
        return None, len(df)

    return dates.max().date(), len(df)


def build_status(output_dir: Path, expected: date, attempt: int, attempts: int, return_code: int) -> Dict[str, object]:
    kospi_date, kospi_rows = read_summary_date(output_dir / "kospi_universe_summary_latest.csv")
    kosdaq_date, kosdaq_rows = read_summary_date(output_dir / "kosdaq_universe_summary_latest.csv")

    actual_dates = [d for d in [kospi_date, kosdaq_date] if d is not None]
    actual_min = min(actual_dates) if actual_dates else None
    actual_max = max(actual_dates) if actual_dates else None

    kospi_fresh = kospi_date is not None and kospi_date >= expected
    kosdaq_fresh = kosdaq_date is not None and kosdaq_date >= expected
    fresh = bool(kospi_fresh and kosdaq_fresh)

    if fresh:
        status = "FRESH"
        reason = "KOSPI/KOSDAQ summary files are updated to the expected latest trading date."
    elif actual_dates:
        status = "STALE_KRX_EMPTY_OR_DELAY"
        reason = (
            "KRX OpenAPI appears not to have provided complete latest trading data yet, "
            "or one market summary is still behind the expected trading date."
        )
    else:
        status = "NO_VALID_OUTPUT"
        reason = "No valid KOSPI/KOSDAQ summary date was found after collect_universe.py execution."

    return {
        "script": SCRIPT_VERSION,
        "run_at_kst": kst_now().isoformat(timespec="seconds"),
        "expected_trading_date": expected.isoformat(),
        "attempt": attempt,
        "attempts_requested": attempts,
        "collector_return_code": return_code,
        "status": status,
        "fresh": fresh,
        "reason": reason,
        "kospi_actual_date": kospi_date.isoformat() if kospi_date else None,
        "kosdaq_actual_date": kosdaq_date.isoformat() if kosdaq_date else None,
        "actual_min_date": actual_min.isoformat() if actual_min else None,
        "actual_max_date": actual_max.isoformat() if actual_max else None,
        "kospi_summary_rows": int(kospi_rows),
        "kosdaq_summary_rows": int(kosdaq_rows),
    }


def write_status_files(output_dir: Path, status: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "krx_latest_retry_status_latest.json"
    txt_path = output_dir / "krx_latest_retry_status_latest.txt"

    json_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"script={status.get('script')}",
        f"run_at_kst={status.get('run_at_kst')}",
        f"expected_trading_date={status.get('expected_trading_date')}",
        f"attempt={status.get('attempt')}/{status.get('attempts_requested')}",
        f"collector_return_code={status.get('collector_return_code')}",
        f"status={status.get('status')}",
        f"fresh={status.get('fresh')}",
        f"kospi_actual_date={status.get('kospi_actual_date')}",
        f"kosdaq_actual_date={status.get('kosdaq_actual_date')}",
        f"kospi_summary_rows={status.get('kospi_summary_rows')}",
        f"kosdaq_summary_rows={status.get('kosdaq_summary_rows')}",
        f"reason={status.get('reason')}",
    ]

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_universe_log(output_dir: Path, status: Dict[str, object]) -> None:
    log_path = output_dir / "universe_run_log_latest.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    block = [
        "",
        "----- KRX_LATEST_RETRY_STATUS -----",
        f"script={status.get('script')}",
        f"run_at_kst={status.get('run_at_kst')}",
        f"expected_trading_date={status.get('expected_trading_date')}",
        f"attempt={status.get('attempt')}/{status.get('attempts_requested')}",
        f"collector_return_code={status.get('collector_return_code')}",
        f"status={status.get('status')}",
        f"fresh={status.get('fresh')}",
        f"kospi_actual_date={status.get('kospi_actual_date')}",
        f"kosdaq_actual_date={status.get('kosdaq_actual_date')}",
        f"kospi_summary_rows={status.get('kospi_summary_rows')}",
        f"kosdaq_summary_rows={status.get('kosdaq_summary_rows')}",
        f"reason={status.get('reason')}",
        "-----------------------------------",
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
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--sleep-minutes", type=float, default=4.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_dir = Path(args.output_dir)
    now = kst_now()
    expected = expected_trading_date(now)

    print(f"[KST] now={now.isoformat(timespec='seconds')}", flush=True)
    print(f"[EXPECTED_TRADING_DATE] {expected.isoformat()}", flush=True)

    final_status: Optional[Dict[str, object]] = None
    last_return_code = 0

    for attempt in range(1, max(args.attempts, 1) + 1):
        print(f"[ATTEMPT] {attempt}/{args.attempts}", flush=True)

        last_return_code = run_collect_universe(
            days=args.days,
            keep_months=args.keep_months,
            output_dir=output_dir,
        )

        status = build_status(
            output_dir=output_dir,
            expected=expected,
            attempt=attempt,
            attempts=args.attempts,
            return_code=last_return_code,
        )

        write_status_files(output_dir, status)
        final_status = status

        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)

        if status["fresh"]:
            print("[FRESH] Latest official KRX universe data is available.", flush=True)
            break

        if attempt < args.attempts:
            sleep_seconds = max(float(args.sleep_minutes), 0.0) * 60
            print(
                f"[STALE] Latest KRX data not confirmed yet. "
                f"Retry after {sleep_seconds:.0f} seconds.",
                flush=True,
            )
            time_module.sleep(sleep_seconds)

    if final_status is None:
        final_status = build_status(
            output_dir=output_dir,
            expected=expected,
            attempt=0,
            attempts=args.attempts,
            return_code=last_return_code,
        )
        write_status_files(output_dir, final_status)

    append_universe_log(output_dir, final_status)

    # KRX 당일 빈 응답/지연은 자동화 실패가 아니라 데이터 제공 지연이므로 exit 0.
    # 단, collect_universe 자체가 계속 실패했고 출력 파일도 전혀 없으면 실패로 표시한다.
    if final_status.get("status") == "NO_VALID_OUTPUT" and last_return_code != 0:
        return last_return_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
