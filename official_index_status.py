#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
official_index_status.py

선택 보완 1단계:
KRX 공식 KOSPI/KOSDAQ 지수 API를 수집해서 기존 market_status 결과에 붙인다.

생성/갱신 파일
- latest/official_index_history_latest.csv
- latest/official_index_summary_latest.csv
- latest/market_index_summary_latest.csv
- latest/bubble_risk_latest.json
- latest/bubble_risk_signals_latest.csv
- latest/official_index_run_log_latest.txt

주의
- 기존 market_status.py는 수정하지 않는다.
- KRX_AUTH_KEY가 없거나 지수 API 권한이 없으면 공식지수는 비워두고 기존 프록시 기준을 유지한다.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "official_index_status.py v1.0_official_krx_index"

OPENAPI_INDEX_URLS = {
    "KOSPI": "http://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd",
    "KOSDAQ": "http://data-dbg.krx.co.kr/svc/apis/idx/kosdaq_dd_trd",
}

REPRESENTATIVE_INDEX_NAMES = {
    "KOSPI": ["코스피", "KOSPI"],
    "KOSDAQ": ["코스닥", "KOSDAQ"],
}

RISK_THRESHOLDS = {
    "kospi_1m_overheat_pct": 20.0,
    "kospi_3m_overheat_pct": 35.0,
    "kospi_3m_extreme_pct": 50.0,
    "weak_breadth_up_ratio_pct": 35.0,
    "weak_breadth_down_ratio_pct": 60.0,
    "samsung_hynix_concentration_pct": 45.0,
    "samsung_hynix_extreme_pct": 50.0,
    "kospi_kosdaq_1m_gap_pct": 25.0,
    "kosdaq_1m_weak_pct": -8.0,
    "trading_value_spike_ratio": 1.5,
}


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def read_json_safely(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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
    if isinstance(value, date):
        return value.isoformat()
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


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_number_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace({"": np.nan, "-": np.nan, "nan": np.nan, "None": np.nan}),
        errors="coerce",
    )


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def request_krx_index_api(url: str, auth_key: str, bas_dd: str, label: str, log_lines: List[str]) -> pd.DataFrame:
    if not auth_key:
        log_lines.append(f"OFFICIAL_INDEX_AUTH_KEY_MISSING {label} {bas_dd}")
        return pd.DataFrame()

    try:
        response = requests.get(
            url,
            params={"basDd": bas_dd},
            headers={"AUTH_KEY": auth_key},
            timeout=20,
        )

        if response.status_code != 200:
            log_lines.append(f"OFFICIAL_INDEX_HTTP_FAIL {label} {bas_dd}: status={response.status_code}")
            return pd.DataFrame()

        try:
            data = response.json()
        except Exception:
            log_lines.append(f"OFFICIAL_INDEX_JSON_FAIL {label} {bas_dd}: text_head={response.text[:80]}")
            return pd.DataFrame()

        records = data.get("OutBlock_1") or data.get("output") or data.get("data") or []

        if not isinstance(records, list) or len(records) == 0:
            log_lines.append(f"OFFICIAL_INDEX_EMPTY {label} {bas_dd}")
            return pd.DataFrame()

        return pd.DataFrame(records)

    except Exception as exc:
        log_lines.append(f"OFFICIAL_INDEX_EXCEPTION {label} {bas_dd}: {type(exc).__name__}: {exc}")
        return pd.DataFrame()


