#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
supply_burden_enricher.py v2.0.0-check-status-separated

목적
- 실제 수급부담 탐지 결과와 DART 조회상태를 완전히 분리한다.
- CHECK_LIMITED를 supply_burden_flag에 저장하지 않는다.
- 조회범위가 제한되어도 실제 공시가 발견되면 부담 여부는 별도로 표시한다.
- 기존 표 및 API와의 호환을 위해 supply_burden_flag는 TRUE/FALSE만 유지한다.

핵심 필드
- supply_check_status: OK / LIMITED / FAILED
- supply_check_scope: 조회 범위 설명
- supply_check_limited_reason: 제한 또는 실패 사유
- supply_burden_detected: TRUE / FALSE
- supply_burden_flag: TRUE / FALSE (기존 호환 필드)
- supply_burden_level: 없음 / 주의 / 경계 / 위험

중요 원칙
- CHECK_LIMITED는 실제 수급부담이 아니다.
- 조회 제한만으로 종목명 오른쪽에 언더바(_)를 붙이지 않는다.
- 실제 부담 공시가 확인된 경우에만 supply_burden_detected=TRUE로 저장한다.
- 조회 실패 시에도 부담을 임의로 FALSE라고 단정하지 않고 check_status로 제한을 알린다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_NAME = (
    "supply_burden_enricher.py "
    "v2.0.0-check-status-separated"
)
POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"

DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS = 90

BASE_TARGET_FILES = [
    "watchlist_summary_latest.csv",
    "kospi_candidates_30_latest.csv",
    "kospi_recommend_7_latest.csv",
    "kosdaq_candidates_10_latest.csv",
    "kosdaq_recommend_5_latest.csv",
    "kospi_gainers_1m_latest.csv",
    "kospi_short_term_candidates_30_latest.csv",
    "kospi_short_term_recommend_7_latest.csv",
    "kospi_fx_weakness_candidates_30_latest.csv",
    "kospi_fx_weakness_recommend_7_latest.csv",
    "kospi_monthly_cycle_latest.csv",
    "kospi_universe_summary_latest.csv",
    "kosdaq_universe_summary_latest.csv",
]

VARIANT_SUFFIXES = (
    "",
    "_current_basis",
    "_supplemented",
)

CODE_COLUMNS = [
    "ticker",
    "code",
    "종목코드",
    "단축코드",
    "stock_code",
    "isuCd",
    "isu_cd",
    "symbol",
]

NAME_COLUMNS = [
    "name",
    "corp_name",
    "종목명",
    "company",
    "회사명",
]

SUPPLY_COLUMNS = [
    "supply_check_status",
    "supply_check_scope",
    "supply_check_limited_reason",
    "supply_burden_detected",
    "supply_burden_flag",
    "supply_burden_level",
    "supply_burden_keywords",
    "supply_burden_latest_report_date",
    "supply_burden_latest_report_name",
    "supply_burden_report_count",
    "supply_burden_checked_at_kst",
]

# severity: 3 위험, 2 경계, 1 주의
KEYWORD_RULES: List[Tuple[str, str, int]] = [
    ("유상증자", "유상증자", 3),
    ("전환청구권행사", "전환청구", 3),
    ("전환청구", "전환청구", 3),
    ("신주인수권행사", "신주인수권행사", 3),
    ("신주인수권", "신주인수권", 2),
    ("교환청구권행사", "교환청구", 3),
    ("전환사채권발행결정", "CB발행", 2),
    ("전환사채", "CB", 2),
    ("신주인수권부사채권발행결정", "BW발행", 2),
    ("신주인수권부사채", "BW", 2),
    ("교환사채권발행결정", "EB발행", 2),
    ("교환사채", "EB", 2),
    ("자기주식처분결정", "자사주처분", 2),
    ("자기주식처분", "자사주처분", 2),
    ("자기주식 처분", "자사주처분", 2),
    ("보호예수", "보호예수", 2),
    ("의무보유", "의무보유", 2),
    ("의무보유등록", "의무보유", 2),
    ("블록딜", "블록딜", 2),
    ("시간외매매", "블록딜/시간외매매", 2),
    ("대량보유", "대량보유", 1),
    ("주식등의대량보유상황보고서", "대량보유", 1),
    (
        "임원ㆍ주요주주특정증권등소유상황보고서",
        "주요주주변동",
        1,
    ),
    (
        "임원·주요주주특정증권등소유상황보고서",
        "주요주주변동",
        1,
    ),
    ("최대주주 변경", "최대주주변경", 2),
    ("최대주주변경", "최대주주변경", 2),
    ("감자", "감자", 3),
    ("상장폐지", "상장폐지위험", 3),
    ("관리종목", "관리종목", 2),
    ("투자경고", "투자경고", 2),
    ("투자위험", "투자위험", 3),
]

