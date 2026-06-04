#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "macro_leverage_status.py v2.0_ecos_datagokr_official"

ECOS_BASE = "https://ecos.bok.or.kr/api"

RISK_THRESHOLDS = {
    "usdk_rw_high": 1500.0,
    "usdk_rw_extreme": 1550.0,
    "usdk_rw_1m_rise_pct": 3.0,
    "usdk_rw_1m_extreme_pct": 5.0,
    "korea3y_high_pct": 3.7,
    "korea3y_extreme_pct": 4.0,
    "korea10y_high_pct": 3.8,
    "korea10y_extreme_pct": 4.2,
    "credit_balance_high_million_krw": 35_000_000.0,
    "credit_balance_extreme_million_krw": 40_000_000.0,
    "credit_deposit_ratio_high_pct": 25.0,
    "credit_deposit_ratio_extreme_pct": 30.0,
}

ECOS_TARGETS = [
    {
        "indicator_code": "USDKRW_ECOS_731Y001",
        "indicator_name": "원달러 환율",
        "stat_code": "731Y001",
        "cycle": "D",
        "unit": "KRW per USD",
        "item_keywords": [["원/달러"], ["미국", "달러"], ["달러"]],
        "fallback_item_code": "0000001",
    },
    {
        "indicator_code": "KOREA3Y_ECOS_817Y002",
        "indicator_name": "국고채 3년 금리",
        "stat_code": "817Y002",
        "cycle": "D",
        "unit": "percent",
        "item_keywords": [["국고채", "3년"], ["국채", "3년"]],
        "fallback_item_code": None,
    },
    {
        "indicator_code": "KOREA10Y_ECOS_817Y002",
        "indicator_name": "국고채 10년 금리",
        "stat_code": "817Y002",
        "cycle": "D",
        "unit": "percent",
        "item_keywords": [["국고채", "10년"], ["국채", "10년"]],
        "fallback_item_code": None,
    },
]

KOFIA_CUSTOM_URL_TARGETS = [
    {
        "env_name": "KOFIA_CREDIT_API_URL",
        "indicator_code": "KOFIA_CREDIT_FINANCING_MILLION_KRW",
        "indicator_name": "신용융자 또는 신용공여 잔고",
        "unit": "million KRW",
        "value_hints": ["신용", "융자", "공여", "잔고", "crdt", "credit", "loan", "bal"],
    },
    {
        "env_name": "KOFIA_MARKET_FUNDS_API_URL",
        "indicator_code": "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW",
        "indicator_name": "투자자예탁금 또는 증시자금",
        "unit": "million KRW",
        "value_hints": ["예탁", "고객", "투자자", "증시자금", "deposit", "money"],
    },
    {
        "env_name": "KOFIA_CMA_API_URL",
        "indicator_code": "KOFIA_CMA_BALANCE_MILLION_KRW",
        "indicator_name": "CMA 잔고",
        "unit": "million KRW",
        "value_hints": ["CMA", "cma", "잔고", "balance", "bal"],
    },
]


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if pd.isna(value):
            return None
        return float(value)
    if isinstance(value, float):
        if pd.isna(value):
            return None
        return value
    if value is pd.NA:
        return None
    return value


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        s = str(value).strip().replace(",", "")
        if s in ["", "-", ".", "nan", "None"]:
            return None
        return float(s)
    except Exception:
        return None


def http_text(url: str, timeout: int = 30) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; krx-watchlist-auto/2.0)",
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ["utf-8", "euc-kr", "cp949"]:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def http_json(url: str, log_lines: List[str], label: str, tries: int = 2) -> Optional[Dict[str, Any]]:
    last_error = None
    for attempt in range(1, tries + 1):
        try:
            text = http_text(url, timeout=30)
            if not text or len(text.strip()) < 2:
                last_error = "empty response"
                log_lines.append(f"HTTP_EMPTY {label}: attempt={attempt}")
            else:
                return json.loads(text)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            log_lines.append(f"HTTP_FAIL {label}: attempt={attempt}, {last_error}")
        time.sleep(attempt)
    log_lines.append(f"HTTP_FINAL_FAIL {label}: {last_error}")
    return None


