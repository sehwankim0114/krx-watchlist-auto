#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
financial_valuation_enricher.py v1.1.0-corp-identity-fix

목적
- OpenDART 공식 기업코드표를 우선 내려받고 회사명까지 검증한다.
- 표에 필요한 최근 확정 실적·재무상태를 수집한다.
- KRX 시가총액·상장주식수와 결합해 기초 밸류에이션을 계산한다.
- 기존 임시 시장점수(legacy_market_score)와 v6 최종점수를 혼동하지 않는다.

생성/갱신 파일
- latest/financial_valuation_cache_latest.csv
- latest/financial_valuation_run_log_latest.txt
- 대상 latest/*.csv에 재무·밸류에이션 컬럼 추가

중요 원칙
- 재무자료가 없으면 추정값을 만들지 않는다.
- 적자기업의 PER는 숫자로 만들지 않는다.
- 분기·반기·3분기 누적순이익은 연환산 여부를 명시한다.
- 연결재무제표(CFS)를 우선하고, 없을 때만 개별재무제표(OFS)를 쓴다.
- OpenDART 조회 제한과 실제 기업 위험을 혼동하지 않는다.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import pandas as pd


SCRIPT_VERSION = "financial_valuation_enricher.py v1.1.0-corp-identity-fix"
POLICY_VERSION = "2026-07-01-v6.0-score-policy"
KST = ZoneInfo("Asia/Seoul")

DART_MAJOR_ACCOUNT_URL = (
    "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
)
DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

CACHE_FILENAME = "financial_valuation_cache_latest.csv"
RUN_LOG_FILENAME = "financial_valuation_run_log_latest.txt"

# 기업코드표는 OpenDART 공식 corpCode.xml을 최우선으로 사용한다.
# dart_corp_code_cache_latest.csv는 기업코드 원본표가 아닐 수 있으므로
# 재무·밸류에이션 수집에서는 절대 사용하지 않는다.
CORP_CODE_MAP_FILENAME = "dart_corp_code_map_latest.csv"

# 전체 KOSPI/KOSDAQ 유니버스는 시가총액·상장주식수 보조자료로만 읽는다.
MARKET_METRIC_FILES = (
    "kospi_universe_summary_latest.csv",
    "kosdaq_universe_summary_latest.csv",
)

# 실제 표에 등장할 수 있는 종목만 DART 조회 대상으로 삼는다.
# current_basis / supplemented 파일은 존재할 때 함께 갱신한다.
BASE_TARGET_FILES = (
    "watchlist_summary_latest.csv",
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
)

VARIANT_SUFFIXES = (
    "",
    "_current_basis",
    "_supplemented",
)

REPORT_NAMES = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}

FLOW_ANNUALIZATION_FACTORS = {
    "11013": 4.0,
    "11012": 2.0,
    "11014": 4.0 / 3.0,
    "11011": 1.0,
}

OUTPUT_COLUMNS = [
    "ticker",
    "name",
    "market",
    "corp_code",
    "corp_name",
    "corp_code_source",
    "corp_identity_status",
    "corp_identity_reason",
    "financial_data_status",
    "financial_source_status",
    "financial_basis",
    "financial_report_year",
    "financial_report_code",
    "financial_report_name",
    "financial_fs_div",
    "financial_currency",
    "revenue",
    "operating_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "previous_revenue",
    "previous_operating_profit",
    "previous_net_income",
    "revenue_yoy_pct",
    "operating_profit_yoy_pct",
    "net_income_yoy_pct",
    "operating_margin_pct",
    "debt_ratio_pct",
    "roe_annualized_pct",
    "earnings_trend",
    "market_cap",
    "listed_shares",
    "valuation_price_basis_date",
    "eps_annualized",
    "bps",
    "per_annualized",
    "pbr",
    "valuation_data_status",
    "valuation_basis",
    "financial_missing_fields",
    "target_period_key",
    "fetched_at_kst",
]

ENRICH_COLUMNS = [
    "corp_code",
    "corp_name",
    "corp_code_source",
    "corp_identity_status",
    "corp_identity_reason",
    "financial_data_status",
    "financial_source_status",
    "financial_basis",
    "financial_report_year",
    "financial_report_code",
    "financial_report_name",
    "financial_fs_div",
    "financial_currency",
    "revenue",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "previous_revenue",
    "previous_operating_profit",
    "previous_net_income",
    "revenue_yoy_pct",
    "operating_profit_yoy_pct",
    "net_income_yoy_pct",
    "operating_margin_pct",
    "debt_ratio_pct",
    "roe_annualized_pct",
    "earnings_trend",
    "market_cap",
    "listed_shares",
    "valuation_price_basis_date",
    "eps_annualized",
    "bps",
    "per_annualized",
    "pbr",
    "valuation_data_status",
    "valuation_basis",
    "financial_missing_fields",
]

# operating_profit 관련 기존 필드는 operating_loss_enricher.py와 호환되게 유지한다.
OPERATING_PROFIT_COMPAT_COLUMNS = [
    "operating_profit",
    "operating_profit_unit",
    "operating_loss_flag",
    "operating_loss_basis",
    "operating_loss_source_status",
]


@dataclass(frozen=True)
class AccountSpec:
    key: str
    statement: str
    exact_names: Tuple[str, ...]
    include_terms: Tuple[str, ...] = ()
    exclude_terms: Tuple[str, ...] = ()


ACCOUNT_SPECS = (
    AccountSpec(
        key="revenue",
        statement="IS",
        exact_names=(
            "매출액",
            "수익(매출액)",
            "영업수익",
            "보험영업수익",
            "영업수익(매출액)",
            "매출",
        ),
        include_terms=("수익",),
        exclude_terms=(
            "비용",
            "원가",
            "이자비용",
            "법인세",
            "기타",
            "금융수익",
        ),
    ),
    AccountSpec(
        key="operating_profit",
        statement="IS",
        exact_names=(
            "영업이익",
            "영업이익(손실)",
            "영업손익",
            "영업손실",
        ),
        include_terms=("영업",),
        exclude_terms=("중단",),
    ),
    AccountSpec(
        key="net_income",
        statement="IS",
        exact_names=(
            "당기순이익",
            "당기순이익(손실)",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
            "연결당기순이익",
            "연결당기순이익(손실)",
        ),
        include_terms=("순이익",),
        exclude_terms=(
            "지배기업",
            "비지배지분",
            "주당",
            "계속영업",
            "중단영업",
        ),
    ),
    AccountSpec(
        key="total_assets",
        statement="BS",
        exact_names=("자산총계", "자산 총계"),
        include_terms=("자산", "총계"),
        exclude_terms=("유동", "비유동"),
    ),
    AccountSpec(
        key="total_liabilities",
        statement="BS",
        exact_names=("부채총계", "부채 총계"),
        include_terms=("부채", "총계"),
        exclude_terms=("유동", "비유동"),
    ),
    AccountSpec(
        key="total_equity",
        statement="BS",
        exact_names=(
            "자본총계",
            "자본 총계",
            "지배기업의 소유주에게 귀속되는 자본",
        ),
        include_terms=("자본", "총계"),
        exclude_terms=("부채와자본", "부채및자본"),
    ),
)


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_text() -> str:
    return now_kst().isoformat(timespec="seconds")


def clean_ticker(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"[^0-9]", "", text)
    return text.zfill(6) if text else ""


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_company_name(value: Any) -> str:
    """회사명 비교용 정규화."""
    text = normalize_text(value).upper()
    replacements = (
        "주식회사",
        "(주)",
        "㈜",
        "CO.,LTD.",
        "CO., LTD.",
        "CO LTD",
        "CO.,LTD",
        "CORPORATION",
        "CORP.",
        "CORP",
        "INC.",
        "INC",
        "LIMITED",
        "LTD.",
        "LTD",
    )
    for token in replacements:
        text = text.replace(token, "")
    text = re.sub(r"[^0-9A-Z가-힣]", "", text)
    return text


def evaluate_corp_identity(
    target_name: Any,
    corp_name: Any,
    source: Any,
) -> Tuple[str, str]:
    """
    종목코드와 회사명 연결을 이중 확인한다.

    - 공식 OpenDART corpCode.xml에서 내려받은 종목코드 매핑은
      종목코드를 우선 신뢰하되 회사명 차이를 기록한다.
    - 캐시 대체자료에서 회사명이 다르면 사용하지 않는다.
    """
    target = normalize_company_name(target_name)
    corp = normalize_company_name(corp_name)
    source_text = normalize_text(source)

    if not target:
        return "NAME_NOT_AVAILABLE", "대상 표에 회사명이 없어 종목코드만 확인"
    if not corp:
        return "CORP_NAME_MISSING", "OpenDART 회사명 누락"
    if target == corp:
        return "MATCH", "종목코드와 회사명 일치"
    if target in corp or corp in target:
        return "MATCH_NORMALIZED", "법인표기 제거 후 회사명 일치"

    if source_text == "OPENDART_OFFICIAL_DOWNLOAD":
        return (
            "OFFICIAL_TICKER_NAME_DIFFERENCE",
            f"공식 종목코드 매핑이나 회사명 차이: {target_name} / {corp_name}",
        )

    return (
        "MISMATCH",
        f"캐시 회사명 불일치: {target_name} / {corp_name}",
    )


def normalize_account_name(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"[\s·ㆍ]", "", text)
    return text


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    if text.lower() in {"", "-", "nan", "none", "null", "n/a"}:
        return None

    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]

    text = (
        text.replace(",", "")
        .replace("원", "")
        .replace("KRW", "")
        .replace(" ", "")
    )
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None

    try:
        number = float(text)
    except ValueError:
        return None

    if not math.isfinite(number):
        return None
    if negative_parentheses:
        number = -abs(number)
    return number


def safe_round(value: Optional[float], digits: int = 2) -> Any:
    if value is None or not math.isfinite(float(value)):
        return ""
    return round(float(value), digits)


def safe_ratio_pct(
    numerator: Optional[float],
    denominator: Optional[float],
) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * 100.0


def safe_yoy_pct(
    current: Optional[float],
    previous: Optional[float],
) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def annualization_factor(report_code: str) -> float:
    return FLOW_ANNUALIZATION_FACTORS.get(report_code, 1.0)


def report_label(year: str, code: str) -> str:
    return f"{year} {REPORT_NAMES.get(code, code)}"


def candidate_report_periods(
    today: Optional[datetime] = None,
) -> List[Tuple[str, str]]:
    """
    법정 제출기한 직후부터 해당 보고서를 우선 조회한다.
    조회 결과가 없으면 이전 보고서로 순차 후퇴한다.
    """
    if today is None:
        today = now_kst()

    year = today.year
    month_day = (today.month, today.day)
    periods: List[Tuple[str, str]] = []

    if month_day >= (11, 16):
        periods.extend(
            [
                (str(year), "11014"),
                (str(year), "11012"),
                (str(year), "11013"),
            ]
        )
    elif month_day >= (8, 16):
        periods.extend(
            [
                (str(year), "11012"),
                (str(year), "11013"),
            ]
        )
    elif month_day >= (5, 16):
        periods.append((str(year), "11013"))

    previous_year = year - 1
    periods.extend(
        [
            (str(previous_year), "11011"),
            (str(previous_year), "11014"),
            (str(previous_year), "11012"),
            (str(previous_year), "11013"),
            (str(previous_year - 1), "11011"),
        ]
    )

    unique: List[Tuple[str, str]] = []
    seen = set()
    for item in periods:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def target_period_key(periods: Sequence[Tuple[str, str]]) -> str:
    if not periods:
        return ""
    return f"{periods[0][0]}_{periods[0][1]}"


def get_ticker_column(df: pd.DataFrame) -> Optional[str]:
    for column in ("ticker", "code", "종목코드", "단축코드"):
        if column in df.columns:
            return column
    return None


def get_name_column(df: pd.DataFrame) -> Optional[str]:
    for column in ("name", "종목명", "회사명"):
        if column in df.columns:
            return column
    return None


def generate_target_filenames() -> List[str]:
    filenames = set(BASE_TARGET_FILES)
    for base in BASE_TARGET_FILES:
        stem = base.removesuffix("_latest.csv")
        for suffix in VARIANT_SUFFIXES:
            if not suffix:
                continue
            filenames.add(f"{stem}{suffix}_latest.csv")
    return sorted(filenames)


def read_csv_safely(
    path: Path,
    *,
    dtype: Any = str,
) -> pd.DataFrame:
    errors: List[str] = []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=dtype)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}:{exc}")
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        except Exception as exc:
            errors.append(f"{encoding}:{type(exc).__name__}:{exc}")
    raise RuntimeError(
        f"CSV_READ_FAILED path={path} attempts={' | '.join(errors)}"
    )


def write_csv_atomically(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(handle)
    temporary_path = Path(temporary_name)

    try:
        df.to_csv(temporary_path, index=False, encoding="utf-8-sig")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def urlopen_bytes(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def download_corp_code_map(
    api_key: str,
    timeout: int,
) -> Dict[str, Dict[str, str]]:
    query = urllib.parse.urlencode({"crtfc_key": api_key})
    raw = urlopen_bytes(f"{DART_CORP_CODE_URL}?{query}", timeout=timeout)

    if raw[:2] != b"PK":
        preview = raw.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"DART_CORP_CODE_NOT_ZIP:{preview}")

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml_names = [
            name for name in archive.namelist()
            if name.lower().endswith(".xml")
        ]
        if not xml_names:
            raise RuntimeError("DART_CORP_CODE_XML_MISSING")
        root = ET.fromstring(archive.read(xml_names[0]))

    mapping: Dict[str, Dict[str, str]] = {}
    for item in root.findall(".//list"):
        stock_code = clean_ticker(item.findtext("stock_code"))
        if not stock_code:
            continue
        mapping[stock_code] = {
            "corp_code": normalize_text(
                item.findtext("corp_code")
            ).zfill(8),
            "corp_name": normalize_text(
                item.findtext("corp_name")
            ),
            "source": "OPENDART_OFFICIAL_DOWNLOAD",
            "modify_date": normalize_text(
                item.findtext("modify_date")
            ),
        }
    return mapping


def write_official_corp_code_map(
    output_dir: Path,
    mapping: Mapping[str, Mapping[str, Any]],
) -> None:
    rows = []
    for stock_code, info in sorted(mapping.items()):
        rows.append(
            {
                "stock_code": stock_code,
                "corp_code": normalize_text(
                    info.get("corp_code", "")
                ),
                "corp_name": normalize_text(
                    info.get("corp_name", "")
                ),
                "modify_date": normalize_text(
                    info.get("modify_date", "")
                ),
                "source": "OPENDART_OFFICIAL_DOWNLOAD",
            }
        )
    write_csv_atomically(
        pd.DataFrame(rows),
        output_dir / CORP_CODE_MAP_FILENAME,
    )


def load_validated_corp_code_cache(
    output_dir: Path,
    log_lines: List[str],
) -> Dict[str, Dict[str, str]]:
    path = output_dir / CORP_CODE_MAP_FILENAME
    if not path.exists():
        return {}

    try:
        df = read_csv_safely(path, dtype=str).fillna("")
    except Exception as exc:
        log_lines.append(
            "corp_code_map_cache_warning="
            f"{type(exc).__name__}:{exc}"
        )
        return {}

    if (
        "stock_code" not in df.columns
        or "corp_code" not in df.columns
        or "corp_name" not in df.columns
    ):
        log_lines.append(
            "corp_code_map_cache_warning=INVALID_SCHEMA"
        )
        return {}

    mapping: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        ticker = clean_ticker(row.get("stock_code", ""))
        corp_code = normalize_text(
            row.get("corp_code", "")
        ).zfill(8)
        corp_name = normalize_text(row.get("corp_name", ""))
        if not ticker or not corp_code or not corp_name:
            continue
        mapping[ticker] = {
            "corp_code": corp_code,
            "corp_name": corp_name,
            "source": "VALIDATED_CORP_CODE_MAP_CACHE",
            "modify_date": normalize_text(
                row.get("modify_date", "")
            ),
        }

    return mapping


def load_corp_code_map(
    output_dir: Path,
    api_key: str,
    timeout: int,
    log_lines: List[str],
) -> Dict[str, Dict[str, str]]:
    """
    공식 OpenDART 기업코드표를 최우선으로 사용한다.

    과거의 dart_corp_code_cache_latest.csv는 다른 목적의 캐시일 수
    있으므로 이 함수에서 읽지 않는다.
    """
    if api_key:
        try:
            mapping = download_corp_code_map(
                api_key,
                timeout,
            )
            if mapping:
                write_official_corp_code_map(
                    output_dir,
                    mapping,
                )
                log_lines.append(
                    "corp_code_source=OPENDART_OFFICIAL_DOWNLOAD"
                )
                log_lines.append(
                    f"corp_code_rows={len(mapping)}"
                )
                return mapping
        except Exception as exc:
            log_lines.append(
                "corp_code_official_download_warning="
                f"{type(exc).__name__}:{exc}"
            )

    mapping = load_validated_corp_code_cache(
        output_dir,
        log_lines,
    )
    if mapping:
        log_lines.append(
            "corp_code_source=VALIDATED_CORP_CODE_MAP_CACHE"
        )
        log_lines.append(f"corp_code_rows={len(mapping)}")
        return mapping

    if not api_key:
        log_lines.append("corp_code_source=NONE_NO_API_KEY")
    else:
        log_lines.append("corp_code_source=NONE_DOWNLOAD_FAILED")
    return {}


def collect_target_metadata(
    output_dir: Path,
    target_files: Sequence[str],
) -> Dict[str, Dict[str, str]]:
    metadata: Dict[str, Dict[str, str]] = {}

    for filename in target_files:
        path = output_dir / filename
        if not path.exists():
            continue
        try:
            df = read_csv_safely(path, dtype=str).fillna("")
        except Exception:
            continue

        ticker_column = get_ticker_column(df)
        name_column = get_name_column(df)
        if ticker_column is None:
            continue

        for _, row in df.iterrows():
            ticker = clean_ticker(row.get(ticker_column, ""))
            if not ticker:
                continue
            current = metadata.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "name": "",
                    "market": "",
                },
            )
            if name_column and not current["name"]:
                current["name"] = normalize_text(
                    row.get(name_column, "")
                )
            if "market" in df.columns and not current["market"]:
                current["market"] = normalize_text(
                    row.get("market", "")
                )
    return metadata


def load_market_metrics(
    output_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    metrics: Dict[str, Dict[str, Any]] = {}

    for filename in MARKET_METRIC_FILES:
        path = output_dir / filename
        if not path.exists():
            continue
        try:
            df = read_csv_safely(path, dtype=str).fillna("")
        except Exception:
            continue

        ticker_column = get_ticker_column(df)
        if ticker_column is None:
            continue

        for _, row in df.iterrows():
            ticker = clean_ticker(row.get(ticker_column, ""))
            if not ticker:
                continue
            metrics[ticker] = {
                "market_cap": parse_number(
                    row.get("market_cap")
                ),
                "listed_shares": parse_number(
                    row.get("listed_shares")
                ),
                "price_basis_date": normalize_text(
                    row.get("last_date", "")
                ),
                "current_close": parse_number(
                    row.get("current_close")
                ),
                "name": normalize_text(row.get("name", "")),
                "market": normalize_text(row.get("market", "")),
            }
    return metrics


def is_flow_statement(spec: AccountSpec) -> bool:
    return spec.statement == "IS"


def current_amount_keys(
    report_code: str,
    spec: AccountSpec,
) -> Tuple[str, ...]:
    if is_flow_statement(spec) and report_code != "11011":
        return ("thstrm_add_amount", "thstrm_amount")
    return ("thstrm_amount", "thstrm_add_amount")


def previous_amount_keys(
    report_code: str,
    spec: AccountSpec,
) -> Tuple[str, ...]:
    if is_flow_statement(spec) and report_code != "11011":
        return ("frmtrm_add_amount", "frmtrm_amount")
    return ("frmtrm_amount", "frmtrm_add_amount")


def account_match_score(
    item: Mapping[str, Any],
    spec: AccountSpec,
) -> int:
    account_name = normalize_account_name(
        item.get("account_nm", "")
    )
    if not account_name:
        return -1

    statement = normalize_text(item.get("sj_div", ""))
    if spec.statement and statement and statement != spec.statement:
        return -1

    normalized_exact = {
        normalize_account_name(name)
        for name in spec.exact_names
    }
    if account_name in normalized_exact:
        score = 100
    else:
        include_terms = tuple(
            normalize_account_name(term)
            for term in spec.include_terms
        )
        if include_terms and not all(
            term in account_name for term in include_terms
        ):
            return -1
        score = 40 + 5 * len(include_terms)

    for excluded in spec.exclude_terms:
        if normalize_account_name(excluded) in account_name:
            return -1

    fs_div = normalize_text(item.get("fs_div", ""))
    if fs_div == "CFS":
        score += 20
    elif fs_div == "OFS":
        score += 10

    return score


def first_parsed_amount(
    item: Mapping[str, Any],
    keys: Iterable[str],
) -> Tuple[Optional[float], str]:
    for key in keys:
        amount = parse_number(item.get(key))
        if amount is not None:
            return amount, key
    return None, ""


def select_account_item(
    items: Sequence[Mapping[str, Any]],
    spec: AccountSpec,
    report_code: str,
    fs_div: str,
) -> Optional[Dict[str, Any]]:
    candidates: List[Tuple[int, Dict[str, Any]]] = []

    for original in items:
        item = dict(original)
        if normalize_text(item.get("fs_div", "")) != fs_div:
            continue

        score = account_match_score(item, spec)
        if score < 0:
            continue

        current, current_key = first_parsed_amount(
            item,
            current_amount_keys(report_code, spec),
        )
        if current is None:
            continue

        previous, previous_key = first_parsed_amount(
            item,
            previous_amount_keys(report_code, spec),
        )

        item["_current_amount"] = current
        item["_previous_amount"] = previous
        item["_current_amount_key"] = current_key
        item["_previous_amount_key"] = previous_key
        candidates.append((score, item))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def extract_statement_set(
    items: Sequence[Mapping[str, Any]],
    report_code: str,
    fs_div: str,
) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "fs_div": fs_div,
        "currency": "",
        "selected_accounts": {},
    }

    completeness = 0
    for spec in ACCOUNT_SPECS:
        selected = select_account_item(
            items,
            spec,
            report_code,
            fs_div,
        )
        values[spec.key] = (
            selected.get("_current_amount")
            if selected
            else None
        )
        values[f"previous_{spec.key}"] = (
            selected.get("_previous_amount")
            if selected
            else None
        )
        if selected:
            completeness += 1
            values["selected_accounts"][spec.key] = {
                "account_nm": normalize_text(
                    selected.get("account_nm", "")
                ),
                "current_amount_key": selected.get(
                    "_current_amount_key",
                    "",
                ),
                "previous_amount_key": selected.get(
                    "_previous_amount_key",
                    "",
                ),
            }
            if not values["currency"]:
                values["currency"] = normalize_text(
                    selected.get("currency", "")
                )

    values["completeness"] = completeness
    return values


def choose_statement_set(
    items: Sequence[Mapping[str, Any]],
    report_code: str,
) -> Optional[Dict[str, Any]]:
    candidates = [
        extract_statement_set(items, report_code, "CFS"),
        extract_statement_set(items, report_code, "OFS"),
    ]

    # 연결재무제표를 우선하되, 핵심 계정이 현저히 부족하면 개별을 선택한다.
    candidates.sort(
        key=lambda item: (
            int(item.get("completeness", 0)),
            1 if item.get("fs_div") == "CFS" else 0,
        ),
        reverse=True,
    )
    best = candidates[0]
    if int(best.get("completeness", 0)) == 0:
        return None
    return best


def determine_earnings_trend(
    current: Optional[float],
    previous: Optional[float],
) -> str:
    if current is None or previous is None:
        return "확인제한"
    if current >= 0 and previous >= 0:
        return "흑자지속"
    if current >= 0 and previous < 0:
        return "흑자전환"
    if current < 0 and previous >= 0:
        return "적자전환"
    return "적자지속"


def compute_financial_status(
    statement: Mapping[str, Any],
) -> Tuple[str, List[str]]:
    required = (
        "revenue",
        "operating_profit",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
    )
    missing = [
        field
        for field in required
        if statement.get(field) is None
    ]

    if not missing:
        return "READY", []
    if len(missing) <= 2 and statement.get("net_income") is not None:
        return "PARTIAL", missing
    return "LIMITED", missing


def compute_metrics(
    statement: Mapping[str, Any],
    report_code: str,
    market_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    revenue = statement.get("revenue")
    operating_profit = statement.get("operating_profit")
    net_income = statement.get("net_income")
    total_liabilities = statement.get("total_liabilities")
    total_equity = statement.get("total_equity")

    previous_revenue = statement.get("previous_revenue")
    previous_operating_profit = statement.get(
        "previous_operating_profit"
    )
    previous_net_income = statement.get("previous_net_income")

    factor = annualization_factor(report_code)
    annualized_net_income = (
        net_income * factor
        if net_income is not None
        else None
    )

    market_cap = market_metrics.get("market_cap")
    listed_shares = market_metrics.get("listed_shares")

    eps = None
    bps = None
    per = None
    pbr = None

    if (
        annualized_net_income is not None
        and listed_shares is not None
        and listed_shares > 0
    ):
        eps = annualized_net_income / listed_shares

    if (
        total_equity is not None
        and listed_shares is not None
        and listed_shares > 0
    ):
        bps = total_equity / listed_shares

    # 적자 또는 0 이익에는 PER 숫자를 만들지 않는다.
    if (
        market_cap is not None
        and market_cap > 0
        and annualized_net_income is not None
        and annualized_net_income > 0
    ):
        per = market_cap / annualized_net_income

    if (
        market_cap is not None
        and market_cap > 0
        and total_equity is not None
        and total_equity > 0
    ):
        pbr = market_cap / total_equity

    if market_cap is None or market_cap <= 0:
        valuation_status = "LIMITED_NO_MARKET_CAP"
    elif total_equity is None or total_equity <= 0:
        valuation_status = "LIMITED_NO_POSITIVE_EQUITY"
    elif annualized_net_income is None:
        valuation_status = "PARTIAL_NO_NET_INCOME"
    elif annualized_net_income <= 0:
        valuation_status = "PARTIAL_LOSS_PER_NA"
    elif listed_shares is None or listed_shares <= 0:
        valuation_status = "PARTIAL_NO_SHARE_COUNT"
    else:
        valuation_status = "READY"

    annualization_label = (
        "연환산 없음"
        if factor == 1.0
        else f"누적순이익 × {factor:.4g} 연환산"
    )

    return {
        "revenue_yoy_pct": safe_round(
            safe_yoy_pct(revenue, previous_revenue)
        ),
        "operating_profit_yoy_pct": safe_round(
            safe_yoy_pct(
                operating_profit,
                previous_operating_profit,
            )
        ),
        "net_income_yoy_pct": safe_round(
            safe_yoy_pct(net_income, previous_net_income)
        ),
        "operating_margin_pct": safe_round(
            safe_ratio_pct(operating_profit, revenue)
        ),
        "debt_ratio_pct": safe_round(
            safe_ratio_pct(total_liabilities, total_equity)
        ),
        "roe_annualized_pct": safe_round(
            safe_ratio_pct(
                annualized_net_income,
                total_equity,
            )
        ),
        "earnings_trend": determine_earnings_trend(
            operating_profit,
            previous_operating_profit,
        ),
        "market_cap": safe_round(market_cap, 0),
        "listed_shares": safe_round(listed_shares, 0),
        "valuation_price_basis_date": normalize_text(
            market_metrics.get("price_basis_date", "")
        ),
        "eps_annualized": safe_round(eps),
        "bps": safe_round(bps),
        "per_annualized": safe_round(per),
        "pbr": safe_round(pbr),
        "valuation_data_status": valuation_status,
        "valuation_basis": (
            "KRX 시가총액·상장주식수 / "
            f"OpenDART {report_label('', report_code).strip()} / "
            f"{annualization_label}"
        ),
    }


def blank_record(
    *,
    ticker: str,
    metadata: Mapping[str, Any],
    corp_info: Mapping[str, Any],
    source_status: str,
    target_key: str,
) -> Dict[str, Any]:
    record = {column: "" for column in OUTPUT_COLUMNS}
    record.update(
        {
            "ticker": ticker,
            "name": normalize_text(metadata.get("name", "")),
            "market": normalize_text(metadata.get("market", "")),
            "corp_code": normalize_text(
                corp_info.get("corp_code", "")
            ),
            "corp_name": normalize_text(
                corp_info.get("corp_name", "")
            ),
            "corp_code_source": normalize_text(
                corp_info.get("source", "")
            ),
            "corp_identity_status": (
                "NO_CORP_CODE"
                if not normalize_text(corp_info.get("corp_code", ""))
                else "NOT_VERIFIED"
            ),
            "corp_identity_reason": source_status,
            "financial_data_status": "LIMITED",
            "financial_source_status": source_status,
            "financial_basis": "",
            "financial_report_year": "",
            "financial_report_code": "",
            "financial_report_name": "",
            "financial_fs_div": "",
            "financial_currency": "KRW",
            "valuation_data_status": "LIMITED_NO_FINANCIAL_DATA",
            "financial_missing_fields": (
                "revenue,operating_profit,net_income,"
                "total_assets,total_liabilities,total_equity"
            ),
            "target_period_key": target_key,
            "fetched_at_kst": now_kst_text(),
        }
    )
    return record


def fetch_financial_record(
    *,
    ticker: str,
    metadata: Mapping[str, Any],
    corp_info: Mapping[str, Any],
    market_metrics: Mapping[str, Any],
    api_key: str,
    periods: Sequence[Tuple[str, str]],
    target_key: str,
    timeout: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    corp_code = normalize_text(corp_info.get("corp_code", ""))
    if not corp_code:
        return blank_record(
            ticker=ticker,
            metadata=metadata,
            corp_info=corp_info,
            source_status="NO_CORP_CODE",
            target_key=target_key,
        )

    identity_status, identity_reason = evaluate_corp_identity(
        metadata.get("name", ""),
        corp_info.get("corp_name", ""),
        corp_info.get("source", ""),
    )
    if identity_status == "MISMATCH":
        result = blank_record(
            ticker=ticker,
            metadata=metadata,
            corp_info=corp_info,
            source_status="CORP_IDENTITY_MISMATCH",
            target_key=target_key,
        )
        result["corp_identity_status"] = identity_status
        result["corp_identity_reason"] = identity_reason
        return result

    last_status = "NO_FINANCIAL_DATA"

    for business_year, report_code in periods:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        query = urllib.parse.urlencode(
            {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": business_year,
                "reprt_code": report_code,
            }
        )
        url = f"{DART_MAJOR_ACCOUNT_URL}?{query}"

        try:
            raw = urlopen_bytes(url, timeout=timeout)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            last_status = f"FETCH_ERROR_{type(exc).__name__}"
            continue

        status = normalize_text(payload.get("status", ""))
        message = normalize_text(payload.get("message", ""))
        if status != "000":
            last_status = f"API_STATUS_{status}:{message}"
            # 020은 조회 제한이므로 다른 기간을 계속 호출하지 않는다.
            if status == "020":
                break
            continue

        items = payload.get("list", [])
        if not isinstance(items, list) or not items:
            last_status = "NO_ACCOUNT_ITEMS"
            continue

        statement = choose_statement_set(items, report_code)
        if statement is None:
            last_status = "NO_MATCHED_ACCOUNTS"
            continue

        financial_status, missing = compute_financial_status(
            statement
        )
        metrics = compute_metrics(
            statement,
            report_code,
            market_metrics,
        )

        record = {column: "" for column in OUTPUT_COLUMNS}
        record.update(
            {
                "ticker": ticker,
                "name": normalize_text(
                    metadata.get("name")
                    or market_metrics.get("name")
                ),
                "market": normalize_text(
                    metadata.get("market")
                    or market_metrics.get("market")
                ),
                "corp_code": corp_code,
                "corp_name": normalize_text(
                    corp_info.get("corp_name", "")
                ),
                "corp_code_source": normalize_text(
                    corp_info.get("source", "")
                ),
                "corp_identity_status": identity_status,
                "corp_identity_reason": identity_reason,
                "financial_data_status": financial_status,
                "financial_source_status": "OK",
                "financial_basis": report_label(
                    business_year,
                    report_code,
                ),
                "financial_report_year": business_year,
                "financial_report_code": report_code,
                "financial_report_name": REPORT_NAMES.get(
                    report_code,
                    report_code,
                ),
                "financial_fs_div": statement.get("fs_div", ""),
                "financial_currency": (
                    statement.get("currency") or "KRW"
                ),
                "revenue": safe_round(
                    statement.get("revenue"),
                    0,
                ),
                "operating_profit": safe_round(
                    statement.get("operating_profit"),
                    0,
                ),
                "net_income": safe_round(
                    statement.get("net_income"),
                    0,
                ),
                "total_assets": safe_round(
                    statement.get("total_assets"),
                    0,
                ),
                "total_liabilities": safe_round(
                    statement.get("total_liabilities"),
                    0,
                ),
                "total_equity": safe_round(
                    statement.get("total_equity"),
                    0,
                ),
                "previous_revenue": safe_round(
                    statement.get("previous_revenue"),
                    0,
                ),
                "previous_operating_profit": safe_round(
                    statement.get("previous_operating_profit"),
                    0,
                ),
                "previous_net_income": safe_round(
                    statement.get("previous_net_income"),
                    0,
                ),
                "financial_missing_fields": ",".join(missing),
                "target_period_key": target_key,
                "fetched_at_kst": now_kst_text(),
            }
        )
        record.update(metrics)
        return record

    return blank_record(
        ticker=ticker,
        metadata=metadata,
        corp_info=corp_info,
        source_status=last_status,
        target_key=target_key,
    )


def parse_fetched_at(value: Any) -> Optional[datetime]:
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(KST)
    except ValueError:
        return None


def read_cache(
    cache_path: Path,
    target_key: str,
    retry_hours: float,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    stable_cache:
      같은 기준기간의 OK/PARTIAL 자료. 새 보고기간이 나오기 전까지 재사용.
    temporary_cache:
      제한·오류 자료. retry_hours 동안만 재사용.
    """
    if not cache_path.exists():
        return {}, {}

    try:
        df = read_csv_safely(cache_path, dtype=str).fillna("")
    except Exception:
        return {}, {}

    if "ticker" not in df.columns:
        return {}, {}

    stable: Dict[str, Dict[str, Any]] = {}
    temporary: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        ticker = clean_ticker(row.get("ticker", ""))
        if not ticker:
            continue
        record = row.to_dict()

        if normalize_text(
            record.get("target_period_key", "")
        ) != target_key:
            continue

        status = normalize_text(
            record.get("financial_source_status", "")
        )
        financial_status = normalize_text(
            record.get("financial_data_status", "")
        )

        if status == "OK" and financial_status in {
            "READY",
            "PARTIAL",
        }:
            stable[ticker] = record
            continue

        fetched_at = parse_fetched_at(
            record.get("fetched_at_kst", "")
        )
        if fetched_at is None:
            continue
        age_hours = (
            now_kst() - fetched_at
        ).total_seconds() / 3600.0
        if age_hours < retry_hours:
            temporary[ticker] = record

    return stable, temporary


def normalize_bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    text = normalize_text(value).lower()
    if text in {"true", "1", "yes", "y"}:
        return "TRUE"
    if text in {"false", "0", "no", "n"}:
        return "FALSE"
    return ""


def enrich_one_file(
    path: Path,
    result_map: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, int, int]:
    if not path.exists():
        return "MISSING", 0, 0

    try:
        df = read_csv_safely(path, dtype=str).fillna("")
    except Exception as exc:
        return f"READ_ERROR_{type(exc).__name__}", 0, 0

    ticker_column = get_ticker_column(df)
    if ticker_column is None:
        return "NO_TICKER_COLUMN", len(df), 0

    for column in ENRICH_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    for column in OPERATING_PROFIT_COMPAT_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    matched = 0
    for index, value in df[ticker_column].items():
        ticker = clean_ticker(value)
        record = result_map.get(ticker)
        if not ticker or not record:
            continue

        for column in ENRICH_COLUMNS:
            df.at[index, column] = normalize_text(
                record.get(column, "")
            )

        # 기존 영업손실 표시와 같은 재무 기준을 쓰도록 동기화한다.
        operating_profit = parse_number(
            record.get("operating_profit")
        )
        if operating_profit is not None:
            df.at[index, "operating_profit"] = str(
                int(round(operating_profit))
            )
            df.at[index, "operating_profit_unit"] = "KRW"
            df.at[index, "operating_loss_flag"] = (
                "TRUE" if operating_profit < 0 else "FALSE"
            )
            df.at[index, "operating_loss_basis"] = normalize_text(
                record.get("financial_basis", "")
            )
            df.at[index, "operating_loss_source_status"] = (
                normalize_text(
                    record.get("financial_source_status", "")
                )
            )
        matched += 1

    write_csv_atomically(df, path)
    return "OK", len(df), matched


def run_self_test() -> int:
    sample_items = [
        {
            "account_nm": "매출액",
            "fs_div": "CFS",
            "sj_div": "IS",
            "thstrm_add_amount": "1,200,000",
            "frmtrm_add_amount": "1,000,000",
            "currency": "KRW",
        },
        {
            "account_nm": "영업이익(손실)",
            "fs_div": "CFS",
            "sj_div": "IS",
            "thstrm_add_amount": "120,000",
            "frmtrm_add_amount": "80,000",
            "currency": "KRW",
        },
        {
            "account_nm": "당기순이익(손실)",
            "fs_div": "CFS",
            "sj_div": "IS",
            "thstrm_add_amount": "90,000",
            "frmtrm_add_amount": "70,000",
            "currency": "KRW",
        },
        {
            "account_nm": "자산총계",
            "fs_div": "CFS",
            "sj_div": "BS",
            "thstrm_amount": "5,000,000",
            "frmtrm_amount": "4,800,000",
            "currency": "KRW",
        },
        {
            "account_nm": "부채총계",
            "fs_div": "CFS",
            "sj_div": "BS",
            "thstrm_amount": "2,000,000",
            "frmtrm_amount": "2,100,000",
            "currency": "KRW",
        },
        {
            "account_nm": "자본총계",
            "fs_div": "CFS",
            "sj_div": "BS",
            "thstrm_amount": "3,000,000",
            "frmtrm_amount": "2,700,000",
            "currency": "KRW",
        },
    ]

    statement = choose_statement_set(sample_items, "11013")
    assert statement is not None
    assert statement["fs_div"] == "CFS"
    assert statement["revenue"] == 1_200_000
    assert statement["previous_revenue"] == 1_000_000
    assert statement["operating_profit"] == 120_000
    assert statement["net_income"] == 90_000
    assert statement["total_assets"] == 5_000_000
    assert statement["total_liabilities"] == 2_000_000
    assert statement["total_equity"] == 3_000_000

    status, missing = compute_financial_status(statement)
    assert status == "READY"
    assert missing == []

    metrics = compute_metrics(
        statement,
        "11013",
        {
            "market_cap": 6_000_000,
            "listed_shares": 1_000,
            "price_basis_date": "2026-06-30",
        },
    )
    assert metrics["revenue_yoy_pct"] == 20.0
    assert metrics["operating_margin_pct"] == 10.0
    assert round(float(metrics["debt_ratio_pct"]), 2) == 66.67
    assert metrics["eps_annualized"] == 360.0
    assert metrics["bps"] == 3000.0
    assert round(float(metrics["per_annualized"]), 2) == 16.67
    assert metrics["pbr"] == 2.0
    assert metrics["valuation_data_status"] == "READY"

    loss_statement = dict(statement)
    loss_statement["net_income"] = -100_000
    loss_metrics = compute_metrics(
        loss_statement,
        "11011",
        {
            "market_cap": 6_000_000,
            "listed_shares": 1_000,
            "price_basis_date": "2026-06-30",
        },
    )
    assert loss_metrics["per_annualized"] == ""
    assert (
        loss_metrics["valuation_data_status"]
        == "PARTIAL_LOSS_PER_NA"
    )

    status, _ = evaluate_corp_identity(
        "DB하이텍",
        "(주)DB하이텍",
        "OPENDART_OFFICIAL_DOWNLOAD",
    )
    assert status in {"MATCH", "MATCH_NORMALIZED"}

    status, _ = evaluate_corp_identity(
        "DB하이텍",
        "IBKS제25호스팩",
        "VALIDATED_CORP_CODE_MAP_CACHE",
    )
    assert status == "MISMATCH"

    print("SELF_TEST_STATUS=OK")
    print("TESTED=account_selection,financial_status,ratios,valuation,corp_identity")
    return 0


def write_run_log(
    path: Path,
    lines: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "OpenDART 재무자료와 KRX 시가총액을 결합해 "
            "재무·밸류에이션 필드를 생성"
        )
    )
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--max-api-calls", type=int, default=5000)
    parser.add_argument(
        "--retry-hours",
        type=float,
        default=20.0,
        help="오류·자료없음 캐시를 재사용할 시간",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="외부 API 없이 내부 계산 시험만 실행",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="캐시만 만들고 표 CSV에는 적용하지 않음",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_path = output_dir / CACHE_FILENAME
    log_path = output_dir / RUN_LOG_FILENAME
    target_files = generate_target_filenames()
    periods = candidate_report_periods()
    target_key = target_period_key(periods)
    api_key = os.environ.get("DART_API_KEY", "").strip()

    log_lines: List[str] = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={now_kst_text()}",
        f"OUTPUT_DIR={output_dir.as_posix()}",
        f"TARGET_PERIOD_KEY={target_key}",
        "CANDIDATE_PERIODS="
        + ",".join(f"{year}_{code}" for year, code in periods),
        f"WORKERS={args.workers}",
        f"MAX_API_CALLS={args.max_api_calls}",
        f"RETRY_HOURS={args.retry_hours}",
        f"DART_API_KEY_PRESENT={'true' if api_key else 'false'}",
    ]

    metadata = collect_target_metadata(
        output_dir,
        target_files,
    )
    market_metrics = load_market_metrics(output_dir)
    log_lines.append(f"TARGET_TICKERS={len(metadata)}")
    log_lines.append(
        f"MARKET_METRIC_TICKERS={len(market_metrics)}"
    )

    if not metadata:
        log_lines.extend(
            [
                "STATUS=ERROR",
                "ERROR=NO_TARGET_TICKERS",
            ]
        )
        write_run_log(log_path, log_lines)
        print("FINANCIAL_VALUATION_STATUS=ERROR_NO_TARGET_TICKERS")
        return 1

    corp_map = load_corp_code_map(
        output_dir,
        api_key,
        args.timeout,
        log_lines,
    )

    stable_cache, temporary_cache = read_cache(
        cache_path,
        target_key,
        args.retry_hours,
    )
    log_lines.append(f"STABLE_CACHE_HITS={len(stable_cache)}")
    log_lines.append(
        f"TEMPORARY_CACHE_HITS={len(temporary_cache)}"
    )

    result_map: Dict[str, Dict[str, Any]] = {}
    to_fetch: List[str] = []

    for ticker in sorted(metadata):
        if ticker in stable_cache:
            result_map[ticker] = stable_cache[ticker]
        elif ticker in temporary_cache:
            result_map[ticker] = temporary_cache[ticker]
        else:
            to_fetch.append(ticker)

    if not api_key:
        for ticker in to_fetch:
            result_map[ticker] = blank_record(
                ticker=ticker,
                metadata=metadata[ticker],
                corp_info=corp_map.get(ticker, {}),
                source_status="NO_DART_API_KEY",
                target_key=target_key,
            )
        to_fetch = []

    original_to_fetch = len(to_fetch)
    if len(to_fetch) > args.max_api_calls:
        to_fetch = to_fetch[: args.max_api_calls]
        log_lines.append(
            "API_CALL_LIMIT_APPLIED="
            f"{args.max_api_calls}/{original_to_fetch}"
        )

    log_lines.append(f"TO_FETCH={len(to_fetch)}")

    if to_fetch:
        with ThreadPoolExecutor(
            max_workers=max(1, args.workers)
        ) as executor:
            futures = {
                executor.submit(
                    fetch_financial_record,
                    ticker=ticker,
                    metadata=metadata[ticker],
                    corp_info=corp_map.get(ticker, {}),
                    market_metrics=market_metrics.get(
                        ticker,
                        {},
                    ),
                    api_key=api_key,
                    periods=periods,
                    target_key=target_key,
                    timeout=args.timeout,
                    sleep_seconds=args.sleep_seconds,
                ): ticker
                for ticker in to_fetch
            }

            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    result_map[ticker] = future.result()
                except Exception as exc:
                    result_map[ticker] = blank_record(
                        ticker=ticker,
                        metadata=metadata[ticker],
                        corp_info=corp_map.get(ticker, {}),
                        source_status=(
                            "UNHANDLED_ERROR_"
                            f"{type(exc).__name__}"
                        ),
                        target_key=target_key,
                    )

    # 호출 제한으로 처리하지 못한 종목은 명확히 LIMITED로 남긴다.
    for ticker in sorted(metadata):
        if ticker not in result_map:
            result_map[ticker] = blank_record(
                ticker=ticker,
                metadata=metadata[ticker],
                corp_info=corp_map.get(ticker, {}),
                source_status="API_CALL_LIMIT_NOT_FETCHED",
                target_key=target_key,
            )

    records = [
        {
            column: result_map[ticker].get(column, "")
            for column in OUTPUT_COLUMNS
        }
        for ticker in sorted(result_map)
    ]
    cache_df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    write_csv_atomically(cache_df, cache_path)

    source_counts = (
        cache_df["financial_source_status"]
        .value_counts(dropna=False)
        .to_dict()
    )
    financial_counts = (
        cache_df["financial_data_status"]
        .value_counts(dropna=False)
        .to_dict()
    )
    valuation_counts = (
        cache_df["valuation_data_status"]
        .value_counts(dropna=False)
        .to_dict()
    )
    identity_counts = (
        cache_df["corp_identity_status"]
        .value_counts(dropna=False)
        .to_dict()
    )

    log_lines.append(f"CACHE_OUTPUT_ROWS={len(cache_df)}")
    log_lines.append(f"SOURCE_STATUS_COUNTS={source_counts}")
    log_lines.append(
        f"FINANCIAL_STATUS_COUNTS={financial_counts}"
    )
    log_lines.append(
        f"VALUATION_STATUS_COUNTS={valuation_counts}"
    )
    log_lines.append(
        f"CORP_IDENTITY_STATUS_COUNTS={identity_counts}"
    )

    enriched_count = 0
    if not args.no_enrich:
        for filename in target_files:
            status, rows, matched = enrich_one_file(
                output_dir / filename,
                result_map,
            )
            if status == "OK":
                enriched_count += 1
            log_lines.append(
                f"ENRICH_FILE={filename}"
                f"|status={status}"
                f"|rows={rows}"
                f"|matched={matched}"
            )

    ready_count = int(
        (
            cache_df["financial_data_status"]
            .astype(str)
            .eq("READY")
        ).sum()
    )
    partial_count = int(
        (
            cache_df["financial_data_status"]
            .astype(str)
            .eq("PARTIAL")
        ).sum()
    )
    limited_count = len(cache_df) - ready_count - partial_count

    log_lines.extend(
        [
            f"FINANCIAL_READY_COUNT={ready_count}",
            f"FINANCIAL_PARTIAL_COUNT={partial_count}",
            f"FINANCIAL_LIMITED_COUNT={limited_count}",
            f"ENRICHED_FILE_COUNT={enriched_count}",
            "STATUS=OK",
            (
                "NOTE=PER는 연환산 순이익이 양수일 때만 계산하며, "
                "적자기업에는 숫자 PER를 만들지 않습니다."
            ),
            (
                "NOTE=이 단계의 PER/PBR은 기초 계산값이며 "
                "업종 상대가치 평가는 후속 점수 계산기에서 수행합니다."
            ),
        ]
    )
    write_run_log(log_path, log_lines)

    print("FINANCIAL_VALUATION_STATUS=OK")
    print(f"CACHE_OUTPUT_ROWS={len(cache_df)}")
    print(f"FINANCIAL_READY_COUNT={ready_count}")
    print(f"FINANCIAL_PARTIAL_COUNT={partial_count}")
    print(f"FINANCIAL_LIMITED_COUNT={limited_count}")
    print(f"ENRICHED_FILE_COUNT={enriched_count}")
    print(f"RUN_LOG={log_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
