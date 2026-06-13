#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
dart_fx_exposure_kospi.py v2.0_corp_code_cache_safe

목적
- 코스피 종목별 DART corp_code를 latest/dart_corp_code_cache_latest.csv에서 정확히 매칭한다.
- OpenDART 정기보고서 목록과 문서 원문에서 환율노출 관련 단서를 추출한다.
- 달러/해외매출, 환율민감도, 환헤지, 외화부채, 수입원가 부담을 점수화한다.
- 기존 KRX 코스피 universe 파일과 결합해 환율약세 후보 30개와 추천 7개를 생성한다.

중요한 개선점
- 종목코드 6자리와 DART corp_code를 혼동하지 않는다.
- DART corp_code 캐시 파일을 우선 사용한다.
- 오래 걸릴 경우 외부 timeout 전에 부분 결과를 저장한다.
- 실패 종목이 있어도 전체 작업이 중단되지 않는다.

입력 파일
- latest/dart_corp_code_cache_latest.csv
- latest/kospi_universe_summary_current_basis_latest.csv 또는 latest/kospi_universe_summary_latest.csv

생성 파일
- latest/kospi_fx_exposure_raw_latest.csv
- latest/kospi_fx_exposure_precision_latest.csv
- latest/kospi_fx_weakness_candidates_30_latest.csv
- latest/kospi_fx_weakness_recommend_7_latest.csv
- latest/kospi_fx_exposure_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import pandas as pd
import requests


SCRIPT_VERSION = "v2.0_corp_code_cache_safe"

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

OUTPUT_RAW = "kospi_fx_exposure_raw_latest.csv"
OUTPUT_PRECISION = "kospi_fx_exposure_precision_latest.csv"
OUTPUT_CANDIDATES = "kospi_fx_weakness_candidates_30_latest.csv"
OUTPUT_RECOMMEND = "kospi_fx_weakness_recommend_7_latest.csv"
OUTPUT_LOG = "kospi_fx_exposure_run_log_latest.txt"

CORP_CACHE_FILE = "dart_corp_code_cache_latest.csv"


POSITIVE_KEYWORDS = {
    "export": [
        "수출",
        "해외매출",
        "해외 매출",
        "국외매출",
        "국외 매출",
        "외화매출",
        "외화 매출",
        "해외시장",
        "글로벌",
        "미국",
        "북미",
        "유럽",
        "중국",
        "동남아",
        "달러",
        "USD",
    ],
    "fx_sensitivity": [
        "환율",
        "환율변동",
        "환율 변동",
        "외환위험",
        "외환 위험",
        "환위험",
        "환 위험",
        "외화위험",
        "외화 위험",
        "외화자산",
        "외화 자산",
        "외화부채",
        "외화 부채",
        "환산손익",
        "외환손익",
    ],
    "hedge": [
        "환헤지",
        "환 헤지",
        "통화선도",
        "선물환",
        "파생상품",
        "위험회피",
        "위험 회피",
        "현금흐름위험회피",
        "공정가치위험회피",
    ],
}

NEGATIVE_KEYWORDS = {
    "foreign_debt": [
        "외화부채",
        "외화 부채",
        "외화차입",
        "외화 차입",
        "외화차입금",
        "외화 차입금",
        "외환손실",
        "외환 손실",
        "환산손실",
        "환산 손실",
    ],
    "import_cost": [
        "원재료 수입",
        "수입 원재료",
        "수입원재료",
        "수입가격",
        "수입 가격",
        "외화매입",
        "외화 매입",
        "달러매입",
        "달러 매입",
        "달러 원가",
        "외화 원가",
    ],
}

REPORT_KEYWORDS = [
    "사업보고서",
    "반기보고서",
    "분기보고서",
]


def now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def now_kst_text() -> str:
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S%z")