def extract_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    for key in ["StatisticSearch", "StatisticItemList"]:
        obj = data.get(key)
        if isinstance(obj, dict):
            rows = obj.get("row")
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
            if isinstance(rows, dict):
                return [rows]

    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == "row":
                    if isinstance(v, list):
                        return [r for r in v if isinstance(r, dict)]
                    if isinstance(v, dict):
                        return [v]
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)

    return []


def ecos_item_list(api_key: str, stat_code: str, cycle: str, log_lines: List[str]) -> List[Dict[str, Any]]:
    candidates = [
        f"{ECOS_BASE}/StatisticItemList/{api_key}/json/kr/1/10000/{stat_code}/{cycle}",
        f"{ECOS_BASE}/StatisticItemList/{api_key}/json/kr/1/10000/{stat_code}",
    ]

    for url in candidates:
        data = http_json(url, log_lines, f"ECOS_ITEM {stat_code}", tries=2)
        if not data:
            continue
        rows = extract_rows(data)
        if rows:
            log_lines.append(f"ECOS_ITEM_OK {stat_code}: rows={len(rows)}")
            return rows

    log_lines.append(f"ECOS_ITEM_EMPTY {stat_code}")
    return []


def row_name_text(row: Dict[str, Any]) -> str:
    parts = []
    for k, v in row.items():
        ku = str(k).upper()
        if "NAME" in ku or "NM" in ku or "항목" in str(k):
            parts.append(str(v))
    return " ".join(parts)


def row_item_code(row: Dict[str, Any]) -> Optional[str]:
    for k in ["ITEM_CODE", "ITEM_CODE1", "ITEM_CD", "ITEM_CD1", "STAT_CODE"]:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    for k, v in row.items():
        ku = str(k).upper()
        if "ITEM" in ku and ("CODE" in ku or "CD" in ku):
            if str(v).strip():
                return str(v).strip()
    return None


def select_ecos_item_code(
    rows: List[Dict[str, Any]],
    keyword_groups: List[List[str]],
    fallback_item_code: Optional[str],
    log_lines: List[str],
    label: str,
) -> Optional[str]:
    for keywords in keyword_groups:
        for row in rows:
            text = row_name_text(row)
            if all(kw.lower() in text.lower() for kw in keywords):
                code = row_item_code(row)
                if code:
                    log_lines.append(f"ECOS_ITEM_SELECT {label}: code={code}, name={text}")
                    return code

    if fallback_item_code:
        log_lines.append(f"ECOS_ITEM_FALLBACK {label}: code={fallback_item_code}")
        return fallback_item_code

    sample = "; ".join(row_name_text(r)[:60] for r in rows[:5])
    log_lines.append(f"ECOS_ITEM_NOT_FOUND {label}: sample={sample}")
    return None


