#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
apply_current_price_basis.py

현재가 기준 보정 파일 생성기

핵심 원칙
- 공식 KRX 산출 파일은 절대 덮어쓰지 않는다.
- 보조 현재가를 이용해 별도 current_basis 파일만 만든다.
- 사용자에게 보여줄 표는 열을 늘리지 않는다.
- 현재가 기준 칸, 즉 close/current_close 값 오른쪽에 아이콘만 붙인다.

예:
  101,200 -> 101,900 🟦
  248,500 -> 255,000 🟠
  82,000  -> 86,000 🔴

생성 파일
- latest/kospi_candidates_30_current_basis_latest.csv
- latest/kosdaq_candidates_10_current_basis_latest.csv
- latest/kospi_gainers_1m_current_basis_latest.csv
- latest/watchlist_summary_current_basis_latest.csv
- latest/current_price_basis_run_log_latest.txt
- latest/current_price_basis_latest.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "apply_current_price_basis.py v1.1_current_close_support"

DEFAULT_SOURCE_FILES = [
    "kospi_candidates_30_latest.csv",
    "kosdaq_candidates_10_latest.csv",
    "kospi_gainers_1m_latest.csv",
    "watchlist_summary_latest.csv",
]


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


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


def normalize_code(value: object) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None

    digits = re.sub(r"[^0-9]", "", text)

    if len(digits) == 6:
        return digits

    if 0 < len(digits) < 6:
        return digits.zfill(6)

    return None


def parse_number(value: object) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None

    text = (
        text.replace(",", "")
        .replace("원", "")
        .replace("+", "")
        .replace("%", "")
        .strip()
    )

    # 기존에 아이콘이 붙어 있어도 숫자만 뽑는다.
    text = re.sub(r"[^0-9.\-]", "", text)

    if text in {"", "-", ".", "-."}:
        return None

    try:
        number = float(text)
    except Exception:
        return None

    if math.isnan(number):
        return None

    return number


def format_price(value: Optional[float]) -> str:
    if value is None:
        return ""

    try:
        return f"{int(round(float(value))):,}"
    except Exception:
        return ""


def find_code_col(df: pd.DataFrame) -> Optional[str]:
    for col in [
        "ticker",
        "code",
        "종목코드",
        "단축코드",
        "isuCd",
        "isu_cd",
        "symbol",
    ]:
        if col in df.columns:
            return col
    return None


def find_price_col(df: pd.DataFrame) -> Optional[str]:
    """
    현재가 열 탐색.

    코피표/코닥표/급등표 계열은 close를 쓰고,
    관종표 watchlist_summary_latest.csv는 current_close를 쓴다.
    """
    for col in [
        "close",
        "current_close",
        "current_price",
        "price",
        "현재가",
        "현재가 기준",
    ]:
        if col in df.columns:
            return col
    return None


