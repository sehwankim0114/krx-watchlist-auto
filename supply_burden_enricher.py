#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
supply_burden_enricher.py
v1.0_dart_title_supply_burden

목적
- OpenDART 공시검색 API의 최근 공시 제목을 기준으로
  CB/BW/EB, 유상증자, 전환청구, 자기주식처분, 대량보유, 보호예수, 블록딜 등
  수급부담 가능성을 자동 탐지한다.
- 기존 latest CSV 파일들에 수급부담 관련 컬럼을 추가한다.

주의
- v1.0은 "공시 제목 기반 1차 탐지"이다.
- 공시 본문 세부 수량, 발행가, 행사비율, 보호예수 해제 물량까지 정밀 판독하는 단계는 아니다.
- 따라서 supply_burden_flag=TRUE는 "수급부담 가능성/주의 신호"로 해석한다.

생성/갱신 파일
- latest/supply_burden_cache_latest.csv
- latest/supply_burden_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

SCRIPT_NAME = "supply_burden_enricher.py v1.0_dart_title_supply_burden"
KST = ZoneInfo("Asia/Seoul")

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

TARGET_FILES = [
    "watchlist_summary_latest.csv",
    "kospi_universe_summary_latest.csv",
    "kosdaq_universe_summary_latest.csv",
    "kospi_candidates_30_latest.csv",
    "kospi_recommend_7_latest.csv",
    "kosdaq_candidates_10_latest.csv",
    "kosdaq_recommend_5_latest.csv",
    "kospi_gainers_1m_latest.csv",
    "kospi_monthly_cycle_latest.csv",
    "kospi_short_term_candidates_30_latest.csv",
    "kospi_short_term_recommend_7_latest.csv",
    "kospi_fx_weakness_candidates_30_latest.csv",
    "kospi_fx_weakness_recommend_7_latest.csv",
]

SUPPLY_COLUMNS = [
    "supply_burden_flag",
    "supply_burden_level",
    "supply_burden_score",
    "supply_burden_types",
    "supply_burden_last_date",
    "supply_burden_recent_reports",
    "supply_burden_basis",
    "supply_burden_source_status",
    "cb_bw_eb_flag",
    "rights_issue_flag",
    "treasury_disposal_flag",
    "major_holder_sale_flag",
    "lockup_release_flag",
    "block_deal_flag",
    "overhang_flag",
]

RISK_RULES = {
    "cb_bw_eb": {
        "weight": 4,
        "keywords": [
            "전환사채",
            "전환사채권발행결정",
            "전환청구권행사",
            "전환가액",
            "전환가액의조정",
            "신주인수권부사채",
            "신주인수권부사채권발행결정",
            "신주인수권행사",
            "교환사채",
            "교환사채권발행결정",
            "교환청구권행사",
            "CB",
            "BW",
            "EB",
        ],
    },
    "rights_issue": {
        "weight": 4,
        "keywords": [
            "유상증자",
            "유상증자결정",
            "증자결정",
            "제3자배정",
            "주주배정",
            "일반공모",
            "소액공모",
            "신주발행",
            "증권신고서",
            "투자설명서",
        ],
    },
    "treasury_disposal": {
        "weight": 3,
        "keywords": [
            "자기주식처분",
            "자기주식 처분",
            "자기주식처분결정",
            "자기주식처분결과보고서",
            "자기주식",
        ],
    },
    "major_holder_sale": {
        "weight": 2,
        "keywords": [
            "주식등의대량보유상황보고서",
            "대량보유상황보고서",
            "임원ㆍ주요주주특정증권등소유상황보고서",
            "임원·주요주주특정증권등소유상황보고서",
            "소유상황보고서",
            "주요주주",
            "최대주주변경",
            "최대주주 변경",
        ],
    },
    "lockup_release": {
        "weight": 3,
        "keywords": [
            "보호예수",
            "의무보유",
            "의무보유해제",
            "의무보유 해제",
            "매각제한",
            "매각제한해제",
            "락업",
            "Lock-up",
            "lockup",
        ],
    },
    "block_deal": {
        "weight": 4,
        "keywords": [
            "블록딜",
            "시간외대량매매",
            "시간외 대량매매",
            "대량매매",
            "대량매도",
            "장외매도",
        ],
    },
    "additional_listing": {
        "weight": 3,
        "keywords": [
            "추가상장",
            "상장예정",
            "전환주식",
            "전환우선주",
            "보통주전환",
            "신주인수권증권",
        ],
    },
}