def ecos_stat_search(
    api_key: str,
    target: Dict[str, Any],
    item_code: str,
    start_ymd: str,
    end_ymd: str,
    log_lines: List[str],
) -> pd.DataFrame:
    stat_code = target["stat_code"]
    cycle = target["cycle"]
    url = f"{ECOS_BASE}/StatisticSearch/{api_key}/json/kr/1/10000/{stat_code}/{cycle}/{start_ymd}/{end_ymd}/{item_code}"

    data = http_json(url, log_lines, f"ECOS_STAT {target['indicator_code']}", tries=2)
    if not data:
        log_lines.append(f"ECOS_STAT_FAIL {target['indicator_code']}: no json")
        return pd.DataFrame()

    rows = extract_rows(data)
    if not rows:
        log_lines.append(f"ECOS_STAT_EMPTY {target['indicator_code']}")
        return pd.DataFrame()

    out_rows = []
    for r in rows:
        date_raw = str(r.get("TIME", "")).strip()
        value = safe_float(r.get("DATA_VALUE"))
        if not date_raw or value is None:
            continue

        if len(date_raw) == 8:
            dt = pd.to_datetime(date_raw, format="%Y%m%d", errors="coerce")
        elif len(date_raw) == 6:
            dt = pd.to_datetime(date_raw + "01", format="%Y%m%d", errors="coerce")
        else:
            dt = pd.to_datetime(date_raw, errors="coerce")

        if pd.isna(dt):
            continue

        out_rows.append(
            {
                "date": dt.date().isoformat(),
                "indicator_code": target["indicator_code"],
                "indicator_name": target["indicator_name"],
                "value": value,
                "unit": target["unit"],
                "frequency": "daily" if target["cycle"] == "D" else target["cycle"],
                "source": "BOK ECOS official API",
                "source_url": url.replace(api_key, "ECOS_API_KEY"),
            }
        )

    out = pd.DataFrame(out_rows)
    log_lines.append(f"ECOS_STAT_OK {target['indicator_code']}: rows={len(out)}")
    return out


def collect_ecos_history(start_date: pd.Timestamp, end_date: pd.Timestamp, log_lines: List[str]) -> pd.DataFrame:
    api_key = os.getenv("ECOS_API_KEY", "").strip()
    if not api_key:
        log_lines.append("ECOS_API_KEY_MISSING")
        return pd.DataFrame()

    start_ymd = start_date.strftime("%Y%m%d")
    end_ymd = end_date.strftime("%Y%m%d")
    frames = []

    item_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    for target in ECOS_TARGETS:
        cache_key = (target["stat_code"], target["cycle"])
        if cache_key not in item_cache:
            item_cache[cache_key] = ecos_item_list(api_key, target["stat_code"], target["cycle"], log_lines)

        item_code = select_ecos_item_code(
            item_cache[cache_key],
            target["item_keywords"],
            target.get("fallback_item_code"),
            log_lines,
            target["indicator_code"],
        )

        if not item_code:
            continue

        one = ecos_stat_search(api_key, target, item_code, start_ymd, end_ymd, log_lines)
        if not one.empty:
            frames.append(one)
        time.sleep(0.2)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def replace_service_key(url: str) -> str:
    key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not key:
        return url
    for token in ["{DATA_GO_KR_SERVICE_KEY}", "{{DATA_GO_KR_SERVICE_KEY}}", "SERVICE_KEY_HERE", "YOUR_SERVICE_KEY"]:
        url = url.replace(token, key)
    return url


def flatten_json_records(obj: Any) -> List[Dict[str, Any]]:
    records = []

    def walk(x: Any):
        if isinstance(x, dict):
            if len(x) >= 2 and any(isinstance(v, (str, int, float)) for v in x.values()):
                records.append(x)
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return records


def find_date_value_from_record(record: Dict[str, Any], value_hints: List[str]):
    date_value = None
    value = None

    date_keys = ["date", "bas", "stdr", "trd", "time", "일자", "기준", "날짜"]

    for k, v in record.items():
        ks = str(k).lower()
        if any(dk in ks for dk in date_keys):
            s = str(v).strip()
            digits = re.sub(r"[^0-9]", "", s)
            if len(digits) >= 8:
                date_value = digits[:8]
                break
            if len(digits) == 6:
                date_value = digits + "01"

    candidate_values = []

    for k, v in record.items():
        fv = safe_float(v)
        if fv is None:
            continue
        ks = str(k).lower()
        score = 0
        for h in value_hints:
            if h.lower() in ks:
                score += 2
        if "amt" in ks or "bal" in ks or "잔고" in str(k) or "금액" in str(k):
            score += 1
        candidate_values.append((score, fv, k))

    if candidate_values:
        candidate_values.sort(key=lambda x: (x[0], abs(x[1])), reverse=True)
        value = candidate_values[0][1]

    if date_value:
        dt = pd.to_datetime(date_value, format="%Y%m%d", errors="coerce")
        date_iso = dt.date().isoformat() if pd.notna(dt) else None
    else:
        date_iso = now_kst().date().isoformat()

    return date_iso, value