def find_low_high_cols(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    low_col = None
    high_col = None

    for col in [
        "low_3m",
        "recent_3m_low",
        "range_low_3m",
        "저점_3m",
        "최근3개월저점",
    ]:
        if col in df.columns:
            low_col = col
            break

    for col in [
        "high_3m",
        "recent_3m_high",
        "range_high_3m",
        "고점_3m",
        "최근3개월고점",
    ]:
        if col in df.columns:
            high_col = col
            break

    return low_col, high_col


def find_position_col(df: pd.DataFrame) -> Optional[str]:
    for col in [
        "position_in_3m_range_pct",
        "current_position",
        "현재 위치",
        "position_pct",
    ]:
        if col in df.columns:
            return col
    return None


def find_reason_col(df: pd.DataFrame) -> Optional[str]:
    for col in [
        "reason",
        "note",
        "comment",
        "추천·주의사유",
        "주의사유",
        "추천사유",
    ]:
        if col in df.columns:
            return col
    return None


def load_aux_prices(output_dir: Path) -> Dict[str, Dict[str, object]]:
    aux_path = output_dir / "supplement_current_prices_latest.csv"
    aux = read_csv_safe(aux_path)

    if aux.empty:
        return {}

    code_col = find_code_col(aux)
    if code_col is None:
        return {}

    price_col = None
    for col in ["aux_current_price", "current_price", "close", "current_close"]:
        if col in aux.columns:
            price_col = col
            break

    if price_col is None:
        return {}

    status_col = "aux_fetch_status" if "aux_fetch_status" in aux.columns else None
    traded_col = "aux_local_traded_at" if "aux_local_traded_at" in aux.columns else None
    run_col = "aux_run_at_kst" if "aux_run_at_kst" in aux.columns else None

    result: Dict[str, Dict[str, object]] = {}

    for _, row in aux.iterrows():
        code = normalize_code(row.get(code_col, ""))
        if not code:
            continue

        price = parse_number(row.get(price_col, ""))
        status = str(row.get(status_col, "")) if status_col else ""
        traded_at = str(row.get(traded_col, "")) if traded_col else ""
        run_at = str(row.get(run_col, "")) if run_col else ""

        result[code] = {
            "aux_current_price": price,
            "aux_fetch_status": status or ("OK" if price is not None else "FAIL"),
            "aux_local_traded_at": traded_at,
            "aux_run_at_kst": run_at,
        }

    return result


def marker_for_gap(gap_pct: Optional[float], aux_ok: bool) -> str:
    if not aux_ok or gap_pct is None:
        return "⚪"

    abs_gap = abs(gap_pct)

    if abs_gap < 0.5:
        return ""

    if abs_gap < 1.5:
        return "🟦"

    if abs_gap < 3.0:
        return "🟠"

    return "🔴"


def calc_position_pct(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    if price is None or low is None or high is None:
        return None

    if high <= low:
        return None

    pct = (price - low) / (high - low) * 100.0
    return max(0.0, min(100.0, pct))


def compact_position_text(pct: Optional[float]) -> str:
    if pct is None:
        return ""

    if pct < 20:
        zone = "저점권"
    elif pct < 40:
        zone = "저점권 반등"
    elif pct < 60:
        zone = "중간권"
    elif pct < 80:
        zone = "상단권"
    else:
        zone = "고점권"

    return f"{zone} {pct:.1f}%"


def append_reason_note(reason: str, marker: str, gap_pct: Optional[float]) -> str:
    if marker == "":
        return reason

    if marker == "🟦":
        note = "현재가 보정 적용"
    elif marker == "🟠":
        note = "현재가 변동 큼"
    elif marker == "🔴":
        note = "현재가 급변, 매수·익절 판단 재점검"
    elif marker == "⚪":
        note = "보조 현재가 확인 실패"
    else:
        note = ""

    if gap_pct is not None and marker in {"🟦", "🟠", "🔴"}:
        note = f"{note}({gap_pct:+.2f}%)"

    if not note:
        return reason

    # 같은 문구가 누적되지 않게 기존 보정 문구 제거
    cleaned = str(reason)
    cleaned = re.sub(r";?\s*현재가 보정 적용\([^)]+\)", "", cleaned)
    cleaned = re.sub(r";?\s*현재가 변동 큼\([^)]+\)", "", cleaned)
    cleaned = re.sub(r";?\s*현재가 급변, 매수·익절 판단 재점검\([^)]+\)", "", cleaned)
    cleaned = re.sub(r";?\s*보조 현재가 확인 실패", "", cleaned)
    cleaned = cleaned.strip(" ;")

    if not cleaned:
        return note

    return f"{cleaned}; {note}"


def output_filename(source_filename: str) -> str:
    if source_filename.endswith("_latest.csv"):
        return source_filename.replace("_latest.csv", "_current_basis_latest.csv")
    if source_filename.endswith(".csv"):
        return source_filename.replace(".csv", "_current_basis_latest.csv")
    return source_filename + "_current_basis_latest.csv"


def apply_to_file(
    output_dir: Path,
    source_filename: str,
    aux_map: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    source_path = output_dir / source_filename
    df = read_csv_safe(source_path)

    result = {
        "source_file": source_filename,
        "output_file": output_filename(source_filename),
        "status": "UNKNOWN",
        "rows": 0,
        "matched": 0,
        "marked_blue": 0,
        "marked_orange": 0,
        "marked_red": 0,
        "marked_fail": 0,
        "changed_price_cells": 0,
        "price_column": "",
    }

    if df.empty:
        result["status"] = "EMPTY_OR_MISSING"
        return result

    code_col = find_code_col(df)
    price_col = find_price_col(df)

    if code_col is None:
        result["status"] = "NO_CODE_COLUMN"
        return result

    if price_col is None:
        result["status"] = "NO_PRICE_COLUMN"
        return result

    result["price_column"] = price_col

    low_col, high_col = find_low_high_cols(df)
    position_col = find_position_col(df)
    reason_col = find_reason_col(df)

    out = df.copy()
    rows = len(out)
    matched = 0
    changed_price_cells = 0
    marked_blue = 0
    marked_orange = 0
    marked_red = 0
    marked_fail = 0

    for idx, row in out.iterrows():
        code = normalize_code(row.get(code_col, ""))
        official_price = parse_number(row.get(price_col, ""))

        if not code or official_price is None:
            continue

        aux_info = aux_map.get(code)
        aux_price = None
        aux_ok = False

        if aux_info:
            aux_price = aux_info.get("aux_current_price")
            aux_ok = (
                aux_price is not None
                and str(aux_info.get("aux_fetch_status", "")).upper() == "OK"
            )

        effective_price = official_price
        gap_pct = None

        if aux_ok and aux_price is not None:
            matched += 1
            effective_price = float(aux_price)
            if official_price:
                gap_pct = (effective_price - official_price) / official_price * 100.0

        marker = marker_for_gap(gap_pct, aux_ok=aux_ok)

        if marker == "🟦":
            marked_blue += 1
        elif marker == "🟠":
            marked_orange += 1
        elif marker == "🔴":
            marked_red += 1
        elif marker == "⚪":
            marked_fail += 1

        price_text = format_price(effective_price)
        if marker:
            price_text = f"{price_text} {marker}"

        out.at[idx, price_col] = price_text

        if effective_price != official_price or marker:
            changed_price_cells += 1

        # 현재 위치 열이 있으면, 열을 늘리지 않고 기존 위치 값만 현재가 기준으로 보정
        if low_col and high_col and position_col:
            low = parse_number(row.get(low_col, ""))
            high = parse_number(row.get(high_col, ""))
            pos_pct = calc_position_pct(effective_price, low, high)

            if pos_pct is not None:
                if position_col == "position_in_3m_range_pct":
                    out.at[idx, position_col] = f"{pos_pct:.2f}"
                else:
                    out.at[idx, position_col] = compact_position_text(pos_pct)

        # 사유 열이 있으면 짧은 보정 문구만 뒤에 붙임
        if reason_col:
            out.at[idx, reason_col] = append_reason_note(
                str(row.get(reason_col, "")),
                marker,
                gap_pct,
            )

    out_path = output_dir / output_filename(source_filename)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    result.update(
        {
            "status": "OK",
            "rows": rows,
            "matched": matched,
            "marked_blue": marked_blue,
            "marked_orange": marked_orange,
            "marked_red": marked_red,
            "marked_fail": marked_fail,
            "changed_price_cells": changed_price_cells,
        }
    )

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--source-files", nargs="*", default=DEFAULT_SOURCE_FILES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_at = kst_now().isoformat(timespec="seconds")
    aux_map = load_aux_prices(output_dir)

    results: List[Dict[str, object]] = []
    for source_file in args.source_files:
        results.append(apply_to_file(output_dir, source_file, aux_map))

    ok_files = sum(1 for r in results if r.get("status") == "OK")
    total_blue = sum(int(r.get("marked_blue", 0)) for r in results)
    total_orange = sum(int(r.get("marked_orange", 0)) for r in results)
    total_red = sum(int(r.get("marked_red", 0)) for r in results)
    total_fail = sum(int(r.get("marked_fail", 0)) for r in results)

    status = {
        "script": SCRIPT_VERSION,
        "run_at_kst": run_at,
        "output_dir": str(output_dir),
        "source_files": args.source_files,
        "aux_price_count": len(aux_map),
        "ok_files": ok_files,
        "results": results,
        "display_rule": "기존 열 구조 유지. 현재가 기준 칸 오른쪽에 아이콘만 표시.",
        "marker_rule": {
            "none": "±0.5% 미만",
            "🟦": "±0.5% 이상 ~ ±1.5% 미만",
            "🟠": "±1.5% 이상 ~ ±3% 미만",
            "🔴": "±3% 이상",
            "⚪": "보조 현재가 확인 실패",
        },
        "summary": {
            "blue": total_blue,
            "orange": total_orange,
            "red": total_red,
            "fail": total_fail,
        },
        "status": "OK" if ok_files > 0 else "NO_OUTPUT",
    }

    json_path = output_dir / "current_price_basis_latest.json"
    txt_path = output_dir / "current_price_basis_run_log_latest.txt"

    json_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"script={SCRIPT_VERSION}",
        f"run_at_kst={run_at}",
        f"output_dir={output_dir}",
        f"aux_price_count={len(aux_map)}",
        f"ok_files={ok_files}",
        f"status={status['status']}",
        "display_rule=기존 열 구조 유지. 현재가 기준 칸 오른쪽에 아이콘만 표시.",
        "marker_none=±0.5% 미만",
        "marker_blue=🟦 ±0.5% 이상 ~ ±1.5% 미만",
        "marker_orange=🟠 ±1.5% 이상 ~ ±3% 미만",
        "marker_red=🔴 ±3% 이상",
        "marker_fail=⚪ 보조 현재가 확인 실패",
    ]

    for r in results:
        lines.append(
            "CURRENT_BASIS_FILE "
            f"{r.get('source_file')}: "
            f"status={r.get('status')}, "
            f"output={r.get('output_file')}, "
            f"rows={r.get('rows')}, "
            f"matched={r.get('matched')}, "
            f"blue={r.get('marked_blue')}, "
            f"orange={r.get('marked_orange')}, "
            f"red={r.get('marked_red')}, "
            f"fail={r.get('marked_fail')}, "
            f"changed_price_cells={r.get('changed_price_cells')}, "
            f"price_column={r.get('price_column')}"
        )

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
