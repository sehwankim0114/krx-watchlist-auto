#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""거래활발·가격탄력·현재위치 공통 라벨 생성기."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple

import pandas as pd

SCRIPT_VERSION = "market_metric_labels_enricher.py v1.0.0-fixed-standards"
POLICY_VERSION = "2026-07-01-v6.0-market-metric-standards"
KST = timezone(timedelta(hours=9))

TRADING_COLS = ("avg20_trading_value", "avg_trading_value")
ELASTICITY_COLS = ("avg_daily_move_pct",)
ELASTICITY_TEXT_COLS = ("avg_daily_move_text",)
POSITION_1M_COLS = ("position_in_1m_range_pct",)
POSITION_3M_COLS = ("position_in_3m_range_pct",)
CURRENT_COLS = ("current_price", "current_close", "close")
LOW_1M_COLS = ("low_1m_intraday", "low_1m")
HIGH_1M_COLS = ("high_1m_intraday", "high_1m")
LOW_3M_COLS = ("low_3m_intraday", "low_3m")
HIGH_3M_COLS = ("high_3m_intraday", "high_3m")
ID_COLS = ("ticker", "code", "종목코드", "단축코드")

OUTPUT_COLS = (
    "market_metric_policy_version",
    "market_metric_label_status",
    "market_metric_missing_fields",
    "trading_activity_label",
    "trading_activity_basis_krw",
    "trading_activity_basis_text",
    "price_elasticity_label",
    "price_elasticity_basis_pct",
    "price_elasticity_basis_text",
    "current_position_label",
    "current_position_basis_pct",
    "current_position_period",
    "current_position_basis_text",
)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if text.lower() in {"", "-", "nan", "none", "null", "n/a"}:
        return None
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def first_number(
    row: Mapping[str, Any],
    columns: Iterable[str],
) -> Tuple[Optional[float], str]:
    for column in columns:
        if column in row:
            number = parse_number(row.get(column))
            if number is not None:
                return number, column
    return None, ""


def parse_pct_text(value: Any) -> Optional[float]:
    match = re.findall(r"[-+]?\d+(?:\.\d+)?\s*%", str(value or ""))
    if not match:
        return None
    try:
        return abs(float(match[-1].replace("%", "").strip()))
    except ValueError:
        return None


def trading_label(value: Optional[float]) -> str:
    if value is None or value < 0:
        return ""
    if value >= 100_000_000_000:
        return "매우활발"
    if value >= 30_000_000_000:
        return "활발"
    if value >= 5_000_000_000:
        return "보통"
    if value >= 1_000_000_000:
        return "부족"
    return "매우부족"


def elasticity_label(value: Optional[float]) -> str:
    if value is None or value < 0:
        return ""
    if value < 1.5:
        return "탄력 낮음"
    if value < 3.0:
        return "탄력 보통"
    if value < 5.0:
        return "탄력 높음"
    return "탄력 불안정"


def position_label(value: Optional[float]) -> str:
    if value is None:
        return ""
    if value <= 20:
        return "저점권"
    if value <= 35:
        return "저점권반등초입"
    if value <= 65:
        return "중간권"
    if value <= 80:
        return "중상단권"
    if value <= 92:
        return "상단권부담"
    return "고점권과열"


