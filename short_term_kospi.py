#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코스피 단기상승예측표 자동 산출기
v1.0_kospi_short_term

생성/갱신 파일
- latest/kospi_short_term_candidates_30_latest.csv
- latest/kospi_short_term_recommend_7_latest.csv
- latest/kospi_short_term_run_log_latest.txt

입력 파일
- latest/kospi_universe_summary_latest.csv
"""

from __future__ import annotations

import argparse
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd

SCRIPT_NAME = "short_term_kospi.py v1.0_kospi_short_term"

OUTPUT_COLUMNS = [
    "rank",
    "recommend_flag",
    "code",
    "name",
    "market",
    "asof_date",
    "close",
    "current_position",
    "buy_range",
    "sell_range",
    "avg_daily_move_text",
    "avg_wave_days",
    "stop_price",
    "low_3m",
    "high_3m",
    "range_pct",
    "position_in_3m_range_pct",
    "return_5d_pct",
    "return_1m_pct",
    "return_3m_pct",
    "avg_volume",
    "avg_trading_value",
    "liquidity_flag",
    "overheat_flag",
    "operating_loss_flag",
    "short_term_score",
    "reason",
]

EXCLUDE_NAME_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "KBSTAR", "SOL ", "ARIRANG", "HANARO",
    "KOSEF", "히어로즈", "PLUS", "ETN", "스팩", "리츠", "인버스", "선물",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_float(value: Any) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        try:
            return float(value)
        except Exception:
            return math.nan
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return math.nan
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except Exception:
        return math.nan


def safe_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"true", "1", "y", "yes", "예", "있음", "loss", "손실"}


def get_any(row: pd.Series, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if name in row.index:
            value = row.get(name)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                return value
    return default


def fmt_won(value: Any) -> str:
    number = safe_float(value)
    if math.isnan(number):
        return ""
    return f"{int(round(number)):,}원"


def build_range_text(low: Any, high: Any) -> str:
    lo = fmt_won(low)
    hi = fmt_won(high)
    if lo and hi:
        return f"{lo}~{hi}"
    return lo or hi or ""


def build_avg_daily_move_text(abs_move: Any, pct_move: Any) -> str:
    won = fmt_won(abs_move)
    pct = safe_float(pct_move)
    pct_text = "" if math.isnan(pct) else f"±{pct:.2f}%"
    if won and pct_text:
        return f"약 ±{won} 내외 ({pct_text})"
    if won:
        return f"약 ±{won} 내외"
    if pct_text:
        return f"약 {pct_text}"
    return ""


def current_position_text(position: Any) -> str:
    p = safe_float(position)
    if math.isnan(p):
        return "확인 제한"
    if p < 20:
        return "저점권"
    if p < 38:
        return "저점권 반등 초입"
    if p < 68:
        return "중간권"
    if p < 88:
        return "상단권"
    return "고점권"


def is_probably_not_common_stock(row: pd.Series) -> bool:
    name = str(get_any(row, ["name", "종목명"], "")).strip()
    if not name:
        return True

    upper = name.upper()
    if any(keyword in upper for keyword in EXCLUDE_NAME_KEYWORDS):
        return True

    # 우선주·특수주 보수적 제외
    if re.search(r"(우$|우B$|[0-9]우$|우\)$)", name):
        return True

    return False


def detect_operating_loss(row: pd.Series) -> bool:
    bool_names = [
        "operating_loss_flag",
        "op_loss_flag",
        "recent_operating_loss",
        "is_operating_loss",
    ]
    for name in bool_names:
        if name in row.index and safe_bool(row.get(name)):
            return True

    numeric_names = [
        "operating_profit",
        "op_profit",
        "recent_operating_profit",
        "quarter_operating_profit",
        "latest_operating_profit",
    ]
    for name in numeric_names:
        if name in row.index:
            value = safe_float(row.get(name))
            if not math.isnan(value) and value < 0:
                return True

    return False


def calculate_short_term_score(row: pd.Series) -> Dict[str, Any]:
    score = 100.0
    reasons: List[str] = []
    overheat_flag = False
    liquidity_flag = False

    ret_5d = safe_float(get_any(row, ["return_5d_pct", "return_1w_pct", "ret_5d_pct"]))
    ret_1m = safe_float(get_any(row, ["return_1m_pct", "ret_1m_pct"]))
    ret_3m = safe_float(get_any(row, ["return_3m_pct", "ret_3m_pct"]))
    position = safe_float(get_any(row, ["position_in_3m_range_pct", "position_pct"]))
    range_pct = safe_float(get_any(row, ["range_3m_pct", "range_pct"]))
    avg_tv = safe_float(get_any(row, ["avg20_trading_value", "avg_trading_value", "trading_value_avg20"]))
    avg_move_pct = safe_float(get_any(row, ["avg_daily_move_pct", "avg_move_pct"]))
    market_cap = safe_float(get_any(row, ["market_cap", "marketcap"]))
    low_liq = safe_bool(get_any(row, ["low_liquidity", "liquidity_flag"]))
    op_loss = detect_operating_loss(row)

    # 5거래일/1주 단기 탄력
    if not math.isnan(ret_5d):
        if 1.5 <= ret_5d <= 9:
            score += 14
            reasons.append(f"단기 탄력 양호 {ret_5d:.1f}%")
        elif 9 < ret_5d <= 16:
            score += 5
            overheat_flag = True
            reasons.append(f"단기 급등 주의 {ret_5d:.1f}%")
        elif ret_5d > 16:
            score -= 18
            overheat_flag = True
            reasons.append(f"단기 과열 {ret_5d:.1f}%")
        elif ret_5d < -6:
            score -= 8
            reasons.append(f"단기 약세 {ret_5d:.1f}%")

    # 1개월 추세
    if not math.isnan(ret_1m):
        if 3 <= ret_1m <= 18:
            score += 15
            reasons.append(f"1개월 추세 양호 {ret_1m:.1f}%")
        elif 0 <= ret_1m < 3:
            score += 5
            reasons.append(f"1개월 완만한 회복 {ret_1m:.1f}%")
        elif 18 < ret_1m <= 30:
            score -= 2
            reasons.append(f"상승 후 부담 {ret_1m:.1f}%")
        elif 30 < ret_1m <= 45:
            score -= 14
            overheat_flag = True
            reasons.append(f"1개월 과열권 {ret_1m:.1f}%")
        elif ret_1m > 45:
            score -= 25
            overheat_flag = True
            reasons.append(f"1개월 급등 과열 {ret_1m:.1f}%")
        elif ret_1m < -15:
            score -= 12
            reasons.append(f"1개월 약세 {ret_1m:.1f}%")

    # 3개월 추세
    if not math.isnan(ret_3m):
        if 0 <= ret_3m <= 35:
            score += 8
            reasons.append(f"3개월 흐름 양호 {ret_3m:.1f}%")
        elif 35 < ret_3m <= 70:
            score += 1
            reasons.append(f"3개월 상승폭 큼 {ret_3m:.1f}%")
        elif ret_3m > 70:
            score -= 12
            overheat_flag = True
            reasons.append(f"3개월 과열 {ret_3m:.1f}%")
        elif ret_3m < -20:
            score -= 10
            reasons.append(f"3개월 약세 {ret_3m:.1f}%")

    # 현재 위치
    if not math.isnan(position):
        if 38 <= position <= 72:
            score += 14
            reasons.append(f"현재 위치 중간권 {position:.1f}%")
        elif 72 < position <= 86:
            score += 6
            reasons.append(f"상단권 추세 {position:.1f}%")
        elif 22 <= position < 38:
            score += 4
            reasons.append(f"저점권 반등 초입 {position:.1f}%")
        elif position >= 92:
            score -= 18
            overheat_flag = True
            reasons.append(f"고점권 추격위험 {position:.1f}%")
        elif position < 15:
            score -= 6
            reasons.append(f"저점권 추세 미확인 {position:.1f}%")

    # 거래대금/유동성
    if low_liq or (not math.isnan(avg_tv) and avg_tv < 5_000_000_000):
        score -= 25
        liquidity_flag = True
        reasons.append("저유동성")
    elif not math.isnan(avg_tv) and avg_tv >= 100_000_000_000:
        score += 12
        reasons.append("거래대금 우수")
    elif not math.isnan(avg_tv) and avg_tv >= 30_000_000_000:
        score += 7
        reasons.append("거래대금 양호")
    elif not math.isnan(avg_tv) and avg_tv >= 10_000_000_000:
        score += 3
        reasons.append("거래대금 보통")

    # 하루 평균 변동성
    if not math.isnan(avg_move_pct):
        if 1.5 <= avg_move_pct <= 4.2:
            score += 8
            reasons.append(f"단기 변동성 적정 {avg_move_pct:.2f}%")
        elif 4.2 < avg_move_pct <= 6.5:
            score -= 3
            reasons.append(f"변동성 큼 {avg_move_pct:.2f}%")
        elif avg_move_pct > 6.5:
            score -= 12
            reasons.append(f"고변동 위험 {avg_move_pct:.2f}%")
        elif avg_move_pct < 0.8:
            score -= 5
            reasons.append(f"탄력 부족 {avg_move_pct:.2f}%")

    if not math.isnan(range_pct):
        if 18 <= range_pct <= 80:
            score += 4
            reasons.append(f"3개월 변동폭 유효 {range_pct:.1f}%")
        elif range_pct > 120:
            score -= 10
            overheat_flag = True
            reasons.append(f"3개월 변동폭 과대 {range_pct:.1f}%")

    if not math.isnan(market_cap):
        if market_cap >= 5_000_000_000_000:
            score += 4
            reasons.append("대형주 안정성")
        elif market_cap < 300_000_000_000:
            score -= 6
            reasons.append("소형주 위험")

    if op_loss:
        score -= 10
        reasons.append("최근 영업손실")

    return {
        "score": round(float(score), 2),
        "liquidity_flag": bool(liquidity_flag),
        "overheat_flag": bool(overheat_flag),
        "operating_loss_flag": bool(op_loss),
        "reason": "; ".join(reasons[:7]) if reasons else "단기 가격·거래대금·변동성 기준 중립",
    }


def row_to_output(row: pd.Series, rank: int, recommend_flag: str, scoring: Dict[str, Any]) -> Dict[str, Any]:
    code = str(get_any(row, ["ticker", "code", "종목코드"], "")).strip().zfill(6)

    return {
        "rank": rank,
        "recommend_flag": recommend_flag,
        "code": code,
        "name": get_any(row, ["name", "종목명"], ""),
        "market": get_any(row, ["market", "시장구분"], "KOSPI"),
        "asof_date": get_any(row, ["last_date", "asof_date", "date"], ""),
        "close": get_any(row, ["current_close", "close", "종가"], ""),
        "current_position": current_position_text(get_any(row, ["position_in_3m_range_pct", "position_pct"])),
        "buy_range": build_range_text(
            get_any(row, ["split_buy_low_ref", "buy_low", "buy_range_low"]),
            get_any(row, ["split_buy_high_ref", "buy_high", "buy_range_high"]),
        ),
        "sell_range": build_range_text(
            get_any(row, ["target1_ref", "sell_low", "target_low"]),
            get_any(row, ["target2_ref", "sell_high", "target_high"]),
        ),
        "avg_daily_move_text": build_avg_daily_move_text(
            get_any(row, ["avg_daily_move_abs", "avg_move_abs"]),
            get_any(row, ["avg_daily_move_pct", "avg_move_pct"]),
        ),
        "avg_wave_days": get_any(row, ["avg_wave_days", "wave_days"], ""),
        "stop_price": get_any(row, ["stop_ref", "stop_price"], ""),
        "low_3m": get_any(row, ["low_3m_intraday", "low_3m"], ""),
        "high_3m": get_any(row, ["high_3m_intraday", "high_3m"], ""),
        "range_pct": get_any(row, ["range_3m_pct", "range_pct"], ""),
        "position_in_3m_range_pct": get_any(row, ["position_in_3m_range_pct", "position_pct"], ""),
        "return_5d_pct": get_any(row, ["return_5d_pct", "return_1w_pct", "ret_5d_pct"], ""),
        "return_1m_pct": get_any(row, ["return_1m_pct", "ret_1m_pct"], ""),
        "return_3m_pct": get_any(row, ["return_3m_pct", "ret_3m_pct"], ""),
        "avg_volume": get_any(row, ["last_volume", "avg_volume", "volume"], ""),
        "avg_trading_value": get_any(row, ["avg20_trading_value", "avg_trading_value"], ""),
        "liquidity_flag": scoring["liquidity_flag"],
        "overheat_flag": scoring["overheat_flag"],
        "operating_loss_flag": scoring["operating_loss_flag"],
        "short_term_score": scoring["score"],
        "reason": scoring["reason"],
    }


def build_short_term_table(
    summary: pd.DataFrame,
    top_n: int,
    recommend_n: int,
    log_lines: List[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary is None or summary.empty:
        log_lines.append("SHORT_TERM: input summary empty")
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        return empty, empty

    df = summary.copy()

    if "market" in df.columns:
        df = df[df["market"].astype(str).str.upper().eq("KOSPI")].copy()

    log_lines.append(f"input_kospi_rows={len(df)}")

    df = df[~df.apply(is_probably_not_common_stock, axis=1)].copy()
    log_lines.append(f"after_common_stock_filter_rows={len(df)}")

    scored_rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        scoring = calculate_short_term_score(row)
        scored = row.to_dict()
        scored["_score"] = scoring["score"]
        scored["_liquidity_flag"] = scoring["liquidity_flag"]
        scored["_overheat_flag"] = scoring["overheat_flag"]
        scored["_operating_loss_flag"] = scoring["operating_loss_flag"]
        scored["_reason"] = scoring["reason"]
        scored_rows.append(scored)

    if not scored_rows:
        log_lines.append("SHORT_TERM: no scored rows")
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        return empty, empty

    scored = pd.DataFrame(scored_rows)

    for col in ["avg20_trading_value", "return_1m_pct", "position_in_3m_range_pct"]:
        if col not in scored.columns:
            scored[col] = np.nan
        scored[col + "_num"] = scored[col].apply(safe_float)

    scored = scored.sort_values(
        ["_score", "avg20_trading_value_num", "return_1m_pct_num"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    stable = scored[
        (~scored["_liquidity_flag"].astype(bool))
        & (~scored["_overheat_flag"].astype(bool))
    ].copy()

    rec_base = stable.head(recommend_n)

    if len(rec_base) < recommend_n:
        fill = scored[~scored.index.isin(rec_base.index)].head(recommend_n - len(rec_base))
        rec_base = pd.concat([rec_base, fill], ignore_index=False)

    rec_codes = set(
        rec_base.apply(
            lambda r: str(get_any(r, ["ticker", "code", "종목코드"], "")).zfill(6),
            axis=1,
        )
    )

    top_base = scored.head(top_n).copy()

    rows: List[Dict[str, Any]] = []

    for rank, (_, row) in enumerate(top_base.iterrows(), start=1):
        code = str(get_any(row, ["ticker", "code", "종목코드"], "")).zfill(6)
        is_rec = code in rec_codes
        has_warning = bool(row.get("_liquidity_flag")) or bool(row.get("_overheat_flag"))
        op_loss = bool(row.get("_operating_loss_flag"))

        if is_rec:
            flag = "✅"
        elif has_warning:
            flag = "⚠️"
        else:
            flag = "🟡"

        if has_warning:
            flag = flag + "̲"

        if op_loss:
            flag = "-" + flag

        scoring = {
            "score": row.get("_score"),
            "liquidity_flag": bool(row.get("_liquidity_flag")),
            "overheat_flag": bool(row.get("_overheat_flag")),
            "operating_loss_flag": op_loss,
            "reason": row.get("_reason", ""),
        }

        rows.append(row_to_output(row, rank, flag, scoring))

    candidates = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)

    rec_rows: List[Dict[str, Any]] = []

    rec_base = rec_base.sort_values(
        ["_score", "avg20_trading_value_num"],
        ascending=[False, False],
        na_position="last",
    ).head(recommend_n)

    for rank, (_, row) in enumerate(rec_base.iterrows(), start=1):
        has_warning = bool(row.get("_liquidity_flag")) or bool(row.get("_overheat_flag"))
        op_loss = bool(row.get("_operating_loss_flag"))

        flag = "✅"

        if has_warning:
            flag = flag + "̲"

        if op_loss:
            flag = "-" + flag

        scoring = {
            "score": row.get("_score"),
            "liquidity_flag": bool(row.get("_liquidity_flag")),
            "overheat_flag": bool(row.get("_overheat_flag")),
            "operating_loss_flag": op_loss,
            "reason": row.get("_reason", ""),
        }

        rec_rows.append(row_to_output(row, rank, flag, scoring))

    recommends = pd.DataFrame(rec_rows, columns=OUTPUT_COLUMNS)

    log_lines.append(f"short_term_candidates_rows={len(candidates)}")
    log_lines.append(f"short_term_recommend_rows={len(recommends)}")

    return candidates, recommends


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--recommend-n", type=int, default=7)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    log_lines: List[str] = [
        f"script={SCRIPT_NAME}",
        f"run_at={datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"output_dir={output_dir}",
    ]

    input_path = output_dir / "kospi_universe_summary_latest.csv"
    candidates_path = output_dir / "kospi_short_term_candidates_30_latest.csv"
    recommends_path = output_dir / "kospi_short_term_recommend_7_latest.csv"
    log_path = output_dir / "kospi_short_term_run_log_latest.txt"

    try:
        if not input_path.exists():
            raise FileNotFoundError(f"input_not_found={input_path}")

        summary = pd.read_csv(input_path, encoding="utf-8-sig")

        log_lines.append(f"input_path={input_path}")
        log_lines.append(f"input_rows={len(summary)}")
        log_lines.append(f"input_columns={','.join(map(str, summary.columns.tolist()))}")

        actual_date = ""

        if "last_date" in summary.columns and not summary.empty:
            actual_date = str(summary["last_date"].dropna().astype(str).max())
        elif "asof_date" in summary.columns and not summary.empty:
            actual_date = str(summary["asof_date"].dropna().astype(str).max())

        log_lines.append(f"short_term_actual_data_last_date={actual_date}")

        candidates, recommends = build_short_term_table(
            summary,
            args.top_n,
            args.recommend_n,
            log_lines,
        )

        candidates.to_csv(candidates_path, index=False, encoding="utf-8-sig")
        recommends.to_csv(recommends_path, index=False, encoding="utf-8-sig")

        log_lines.append(f"output_candidates={candidates_path}, rows={len(candidates)}")
        log_lines.append(f"output_recommends={recommends_path}, rows={len(recommends)}")
        log_lines.append("status=OK")

    except Exception as exc:
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        empty.to_csv(candidates_path, index=False, encoding="utf-8-sig")
        empty.to_csv(recommends_path, index=False, encoding="utf-8-sig")

        log_lines.append("status=ERROR")
        log_lines.append(f"error={type(exc).__name__}: {exc}")

        raise

    finally:
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
