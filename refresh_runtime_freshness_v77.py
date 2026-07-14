#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-evaluate KRX API freshness against the current KST date.

This script does not fabricate or recollect market data. It only updates the
freshness gate in api/status.json, api/manifest.json, and Korean table payloads
so an old API build cannot continue to advertise itself as latest.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

VERSION = "2026-07-14-v7.7-runtime-freshness-gate"
KST = ZoneInfo("Asia/Seoul")
CUTOFF_HOUR = 8
CUTOFF_MINUTE = 30


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_holidays(root: Path) -> set[str]:
    path = root / "config" / "krx_market_holidays.json"
    raw = read_json(path)
    values: Iterable[Any] = []
    if raw:
        for key in ("holidays", "dates", "market_holidays"):
            if isinstance(raw.get(key), list):
                values = raw[key]
                break
    else:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, list):
                values = value
        except Exception:
            values = []

    result: set[str] = set()
    for item in values:
        if isinstance(item, str):
            result.add(item[:10])
        elif isinstance(item, dict):
            day = item.get("date") or item.get("day")
            if day:
                result.add(str(day)[:10])
    return result


def is_trading_day(day: date, holidays: set[str]) -> bool:
    return day.weekday() < 5 and day.isoformat() not in holidays


def previous_trading_day(base_date: date, holidays: set[str]) -> date:
    cursor = base_date - timedelta(days=1)
    while not is_trading_day(cursor, holidays):
        cursor -= timedelta(days=1)
    return cursor


def expected_official_date(now: datetime, holidays: set[str]) -> date:
    cutoff_reached = (now.hour, now.minute) >= (CUTOFF_HOUR, CUTOFF_MINUTE)
    expected_base = now.date() if cutoff_reached else now.date() - timedelta(days=1)
    return previous_trading_day(expected_base, holidays)


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def trading_day_lag(actual: Optional[date], expected: date, holidays: set[str]) -> Optional[int]:
    if actual is None:
        return None
    if actual >= expected:
        return 0
    lag = 0
    cursor = actual + timedelta(days=1)
    while cursor <= expected:
        if is_trading_day(cursor, holidays):
            lag += 1
        cursor += timedelta(days=1)
    return lag


def select_actual_dates(status: Dict[str, Any], api_dir: Path) -> tuple[Optional[date], Optional[date]]:
    kospi = parse_date(status.get("kospi_actual_date"))
    kosdaq = parse_date(status.get("kosdaq_actual_date"))
    if kospi and kosdaq:
        return kospi, kosdaq

    for filename in ("kospi_watchlist.json", "kosdaq_watchlist.json"):
        payload = read_json(api_dir / filename)
        official = payload.get("official_data") if isinstance(payload.get("official_data"), dict) else {}
        if filename.startswith("kospi") and kospi is None:
            kospi = parse_date(official.get("kospi_actual_date"))
        if filename.startswith("kosdaq") and kosdaq is None:
            kosdaq = parse_date(official.get("kosdaq_actual_date"))
    return kospi, kosdaq


def current_price_mixed_state(status: Dict[str, Any], confirmed: Optional[date]) -> tuple[bool, Optional[str]]:
    price_dt = parse_dt(status.get("current_price_asof_kst"))
    if price_dt is None or confirmed is None:
        return False, price_dt.isoformat(timespec="seconds") if price_dt else None
    return price_dt.date() > confirmed, price_dt.isoformat(timespec="seconds")


