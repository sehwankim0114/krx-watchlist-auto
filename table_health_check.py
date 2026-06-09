#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
주식표 전체 작동상태 통합점검표
v1.0_table_health_check

생성/갱신 파일
- latest/table_health_latest.csv
- latest/table_health_latest.json
- latest/table_health_run_log_latest.txt

점검 대상
- 관종표/분석표
- 코피표
- 코닥표
- 코급표
- 월사이클표
- 단상표
- 환율약세표
- 시장위험/버블위험
- 거시·레버리지 위험자료
- KOFIA bridge
- 공식지수 교차검증
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

SCRIPT_NAME = "table_health_check.py v1.0_table_health_check"
KST = ZoneInfo("Asia/Seoul")


TABLE_CHECKS: List[Dict[str, Any]] = [
    {
        "table_name": "관종표/분석표",
        "csv_checks": [
            {"file": "watchlist_summary_latest.csv", "min_rows": 40},
        ],
        "log_checks": [
            {
                "file": "run_log_latest.txt",
                "ok_patterns": ["status_counts={'OK'", "status_counts={\"OK\"", "summary_rows="],
                "date_keys": ["actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "코피표",
        "csv_checks": [
            {"file": "kospi_universe_summary_latest.csv", "min_rows": 800},
            {"file": "kospi_candidates_30_latest.csv", "min_rows": 30},
            {"file": "kospi_recommend_7_latest.csv", "min_rows": 7},
        ],
        "log_checks": [
            {
                "file": "universe_run_log_latest.txt",
                "ok_patterns": ["status=OK", "kospi_candidates", "kospi_recommend", "summary_rows"],
                "date_keys": ["actual_data_last_date", "universe_actual_data_last_date", "latest_actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "코닥표",
        "csv_checks": [
            {"file": "kosdaq_universe_summary_latest.csv", "min_rows": 1000},
            {"file": "kosdaq_candidates_10_latest.csv", "min_rows": 10},
            {"file": "kosdaq_recommend_5_latest.csv", "min_rows": 5},
        ],
        "log_checks": [
            {
                "file": "universe_run_log_latest.txt",
                "ok_patterns": ["status=OK", "kosdaq_candidates", "kosdaq_recommend", "summary_rows"],
                "date_keys": ["actual_data_last_date", "universe_actual_data_last_date", "latest_actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "코급표",
        "csv_checks": [
            {"file": "kospi_gainers_1m_latest.csv", "min_rows": 20},
        ],
        "log_checks": [
            {
                "file": "universe_run_log_latest.txt",
                "ok_patterns": ["status=OK", "gainers", "kospi_gainers_1m"],
                "date_keys": ["actual_data_last_date", "universe_actual_data_last_date", "latest_actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "월사이클표/사이클표/파동표",
        "csv_checks": [
            {"file": "kospi_monthly_cycle_latest.csv", "min_rows": 20},
        ],
        "log_checks": [
            {
                "file": "monthly_cycle_run_log_latest.txt",
                "ok_patterns": ["status=OK", "monthly_cycle_latest_rows", "monthly_cycle_candidates_all"],
                "date_keys": ["monthly_cycle_actual_data_last_date", "actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "단상표",
        "csv_checks": [
            {"file": "kospi_short_term_candidates_30_latest.csv", "min_rows": 30},
            {"file": "kospi_short_term_recommend_7_latest.csv", "min_rows": 7},
        ],
        "log_checks": [
            {
                "file": "kospi_short_term_run_log_latest.txt",
                "ok_patterns": ["status=OK", "short_term_candidates_rows=30", "short_term_recommend_rows=7"],
                "date_keys": ["short_term_actual_data_last_date", "actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "환율약세표",
        "csv_checks": [
            {"file": "kospi_fx_weakness_candidates_30_latest.csv", "min_rows": 30},
            {"file": "kospi_fx_weakness_recommend_7_latest.csv", "min_rows": 7},
        ],
        "log_checks": [
            {
                "file": "kospi_fx_weakness_run_log_latest.txt",
                "ok_patterns": ["status=OK", "fx_weakness_candidates_rows=30", "fx_weakness_recommend_rows=7"],
                "date_keys": ["fx_weakness_actual_data_last_date", "actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "시장위험/버블위험",
        "csv_checks": [
            {"file": "market_index_summary_latest.csv", "min_rows": 2},
            {"file": "bubble_risk_signals_latest.csv", "min_rows": 1},
        ],
        "log_checks": [
            {
                "file": "market_status_run_log_latest.txt",
                "ok_patterns": ["status=OK", "status=OK_NEW_CONFIRMED_TRADING_DAY", "bubble_risk_level="],
                "date_keys": ["actual_data_last_date"],
            }
        ],
    },
    {
        "table_name": "거시·레버리지 위험자료",
        "csv_checks": [
            {"file": "macro_leverage_history_latest.csv", "min_rows": 100},
            {"file": "macro_leverage_summary_latest.csv", "min_rows": 5},
        ],
        "log_checks": [
            {
                "file": "macro_leverage_run_log_latest.txt",
                "ok_patterns": ["macro_success_count=", "macro_summary_rows=", "final_bubble_alert_required="],
                "date_keys": [],
            }
        ],
    },
    {
        "table_name": "KOFIA bridge",
        "csv_checks": [],
        "log_checks": [
            {
                "file": "kofia_macro_bridge_run_log_latest.txt",
                "ok_patterns": ["overall_status=OK_ALL_3", "BRIDGE_OK credit", "BRIDGE_OK deposit", "BRIDGE_OK cma"],
                "date_keys": [],
            }
        ],
    },
    {
        "table_name": "공식지수 교차검증",
        "csv_checks": [],
        "log_checks": [
            {
                "file": "official_index_validation_run_log_latest.txt",
                "ok_patterns": ["overall_status=PASS_ALL", "VALIDATION KOSPI: status=PASS", "VALIDATION KOSDAQ: status=PASS"],
                "date_keys": [],
            }
        ],
    },
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def now_kst() -> datetime:
    return datetime.now(KST)


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


def normalize_date_text(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    text = text.replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    return ""


def parse_date(value: str) -> Optional[date]:
    text = normalize_date_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def extract_date_from_text(text: str, keys: Iterable[str]) -> str:
    for key in keys:
        pattern = rf"{re.escape(key)}=([0-9]{{4}}[-/]?[0-9]{{2}}[-/]?[0-9]{{2}})"
        match = re.search(pattern, text)
        if match:
            normalized = normalize_date_text(match.group(1))
            if normalized:
                return normalized
    return ""


def latest_date_from_csv(path: Path) -> str:
    if not path.exists():
        return ""

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return ""

    if df.empty:
        return ""

    for col in ["asof_date", "last_date", "date", "기준일"]:
        if col in df.columns:
            values = []
            for value in df[col].dropna().astype(str).tolist():
                parsed = parse_date(value)
                if parsed:
                    values.append(parsed)
            if values:
                return max(values).isoformat()

    return ""


def count_csv_rows(path: Path) -> Tuple[Optional[int], str]:
    if not path.exists():
        return None, "missing"

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        return int(len(df)), "ok"
    except pd.errors.EmptyDataError:
        return 0, "empty"
    except Exception as exc:
        return None, f"read_error={type(exc).__name__}: {exc}"


def severity_rank(status: str) -> int:
    order = {"OK": 0, "WARN": 1, "ERROR": 2}
    return order.get(status, 1)


def worst_status(statuses: Iterable[str]) -> str:
    result = "OK"
    for status in statuses:
        if severity_rank(status) > severity_rank(result):
            result = status
    return result


def check_freshness(date_text: str, warn_days: int, error_days: int) -> Tuple[str, str, Optional[int]]:
    parsed = parse_date(date_text)
    if not parsed:
        return "WARN", "latest_date 확인 제한", None

    today = now_kst().date()
    gap = (today - parsed).days

    if gap < 0:
        return "WARN", f"latest_date가 미래 날짜로 보임: {date_text}", gap
    if gap > error_days:
        return "ERROR", f"최신 거래일 기준 {gap}일 경과", gap
    if gap > warn_days:
        return "WARN", f"최신 거래일 기준 {gap}일 경과", gap

    return "OK", f"최신성 양호: {date_text}, {gap}일 경과", gap


def evaluate_csv_check(output_dir: Path, check: Dict[str, Any]) -> Dict[str, Any]:
    rel = check["file"]
    path = output_dir / rel

    rows, read_status = count_csv_rows(path)
    min_rows = check.get("min_rows")
    max_rows = check.get("max_rows")

    notes: List[str] = []
    status = "OK"

    if rows is None:
        status = "ERROR"
        notes.append(f"{rel}: {read_status}")
    elif read_status != "ok":
        status = "ERROR"
        notes.append(f"{rel}: {read_status}")
    else:
        notes.append(f"{rel}: rows={rows}")

        if min_rows is not None and rows < int(min_rows):
            status = "ERROR"
            notes.append(f"필요 최소 행수 {min_rows} 미만")
        if max_rows is not None and rows > int(max_rows):
            status = worst_status([status, "WARN"])
            notes.append(f"기대 최대 행수 {max_rows} 초과")

    latest_date = latest_date_from_csv(path)

    return {
        "file": rel,
        "status": status,
        "rows": rows if rows is not None else "",
        "latest_date": latest_date,
        "notes": "; ".join(notes),
    }


def evaluate_log_check(output_dir: Path, check: Dict[str, Any]) -> Dict[str, Any]:
    rel = check["file"]
    path = output_dir / rel
    text = read_text(path)

    status = "OK"
    notes: List[str] = []

    if not path.exists():
        return {
            "file": rel,
            "status": "ERROR",
            "latest_date": "",
            "notes": f"{rel}: missing",
        }

    if not text.strip():
        return {
            "file": rel,
            "status": "ERROR",
            "latest_date": "",
            "notes": f"{rel}: empty",
        }

    ok_patterns = check.get("ok_patterns", [])
    matched = [pattern for pattern in ok_patterns if pattern in text]

    if matched:
        notes.append("OK pattern: " + ", ".join(matched[:3]))
    else:
        lowered = text.lower()
        if "error" in lowered or "fail" in lowered or "traceback" in lowered:
            status = "ERROR"
            notes.append("오류/실패 문구 감지")
        else:
            status = "WARN"
            notes.append("명시적 OK pattern 확인 제한")

    latest_date = extract_date_from_text(text, check.get("date_keys", []))

    return {
        "file": rel,
        "status": status,
        "latest_date": latest_date,
        "notes": "; ".join(notes),
    }


def evaluate_table(
    output_dir: Path,
    table_check: Dict[str, Any],
    freshness_warn_days: int,
    freshness_error_days: int,
) -> Dict[str, Any]:
    table_name = table_check["table_name"]

    csv_results = [
        evaluate_csv_check(output_dir, check)
        for check in table_check.get("csv_checks", [])
    ]

    log_results = [
        evaluate_log_check(output_dir, check)
        for check in table_check.get("log_checks", [])
    ]

    statuses = [item["status"] for item in csv_results + log_results]
    if not statuses:
        statuses = ["WARN"]

    latest_dates = [
        item.get("latest_date", "")
        for item in csv_results + log_results
        if item.get("latest_date", "")
    ]

    latest_date = ""

    parsed_dates = []
    for value in latest_dates:
        parsed = parse_date(value)
        if parsed:
            parsed_dates.append(parsed)

    if parsed_dates:
        latest_date = max(parsed_dates).isoformat()

    freshness_status = "OK"
    freshness_note = "최신성 날짜 점검 대상 아님"
    freshness_days: Any = ""

    if latest_date:
        freshness_status, freshness_note, freshness_days = check_freshness(
            latest_date,
            freshness_warn_days,
            freshness_error_days,
        )

    final_status = worst_status(statuses + [freshness_status])

    csv_summary = " | ".join(
        f"{item['file']}({item['status']}, rows={item['rows']})"
        for item in csv_results
    )

    log_summary = " | ".join(
        f"{item['file']}({item['status']})"
        for item in log_results
    )

    notes = []
    for item in csv_results + log_results:
        if item.get("notes"):
            notes.append(item["notes"])
    notes.append(freshness_note)

    return {
        "checked_at_kst": now_kst().isoformat(timespec="seconds"),
        "table_name": table_name,
        "status": final_status,
        "latest_date": latest_date,
        "freshness_days": freshness_days,
        "csv_summary": csv_summary,
        "log_summary": log_summary,
        "notes": " / ".join(notes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--freshness-warn-days", type=int, default=4)
    parser.add_argument("--freshness-error-days", type=int, default=10)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    checked_at = now_kst().isoformat(timespec="seconds")

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at_kst={checked_at}",
        f"output_dir={output_dir}",
        f"freshness_warn_days={args.freshness_warn_days}",
        f"freshness_error_days={args.freshness_error_days}",
    ]

    rows = []

    for table_check in TABLE_CHECKS:
        result = evaluate_table(
            output_dir,
            table_check,
            args.freshness_warn_days,
            args.freshness_error_days,
        )
        rows.append(result)
        log_lines.append(
            f"TABLE_HEALTH {result['table_name']}: "
            f"status={result['status']}, "
            f"latest_date={result['latest_date']}, "
            f"freshness_days={result['freshness_days']}"
        )

    df = pd.DataFrame(rows)

    csv_path = output_dir / "table_health_latest.csv"
    json_path = output_dir / "table_health_latest.json"
    log_path = output_dir / "table_health_run_log_latest.txt"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    payload = {
        "script": SCRIPT_NAME,
        "checked_at_kst": checked_at,
        "overall_status": worst_status(df["status"].tolist()) if not df.empty else "WARN",
        "status_counts": df["status"].value_counts().to_dict() if not df.empty else {},
        "tables": rows,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    overall_status = payload["overall_status"]
    log_lines.append(f"table_health_rows={len(df)}")
    log_lines.append(f"status_counts={payload['status_counts']}")
    log_lines.append(f"overall_status={overall_status}")

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    if overall_status == "ERROR":
        print("TABLE_HEALTH_OVERALL_STATUS=ERROR")
    elif overall_status == "WARN":
        print("TABLE_HEALTH_OVERALL_STATUS=WARN")
    else:
        print("TABLE_HEALTH_OVERALL_STATUS=OK")


if __name__ == "__main__":
    main()