def normalize_stock_code(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""

    text = text.replace(".0", "")
    text = re.sub(r"[^0-9]", "", text)

    if not text:
        return ""

    return text.zfill(6)[-6:]


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return text.strip()


def parse_number(value: Any) -> float:
    text = normalize_text(value)
    if not text:
        return 0.0

    text = text.replace(",", "")
    text = text.replace("%", "")
    text = text.replace("원", "")
    text = text.replace("약", "")
    text = text.strip()

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0

    try:
        return float(match.group(0))
    except Exception:
        return 0.0


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    cols = [str(c) for c in columns]

    for cand in candidates:
        for col in cols:
            if col == cand:
                return col

    for cand in candidates:
        for col in cols:
            if cand.lower() in col.lower():
                return col

    return None


def detect_stock_code_from_row(row: pd.Series) -> str:
    for value in row.values:
        code = normalize_stock_code(value)
        if len(code) == 6:
            return code
    return ""


def load_universe(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"universe file not found: {path}")

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df = df.fillna("")

    columns = list(df.columns)

    code_col = find_column(
        columns,
        [
            "종목코드",
            "단축코드",
            "stock_code",
            "ticker",
            "code",
            "symbol",
            "종목번호",
        ],
    )
    name_col = find_column(
        columns,
        [
            "종목명",
            "종목",
            "회사명",
            "corp_name",
            "name",
            "기업명",
        ],
    )
    price_col = find_column(
        columns,
        [
            "현재가 기준",
            "현재가",
            "current_price",
            "close",
            "종가",
            "기준가",
        ],
    )
    score_col = find_column(
        columns,
        [
            "score",
            "점수",
            "종합점수",
            "total_score",
            "quality_score",
        ],
    )

    stock_codes = []
    names = []
    prices = []
    base_scores = []

    for _, row in df.iterrows():
        if code_col:
            code = normalize_stock_code(row.get(code_col, ""))
        else:
            code = detect_stock_code_from_row(row)

        if name_col:
            name = normalize_text(row.get(name_col, ""))
        else:
            name = ""

        if not name:
            # 코드 컬럼이 아닌 문자형 값 중 가장 그럴듯한 값을 이름 후보로 사용
            for value in row.values:
                text = normalize_text(value)
                if text and not normalize_stock_code(text) and len(text) <= 40:
                    name = text
                    break

        price = parse_number(row.get(price_col, "")) if price_col else 0.0
        base_score = parse_number(row.get(score_col, "")) if score_col else 0.0

        stock_codes.append(code)
        names.append(name)
        prices.append(price)
        base_scores.append(base_score)

    out = df.copy()
    out["_stock_code"] = stock_codes
    out["_stock_name"] = names
    out["_current_price"] = prices
    out["_base_score"] = base_scores

    out = out[out["_stock_code"].astype(str).str.len() == 6].copy()
    out = out.drop_duplicates(subset=["_stock_code"], keep="first").reset_index(drop=True)

    if out.empty:
        raise RuntimeError(f"No valid 6-digit stock code found in universe file: {path}")

    return out


def load_corp_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"DART corp code cache not found: {path}")

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")

    required = {"corp_code", "stock_code"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"DART corp cache missing columns: {sorted(missing)}")

    mapping: dict[str, dict[str, str]] = {}

    for _, row in df.iterrows():
        stock_code = normalize_stock_code(row.get("stock_code", ""))
        corp_code = normalize_text(row.get("corp_code", ""))
        corp_name = normalize_text(row.get("corp_name", ""))

        if not stock_code or not corp_code:
            continue

        mapping[stock_code] = {
            "corp_code": corp_code,
            "corp_name": corp_name,
            "modify_date": normalize_text(row.get("modify_date", "")),
        }

    if not mapping:
        raise RuntimeError(f"DART corp cache has no valid stock_code/corp_code mapping: {path}")

    return mapping


