#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kofia_market_status.py

선택 보완 2-1단계: 금융투자협회 종합통계정보 세 API 독립 수집기

수집 대상
- 일자별 CMA 현황
- 신용공여 잔고 추이
- 증시자금 추이

설계 원칙
- 기존 market_status.py / official_index_status.py는 수정하지 않는다.
- 세 API 중 일부가 실패해도 나머지 수집은 계속한다.
- 신규 응답이 비어 있거나 오류가 나면 기존 정상 이력 파일을 지우지 않는다.
- JSON/XML 응답을 모두 자동 판별한다.
- API 원본 필드는 최대한 그대로 보존하고 basDt만 공통 date 열로 정규화한다.
- 필드 구조 검증 결과와 API별 상태를 JSON/로그로 남긴다.
- 이번 단계에서는 bubble_risk_latest.json에 신호를 합치지 않는다.

필수 GitHub Secret
- DATA_GO_KR_SERVICE_KEY

권장 GitHub Actions Variables 또는 환경변수
- KOFIA_CMA_API_URL
- KOFIA_CREDIT_API_URL
- KOFIA_MARKET_FUNDS_API_URL

선택 환경변수: 각 API의 정확한 조회 파라미터를 JSON 문자열로 지정
- KOFIA_CMA_QUERY_JSON
- KOFIA_CREDIT_QUERY_JSON
- KOFIA_MARKET_FUNDS_QUERY_JSON

예시
KOFIA_CMA_QUERY_JSON={"pageNo":1,"numOfRows":1000,"resultType":"json","basDt":"20260604"}

선택 환경변수: 확인된 필수 필드 목록을 쉼표로 지정
- KOFIA_CREDIT_REQUIRED_FIELDS
- KOFIA_MARKET_FUNDS_REQUIRED_FIELDS

생성/갱신 파일
- latest/kofia_cma_history_latest.csv
- latest/kofia_credit_history_latest.csv
- latest/kofia_market_funds_history_latest.csv
- latest/kofia_market_funds_summary_latest.csv
- latest/kofia_market_funds_status_latest.json
- latest/kofia_market_funds_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_VERSION = "kofia_market_status.py v1.0_three_api_collector"
BASE_URL = "https://apis.data.go.kr/1160100/service/GetKofiaStatisticsInfoService"
KNOWN_MARKET_FUNDS_URL = f"{BASE_URL}/getSecuritiesMarketTotalCapitalInfo"

# 주소가 현재 파일에 노출되지 않은 API는 추측하지 않고 환경변수로 받는다.
API_SPECS: Dict[str, Dict[str, Any]] = {
    "cma": {
        "label": "일자별 CMA 현황",
        "url_env": "KOFIA_CMA_API_URL",
        "default_url": "",
        "query_env": "KOFIA_CMA_QUERY_JSON",
        "required_fields_env": "KOFIA_CMA_REQUIRED_FIELDS",
        "required_fields_default": [
            "basDt",
            "mngInvTgt",
            "invrCtg",
            "scrtCmpyCnt",
            "actCnt",
            "actBal",
        ],
        "history_file": "kofia_cma_history_latest.csv",
    },
    "credit": {
        "label": "신용공여 잔고 추이",
        "url_env": "KOFIA_CREDIT_API_URL",
        "default_url": "",
        "query_env": "KOFIA_CREDIT_QUERY_JSON",
        "required_fields_env": "KOFIA_CREDIT_REQUIRED_FIELDS",
        "required_fields_default": ["basDt"],
        "history_file": "kofia_credit_history_latest.csv",
    },
    "market_funds": {
        "label": "증시자금 추이",
        "url_env": "KOFIA_MARKET_FUNDS_API_URL",
        "default_url": KNOWN_MARKET_FUNDS_URL,
        "query_env": "KOFIA_MARKET_FUNDS_QUERY_JSON",
        "required_fields_env": "KOFIA_MARKET_FUNDS_REQUIRED_FIELDS",
        "required_fields_default": ["basDt"],
        "history_file": "kofia_market_funds_history_latest.csv",
    },
}

