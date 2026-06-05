#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kofia_macro_bridge.py

금융투자협회 세 API 수집 CSV를 macro_leverage_status.py가 사용하는
공통 지표 형식으로 변환하여 latest/macro_leverage_history_latest.csv에 병합한다.

입력
- latest/kofia_credit_history_latest.csv
- latest/kofia_market_funds_history_latest.csv
- latest/kofia_cma_history_latest.csv

출력
- latest/kofia_macro_bridge_latest.csv
- latest/kofia_macro_bridge_status_latest.json
- latest/kofia_macro_bridge_run_log_latest.txt
- latest/macro_leverage_history_latest.csv  (기존 ECOS 자료를 보존하며 KOFIA 3개 지표만 갱신)

정규화 지표
- KOFIA_CREDIT_FINANCING_MILLION_KRW : 신용융자 전체 잔고(crdTrFingWhl)
- KOFIA_INVESTOR_DEPOSIT_MILLION_KRW : 투자자예탁금(invrDpsgAmt)
- KOFIA_CMA_BALANCE_MILLION_KRW : CMA 잔고(actBal) 일자별 합계

설계 원칙
- 기존 macro_leverage_status.py를 직접 수정하지 않는다.
- 원본 KOFIA CSV를 삭제하거나 수정하지 않는다.
- 기존 macro_leverage_history_latest.csv의 ECOS 지표는 보존한다.
- KOFIA 세 지표만 최신 수집 CSV 기준으로 교체한다.
- 값 단위가 원(KRW)으로 보이면 자동으로 백만원 단위로 변환한다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "kofia_macro_bridge.py v1.0_local_csv_bridge"
KOFIA_CODES = {
    "credit": "KOFIA_CREDIT_FINANCING_MILLION_KRW",
    "deposit": "KOFIA_INVESTOR_DEPOSIT_MILLION_KRW",
    "cma": "KOFIA_CMA_BALANCE_MILLION_KRW",
}
COMMON_COLUMNS = [
    "date",
    "indicator_code",
    "indicator_name",
    "value",
    "unit",
    "frequency",
    "source",
    "source_url",
]


def now_kst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype={"basDt": str})
        except Exception:
            continue
    return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(data: Dict, path: Path) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_date(df: pd.DataFrame) -> pd.Series:
    if "date" in df.columns:
        parsed = pd.to_datetime(df["date"], errors="coerce")
    elif "basDt" in df.columns:
        raw = df["basDt"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        parsed = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.Series(pd.NaT, index=df.index)
    return parsed.dt.strftime("%Y-%m-%d")


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.strip()
        .replace({"": None, "-": None, "nan": None, "None": None}),
        errors="coerce",
    )


def to_million_krw(series: pd.Series) -> Tuple[pd.Series, str]:
    """
    값의 중앙값이 매우 크면 원(KRW) 단위로 보고 백만원 단위로 변환한다.
    신용융자·예탁금 API는 통상 백만원 단위 값으로 내려오고,
    CMA actBal은 원 단위 값으로 내려오는 경우를 처리한다.
    """
    values = numeric(series)
    nonzero = values.dropna().abs()
    nonzero = nonzero[nonzero > 0]
    median_abs = float(nonzero.median()) if not nonzero.empty else 0.0

    if median_abs >= 1_000_000_000:
        return values / 1_000_000.0, "KRW_to_million_KRW"
    return values, "already_million_KRW"


def latest_per_date(df: pd.DataFrame, subset: List[str]) -> pd.DataFrame:
    out = df.copy()
    if "_collected_at_kst" in out.columns:
        out["_collected_at_dt"] = pd.to_datetime(out["_collected_at_kst"], errors="coerce")
        out = out.sort_values("_collected_at_dt")
    return out.drop_duplicates(subset=subset, keep="last")