def now_kst() -> datetime:
    return datetime.now(KST)


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def normalize_ticker(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return ""

    if text.endswith(".0"):
        text = text[:-2]

    text = "".join(ch for ch in text if ch.isdigit())

    if text == "":
        return ""

    return text.zfill(6)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace(" ", "")
    text = text.replace("\u3000", "")
    text = text.replace("ㆍ", "·")

    return text


def http_get_json(params: Dict[str, Any], timeout: int = 25) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{DART_LIST_URL}?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 krx-watchlist-auto supply-burden-enricher",
            "Accept": "application/json,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    return json.loads(body)


def make_date_windows(end_dt: datetime, lookback_days: int, max_window_days: int = 90) -> List[Tuple[str, str]]:
    start_dt = end_dt - timedelta(days=lookback_days - 1)
    windows: List[Tuple[str, str]] = []

    cur = start_dt

    while cur <= end_dt:
        win_end = min(cur + timedelta(days=max_window_days - 1), end_dt)
        windows.append((ymd(cur), ymd(win_end)))
        cur = win_end + timedelta(days=1)

    return windows


def collect_target_tickers(output_dir: Path) -> List[str]:
    tickers: set[str] = set()

    for filename in TARGET_FILES:
        path = output_dir / filename

        if not path.exists():
            continue

        try:
            df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
        except Exception:
            continue

        if "ticker" not in df.columns:
            continue

        for value in df["ticker"].tolist():
            ticker = normalize_ticker(value)

            if ticker:
                tickers.add(ticker)

    return sorted(tickers)


def fetch_dart_disclosures(
    api_key: str,
    lookback_days: int,
    sleep_seconds: float,
    max_pages_per_query: int,
    log_lines: List[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    end_dt = now_kst()
    windows = make_date_windows(end_dt, lookback_days, max_window_days=90)

    all_items: List[Dict[str, Any]] = []
    seen_rcept_no: set[str] = set()
    status_counter: Counter[str] = Counter()

    log_lines.append(f"dart_lookback_days={lookback_days}")
    log_lines.append(
        "dart_date_windows="
        + ",".join([f"{bgn}-{end}" for bgn, end in windows])
    )

    for corp_cls in ["Y", "K"]:
        for bgn_de, end_de in windows:
            page_no = 1

            while page_no <= max_pages_per_query:
                params = {
                    "crtfc_key": api_key,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "last_reprt_at": "N",
                    "corp_cls": corp_cls,
                    "sort": "date",
                    "sort_mth": "desc",
                    "page_no": page_no,
                    "page_count": 100,
                }

                try:
                    data = http_get_json(params)
                except Exception as exc:
                    status_counter[f"HTTP_ERROR:{type(exc).__name__}"] += 1
                    log_lines.append(
                        f"DART_HTTP_ERROR corp_cls={corp_cls} window={bgn_de}-{end_de} page={page_no}: {type(exc).__name__}: {exc}"
                    )
                    break

                status = str(data.get("status", "")).strip()
                message = str(data.get("message", "")).strip()

                if status and status != "000":
                    status_counter[f"{status}:{message}"] += 1
                else:
                    status_counter["000"] += 1

                if status == "013":
                    log_lines.append(
                        f"DART_NO_DATA corp_cls={corp_cls} window={bgn_de}-{end_de} page={page_no}"
                    )
                    break

                if status != "000":
                    log_lines.append(
                        f"DART_STATUS_NOT_OK corp_cls={corp_cls} window={bgn_de}-{end_de} page={page_no}: status={status}, message={message}"
                    )
                    break

                items = data.get("list") or []

                if not isinstance(items, list) or len(items) == 0:
                    log_lines.append(
                        f"DART_EMPTY_LIST corp_cls={corp_cls} window={bgn_de}-{end_de} page={page_no}"
                    )
                    break

                for item in items:
                    rcept_no = str(item.get("rcept_no", "")).strip()

                    if rcept_no and rcept_no in seen_rcept_no:
                        continue

                    if rcept_no:
                        seen_rcept_no.add(rcept_no)

                    all_items.append(item)

                try:
                    total_page = int(data.get("total_page") or 1)
                except Exception:
                    total_page = 1

                if page_no >= total_page:
                    break

                page_no += 1
                time.sleep(sleep_seconds)

            time.sleep(sleep_seconds)

    return all_items, dict(status_counter)


def classify_report(report_nm: str) -> Tuple[Dict[str, bool], int, List[str]]:
    normalized = normalize_text(report_nm)

    type_flags: Dict[str, bool] = {}
    score = 0
    matched_types: List[str] = []

    for risk_type, rule in RISK_RULES.items():
        keywords = rule["keywords"]
        matched = False

        for keyword in keywords:
            if normalize_text(keyword) in normalized:
                matched = True
                break

        type_flags[risk_type] = matched

        if matched:
            score += int(rule["weight"])
            matched_types.append(risk_type)

    return type_flags, score, matched_types


def aggregate_by_ticker(
    disclosures: List[Dict[str, Any]],
    target_tickers: Iterable[str],
    log_lines: List[str],
) -> Dict[str, Dict[str, Any]]:
    target_set = set(target_tickers)
    agg: Dict[str, Dict[str, Any]] = {}

    matched_disclosure_count = 0
    risk_disclosure_count = 0

    for item in disclosures:
        ticker = normalize_ticker(item.get("stock_code"))

        if not ticker or ticker not in target_set:
            continue

        matched_disclosure_count += 1

        report_nm = str(item.get("report_nm", "")).strip()
        rcept_dt = str(item.get("rcept_dt", "")).strip()
        rcept_no = str(item.get("rcept_no", "")).strip()
        corp_name = str(item.get("corp_name", "")).strip()

        type_flags, report_score, matched_types = classify_report(report_nm)

        if report_score <= 0:
            continue

        risk_disclosure_count += 1

        if ticker not in agg:
            agg[ticker] = {
                "ticker": ticker,
                "name": corp_name,
                "score": 0,
                "types": set(),
                "reports": [],
                "last_date": "",
                "flags": defaultdict(bool),
            }

        row = agg[ticker]
        row["score"] += report_score
        row["types"].update(matched_types)

        for key, value in type_flags.items():
            if value:
                row["flags"][key] = True

        if rcept_dt and rcept_dt > row["last_date"]:
            row["last_date"] = rcept_dt

        report_label = f"{rcept_dt}:{report_nm}"

        if rcept_no:
            report_label += f":{rcept_no}"

        row["reports"].append(report_label)

    log_lines.append(f"matched_disclosure_count={matched_disclosure_count}")
    log_lines.append(f"risk_disclosure_count={risk_disclosure_count}")

    result: Dict[str, Dict[str, Any]] = {}

    for ticker, row in agg.items():
        score = int(row["score"])
        types = sorted(list(row["types"]))
        flags = row["flags"]

        cb_bw_eb_flag = bool(flags.get("cb_bw_eb"))
        rights_issue_flag = bool(flags.get("rights_issue"))
        treasury_disposal_flag = bool(flags.get("treasury_disposal"))
        major_holder_sale_flag = bool(flags.get("major_holder_sale"))
        lockup_release_flag = bool(flags.get("lockup_release"))
        block_deal_flag = bool(flags.get("block_deal"))
        additional_listing_flag = bool(flags.get("additional_listing"))

        overhang_flag = any(
            [
                cb_bw_eb_flag,
                rights_issue_flag,
                treasury_disposal_flag,
                lockup_release_flag,
                block_deal_flag,
                additional_listing_flag,
            ]
        )

        if score >= 7 or overhang_flag:
            level = "HIGH"
        elif score >= 3:
            level = "WATCH"
        elif score > 0:
            level = "LOW"
        else:
            level = ""

        supply_burden_flag = level in {"WATCH", "HIGH"}

        reports = row["reports"]
        reports = sorted(reports, reverse=True)
        recent_reports = " | ".join(reports[:5])

        basis_parts = []

        if types:
            basis_parts.append("types=" + ",".join(types))

        if recent_reports:
            basis_parts.append("recent=" + recent_reports[:500])

        basis = "; ".join(basis_parts)

        result[ticker] = {
            "ticker": ticker,
            "name": row.get("name", ""),
            "supply_burden_flag": supply_burden_flag,
            "supply_burden_level": level,
            "supply_burden_score": score,
            "supply_burden_types": ",".join(types),
            "supply_burden_last_date": row["last_date"],
            "supply_burden_recent_reports": recent_reports,
            "supply_burden_basis": basis,
            "supply_burden_source_status": "OK",
            "cb_bw_eb_flag": cb_bw_eb_flag,
            "rights_issue_flag": rights_issue_flag,
            "treasury_disposal_flag": treasury_disposal_flag,
            "major_holder_sale_flag": major_holder_sale_flag,
            "lockup_release_flag": lockup_release_flag,
            "block_deal_flag": block_deal_flag,
            "overhang_flag": overhang_flag,
        }

    return result


def make_cache_df(target_tickers: List[str], burden_map: Dict[str, Dict[str, Any]], no_key: bool = False) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    for ticker in target_tickers:
        if no_key:
            rows.append(
                {
                    "ticker": ticker,
                    "supply_burden_flag": "",
                    "supply_burden_level": "",
                    "supply_burden_score": "",
                    "supply_burden_types": "",
                    "supply_burden_last_date": "",
                    "supply_burden_recent_reports": "",
                    "supply_burden_basis": "",
                    "supply_burden_source_status": "NO_DART_API_KEY",
                    "cb_bw_eb_flag": "",
                    "rights_issue_flag": "",
                    "treasury_disposal_flag": "",
                    "major_holder_sale_flag": "",
                    "lockup_release_flag": "",
                    "block_deal_flag": "",
                    "overhang_flag": "",
                }
            )
            continue

        if ticker in burden_map:
            rows.append(burden_map[ticker])
        else:
            rows.append(
                {
                    "ticker": ticker,
                    "supply_burden_flag": False,
                    "supply_burden_level": "",
                    "supply_burden_score": 0,
                    "supply_burden_types": "",
                    "supply_burden_last_date": "",
                    "supply_burden_recent_reports": "",
                    "supply_burden_basis": "",
                    "supply_burden_source_status": "NO_RECENT_RISK_DISCLOSURE",
                    "cb_bw_eb_flag": False,
                    "rights_issue_flag": False,
                    "treasury_disposal_flag": False,
                    "major_holder_sale_flag": False,
                    "lockup_release_flag": False,
                    "block_deal_flag": False,
                    "overhang_flag": False,
                }
            )

    return pd.DataFrame(rows)


def enrich_file(path: Path, cache_df: pd.DataFrame) -> Dict[str, Any]:
    result = {
        "file": path.name,
        "status": "skip_missing",
        "rows": 0,
        "matched": 0,
        "supply_burden_true": 0,
    }

    if not path.exists():
        return result

    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
    except Exception as exc:
        result["status"] = f"read_error:{type(exc).__name__}"
        return result

    result["rows"] = int(len(df))

    if "ticker" not in df.columns:
        result["status"] = "skip_no_ticker"
        return result

    for col in SUPPLY_COLUMNS:
        if col in df.columns:
            df = df.drop(columns=[col])

    df["_ticker_norm_for_supply"] = df["ticker"].map(normalize_ticker)

    merge_cols = ["ticker"] + SUPPLY_COLUMNS
    cache_small = cache_df[merge_cols].copy()
    cache_small["_ticker_norm_for_supply"] = cache_small["ticker"].map(normalize_ticker)
    cache_small = cache_small.drop(columns=["ticker"])

    merged = df.merge(
        cache_small,
        on="_ticker_norm_for_supply",
        how="left",
        validate="many_to_one",
    )

    matched_mask = merged["supply_burden_source_status"].notna()
    result["matched"] = int(matched_mask.sum())

    for col in SUPPLY_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""

    merged["supply_burden_source_status"] = merged["supply_burden_source_status"].fillna("NOT_IN_CACHE")

    for col in [
        "supply_burden_flag",
        "cb_bw_eb_flag",
        "rights_issue_flag",
        "treasury_disposal_flag",
        "major_holder_sale_flag",
        "lockup_release_flag",
        "block_deal_flag",
        "overhang_flag",
    ]:
        merged[col] = merged[col].fillna(False)

    merged["supply_burden_score"] = merged["supply_burden_score"].fillna(0)

    for col in [
        "supply_burden_level",
        "supply_burden_types",
        "supply_burden_last_date",
        "supply_burden_recent_reports",
        "supply_burden_basis",
    ]:
        merged[col] = merged[col].fillna("")

    result["supply_burden_true"] = int(
        merged["supply_burden_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()
    )

    merged = merged.drop(columns=["_ticker_norm_for_supply"])

    merged.to_csv(path, index=False, encoding="utf-8-sig")

    result["status"] = "ok"
    return result


def write_log(output_dir: Path, log_lines: List[str]) -> None:
    path = output_dir / "supply_burden_run_log_latest.txt"
    path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--sleep-seconds", type=float, default=0.12)
    parser.add_argument("--max-pages-per-query", type=int, default=200)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at_kst={now_kst().isoformat(timespec='seconds')}",
        f"output_dir={output_dir}",
        f"lookback_days={args.lookback_days}",
        f"method=opendart_list_title_keyword_scan",
        f"note=공시 제목 기반 1차 탐지이며 본문 수량/비율 정밀 판독은 아님",
    ]

    target_tickers = collect_target_tickers(output_dir)
    log_lines.append(f"target_tickers={len(target_tickers)}")

    api_key = os.environ.get("DART_API_KEY", "").strip()

    if not api_key:
        log_lines.append("status=WARN_NO_DART_API_KEY")
        log_lines.append("message=DART_API_KEY가 없어 빈 수급부담 컬럼만 추가합니다.")

        cache_df = make_cache_df(target_tickers, {}, no_key=True)

        cache_path = output_dir / "supply_burden_cache_latest.csv"
        cache_df.to_csv(cache_path, index=False, encoding="utf-8-sig")

        for filename in TARGET_FILES:
            result = enrich_file(output_dir / filename, cache_df)
            log_lines.append(
                f"ENRICH_FILE {filename}: status={result['status']}, rows={result['rows']}, matched={result['matched']}, supply_burden_true={result['supply_burden_true']}"
            )

        log_lines.append(f"cache_output_rows={len(cache_df)}")
        log_lines.append("supply_burden_count=0")
        log_lines.append("status=OK")
        write_log(output_dir, log_lines)
        print("SUPPLY_BURDEN_STATUS=OK")
        return

    disclosures, dart_status_counts = fetch_dart_disclosures(
        api_key=api_key,
        lookback_days=args.lookback_days,
        sleep_seconds=args.sleep_seconds,
        max_pages_per_query=args.max_pages_per_query,
        log_lines=log_lines,
    )

    log_lines.append(f"dart_disclosure_rows={len(disclosures)}")
    log_lines.append(f"dart_status_counts={dart_status_counts}")

    burden_map = aggregate_by_ticker(disclosures, target_tickers, log_lines)

    cache_df = make_cache_df(target_tickers, burden_map, no_key=False)

    cache_path = output_dir / "supply_burden_cache_latest.csv"
    cache_df.to_csv(cache_path, index=False, encoding="utf-8-sig")

    supply_burden_count = int(
        cache_df["supply_burden_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()
    )

    source_status_counts = dict(Counter(cache_df["supply_burden_source_status"].fillna("").astype(str)))

    flag_counts = {
        "cb_bw_eb_flag": int(cache_df["cb_bw_eb_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "rights_issue_flag": int(cache_df["rights_issue_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "treasury_disposal_flag": int(cache_df["treasury_disposal_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "major_holder_sale_flag": int(cache_df["major_holder_sale_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "lockup_release_flag": int(cache_df["lockup_release_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "block_deal_flag": int(cache_df["block_deal_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
        "overhang_flag": int(cache_df["overhang_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()),
    }

    log_lines.append(f"cache_output_rows={len(cache_df)}")
    log_lines.append(f"supply_burden_count={supply_burden_count}")
    log_lines.append(f"source_status_counts={source_status_counts}")
    log_lines.append(f"flag_counts={flag_counts}")

    enriched_files = 0

    for filename in TARGET_FILES:
        result = enrich_file(output_dir / filename, cache_df)

        if result["status"] == "ok":
            enriched_files += 1

        log_lines.append(
            f"ENRICH_FILE {filename}: status={result['status']}, rows={result['rows']}, matched={result['matched']}, supply_burden_true={result['supply_burden_true']}"
        )

    log_lines.append(f"enriched_files={enriched_files}")
    log_lines.append("status=OK")

    write_log(output_dir, log_lines)

    print("SUPPLY_BURDEN_STATUS=OK")
    print(f"SUPPLY_BURDEN_COUNT={supply_burden_count}")


if __name__ == "__main__":
    main()
