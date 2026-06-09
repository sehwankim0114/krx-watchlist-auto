#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
operating_loss_enricher.py

영업손실 자동판별 보강기
- OpenDART 고유번호(corp_code)와 단일회사 주요계정 API를 이용해 최근 확정 보고서의 영업이익을 확인한다.
- 기존 latest/*.csv 표 파일에 영업손실 관련 컬럼을 추가/갱신한다.
- DART_API_KEY가 없으면 실패시키지 않고 WARN 로그를 남긴 뒤 빈 컬럼만 추가한다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd


SCRIPT_NAME = "operating_loss_enricher.py v1.1_syntax_fix_and_fresh_tables"
KST = ZoneInfo("Asia/Seoul")

TARGET_CSV_FILES = [
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

OUTPUT_COLUMNS = [
    "ticker",
    "corp_code",
    "corp_name",
    "operating_profit",
    "operating_profit_unit",
    "operating_loss_flag",
    "operating_loss_basis",
    "operating_loss_source_status",
    "account_nm",
    "fs_div",
    "sj_div",
    "bsns_year",
    "reprt_code",
    "target_period_key",
    "fetched_at_kst",
]


def now_kst() -> datetime:
    return datetime.now(KST)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_ticker(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]

    text = re.sub(r"[^0-9]", "", text)
    return text.zfill(6) if text else ""


def get_ticker_column(df: pd.DataFrame) -> Optional[str]:
    for col in ["ticker", "code", "종목코드", "단축코드", "isuCd", "isu_cd", "symbol"]:
        if col in df.columns:
            return col
    return None


def parse_amount(value: Any) -> Optional[int]:
    if value is None:
        return None

    text = str(value).strip()
    if text in {"", "-", "nan", "None", "null"}:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    text = text.replace(",", "").replace("원", "").replace(" ", "")
    text = re.sub(r"[^0-9.\-]", "", text)

    if text in {"", "-", "."}:
        return None

    try:
        number = float(text)
    except Exception:
        return None

    if negative:
        number = -abs(number)

    return int(round(number))


def candidate_report_periods(today: Optional[datetime] = None) -> List[Tuple[str, str]]:
    """
    OpenDART 보고서 코드
    - 11013: 1분기보고서
    - 11012: 반기보고서
    - 11014: 3분기보고서
    - 11011: 사업보고서
    """
    if today is None:
        today = now_kst()

    y = today.year
    m = today.month
    d = today.day

    periods: List[Tuple[str, str]] = []

    if (m, d) >= (11, 16):
        periods.extend([(str(y), "11014"), (str(y), "11012"), (str(y), "11013")])
    elif (m, d) >= (8, 16):
        periods.extend([(str(y), "11012"), (str(y), "11013")])
    elif (m, d) >= (5, 16):
        periods.extend([(str(y), "11013")])

    py = y - 1
    periods.extend(
        [
            (str(py), "11011"),
            (str(py), "11014"),
            (str(py), "11012"),
            (str(py), "11013"),
            (str(py - 1), "11011"),
        ]
    )

    seen = set()
    unique: List[Tuple[str, str]] = []
    for item in periods:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique


def report_label(bsns_year: str, reprt_code: str) -> str:
    labels = {
        "11013": "1분기보고서",
        "11012": "반기보고서",
        "11014": "3분기보고서",
        "11011": "사업보고서",
    }
    return f"{bsns_year} {labels.get(reprt_code, reprt_code)}"


def target_period_key(periods: List[Tuple[str, str]]) -> str:
    if not periods:
        return ""
    y, code = periods[0]
    return f"{y}_{code}"


def urlopen_bytes(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


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


def load_corp_code_map(api_key: str, output_dir: Path, log_lines: List[str]) -> Dict[str, Dict[str, str]]:
    cache_path = output_dir / "dart_corp_code_map_latest.csv"

    if cache_path.exists():
        try:
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=KST)
            if (now_kst() - mtime).total_seconds() < 86400:
                cached = read_csv_safe(cache_path)
                mapping = {
                    clean_ticker(row["stock_code"]): {
                        "corp_code": str(row["corp_code"]).zfill(8),
                        "corp_name": str(row.get("corp_name", "")),
                    }
                    for _, row in cached.iterrows()
                    if clean_ticker(row.get("stock_code", ""))
                }
                if mapping:
                    log_lines.append(f"corp_code_map_source=cache, rows={len(mapping)}")
                    return mapping
        except Exception as exc:
            log_lines.append(f"corp_code_map_cache_read_warn={type(exc).__name__}: {exc}")

    url = "https://opendart.fss.or.kr/api/corpCode.xml?" + urllib.parse.urlencode(
        {"crtfc_key": api_key}
    )
    data = urlopen_bytes(url, timeout=30)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        xml_name = names[0]
        xml_bytes = zf.read(xml_name)

    root = ET.fromstring(xml_bytes)
    records: List[Dict[str, str]] = []
    mapping: Dict[str, Dict[str, str]] = {}

    for item in root.findall("list"):
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = clean_ticker(item.findtext("stock_code") or "")

        if not stock_code:
            continue

        record = {
            "corp_code": corp_code.zfill(8),
            "corp_name": corp_name,
            "stock_code": stock_code,
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        records.append(record)
        mapping[stock_code] = {
            "corp_code": corp_code.zfill(8),
            "corp_name": corp_name,
        }

    pd.DataFrame(records).to_csv(cache_path, index=False, encoding="utf-8-sig")
    log_lines.append(f"corp_code_map_source=opendart, rows={len(mapping)}")
    return mapping


def choose_operating_profit_item(items: List[Dict[str, Any]], reprt_code: str) -> Optional[Dict[str, Any]]:
    candidates = []

    for item in items:
        account_nm = str(item.get("account_nm", "")).strip()
        sj_div = str(item.get("sj_div", "")).strip()
        fs_div = str(item.get("fs_div", "")).strip()

        if "영업" not in account_nm:
            continue
        if "이익" not in account_nm and "손실" not in account_nm:
            continue
        if sj_div and sj_div != "IS":
            continue

        amount_key_order = ["thstrm_amount"]
        if reprt_code in {"11013", "11012", "11014"}:
            amount_key_order = ["thstrm_add_amount", "thstrm_amount"]

        amount = None
        amount_key = ""
        for key in amount_key_order:
            amount = parse_amount(item.get(key))
            if amount is not None:
                amount_key = key
                break

        if amount is None:
            continue

        priority = 0
        if fs_div == "CFS":
            priority += 20
        if account_nm in {"영업이익", "영업이익(손실)"}:
            priority += 10
        if amount_key == "thstrm_add_amount":
            priority += 3

        candidates.append((priority, item, amount, amount_key))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, item, amount, amount_key = candidates[0]
    selected = dict(item)
    selected["_parsed_amount"] = amount
    selected["_amount_key"] = amount_key
    return selected


def blank_result(ticker: str, target_key: str, source_status: str, corp_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    corp_info = corp_info or {}
    return {
        "ticker": ticker,
        "corp_code": str(corp_info.get("corp_code", "")),
        "corp_name": str(corp_info.get("corp_name", "")),
        "operating_profit": "",
        "operating_profit_unit": "KRW",
        "operating_loss_flag": "",
        "operating_loss_basis": "",
        "operating_loss_source_status": source_status,
        "account_nm": "",
        "fs_div": "",
        "sj_div": "",
        "bsns_year": "",
        "reprt_code": "",
        "target_period_key": target_key,
        "fetched_at_kst": now_kst().isoformat(timespec="seconds"),
    }


def fetch_operating_profit_for_ticker(
    ticker: str,
    corp_info: Dict[str, str],
    api_key: str,
    periods: List[Tuple[str, str]],
    target_key: str,
    timeout: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    corp_code = corp_info.get("corp_code", "")
    corp_name = corp_info.get("corp_name", "")

    if not corp_code:
        return blank_result(ticker, target_key, "NO_CORP_CODE", corp_info)

    last_status = ""

    for bsns_year, reprt_code in periods:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }
        url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?" + urllib.parse.urlencode(params)

        try:
            raw = urlopen_bytes(url, timeout=timeout)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            last_status = f"FETCH_ERROR_{type(exc).__name__}"
            continue

        status = str(payload.get("status", ""))
        message = str(payload.get("message", ""))
        last_status = f"API_STATUS_{status}:{message}"

        if status != "000":
            continue

        items = payload.get("list", [])
        selected = choose_operating_profit_item(items, reprt_code)
        if selected is None:
            last_status = "NO_OPERATING_PROFIT_ITEM"
            continue

        amount = selected.get("_parsed_amount")
        loss_flag = bool(amount is not None and amount < 0)

        return {
            "ticker": ticker,
            "corp_code": corp_code,
            "corp_name": corp_name,
            "operating_profit": amount if amount is not None else "",
            "operating_profit_unit": "KRW",
            "operating_loss_flag": loss_flag,
            "operating_loss_basis": report_label(bsns_year, reprt_code),
            "operating_loss_source_status": "OK",
            "account_nm": selected.get("account_nm", ""),
            "fs_div": selected.get("fs_div", ""),
            "sj_div": selected.get("sj_div", ""),
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "target_period_key": target_key,
            "fetched_at_kst": now_kst().isoformat(timespec="seconds"),
        }

    return blank_result(ticker, target_key, last_status or "NO_FINANCIAL_DATA", corp_info)


def read_cache(cache_path: Path, target_key: str) -> Dict[str, Dict[str, Any]]:
    if not cache_path.exists():
        return {}

    try:
        df = pd.read_csv(cache_path, encoding="utf-8-sig", dtype=str).fillna("")
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(cache_path, dtype=str).fillna("")
        except Exception:
            return {}
    except Exception:
        return {}

    if "ticker" not in df.columns or "target_period_key" not in df.columns:
        return {}

    df = df[df["target_period_key"].astype(str).eq(target_key)].copy()

    cache: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        ticker = clean_ticker(row.get("ticker", ""))
        if not ticker:
            continue

        record = row.to_dict()
        flag_text = str(record.get("operating_loss_flag", "")).lower()
        if flag_text in {"true", "1", "yes", "y"}:
            record["operating_loss_flag"] = True
        elif flag_text in {"false", "0", "no", "n"}:
            record["operating_loss_flag"] = False

        cache[ticker] = record

    return cache


def collect_tickers_from_files(output_dir: Path, target_files: List[str]) -> List[str]:
    tickers = set()

    for filename in target_files:
        path = output_dir / filename
        df = read_csv_safe(path)
        if df.empty:
            continue

        ticker_col = get_ticker_column(df)
        if not ticker_col:
            continue

        for value in df[ticker_col].dropna().tolist():
            ticker = clean_ticker(value)
            if ticker:
                tickers.add(ticker)

    return sorted(tickers)


def normalize_bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return "TRUE"
    if text in {"false", "0", "no", "n"}:
        return "FALSE"
    return ""


def enrich_csv_file(path: Path, result_map: Dict[str, Dict[str, Any]]) -> Tuple[str, int, int]:
    if not path.exists():
        return "missing", 0, 0

    df = read_csv_safe(path)
    if df.empty:
        return "empty_or_read_error", 0, 0

    ticker_col = get_ticker_column(df)
    if not ticker_col:
        return "no_ticker_column", len(df), 0

    for col in [
        "operating_profit",
        "operating_profit_unit",
        "operating_loss_flag",
        "operating_loss_basis",
        "operating_loss_source_status",
    ]:
        if col not in df.columns:
            df[col] = ""

    matched = 0
    for idx, value in df[ticker_col].items():
        ticker = clean_ticker(value)
        if not ticker:
            continue

        record = result_map.get(ticker)
        if not record:
            continue

        df.at[idx, "operating_profit"] = str(record.get("operating_profit", ""))
        df.at[idx, "operating_profit_unit"] = str(record.get("operating_profit_unit", "KRW"))
        df.at[idx, "operating_loss_flag"] = normalize_bool_text(record.get("operating_loss_flag", ""))
        df.at[idx, "operating_loss_basis"] = str(record.get("operating_loss_basis", ""))
        df.at[idx, "operating_loss_source_status"] = str(record.get("operating_loss_source_status", ""))
        matched += 1

    df.to_csv(path, index=False, encoding="utf-8-sig")
    return "ok", len(df), matched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--max-api-calls", type=int, default=5000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at_kst={now_kst().isoformat(timespec='seconds')}",
        f"output_dir={output_dir}",
        f"workers={args.workers}",
        f"max_api_calls={args.max_api_calls}",
    ]

    periods = candidate_report_periods()
    target_key = target_period_key(periods)
    log_lines.append("candidate_periods=" + ",".join([f"{y}_{code}" for y, code in periods]))
    log_lines.append(f"target_period_key={target_key}")

    api_key = os.environ.get("DART_API_KEY", "").strip()
    cache_path = output_dir / "operating_loss_cache_latest.csv"
    run_log_path = output_dir / "operating_loss_run_log_latest.txt"

    tickers = collect_tickers_from_files(output_dir, TARGET_CSV_FILES)
    log_lines.append(f"target_tickers={len(tickers)}")

    if not tickers:
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        empty.to_csv(cache_path, index=False, encoding="utf-8-sig")
        log_lines.append("status=ERROR")
        log_lines.append("error=NO_TARGET_TICKERS")
        run_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        return

    cache = read_cache(cache_path, target_key)
    log_lines.append(f"cache_rows_for_target={len(cache)}")

    result_map: Dict[str, Dict[str, Any]] = {}

    if not api_key:
        log_lines.append("status=WARN_NO_DART_API_KEY")
        log_lines.append("message=DART_API_KEY가 없어 기존 CSV에 빈 영업손실 컬럼만 추가합니다.")
        for ticker in tickers:
            result_map[ticker] = blank_result(ticker, target_key, "NO_DART_API_KEY")
    else:
        corp_map = load_corp_code_map(api_key, output_dir, log_lines)
        to_fetch = []

        for ticker in tickers:
            if ticker in cache and str(cache[ticker].get("operating_loss_source_status", "")) == "OK":
                result_map[ticker] = cache[ticker]
            else:
                to_fetch.append(ticker)

        if len(to_fetch) > args.max_api_calls:
            log_lines.append(f"api_call_limit_applied={args.max_api_calls}, original_to_fetch={len(to_fetch)}")
            to_fetch = to_fetch[: args.max_api_calls]

        log_lines.append(f"cache_hit_ok={len(result_map)}")
        log_lines.append(f"to_fetch={len(to_fetch)}")

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {
                executor.submit(
                    fetch_operating_profit_for_ticker,
                    ticker,
                    corp_map.get(ticker, {}),
                    api_key,
                    periods,
                    target_key,
                    args.timeout,
                    args.sleep_seconds,
                ): ticker
                for ticker in to_fetch
            }

            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = blank_result(
                        ticker,
                        target_key,
                        f"UNHANDLED_ERROR_{type(exc).__name__}",
                    )
                result_map[ticker] = result

    output_records = []
    for ticker in sorted(result_map.keys()):
        record = {col: result_map[ticker].get(col, "") for col in OUTPUT_COLUMNS}
        record["ticker"] = ticker
        output_records.append(record)

    cache_df = pd.DataFrame(output_records, columns=OUTPUT_COLUMNS)
    cache_df.to_csv(cache_path, index=False, encoding="utf-8-sig")

    status_counts = cache_df["operating_loss_source_status"].value_counts().to_dict() if not cache_df.empty else {}
    loss_count = 0
    if not cache_df.empty:
        loss_count = int(
            cache_df["operating_loss_flag"].astype(str).str.lower().isin(["true", "1", "yes"]).sum()
        )

    log_lines.append(f"cache_output_rows={len(cache_df)}")
    log_lines.append(f"operating_loss_count={loss_count}")
    log_lines.append(f"source_status_counts={status_counts}")

    enriched_files = 0
    for filename in TARGET_CSV_FILES:
        path = output_dir / filename
        status, rows, matched = enrich_csv_file(path, result_map)
        if status == "ok":
            enriched_files += 1
        log_lines.append(f"ENRICH_FILE {filename}: status={status}, rows={rows}, matched={matched}")

    log_lines.append(f"enriched_files={enriched_files}")
    log_lines.append("status=OK")
    run_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("OPERATING_LOSS_ENRICHMENT_STATUS=OK")
    print(f"OPERATING_LOSS_COUNT={loss_count}")
    print(f"ENRICHED_FILES={enriched_files}")


if __name__ == "__main__":
    main()