def calculated_position(
    current: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    if current is None or low is None or high is None or high <= low:
        return None
    return round((current - low) / (high - low) * 100, 2)


def extract_position(
    row: Mapping[str, Any],
) -> Tuple[Optional[float], str, str]:
    value, source = first_number(row, POSITION_1M_COLS)
    if value is not None:
        return value, "1개월", source

    current, current_source = first_number(row, CURRENT_COLS)
    low, low_source = first_number(row, LOW_1M_COLS)
    high, high_source = first_number(row, HIGH_1M_COLS)
    value = calculated_position(current, low, high)
    if value is not None:
        return value, "1개월", f"calculated:{current_source},{low_source},{high_source}"

    value, source = first_number(row, POSITION_3M_COLS)
    if value is not None:
        return value, "3개월", source

    low, low_source = first_number(row, LOW_3M_COLS)
    high, high_source = first_number(row, HIGH_3M_COLS)
    value = calculated_position(current, low, high)
    if value is not None:
        return value, "3개월", f"calculated:{current_source},{low_source},{high_source}"

    return None, "", ""


def labels_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    trading, trading_source = first_number(row, TRADING_COLS)

    elasticity, elasticity_source = first_number(row, ELASTICITY_COLS)
    if elasticity is None:
        for column in ELASTICITY_TEXT_COLS:
            if column in row:
                elasticity = parse_pct_text(row.get(column))
                if elasticity is not None:
                    elasticity_source = column
                    break
    if elasticity is not None:
        elasticity = abs(elasticity)

    position, period, position_source = extract_position(row)

    t_label = trading_label(trading)
    e_label = elasticity_label(elasticity)
    p_label = position_label(position)

    missing = []
    if not t_label:
        missing.append("trading_activity")
    if not e_label:
        missing.append("price_elasticity")
    if not p_label:
        missing.append("current_position")

    status = "READY" if not missing else "PARTIAL" if len(missing) < 3 else "LIMITED"

    return {
        "market_metric_policy_version": POLICY_VERSION,
        "market_metric_label_status": status,
        "market_metric_missing_fields": ",".join(missing),
        "trading_activity_label": t_label,
        "trading_activity_basis_krw": "" if trading is None else int(round(trading)),
        "trading_activity_basis_text": (
            "" if trading is None else f"최근 20거래일 평균 거래대금 ({trading_source})"
        ),
        "price_elasticity_label": e_label,
        "price_elasticity_basis_pct": (
            "" if elasticity is None else round(elasticity, 2)
        ),
        "price_elasticity_basis_text": (
            "" if elasticity is None
            else f"최근 20거래일 하루평균 절대등락률 ({elasticity_source})"
        ),
        "current_position_label": p_label,
        "current_position_basis_pct": (
            "" if position is None else round(position, 2)
        ),
        "current_position_period": period,
        "current_position_basis_text": (
            "" if not period
            else f"{period} 장중 최저~최고 대비 현재가 위치 ({position_source})"
        ),
    }


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str).fillna("")
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    raise RuntimeError(f"CSV_READ_FAILED:{path}")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def enrich_file(path: Path) -> dict[str, Any]:
    df = read_csv(path)
    result = {
        "file": path.name,
        "status": "",
        "rows": len(df),
        "ready": 0,
        "partial": 0,
        "limited": 0,
    }

    if df.empty and len(df.columns) == 0:
        result["status"] = "EMPTY"
        return result

    if not any(column in df.columns for column in ID_COLS):
        result["status"] = "NO_IDENTIFIER"
        return result

    source_cols = set(
        TRADING_COLS + ELASTICITY_COLS + ELASTICITY_TEXT_COLS
        + POSITION_1M_COLS + POSITION_3M_COLS
        + CURRENT_COLS + LOW_1M_COLS + HIGH_1M_COLS
        + LOW_3M_COLS + HIGH_3M_COLS
    )
    if not (source_cols & set(df.columns)):
        result["status"] = "NO_SOURCE"
        return result

    for column in OUTPUT_COLS:
        if column not in df.columns:
            df[column] = ""

    for index, row in df.iterrows():
        labels = labels_for_row(row.to_dict())
        for column in OUTPUT_COLS:
            df.at[index, column] = str(labels[column])
        key = labels["market_metric_label_status"].lower()
        result[key] += 1

    allowed = {
        "trading_activity_label": {
            "", "매우활발", "활발", "보통", "부족", "매우부족"
        },
        "price_elasticity_label": {
            "", "탄력 낮음", "탄력 보통", "탄력 높음", "탄력 불안정"
        },
        "current_position_label": {
            "", "저점권", "저점권반등초입", "중간권",
            "중상단권", "상단권부담", "고점권과열"
        },
    }
    for column, values in allowed.items():
        if not set(df[column]).issubset(values):
            raise RuntimeError(f"INVALID_LABEL:{path.name}:{column}")

    write_csv(df, path)
    result["status"] = "UPDATED"
    return result


def policy_payload() -> dict[str, Any]:
    return {
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": now_kst(),
        "trading_activity": {
            "basis": "최근 20거래일 평균 거래대금",
            "thresholds_krw": {
                "매우활발": ">=100000000000",
                "활발": ">=30000000000 and <100000000000",
                "보통": ">=5000000000 and <30000000000",
                "부족": ">=1000000000 and <5000000000",
                "매우부족": ">=0 and <1000000000",
            },
        },
        "price_elasticity": {
            "basis": "최근 20거래일 하루평균 절대등락률",
            "thresholds_pct": {
                "탄력 낮음": "<1.5",
                "탄력 보통": ">=1.5 and <3.0",
                "탄력 높음": ">=3.0 and <5.0",
                "탄력 불안정": ">=5.0",
            },
        },
        "current_position": {
            "formula": "(current-low)/(high-low)*100",
            "default_period": "3개월",
            "one_month_table_period": "1개월",
            "thresholds_pct": {
                "저점권": "<=20",
                "저점권반등초입": ">20 and <=35",
                "중간권": ">35 and <=65",
                "중상단권": ">65 and <=80",
                "상단권부담": ">80 and <=92",
                "고점권과열": ">92",
            },
        },
        "letter_grades_forbidden": ["A+", "A", "B", "C", "D"],
        "missing_data_policy": "추정하지 않고 PARTIAL/LIMITED",
    }


