#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
macro_leverage_status.py

선택보완 2번:
- 신용융자/투자자예탁금/CMA잔고/국고채 3년 등 KOFIA 대시보드 지표 수집 시도
- FRED 공개 CSV 기반 USD/KRW, 미국 10년물, 미국 기준금리, 한국 10년물 지표 수집
- macro_leverage_latest.json / macro_leverage_summary_latest.csv 생성
- bubble_risk_latest.json에 macro/leverage 신호를 병합

주의:
- FRED 데이터는 공개 CSV를 사용하므로 별도 API 키가 필요 없다.
- KOFIA 대시보드 스크래핑은 사이트 구조 변경 시 실패할 수 있다.
- KOFIA 공식 OpenAPI까지 완전 연결하려면 data.go.kr 활용신청 후 별도 서비스키가 필요할 수 있다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "macro_leverage_status.py v1.0_credit_fx_rates"

FRED_SERIES = [
    {
        "indicator_code": "USDKRW_FRED_DEXKOUS",
        "indicator_name": "원달러 환율",
        "series_id": "DEXKOUS",
        "unit": "KRW per USD",
        "frequency": "daily",
        "source": "FRED",
    },
    {
        "indicator_code": "US10Y_FRED_DGS10",
        "indicator_name": "미국 10년 국채금리",
        "series_id": "DGS10",
        "unit": "percent",
        "frequency": "daily",
        "source": "FRED",
    },
    {
        "indicator_code": "FEDFUNDS_FRED_DFF",
        "indicator_name": "미국 유효 연방기금금리",
        "series_id": "DFF",
        "unit": "percent",
        "frequency": "daily",
        "source": "FRED",
    },
    {
        "indicator_code": "KOREA10Y_FRED_IRLTLT01KRM156N",
        "indicator_name": "한국 10년 국채금리",
        "series_id": "IRLTLT01KRM156N",
        "unit": "percent",
        "frequency": "monthly",
        "source": "FRED/OECD",
    },
]

KOFIA_URLS = [
    "https://freesis.kofia.or.kr/",
    "https://freesis.kofia.or.kr/main/main.do",
    "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070",
]

RISK_THRESHOLDS = {
    "usdk_rw_high": 1500.0,
    "usdk_rw_extreme": 1550.0,
    "usdk_rw_1m_rise_pct": 3.0,
    "usdk_rw_1m_extreme_pct": 5.0,
    "us10y_high_pct": 4.5,
    "us10y_extreme_pct": 5.0,
    "korea10y_high_pct": 3.8,
    "korea10y_extreme_pct": 4.2,
    "ktb3y_high_pct": 3.7,
    "ktb3y_extreme_pct": 4.0,
    "credit_balance_high_million_krw": 35_000_000.0,
    "credit_balance_extreme_million_krw": 40_000_000.0,
    "credit_deposit_ratio_high_pct": 25.0,
    "credit_deposit_ratio_extreme_pct": 30.0,
}


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