def normalize_official_index_rows(raw: pd.DataFrame, market: str, bas_dd: str, log_lines: List[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    if "IDX_NM" not in raw.columns:
        log_lines.append(f"OFFICIAL_INDEX_NORMALIZE_FAIL {market} {bas_dd}: IDX_NM missing")
        return pd.DataFrame()

    name_series = raw["IDX_NM"].astype(str).str.strip()
    target_names = REPRESENTATIVE_INDEX_NAMES.get(market, [])
    part = raw[name_series.isin(target_names)].copy()

    if part.empty:
        if market == "KOSPI":
            part = raw[
                name_series.str.contains("코스피|KOSPI", case=False, na=False)
                & ~name_series.str.contains("200|100|50|대형|중형|소형", na=False)
            ].copy()
        elif market == "KOSDAQ":
            part = raw[
                name_series.str.contains("코스닥|KOSDAQ", case=False, na=False)
                & ~name_series.str.contains("150|글로벌|벤처|스타|프리미어", na=False)
            ].copy()

    if part.empty:
        log_lines.append(f"OFFICIAL_INDEX_TARGET_NOT_FOUND {market} {bas_dd}")
        return pd.DataFrame()

    part = part.head(1).copy()
    idx = part.index

    def col_numeric(col: str) -> pd.Series:
        if col in part.columns:
            return clean_number_series(part[col])
        return pd.Series(index=idx, dtype=float)

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(bas_dd, format="%Y%m%d", errors="coerce"),
            "market": market,
            "official_index_name": part["IDX_NM"].astype(str).values,
            "official_index_close": col_numeric("CLSPRC_IDX").values,
            "official_daily_change": col_numeric("CMPPREVDD_IDX").values,
            "official_daily_return_pct": col_numeric("FLUC_RT").values,
            "official_index_open": col_numeric("OPNPRC_IDX").values,
            "official_index_high": col_numeric("HGPRC_IDX").values,
            "official_index_low": col_numeric("LWPRC_IDX").values,
            "official_trading_volume": col_numeric("ACC_TRDVOL").values,
            "official_trading_value": col_numeric("ACC_TRDVAL").values,
            "official_market_cap": col_numeric("MKTCAP").values,
        }
    )

    out = out.dropna(subset=["date", "official_index_close"])
    return out.reset_index(drop=True)


def collect_official_index_history(start_dt: date, end_dt: date, auth_key: str, log_lines: List[str]) -> pd.DataFrame:
    if not auth_key:
        log_lines.append("OFFICIAL_INDEX_SKIP: KRX_AUTH_KEY missing")
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []

    for d in pd.date_range(start_dt, end_dt, freq="B"):
        bas_dd = pd.Timestamp(d).strftime("%Y%m%d")

        for market, url in OPENAPI_INDEX_URLS.items():
            raw = request_krx_index_api(url, auth_key, bas_dd, f"{market}_index", log_lines)
            one = normalize_official_index_rows(raw, market, bas_dd, log_lines)

            if not one.empty:
                frames.append(one)

            time.sleep(0.03)

    if not frames:
        log_lines.append("OFFICIAL_INDEX_COLLECT: rows=0")
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["date", "market"], keep="last")
    out = out.sort_values(["market", "date"]).reset_index(drop=True)
    log_lines.append(f"OFFICIAL_INDEX_COLLECT: rows={len(out)}")
    return out


def combine_official_index_history(fresh: pd.DataFrame, existing_path: Path, keep_months: int, end_dt: pd.Timestamp, log_lines: List[str]) -> pd.DataFrame:
    existing = read_csv_safely(existing_path)

    if not existing.empty and "date" in existing.columns:
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")

    if fresh is None:
        fresh = pd.DataFrame()

    if not fresh.empty and "date" in fresh.columns:
        fresh["date"] = pd.to_datetime(fresh["date"], errors="coerce")

    frames: List[pd.DataFrame] = []
    if not existing.empty:
        frames.append(existing)
    if not fresh.empty:
        frames.append(fresh)

    if not frames:
        log_lines.append("OFFICIAL_INDEX_COMBINE: rows=0")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["date", "market", "official_index_close"])
    combined = combined.drop_duplicates(subset=["date", "market"], keep="last")

    cutoff = end_dt - relativedelta(months=keep_months)
    combined = combined[(combined["date"] >= cutoff) & (combined["date"] <= end_dt)]
    combined = combined.sort_values(["market", "date"]).reset_index(drop=True)

    log_lines.append(f"OFFICIAL_INDEX_COMBINE: existing={len(existing)}, fresh={len(fresh)}, combined={len(combined)}")
    return combined


