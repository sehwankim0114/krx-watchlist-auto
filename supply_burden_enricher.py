#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
supply_burden_enricher.py
v1.2_dart_whole_market_90d_cap

목적
- OpenDART 공시검색 API의 최근 공시 제목을 기준으로 CB/BW/EB, 유상증자,
  전환청구, 자기주식처분, 대량보유, 보호예수, 블록딜 등 수급부담 가능성을 자동 탐지한다.
- 기존 latest CSV 파일들에 수급부담 관련 기술 컬럼을 추가한다.
- 실행 성공/실패와 무관하게 latest/supply_burden_run_log_latest.txt,
  latest/supply_burden_latest.json 파일을 항상 생성한다.

주의
- v1.2는 공시 제목 기반 1차 탐지이며, corp_code 없는 전체시장 검색은 DART 제한에 맞춰 90일 이하로 자동 제한한다.
- 공시 본문 세부 수량, 발행가, 행사비율, 보호예수 해제 물량까지 정밀 판독하는 단계는 아니다.
- supply_burden_flag=TRUE는 "수급부담 가능성/주의 신호"로 해석한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

SCRIPT_NAME = "supply_burden_enricher.py v1.2_dart_whole_market_90d_cap"

TARGET_FILES = [
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

# OpenDART 공시검색 API는 corp_code 없이 전체시장 검색 시 검색기간을 3개월 이내로 제한한다.
# 이 스크립트는 corp_code 없는 코스피/코스닥 전체검색 방식이므로 기본 90일로 자동 제한한다.
DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS = 90

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
    ("임원ㆍ주요주주특정증권등소유상황보고서", "주요주주변동", 1),
    ("임원·주요주주특정증권등소유상황보고서", "주요주주변동", 1),
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


def effective_whole_market_lookback_days(requested_days: int, max_days: int = DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS) -> int:
    """
    OpenDART 공시검색 API는 corp_code 없이 전체시장 검색할 때 검색기간을 3개월 이내로 제한한다.
    사용자가 180일처럼 긴 기간을 넣어도 전체검색에서는 자동으로 90일 이하로 줄인다.
    """
    try:
        requested = int(requested_days)
    except Exception:
        requested = max_days

    try:
        max_allowed = int(max_days)
    except Exception:
        max_allowed = DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS

    if requested < 1:
        requested = 1
    if max_allowed < 1:
        max_allowed = DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS

    return min(requested, max_allowed)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_code(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 6:
        return digits
    if 0 < len(digits) < 6:
        return digits.zfill(6)
    return None


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    except UnicodeDecodeError:
        try:
            return pd.read_csv(path, dtype=str).fillna("")
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def find_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def collect_target_tickers(output_dir: Path, target_files: List[str]) -> Tuple[Dict[str, str], Dict[str, List[str]], Dict[str, int]]:
    name_map: Dict[str, str] = {}
    file_map: Dict[str, List[str]] = defaultdict(list)
    file_rows: Dict[str, int] = {}

    for filename in target_files:
        path = output_dir / filename
        df = read_csv_safe(path)
        file_rows[filename] = int(len(df)) if not df.empty else 0
        if df.empty:
            continue

        code_col = find_col(df, CODE_COLUMNS)
        name_col = find_col(df, NAME_COLUMNS)
        if code_col is None:
            continue

        for _, row in df.iterrows():
            code = normalize_code(row.get(code_col, ""))
            if not code:
                continue
            file_map[code].append(filename)
            if name_col:
                name = str(row.get(name_col, "")).strip()
                if name and code not in name_map:
                    name_map[code] = name

    return name_map, dict(file_map), file_rows


def dart_get_json(params: Dict[str, Any], timeout: int = 25) -> Dict[str, Any]:
    url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read().decode("utf-8", errors="replace")
    return json.loads(data)


def classify_report(report_name: str) -> Tuple[bool, List[str], int, bool]:
    title = str(report_name or "")
    matched: List[str] = []
    severity = 0

    for keyword, label, sev in KEYWORD_RULES:
        if keyword in title:
            matched.append(label)
            severity = max(severity, sev)

    relief = any(keyword in title for keyword in RELIEF_KEYWORDS)
    return bool(matched), sorted(set(matched)), severity, relief


def severity_to_level(severity: int, count: int) -> str:
    if severity >= 3:
        return "위험"
    if severity == 2:
        if count >= 3:
            return "위험"
        return "경계"
    if severity == 1:
        if count >= 3:
            return "경계"
        return "주의"
    return "없음"


def fetch_dart_reports(
    api_key: str,
    target_codes: set[str],
    lookback_days: int,
    max_pages: int,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    end_dt = now_kst().date()
    begin_dt = end_dt - timedelta(days=lookback_days)
    bgn_de = begin_dt.strftime("%Y%m%d")
    end_de = end_dt.strftime("%Y%m%d")

    all_hits: List[Dict[str, Any]] = []
    status = {
        "bgn_de": bgn_de,
        "end_de": end_de,
        "lookback_days": lookback_days,
        "corp_cls": {},
        "api_calls": 0,
        "api_errors": [],
    }

    for corp_cls in ["Y", "K"]:
        page_no = 1
        total_page = None
        corp_stats = {
            "pages_requested": 0,
            "total_page": None,
            "raw_reports": 0,
            "target_reports": 0,
            "matched_reports": 0,
        }

        while page_no <= max_pages:
            params = {
                "crtfc_key": api_key,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "corp_cls": corp_cls,
                "page_no": page_no,
                "page_count": 100,
            }
            try:
                payload = dart_get_json(params)
                status["api_calls"] += 1
                corp_stats["pages_requested"] += 1
            except Exception as exc:
                status["api_errors"].append(f"corp_cls={corp_cls}, page={page_no}, error={type(exc).__name__}: {exc}")
                break

            dart_status = str(payload.get("status", ""))
            if dart_status == "013":
                # 조회된 데이터 없음
                break
            if dart_status != "000":
                message = payload.get("message", "")
                status["api_errors"].append(f"corp_cls={corp_cls}, page={page_no}, dart_status={dart_status}, message={message}")
                break

            try:
                total_page = int(payload.get("total_page", 1))
            except Exception:
                total_page = 1
            corp_stats["total_page"] = total_page

            reports = payload.get("list", []) or []
            corp_stats["raw_reports"] += len(reports)

            for item in reports:
                stock_code = normalize_code(item.get("stock_code", ""))
                if not stock_code or stock_code not in target_codes:
                    continue

                corp_stats["target_reports"] += 1
                report_name = str(item.get("report_nm", ""))
                is_risk, labels, severity, relief = classify_report(report_name)
                if not is_risk:
                    continue

                corp_stats["matched_reports"] += 1
                all_hits.append(
                    {
                        "stock_code": stock_code,
                        "corp_name": str(item.get("corp_name", "")),
                        "report_name": report_name,
                        "rcept_dt": str(item.get("rcept_dt", "")),
                        "rcept_no": str(item.get("rcept_no", "")),
                        "corp_cls": corp_cls,
                        "keywords": ",".join(labels),
                        "severity": severity,
                        "relief_flag": relief,
                    }
                )

            if total_page is not None and page_no >= total_page:
                break
            page_no += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        status["corp_cls"][corp_cls] = corp_stats

    return all_hits, status


def build_summary(
    target_codes: List[str],
    name_map: Dict[str, str],
    file_map: Dict[str, List[str]],
    hits: List[Dict[str, Any]],
    checked_at: str,
    limited_reason: str = "",
) -> pd.DataFrame:
    hits_by_code: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for hit in hits:
        code = normalize_code(hit.get("stock_code", ""))
        if code:
            hits_by_code[code].append(hit)

    rows: List[Dict[str, Any]] = []
    for code in sorted(target_codes):
        code_hits = sorted(hits_by_code.get(code, []), key=lambda x: str(x.get("rcept_dt", "")), reverse=True)
        count = len(code_hits)
        max_severity = max([int(item.get("severity", 0) or 0) for item in code_hits], default=0)
        level = severity_to_level(max_severity, count)
        keywords = sorted(set(
            label.strip()
            for item in code_hits
            for label in str(item.get("keywords", "")).split(",")
            if label.strip()
        ))
        latest = code_hits[0] if code_hits else {}

        if limited_reason:
            flag = "CHECK_LIMITED"
            level_out = "확인제한"
        else:
            flag = "TRUE" if count > 0 else "FALSE"
            level_out = level

        rows.append(
            {
                "ticker": code,
                "name": name_map.get(code, ""),
                "supply_burden_flag": flag,
                "supply_burden_level": level_out,
                "supply_burden_keywords": ",".join(keywords),
                "supply_burden_latest_report_date": str(latest.get("rcept_dt", "")),
                "supply_burden_latest_report_name": str(latest.get("report_name", "")),
                "supply_burden_report_count": count,
                "source_files": ",".join(sorted(set(file_map.get(code, [])))),
                "supply_burden_checked_at_kst": checked_at,
                "limited_reason": limited_reason,
            }
        )

    return pd.DataFrame(rows)


def enrich_file(output_dir: Path, filename: str, summary_map: Dict[str, Dict[str, Any]], checked_at: str) -> Dict[str, Any]:
    path = output_dir / filename
    df = read_csv_safe(path)
    result = {
        "file": filename,
        "status": "UNKNOWN",
        "rows": 0,
        "matched_rows": 0,
        "flagged_rows": 0,
        "note": "",
    }

    if df.empty:
        result.update({"status": "EMPTY_OR_MISSING", "note": "file missing or empty"})
        return result

    code_col = find_col(df, CODE_COLUMNS)
    if code_col is None:
        result.update({"status": "NO_CODE_COLUMN", "rows": len(df)})
        return result

    out = df.copy()
    for col in SUPPLY_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    matched_rows = 0
    flagged_rows = 0
    for idx, row in out.iterrows():
        code = normalize_code(row.get(code_col, ""))
        if not code:
            continue
        info = summary_map.get(code)
        if not info:
            continue
        matched_rows += 1
        flag = str(info.get("supply_burden_flag", ""))
        if flag == "TRUE":
            flagged_rows += 1
        for col in SUPPLY_COLUMNS:
            out.at[idx, col] = str(info.get(col, "")) if col != "supply_burden_checked_at_kst" else checked_at

    out.to_csv(path, index=False, encoding="utf-8-sig")
    result.update(
        {
            "status": "OK",
            "rows": len(out),
            "matched_rows": matched_rows,
            "flagged_rows": flagged_rows,
        }
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument(
        "--dart-whole-market-max-days",
        type=int,
        default=DART_WHOLE_MARKET_MAX_LOOKBACK_DAYS,
        help="corp_code 없는 DART 전체시장 검색의 최대 조회일수. 기본 90일.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.12)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--target-files", nargs="*", default=TARGET_FILES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    checked_at = now_kst().isoformat(timespec="seconds")
    original_lookback_days = int(args.lookback_days)
    effective_lookback_days = effective_whole_market_lookback_days(
        original_lookback_days,
        args.dart_whole_market_max_days,
    )
    lookback_capped = effective_lookback_days != original_lookback_days

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at_kst={checked_at}",
        f"output_dir={output_dir}",
        f"original_lookback_days={original_lookback_days}",
        f"effective_lookback_days={effective_lookback_days}",
        f"dart_whole_market_max_days={args.dart_whole_market_max_days}",
        f"lookback_capped={lookback_capped}",
        f"max_pages={args.max_pages}",
        f"sleep_seconds={args.sleep_seconds}",
    ]

    api_key = os.environ.get("DART_API_KEY", "").strip()
    name_map, file_map, file_rows = collect_target_tickers(output_dir, args.target_files)
    target_codes = sorted(file_map.keys())

    log_lines.append(f"target_tickers={len(target_codes)}")
    log_lines.append(f"target_files={','.join(args.target_files)}")
    for filename, rows in file_rows.items():
        log_lines.append(f"TARGET_FILE {filename}: rows={rows}")

    hits: List[Dict[str, Any]] = []
    dart_status: Dict[str, Any] = {}
    limited_reason = ""

    if lookback_capped:
        limited_reason = f"DART_WHOLE_MARKET_LOOKBACK_CAPPED_{effective_lookback_days}D_FROM_{original_lookback_days}D"
        log_lines.append(f"LOOKBACK_CAP_APPLIED original={original_lookback_days}, effective={effective_lookback_days}")

    if not api_key:
        status = "WARN_NO_DART_API_KEY"
        limited_reason = "NO_DART_API_KEY"
        log_lines.append("status=WARN_NO_DART_API_KEY")
    elif not target_codes:
        status = "WARN_NO_TARGET_TICKERS"
        limited_reason = "NO_TARGET_TICKERS"
        log_lines.append("status=WARN_NO_TARGET_TICKERS")
    else:
        hits, dart_status = fetch_dart_reports(
            api_key=api_key,
            target_codes=set(target_codes),
            lookback_days=effective_lookback_days,
            max_pages=args.max_pages,
            sleep_seconds=args.sleep_seconds,
        )
        if dart_status.get("api_errors"):
            status = "WARN_DART_PARTIAL_ERROR"
        else:
            status = "OK"
        log_lines.append(f"dart_api_calls={dart_status.get('api_calls', 0)}")
        log_lines.append(f"dart_api_error_count={len(dart_status.get('api_errors', []))}")
        for error in dart_status.get("api_errors", [])[:20]:
            log_lines.append(f"DART_ERROR {error}")

    summary_df = build_summary(
        target_codes=target_codes,
        name_map=name_map,
        file_map=file_map,
        hits=hits,
        checked_at=checked_at,
        limited_reason=limited_reason,
    )

    summary_map = {
        str(row["ticker"]): row.to_dict()
        for _, row in summary_df.iterrows()
    } if not summary_df.empty else {}

    enrich_results = [enrich_file(output_dir, filename, summary_map, checked_at) for filename in args.target_files]

    hits_df = pd.DataFrame(hits)
    summary_csv = output_dir / "supply_burden_summary_latest.csv"
    hits_csv = output_dir / "supply_burden_hits_latest.csv"
    json_path = output_dir / "supply_burden_latest.json"
    log_path = output_dir / "supply_burden_run_log_latest.txt"

    summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    if hits_df.empty:
        hits_df = pd.DataFrame(columns=["stock_code", "corp_name", "report_name", "rcept_dt", "rcept_no", "corp_cls", "keywords", "severity", "relief_flag"])
    hits_df.to_csv(hits_csv, index=False, encoding="utf-8-sig")

    flagged_count = int((summary_df.get("supply_burden_flag") == "TRUE").sum()) if not summary_df.empty else 0
    danger_count = int((summary_df.get("supply_burden_level") == "위험").sum()) if not summary_df.empty else 0
    warning_count = int((summary_df.get("supply_burden_level") == "경계").sum()) if not summary_df.empty else 0
    caution_count = int((summary_df.get("supply_burden_level") == "주의").sum()) if not summary_df.empty else 0

    payload = {
        "script": SCRIPT_NAME,
        "run_at_kst": checked_at,
        "status": status,
        "output_dir": str(output_dir),
        "original_lookback_days": original_lookback_days,
        "effective_lookback_days": effective_lookback_days,
        "dart_whole_market_max_days": args.dart_whole_market_max_days,
        "lookback_capped": lookback_capped,
        "target_tickers": len(target_codes),
        "hit_reports": len(hits),
        "flagged_tickers": flagged_count,
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
        "note": "공시 제목 기반 1차 수급부담 탐지. 본문 수량/발행가/행사비율 정밀판독 아님.",
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    log_lines.extend(
        [
            f"status={status}",
            f"summary_rows={len(summary_df)}",
            f"hit_reports={len(hits)}",
            f"flagged_tickers={flagged_count}",
            f"danger_tickers={danger_count}",
            f"warning_tickers={warning_count}",
            f"caution_tickers={caution_count}",
            f"output_summary={summary_csv}",
            f"output_hits={hits_csv}",
            f"output_json={json_path}",
        ]
    )

    for result in enrich_results:
        log_lines.append(
            "ENRICH_FILE "
            f"{result.get('file')}: "
            f"status={result.get('status')}, "
            f"rows={result.get('rows')}, "
            f"matched_rows={result.get('matched_rows')}, "
            f"flagged_rows={result.get('flagged_rows')}, "
            f"note={result.get('note', '')}"
        )

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