def fetch_custom_kofia_url(target: Dict[str, Any], log_lines: List[str]) -> pd.DataFrame:
    url = os.getenv(target["env_name"], "").strip()
    if not url:
        log_lines.append(f"{target['env_name']}_MISSING")
        return pd.DataFrame()

    if "{DATA_GO_KR_SERVICE_KEY}" in url and not os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip():
        log_lines.append(f"{target['env_name']}_SERVICE_KEY_MISSING")
        return pd.DataFrame()

    url = replace_service_key(url)

    data = http_json(url, log_lines, f"KOFIA_CUSTOM {target['indicator_code']}", tries=2)
    if not data:
        log_lines.append(f"KOFIA_CUSTOM_FAIL {target['indicator_code']}: no json")
        return pd.DataFrame()

    records = flatten_json_records(data)
    rows = []
    for rec in records:
        dt, value = find_date_value_from_record(rec, target["value_hints"])
        if dt and value is not None:
            rows.append(
                {
                    "date": dt,
                    "indicator_code": target["indicator_code"],
                    "indicator_name": target["indicator_name"],
                    "value": value,
                    "unit": target["unit"],
                    "frequency": "daily_or_api",
                    "source": "data.go.kr KOFIA custom URL",
                    "source_url": re.sub(r"serviceKey=[^&]+", "serviceKey=DATA_GO_KR_SERVICE_KEY", url, flags=re.I),
                }
            )

    out = pd.DataFrame(rows).drop_duplicates(subset=["date", "indicator_code"], keep="last")
    log_lines.append(f"KOFIA_CUSTOM_OK {target['indicator_code']}: rows={len(out)}")
    return out


def collect_kofia_custom_history(log_lines: List[str]) -> pd.DataFrame:
    frames = []
    for target in KOFIA_CUSTOM_URL_TARGETS:
        one = fetch_custom_kofia_url(target, log_lines)
        if not one.empty:
            frames.append(one)
        time.sleep(0.2)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def combine_with_existing(fresh: pd.DataFrame, existing_path: Path, lookback_days: int, log_lines: List[str]) -> pd.DataFrame:
    existing = read_csv(existing_path)
    frames = []

    if not existing.empty:
        frames.append(existing)
    if fresh is not None and not fresh.empty:
        frames.append(fresh)

    columns = ["date", "indicator_code", "indicator_name", "value", "unit", "frequency", "source", "source_url"]

    if not frames:
        return pd.DataFrame(columns=columns)

    combined = pd.concat(frames, ignore_index=True)

    for col in columns:
        if col not in combined.columns:
            combined[col] = np.nan

    combined["date_dt"] = pd.to_datetime(combined["date"], errors="coerce")
    combined["value"] = pd.to_numeric(combined["value"], errors="coerce")
    combined = combined.dropna(subset=["date_dt", "indicator_code", "value"])
    combined = combined.drop_duplicates(subset=["date", "indicator_code"], keep="last")

    if combined.empty:
        log_lines.append(f"MACRO_COMBINE: existing={len(existing)}, fresh={0 if fresh is None else len(fresh)}, combined=0")
        return combined.drop(columns=["date_dt"], errors="ignore")

    max_date = combined["date_dt"].max()
    cutoff = max_date - pd.Timedelta(days=lookback_days)
    combined = combined[combined["date_dt"] >= cutoff]
    combined = combined.sort_values(["indicator_code", "date_dt"])
    combined["date"] = combined["date_dt"].dt.date.astype(str)
    combined = combined.drop(columns=["date_dt"])

    log_lines.append(f"MACRO_COMBINE: existing={len(existing)}, fresh={0 if fresh is None else len(fresh)}, combined={len(combined)}")
    return combined.reset_index(drop=True)