def make_gate(
    *,
    now: datetime,
    expected: date,
    kospi: Optional[date],
    kosdaq: Optional[date],
    api_sync_ok: bool,
    holidays: set[str],
    current_price_mixed: bool,
    current_price_asof: Optional[str],
) -> Dict[str, Any]:
    same_market_date = bool(kospi and kosdaq and kospi == kosdaq)
    fresh = bool(
        same_market_date
        and kospi is not None
        and kosdaq is not None
        and kospi >= expected
        and kosdaq >= expected
    )
    safe = bool(api_sync_ok and fresh)
    confirmed = min([d for d in (kospi, kosdaq) if d is not None], default=None)
    lag = trading_day_lag(confirmed, expected, holidays)

    reasons: list[str] = []
    if not api_sync_ok:
        reasons.append("API_SYNC_NOT_OK")
    if kospi is None:
        reasons.append("KOSPI_ACTUAL_DATE_MISSING")
    if kosdaq is None:
        reasons.append("KOSDAQ_ACTUAL_DATE_MISSING")
    if kospi and kosdaq and kospi != kosdaq:
        reasons.append("KOSPI_KOSDAQ_DATE_MISMATCH")
    if kospi and kospi < expected:
        reasons.append("KOSPI_BEHIND_EXPECTED")
    if kosdaq and kosdaq < expected:
        reasons.append("KOSDAQ_BEHIND_EXPECTED")
    if current_price_mixed and not fresh:
        reasons.append("NEWER_REQUEST_PRICE_OVER_OLDER_ANALYSIS")

    if not api_sync_ok:
        status = "API_SYNC_ERROR"
        label = "API 구조 오류"
    elif fresh:
        status = "LATEST_OFFICIAL"
        label = "최신 공식자료 기준"
    elif current_price_mixed:
        status = "STALE_OFFICIAL_WITH_CURRENT_PRICE_OVERLAY"
        label = "직전 확정 공식자료 + 더 최신 현재가 혼합"
    else:
        status = "STALE_OFFICIAL"
        label = "직전 확정 공식자료 · 최신 아님"

    return {
        "version": VERSION,
        "evaluated_at_kst": now.isoformat(timespec="seconds"),
        "publication_cutoff_kst": "08:30",
        "expected_official_trading_date": expected.isoformat(),
        "kospi_actual_date": kospi.isoformat() if kospi else None,
        "kosdaq_actual_date": kosdaq.isoformat() if kosdaq else None,
        "same_market_date": same_market_date,
        "official_fresh_now": fresh,
        "api_sync_ok": api_sync_ok,
        "safe_to_analyze_as_latest": safe,
        "status": status,
        "display_label": label,
        "stale_reasons": reasons,
        "data_lag_trading_days": lag,
        "current_price_asof_kst": current_price_asof,
        "newer_current_price_over_older_analysis": bool(current_price_mixed and not fresh),
        "analysis_policy": (
            "May describe as latest official only when safe_to_analyze_as_latest=true. "
            "When false, keep the table available only as the last confirmed reference, "
            "show the stale warning, and do not present score/buy/target ranges as current."
        ),
    }


def update_official_block(block: Dict[str, Any], gate: Dict[str, Any]) -> None:
    block["computed_expected_official_trading_date"] = gate["expected_official_trading_date"]
    block["official_fresh_now"] = gate["official_fresh_now"]
    block["runtime_freshness_evaluated_at_kst"] = gate["evaluated_at_kst"]
    block["runtime_freshness_gate_version"] = VERSION
    block["data_lag_trading_days"] = gate["data_lag_trading_days"]
    block["source_display_label"] = gate["display_label"]
    block["source_warning"] = "" if gate["official_fresh_now"] else ";".join(gate["stale_reasons"])


