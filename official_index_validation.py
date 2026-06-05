#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
official_index_validation.py

KRX 공식지수와 기존 전종목 시총가중 프록시 지수의 수익률을 교차검증한다.

중요
- 공식지수 종가와 프록시 종가의 절대 숫자는 기준점이 다르므로 직접 비교하지 않는다.
- 일간·1개월·3개월 수익률, 기준일, 지수명을 비교한다.
- 검증 실패 시 bubble_risk_latest.json의 자동 경고(alert_required)를 안전하게 차단한다.
- 기존 official_index_status.py와 macro_leverage_status.py는 수정하지 않는다.

입력
- latest/market_index_summary_latest.csv
- latest/bubble_risk_latest.json
- latest/data_status_latest.json

출력
- latest/official_index_validation_latest.csv
- latest/official_index_validation_latest.json
- latest/official_index_validation_run_log_latest.txt
- latest/bubble_risk_latest.json (검증 메타데이터 추가 및 실패 시 alert_required=false)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "official_index_validation.py v1.0_return_cross_validation"

EXPECTED_INDEX_NAMES = {
    "KOSPI": {"코스피", "KOSPI"},
    "KOSDAQ": {"코스닥", "KOSDAQ"},
}

THRESHOLDS = {
    "daily_gap_pctp": 2.0,
    "return_1m_gap_pctp": 5.0,
    "return_3m_gap_pctp": 10.0,
    "max_date_gap_days": 0,
}


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except Exception:
            continue
    return pd.DataFrame()


def read_json_safely(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def safe_date(value: Any) -> Optional[pd.Timestamp]:
    try:
        out = pd.to_datetime(value, errors="coerce")
        if pd.isna(out):
            return None
        return pd.Timestamp(out).normalize()
    except Exception:
        return None


def abs_gap(a: Any, b: Any) -> Optional[float]:
    av = safe_float(a)
    bv = safe_float(b)
    if av is None or bv is None:
        return None
    return round(abs(av - bv), 4)


def validate_market(row: Dict[str, Any]) -> Dict[str, Any]:
    market = str(row.get("market", "")).strip().upper()
    reasons: List[str] = []
    warnings: List[str] = []

    official_name = str(row.get("official_index_name", "")).strip()
    official_close = safe_float(row.get("official_index_close"))
    market_date = safe_date(row.get("asof_date"))
    official_date = safe_date(row.get("official_asof_date"))

    daily_gap = abs_gap(row.get("official_daily_return_pct"), row.get("proxy_daily_return_pct"))
    gap_1m = abs_gap(row.get("official_return_1m_pct"), row.get("proxy_return_1m_pct"))
    gap_3m = abs_gap(row.get("official_return_3m_pct"), row.get("proxy_return_3m_pct"))

    if official_name not in EXPECTED_INDEX_NAMES.get(market, set()):
        reasons.append(f"공식지수명 불일치: {official_name or '없음'}")

    if official_close is None or official_close <= 0:
        reasons.append("공식지수 종가가 없거나 0 이하")

    date_gap_days: Optional[int] = None
    if market_date is None or official_date is None:
        reasons.append("시장 기준일 또는 공식지수 기준일 없음")
    else:
        date_gap_days = abs((official_date - market_date).days)
        if date_gap_days > THRESHOLDS["max_date_gap_days"]:
            reasons.append(f"시장·공식지수 기준일 불일치: {date_gap_days}일")

    if daily_gap is None:
        warnings.append("일간 수익률 교차검증 불가")
    elif daily_gap > THRESHOLDS["daily_gap_pctp"]:
        reasons.append(f"일간 수익률 괴리 {daily_gap}%p")

    if gap_1m is None:
        warnings.append("1개월 수익률 교차검증 불가")
    elif gap_1m > THRESHOLDS["return_1m_gap_pctp"]:
        reasons.append(f"1개월 수익률 괴리 {gap_1m}%p")

    if gap_3m is None:
        warnings.append("3개월 수익률 교차검증 불가")
    elif gap_3m > THRESHOLDS["return_3m_gap_pctp"]:
        reasons.append(f"3개월 수익률 괴리 {gap_3m}%p")

    if reasons:
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "market": market,
        "status": status,
        "official_index_name": official_name or None,
        "market_asof_date": market_date.date().isoformat() if market_date is not None else None,
        "official_asof_date": official_date.date().isoformat() if official_date is not None else None,
        "date_gap_days": date_gap_days,
        "official_index_close": official_close,
        "proxy_index_close": safe_float(row.get("proxy_index_close")),
        "daily_return_gap_pctp": daily_gap,
        "return_1m_gap_pctp": gap_1m,
        "return_3m_gap_pctp": gap_3m,
        "risk_return_source_before_validation": row.get("risk_return_source"),
        "failure_reasons": " | ".join(reasons),
        "warnings": " | ".join(warnings),
        "note": "공식지수와 프록시 지수는 기준점이 달라 종가 절대값은 비교하지 않음",
    }


