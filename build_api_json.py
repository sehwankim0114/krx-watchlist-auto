#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_api_json.py v4.0_single_table

목적
- GitHub latest 산출물을 Custom GPT가 읽는 api/*.json으로 변환한다.
- 현재가 보정(current_basis) 파일을 우선한다.
- 공식 자료 기준일, 현재가 기준시각, 규칙 버전/해시, 원본 커밋을 함께 기록한다.
- API 동기화 상태와 공식자료 최신성을 분리해서 판정한다.

중요
- api_sync_ok=True: API 파일 구조·행 수·규칙 해시가 서로 맞음.
- official_fresh_now=True: 현재 시점의 기대 공식 거래일과 KRX 실제 기준일이 맞음.
- safe_to_analyze_as_latest=True: 위 두 조건이 모두 참일 때만 가능.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_VERSION = "build_api_json.py v4.9_display_normalization_v74"
SCHEMA_VERSION = "4.2"
ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "latest"
API = ROOT / "api"
DOCS = ROOT / "docs"
CONFIG = ROOT / "config"
RULES_PATH = DOCS / "stock_table_rules_latest.md"
API.mkdir(parents=True, exist_ok=True)

PRESENTATION_POLICY: Dict[str, Any] = {
    "format_contract": "improvement_plan_2_final",
    "default_output_mode": "single_main_table",
    "separate_recommendation_table_default": False,
    "recommendation_markings_embedded_in_main_table": True,
    "explicit_shortlist_request": (
        "filter main candidate rows and output only the shortlist table"
    ),
    "duplicate_rows_across_main_and_shortlist_tables": False,
    "metadata_display_mode": "compact_two_column_table",
    "bold_price_ranges": True,
    "kr_sector_theme_source": "KRX_KIND_LISTED_COMPANY",
    "kr_sector_theme_missing_display": "자료 미제공",
    "kr_average_volume_per_minute_value_column_label": "평균거래량·분당거래금",
    "kr_regular_session_minutes": 390,
    "recommendation_column_label": "추천/종목",
    "show_rank_numbers_default": False,
    "rank_field_use": "sorting_only",
    "supply_keyword_alias_deduplication": True,
    "supply_keyword_display_separator": "·",
    "current_price_column_label": "요청시점 현재가",
    "price_range_markdown_required": True,
    "preferred_buy_range_field": "value_buy_range_markdown",
    "preferred_first_sell_range_field": "first_sell_target_range_markdown",
    "price_timestamp_label_policy": "use_price_data_time_unless_actual_trade_time_is_guaranteed",
    "market_specific_metadata": True,
    "us_table_omit_kr_market_metadata_by_default": True,
    "output_sequence": [
        "title",
        "metadata_two_column_table",
        "main_stock_table",
        "minimal_required_notes",
    ],
    "metadata_table_complete_before_main_table": True,
    "minimal_notes_position": "after_main_table_only",
    "forbid_notes_inside_metadata_table": True,
    "forbid_metadata_rows_after_notes": True,
    "explanation_default_mode": (
        "main_table_plus_minimal_required_notes_only"
    ),
    "automatic_weekly_guide": False,
    "full_manual_trigger": "설명서",
    "partial_help_trigger_phrases": [
        "사용법",
        "해석해줘",
        "표시 설명",
        "항목 설명",
        "용어 설명",
    ],
    "full_manual_section_order": [
        "30초 사용법",
        "표시 읽는 법",
        "어떤 표를 사용할지",
        "항목 읽는 법",
        "점수·추천·주의사유 해석",
        "여러 표 연결 방법",
        "꼭 기억할 원칙",
        "주요 용어",
    ],
    "minimal_notes_allowed": [
        "symbols_used_in_current_table",
        "request_time_price_failures_or_partial_results",
        "after_hours_not_reflected",
        "short_investment_reference_disclaimer",
    ],
    "prohibited_default_extras": [
        "monday_first_table_guide",
        "weekly_usage_guide",
        "full_command_catalog",
        "full_glossary",
        "long_explanation_section",
        "notes_between_metadata_rows",
        "metadata_rows_after_notes",
    ],
}
# EXPLANATION_MANUAL_POLICY_V62
# OUTPUT_ORDER_PRICE_RETRY_V65
# REQUEST_TIME_PRICE_POLICY_V51_BEGIN
REQUEST_TIME_PRICE_POLICY: Dict[str, Any] = {
    "enabled": True,
    "mode": "request_time_dynamic_overlay",
    "lookup_scope": "all_rows_in_requested_table",
    "action_operation_id": "getRequestTimePrices",
    "health_operation_id": "getRequestTimePriceHealth",
    "api_base_url": "https://krx-live-price-ksh.diaconos.workers.dev",
    "max_batch_size": 10,
    "initial_batch_size": 10,
    "batch_execution_mode": "sequential",
    "max_parallel_batches": 1,
    "retry_failed_quotes": True,
    "retry_only_failed": True,
    "retry_rounds": 2,
    "retry_batch_sizes": [5, 2],
    "retry_execution_mode": "sequential",
    "merge_results_by_quote_key": True,
    "preserve_input_order": True,
    "deduplicate_quote_keys": True,
    "final_success_count_after_retries": True,
    "quote_key_fields": [
        "ticker",
        "symbol",
        "code",
        "종목코드",
        "stock_code",
    ],
    "quote_key_aliases": {
        "us": ["ticker", "symbol"],
        "kr": ["code", "종목코드", "stock_code"],
    },
    "market_fields": ["market", "시장", "exchange", "country"],
    "preserve_official_history": True,
    "allow_last_confirmed_official_when_delayed": True,
    "failed_quote_behavior": (
        "after_all_retries_keep_row_mark_white_circle_do_not_fake_price"
    ),
    "large_table_behavior": (
        "split_into_sequential_batches_until_all_rows_attempted"
    ),
    "execution_steps": [
        "extract_all_quote_keys_in_table_order",
        "call_initial_sequential_batches_of_at_most_10",
        "collect_only_failed_quote_keys",
        "retry_failed_keys_in_batches_of_at_most_5",
        "retry_still_failed_keys_in_batches_of_at_most_2",
        "merge_all_successes_and_preserve_original_row_order",
        "mark_only_final_failures_with_white_circle",
    ],
}
# REQUEST_TIME_PRICE_POLICY_V51_END
# QUOTE_KEY_ALIASES_V64
# OUTPUT_ORDER_PRICE_RETRY_V65

@dataclass(frozen=True)
class TableSpec:
    table_id: str
    display_name: str
    output_name: str
    sources: Tuple[str, ...]
    required: bool = False
    exact_rows: Optional[int] = None
    min_rows: Optional[int] = None
    overlay_source: Optional[str] = None
    default_output: bool = True
    explicit_request_only: bool = False


TABLE_SPECS: Tuple[TableSpec, ...] = (
    TableSpec(
        "watchlist", "관종표", "watchlist.json",
        ("watchlist_summary_current_basis_latest.csv", "watchlist_summary_latest.csv"),
        required=True, exact_rows=47,
    ),
    TableSpec(
        "kospi_candidates_30", "코피표 후보 30", "kospi_candidates_30.json",
        ("kospi_candidates_30_current_basis_latest.csv", "kospi_candidates_30_latest.csv"),
        required=True, exact_rows=30,
    ),
    TableSpec(
        "kospi_recommend_7", "별도 요청용 코피 추천 7", "kospi_recommend_7.json",
        ("kospi_recommend_7_current_basis_latest.csv", "kospi_recommend_7_latest.csv"),
        required=False, exact_rows=7,
        overlay_source="kospi_candidates_30_current_basis_latest.csv",
        default_output=False, explicit_request_only=True,
    ),
    TableSpec(
        "kosdaq_candidates_10", "코닥표 후보 10", "kosdaq_candidates_10.json",
        ("kosdaq_candidates_10_current_basis_latest.csv", "kosdaq_candidates_10_latest.csv"),
        required=True, exact_rows=10,
    ),
    TableSpec(
        "kosdaq_recommend_5", "별도 요청용 코닥 추천 5", "kosdaq_recommend_5.json",
        ("kosdaq_recommend_5_current_basis_latest.csv", "kosdaq_recommend_5_latest.csv"),
        required=False, exact_rows=5,
        overlay_source="kosdaq_candidates_10_current_basis_latest.csv",
        default_output=False, explicit_request_only=True,
    ),
    # ONE_MONTH_API_TABLE_SPECS_V6_BEGIN
    TableSpec(
        "kospi_1m_candidates_30",
        "코피표1개월 후보 30",
        "kospi_1m_candidates_30.json",
        ("kospi_1m_candidates_30_latest.csv",),
        required=True,
        exact_rows=30,
    ),
    TableSpec(
        "kospi_1m_recommend_7",
        "별도 요청용 코피표1개월 추천 7",
        "kospi_1m_recommend_7.json",
        ("kospi_1m_recommend_7_latest.csv",),
        required=False,
        exact_rows=7,
        default_output=False,
        explicit_request_only=True,
    ),
    TableSpec(
        "kosdaq_1m_candidates_10",
        "코닥표1개월 후보 10",
        "kosdaq_1m_candidates_10.json",
        ("kosdaq_1m_candidates_10_latest.csv",),
        required=True,
        exact_rows=10,
    ),
    TableSpec(
        "kosdaq_1m_recommend_5",
        "별도 요청용 코닥표1개월 추천 5",
        "kosdaq_1m_recommend_5.json",
        ("kosdaq_1m_recommend_5_latest.csv",),
        required=False,
        exact_rows=5,
        default_output=False,
        explicit_request_only=True,
    ),
    # ONE_MONTH_API_TABLE_SPECS_V6_END
# US_WATCHLIST_API_TABLE_SPECS_V6_BEGIN
    TableSpec(
        "us_watchlist",
        "미관종표 S&P500 후보 30",
        "us_watchlist.json",
        ("us_sp500_watchlist_latest.csv",),
        required=True,
        exact_rows=30,
    ),
    TableSpec(
        "us_watchlist_recommend_7",
        "별도 요청용 미관종표 추천 7",
        "us_watchlist_recommend_7.json",
        ("us_sp500_recommend_7_latest.csv",),
        required=False,
        exact_rows=7,
        default_output=False,
        explicit_request_only=True,
    ),
# US_WATCHLIST_API_TABLE_SPECS_V6_END
    TableSpec(
        "kospi_gainers_1m", "코급표 후보", "kospi_gainers_1m.json",
        ("kospi_gainers_1m_current_basis_latest.csv", "kospi_gainers_1m_latest.csv"),
        required=True, min_rows=15,
    ),
    TableSpec(
        "kospi_monthly_cycle", "월사이클표 핵심 후보", "kospi_monthly_cycle.json",
        ("kospi_monthly_cycle_latest.csv",), min_rows=1,
        default_output=True,
        explicit_request_only=False,
    ),
    TableSpec(
        "kospi_monthly_cycle_candidates", "월사이클표 전체 후보", "kospi_monthly_cycle_candidates.json",
        ("kospi_monthly_cycle_candidates_latest.csv",), min_rows=1,
        default_output=False,
        explicit_request_only=True,
    ),
    TableSpec(
        "kospi_fx_weakness_candidates_30", "환율약세표 후보 30",
        "kospi_fx_weakness_candidates_30.json",
        ("kospi_fx_weakness_candidates_30_latest.csv",), exact_rows=30,
    ),
    TableSpec(
        "kospi_fx_weakness_recommend_7", "별도 요청용 환율약세 추천 7",
        "kospi_fx_weakness_recommend_7.json",
        ("kospi_fx_weakness_recommend_7_latest.csv",), exact_rows=7,
        default_output=False, explicit_request_only=True,
    ),
    TableSpec(
        "kospi_short_term_candidates_30", "단상표 후보 30",
        "kospi_short_term_candidates_30.json",
        ("kospi_short_term_candidates_30_latest.csv",), exact_rows=30,
    ),
    TableSpec(
        "kospi_short_term_recommend_7", "별도 요청용 단상 추천 7",
        "kospi_short_term_recommend_7.json",
        ("kospi_short_term_recommend_7_latest.csv",), exact_rows=7,
        default_output=False, explicit_request_only=True,
    ),
)

JSON_SNAPSHOTS: Tuple[Tuple[str, str, str], ...] = (
    ("official_data_status", "공식 KRX 최신성 상태", "official_data_status_latest.json"),
    ("krx_official_retry_status", "공식 KRX 재시도 상태", "krx_official_retry_status_latest.json"),
    ("current_price_basis", "현재가 보정 상태", "current_price_basis_latest.json"),
    ("data_freshness_notice", "자료 최신성 안내", "data_freshness_notice_latest.json"),
    ("table_health", "전체 표 통합 점검", "table_health_latest.json"),
    ("market_status", "시장 상태", "data_status_latest.json"),
    ("macro_leverage", "거시·레버리지 위험", "macro_leverage_latest.json"),
    ("kofia_macro_bridge_status", "KOFIA 연결 상태", "kofia_macro_bridge_status_latest.json"),
    ("bubble_risk", "버블 위험 상태", "bubble_risk_latest.json"),
)


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def iso_kst(dt: Optional[datetime] = None) -> str:
    return (dt or kst_now()).isoformat(timespec="seconds")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "UNKNOWN"


def load_holidays() -> set[str]:
    path = CONFIG / "krx_market_holidays.json"
    data = read_json(path)
    values: Iterable[Any] = []
    if isinstance(data, dict):
        for key in ("holidays", "dates", "market_holidays"):
            if isinstance(data.get(key), list):
                values = data[key]
                break
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                values = raw
        except Exception:
            values = []
    result: set[str] = set()
    for value in values:
        if isinstance(value, str):
            result.add(value[:10])
        elif isinstance(value, dict):
            day = value.get("date") or value.get("day")
            if day:
                result.add(str(day)[:10])
    return result


def previous_trading_day(base_date: date) -> date:
    holidays = load_holidays()
    cursor = base_date - timedelta(days=1)
    while cursor.weekday() >= 5 or cursor.isoformat() in holidays:
        cursor -= timedelta(days=1)
    return cursor


def expected_official_date(now: datetime) -> date:
    # 기존 수집기의 08:30 게시 컷오프 규칙과 동일하게 계산한다.
    cutoff_reached = (now.hour, now.minute) >= (8, 30)
    expected_base = now.date() if cutoff_reached else now.date() - timedelta(days=1)
    return previous_trading_day(expected_base)


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return None


def choose_latest_status() -> Tuple[Dict[str, Any], str]:
    candidates = (
        ("official_data_status_latest.json", read_json(LATEST / "official_data_status_latest.json")),
        ("krx_official_retry_status_latest.json", read_json(LATEST / "krx_official_retry_status_latest.json")),
    )
    valid: List[Tuple[datetime, str, Dict[str, Any]]] = []
    for name, data in candidates:
        if not data:
            continue
        dt = parse_dt(data.get("run_at_kst"))
        if dt is None:
            dt = datetime.min
        valid.append((dt, name, data))
    if not valid:
        return {}, ""
    valid.sort(key=lambda item: item[0], reverse=True)
    _, name, data = valid[0]
    return data, name


def normalized_official_meta(now: datetime) -> Dict[str, Any]:
    source, source_name = choose_latest_status()
    expected = expected_official_date(now).isoformat()
    kospi = source.get("kospi_actual_date")
    kosdaq = source.get("kosdaq_actual_date")
    same = bool(kospi and kosdaq and kospi == kosdaq)
    fresh_now = bool(same and str(kospi) >= expected and str(kosdaq) >= expected)
    return {
        "source_file": source_name or None,
        "source_run_at_kst": source.get("run_at_kst"),
        "source_expected_official_trading_date": source.get("expected_official_trading_date"),
        "computed_expected_official_trading_date": expected,
        "kospi_actual_date": kospi,
        "kosdaq_actual_date": kosdaq,
        "basis_date_for_display": source.get("basis_date_for_display") or kospi or kosdaq,
        "same_market_date": same,
        "official_fresh_at_source": bool(source.get("official_fresh", source.get("fresh", False))),
        "official_fresh_now": fresh_now,
        "collector_return_code": source.get("collector_return_code"),
        "source_status": source.get("official_status") or source.get("status"),
        "source_display_label": source.get("display_label"),
        "source_warning": source.get("warning"),
        "kospi_summary_rows": source.get("kospi_summary_rows"),
        "kosdaq_summary_rows": source.get("kosdaq_summary_rows"),
    }


def rules_meta() -> Tuple[Dict[str, Any], str]:
    text = RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.exists() else ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    match = re.search(r"(?:규칙 버전|rules_version)\s*[:：]\s*`?([0-9A-Za-z._-]+)`?", text)
    if match is None:
        match = re.search(r"최종 업데이트\s*[:：]\s*([0-9A-Za-z._-]+)", text)
    version = match.group(1) if match else "UNKNOWN"
    return {
        "source_file": str(RULES_PATH.relative_to(ROOT)) if RULES_PATH.exists() else None,
        "version": version,
        "sha256": digest,
    }, text


def read_csv(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig")
    dtype = {col: str for col in ("ticker", "code", "종목코드") if col in header.columns}
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=dtype)
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=dtype)
    return df


def choose_source(names: Sequence[str]) -> Optional[Path]:
    for name in names:
        path = LATEST / name
        if path.exists():
            return path
    return None


def normalized_key(series: pd.Series, key: str) -> pd.Series:
    values = series.astype(str).str.strip()
    if key in {"code", "ticker", "종목코드"}:
        values = values.str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return values


def overlay_dataframe(base: pd.DataFrame, overlay_path: Optional[Path]) -> Tuple[pd.DataFrame, Optional[str]]:
    if overlay_path is None or not overlay_path.exists() or base.empty:
        return base, None
    overlay = read_csv(overlay_path)
    if overlay.empty:
        return base, None
    key = next(
        (candidate for candidate in ("code", "ticker", "종목코드", "name", "종목명")
         if candidate in base.columns and candidate in overlay.columns),
        None,
    )
    if key is None:
        return base, None

    left = base.copy()
    right = overlay.copy()
    left["_sync_key"] = normalized_key(left[key], key)
    right["_sync_key"] = normalized_key(right[key], key)
    right = right.drop_duplicates("_sync_key", keep="first").set_index("_sync_key")
    left = left.set_index("_sync_key")
    common_cols = [col for col in left.columns if col in right.columns and col != key]
    for col in common_cols:
        mapped = left.index.to_series().map(right[col])
        left[col] = mapped.where(mapped.notna(), left[col])
    left = left.reset_index(drop=True)
    return left, str(overlay_path.relative_to(ROOT))


def date_range_from_df(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    preferred = (
        "asof_date", "last_date", "date", "basDt", "trading_date",
        "분석자료 기준일", "기준일",
    )
    all_dates: List[pd.Timestamp] = []
    used_cols: List[str] = []
    for col in preferred:
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce").dropna()
        if parsed.empty:
            continue
        used_cols.append(col)
        all_dates.extend(parsed.tolist())
    if not all_dates:
        return {"data_date_min": None, "data_date_max": None, "date_columns": []}
    return {
        "data_date_min": min(all_dates).date().isoformat(),
        "data_date_max": max(all_dates).date().isoformat(),
        "date_columns": used_cols,
    }


def current_price_meta() -> Dict[str, Any]:
    basis = read_json(LATEST / "current_price_basis_latest.json")
    fresh = read_json(LATEST / "data_freshness_notice_latest.json")
    supplement = read_json(LATEST / "supplement_current_prices_latest.json")
    candidates = [
        basis.get("run_at_kst"),
        fresh.get("aux_run_at_kst"),
        supplement.get("run_at_kst"),
        supplement.get("generated_at_kst"),
    ]
    parsed = [(parse_dt(v), v) for v in candidates if v]
    parsed = [(dt, v) for dt, v in parsed if dt is not None]
    latest_value = max(parsed, key=lambda item: item[0])[1] if parsed else None
    return {
        "current_price_asof_kst": latest_value,
        "current_price_basis_status": basis.get("status"),
        "aux_price_count": basis.get("aux_price_count"),
        "current_basis_ok_files": basis.get("ok_files"),
        "time_after_hours_reflected": fresh.get("time_after_hours_reflected"),
        "freshness_mode": fresh.get("mode"),
    }


def row_count_ok(spec: TableSpec, count: int) -> Tuple[bool, str]:
    if spec.exact_rows is not None and count != spec.exact_rows:
        return False, f"EXPECTED_EXACT_{spec.exact_rows}_GOT_{count}"
    if spec.min_rows is not None and count < spec.min_rows:
        return False, f"EXPECTED_MIN_{spec.min_rows}_GOT_{count}"
    return True, "OK"


def dataframe_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    clean = df.astype(object).where(pd.notna(df), None)
    return clean.to_dict(orient="records")


def build_table(
    spec: TableSpec,
    *,
    build_id: str,
    generated_at: str,
    commit_sha: str,
    official: Dict[str, Any],
    price_meta: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    source_path = choose_source(spec.sources)
    base: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "script": SCRIPT_VERSION,
        "table_id": spec.table_id,
        "display_name": spec.display_name,
        "generated_at_kst": generated_at,
        "source_commit_sha": commit_sha,
        "required": spec.required,
        "default_output": spec.default_output,
        "explicit_request_only": spec.explicit_request_only,
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
        "rules_version": rules.get("version"),
        "rules_sha256": rules.get("sha256"),
        "expected_rows": {
            "exact": spec.exact_rows,
            "minimum": spec.min_rows,
        },
        "official_data": official,
        "current_price_basis": price_meta,
        "rules": rules,
    }

    if source_path is None:
        base.update({
            "status": "MISSING",
            "source_file": None,
            "overlay_source_file": None,
            "row_count": 0,
            "row_count_ok": False if spec.required else True,
            "validation_message": "SOURCE_FILE_MISSING",
            "columns": [],
            "rows": [],
        })
        return base

    try:
        df = read_csv(source_path)
        overlay_path = LATEST / spec.overlay_source if spec.overlay_source else None
        df, overlay_used = overlay_dataframe(df, overlay_path)
        ok, message = row_count_ok(spec, len(df))
        base.update({
            "status": "OK" if ok else "ROW_COUNT_ERROR",
            "source_file": str(source_path.relative_to(ROOT)),
            "source_priority": list(spec.sources),
            "current_basis_selected": "_current_basis_" in source_path.name,
            "overlay_source_file": overlay_used,
            "row_count": int(len(df)),
            "row_count_ok": ok,
            "validation_message": message,
            "columns": list(df.columns),
            **date_range_from_df(df),
            "rows": dataframe_records(df),
        })
        return base
    except Exception as exc:
        base.update({
            "status": "READ_ERROR",
            "source_file": str(source_path.relative_to(ROOT)),
            "overlay_source_file": None,
            "row_count": 0,
            "row_count_ok": False,
            "validation_message": f"{type(exc).__name__}: {exc}",
            "columns": [],
            "rows": [],
        })
        return base


def snapshot_payload(
    snapshot_id: str,
    display_name: str,
    source_name: str,
    *,
    build_id: str,
    generated_at: str,
    commit_sha: str,
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    source = LATEST / source_name
    data = read_json(source)
    return {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "snapshot_id": snapshot_id,
        "display_name": display_name,
        "generated_at_kst": generated_at,
        "source_commit_sha": commit_sha,
        "source_file": str(source.relative_to(ROOT)),
        "status": "OK" if data else "MISSING_OR_INVALID",
        "rules_version": rules.get("version"),
        "rules_sha256": rules.get("sha256"),
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
        "rules": rules,
        "data": data,
    }


# HOLDINGS_PRIVATE_RUNTIME_BUILD_V6_BEGIN
def build_holdings_public_reference_api() -> None:
    command = [
        sys.executable,
        str(ROOT / "build_stock_reference_api.py"),
        "--kospi-summary",
        str(LATEST / "kospi_universe_summary_latest.csv"),
        "--kosdaq-summary",
        str(LATEST / "kosdaq_universe_summary_latest.csv"),
        "--api-dir",
        str(API),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Stock reference API build failed: "
            f"{completed.returncode}"
        )
    print("HOLDINGS_PUBLIC_REFERENCE_API=OK")
# HOLDINGS_PRIVATE_RUNTIME_BUILD_V6_END

def main() -> int:
    build_holdings_public_reference_api()
    now = kst_now()
    generated_at = iso_kst(now)
    commit_sha = git_sha()
    build_id = f"{now.strftime('%Y%m%dT%H%M%S%z')}-{commit_sha[:10]}"
    official = normalized_official_meta(now)
    price_meta = current_price_meta()
    rules, rules_text = rules_meta()

    table_results: List[Dict[str, Any]] = []
    manifest_tables: List[Dict[str, Any]] = []
    critical_errors: List[str] = []
    warnings: List[str] = []

    for spec in TABLE_SPECS:
        payload = build_table(
            spec,
            build_id=build_id,
            generated_at=generated_at,
            commit_sha=commit_sha,
            official=official,
            price_meta=price_meta,
            rules=rules,
        )
        write_json(API / spec.output_name, payload)
        table_results.append(payload)
        manifest_tables.append({
            "table_id": spec.table_id,
            "display_name": spec.display_name,
            "api_file": f"api/{spec.output_name}",
            "source_file": payload.get("source_file"),
            "overlay_source_file": payload.get("overlay_source_file"),
            "status": payload.get("status"),
            "row_count": payload.get("row_count"),
            "required": spec.required,
        "default_output": spec.default_output,
        "explicit_request_only": spec.explicit_request_only,
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
            "current_basis_selected": payload.get("current_basis_selected"),
        })
        if spec.required and payload.get("status") != "OK":
            critical_errors.append(
                f"{spec.table_id}:{payload.get('status')}:{payload.get('validation_message')}"
            )
        elif payload.get("status") not in {"OK", "MISSING"}:
            warnings.append(
                f"{spec.table_id}:{payload.get('status')}:{payload.get('validation_message')}"
            )

    # 상태·거시 JSON도 Action으로 직접 읽을 수 있게 복제한다.
    snapshot_files: List[Dict[str, Any]] = []
    for snapshot_id, display_name, source_name in JSON_SNAPSHOTS:
        payload = snapshot_payload(
            snapshot_id, display_name, source_name,
            build_id=build_id,
            generated_at=generated_at,
            commit_sha=commit_sha,
            rules=rules,
        )
        output_name = f"{snapshot_id}.json"
        write_json(API / output_name, payload)
        snapshot_files.append({
            "snapshot_id": snapshot_id,
            "display_name": display_name,
            "api_file": f"api/{output_name}",
            "source_file": payload["source_file"],
            "status": payload["status"],
        })

    rules_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "status": "OK" if rules_text else "MISSING",
        "generated_at_kst": generated_at,
        "source_commit_sha": commit_sha,
        "source_file": rules.get("source_file"),
        "rules_version": rules.get("version"),
        "rules_sha256": rules.get("sha256"),
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
        "content_markdown": rules_text,
    }
    write_json(API / "stock_table_rules.json", rules_payload)
    if not rules_text:
        critical_errors.append("stock_table_rules:MISSING")

    api_sync_ok = not critical_errors
    official_fresh_now = bool(official.get("official_fresh_now"))
    safe_latest = bool(api_sync_ok and official_fresh_now)
    if not official_fresh_now:
        warnings.append(
            "OFFICIAL_DATA_NOT_FRESH_NOW:"
            f"expected={official.get('computed_expected_official_trading_date')},"
            f"kospi={official.get('kospi_actual_date')},"
            f"kosdaq={official.get('kosdaq_actual_date')}"
        )

    if critical_errors:
        overall_status = "API_SYNC_ERROR"
    elif not official_fresh_now:
        overall_status = "STALE_OFFICIAL"
    else:
        overall_status = "READY"

    status_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "script": SCRIPT_VERSION,
        "generated_at_kst": generated_at,
        "source_commit_sha": commit_sha,
        "status": overall_status,
        "api_sync_ok": api_sync_ok,
        "official_fresh_now": official_fresh_now,
        "safe_to_analyze_as_latest": safe_latest,
        "confirmed_basis_date": official.get("basis_date_for_display"),
        "computed_expected_official_trading_date": official.get(
            "computed_expected_official_trading_date"
        ),
        "kospi_actual_date": official.get("kospi_actual_date"),
        "kosdaq_actual_date": official.get("kosdaq_actual_date"),
        "official_status_source": official.get("source_file"),
        "official_status_source_run_at_kst": official.get("source_run_at_kst"),
        "current_price_asof_kst": price_meta.get("current_price_asof_kst"),
        "current_price_basis_status": price_meta.get("current_price_basis_status"),
        "rules_version": rules.get("version"),
        "rules_sha256": rules.get("sha256"),
        "required_table_count": sum(1 for spec in TABLE_SPECS if spec.required),
        "generated_table_count": len(TABLE_SPECS),
        "critical_errors": critical_errors,
        "warnings": warnings,
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
        "usage_rule": (
            "Custom GPT must call this endpoint first. "
            "Only when api_sync_ok and official_fresh_now are both true may it "
            "describe the data as the latest official dataset. "
            "Default output must use the improvement-plan-2 final format: "
            "one compact metadata table, one main stock table, bold buy/target "
            "price ranges, and only minimal necessary notes. "
            "Never add a Monday or weekly usage guide automatically. "
            "Output the full eight-section manual only when the user requests "
            "'설명서'. If api_sync_ok is false, stop table analysis."
        ),
    }
    write_json(API / "status.json", status_payload)

    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "generated_at_kst": generated_at,
        "source_commit_sha": commit_sha,
        "status": overall_status,
        "api_sync_ok": api_sync_ok,
        "safe_to_analyze_as_latest": safe_latest,
        "rules_version": rules.get("version"),
        "rules_sha256": rules.get("sha256"),
        "rules": rules,
        "presentation_policy": PRESENTATION_POLICY,
        "request_time_price_policy": REQUEST_TIME_PRICE_POLICY,
        "tables": manifest_tables,
        "snapshots": snapshot_files,
        "control_files": [
            "api/status.json",
            "api/manifest.json",
            "api/stock_table_rules.json",
            "api/validation_report.json",
        ],
    }
    write_json(API / "manifest.json", manifest_payload)

    # LIGHTWEIGHT_WATCHLIST_BUILD_V66_BEGIN
    from build_lightweight_watchlist_api_v66 import (
        build_lightweight_watchlists,
    )
    lightweight_entries = build_lightweight_watchlists(API)
    print(
        "LIGHTWEIGHT_WATCHLISTS="
        + ",".join(
            f"{item['table_id']}:{item['row_count']}:"
            f"{item['payload_size_bytes']}"
            for item in lightweight_entries
        )
    )
    # LIGHTWEIGHT_WATCHLIST_BUILD_V66_END

    # FINAL_DISPLAY_CONTRACT_V71_BEGIN
    from apply_final_display_contract_v71 import (
        apply_final_display_contract,
    )
    final_display_entries = apply_final_display_contract(API)
    print(
        "FINAL_DISPLAY_ENTRIES="
        + ",".join(
            f"{item['filename']}:{item['row_count']}"
            for item in final_display_entries
        )
    )
    # FINAL_DISPLAY_CONTRACT_V71_END

    # KR_SECTOR_THEME_V72_BEGIN
    from apply_kr_sector_theme_v72 import (
        apply_kr_sector_theme,
    )
    kr_sector_entries = apply_kr_sector_theme(API, LATEST)
    print(
        "KR_SECTOR_THEME_ENTRIES="
        + ",".join(
            f"{item['table_id']}:{item['sector_theme_matched']}"
            for item in kr_sector_entries
        )
    )
    # KR_SECTOR_THEME_V72_END

    # DISPLAY_NORMALIZATION_V74_BEGIN
    from apply_display_normalization_v74 import (
        apply_display_normalization,
    )
    display_normalization_entries = (
        apply_display_normalization(API)
    )
    print(
        "DISPLAY_NORMALIZATION_ENTRIES="
        + ",".join(
            f"{item['table_id']}:{item['row_count']}"
            for item in display_normalization_entries
        )
    )
    # DISPLAY_NORMALIZATION_V74_END

    print(f"BUILD_ID={build_id}")
    print(f"API_STATUS={overall_status}")
    print(f"API_SYNC_OK={str(api_sync_ok).lower()}")
    print(f"OFFICIAL_FRESH_NOW={str(official_fresh_now).lower()}")
    print(f"SAFE_TO_ANALYZE_AS_LATEST={str(safe_latest).lower()}")
    print(f"CONFIRMED_BASIS_DATE={official.get('basis_date_for_display')}")
    print(f"EXPECTED_OFFICIAL_DATE={official.get('computed_expected_official_trading_date')}")
    print(f"CURRENT_PRICE_ASOF_KST={price_meta.get('current_price_asof_kst')}")
    print(f"RULES_VERSION={rules.get('version')}")
    if critical_errors:
        print("CRITICAL_ERRORS=" + " | ".join(critical_errors))
    if warnings:
        print("WARNINGS=" + " | ".join(warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
