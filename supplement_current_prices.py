#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
supplement_current_prices.py

보조 현재가 참고판 생성기

핵심 원칙
- 15:35, 18:10 보조판은 공식 KRX 파일을 덮어쓰지 않는다.
- supplemented 파일만 생성한다.
- 보조 현재가는 공식 확정자료가 아니라 참고용이다.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "supplement_current_prices.py v1.1_aux_only_no_overwrite"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def normalize_code(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    digits = re.sub(r"[^0-9]", "", s)
    if len(digits) == 6:
        return digits
    if 0 < len(digits) < 6:
        return digits.zfill(6)
    return None


def to_int(value: object) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("+", "").replace("원", "")
    s = re.sub(r"[^0-9\-\.]", "", s)
    if not s or s in ["-", ".", "-."]:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("+", "").replace("%", "")
    s = re.sub(r"[^0-9\-\.]", "", s)
    if not s or s in ["-", ".", "-."]:
        return None
    try:
        return float(s)
    except Exception:
        return None


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str)
    except Exception:
        return pd.DataFrame()


def find_code_col(df: pd.DataFrame) -> Optional[str]:
    for c in ["ticker", "code", "종목코드", "isuCd", "isu_cd", "symbol"]:
        if c in df.columns:
            return c
    return None


def find_name_col(df: pd.DataFrame) -> Optional[str]:
    for c in ["name", "종목", "종목명", "isuNm", "isu_nm", "stockName"]:
        if c in df.columns:
            return c
    return None


def read_codes_from_file(path: Path) -> pd.DataFrame:
    df = read_csv_safe(path)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "name", "source_file"])

    code_col = find_code_col(df)
    name_col = find_name_col(df)

    if code_col is None:
        return pd.DataFrame(columns=["ticker", "name", "source_file"])

    out = pd.DataFrame()
    out["ticker"] = df[code_col].map(normalize_code)
    out["name"] = df[name_col].astype(str) if name_col else ""
    out["source_file"] = path.name
    out = out.dropna(subset=["ticker"]).drop_duplicates(subset=["ticker"])
    return out


def collect_target_codes(output_dir: Path, source_files: List[str]) -> pd.DataFrame:
    frames = []
    for filename in source_files:
        path = output_dir / filename
        frames.append(read_codes_from_file(path))

    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "source_file"])

    merged = pd.concat(frames, ignore_index=True)
    if merged.empty:
        return pd.DataFrame(columns=["ticker", "name", "source_file"])

    merged = merged.drop_duplicates(subset=["ticker"], keep="first")
    merged = merged.sort_values(["source_file", "ticker"]).reset_index(drop=True)
    return merged


def fetch_json(url: str, timeout: float = 6.0) -> Optional[Dict[str, object]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://m.stock.naver.com/",
    }

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    try:
        data = json.loads(body)
    except Exception:
        return None

    return data if isinstance(data, dict) else None


def fetch_naver_basic(code: str) -> Dict[str, object]:
    urls = [
        f"https://m.stock.naver.com/api/stock/{code}/basic",
        f"https://api.stock.naver.com/stock/{code}/basic",
    ]

    for url in urls:
        data = fetch_json(url)
        if not data:
            continue

        price = (
            to_int(data.get("closePrice"))
            or to_int(data.get("nowVal"))
            or to_int(data.get("lastPrice"))
            or to_int(data.get("currentPrice"))
        )

        if price is None:
            continue

        return {
            "ticker": code,
            "aux_name": data.get("stockName") or data.get("itemName") or "",
            "aux_current_price": price,
            "aux_compare_to_previous_close": to_int(data.get("compareToPreviousClosePrice")),
            "aux_fluctuations_ratio": to_float(data.get("fluctuationsRatio")),
            "aux_accumulated_trading_volume": to_int(data.get("accumulatedTradingVolume")),
            "aux_accumulated_trading_value": to_int(data.get("accumulatedTradingValue")),
            "aux_market_status": data.get("marketStatus") or "",
            "aux_local_traded_at": data.get("localTradedAt") or "",
            "aux_source": "NAVER",
            "aux_fetch_status": "OK",
        }

    return {
        "ticker": code,
        "aux_name": "",
        "aux_current_price": None,
        "aux_compare_to_previous_close": None,
        "aux_fluctuations_ratio": None,
        "aux_accumulated_trading_volume": None,
        "aux_accumulated_trading_value": None,
        "aux_market_status": "",
        "aux_local_traded_at": "",
        "aux_source": "NAVER",
        "aux_fetch_status": "FAIL",
    }