def build_standard_frame(
    dates: pd.Series,
    values: pd.Series,
    code: str,
    name: str,
    source_url: str,
) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": dates,
            "indicator_code": code,
            "indicator_name": name,
            "value": values,
            "unit": "million KRW",
            "frequency": "daily",
            "source": "data.go.kr KOFIA local normalized CSV",
            "source_url": source_url,
        }
    )
    out["date_dt"] = pd.to_datetime(out["date"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["date_dt", "value"])
    out["date"] = out["date_dt"].dt.strftime("%Y-%m-%d")
    out = out.drop(columns=["date_dt"])
    out = out.drop_duplicates(subset=["date", "indicator_code"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def convert_credit(path: Path, logs: List[str]) -> pd.DataFrame:
    df = read_csv(path)
    required = {"crdTrFingWhl"}
    if df.empty or not required.issubset(df.columns):
        logs.append(f"BRIDGE_SKIP credit: missing_file_or_fields={path.as_posix()}")
        return pd.DataFrame(columns=COMMON_COLUMNS)

    df["date"] = normalize_date(df)
    df = latest_per_date(df, ["date"])
    values, unit_mode = to_million_krw(df["crdTrFingWhl"])
    out = build_standard_frame(
        df["date"],
        values,
        KOFIA_CODES["credit"],
        "신용융자 전체 잔고",
        "getGrantingOfCreditBalanceInfo",
    )
    logs.append(
        f"BRIDGE_OK credit: rows={len(out)}, latest={out['date'].max() if not out.empty else None}, unit_mode={unit_mode}"
    )
    return out


def convert_deposit(path: Path, logs: List[str]) -> pd.DataFrame:
    df = read_csv(path)
    required = {"invrDpsgAmt"}
    if df.empty or not required.issubset(df.columns):
        logs.append(f"BRIDGE_SKIP deposit: missing_file_or_fields={path.as_posix()}")
        return pd.DataFrame(columns=COMMON_COLUMNS)

    df["date"] = normalize_date(df)
    df = latest_per_date(df, ["date"])
    values, unit_mode = to_million_krw(df["invrDpsgAmt"])
    out = build_standard_frame(
        df["date"],
        values,
        KOFIA_CODES["deposit"],
        "투자자예탁금",
        "getSecuritiesMarketTotalCapitalInfo",
    )
    logs.append(
        f"BRIDGE_OK deposit: rows={len(out)}, latest={out['date'].max() if not out.empty else None}, unit_mode={unit_mode}"
    )
    return out


def convert_cma(path: Path, logs: List[str]) -> pd.DataFrame:
    df = read_csv(path)
    required = {"actBal"}
    if df.empty or not required.issubset(df.columns):
        logs.append(f"BRIDGE_SKIP cma: missing_file_or_fields={path.as_posix()}")
        return pd.DataFrame(columns=COMMON_COLUMNS)

    df["date"] = normalize_date(df)
    df["actBal_num"] = numeric(df["actBal"])

    # 동일 일자·운용대상·투자자구분이 여러 번 수집된 경우 최신 수집분만 사용한다.
    dedup_keys = ["date"]
    for col in ("mngInvTgt", "invrCtg"):
        if col in df.columns:
            dedup_keys.append(col)
    df = latest_per_date(df, dedup_keys)

    # 전체/합계 행이 세부행과 함께 존재하면 중복 합산을 막기 위해 제외한다.
    aggregate_mask = pd.Series(False, index=df.index)
    for col in ("mngInvTgt", "invrCtg"):
        if col in df.columns:
            aggregate_mask = aggregate_mask | df[col].astype(str).str.contains(
                r"전체|합계|총계|total", case=False, na=False
            )
    detailed = df[~aggregate_mask].copy()
    if detailed.empty:
        detailed = df.copy()

    grouped = detailed.groupby("date", dropna=True)["actBal_num"].sum(min_count=1).reset_index()
    values, unit_mode = to_million_krw(grouped["actBal_num"])
    out = build_standard_frame(
        grouped["date"],
        values,
        KOFIA_CODES["cma"],
        "CMA 전체 잔고",
        "getCMAStatus",
    )
    logs.append(
        f"BRIDGE_OK cma: rows={len(out)}, latest={out['date'].max() if not out.empty else None}, unit_mode={unit_mode}"
    )
    return out


def merge_macro_history(
    bridge: pd.DataFrame,
    existing_path: Path,
    lookback_days: int,
    logs: List[str],
) -> pd.DataFrame:
    existing = read_csv(existing_path)
    if existing.empty:
        existing = pd.DataFrame(columns=COMMON_COLUMNS)

    for col in COMMON_COLUMNS:
        if col not in existing.columns:
            existing[col] = None

    existing = existing[COMMON_COLUMNS].copy()
    existing["indicator_code"] = existing["indicator_code"].astype(str)

    # 기존 KOFIA 변환 행만 제거하고 ECOS 및 다른 자료는 보존한다.
    existing = existing[~existing["indicator_code"].isin(KOFIA_CODES.values())]

    combined = pd.concat([existing, bridge[COMMON_COLUMNS]], ignore_index=True)
    combined["date_dt"] = pd.to_datetime(combined["date"], errors="coerce")
    combined["value"] = pd.to_numeric(combined["value"], errors="coerce")
    combined = combined.dropna(subset=["date_dt", "indicator_code", "value"])
    combined = combined.drop_duplicates(subset=["date", "indicator_code"], keep="last")

    if not combined.empty:
        max_date = combined["date_dt"].max()
        cutoff = max_date - pd.Timedelta(days=lookback_days)
        combined = combined[combined["date_dt"] >= cutoff]

    combined["date"] = combined["date_dt"].dt.strftime("%Y-%m-%d")
    combined = combined.sort_values(["indicator_code", "date_dt"])
    combined = combined.drop(columns=["date_dt"])
    combined = combined[COMMON_COLUMNS].reset_index(drop=True)

    write_csv(combined, existing_path)
    logs.append(
        f"MACRO_HISTORY_MERGED: bridge_rows={len(bridge)}, total_rows={len(combined)}, file={existing_path.as_posix()}"
    )
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--lookback-days", type=int, default=370)
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    ensure_dir(outdir)
    run_at = now_kst()

    logs: List[str] = [
        f"script={SCRIPT_VERSION}",
        f"run_at_kst={run_at.isoformat(timespec='seconds')}",
    ]

    frames = [
        convert_credit(outdir / "kofia_credit_history_latest.csv", logs),
        convert_deposit(outdir / "kofia_market_funds_history_latest.csv", logs),
        convert_cma(outdir / "kofia_cma_history_latest.csv", logs),
    ]
    usable = [df for df in frames if not df.empty]
    bridge = pd.concat(usable, ignore_index=True) if usable else pd.DataFrame(columns=COMMON_COLUMNS)

    bridge_path = outdir / "kofia_macro_bridge_latest.csv"
    write_csv(bridge, bridge_path)

    macro_path = outdir / "macro_leverage_history_latest.csv"
    merged = merge_macro_history(bridge, macro_path, args.lookback_days, logs)

    codes = sorted(bridge["indicator_code"].unique().tolist()) if not bridge.empty else []
    latest_dates = {}
    if not bridge.empty:
        for code, group in bridge.groupby("indicator_code"):
            latest_dates[str(code)] = str(group["date"].max())

    if len(codes) == 3:
        overall_status = "OK_ALL_3"
    elif len(codes) > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "NO_KOFIA_DATA"

    status = {
        "script": SCRIPT_VERSION,
        "run_at_kst": run_at.isoformat(timespec="seconds"),
        "overall_status": overall_status,
        "bridge_indicator_count": len(codes),
        "bridge_indicator_codes": codes,
        "latest_dates": latest_dates,
        "bridge_rows": int(len(bridge)),
        "macro_history_rows_after_merge": int(len(merged)),
        "next_step": "Run macro_leverage_status.py after this bridge so bubble_risk_latest.json receives the KOFIA snapshot.",
    }
    write_json(status, outdir / "kofia_macro_bridge_status_latest.json")

    logs.extend(
        [
            f"overall_status={overall_status}",
            f"bridge_indicator_count={len(codes)}",
            f"bridge_indicator_codes={','.join(codes)}",
            f"bridge_rows={len(bridge)}",
            f"macro_history_rows_after_merge={len(merged)}",
        ]
    )
    log_path = outdir / "kofia_macro_bridge_run_log_latest.txt"
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")
    print("\n".join(logs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