def get_first_value_on_or_after(g: pd.DataFrame, date_col: str, value_col: str, target_date: pd.Timestamp):
    part = g[pd.to_datetime(g[date_col]) >= target_date]
    if part.empty:
        return np.nan
    return part.iloc[0][value_col]


def build_official_index_summary(official_hist: pd.DataFrame, end_dt: pd.Timestamp) -> pd.DataFrame:
    if official_hist is None or official_hist.empty:
        return pd.DataFrame()

    oh = official_hist.copy()
    oh["date_dt"] = pd.to_datetime(oh["date"], errors="coerce")
    oh = oh.dropna(subset=["date_dt", "market", "official_index_close"])
    oh = oh[oh["date_dt"] <= end_dt].sort_values(["market", "date_dt"])

    rows: List[Dict[str, Any]] = []

    for market, g in oh.groupby("market", sort=False):
        g = g.sort_values("date_dt").copy()
        last = g.iloc[-1]
        last_date = last["date_dt"]
        last_close = safe_float(last.get("official_index_close"))

        if last_close is None or last_close <= 0:
            continue

        one_month_ago = last_date - relativedelta(months=1)
        three_months_ago = last_date - relativedelta(months=3)

        close_1m = get_first_value_on_or_after(g, "date_dt", "official_index_close", one_month_ago)
        close_3m = get_first_value_on_or_after(g, "date_dt", "official_index_close", three_months_ago)

        ret_1m = round((last_close / float(close_1m) - 1) * 100, 2) if pd.notna(close_1m) and float(close_1m) > 0 else None
        ret_3m = round((last_close / float(close_3m) - 1) * 100, 2) if pd.notna(close_3m) and float(close_3m) > 0 else None

        rows.append(
            {
                "market": market,
                "official_asof_date": last_date.date().isoformat(),
                "official_index_name": last.get("official_index_name"),
                "official_index_close": round(last_close, 2),
                "official_daily_return_pct": safe_float(last.get("official_daily_return_pct")),
                "official_return_1m_pct": ret_1m,
                "official_return_3m_pct": ret_3m,
            }
        )

    return pd.DataFrame(rows)


def update_market_index_summary(market_summary: pd.DataFrame, official_summary: pd.DataFrame) -> pd.DataFrame:
    if market_summary is None or market_summary.empty:
        return pd.DataFrame()

    out = market_summary.copy()

    official_cols = [
        "official_asof_date",
        "official_index_name",
        "official_index_close",
        "official_daily_return_pct",
        "official_return_1m_pct",
        "official_return_3m_pct",
    ]

    for col in official_cols:
        if col not in out.columns:
            out[col] = np.nan

    if "risk_return_source" not in out.columns:
        out["risk_return_source"] = "proxy"

    if official_summary is None or official_summary.empty:
        return out

    off = official_summary.set_index("market")

    for idx, row in out.iterrows():
        market = row.get("market")
        if market not in off.index:
            continue

        for col in official_cols:
            out.at[idx, col] = off.at[market, col]

        if pd.notna(out.at[idx, "official_return_1m_pct"]) and pd.notna(out.at[idx, "official_return_3m_pct"]):
            out.at[idx, "risk_return_source"] = "official"
        else:
            out.at[idx, "risk_return_source"] = "proxy"

    out["index_source"] = "official_krx_index_if_available_else_proxy"
    return out


def row_by_market(summary: pd.DataFrame, market: str) -> Dict[str, Any]:
    if summary.empty:
        return {}
    part = summary[summary["market"].eq(market)]
    if part.empty:
        return {}
    row = part.iloc[0].to_dict()
    return {k: to_jsonable(v) for k, v in row.items()}


def return_value(row: Dict[str, Any], period: str) -> Optional[float]:
    official_key = f"official_return_{period}_pct"
    proxy_key = f"proxy_return_{period}_pct"
    official_value = safe_float(row.get(official_key))
    if official_value is not None:
        return official_value
    return safe_float(row.get(proxy_key))


