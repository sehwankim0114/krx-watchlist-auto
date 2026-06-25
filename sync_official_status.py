#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync_official_status.py v1.0_canonical_status

두 공식 최신성 상태파일 중 run_at_kst가 가장 최근인 정상 JSON을 고른 뒤,
현재 시점의 08:30 게시 컷오프와 KRX 휴장일을 다시 적용하여
latest/official_data_status_latest.json을 단일 기준파일로 갱신한다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_VERSION = "sync_official_status.py v1.0_canonical_status"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def load_holidays(root: Path) -> set[str]:
    path = root / "config" / "krx_market_holidays.json"
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    values: Iterable[Any] = []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, dict):
        for key in ("holidays", "dates", "market_holidays"):
            if isinstance(raw.get(key), list):
                values = raw[key]
                break
    result: set[str] = set()
    for value in values:
        if isinstance(value, str):
            result.add(value[:10])
        elif isinstance(value, dict):
            day = value.get("date") or value.get("day")
            if day:
                result.add(str(day)[:10])
    return result


def previous_trading_day(base_date: date, holidays: set[str]) -> date:
    cursor = base_date - timedelta(days=1)
    while cursor.weekday() >= 5 or cursor.isoformat() in holidays:
        cursor -= timedelta(days=1)
    return cursor


def expected_date(now: datetime, holidays: set[str]) -> date:
    cutoff_reached = (now.hour, now.minute) >= (8, 30)
    base_date = now.date() if cutoff_reached else now.date() - timedelta(days=1)
    return previous_trading_day(base_date, holidays)


def choose_latest(latest: Path) -> Tuple[str, Dict[str, Any]]:
    names = (
        "official_data_status_latest.json",
        "krx_official_retry_status_latest.json",
    )
    candidates = []
    for name in names:
        data = read_json(latest / name)
        if not data:
            continue
        dt = parse_dt(data.get("run_at_kst")) or datetime.min
        candidates.append((dt, name, data))
    if not candidates:
        return "", {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, name, data = candidates[0]
    return name, data


def write_txt(path: Path, data: Dict[str, Any]) -> None:
    order = (
        "script", "synchronized_at_kst", "source_status_file", "source_run_at_kst",
        "run_mode", "final_run_mode", "expected_official_trading_date",
        "source_expected_official_trading_date", "status", "official_status",
        "fresh", "official_fresh", "display_label", "warning", "reason",
        "kospi_actual_date", "kosdaq_actual_date", "actual_min_date",
        "actual_max_date", "same_market_date", "basis_date_for_display",
        "kospi_summary_rows", "kosdaq_summary_rows", "collector_return_code",
    )
    lines = [f"{key}={data.get(key)}" for key in order]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    latest = root / args.output_dir
    latest.mkdir(parents=True, exist_ok=True)
    now = kst_now()
    source_name, source = choose_latest(latest)
    if not source:
        raise SystemExit("No valid official status JSON was found.")

    expected = expected_date(now, load_holidays(root)).isoformat()
    kospi = source.get("kospi_actual_date")
    kosdaq = source.get("kosdaq_actual_date")
    same = bool(kospi and kosdaq and kospi == kosdaq)
    fresh = bool(same and str(kospi) >= expected and str(kosdaq) >= expected)

    actual_values = [str(v) for v in (kospi, kosdaq) if v]
    actual_min = min(actual_values) if actual_values else None
    actual_max = max(actual_values) if actual_values else None

    canonical = dict(source)
    canonical.update({
        "script": SCRIPT_VERSION,
        "synchronized_at_kst": now.isoformat(timespec="seconds"),
        "source_status_file": source_name,
        "source_run_at_kst": source.get("run_at_kst"),
        "source_expected_official_trading_date": source.get(
            "expected_official_trading_date"
        ),
        "expected_official_trading_date": expected,
        "status": "FRESH" if fresh else "STALE_KRX_EMPTY_OR_DELAY",
        "official_status": "FRESH" if fresh else "STALE_KRX_EMPTY_OR_DELAY",
        "fresh": fresh,
        "official_fresh": fresh,
        "display_label": "최신 공식판" if fresh else "KRX 공식자료 미확정/이전 기준일 사용",
        "warning": "" if fresh else "KRX 공식자료 미확정/이전 기준일 사용",
        "reason": (
            "Canonical official status matches the current expected KRX trading date."
            if fresh
            else "Canonical official status is behind the current expected KRX trading date."
        ),
        "actual_min_date": actual_min,
        "actual_max_date": actual_max,
        "same_market_date": same,
        "basis_date_for_display": actual_min,
    })

    json_path = latest / "official_data_status_latest.json"
    txt_path = latest / "official_data_status_latest.txt"
    json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_txt(txt_path, canonical)

    print(f"OFFICIAL_STATUS_SOURCE={source_name}")
    print(f"SOURCE_RUN_AT_KST={source.get('run_at_kst')}")
    print(f"EXPECTED_OFFICIAL_DATE={expected}")
    print(f"KOSPI_ACTUAL_DATE={kospi}")
    print(f"KOSDAQ_ACTUAL_DATE={kosdaq}")
    print(f"OFFICIAL_FRESH={str(fresh).lower()}")
    print(f"CANONICAL_JSON={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