def refresh_runtime_freshness(
    repo_root: Path,
    *,
    now: Optional[datetime] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    api_dir = root / "api"
    status_path = api_dir / "status.json"
    manifest_path = api_dir / "manifest.json"
    status_payload = read_json(status_path)
    if not status_payload:
        raise RuntimeError(f"필수 상태 파일 누락 또는 JSON 오류: {status_path}")

    now = (now or datetime.now(KST)).astimezone(KST)
    holidays = load_holidays(root)
    expected = expected_official_date(now, holidays)
    kospi, kosdaq = select_actual_dates(status_payload, api_dir)
    api_sync_ok = bool(status_payload.get("api_sync_ok"))
    confirmed = min([d for d in (kospi, kosdaq) if d is not None], default=None)
    mixed, price_asof = current_price_mixed_state(status_payload, confirmed)
    gate = make_gate(
        now=now,
        expected=expected,
        kospi=kospi,
        kosdaq=kosdaq,
        api_sync_ok=api_sync_ok,
        holidays=holidays,
        current_price_mixed=mixed,
        current_price_asof=price_asof,
    )

    if "static_official_fresh_at_api_build" not in status_payload:
        status_payload["static_official_fresh_at_api_build"] = bool(
            status_payload.get("official_fresh_now")
        )
    status_payload["runtime_freshness_gate"] = gate
    status_payload["runtime_freshness_gate_version"] = VERSION
    status_payload["runtime_freshness_evaluated_at_kst"] = gate["evaluated_at_kst"]
    status_payload["computed_expected_official_trading_date"] = gate[
        "expected_official_trading_date"
    ]
    status_payload["official_fresh_now"] = gate["official_fresh_now"]
    status_payload["safe_to_analyze_as_latest"] = gate["safe_to_analyze_as_latest"]
    status_payload["status"] = (
        "API_SYNC_ERROR"
        if not api_sync_ok
        else "READY"
        if gate["official_fresh_now"]
        else "STALE_OFFICIAL"
    )

    warnings = [
        str(item)
        for item in status_payload.get("warnings", [])
        if "RUNTIME_FRESHNESS_V77" not in str(item)
    ]
    if not gate["official_fresh_now"]:
        warnings.append(
            "RUNTIME_FRESHNESS_V77:"
            f"expected={gate['expected_official_trading_date']},"
            f"kospi={gate['kospi_actual_date']},"
            f"kosdaq={gate['kosdaq_actual_date']},"
            f"lag={gate['data_lag_trading_days']},"
            f"mixed_price={str(gate['newer_current_price_over_older_analysis']).lower()}"
        )
    status_payload["warnings"] = warnings
    status_payload["usage_rule"] = (
        "Custom GPT must call this endpoint first. Describe the dataset as latest official "
        "only when api_sync_ok=true, runtime_freshness_gate.official_fresh_now=true, "
        "and runtime_freshness_gate.safe_to_analyze_as_latest=true. When false, explicitly "
        "label it as the last confirmed official reference and warn that request-time prices "
        "may be newer than the analysis, score, buy range, and target range."
    )

    manifest_payload = read_json(manifest_path)
    if manifest_payload:
        manifest_payload["runtime_freshness_gate"] = gate
        manifest_payload["runtime_freshness_gate_version"] = VERSION
        manifest_payload["official_fresh_now"] = gate["official_fresh_now"]
        manifest_payload["safe_to_analyze_as_latest"] = gate["safe_to_analyze_as_latest"]
        manifest_payload["status"] = (
            "API_SYNC_ERROR"
            if not api_sync_ok
            else "READY"
            if gate["official_fresh_now"]
            else "STALE_OFFICIAL"
        )

    changed_tables: list[str] = []
    for path in sorted(api_dir.glob("*.json")):
        # 미국표에는 KRX 최신성 메타데이터를 추가하지 않는다.
        if path.name.startswith("us_"):
            continue
        if path.name in {
            "status.json",
            "manifest.json",
            "validation_report.json",
            "stock_table_rules.json",
            "stock_reference_manifest.json",
        }:
            continue
        payload = read_json(path)
        if not payload:
            continue
        official = payload.get("official_data")
        if not isinstance(official, dict):
            continue
        update_official_block(official, gate)
        payload["runtime_freshness_gate"] = gate
        payload["safe_to_analyze_as_latest"] = gate["safe_to_analyze_as_latest"]
        payload["analysis_latest_status"] = gate["status"]
        payload["stale_analysis_warning"] = (
            None
            if gate["official_fresh_now"]
            else (
                "분석자료 기준일이 현재 기대 공식 거래일보다 오래되었습니다. "
                "요청시점 현재가가 더 최신이어도 점수·가치매수구간·익절가는 "
                "직전 확정 분석 기준이므로 최신 투자판단으로 단정하지 마십시오."
            )
        )
        if persist:
            write_json(path, payload)
        changed_tables.append(path.name)

    if persist:
        write_json(status_path, status_payload)
        if manifest_payload:
            write_json(manifest_path, manifest_payload)

    return {
        **gate,
        "updated_table_files": changed_tables,
        "updated_table_count": len(changed_tables),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--now-kst", help="테스트용 ISO 시각")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    now = parse_dt(args.now_kst) if args.now_kst else None
    result = refresh_runtime_freshness(
        Path(args.repo_root),
        now=now,
        persist=not args.check_only,
    )
    print("RUNTIME_FRESHNESS_V77=PASS")
    print(f"EVALUATED_AT_KST={result['evaluated_at_kst']}")
    print(f"EXPECTED_OFFICIAL_DATE={result['expected_official_trading_date']}")
    print(f"KOSPI_ACTUAL_DATE={result['kospi_actual_date']}")
    print(f"KOSDAQ_ACTUAL_DATE={result['kosdaq_actual_date']}")
    print(f"OFFICIAL_FRESH_NOW={str(result['official_fresh_now']).lower()}")
    print(f"SAFE_TO_ANALYZE_AS_LATEST={str(result['safe_to_analyze_as_latest']).lower()}")
    print(f"RUNTIME_STATUS={result['status']}")
    print(f"DATA_LAG_TRADING_DAYS={result['data_lag_trading_days']}")
    print(
        "NEWER_CURRENT_PRICE_OVER_OLDER_ANALYSIS="
        f"{str(result['newer_current_price_over_older_analysis']).lower()}"
    )
    print(f"UPDATED_TABLE_COUNT={result['updated_table_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