def clean_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in [".", "-", "nan", "None"]:
        return None
    s = s.replace(",", "").replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def http_text(url: str, timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; krx-watchlist-auto/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


def textify_html(src: str) -> str:
    src = html.unescape(src)
    src = re.sub(r"<script[\s\S]*?</script>", " ", src, flags=re.I)
    src = re.sub(r"<style[\s\S]*?</style>", " ", src, flags=re.I)
    src = re.sub(r"<[^>]+>", " ", src)
    src = re.sub(r"\s+", " ", src)
    return src.strip()


def parse_metric_near_label(text: str, label: str) -> Optional[float]:
    escaped = re.escape(label)
    patterns = [
        rf"{escaped}\s*[:：]?\s*(?:[A-Za-z가-힣()%·/\s]*?)\s*([-+]?\d[\d,]*(?:\.\d+)?)",
        rf"{escaped}[^0-9\-+]{{0,120}}([-+]?\d[\d,]*(?:\.\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return clean_number(m.group(1))
    return None


def fetch_kofia_dashboard(log_lines: List[str]) -> pd.DataFrame:
    labels = [
        ("KOFIA_INVESTOR_DEPOSIT_MILLION_KRW", "투자자예탁금", "백만원"),
        ("KOFIA_CREDIT_FINANCING_MILLION_KRW", "신용융자", "백만원"),
        ("KOFIA_CMA_BALANCE_MILLION_KRW", "CMA잔고", "백만원"),
        ("KOFIA_KTB_3Y_PCT", "국고채(3년)", "%"),
    ]

    rows: List[Dict[str, Any]] = []

    for url in KOFIA_URLS:
        try:
            raw = http_text(url)
            text = textify_html(raw)
            found_count = 0

            for code, label, unit in labels:
                value = parse_metric_near_label(text, label)
                if value is not None:
                    found_count += 1
                    rows.append(
                        {
                            "date": now_kst().date().isoformat(),
                            "indicator_code": code,
                            "indicator_name": label,
                            "value": value,
                            "unit": unit,
                            "frequency": "dashboard",
                            "source": "KOFIA FreeSIS dashboard",
                            "source_url": url,
                        }
                    )

            log_lines.append(f"KOFIA_DASHBOARD_TRY {url}: found={found_count}")

            if found_count > 0:
                break

        except Exception as e:
            log_lines.append(f"KOFIA_DASHBOARD_FAIL {url}: {type(e).__name__}: {e}")
            continue

    if not rows:
        log_lines.append("KOFIA_DASHBOARD_STATUS=NO_DATA")
        return pd.DataFrame(
            columns=[
                "date",
                "indicator_code",
                "indicator_name",
                "value",
                "unit",
                "frequency",
                "source",
                "source_url",
            ]
        )

    out = pd.DataFrame(rows).drop_duplicates(subset=["indicator_code"], keep="last")
    log_lines.append(f"KOFIA_DASHBOARD_STATUS=OK rows={len(out)}")
    return out.reset_index(drop=True)


def fetch_fred_series(meta: Dict[str, Any], log_lines: List[str]) -> pd.DataFrame:
    series_id = meta["series_id"]
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

    try:
        raw = pd.read_csv(url)
    except Exception as e:
        log_lines.append(f"FRED_FAIL {series_id}: {type(e).__name__}: {e}")
        return pd.DataFrame()

    if raw.empty or len(raw.columns) < 2:
        log_lines.append(f"FRED_EMPTY {series_id}")
        return pd.DataFrame()

    date_col = raw.columns[0]
    value_col = series_id if series_id in raw.columns else raw.columns[1]

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="coerce"),
            "indicator_code": meta["indicator_code"],
            "indicator_name": meta["indicator_name"],
            "value": pd.to_numeric(raw[value_col].replace(".", np.nan), errors="coerce"),
            "unit": meta["unit"],
            "frequency": meta["frequency"],
            "source": meta["source"],
            "source_url": url,
        }
    )

    out = out.dropna(subset=["date", "value"]).sort_values("date")
    out["date"] = out["date"].dt.date.astype(str)

    log_lines.append(f"FRED_OK {series_id}: rows={len(out)}")
    return out