TEXT_COLUMN_HINTS = (
    "nm",
    "name",
    "ctg",
    "type",
    "tgt",
    "code",
    "cd",
    "kind",
    "market",
    "note",
    "status",
)
DATE_COLUMN_HINTS = ("dt", "date", "ymd")
NON_DATA_KEYS = {
    "resultCode",
    "resultMsg",
    "pageNo",
    "numOfRows",
    "totalCount",
}


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def read_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype={"basDt": str})
    except UnicodeDecodeError:
        try:
            return pd.read_csv(path, dtype={"basDt": str})
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_json_env(name: str, log_lines: List[str]) -> Dict[str, Any]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        log_lines.append(f"QUERY_ENV_INVALID {name}: JSON object required")
    except Exception as exc:
        log_lines.append(f"QUERY_ENV_PARSE_FAIL {name}: {type(exc).__name__}: {exc}")
    return {}


def parse_required_fields(spec: Dict[str, Any]) -> List[str]:
    raw = os.getenv(spec["required_fields_env"], "").strip()
    if raw:
        return [field.strip() for field in raw.split(",") if field.strip()]
    return list(spec.get("required_fields_default", []))


def mask_url(url: str) -> str:
    if not url:
        return ""
    # 혹시 URL 자체에 serviceKey가 들어 있어도 로그에는 노출하지 않는다.
    return re.sub(r"([?&](?:serviceKey|ServiceKey|authKey|AUTH_KEY)=)[^&]+", r"\1***", url)


def response_header_info(payload: Any) -> Dict[str, Any]:
    """공공데이터포털의 일반적인 response/header 구조에서 결과코드/메시지를 찾는다."""
    found: Dict[str, Any] = {}

    def walk(obj: Any) -> None:
        if found.get("resultCode") is not None and found.get("resultMsg") is not None:
            return
        if isinstance(obj, dict):
            for key in ("resultCode", "resultMsg", "returnAuthMsg", "returnReasonCode"):
                if key in obj and key not in found:
                    found[key] = obj.get(key)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj[:10]:
                walk(value)

    walk(payload)
    return found


def find_json_items(payload: Any) -> List[Dict[str, Any]]:
    """다양한 공공데이터 JSON 포장 구조에서 실제 item 레코드를 재귀적으로 찾는다."""
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) for item in payload):
            return payload
        for item in payload:
            found = find_json_items(item)
            if found:
                return found
        return []

    if not isinstance(payload, dict):
        return []

    if "item" in payload:
        item = payload["item"]
        if isinstance(item, list):
            return [row for row in item if isinstance(row, dict)]
        if isinstance(item, dict):
            return [item]

    # 흔한 포장 키를 먼저 탐색한다.
    for key in ("items", "body", "response", "data", "result", "OutBlock_1", "output"):
        if key in payload:
            found = find_json_items(payload[key])
            if found:
                return found

    # 최상위 자체가 단일 실제 레코드인 경우
    data_keys = [key for key in payload.keys() if key not in NON_DATA_KEYS]
    if "basDt" in payload or (len(data_keys) >= 2 and all(not isinstance(payload[k], (dict, list)) for k in data_keys)):
        return [payload]

    for value in payload.values():
        found = find_json_items(value)
        if found:
            return found
    return []