def value_on_or_before(g: pd.DataFrame, target_date: pd.Timestamp) -> Optional[float]:
    part = g[g["date_dt"] <= target_date].sort_values("date_dt")
    if part.empty:
        return None
    return safe_float(part.iloc[-1]["value"])


def build_macro_summary(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty:
        return pd.DataFrame()

    df = hist.copy()
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date_dt", "value", "indicator_code"])

    rows = []
    for code, g in df.groupby("indicator_code", sort=False):
        g = g.sort_values("date_dt").copy()
        last = g.iloc[-1]
        last_date = last["date_dt"]
        latest = safe_float(last["value"])

        v_7d = value_on_or_before(g, last_date - pd.Timedelta(days=7))
        v_1m = value_on_or_before(g, last_date - pd.Timedelta(days=30))
        v_3m = value_on_or_before(g, last_date - pd.Timedelta(days=90))

        def pct_change(base):
            if latest is None or base is None or base == 0:
                return None
            return round((latest / base - 1) * 100, 2)

        def diff_change(base):
            if latest is None or base is None:
                return None
            return round(latest - base, 4)

        rows.append(
            {
                "indicator_code": code,
                "indicator_name": last.get("indicator_name"),
                "latest_date": last_date.date().isoformat(),
                "latest_value": latest,
                "unit": last.get("unit"),
                "frequency": last.get("frequency"),
                "source": last.get("source"),
                "source_url": last.get("source_url"),
                "change_7d_pct": pct_change(v_7d),
                "change_1m_pct": pct_change(v_1m),
                "change_3m_pct": pct_change(v_3m),
                "diff_7d": diff_change(v_7d),
                "diff_1m": diff_change(v_1m),
                "diff_3m": diff_change(v_3m),
            }
        )

    return pd.DataFrame(rows)


def summary_value(summary: pd.DataFrame, code: str, field: str = "latest_value") -> Optional[float]:
    if summary.empty:
        return None
    part = summary[summary["indicator_code"].eq(code)]
    if part.empty or field not in part.columns:
        return None
    return safe_float(part.iloc[0][field])


def summary_row(summary: pd.DataFrame, code: str) -> Dict[str, Any]:
    if summary.empty:
        return {}
    part = summary[summary["indicator_code"].eq(code)]
    if part.empty:
        return {}
    return {k: to_jsonable(v) for k, v in part.iloc[0].to_dict().items()}


def add_signal(signals, code, title, market, value, threshold, severity, detail):
    signals.append(
        {
            "code": code,
            "title": title,
            "market": market,
            "value": to_jsonable(value),
            "threshold": threshold,
            "severity": severity,
            "detail": detail,
        }
    )


def classify_macro_leverage(summary: pd.DataFrame) -> Dict[str, Any]:
    signals = []

    usdk = summary_value(summary, "USDKRW_ECOS_731Y001")
    usdk_1m = summary_value(summary, "USDKRW_ECOS_731Y001", "change_1m_pct")
    kr3y = summary_value(summary, "KOREA3Y_ECOS_817Y002")
    kr10y = summary_value(summary, "KOREA10Y_ECOS_817Y002")
    credit = summary_value(summary, "KOFIA_CREDIT_FINANCING_MILLION_KRW")
    deposit = summary_value(summary, "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW")

    if usdk is not None and usdk >= RISK_THRESHOLDS["usdk_rw_high"]:
        severity = "강함" if usdk >= RISK_THRESHOLDS["usdk_rw_extreme"] else "주의"
        add_signal(signals, "MACRO_USDKRW_HIGH", "원달러 환율 고공권", "MACRO", round(usdk, 2), f">= {RISK_THRESHOLDS['usdk_rw_high']}", severity, "원달러 환율 고공권은 외국인 수급과 위험자산 선호에 부담이 될 수 있습니다.")

    if usdk_1m is not None and usdk_1m >= RISK_THRESHOLDS["usdk_rw_1m_rise_pct"]:
        severity = "강함" if usdk_1m >= RISK_THRESHOLDS["usdk_rw_1m_extreme_pct"] else "주의"
        add_signal(signals, "MACRO_USDKRW_1M_RISE", "원달러 환율 1개월 급등", "MACRO", f"{usdk_1m}%", f">= {RISK_THRESHOLDS['usdk_rw_1m_rise_pct']}%", severity, "환율이 단기간 상승하면 외국인 이탈과 성장주 할인율 부담이 커질 수 있습니다.")

    if kr3y is not None and kr3y >= RISK_THRESHOLDS["korea3y_high_pct"]:
        severity = "강함" if kr3y >= RISK_THRESHOLDS["korea3y_extreme_pct"] else "주의"
        add_signal(signals, "MACRO_KOREA3Y_HIGH", "국고채 3년 금리 고공권", "MACRO", f"{kr3y}%", f">= {RISK_THRESHOLDS['korea3y_high_pct']}%", severity, "국고채 3년 금리 상승은 단기 자금비용과 신용융자 부담을 높일 수 있습니다.")

    if kr10y is not None and kr10y >= RISK_THRESHOLDS["korea10y_high_pct"]:
        severity = "강함" if kr10y >= RISK_THRESHOLDS["korea10y_extreme_pct"] else "주의"
        add_signal(signals, "MACRO_KOREA10Y_HIGH", "국고채 10년 금리 고공권", "MACRO", f"{kr10y}%", f">= {RISK_THRESHOLDS['korea10y_high_pct']}", severity, "장기금리 상승은 성장주와 AI·반도체 밸류에이션 부담으로 이어질 수 있습니다.")

    credit_deposit_ratio = None

    if credit is not None and credit >= RISK_THRESHOLDS["credit_balance_high_million_krw"]:
        severity = "강함" if credit >= RISK_THRESHOLDS["credit_balance_extreme_million_krw"] else "주의"
        add_signal(signals, "LEVERAGE_CREDIT_BALANCE_HIGH", "신용융자 잔고 고공권", "LEVERAGE", f"{round(credit / 1_000_000, 2)}조원", f">= {RISK_THRESHOLDS['credit_balance_high_million_krw'] / 1_000_000:.1f}조원", severity, "신용융자 잔고가 높으면 조정 시 반대매매·동반매도 압력이 커질 수 있습니다.")

    if credit is not None and deposit is not None and deposit > 0:
        credit_deposit_ratio = round(credit / deposit * 100, 2)
        if credit_deposit_ratio >= RISK_THRESHOLDS["credit_deposit_ratio_high_pct"]:
            severity = "강함" if credit_deposit_ratio >= RISK_THRESHOLDS["credit_deposit_ratio_extreme_pct"] else "주의"
            add_signal(signals, "LEVERAGE_CREDIT_DEPOSIT_RATIO_HIGH", "예탁금 대비 신용융자 부담", "LEVERAGE", f"{credit_deposit_ratio}%", f">= {RISK_THRESHOLDS['credit_deposit_ratio_high_pct']}%", severity, "예탁금 대비 신용융자 비중이 높아 레버리지 청산 위험이 커질 수 있습니다.")

    strong_count = sum(1 for s in signals if s.get("severity") == "강함")

    return {
        "signal_count": len(signals),
        "strong_signal_count": strong_count,
        "signals": signals,
        "credit_deposit_ratio_pct": credit_deposit_ratio,
        "snapshot": {
            "USDKRW_ECOS_731Y001": summary_row(summary, "USDKRW_ECOS_731Y001"),
            "KOREA3Y_ECOS_817Y002": summary_row(summary, "KOREA3Y_ECOS_817Y002"),
            "KOREA10Y_ECOS_817Y002": summary_row(summary, "KOREA10Y_ECOS_817Y002"),
            "KOFIA_CREDIT_FINANCING_MILLION_KRW": summary_row(summary, "KOFIA_CREDIT_FINANCING_MILLION_KRW"),
            "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW": summary_row(summary, "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW"),
            "KOFIA_CMA_BALANCE_MILLION_KRW": summary_row(summary, "KOFIA_CMA_BALANCE_MILLION_KRW"),
        },
    }


def recalc_risk_level(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    signal_count = len(signals)
    strong_signal_count = sum(1 for s in signals if s.get("severity") == "강함")

    if signal_count >= 5 or (strong_signal_count >= 1 and signal_count >= 4):
        risk_level = "위험"
    elif signal_count >= 3 or strong_signal_count >= 1:
        risk_level = "경계"
    elif signal_count >= 1:
        risk_level = "관찰"
    else:
        risk_level = "정상"

    return {
        "risk_level": risk_level,
        "signal_count": signal_count,
        "strong_signal_count": strong_signal_count,
        "alert_by_signals": risk_level in ["경계", "위험"],
    }


def merge_into_bubble_risk(outdir: Path, macro_result: Dict[str, Any], run_at: datetime, log_lines: List[str]) -> Dict[str, Any]:
    bubble_path = outdir / "bubble_risk_latest.json"
    bubble = read_json(bubble_path)

    if not bubble:
        bubble = {
            "script": SCRIPT_VERSION,
            "run_at": run_at.isoformat(timespec="seconds"),
            "actual_data_last_date": None,
            "data_status": "NO_BUBBLE_BASE",
            "new_confirmed_trading_day": False,
            "signals": [],
        }

    original_signals = bubble.get("signals", [])
    base_signals = [
        s for s in original_signals
        if not str(s.get("code", "")).startswith("MACRO_")
        and not str(s.get("code", "")).startswith("LEVERAGE_")
    ]

    merged_signals = base_signals + macro_result.get("signals", [])
    risk = recalc_risk_level(merged_signals)

    data_status = bubble.get("data_status")
    if not data_status:
        data_status = read_json(outdir / "data_status_latest.json").get("status")

    alert_required = bool(risk["alert_by_signals"] and data_status == "OK_NEW_CONFIRMED_TRADING_DAY")

    bubble["updated_by_macro_leverage"] = SCRIPT_VERSION
    bubble["macro_leverage_run_at"] = run_at.isoformat(timespec="seconds")
    bubble["signals"] = merged_signals
    bubble["risk_level"] = risk["risk_level"]
    bubble["signal_count"] = risk["signal_count"]
    bubble["strong_signal_count"] = risk["strong_signal_count"]
    bubble["alert_by_signals"] = bool(risk["alert_by_signals"])
    bubble["alert_required"] = bool(alert_required)
    bubble["macro_leverage_signal_count"] = macro_result.get("signal_count", 0)
    bubble["macro_leverage_strong_signal_count"] = macro_result.get("strong_signal_count", 0)
    bubble["macro_leverage_snapshot"] = macro_result.get("snapshot", {})
    bubble["macro_credit_deposit_ratio_pct"] = macro_result.get("credit_deposit_ratio_pct")
    bubble["macro_leverage_thresholds"] = RISK_THRESHOLDS

    if alert_required:
        bubble["action_hint"] = "가격·시장폭·쏠림·거시/레버리지 신호가 함께 충족되었습니다. 신용추가매수 중단, 현금확보, 일부 이익보호 검토가 필요합니다."
    elif risk["alert_by_signals"]:
        bubble["action_hint"] = "위험 신호는 기준을 충족하지만 새 확정 거래일이 아니므로 자동 경고 알림은 보류합니다."
    else:
        bubble["action_hint"] = "경고 기준 미충족입니다. 정규 경고 알림은 보내지 않습니다."

    bubble["note"] = "가격·시장폭·쏠림 신호에 한국은행 ECOS 공식 API와 선택적 data.go.kr KOFIA 지표를 병합했습니다."

    write_json(bubble_path, bubble)
    write_csv(pd.DataFrame(merged_signals), outdir / "bubble_risk_signals_latest.csv")

    log_lines.append(f"BUBBLE_MERGE: base_signals={len(base_signals)}, macro_signals={macro_result.get('signal_count', 0)}, merged={len(merged_signals)}")
    log_lines.append(f"bubble_risk_level={bubble['risk_level']}")
    log_lines.append(f"bubble_signal_count={bubble['signal_count']}")
    log_lines.append(f"bubble_alert_required={bubble['alert_required']}")

    return bubble


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-days", type=int, default=370)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    run_at = now_kst()
    end_date = pd.Timestamp(run_at.date())
    start_date = end_date - pd.Timedelta(days=args.lookback_days)

    log_lines = [
        f"script={SCRIPT_VERSION}",
        f"run_at={run_at.isoformat(timespec='seconds')}",
    ]

    ecos = collect_ecos_history(start_date, end_date, log_lines)
    kofia = collect_kofia_custom_history(log_lines)

    frames = []
    if not ecos.empty:
        frames.append(ecos)
    if not kofia.empty:
        frames.append(kofia)

    fresh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    hist_path = outdir / "macro_leverage_history_latest.csv"
    hist = combine_with_existing(fresh, hist_path, args.lookback_days, log_lines)
    summary = build_macro_summary(hist)
    macro_result = classify_macro_leverage(summary)

    macro_latest = {
        "script": SCRIPT_VERSION,
        "run_at": run_at.isoformat(timespec="seconds"),
        "macro_history_rows": int(len(hist)),
        "macro_summary_rows": int(len(summary)),
        "macro_signal_count": int(macro_result.get("signal_count", 0)),
        "macro_strong_signal_count": int(macro_result.get("strong_signal_count", 0)),
        "credit_deposit_ratio_pct": macro_result.get("credit_deposit_ratio_pct"),
        "signals": macro_result.get("signals", []),
        "snapshot": macro_result.get("snapshot", {}),
        "thresholds": RISK_THRESHOLDS,
        "note": "한국은행 ECOS 공식 API와 선택적 data.go.kr KOFIA custom URL 기반 보조자료입니다.",
    }

    write_csv(hist, hist_path)
    write_csv(summary, outdir / "macro_leverage_summary_latest.csv")
    write_csv(pd.DataFrame(macro_result.get("signals", [])), outdir / "macro_leverage_signals_latest.csv")
    write_json(outdir / "macro_leverage_latest.json", macro_latest)

    bubble = merge_into_bubble_risk(outdir, macro_result, run_at, log_lines)

    summary_codes = []
    summary_sources = {}
    if not summary.empty and "indicator_code" in summary.columns:
        summary_codes = [str(x) for x in summary["indicator_code"].tolist()]
        for _, row in summary.iterrows():
            summary_sources[str(row.get("indicator_code"))] = str(row.get("source"))

    log_lines.append(f"macro_success_count={len(summary_codes)}")
    log_lines.append(f"macro_success_codes={','.join(summary_codes)}")
    log_lines.append(f"macro_summary_sources={summary_sources}")
    log_lines.append(f"macro_history_rows={len(hist)}")
    log_lines.append(f"macro_summary_rows={len(summary)}")
    log_lines.append(f"macro_signal_count={macro_result.get('signal_count', 0)}")
    log_lines.append(f"macro_strong_signal_count={macro_result.get('strong_signal_count', 0)}")
    log_lines.append(f"macro_credit_deposit_ratio_pct={macro_result.get('credit_deposit_ratio_pct')}")
    log_lines.append(f"final_bubble_alert_required={bubble.get('alert_required')}")

    log_path = outdir / "macro_leverage_run_log_latest.txt"
    ensure_dir(log_path.parent)
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