RELIEF_KEYWORDS = [
    "자기주식취득결정",
    "자기주식 취득",
    "자기주식취득 신탁계약",
    "자기주식취득신탁계약",
]


def now_kst() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def now_kst_text() -> str:
    return now_kst().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_code(value: object) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {
        "nan",
        "none",
        "null",
    }:
        return None

    if text.endswith(".0"):
        text = text[:-2]

    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 6 and digits != "000000":
        return digits
    if 0 < len(digits) < 6:
        code = digits.zfill(6)
        return code if code != "000000" else None
    return None


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(
                path,
                encoding=encoding,
                dtype=str,
            ).fillna("")
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        except Exception:
            continue

    return pd.DataFrame()


def write_csv_atomically(
    df: pd.DataFrame,
    path: Path,
) -> None:
    ensure_dir(path.parent)

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(handle)
    temporary_path = Path(temporary_name)

    try:
        df.to_csv(
            temporary_path,
            index=False,
            encoding="utf-8-sig",
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def find_col(
    df: pd.DataFrame,
    candidates: Iterable[str],
) -> Optional[str]:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def generate_target_files() -> List[str]:
    filenames = set(BASE_TARGET_FILES)

    for base in BASE_TARGET_FILES:
        if not base.endswith("_latest.csv"):
            continue

        stem = base[: -len("_latest.csv")]
        for suffix in VARIANT_SUFFIXES:
            if not suffix:
                continue
            filenames.add(
                f"{stem}{suffix}_latest.csv"
            )

    return sorted(filenames)


def effective_whole_market_lookback_days(
    requested_days: int,
    max_days: int = DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS,
) -> int:
    try:
        requested = int(requested_days)
    except Exception:
        requested = max_days

    try:
        maximum = int(max_days)
    except Exception:
        maximum = DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS

    requested = max(1, requested)
    maximum = max(1, maximum)
    return min(requested, maximum)


def collect_target_tickers(
    output_dir: Path,
    target_files: Sequence[str],
) -> Tuple[
    Dict[str, str],
    Dict[str, List[str]],
    Dict[str, int],
]:
    name_map: Dict[str, str] = {}
    file_map: Dict[str, List[str]] = defaultdict(list)
    file_rows: Dict[str, int] = {}

    for filename in target_files:
        path = output_dir / filename
        df = read_csv_safe(path)
        file_rows[filename] = int(len(df)) if not df.empty else 0

        if df.empty:
            continue

        code_column = find_col(df, CODE_COLUMNS)
        name_column = find_col(df, NAME_COLUMNS)
        if code_column is None:
            continue

        for _, row in df.iterrows():
            code = normalize_code(row.get(code_column, ""))
            if not code:
                continue

            file_map[code].append(filename)

            if name_column:
                name = str(
                    row.get(name_column, "")
                ).strip()
                if name and code not in name_map:
                    name_map[code] = name

    return name_map, dict(file_map), file_rows


def dart_get_json(
    params: Dict[str, Any],
    timeout: int = 25,
) -> Dict[str, Any]:
    url = (
        "https://opendart.fss.or.kr/api/list.json?"
        + urllib.parse.urlencode(params)
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        data = response.read().decode(
            "utf-8",
            errors="replace",
        )
    return json.loads(data)


def classify_report(
    report_name: str,
) -> Tuple[bool, List[str], int, bool]:
    title = str(report_name or "")
    matched: List[str] = []
    severity = 0

    for keyword, label, level in KEYWORD_RULES:
        if keyword in title:
            matched.append(label)
            severity = max(severity, level)

    relief = any(
        keyword in title
        for keyword in RELIEF_KEYWORDS
    )

    return (
        bool(matched),
        sorted(set(matched)),
        severity,
        relief,
    )


def severity_to_level(
    severity: int,
    count: int,
) -> str:
    if severity >= 3:
        return "위험"
    if severity == 2:
        return "위험" if count >= 3 else "경계"
    if severity == 1:
        return "경계" if count >= 3 else "주의"
    return "없음"


def fetch_dart_reports(
    *,
    api_key: str,
    target_codes: set[str],
    lookback_days: int,
    max_pages: int,
    sleep_seconds: float,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    end_date = now_kst().date()
    begin_date = end_date - timedelta(
        days=lookback_days
    )

    status: Dict[str, Any] = {
        "bgn_de": begin_date.strftime("%Y%m%d"),
        "end_de": end_date.strftime("%Y%m%d"),
        "lookback_days": lookback_days,
        "corp_cls": {},
        "api_calls": 0,
        "api_errors": [],
    }

    hits: List[Dict[str, Any]] = []

    for corp_class in ("Y", "K"):
        page_number = 1
        total_pages: Optional[int] = None

        class_status = {
            "pages_requested": 0,
            "total_page": None,
            "raw_reports": 0,
            "target_reports": 0,
            "matched_reports": 0,
        }

        while page_number <= max_pages:
            params = {
                "crtfc_key": api_key,
                "bgn_de": status["bgn_de"],
                "end_de": status["end_de"],
                "corp_cls": corp_class,
                "page_no": page_number,
                "page_count": 100,
            }

            try:
                payload = dart_get_json(
                    params,
                    timeout=timeout,
                )
                status["api_calls"] += 1
                class_status["pages_requested"] += 1
            except Exception as exc:
                status["api_errors"].append(
                    "corp_cls="
                    f"{corp_class},page={page_number},"
                    f"error={type(exc).__name__}:{exc}"
                )
                break

            dart_status = str(
                payload.get("status", "")
            )
            message = str(
                payload.get("message", "")
            )

            if dart_status == "013":
                break

            if dart_status != "000":
                status["api_errors"].append(
                    "corp_cls="
                    f"{corp_class},page={page_number},"
                    f"dart_status={dart_status},"
                    f"message={message}"
                )
                break

            try:
                total_pages = int(
                    payload.get("total_page", 1)
                )
            except Exception:
                total_pages = 1

            class_status["total_page"] = total_pages

            reports = payload.get("list", []) or []
            class_status["raw_reports"] += len(reports)

            for item in reports:
                stock_code = normalize_code(
                    item.get("stock_code", "")
                )
                if (
                    not stock_code
                    or stock_code not in target_codes
                ):
                    continue

                class_status["target_reports"] += 1

                report_name = str(
                    item.get("report_nm", "")
                )
                (
                    is_risk,
                    labels,
                    severity,
                    relief,
                ) = classify_report(report_name)

                if not is_risk:
                    continue

                class_status["matched_reports"] += 1
                hits.append(
                    {
                        "stock_code": stock_code,
                        "corp_name": str(
                            item.get("corp_name", "")
                        ),
                        "report_name": report_name,
                        "rcept_dt": str(
                            item.get("rcept_dt", "")
                        ),
                        "rcept_no": str(
                            item.get("rcept_no", "")
                        ),
                        "corp_cls": corp_class,
                        "keywords": ",".join(labels),
                        "severity": severity,
                        "relief_flag": relief,
                    }
                )

            if (
                total_pages is not None
                and page_number >= total_pages
            ):
                break

            page_number += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        status["corp_cls"][corp_class] = class_status

    return hits, status


def determine_check_state(
    *,
    api_key_present: bool,
    target_codes_present: bool,
    requested_days: int,
    effective_days: int,
    api_errors: Sequence[str],
) -> Tuple[str, str, str]:
    """
    반환:
    - status: OK / LIMITED / FAILED
    - scope
    - reason
    """
    scope = f"DART 최근 {effective_days}일 공시 제목 기준"

    if not api_key_present:
        return (
            "FAILED",
            scope,
            "NO_DART_API_KEY",
        )

    if not target_codes_present:
        return (
            "FAILED",
            scope,
            "NO_TARGET_TICKERS",
        )

    reasons: List[str] = []

    if effective_days < requested_days:
        reasons.append(
            "DART_WHOLE_MARKET_LOOKBACK_CAPPED_"
            f"{effective_days}D_FROM_{requested_days}D"
        )

    if api_errors:
        reasons.append(
            "DART_PARTIAL_ERROR_COUNT_"
            f"{len(api_errors)}"
        )

    if reasons:
        return (
            "LIMITED",
            scope,
            ";".join(reasons),
        )

    return "OK", scope, ""


def build_summary(
    *,
    target_codes: Sequence[str],
    name_map: Dict[str, str],
    file_map: Dict[str, List[str]],
    hits: Sequence[Dict[str, Any]],
    checked_at: str,
    check_status: str,
    check_scope: str,
    limited_reason: str,
) -> pd.DataFrame:
    hits_by_code: Dict[
        str,
        List[Dict[str, Any]],
    ] = defaultdict(list)

    for hit in hits:
        code = normalize_code(
            hit.get("stock_code", "")
        )
        if code:
            hits_by_code[code].append(dict(hit))

    rows: List[Dict[str, Any]] = []

    for code in sorted(target_codes):
        code_hits = sorted(
            hits_by_code.get(code, []),
            key=lambda item: str(
                item.get("rcept_dt", "")
            ),
            reverse=True,
        )

        report_count = len(code_hits)
        maximum_severity = max(
            [
                int(
                    item.get("severity", 0)
                    or 0
                )
                for item in code_hits
            ],
            default=0,
        )

        detected = report_count > 0
        level = severity_to_level(
            maximum_severity,
            report_count,
        )

        keywords = sorted(
            {
                label.strip()
                for item in code_hits
                for label in str(
                    item.get("keywords", "")
                ).split(",")
                if label.strip()
            }
        )

        latest = code_hits[0] if code_hits else {}

        rows.append(
            {
                "ticker": code,
                "name": name_map.get(code, ""),
                "supply_check_status": check_status,
                "supply_check_scope": check_scope,
                "supply_check_limited_reason": (
                    limited_reason
                ),
                "supply_burden_detected": (
                    "TRUE" if detected else "FALSE"
                ),
                # 기존 호환 필드도 TRUE/FALSE만 허용한다.
                "supply_burden_flag": (
                    "TRUE" if detected else "FALSE"
                ),
                "supply_burden_level": level,
                "supply_burden_keywords": (
                    ",".join(keywords)
                ),
                "supply_burden_latest_report_date": str(
                    latest.get("rcept_dt", "")
                ),
                "supply_burden_latest_report_name": str(
                    latest.get("report_name", "")
                ),
                "supply_burden_report_count": (
                    report_count
                ),
                "source_files": ",".join(
                    sorted(
                        set(file_map.get(code, []))
                    )
                ),
                "supply_burden_checked_at_kst": (
                    checked_at
                ),
            }
        )

    return pd.DataFrame(rows)


def enrich_file(
    *,
    output_dir: Path,
    filename: str,
    summary_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    path = output_dir / filename
    df = read_csv_safe(path)

    result: Dict[str, Any] = {
        "file": filename,
        "status": "UNKNOWN",
        "rows": 0,
        "matched_rows": 0,
        "burden_detected_rows": 0,
        "check_limited_rows": 0,
        "check_failed_rows": 0,
        "note": "",
    }

    if df.empty:
        result.update(
            {
                "status": "EMPTY_OR_MISSING",
                "note": "file missing or empty",
            }
        )
        return result

    code_column = find_col(df, CODE_COLUMNS)
    if code_column is None:
        result.update(
            {
                "status": "NO_CODE_COLUMN",
                "rows": len(df),
            }
        )
        return result

    output = df.copy()

    for column in SUPPLY_COLUMNS:
        if column not in output.columns:
            output[column] = ""

    matched = 0
    burden_detected = 0
    limited = 0
    failed = 0

    for index, row in output.iterrows():
        code = normalize_code(
            row.get(code_column, "")
        )
        if not code:
            continue

        info = summary_map.get(code)
        if not info:
            continue

        matched += 1

        if str(
            info.get(
                "supply_burden_detected",
                "",
            )
        ) == "TRUE":
            burden_detected += 1

        check_status = str(
            info.get("supply_check_status", "")
        )
        if check_status == "LIMITED":
            limited += 1
        elif check_status == "FAILED":
            failed += 1

        for column in SUPPLY_COLUMNS:
            output.at[index, column] = str(
                info.get(column, "")
            )

    # CHECK_LIMITED가 실제 부담 필드에 남아 있으면 저장하지 않는다.
    invalid_flags = output[
        "supply_burden_flag"
    ].astype(str).isin(
        ["CHECK_LIMITED", "LIMITED", "FAILED"]
    )
    if invalid_flags.any():
        raise RuntimeError(
            f"INVALID_SUPPLY_FLAG file={filename}"
        )

    mismatch = (
        output["supply_burden_flag"].astype(str)
        != output[
            "supply_burden_detected"
        ].astype(str)
    )
    if mismatch.any():
        raise RuntimeError(
            f"SUPPLY_FLAG_DETECTED_MISMATCH file={filename}"
        )

    write_csv_atomically(output, path)

    result.update(
        {
            "status": "OK",
            "rows": len(output),
            "matched_rows": matched,
            "burden_detected_rows": burden_detected,
            "check_limited_rows": limited,
            "check_failed_rows": failed,
        }
    )
    return result


def run_self_test() -> int:
    hits = [
        {
            "stock_code": "005930",
            "report_name": "전환사채권발행결정",
            "rcept_dt": "20260701",
            "keywords": "CB발행",
            "severity": 2,
        }
    ]

    # 조회 제한이 있어도 실제 부담 필드는 TRUE/FALSE로만 유지한다.
    limited = build_summary(
        target_codes=["005930", "000660"],
        name_map={
            "005930": "삼성전자",
            "000660": "SK하이닉스",
        },
        file_map={},
        hits=hits,
        checked_at="2026-07-01T16:00:00+09:00",
        check_status="LIMITED",
        check_scope="DART 최근 90일 공시 제목 기준",
        limited_reason=(
            "DART_WHOLE_MARKET_LOOKBACK_CAPPED_"
            "90D_FROM_180D"
        ),
    )

    samsung = limited[
        limited["ticker"].eq("005930")
    ].iloc[0]
    hynix = limited[
        limited["ticker"].eq("000660")
    ].iloc[0]

    assert samsung["supply_check_status"] == "LIMITED"
    assert samsung["supply_burden_detected"] == "TRUE"
    assert samsung["supply_burden_flag"] == "TRUE"
    assert samsung["supply_burden_level"] == "경계"

    assert hynix["supply_check_status"] == "LIMITED"
    assert hynix["supply_burden_detected"] == "FALSE"
    assert hynix["supply_burden_flag"] == "FALSE"
    assert hynix["supply_burden_level"] == "없음"

    assert "CHECK_LIMITED" not in set(
        limited["supply_burden_flag"]
    )

    status = determine_check_state(
        api_key_present=True,
        target_codes_present=True,
        requested_days=90,
        effective_days=90,
        api_errors=[],
    )
    assert status == (
        "OK",
        "DART 최근 90일 공시 제목 기준",
        "",
    )

    status = determine_check_state(
        api_key_present=True,
        target_codes_present=True,
        requested_days=180,
        effective_days=90,
        api_errors=[],
    )
    assert status[0] == "LIMITED"
    assert "LOOKBACK_CAPPED" in status[2]

    status = determine_check_state(
        api_key_present=False,
        target_codes_present=True,
        requested_days=90,
        effective_days=90,
        api_errors=[],
    )
    assert status[0] == "FAILED"

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "check_status_separation,"
        "limited_without_false_burden,"
        "actual_burden_detection,"
        "check_limited_removed_from_flag"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output-dir",
        default="latest",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
    )
    parser.add_argument(
        "--dart-whole-market-max-days",
        type=int,
        default=DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS,
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.12,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--target-files",
        nargs="*",
        default=None,
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

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    target_files = (
        list(args.target_files)
        if args.target_files
        else generate_target_files()
    )

    checked_at = now_kst_text()
    requested_days = int(args.lookback_days)
    effective_days = (
        effective_whole_market_lookback_days(
            requested_days,
            args.dart_whole_market_max_days,
        )
    )

    api_key = os.environ.get(
        "DART_API_KEY",
        "",
    ).strip()

    (
        name_map,
        file_map,
        file_rows,
    ) = collect_target_tickers(
        output_dir,
        target_files,
    )

    target_codes = sorted(file_map.keys())

    log_lines: List[str] = [
        f"SCRIPT_NAME={SCRIPT_NAME}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={checked_at}",
        f"OUTPUT_DIR={output_dir}",
        f"REQUESTED_LOOKBACK_DAYS={requested_days}",
        f"EFFECTIVE_LOOKBACK_DAYS={effective_days}",
        "DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS="
        f"{args.dart_whole_market_max_days}",
        f"TARGET_TICKERS={len(target_codes)}",
        f"TARGET_FILE_COUNT={len(target_files)}",
        f"DART_API_KEY_PRESENT={'true' if api_key else 'false'}",
    ]

    for filename, row_count in file_rows.items():
        log_lines.append(
            f"TARGET_FILE={filename}|rows={row_count}"
        )

    hits: List[Dict[str, Any]] = []
    dart_status: Dict[str, Any] = {
        "api_calls": 0,
        "api_errors": [],
    }

    if api_key and target_codes:
        hits, dart_status = fetch_dart_reports(
            api_key=api_key,
            target_codes=set(target_codes),
            lookback_days=effective_days,
            max_pages=args.max_pages,
            sleep_seconds=args.sleep_seconds,
            timeout=args.timeout,
        )

    api_errors = list(
        dart_status.get("api_errors", [])
    )

    (
        check_status,
        check_scope,
        limited_reason,
    ) = determine_check_state(
        api_key_present=bool(api_key),
        target_codes_present=bool(target_codes),
        requested_days=requested_days,
        effective_days=effective_days,
        api_errors=api_errors,
    )

    summary_df = build_summary(
        target_codes=target_codes,
        name_map=name_map,
        file_map=file_map,
        hits=hits,
        checked_at=checked_at,
        check_status=check_status,
        check_scope=check_scope,
        limited_reason=limited_reason,
    )

    summary_map = {
        str(row["ticker"]): row.to_dict()
        for _, row in summary_df.iterrows()
    }

    enrich_results = [
        enrich_file(
            output_dir=output_dir,
            filename=filename,
            summary_map=summary_map,
        )
        for filename in target_files
    ]

    hits_df = pd.DataFrame(hits)
    if hits_df.empty:
        hits_df = pd.DataFrame(
            columns=[
                "stock_code",
                "corp_name",
                "report_name",
                "rcept_dt",
                "rcept_no",
                "corp_cls",
                "keywords",
                "severity",
                "relief_flag",
            ]
        )

    summary_csv = (
        output_dir
        / "supply_burden_summary_latest.csv"
    )
    hits_csv = (
        output_dir
        / "supply_burden_hits_latest.csv"
    )
    json_path = (
        output_dir
        / "supply_burden_latest.json"
    )
    log_path = (
        output_dir
        / "supply_burden_run_log_latest.txt"
    )

    write_csv_atomically(summary_df, summary_csv)
    write_csv_atomically(hits_df, hits_csv)

    if summary_df.empty:
        detected_count = 0
        danger_count = 0
        warning_count = 0
        caution_count = 0
    else:
        detected_count = int(
            summary_df[
                "supply_burden_detected"
            ].eq("TRUE").sum()
        )
        danger_count = int(
            summary_df[
                "supply_burden_level"
            ].eq("위험").sum()
        )
        warning_count = int(
            summary_df[
                "supply_burden_level"
            ].eq("경계").sum()
        )
        caution_count = int(
            summary_df[
                "supply_burden_level"
            ].eq("주의").sum()
        )

    payload = {
        "script": SCRIPT_NAME,
        "policy_version": POLICY_VERSION,
        "run_at_kst": checked_at,
        "status": check_status,
        "check_scope": check_scope,
        "check_limited_reason": limited_reason,
        "output_dir": str(output_dir),
        "requested_lookback_days": requested_days,
        "effective_lookback_days": effective_days,
        "dart_whole_market_max_days": (
            args.dart_whole_market_max_days
        ),
        "target_tickers": len(target_codes),
        "hit_reports": len(hits),
        "supply_burden_detected_tickers": (
            detected_count
        ),
        "danger_tickers": danger_count,
        "warning_tickers": warning_count,
        "caution_tickers": caution_count,
        "dart_status": dart_status,
        "enrich_results": enrich_results,
        "outputs": {
            "summary_csv": str(summary_csv),
            "hits_csv": str(hits_csv),
            "json": str(json_path),
            "log": str(log_path),
        },
        "field_policy": {
            "supply_check_status": (
                "OK/LIMITED/FAILED"
            ),
            "supply_burden_detected": (
                "TRUE/FALSE only"
            ),
            "supply_burden_flag": (
                "TRUE/FALSE compatibility only"
            ),
            "check_limited_is_not_burden": True,
        },
        "note": (
            "공시 제목 기반 1차 탐지이며 "
            "공시 본문 수량·행사가격·잠재물량 "
            "정밀판독은 후속 단계에서 수행합니다."
        ),
    }

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    log_lines.extend(
        [
            f"SUPPLY_CHECK_STATUS={check_status}",
            f"SUPPLY_CHECK_SCOPE={check_scope}",
            "SUPPLY_CHECK_LIMITED_REASON="
            f"{limited_reason}",
            "DART_API_CALLS="
            f"{dart_status.get('api_calls', 0)}",
            f"DART_API_ERROR_COUNT={len(api_errors)}",
            f"SUMMARY_ROWS={len(summary_df)}",
            f"HIT_REPORTS={len(hits)}",
            "SUPPLY_BURDEN_DETECTED_TICKERS="
            f"{detected_count}",
            f"DANGER_TICKERS={danger_count}",
            f"WARNING_TICKERS={warning_count}",
            f"CAUTION_TICKERS={caution_count}",
            "CHECK_LIMITED_IN_BURDEN_FLAG=0",
            f"OUTPUT_SUMMARY={summary_csv}",
            f"OUTPUT_HITS={hits_csv}",
            f"OUTPUT_JSON={json_path}",
        ]
    )

    for error in api_errors[:20]:
        log_lines.append(f"DART_ERROR={error}")

    for result in enrich_results:
        log_lines.append(
            "ENRICH_FILE="
            f"{result.get('file')}"
            f"|status={result.get('status')}"
            f"|rows={result.get('rows')}"
            f"|matched_rows={result.get('matched_rows')}"
            "|burden_detected_rows="
            f"{result.get('burden_detected_rows')}"
            "|check_limited_rows="
            f"{result.get('check_limited_rows')}"
            "|check_failed_rows="
            f"{result.get('check_failed_rows')}"
            f"|note={result.get('note', '')}"
        )

    log_path.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    # API 제한 또는 일부 오류는 자료상태로 표시하므로
    # 파일 생성 자체가 성공했으면 종료코드는 0으로 유지한다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