def update_bubble_risk(
    bubble: Dict[str, Any],
    overall_status: str,
    rows: List[Dict[str, Any]],
    run_at: str,
) -> Dict[str, Any]:
    out = dict(bubble)
    fail_rows = [r for r in rows if r.get("status") == "FAIL"]
    warn_rows = [r for r in rows if r.get("status") == "WARN"]

    out["official_index_validation"] = {
        "script": SCRIPT_VERSION,
        "run_at_kst": run_at,
        "overall_status": overall_status,
        "thresholds": THRESHOLDS,
        "markets": rows,
        "note": "공식지수와 프록시 지수의 종가 절대값은 비교하지 않고 수익률·기준일·지수명을 교차검증합니다.",
    }

    blocked = bool(fail_rows)
    out["official_index_validation_alert_blocked"] = blocked

    if blocked:
        out["alert_required_before_official_validation"] = bool(out.get("alert_required"))
        out["alert_required"] = False
        out["action_hint"] = (
            "공식지수 교차검증 실패로 자동 경고를 차단했습니다. "
            "공식지수명·기준일·수익률 괴리를 점검한 뒤 판단하십시오."
        )
        out["data_quality_warning"] = {
            "code": "OFFICIAL_INDEX_VALIDATION_FAIL",
            "severity": "강함",
            "markets": [r.get("market") for r in fail_rows],
            "details": [r.get("failure_reasons") for r in fail_rows],
        }
    elif warn_rows:
        out["data_quality_warning"] = {
            "code": "OFFICIAL_INDEX_VALIDATION_WARN",
            "severity": "주의",
            "markets": [r.get("market") for r in warn_rows],
            "details": [r.get("warnings") for r in warn_rows],
        }
    else:
        out.pop("data_quality_warning", None)

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    ensure_dir(outdir)
    run_at = now_kst().isoformat(timespec="seconds")

    market_summary_path = outdir / "market_index_summary_latest.csv"
    bubble_path = outdir / "bubble_risk_latest.json"

    market_summary = read_csv_safely(market_summary_path)
    bubble = read_json_safely(bubble_path)

    logs: List[str] = [
        f"script={SCRIPT_VERSION}",
        f"run_at_kst={run_at}",
    ]

    if market_summary.empty or "market" not in market_summary.columns:
        status = {
            "script": SCRIPT_VERSION,
            "run_at_kst": run_at,
            "overall_status": "NO_MARKET_SUMMARY",
            "thresholds": THRESHOLDS,
            "markets": [],
        }
        write_json(outdir / "official_index_validation_latest.json", status)
        (outdir / "official_index_validation_run_log_latest.txt").write_text(
            "\n".join(logs + ["overall_status=NO_MARKET_SUMMARY"]) + "\n",
            encoding="utf-8",
        )
        print("\n".join(logs + ["overall_status=NO_MARKET_SUMMARY"]))
        return 0

    rows: List[Dict[str, Any]] = []
    for _, row in market_summary.iterrows():
        market = str(row.get("market", "")).strip().upper()
        if market not in EXPECTED_INDEX_NAMES:
            continue
        result = validate_market(row.to_dict())
        rows.append(result)
        logs.append(
            "VALIDATION "
            f"{result['market']}: status={result['status']}, "
            f"date_gap={result['date_gap_days']}, "
            f"daily_gap={result['daily_return_gap_pctp']}, "
            f"gap_1m={result['return_1m_gap_pctp']}, "
            f"gap_3m={result['return_3m_gap_pctp']}"
        )
        if result["failure_reasons"]:
            logs.append(f"FAIL_REASON {result['market']}: {result['failure_reasons']}")
        if result["warnings"]:
            logs.append(f"WARN_REASON {result['market']}: {result['warnings']}")

    fail_count = sum(1 for r in rows if r["status"] == "FAIL")
    warn_count = sum(1 for r in rows if r["status"] == "WARN")
    pass_count = sum(1 for r in rows if r["status"] == "PASS")

    if fail_count:
        overall_status = "FAIL_ALERT_BLOCKED"
    elif warn_count:
        overall_status = "WARN"
    elif pass_count == len(EXPECTED_INDEX_NAMES):
        overall_status = "PASS_ALL"
    else:
        overall_status = "PARTIAL"

    validation = {
        "script": SCRIPT_VERSION,
        "run_at_kst": run_at,
        "overall_status": overall_status,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "thresholds": THRESHOLDS,
        "markets": rows,
        "note": "프록시 지수와 공식지수의 종가 절대값은 기준점이 달라 비교 대상이 아닙니다.",
    }

    pd.DataFrame(rows).to_csv(
        outdir / "official_index_validation_latest.csv",
        index=False,
        encoding="utf-8-sig",
    )
    write_json(outdir / "official_index_validation_latest.json", validation)

    if bubble:
        updated_bubble = update_bubble_risk(bubble, overall_status, rows, run_at)
        write_json(bubble_path, updated_bubble)
        logs.append(
            "BUBBLE_RISK_UPDATED "
            f"alert_blocked={updated_bubble.get('official_index_validation_alert_blocked')}"
        )
    else:
        logs.append("BUBBLE_RISK_NOT_UPDATED: bubble_risk_latest.json missing_or_invalid")

    logs.extend(
        [
            f"overall_status={overall_status}",
            f"pass_count={pass_count}",
            f"warn_count={warn_count}",
            f"fail_count={fail_count}",
            f"alert_blocked={bool(fail_count)}",
        ]
    )

    log_path = outdir / "official_index_validation_run_log_latest.txt"
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")
    print("\n".join(logs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