def self_test() -> int:
    checks = [
        (trading_label(100_000_000_000), "매우활발"),
        (trading_label(30_000_000_000), "활발"),
        (trading_label(5_000_000_000), "보통"),
        (trading_label(1_000_000_000), "부족"),
        (trading_label(999_999_999), "매우부족"),
        (elasticity_label(1.49), "탄력 낮음"),
        (elasticity_label(1.5), "탄력 보통"),
        (elasticity_label(3.0), "탄력 높음"),
        (elasticity_label(5.0), "탄력 불안정"),
        (position_label(20), "저점권"),
        (position_label(35), "저점권반등초입"),
        (position_label(65), "중간권"),
        (position_label(80), "중상단권"),
        (position_label(92), "상단권부담"),
        (position_label(92.01), "고점권과열"),
    ]
    for actual, expected in checks:
        assert actual == expected, (actual, expected)

    labels = labels_for_row({
        "avg20_trading_value": "120000000000",
        "avg_daily_move_pct": "3.2",
        "current_close": "150",
        "low_3m": "100",
        "high_3m": "200",
    })
    assert labels["market_metric_label_status"] == "READY"
    assert labels["trading_activity_label"] == "매우활발"
    assert labels["price_elasticity_label"] == "탄력 높음"
    assert labels["current_position_label"] == "중간권"
    assert labels["current_position_basis_pct"] == 50.0

    labels = labels_for_row({
        "avg_trading_value": "30000000000",
        "avg_daily_move_text": "약 ±500원 내외 (±1.50%)",
        "position_in_1m_range_pct": "92.01",
    })
    assert labels["current_position_period"] == "1개월"
    assert labels["current_position_label"] == "고점권과열"

    assert labels_for_row({})["market_metric_label_status"] == "LIMITED"

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED=trading_boundaries,elasticity_boundaries,"
        "position_boundaries,position_calculation,one_month_priority,"
        "missing_data_limited"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-dir", default="latest")
    parser.add_argument("--target-files", nargs="*", default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    latest = Path(args.latest_dir)
    latest.mkdir(parents=True, exist_ok=True)
    paths = (
        [latest / name for name in args.target_files]
        if args.target_files
        else sorted(latest.glob("*_latest.csv"))
    )

    results, failures = [], []
    for path in paths:
        if not path.exists():
            continue
        try:
            results.append(enrich_file(path))
        except Exception as exc:
            failures.append(f"{path.name}:{type(exc).__name__}:{exc}")

    policy_path = latest / "market_metric_standards_latest.json"
    policy_path.write_text(
        json.dumps(policy_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    updated = [r for r in results if r["status"] == "UPDATED"]
    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={now_kst()}",
        f"SCANNED_FILE_COUNT={len(results)}",
        f"UPDATED_FILE_COUNT={len(updated)}",
        f"FAILED_FILE_COUNT={len(failures)}",
        f"READY_ROW_COUNT={sum(r['ready'] for r in updated)}",
        f"PARTIAL_ROW_COUNT={sum(r['partial'] for r in updated)}",
        f"LIMITED_ROW_COUNT={sum(r['limited'] for r in updated)}",
        "TRADING_ACTIVITY_THRESHOLDS=100B/30B/5B/1B_KRW",
        "PRICE_ELASTICITY_THRESHOLDS=1.5/3.0/5.0_PERCENT",
        "CURRENT_POSITION_THRESHOLDS=20/35/65/80/92_PERCENT",
        "LETTER_GRADES_FORBIDDEN=A+,A,B,C,D",
        f"STATUS={'FAILED' if failures else 'OK'}",
        "",
        "[FILES]",
    ]
    for result in results:
        log_lines.append(
            f"FILE={result['file']}|status={result['status']}|rows={result['rows']}"
            f"|ready={result['ready']}|partial={result['partial']}"
            f"|limited={result['limited']}"
        )
    log_lines += ["", "[FAILURES]"] + (failures or ["NONE"])

    log_path = latest / "market_metric_labels_run_log_latest.txt"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(f"MARKET_METRIC_LABEL_STATUS={'FAILED' if failures else 'OK'}")
    print(f"UPDATED_FILE_COUNT={len(updated)}")
    print(f"FAILED_FILE_COUNT={len(failures)}")
    print(f"RUN_LOG={log_path}")
    print(f"POLICY_JSON={policy_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