def fetch_aux_prices(codes: Iterable[str], sleep_seconds: float) -> pd.DataFrame:
    rows = []
    codes_list = list(codes)

    for i, code in enumerate(codes_list, start=1):
        print(f"[AUX_PRICE] {i}/{len(codes_list)} {code}", flush=True)
        rows.append(fetch_naver_basic(code))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return pd.DataFrame(rows)


def write_supplemented_file(output_dir: Path, source_filename: str, aux_df: pd.DataFrame) -> Optional[str]:
    source_path = output_dir / source_filename
    base = read_csv_safe(source_path)

    if base.empty:
        return None

    code_col = find_code_col(base)
    if code_col is None:
        return None

    base["_merge_ticker"] = base[code_col].map(normalize_code)
    merged = base.merge(
        aux_df,
        how="left",
        left_on="_merge_ticker",
        right_on="ticker",
        suffixes=("", "_aux"),
    )

    merged = merged.drop(columns=["_merge_ticker"], errors="ignore")

    stem = source_filename.replace("_latest.csv", "").replace(".csv", "")
    out_path = output_dir / f"{stem}_supplemented_latest.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")

    return str(out_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--sleep-seconds", type=float, default=0.08)
    parser.add_argument(
        "--source-files",
        nargs="*",
        default=[
            "kospi_candidates_30_latest.csv",
            "kosdaq_candidates_10_latest.csv",
            "kospi_gainers_1m_latest.csv",
            "watchlist_summary_latest.csv",
        ],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = kst_now()
    targets = collect_target_codes(output_dir, args.source_files)

    if targets.empty:
        status = {
            "script": SCRIPT_VERSION,
            "run_at_kst": now.isoformat(timespec="seconds"),
            "status": "NO_TARGET_CODES",
            "target_count": 0,
            "ok_count": 0,
            "fail_count": 0,
            "data_type": "SUPPLEMENT_AUX_CURRENT_PRICE_NOT_OFFICIAL_KRX",
            "display_label": "보조 현재가 참고판",
            "notice": "보조 현재가이며 공식 KRX 일별매매정보를 대체하지 않습니다.",
        }

        pd.DataFrame().to_csv(
            output_dir / "supplement_current_prices_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )

        (output_dir / "supplement_current_prices_latest.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        (output_dir / "supplement_current_prices_run_log_latest.txt").write_text(
            "\n".join(f"{k}={v}" for k, v in status.items()) + "\n",
            encoding="utf-8",
        )

        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
        return 0

    aux = fetch_aux_prices(targets["ticker"].tolist(), sleep_seconds=args.sleep_seconds)
    merged = targets.merge(aux, how="left", on="ticker")

    merged["aux_run_at_kst"] = now.isoformat(timespec="seconds")
    merged["aux_data_type"] = "SUPPLEMENT_AUX_CURRENT_PRICE_NOT_OFFICIAL_KRX"
    merged["aux_display_label"] = "보조 현재가 참고판"

    merged.to_csv(
        output_dir / "supplement_current_prices_latest.csv",
        index=False,
        encoding="utf-8-sig",
    )

    supplemented_outputs = []
    for filename in args.source_files:
        out = write_supplemented_file(output_dir, filename, aux)
        if out:
            supplemented_outputs.append(out)

    ok_count = int((merged["aux_fetch_status"] == "OK").sum())
    fail_count = int((merged["aux_fetch_status"] != "OK").sum())

    status = {
        "script": SCRIPT_VERSION,
        "run_at_kst": now.isoformat(timespec="seconds"),
        "status": "OK" if ok_count > 0 else "ALL_AUX_FETCH_FAILED",
        "target_count": int(len(merged)),
        "ok_count": ok_count,
        "fail_count": fail_count,
        "data_type": "SUPPLEMENT_AUX_CURRENT_PRICE_NOT_OFFICIAL_KRX",
        "display_label": "보조 현재가 참고판",
        "source": "NAVER",
        "supplemented_outputs": supplemented_outputs,
        "notice": "보조 현재가이며 공식 KRX 일별매매정보를 대체하지 않습니다.",
    }

    (output_dir / "supplement_current_prices_latest.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log_lines = [f"{k}={v}" for k, v in status.items()]
    (output_dir / "supplement_current_prices_run_log_latest.txt").write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