def parse_xml_rows(text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    root = ET.fromstring(text)
    header: Dict[str, Any] = {}
    for tag in ("resultCode", "resultMsg", "returnAuthMsg", "returnReasonCode"):
        node = root.find(f".//{tag}")
        if node is not None:
            header[tag] = node.text

    rows: List[Dict[str, Any]] = []
    item_nodes = root.findall(".//item")
    for item in item_nodes:
        row = {child.tag: (child.text or "").strip() for child in list(item)}
        if row:
            rows.append(row)

    if rows:
        return rows, header

    # item 태그가 없는 XML도 잎 노드 묶음을 레코드 후보로 인식한다.
    for parent in root.iter():
        children = list(parent)
        if not children:
            continue
        if all(len(list(child)) == 0 for child in children):
            row = {child.tag: (child.text or "").strip() for child in children}
            data_keys = [key for key in row if key not in NON_DATA_KEYS]
            if "basDt" in row or len(data_keys) >= 2:
                rows.append(row)

    return rows, header


def build_params(spec: Dict[str, Any], service_key: str, log_lines: List[str]) -> Dict[str, Any]:
    # 공공데이터포털의 일반 기본값이며, 확인된 정확한 값은 *_QUERY_JSON이 우선한다.
    params: Dict[str, Any] = {
        "pageNo": 1,
        "numOfRows": 1000,
        "resultType": "json",
    }
    params.update(parse_json_env(spec["query_env"], log_lines))
    params["serviceKey"] = service_key
    return params


def request_api(
    api_key: str,
    spec: Dict[str, Any],
    service_key: str,
    timeout: int,
    log_lines: List[str],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    url = os.getenv(spec["url_env"], spec.get("default_url", "")).strip()
    status: Dict[str, Any] = {
        "api": api_key,
        "label": spec["label"],
        "configured": bool(url),
        "url": mask_url(url),
        "status": "NOT_STARTED",
        "http_status": None,
        "response_header": {},
        "fresh_rows": 0,
        "response_columns": [],
    }

    if not url:
        status["status"] = "URL_NOT_CONFIGURED"
        log_lines.append(f"API_SKIP {api_key}: {spec['url_env']} not configured")
        return pd.DataFrame(), status

    if not service_key:
        status["status"] = "SERVICE_KEY_MISSING"
        log_lines.append(f"API_SKIP {api_key}: DATA_GO_KR_SERVICE_KEY missing")
        return pd.DataFrame(), status

    params = build_params(spec, service_key, log_lines)
    # 비밀키나 조회값 전체는 로그에 기록하지 않고, 키 이름만 남긴다.
    status["query_parameter_names"] = sorted([str(key) for key in params.keys() if str(key).lower() != "servicekey"])

    try:
        response = requests.get(url, params=params, timeout=timeout)
        status["http_status"] = response.status_code
    except Exception as exc:
        status["status"] = "REQUEST_EXCEPTION"
        status["error"] = f"{type(exc).__name__}: {exc}"
        log_lines.append(f"API_REQUEST_EXCEPTION {api_key}: {type(exc).__name__}: {exc}")
        return pd.DataFrame(), status

    if response.status_code != 200:
        status["status"] = "HTTP_FAIL"
        status["response_head"] = response.text[:250].replace("\n", " ")
        log_lines.append(f"API_HTTP_FAIL {api_key}: status={response.status_code}")
        return pd.DataFrame(), status

    text = response.text.lstrip("\ufeff \t\r\n")
    rows: List[Dict[str, Any]] = []
    header_info: Dict[str, Any] = {}
    parse_mode = "unknown"

    try:
        if text.startswith("<"):
            rows, header_info = parse_xml_rows(text)
            parse_mode = "xml"
        else:
            payload = response.json()
            rows = find_json_items(payload)
            header_info = response_header_info(payload)
            parse_mode = "json"
    except Exception as first_exc:
        # Content-Type이나 resultType과 실제 본문 형식이 다른 경우 반대 방식으로 한 번 더 시도한다.
        try:
            if text.startswith("<"):
                payload = response.json()
                rows = find_json_items(payload)
                header_info = response_header_info(payload)
                parse_mode = "json_fallback"
            else:
                rows, header_info = parse_xml_rows(text)
                parse_mode = "xml_fallback"
        except Exception as second_exc:
            status["status"] = "PARSE_FAIL"
            status["error"] = (
                f"primary={type(first_exc).__name__}: {first_exc}; "
                f"fallback={type(second_exc).__name__}: {second_exc}"
            )
            status["response_head"] = text[:250].replace("\n", " ")
            log_lines.append(f"API_PARSE_FAIL {api_key}: {status['error']}")
            return pd.DataFrame(), status

    status["parse_mode"] = parse_mode
    status["response_header"] = header_info

    if not rows:
        status["status"] = "EMPTY_RESPONSE"
        log_lines.append(f"API_EMPTY {api_key}: parse_mode={parse_mode}, header={header_info}")
        return pd.DataFrame(), status

    frame = pd.DataFrame(rows)
    status["status"] = "RECEIVED"
    status["fresh_rows"] = len(frame)
    status["response_columns"] = [str(col) for col in frame.columns]
    log_lines.append(f"API_RECEIVED {api_key}: rows={len(frame)}, cols={len(frame.columns)}, parse={parse_mode}")
    return frame, status


def clean_numeric_text(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace({"": None, "-": None, "nan": None, "None": None, "null": None})
    )


def likely_text_or_date_column(column: str) -> bool:
    lower = str(column).lower()
    return any(hint in lower for hint in TEXT_COLUMN_HINTS + DATE_COLUMN_HINTS)


def normalize_frame(api_key: str, frame: pd.DataFrame, collected_at: datetime) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    df = frame.copy()
    df.columns = [str(col).strip() for col in df.columns]

    # 원본 basDt는 문자열로 유지하고 공통 date를 별도로 생성한다.
    if "basDt" in df.columns:
        df["basDt"] = df["basDt"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        parsed = pd.to_datetime(df["basDt"], format="%Y%m%d", errors="coerce")
        if parsed.isna().all():
            parsed = pd.to_datetime(df["basDt"], errors="coerce")
        date_text = parsed.dt.strftime("%Y-%m-%d")
        if "date" in df.columns:
            df["date"] = date_text.fillna(df["date"].astype(str))
        else:
            df.insert(0, "date", date_text)

    # 수치처럼 보이는 열만 안전하게 숫자로 변환한다.
    for col in list(df.columns):
        if col in {"date", "basDt", "_source_api", "_collected_at_kst"}:
            continue
        if likely_text_or_date_column(col):
            continue
        cleaned = clean_numeric_text(df[col])
        numeric = pd.to_numeric(cleaned, errors="coerce")
        non_empty = cleaned.notna().sum()
        numeric_ratio = (numeric.notna().sum() / non_empty) if non_empty else 0.0
        if numeric_ratio >= 0.80:
            df[col] = numeric

    df["_source_api"] = api_key
    df["_collected_at_kst"] = collected_at.isoformat(timespec="seconds")
    return df


def validate_fields(df: pd.DataFrame, required_fields: Iterable[str]) -> Tuple[List[str], List[str]]:
    required = [str(field) for field in required_fields if str(field).strip()]
    missing = [field for field in required if field not in df.columns]
    return required, missing


def normalize_existing(df: pd.DataFrame, api_key: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "basDt" in out.columns:
        out["basDt"] = out["basDt"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    if "_source_api" not in out.columns:
        out["_source_api"] = api_key
    return out


def combine_history(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if (existing is None or existing.empty) and (fresh is None or fresh.empty):
        return pd.DataFrame()
    if fresh is None or fresh.empty:
        return existing.copy()
    if existing is None or existing.empty:
        combined = fresh.copy()
    else:
        combined = pd.concat([existing, fresh], ignore_index=True, sort=False)

    # 수집시각만 다른 동일 레코드는 하나로 만든다.
    dedup_cols = [col for col in combined.columns if col != "_collected_at_kst"]
    if dedup_cols:
        combined = combined.drop_duplicates(subset=dedup_cols, keep="last")

    sort_cols = [col for col in ("date", "basDt") if col in combined.columns]
    if sort_cols:
        combined = combined.sort_values(sort_cols, na_position="last")
    return combined.reset_index(drop=True)


def latest_date_value(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None
    if "date" in df.columns:
        values = pd.to_datetime(df["date"], errors="coerce")
        if values.notna().any():
            return values.max().strftime("%Y-%m-%d")
    if "basDt" in df.columns:
        values = df["basDt"].astype(str).str.replace(r"\.0$", "", regex=True)
        values = values[values.str.fullmatch(r"\d{8}", na=False)]
        if not values.empty:
            value = values.max()
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return None


def latest_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    latest = latest_date_value(out)
    if latest and "date" in out.columns:
        parsed = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        return out[parsed == latest].copy()
    if latest and "basDt" in out.columns:
        compact = latest.replace("-", "")
        return out[out["basDt"].astype(str).str.replace(r"\.0$", "", regex=True) == compact].copy()
    return out.tail(1).copy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--timeout", type=int, default=35)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    ensure_dir(outdir)
    run_at = now_kst()
    service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()

    log_lines: List[str] = [
        f"script={SCRIPT_VERSION}",
        f"run_at_kst={run_at.isoformat(timespec='seconds')}",
        f"service_key_configured={bool(service_key)}",
    ]
    api_statuses: Dict[str, Dict[str, Any]] = {}
    histories: Dict[str, pd.DataFrame] = {}
    fresh_success_count = 0
    preserved_count = 0

    for api_key, spec in API_SPECS.items():
        history_path = outdir / spec["history_file"]
        existing = normalize_existing(read_csv_safely(history_path), api_key)
        raw_fresh, status = request_api(api_key, spec, service_key, args.timeout, log_lines)
        fresh = normalize_frame(api_key, raw_fresh, run_at)

        required, missing = validate_fields(fresh, parse_required_fields(spec))
        status["required_fields"] = required
        status["missing_required_fields"] = missing
        status["existing_rows_before"] = len(existing)

        if not fresh.empty and missing:
            status["status"] = "FIELD_VALIDATION_FAIL"
            log_lines.append(f"FIELD_VALIDATION_FAIL {api_key}: missing={missing}")
            # 필드 구조가 틀린 응답은 정상 이력에 합치지 않는다.
            combined = existing.copy()
        elif not fresh.empty:
            combined = combine_history(existing, fresh)
            write_csv(combined, history_path)
            fresh_success_count += 1
            status["status"] = "OK"
            log_lines.append(
                f"HISTORY_WRITTEN {api_key}: fresh={len(fresh)}, total={len(combined)}, file={history_path.as_posix()}"
            )
        else:
            combined = existing.copy()
            if not existing.empty:
                preserved_count += 1
                status["preserved_existing"] = True
                log_lines.append(f"HISTORY_PRESERVED {api_key}: existing_rows={len(existing)}")
            else:
                status["preserved_existing"] = False

        status["total_rows_after"] = len(combined)
        status["latest_date"] = latest_date_value(combined)
        status["stored_columns"] = [str(col) for col in combined.columns]
        api_statuses[api_key] = status
        histories[api_key] = combined

    summary_frames: List[pd.DataFrame] = []
    for api_key, df in histories.items():
        part = latest_rows(df)
        if part.empty:
            continue
        part = part.copy()
        part.insert(0, "api", api_key)
        part.insert(1, "api_label", API_SPECS[api_key]["label"])
        summary_frames.append(part)

    summary_path = outdir / "kofia_market_funds_summary_latest.csv"
    if summary_frames:
        summary = pd.concat(summary_frames, ignore_index=True, sort=False)
        write_csv(summary, summary_path)
        log_lines.append(f"SUMMARY_WRITTEN rows={len(summary)}, file={summary_path.as_posix()}")
    else:
        summary = pd.DataFrame()
        log_lines.append("SUMMARY_NOT_WRITTEN no usable history rows")

    configured_count = sum(1 for status in api_statuses.values() if status.get("configured"))
    usable_history_count = sum(1 for df in histories.values() if df is not None and not df.empty)
    if fresh_success_count == len(API_SPECS):
        overall_status = "OK_ALL_FRESH"
    elif fresh_success_count > 0:
        overall_status = "PARTIAL_FRESH"
    elif usable_history_count > 0:
        overall_status = "NO_FRESH_USING_PRESERVED_HISTORY"
    elif configured_count == 0:
        overall_status = "NO_API_URL_CONFIGURED"
    else:
        overall_status = "NO_DATA"

    status_doc: Dict[str, Any] = {
        "script": SCRIPT_VERSION,
        "generated_at_kst": run_at,
        "overall_status": overall_status,
        "service_key_configured": bool(service_key),
        "configured_api_count": configured_count,
        "fresh_success_count": fresh_success_count,
        "preserved_existing_count": preserved_count,
        "usable_history_count": usable_history_count,
        "summary_rows": len(summary),
        "apis": api_statuses,
        "next_stage_note": "세 API 원자료 수집/검증 단계입니다. 위험 신호 결합은 별도 다음 단계에서 수행합니다.",
    }

    status_path = outdir / "kofia_market_funds_status_latest.json"
    log_path = outdir / "kofia_market_funds_run_log_latest.txt"
    write_json(status_path, status_doc)

    log_lines.extend(
        [
            f"overall_status={overall_status}",
            f"configured_api_count={configured_count}",
            f"fresh_success_count={fresh_success_count}",
            f"preserved_existing_count={preserved_count}",
            f"usable_history_count={usable_history_count}",
            f"summary_rows={len(summary)}",
            f"status_file={status_path.as_posix()}",
        ]
    )
    write_text(log_path, "\n".join(log_lines) + "\n")
    print("\n".join(log_lines))

    # 부분 실패가 전체 GitHub Actions를 중단시키지 않도록 정상 종료한다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