def daily_return_value(row: Dict[str, Any]) -> Optional[float]:
    official_value = safe_float(row.get("official_daily_return_pct"))
    if official_value is not None:
        return official_value
    return safe_float(row.get("proxy_daily_return_pct"))


def return_source_label(row: Dict[str, Any]) -> str:
    if row.get("risk_return_source") == "official":
        return "공식 KRX 지수"
    return "전종목 시총가중 프록시 지수"


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


def classify_bubble_risk(summary: pd.DataFrame, data_status: Dict[str, Any]) -> Dict[str, Any]:
    kospi = row_by_market(summary, "KOSPI")
    kosdaq = row_by_market(summary, "KOSDAQ")

    signals: List[Dict[str, Any]] = []

    kospi_1m = return_value(kospi, "1m")
    kospi_3m = return_value(kospi, "3m")
    kospi_up = safe_float(kospi.get("up_ratio_pct"))
    kospi_down = safe_float(kospi.get("down_ratio_pct"))
    kospi_daily = daily_return_value(kospi)
    sh_ratio = safe_float(kospi.get("samsung_hynix_market_cap_ratio_pct"))
    kospi_value_ratio = safe_float(kospi.get("trading_value_vs_20d_avg"))
    kospi_source = return_source_label(kospi)

    kosdaq_1m = return_value(kosdaq, "1m")
    kosdaq_up = safe_float(kosdaq.get("up_ratio_pct"))
    kosdaq_source = return_source_label(kosdaq)

    if kospi_1m is not None and kospi_1m >= RISK_THRESHOLDS["kospi_1m_overheat_pct"]:
        add_signal(
            signals,
            "KOSPI_1M_OVERHEAT",
            "KOSPI 1개월 급등 과열",
            "KOSPI",
            kospi_1m,
            f">= {RISK_THRESHOLDS['kospi_1m_overheat_pct']}%",
            "주의",
            f"최근 1개월 {kospi_source} 상승률이 과열 기준을 넘었습니다.",
        )

    if kospi_3m is not None and kospi_3m >= RISK_THRESHOLDS["kospi_3m_overheat_pct"]:
        severity = "강함" if kospi_3m >= RISK_THRESHOLDS["kospi_3m_extreme_pct"] else "주의"
        add_signal(
            signals,
            "KOSPI_3M_OVERHEAT",
            "KOSPI 3개월 급등 과열",
            "KOSPI",
            kospi_3m,
            f">= {RISK_THRESHOLDS['kospi_3m_overheat_pct']}%",
            severity,
            f"최근 3개월 {kospi_source} 상승률이 과열 기준을 넘었습니다.",
        )

    if kospi_up is not None and kospi_down is not None:
        if kospi_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"] and kospi_down >= RISK_THRESHOLDS["weak_breadth_down_ratio_pct"]:
            add_signal(
                signals,
                "KOSPI_BREADTH_WEAKNESS",
                "KOSPI 시장폭 악화",
                "KOSPI",
                f"상승 {kospi_up}%, 하락 {kospi_down}%",
                f"상승 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%, 하락 >= {RISK_THRESHOLDS['weak_breadth_down_ratio_pct']}%",
                "주의",
                "지수 흐름에 비해 상승 종목 비율이 낮고 하락 종목 비율이 높습니다.",
            )

    if kospi_daily is not None and kospi_up is not None:
        if kospi_daily > 0 and kospi_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"]:
            add_signal(
                signals,
                "KOSPI_DISTRIBUTION_STYLE_BREADTH",
                "지수 상승 중 내부 종목 약세",
                "KOSPI",
                f"일간 {kospi_daily}%, 상승종목 {kospi_up}%",
                f"일간 상승 & 상승종목 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%",
                "주의",
                "지수는 올랐지만 다수 종목이 따라오지 못하는 분배형 시장폭 신호입니다.",
            )

    if sh_ratio is not None and sh_ratio >= RISK_THRESHOLDS["samsung_hynix_concentration_pct"]:
        severity = "강함" if sh_ratio >= RISK_THRESHOLDS["samsung_hynix_extreme_pct"] else "주의"
        add_signal(
            signals,
            "SAMSUNG_HYNIX_CONCENTRATION",
            "삼성전자·SK하이닉스 시총 쏠림",
            "KOSPI",
            sh_ratio,
            f">= {RISK_THRESHOLDS['samsung_hynix_concentration_pct']}%",
            severity,
            "KOSPI 시가총액이 삼성전자·SK하이닉스에 과도하게 집중되어 있습니다.",
        )

    if kospi_1m is not None and kosdaq_1m is not None:
        gap = round(kospi_1m - kosdaq_1m, 2)
        if gap >= RISK_THRESHOLDS["kospi_kosdaq_1m_gap_pct"]:
            add_signal(
                signals,
                "KOSPI_KOSDAQ_DIVERGENCE",
                "KOSPI·KOSDAQ 1개월 괴리",
                "ALL",
                gap,
                f">= {RISK_THRESHOLDS['kospi_kosdaq_1m_gap_pct']}%p",
                "주의",
                f"KOSPI는 {kospi_source}, KOSDAQ은 {kosdaq_source} 기준으로 대형주 중심 시장 괴리가 확대되었습니다.",
            )

    if kosdaq_1m is not None and kosdaq_up is not None:
        if kosdaq_1m <= RISK_THRESHOLDS["kosdaq_1m_weak_pct"] and kosdaq_up <= RISK_THRESHOLDS["weak_breadth_up_ratio_pct"]:
            add_signal(
                signals,
                "KOSDAQ_WEAKNESS",
                "KOSDAQ 약세와 시장폭 악화",
                "KOSDAQ",
                f"1개월 {kosdaq_1m}%, 상승종목 {kosdaq_up}%",
                f"1개월 <= {RISK_THRESHOLDS['kosdaq_1m_weak_pct']}%, 상승종목 <= {RISK_THRESHOLDS['weak_breadth_up_ratio_pct']}%",
                "주의",
                f"KOSDAQ이 약세 흐름에 있고 내부 시장폭도 약합니다. 수익률 기준은 {kosdaq_source}입니다.",
            )

    if kospi_value_ratio is not None and kospi_value_ratio >= RISK_THRESHOLDS["trading_value_spike_ratio"]:
        add_signal(
            signals,
            "KOSPI_TRADING_VALUE_SPIKE",
            "KOSPI 거래대금 급증",
            "KOSPI",
            kospi_value_ratio,
            f">= {RISK_THRESHOLDS['trading_value_spike_ratio']}배",
            "주의",
            "최근 거래대금이 20일 평균 대비 빠르게 증가했습니다.",
        )

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

    alert_by_signals = risk_level in ["경계", "위험"]
    alert_required = bool(alert_by_signals and data_status.get("status") == "OK_NEW_CONFIRMED_TRADING_DAY")

    if alert_required:
        action_hint = "신용추가매수 중단, 현금확보, 고비중 주도주 일부 이익보호 검토가 필요합니다."
    elif alert_by_signals:
        action_hint = "위험 신호는 기준을 충족하지만 새 확정 거래일이 아니므로 자동 경고 알림은 보류합니다."
    else:
        action_hint = "경고 기준 미충족입니다. 정규 경고 알림은 보내지 않습니다."

    return {
        "script": SCRIPT_VERSION,
        "run_at": data_status.get("run_at"),
        "actual_data_last_date": data_status.get("actual_data_last_date"),
        "data_status": data_status.get("status"),
        "new_confirmed_trading_day": data_status.get("new_confirmed_trading_day"),
        "risk_level": risk_level,
        "signal_count": signal_count,
        "strong_signal_count": strong_signal_count,
        "alert_by_signals": bool(alert_by_signals),
        "alert_required": bool(alert_required),
        "signals": signals,
        "market_snapshot": {
            "KOSPI": kospi,
            "KOSDAQ": kosdaq,
        },
        "thresholds": RISK_THRESHOLDS,
        "action_hint": action_hint,
        "note": "공식 KRX 지수 수익률이 있으면 공식지수를 우선 사용하고, 없으면 기존 전종목 시총가중 프록시 지수를 사용합니다.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-months", type=int, default=7)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    run_at = now_kst()

    log_lines: List[str] = []
    log_lines.append(f"script={SCRIPT_VERSION}")
    log_lines.append(f"run_at={run_at.isoformat(timespec='seconds')}")

    data_status_path = outdir / "data_status_latest.json"
    market_summary_path = outdir / "market_index_summary_latest.csv"
    official_history_path = outdir / "official_index_history_latest.csv"
    official_summary_path = outdir / "official_index_summary_latest.csv"

    data_status = read_json_safely(data_status_path)
    market_summary = read_csv_safely(market_summary_path)

    actual_date_raw = data_status.get("actual_data_last_date")
    if actual_date_raw:
        end_dt = pd.to_datetime(actual_date_raw, errors="coerce")
    elif not market_summary.empty and "asof_date" in market_summary.columns:
        end_dt = pd.to_datetime(market_summary["asof_date"], errors="coerce").max()
    else:
        end_dt = pd.NaT

    if pd.isna(end_dt):
        log_lines.append("status=NO_ACTUAL_DATE")
        log_lines.append("reason=data_status_latest.json 또는 market_index_summary_latest.csv에서 기준일을 찾지 못했습니다.")
        write_csv(pd.DataFrame(), official_summary_path)
        (outdir / "official_index_run_log_latest.txt").write_text("\n".join(log_lines), encoding="utf-8")
        print("\n".join(log_lines))
        return

    start_dt = end_dt - relativedelta(months=args.lookback_months)
    auth_key = os.getenv("KRX_AUTH_KEY", "").strip()

    official_fresh = collect_official_index_history(start_dt.date(), end_dt.date(), auth_key, log_lines)
    official_history = combine_official_index_history(
        official_fresh,
        official_history_path,
        args.lookback_months,
        end_dt,
        log_lines,
    )

    official_summary = build_official_index_summary(official_history, end_dt)
    updated_market_summary = update_market_index_summary(market_summary, official_summary)

    write_csv(official_history, official_history_path)
    write_csv(official_summary, official_summary_path)

    if not updated_market_summary.empty:
        write_csv(updated_market_summary, market_summary_path)

    bubble_risk = classify_bubble_risk(updated_market_summary, data_status) if not updated_market_summary.empty else {
        "script": SCRIPT_VERSION,
        "run_at": data_status.get("run_at") or run_at.isoformat(timespec="seconds"),
        "actual_data_last_date": data_status.get("actual_data_last_date"),
        "data_status": data_status.get("status"),
        "new_confirmed_trading_day": data_status.get("new_confirmed_trading_day"),
        "risk_level": "판단불가",
        "signal_count": 0,
        "strong_signal_count": 0,
        "alert_by_signals": False,
        "alert_required": False,
        "signals": [],
        "action_hint": "market_index_summary_latest.csv가 비어 있어 위험 판단을 하지 않습니다.",
    }

    write_json(outdir / "bubble_risk_latest.json", bubble_risk)
    write_csv(pd.DataFrame(bubble_risk.get("signals", [])), outdir / "bubble_risk_signals_latest.csv")

    official_status = "OK" if not official_summary.empty else "NO_OFFICIAL_INDEX_DATA"
    log_lines.append(f"actual_data_last_date={pd.Timestamp(end_dt).date().isoformat()}")
    log_lines.append(f"official_index_status={official_status}")
    log_lines.append(f"official_index_history_rows={len(official_history)}")
    log_lines.append(f"official_index_summary_rows={len(official_summary)}")
    log_lines.append(f"updated_market_index_summary_rows={len(updated_market_summary)}")
    log_lines.append(f"bubble_risk_level={bubble_risk.get('risk_level')}")
    log_lines.append(f"bubble_signal_count={bubble_risk.get('signal_count')}")
    log_lines.append(f"bubble_alert_required={bubble_risk.get('alert_required')}")

    log_path = outdir / "official_index_run_log_latest.txt"
    ensure_dir(log_path.parent)
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