def dart_get_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: int,
    retry: int = 2,
    sleep_seconds: float = 0.2,
) -> dict[str, Any]:
    last_error = ""

    for attempt in range(1, retry + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            text = resp.text

            if resp.status_code != 200:
                last_error = f"HTTP_{resp.status_code}"
                time.sleep(sleep_seconds)
                continue

            try:
                return resp.json()
            except Exception:
                last_error = f"JSON_PARSE_FAIL:{text[:200]}"
                time.sleep(sleep_seconds)

        except Exception as e:
            last_error = f"{type(e).__name__}:{e}"
            time.sleep(sleep_seconds)

    return {
        "status": "LOCAL_ERROR",
        "message": last_error,
        "list": [],
    }


def find_latest_periodic_report(
    session: requests.Session,
    api_key: str,
    corp_code: str,
    bgn_de: str,
    end_de: str,
    timeout: int,
    sleep_seconds: float,
) -> tuple[dict[str, Any] | None, str]:
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "pblntf_ty": "A",
        "page_no": "1",
        "page_count": "20",
    }

    data = dart_get_json(
        session=session,
        url=DART_LIST_URL,
        params=params,
        timeout=timeout,
        retry=2,
        sleep_seconds=sleep_seconds,
    )

    status = normalize_text(data.get("status"))
    message = normalize_text(data.get("message"))

    if status != "000":
        return None, f"DART_LIST_{status}_{message}"

    items = data.get("list") or []

    periodic = []
    for item in items:
        report_nm = normalize_text(item.get("report_nm"))
        if any(keyword in report_nm for keyword in REPORT_KEYWORDS):
            periodic.append(item)

    if not periodic:
        return None, "NO_RECENT_PERIODIC_REPORT"

    periodic.sort(
        key=lambda x: (
            normalize_text(x.get("rcept_dt")),
            normalize_text(x.get("rcept_no")),
        ),
        reverse=True,
    )

    return periodic[0], "OK"