def collect_macro_history(log_lines: List[str]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    for meta in FRED_SERIES:
        one = fetch_fred_series(meta, log_lines)
        if not one.empty:
            frames.append(one)
        time.sleep(0.05)

    kofia = fetch_kofia_dashboard(log_lines)
    if not kofia.empty:
        frames.append(kofia)

    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "indicator_code",
                "indicator_name",
                "value",
                "unit",
                "frequency",
                "source",
                "source_url",
            ]
        )

    out = pd.concat(frames, ignore_index=True)
    out["date_dt"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date_dt", "indicator_code", "value"])
    out = out.sort_values(["indicator_code", "date_dt"])
    out["date"] = out["date_dt"].dt.date.astype(str)
    out = out.drop(columns=["date_dt"])
    return out.reset_index(drop=True)


def combine_with_existing(
    fresh: pd.DataFrame,
    existing_path: Path,
    lookback_days: int,
    log_lines: List[str],
) -> pd.DataFrame:
    existing = read_csv(existing_path)

    frames: List[pd.DataFrame] = []

    if not existing.empty:
        frames.append(existing)
    if fresh is not None and not fresh.empty:
        frames.append(fresh)

    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "indicator_code",
                "indicator_name",
                "value",
                "unit",
                "frequency",
                "source",
                "source_url",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    combined["date_dt"] = pd.to_datetime(combined["date"], errors="coerce")
    combined["value"] = pd.to_numeric(combined["value"], errors="coerce")
    combined = combined.dropna(subset=["date_dt", "indicator_code", "value"])
    combined = combined.drop_duplicates(subset=["date", "indicator_code"], keep="last")

    max_date = combined["date_dt"].max()
    cutoff = max_date - pd.Timedelta(days=lookback_days)
    combined = combined[combined["date_dt"] >= cutoff]

    combined = combined.sort_values(["indicator_code", "date_dt"])
    combined["date"] = combined["date_dt"].dt.date.astype(str)
    combined = combined.drop(columns=["date_dt"])

    log_lines.append(
        f"MACRO_COMBINE: existing={len(existing)}, fresh={0 if fresh is None else len(fresh)}, combined={len(combined)}"
    )

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
    df = df.dropna(subset=["date_dt", "value"])

    rows: List[Dict[str, Any]] = []

    for code, g in df.groupby("indicator_code", sort=False):
        g = g.sort_values("date_dt").copy()
        last = g.iloc[-1]
        last_date = last["date_dt"]
        latest = safe_float(last["value"])

        v_7d = value_on_or_before(g, last_date - pd.Timedelta(days=7))
        v_1m = value_on_or_before(g, last_date - pd.Timedelta(days=30))
        v_3m = value_on_or_before(g, last_date - pd.Timedelta(days=90))

        def pct_change(base: Optional[float]) -> Optional[float]:
            if latest is None or base is None or base == 0:
                return None
            return round((latest / base - 1) * 100, 2)

        def diff_change(base: Optional[float]) -> Optional[float]:
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


def add_signal(
    signals: List[Dict[str, Any]],
    code: str,
    title: str,
    market: str,
    value: Any,
    threshold: Any,
    severity: str,
    detail: str,
) -> None:
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
    signals: List[Dict[str, Any]] = []

    usdk = summary_value(summary, "USDKRW_FRED_DEXKOUS")
    usdk_1m = summary_value(summary, "USDKRW_FRED_DEXKOUS", "change_1m_pct")
    us10y = summary_value(summary, "US10Y_FRED_DGS10")
    kr10y = summary_value(summary, "KOREA10Y_FRED_IRLTLT01KRM156N")
    ktb3y = summary_value(summary, "KOFIA_KTB_3Y_PCT")
    credit = summary_value(summary, "KOFIA_CREDIT_FINANCING_MILLION_KRW")
    deposit = summary_value(summary, "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW")

    if usdk is not None and usdk >= RISK_THRESHOLDS["usdk_rw_high"]:
        severity = "강함" if usdk >= RISK_THRESHOLDS["usdk_rw_extreme"] else "주의"
        add_signal(
            signals,
            "MACRO_USDKRW_HIGH",
            "원달러 환율 고공권",
            "MACRO",
            round(usdk, 2),
            f">= {RISK_THRESHOLDS['usdk_rw_high']}",
            severity,
            "원달러 환율이 높아 외국인 수급·할인율·위험자산 선호에 부담이 될 수 있습니다.",
        )

    if usdk_1m is not None and usdk_1m >= RISK_THRESHOLDS["usdk_rw_1m_rise_pct"]:
        severity = "강함" if usdk_1m >= RISK_THRESHOLDS["usdk_rw_1m_extreme_pct"] else "주의"
        add_signal(
            signals,
            "MACRO_USDKRW_1M_RISE",
            "원달러 환율 1개월 급등",
            "MACRO",
            f"{usdk_1m}%",
            f">= {RISK_THRESHOLDS['usdk_rw_1m_rise_pct']}%",
            severity,
            "환율이 단기간 상승하면 외국인 이탈과 성장주 밸류에이션 부담이 커질 수 있습니다.",
        )

    if us10y is not None and us10y >= RISK_THRESHOLDS["us10y_high_pct"]:
        severity = "강함" if us10y >= RISK_THRESHOLDS["us10y_extreme_pct"] else "주의"
        add_signal(
            signals,
            "MACRO_US10Y_HIGH",
            "미국 10년물 금리 고공권",
            "MACRO",
            f"{us10y}%",
            f">= {RISK_THRESHOLDS['us10y_high_pct']}%",
            severity,
            "미국 장기금리 상승은 AI·성장주 할인율 부담으로 이어질 수 있습니다.",
        )

    if kr10y is not None and kr10y >= RISK_THRESHOLDS["korea10y_high_pct"]:
        severity = "강함" if kr10y >= RISK_THRESHOLDS["korea10y_extreme_pct"] else "주의"
        add_signal(
            signals,
            "MACRO_KOREA10Y_HIGH",
            "한국 10년물 금리 고공권",
            "MACRO",
            f"{kr10y}%",
            f">= {RISK_THRESHOLDS['korea10y_high_pct']}%",
            severity,
            "국내 장기금리 상승은 주식시장 할인율과 신용비용 부담을 높일 수 있습니다.",
        )

    if ktb3y is not None and ktb3y >= RISK_THRESHOLDS["ktb3y_high_pct"]:
        severity = "강함" if ktb3y >= RISK_THRESHOLDS["ktb3y_extreme_pct"] else "주의"
        add_signal(
            signals,
            "MACRO_KTB3Y_HIGH",
            "국고채 3년 금리 고공권",
            "MACRO",
            f"{ktb3y}%",
            f">= {RISK_THRESHOLDS['ktb3y_high_pct']}%",
            severity,
            "국고채 3년 금리가 높으면 단기 자금비용과 신용융자 부담이 커질 수 있습니다.",
        )

    credit_deposit_ratio = None

    if credit is not None and credit >= RISK_THRESHOLDS["credit_balance_high_million_krw"]:
        severity = "강함" if credit >= RISK_THRESHOLDS["credit_balance_extreme_million_krw"] else "주의"
        add_signal(
            signals,
            "LEVERAGE_CREDIT_BALANCE_HIGH",
            "신용융자 잔고 고공권",
            "LEVERAGE",
            f"{round(credit / 1_000_000, 2)}조원",
            f">= {RISK_THRESHOLDS['credit_balance_high_million_krw'] / 1_000_000:.1f}조원",
            severity,
            "신용융자 잔고가 높으면 주도주 조정 시 반대매매·동반매도 압력이 커질 수 있습니다.",
        )

    if credit is not None and deposit is not None and deposit > 0:
        credit_deposit_ratio = round(credit / deposit * 100, 2)

        if credit_deposit_ratio >= RISK_THRESHOLDS["credit_deposit_ratio_high_pct"]:
            severity = "강함" if credit_deposit_ratio >= RISK_THRESHOLDS["credit_deposit_ratio_extreme_pct"] else "주의"
            add_signal(
                signals,
                "LEVERAGE_CREDIT_DEPOSIT_RATIO_HIGH",
                "투자자예탁금 대비 신용융자 부담",
                "LEVERAGE",
                f"{credit_deposit_ratio}%",
                f">= {RISK_THRESHOLDS['credit_deposit_ratio_high_pct']}%",
                severity,
                "예탁금 대비 신용융자 비중이 높아 레버리지 청산 위험이 커질 수 있습니다.",
            )

    strong_count = sum(1 for s in signals if s.get("severity") == "강함")

    return {
        "signal_count": len(signals),
        "strong_signal_count": strong_count,
        "signals": signals,
        "credit_deposit_ratio_pct": credit_deposit_ratio,
        "snapshot": {
            "USDKRW_FRED_DEXKOUS": summary_row(summary, "USDKRW_FRED_DEXKOUS"),
            "US10Y_FRED_DGS10": summary_row(summary, "US10Y_FRED_DGS10"),
            "FEDFUNDS_FRED_DFF": summary_row(summary, "FEDFUNDS_FRED_DFF"),
            "KOREA10Y_FRED_IRLTLT01KRM156N": summary_row(summary, "KOREA10Y_FRED_IRLTLT01KRM156N"),
            "KOFIA_CREDIT_FINANCING_MILLION_KRW": summary_row(summary, "KOFIA_CREDIT_FINANCING_MILLION_KRW"),
            "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW": summary_row(summary, "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW"),
            "KOFIA_CMA_BALANCE_MILLION_KRW": summary_row(summary, "KOFIA_CMA_BALANCE_MILLION_KRW"),
            "KOFIA_KTB_3Y_PCT": summary_row(summary, "KOFIA_KTB_3Y_PCT"),
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


def merge_into_bubble_risk(
    outdir: Path,
    macro_result: Dict[str, Any],
    run_at: datetime,
    log_lines: List[str],
) -> Dict[str, Any]:
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
        s
        for s in original_signals
        if not str(s.get("code", "")).startswith("MACRO_")
        and not str(s.get("code", "")).startswith("LEVERAGE_")
    ]

    merged_signals = base_signals + macro_result.get("signals", [])
    risk = recalc_risk_level(merged_signals)

    data_status = bubble.get("data_status")

    if not data_status:
        data_status_file = read_json(outdir / "data_status_latest.json")
        data_status = data_status_file.get("status")

    alert_required = bool(
        risk["alert_by_signals"]
        and data_status == "OK_NEW_CONFIRMED_TRADING_DAY"
    )

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
        bubble["action_hint"] = (
            "가격·시장폭·쏠림·거시/레버리지 신호가 함께 충족되었습니다. "
            "신용추가매수 중단, 현금확보, 일부 이익보호 검토가 필요합니다."
        )
    elif risk["alert_by_signals"]:
        bubble["action_hint"] = (
            "위험 신호는 기준을 충족하지만 새 확정 거래일이 아니므로 자동 경고 알림은 보류합니다."
        )
    else:
        bubble["action_hint"] = "경고 기준 미충족입니다. 정규 경고 알림은 보내지 않습니다."

    bubble["note"] = (
        "가격·시장폭·쏠림 신호에 환율·금리·신용융자 보조 신호를 병합했습니다. "
        "KOFIA 대시보드 스크래핑은 사이트 구조 변경 시 비어 있을 수 있습니다."
    )

    write_json(bubble_path, bubble)
    write_csv(pd.DataFrame(merged_signals), outdir / "bubble_risk_signals_latest.csv")

    log_lines.append(
        f"BUBBLE_MERGE: base_signals={len(base_signals)}, macro_signals={macro_result.get('signal_count', 0)}, merged={len(merged_signals)}"
    )
    log_lines.append(f"bubble_risk_level={bubble['risk_level']}")
    log_lines.append(f"bubble_signal_count={bubble['signal_count']}")
    log_lines.append(f"bubble_alert_required={bubble['alert_required']}")

    return bubble


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-days", type=int, default=240)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    run_at = now_kst()

    log_lines: List[str] = []
    log_lines.append(f"script={SCRIPT_VERSION}")
    log_lines.append(f"run_at={run_at.isoformat(timespec='seconds')}")

    fresh = collect_macro_history(log_lines)

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
        "note": "FRED 공개 CSV와 KOFIA FreeSIS 대시보드 스크래핑 기반 보조자료입니다.",
    }

    write_csv(hist, hist_path)
    write_csv(summary, outdir / "macro_leverage_summary_latest.csv")
    write_csv(pd.DataFrame(macro_result.get("signals", [])), outdir / "macro_leverage_signals_latest.csv")
    write_json(outdir / "macro_leverage_latest.json", macro_latest)

    bubble = merge_into_bubble_risk(outdir, macro_result, run_at, log_lines)

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