def decode_bytes(data: bytes) -> str:
    for enc in ["utf-8", "cp949", "euc-kr", "latin1"]:
        try:
            return data.decode(enc, errors="replace")
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def strip_markup(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_report_text(
    session: requests.Session,
    api_key: str,
    rcept_no: str,
    timeout: int,
    max_chars: int,
    sleep_seconds: float,
) -> tuple[str, str]:
    params = {
        "crtfc_key": api_key,
        "rcept_no": rcept_no,
    }

    try:
        resp = session.get(DART_DOCUMENT_URL, params=params, timeout=timeout)
        content = resp.content or b""

        if resp.status_code != 200:
            return "", f"DART_DOC_HTTP_{resp.status_code}"

        if content[:2] != b"PK":
            text = decode_bytes(content)
            # OpenDART 오류 XML이 올 수 있음
            status_match = re.search(r"<status>(.*?)</status>", text)
            msg_match = re.search(r"<message>(.*?)</message>", text)
            if status_match or msg_match:
                status = status_match.group(1) if status_match else "UNKNOWN"
                message = msg_match.group(1) if msg_match else ""
                return "", f"DART_DOC_{status}_{message}"
            return strip_markup(text)[:max_chars], "OK_TEXT"

        pieces = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()

            # XML/HTML/TXT 우선. 이미지/PDF는 제외.
            text_files = [
                n for n in names
                if n.lower().endswith((".xml", ".html", ".htm", ".txt"))
            ]

            for name in text_files[:20]:
                try:
                    raw = zf.read(name)
                    decoded = decode_bytes(raw)
                    cleaned = strip_markup(decoded)
                    if cleaned:
                        pieces.append(cleaned)
                    if sum(len(p) for p in pieces) >= max_chars:
                        break
                except Exception:
                    continue

        text = " ".join(pieces)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return "", "DART_DOC_EMPTY_ZIP_TEXT"

        time.sleep(sleep_seconds)
        return text[:max_chars], "OK_ZIP"

    except Exception as e:
        return "", f"DART_DOC_ERROR_{type(e).__name__}:{e}"


def count_keywords(text: str, keywords: list[str]) -> int:
    if not text:
        return 0

    count = 0
    lowered = text.lower()

    for keyword in keywords:
        if re.search(r"[A-Za-z]", keyword):
            count += lowered.count(keyword.lower())
        else:
            count += text.count(keyword)

    return count


def make_snippet(text: str, keywords: list[str], width: int = 90) -> str:
    if not text:
        return ""

    for keyword in keywords:
        pos = text.find(keyword)
        if pos >= 0:
            start = max(0, pos - width)
            end = min(len(text), pos + len(keyword) + width)
            snippet = text[start:end]
            snippet = re.sub(r"\s+", " ", snippet).strip()
            return snippet[:240]

    return ""


def analyze_text(text: str) -> dict[str, Any]:
    export_hits = count_keywords(text, POSITIVE_KEYWORDS["export"])
    fx_hits = count_keywords(text, POSITIVE_KEYWORDS["fx_sensitivity"])
    hedge_hits = count_keywords(text, POSITIVE_KEYWORDS["hedge"])
    debt_hits = count_keywords(text, NEGATIVE_KEYWORDS["foreign_debt"])
    import_hits = count_keywords(text, NEGATIVE_KEYWORDS["import_cost"])

    positive_score = 0
    positive_score += min(export_hits, 12) * 3
    positive_score += min(fx_hits, 15) * 2
    positive_score += min(hedge_hits, 8) * 1

    negative_score = 0
    negative_score += min(debt_hits, 10) * 2
    negative_score += min(import_hits, 8) * 2

    # 환헤지는 수혜 폭을 줄일 수 있지만 리스크 관리 신뢰도는 높인다.
    hedge_control_score = min(hedge_hits, 6)

    fx_exposure_score = positive_score - negative_score + hedge_control_score
    fx_exposure_score = max(-40, min(80, fx_exposure_score))

    all_keywords = (
        POSITIVE_KEYWORDS["export"]
        + POSITIVE_KEYWORDS["fx_sensitivity"]
        + POSITIVE_KEYWORDS["hedge"]
        + NEGATIVE_KEYWORDS["foreign_debt"]
        + NEGATIVE_KEYWORDS["import_cost"]
    )

    return {
        "export_hits": export_hits,
        "fx_hits": fx_hits,
        "hedge_hits": hedge_hits,
        "foreign_debt_hits": debt_hits,
        "import_cost_hits": import_hits,
        "fx_exposure_score": fx_exposure_score,
        "evidence_snippet": make_snippet(text, all_keywords),
    }


def confidence_grade(
    *,
    corp_code_found: bool,
    report_found: bool,
    document_status: str,
    text_length: int,
    total_hits: int,
) -> str:
    if not corp_code_found:
        return "D"

    if not report_found:
        return "C"

    if document_status.startswith("OK") and text_length >= 20000 and total_hits >= 10:
        return "A"

    if document_status.startswith("OK") and text_length >= 5000 and total_hits >= 3:
        return "B"

    if document_status.startswith("OK"):
        return "C"

    return "D"


def confidence_bonus(grade: str) -> int:
    if grade == "A":
        return 20
    if grade == "B":
        return 12
    if grade == "C":
        return 4
    return -15


def status_icon(row: dict[str, Any]) -> str:
    grade = row.get("confidence", "D")
    score = float(row.get("final_score", 0) or 0)
    negative = float(row.get("negative_score", 0) or 0)

    if grade in {"A", "B"} and score >= 70 and negative <= 18:
        return "✅"
    if grade in {"A", "B", "C"} and score >= 45:
        return "🟡"
    if grade == "D":
        return "⚠️"
    return "🟡"


def build_reason(row: dict[str, Any]) -> str:
    pieces = []

    if row.get("corp_code"):
        pieces.append("DART corp_code 매칭")
    else:
        pieces.append("DART corp_code 미매칭")

    if row.get("report_nm"):
        pieces.append(f"최근 보고서: {row.get('report_nm')}")
    else:
        pieces.append("최근 정기보고서 확인 부족")

    export_hits = int(row.get("export_hits", 0) or 0)
    fx_hits = int(row.get("fx_hits", 0) or 0)
    hedge_hits = int(row.get("hedge_hits", 0) or 0)
    debt_hits = int(row.get("foreign_debt_hits", 0) or 0)
    import_hits = int(row.get("import_cost_hits", 0) or 0)

    if export_hits or fx_hits:
        pieces.append(f"수출/해외·환율 단서 {export_hits + fx_hits}건")

    if hedge_hits:
        pieces.append(f"환헤지/파생상품 단서 {hedge_hits}건")

    if debt_hits or import_hits:
        pieces.append(f"외화부채·수입원가 부담 단서 {debt_hits + import_hits}건")

    confidence = row.get("confidence", "D")
    pieces.append(f"공시신뢰도 {confidence}")

    return " / ".join(pieces)


def safe_to_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_outputs(output_dir: Path, rows: list[dict[str, Any]], run_meta: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_df = pd.DataFrame(rows)

    if raw_df.empty:
        raw_df = pd.DataFrame(
            columns=[
                "stock_code",
                "stock_name",
                "corp_code",
                "corp_name",
                "status",
                "confidence",
                "final_score",
            ]
        )

    # 점수 계산 보정
    if "final_score" not in raw_df.columns:
        raw_df["final_score"] = 0

    raw_df["final_score"] = pd.to_numeric(raw_df["final_score"], errors="coerce").fillna(0)
    raw_df = raw_df.sort_values(
        by=["final_score", "confidence", "stock_code"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    precision_cols = [
        "추천표시",
        "stock_code",
        "stock_name",
        "current_price",
        "corp_code",
        "corp_name",
        "report_nm",
        "rcept_dt",
        "confidence",
        "fx_exposure_score",
        "base_score",
        "negative_score",
        "final_score",
        "export_hits",
        "fx_hits",
        "hedge_hits",
        "foreign_debt_hits",
        "import_cost_hits",
        "status",
        "document_status",
        "reason",
        "evidence_snippet",
    ]

    for col in precision_cols:
        if col not in raw_df.columns:
            raw_df[col] = ""

    precision_df = raw_df[precision_cols].copy()

    candidates_df = precision_df.head(30).copy()
    recommend_df = precision_df.head(7).copy()

    safe_to_csv(raw_df, output_dir / OUTPUT_RAW)
    safe_to_csv(precision_df, output_dir / OUTPUT_PRECISION)
    safe_to_csv(candidates_df, output_dir / OUTPUT_CANDIDATES)
    safe_to_csv(recommend_df, output_dir / OUTPUT_RECOMMEND)

    status_counts = Counter(raw_df.get("status", pd.Series(dtype=str)).astype(str).tolist())
    confidence_counts = Counter(raw_df.get("confidence", pd.Series(dtype=str)).astype(str).tolist())

    log_lines = [
        f"script=dart_fx_exposure_kospi.py {SCRIPT_VERSION}",
        f"run_at_kst={now_kst_text()}",
        f"status={run_meta.get('status', 'OK')}",
        f"universe={run_meta.get('universe', '')}",
        f"corp_cache={run_meta.get('corp_cache', '')}",
        f"lookback_days={run_meta.get('lookback_days', '')}",
        f"bgn_de={run_meta.get('bgn_de', '')}",
        f"end_de={run_meta.get('end_de', '')}",
        f"processed_rows={len(raw_df)}",
        f"candidate_rows={len(candidates_df)}",
        f"recommend_rows={len(recommend_df)}",
        f"status_counts={dict(status_counts)}",
        f"confidence_counts={dict(confidence_counts)}",
        f"elapsed_seconds={run_meta.get('elapsed_seconds', '')}",
        f"partial_timeout={run_meta.get('partial_timeout', False)}",
        f"max_symbols={run_meta.get('max_symbols', 0)}",
        f"max_runtime_minutes={run_meta.get('max_runtime_minutes', 0)}",
        f"error={run_meta.get('error', '')}",
        f"raw={OUTPUT_RAW}",
        f"precision={OUTPUT_PRECISION}",
        f"candidates={OUTPUT_CANDIDATES}",
        f"recommend={OUTPUT_RECOMMEND}",
    ]

    (output_dir / OUTPUT_LOG).write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def analyze_one_company(
    *,
    session: requests.Session,
    api_key: str,
    stock_code: str,
    stock_name: str,
    current_price: float,
    base_score: float,
    corp_info: dict[str, str] | None,
    bgn_de: str,
    end_de: str,
    list_timeout: int,
    doc_timeout: int,
    max_doc_chars: int,
    sleep_seconds: float,
    download_documents: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "current_price": current_price,
        "base_score": base_score,
        "corp_code": "",
        "corp_name": "",
        "report_nm": "",
        "rcept_no": "",
        "rcept_dt": "",
        "status": "",
        "document_status": "",
        "confidence": "D",
        "export_hits": 0,
        "fx_hits": 0,
        "hedge_hits": 0,
        "foreign_debt_hits": 0,
        "import_cost_hits": 0,
        "fx_exposure_score": 0,
        "negative_score": 0,
        "final_score": 0,
        "evidence_snippet": "",
        "reason": "",
        "추천표시": "",
    }

    if not corp_info:
        row["status"] = "NO_CORP_CODE"
        row["document_status"] = "NO_CORP_CODE"
        row["confidence"] = "D"
        row["negative_score"] = 0
        row["final_score"] = base_score + confidence_bonus("D")
        row["추천표시"] = status_icon(row)
        row["reason"] = build_reason(row)
        return row

    corp_code = normalize_text(corp_info.get("corp_code"))
    corp_name = normalize_text(corp_info.get("corp_name"))

    row["corp_code"] = corp_code
    row["corp_name"] = corp_name

    report, list_status = find_latest_periodic_report(
        session=session,
        api_key=api_key,
        corp_code=corp_code,
        bgn_de=bgn_de,
        end_de=end_de,
        timeout=list_timeout,
        sleep_seconds=sleep_seconds,
    )

    if not report:
        row["status"] = list_status
        row["document_status"] = "NO_DOCUMENT"
        row["confidence"] = confidence_grade(
            corp_code_found=True,
            report_found=False,
            document_status="NO_DOCUMENT",
            text_length=0,
            total_hits=0,
        )
        row["negative_score"] = 0
        row["final_score"] = base_score + confidence_bonus(row["confidence"])
        row["추천표시"] = status_icon(row)
        row["reason"] = build_reason(row)
        time.sleep(sleep_seconds)
        return row

    report_nm = normalize_text(report.get("report_nm"))
    rcept_no = normalize_text(report.get("rcept_no"))
    rcept_dt = normalize_text(report.get("rcept_dt"))

    row["report_nm"] = report_nm
    row["rcept_no"] = rcept_no
    row["rcept_dt"] = rcept_dt

    if not download_documents:
        row["status"] = "OK_REPORT_LIST_ONLY"
        row["document_status"] = "SKIPPED_DOCUMENT_DOWNLOAD"
        row["confidence"] = "C"
        row["final_score"] = base_score + confidence_bonus("C")
        row["추천표시"] = status_icon(row)
        row["reason"] = build_reason(row)
        return row

    text, doc_status = fetch_report_text(
        session=session,
        api_key=api_key,
        rcept_no=rcept_no,
        timeout=doc_timeout,
        max_chars=max_doc_chars,
        sleep_seconds=sleep_seconds,
    )

    analysis = analyze_text(text)
    row.update(analysis)

    total_hits = (
        int(row["export_hits"])
        + int(row["fx_hits"])
        + int(row["hedge_hits"])
        + int(row["foreign_debt_hits"])
        + int(row["import_cost_hits"])
    )

    negative_score = min(
        40,
        int(row["foreign_debt_hits"]) * 2 + int(row["import_cost_hits"]) * 2,
    )

    row["negative_score"] = negative_score
    row["document_status"] = doc_status
    row["status"] = "OK" if doc_status.startswith("OK") else doc_status
    row["confidence"] = confidence_grade(
        corp_code_found=True,
        report_found=True,
        document_status=doc_status,
        text_length=len(text),
        total_hits=total_hits,
    )

    # base_score가 없으면 50점을 중립값으로 사용
    base_component = base_score if base_score else 50

    row["final_score"] = (
        base_component
        + float(row["fx_exposure_score"])
        + confidence_bonus(row["confidence"])
        - negative_score * 0.35
    )

    row["추천표시"] = status_icon(row)
    row["reason"] = build_reason(row)

    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--universe", default="")
    parser.add_argument("--lookback-days", type=int, default=370)
    parser.add_argument("--sleep", type=float, default=0.20)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-runtime-minutes", type=float, default=42.0)
    parser.add_argument("--list-timeout", type=int, default=12)
    parser.add_argument("--doc-timeout", type=int, default=18)
    parser.add_argument("--max-doc-chars", type=int, default=500000)
    parser.add_argument("--no-download-documents", action="store_true")
    args = parser.parse_args()

    started = time.time()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("DART_API_KEY", "").strip()

    if not api_key:
        run_meta = {
            "status": "ERROR_DART_API_KEY_MISSING",
            "error": "DART_API_KEY environment variable is missing",
            "elapsed_seconds": round(time.time() - started, 2),
        }
        write_outputs(output_dir, [], run_meta)
        return 2

    if args.universe:
        universe_path = Path(args.universe)
    else:
        current_basis = output_dir / "kospi_universe_summary_current_basis_latest.csv"
        official_basis = output_dir / "kospi_universe_summary_latest.csv"
        universe_path = current_basis if current_basis.exists() else official_basis

    corp_cache_path = output_dir / CORP_CACHE_FILE

    end_dt = now_kst().date()
    bgn_dt = end_dt - timedelta(days=int(args.lookback_days))

    bgn_de = bgn_dt.strftime("%Y%m%d")
    end_de = end_dt.strftime("%Y%m%d")

    run_meta: dict[str, Any] = {
        "status": "OK",
        "universe": str(universe_path),
        "corp_cache": str(corp_cache_path),
        "lookback_days": args.lookback_days,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "max_symbols": args.max_symbols,
        "max_runtime_minutes": args.max_runtime_minutes,
        "partial_timeout": False,
        "error": "",
    }

    rows: list[dict[str, Any]] = []

    try:
        universe_df = load_universe(universe_path)
        corp_map = load_corp_cache(corp_cache_path)

        if args.max_symbols and args.max_symbols > 0:
            universe_df = universe_df.head(args.max_symbols).copy()

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "krx-watchlist-auto/2.0 (+https://github.com/sehwankim0114/krx-watchlist-auto)"
            }
        )

        deadline = None
        if args.max_runtime_minutes and args.max_runtime_minutes > 0:
            deadline = started + float(args.max_runtime_minutes) * 60

        total = len(universe_df)

        for idx, row in universe_df.iterrows():
            if deadline and time.time() >= deadline:
                run_meta["status"] = "PARTIAL_TIMEOUT"
                run_meta["partial_timeout"] = True
                break

            stock_code = normalize_stock_code(row.get("_stock_code", ""))
            stock_name = normalize_text(row.get("_stock_name", ""))
            current_price = float(row.get("_current_price", 0) or 0)
            base_score = float(row.get("_base_score", 0) or 0)

            corp_info = corp_map.get(stock_code)

            try:
                result = analyze_one_company(
                    session=session,
                    api_key=api_key,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    current_price=current_price,
                    base_score=base_score,
                    corp_info=corp_info,
                    bgn_de=bgn_de,
                    end_de=end_de,
                    list_timeout=args.list_timeout,
                    doc_timeout=args.doc_timeout,
                    max_doc_chars=args.max_doc_chars,
                    sleep_seconds=args.sleep,
                    download_documents=not args.no_download_documents,
                )
            except Exception as e:
                result = {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "current_price": current_price,
                    "base_score": base_score,
                    "corp_code": corp_info.get("corp_code", "") if corp_info else "",
                    "corp_name": corp_info.get("corp_name", "") if corp_info else "",
                    "report_nm": "",
                    "rcept_no": "",
                    "rcept_dt": "",
                    "status": f"LOCAL_ERROR_{type(e).__name__}",
                    "document_status": f"LOCAL_ERROR_{type(e).__name__}:{e}",
                    "confidence": "D",
                    "export_hits": 0,
                    "fx_hits": 0,
                    "hedge_hits": 0,
                    "foreign_debt_hits": 0,
                    "import_cost_hits": 0,
                    "fx_exposure_score": 0,
                    "negative_score": 0,
                    "final_score": base_score + confidence_bonus("D"),
                    "evidence_snippet": "",
                    "추천표시": "⚠️",
                    "reason": f"개별 종목 처리 오류: {type(e).__name__}",
                }

            rows.append(result)

            if (len(rows) % 25) == 0:
                print(f"processed={len(rows)}/{total} latest={stock_code} {stock_name}", flush=True)

            time.sleep(args.sleep)

        run_meta["elapsed_seconds"] = round(time.time() - started, 2)
        write_outputs(output_dir, rows, run_meta)

        print(f"status={run_meta['status']}")
        print(f"processed_rows={len(rows)}")
        print(f"elapsed_seconds={run_meta['elapsed_seconds']}")
        print(f"raw={output_dir / OUTPUT_RAW}")
        print(f"precision={output_dir / OUTPUT_PRECISION}")
        print(f"candidates={output_dir / OUTPUT_CANDIDATES}")
        print(f"recommend={output_dir / OUTPUT_RECOMMEND}")

        if run_meta["status"] == "PARTIAL_TIMEOUT":
            return 0

        return 0

    except Exception as e:
        run_meta["status"] = "ERROR"
        run_meta["error"] = f"{type(e).__name__}: {e}"
        run_meta["elapsed_seconds"] = round(time.time() - started, 2)

        try:
            write_outputs(output_dir, rows, run_meta)
        except Exception as write_error:
            print(f"OUTPUT_WRITE_ERROR {type(write_error).__name__}: {write_error}", file=sys.stderr)

        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
