#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
코스피 환율약세표 자동 산출기
v1.0_kospi_currency_weakness

생성/갱신 파일
- latest/kospi_fx_weakness_candidates_30_latest.csv
- latest/kospi_fx_weakness_recommend_7_latest.csv
- latest/kospi_fx_weakness_run_log_latest.txt

입력 파일
- latest/kospi_universe_summary_latest.csv

주의
- 이 스크립트는 기업별 환헤지비율, 달러매출 비중, 외화부채 재무주석을 직접 추출하지 않는다.
- 현재 자동수집 원자료에 있는 가격·거래대금·시총·위치 자료와 종목명 기반 업종 프록시로 원화 약세 수혜 가능성을 점수화한다.
"""

from __future__ import annotations

import argparse
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

SCRIPT_NAME = "currency_weakness_kospi.py v1.0_kospi_currency_weakness"

OUTPUT_COLUMNS = [
    "rank",
    "recommend_flag",
    "code",
    "name",
    "market",
    "asof_date",
    "close",
    "buy_range",
    "sell_range",
    "avg_daily_move_text",
    "avg_wave_days",
    "stop_price",
    "current_position",
    "low_3m",
    "high_3m",
    "range_pct",
    "position_in_3m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "avg_trading_value",
    "market_cap",
    "fx_benefit_structure",
    "fx_proxy_score",
    "import_cost_risk",
    "liquidity_flag",
    "overheat_flag",
    "operating_loss_flag",
    "final_score",
    "reason",
]

EXCLUDE_NAME_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "KBSTAR", "SOL ", "ARIRANG", "HANARO",
    "KOSEF", "히어로즈", "PLUS", "ETN", "스팩", "리츠", "인버스", "선물",
]

# 원화 약세 수혜 가능성이 상대적으로 큰 업종/종목명 프록시
FX_BENEFIT_RULES: List[Tuple[str, int, str]] = [
    ("하이닉스", 30, "반도체 수출·달러매출 수혜"),
    ("삼성전자", 28, "반도체·IT 수출 수혜"),
    ("반도체", 24, "반도체 수출 수혜"),
    ("한미반도체", 24, "반도체 장비 수출 수혜"),
    ("이수페타시스", 22, "AI·PCB 수출 수혜"),
    ("삼성전기", 20, "전자부품 수출 수혜"),
    ("LG이노텍", 20, "전자부품 수출 수혜"),
    ("전기", 14, "전자부품·전장 수출 노출"),
    ("전자", 14, "IT·전자 수출 노출"),
    ("디스플레이", 14, "디스플레이 수출 노출"),

    ("현대차", 28, "자동차 수출·달러매출 수혜"),
    ("기아", 28, "자동차 수출·달러매출 수혜"),
    ("현대모비스", 22, "자동차 부품 수출 수혜"),
    ("오토에버", 14, "자동차 그룹 전장·SW 노출"),
    ("자동차", 22, "자동차 수출 수혜"),
    ("타이어", 18, "타이어 수출 수혜"),

    ("HD현대중공업", 28, "조선 달러수주 수혜"),
    ("HD한국조선해양", 28, "조선 달러수주 수혜"),
    ("한화오션", 28, "조선 달러수주 수혜"),
    ("삼성중공업", 28, "조선 달러수주 수혜"),
    ("조선", 26, "조선 달러수주 수혜"),
    ("중공업", 20, "중공업·수출 수혜"),
    ("오션", 20, "조선·해양 달러수주 수혜"),
    ("엔진", 16, "선박·기계 수출 수혜"),

    ("한화에어로스페이스", 26, "방산·항공 수출 수혜"),
    ("현대로템", 24, "방산·철도 수출 수혜"),
    ("LIG넥스원", 24, "방산 수출 수혜"),
    ("에어로스페이스", 24, "방산·항공 수출 수혜"),
    ("로템", 22, "방산·철도 수출 수혜"),
    ("넥스원", 22, "방산 수출 수혜"),
    ("방산", 22, "방산 수출 수혜"),

    ("LG에너지솔루션", 20, "2차전지 해외매출 노출"),
    ("삼성SDI", 20, "2차전지 해외매출 노출"),
    ("포스코퓨처엠", 16, "2차전지 소재 해외매출 노출"),
    ("2차전지", 16, "2차전지 해외매출 노출"),
    ("배터리", 16, "배터리 해외매출 노출"),
    ("소재", 10, "소재 수출 노출"),

    ("화학", 12, "화학제품 수출 노출"),
    ("정유", 10, "정유·석유화학 달러매출 노출"),
    ("철강", 10, "철강 수출 노출"),
    ("스틸", 10, "철강 수출 노출"),
    ("제강", 10, "철강 수출 노출"),
    ("HMM", 10, "해운 달러매출 노출"),
]

# 원화 약세 시 원가·부채 부담 가능성이 큰 업종/종목명 프록시
IMPORT_COST_RISK_RULES: List[Tuple[str, int, str]] = [
    ("대한항공", 24, "항공유·달러비용 부담"),
    ("아시아나", 24, "항공유·달러비용 부담"),
    ("항공", 20, "항공유·달러비용 부담"),
    ("한국전력", 24, "에너지 수입원가 부담"),
    ("전력", 18, "에너지 수입원가 부담"),
    ("가스", 18, "LNG 수입원가 부담"),
    ("지역난방", 16, "에너지 수입원가 부담"),
    ("식품", 12, "곡물·원재료 수입원가 부담"),
    ("제당", 12, "원재료 수입원가 부담"),
    ("오뚜기", 10, "원재료 수입원가 부담"),
    ("농심", 10, "원재료 수입원가 부담"),
    ("CJ제일제당", 10, "원재료 수입원가 부담"),
    ("이마트", 10, "소비·수입원가 부담"),
    ("롯데쇼핑", 10, "소비·수입원가 부담"),
    ("호텔", 8, "소비·여행 수요 민감"),
    ("면세", 8, "소비·여행 수요 민감"),
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


def clean_code(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"[^0-9]", "", text)
    return text.zfill(6) if text else ""


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


def match_rules(name: str, rules: List[Tuple[str, int, str]]) -> Tuple[int, List[str]]:
    total = 0
    labels: List[str] = []
    upper_name = name.upper()

    for keyword, score, label in rules:
        if keyword.upper() in upper_name or keyword in name:
            total += score
            if label not in labels:
                labels.append(label)

    return total, labels


def calculate_fx_score(row: pd.Series) -> Dict[str, Any]:
    name = str(get_any(row, ["name", "종목명"], "")).strip()

    benefit_score, benefit_labels = match_rules(name, FX_BENEFIT_RULES)
    risk_score, risk_labels = match_rules(name, IMPORT_COST_RISK_RULES)

    ret_1m = safe_float(get_any(row, ["return_1m_pct", "ret_1m_pct"]))
    ret_3m = safe_float(get_any(row, ["return_3m_pct", "ret_3m_pct"]))
    position = safe_float(get_any(row, ["position_in_3m_range_pct", "position_pct"]))
    range_pct = safe_float(get_any(row, ["range_3m_pct", "range_pct"]))
    avg_tv = safe_float(get_any(row, ["avg20_trading_value", "avg_trading_value"]))
    avg_move_pct = safe_float(get_any(row, ["avg_daily_move_pct", "avg_move_pct"]))
    market_cap = safe_float(get_any(row, ["market_cap", "marketcap"]))
    low_liq = safe_bool(get_any(row, ["low_liquidity", "liquidity_flag"]))
    op_loss = detect_operating_loss(row)

    score = 50.0
    reasons: List[str] = []

    fx_proxy_score = benefit_score - risk_score
    score += fx_proxy_score

    if benefit_labels:
        reasons.append(" / ".join(benefit_labels[:2]))
    if risk_labels:
        reasons.append("수입원가·달러비용 부담: " + " / ".join(risk_labels[:2]))

    if benefit_score <= 0:
        score -= 12
        reasons.append("환율수혜 구조 확인 제한")

    if risk_score >= 18:
        score -= 16
    elif risk_score >= 10:
        score -= 8

    overheat_flag = False
    liquidity_flag = False

    if not math.isnan(ret_1m):
        if 2 <= ret_1m <= 18:
            score += 12
            reasons.append(f"1개월 흐름 양호 {ret_1m:.1f}%")
        elif 18 < ret_1m <= 35:
            score += 2
            reasons.append(f"상승폭 부담 {ret_1m:.1f}%")
        elif ret_1m > 35:
            score -= 14
            overheat_flag = True
            reasons.append(f"1개월 과열 {ret_1m:.1f}%")
        elif ret_1m < -15:
            score -= 9
            reasons.append(f"1개월 약세 {ret_1m:.1f}%")

    if not math.isnan(ret_3m):
        if 0 <= ret_3m <= 45:
            score += 7
            reasons.append(f"3개월 추세 양호 {ret_3m:.1f}%")
        elif 45 < ret_3m <= 80:
            score -= 2
            reasons.append(f"3개월 상승부담 {ret_3m:.1f}%")
        elif ret_3m > 80:
            score -= 12
            overheat_flag = True
            reasons.append(f"3개월 과열 {ret_3m:.1f}%")
        elif ret_3m < -25:
            score -= 8
            reasons.append(f"3개월 약세 {ret_3m:.1f}%")

    if not math.isnan(position):
        if 25 <= position <= 72:
            score += 10
            reasons.append(f"현재 위치 양호 {position:.1f}%")
        elif 72 < position <= 88:
            score += 3
            reasons.append(f"상단권 추세 {position:.1f}%")
        elif position >= 92:
            score -= 15
            overheat_flag = True
            reasons.append(f"고점권 추격위험 {position:.1f}%")
        elif position < 15:
            score -= 5
            reasons.append(f"저점권 추세확인 필요 {position:.1f}%")

    if low_liq or (not math.isnan(avg_tv) and avg_tv < 5_000_000_000):
        score -= 25
        liquidity_flag = True
        reasons.append("저유동성")
    elif not math.isnan(avg_tv) and avg_tv >= 100_000_000_000:
        score += 10
        reasons.append("거래대금 우수")
    elif not math.isnan(avg_tv) and avg_tv >= 30_000_000_000:
        score += 6
        reasons.append("거래대금 양호")
    elif not math.isnan(avg_tv) and avg_tv >= 10_000_000_000:
        score += 3
        reasons.append("거래대금 보통")

    if not math.isnan(avg_move_pct):
        if 1.2 <= avg_move_pct <= 4.8:
            score += 6
            reasons.append(f"변동성 적정 {avg_move_pct:.2f}%")
        elif 4.8 < avg_move_pct <= 7:
            score -= 3
            reasons.append(f"변동성 큼 {avg_move_pct:.2f}%")
        elif avg_move_pct > 7:
            score -= 10
            overheat_flag = True
            reasons.append(f"고변동 위험 {avg_move_pct:.2f}%")

    if not math.isnan(range_pct):
        if 15 <= range_pct <= 90:
            score += 3
        elif range_pct > 130:
            score -= 8
            overheat_flag = True
            reasons.append(f"3개월 변동폭 과대 {range_pct:.1f}%")

    if not math.isnan(market_cap):
        if market_cap >= 5_000_000_000_000:
            score += 4
            reasons.append("대형주 안정성")
        elif market_cap < 300_000_000_000:
            score -= 5
            reasons.append("소형주 위험")

    if op_loss:
        score -= 10
        reasons.append("최근 영업손실")

    if benefit_labels:
        fx_structure = " / ".join(benefit_labels[:3])
    elif risk_labels:
        fx_structure = "원화 약세 부담 가능: " + " / ".join(risk_labels[:2])
    else:
        fx_structure = "환율수혜 구조 확인 제한"

    if risk_labels:
        import_cost_risk = " / ".join(risk_labels[:3])
    else:
        import_cost_risk = "낮음 또는 확인 제한"

    return {
        "score": round(float(score), 2),
        "fx_proxy_score": fx_proxy_score,
        "fx_structure": fx_structure,
        "import_cost_risk": import_cost_risk,
        "liquidity_flag": bool(liquidity_flag),
        "overheat_flag": bool(overheat_flag),
        "operating_loss_flag": bool(op_loss),
        "reason": "; ".join(reasons[:8]) if reasons else "환율수혜·가격흐름 기준 중립",
    }


def row_to_output(row: pd.Series, rank: int, recommend_flag: str, scoring: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rank": rank,
        "recommend_flag": recommend_flag,
        "code": clean_code(get_any(row, ["ticker", "code", "종목코드"], "")),
        "name": get_any(row, ["name", "종목명"], ""),
        "market": get_any(row, ["market", "시장구분"], "KOSPI"),
        "asof_date": get_any(row, ["last_date", "asof_date", "date"], ""),
        "close": get_any(row, ["current_close", "close", "종가"], ""),
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
        "current_position": current_position_text(get_any(row, ["position_in_3m_range_pct", "position_pct"])),
        "low_3m": get_any(row, ["low_3m_intraday", "low_3m"], ""),
        "high_3m": get_any(row, ["high_3m_intraday", "high_3m"], ""),
        "range_pct": get_any(row, ["range_3m_pct", "range_pct"], ""),
        "position_in_3m_range_pct": get_any(row, ["position_in_3m_range_pct", "position_pct"], ""),
        "return_1m_pct": get_any(row, ["return_1m_pct", "ret_1m_pct"], ""),
        "return_3m_pct": get_any(row, ["return_3m_pct", "ret_3m_pct"], ""),
        "avg_trading_value": get_any(row, ["avg20_trading_value", "avg_trading_value"], ""),
        "market_cap": get_any(row, ["market_cap", "marketcap"], ""),
        "fx_benefit_structure": scoring["fx_structure"],
        "fx_proxy_score": scoring["fx_proxy_score"],
        "import_cost_risk": scoring["import_cost_risk"],
        "liquidity_flag": scoring["liquidity_flag"],
        "overheat_flag": scoring["overheat_flag"],
        "operating_loss_flag": scoring["operating_loss_flag"],
        "final_score": scoring["score"],
        "reason": scoring["reason"],
    }


def build_fx_weakness_table(
    summary: pd.DataFrame,
    top_n: int,
    recommend_n: int,
    log_lines: List[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary is None or summary.empty:
        log_lines.append("FX_WEAKNESS: input summary empty")
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
        scoring = calculate_fx_score(row)
        scored = row.to_dict()
        scored["_score"] = scoring["score"]
        scored["_fx_proxy_score"] = scoring["fx_proxy_score"]
        scored["_fx_structure"] = scoring["fx_structure"]
        scored["_import_cost_risk"] = scoring["import_cost_risk"]
        scored["_liquidity_flag"] = scoring["liquidity_flag"]
        scored["_overheat_flag"] = scoring["overheat_flag"]
        scored["_operating_loss_flag"] = scoring["operating_loss_flag"]
        scored["_reason"] = scoring["reason"]
        scored_rows.append(scored)

    if not scored_rows:
        log_lines.append("FX_WEAKNESS: no scored rows")
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        return empty, empty

    scored = pd.DataFrame(scored_rows)

    for col in ["avg20_trading_value", "return_1m_pct", "position_in_3m_range_pct"]:
        if col not in scored.columns:
            scored[col] = np.nan
        scored[col + "_num"] = scored[col].apply(safe_float)

    scored = scored.sort_values(
        ["_score", "_fx_proxy_score", "avg20_trading_value_num", "return_1m_pct_num"],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    rec_base = scored[
        (scored["_fx_proxy_score"] > 0)
        & (~scored["_liquidity_flag"].astype(bool))
        & (~scored["_overheat_flag"].astype(bool))
    ].copy().head(recommend_n)

    if len(rec_base) < recommend_n:
        fill = scored[~scored.index.isin(rec_base.index)].head(recommend_n - len(rec_base))
        rec_base = pd.concat([rec_base, fill], ignore_index=False)

    rec_codes = set(
        rec_base.apply(
            lambda r: clean_code(get_any(r, ["ticker", "code", "종목코드"], "")),
            axis=1,
        )
    )

    top_base = scored.head(top_n).copy()

    rows: List[Dict[str, Any]] = []

    for rank, (_, row) in enumerate(top_base.iterrows(), start=1):
        code = clean_code(get_any(row, ["ticker", "code", "종목코드"], ""))
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
            "fx_proxy_score": row.get("_fx_proxy_score"),
            "fx_structure": row.get("_fx_structure", ""),
            "import_cost_risk": row.get("_import_cost_risk", ""),
            "liquidity_flag": bool(row.get("_liquidity_flag")),
            "overheat_flag": bool(row.get("_overheat_flag")),
            "operating_loss_flag": op_loss,
            "reason": row.get("_reason", ""),
        }

        rows.append(row_to_output(row, rank, flag, scoring))

    candidates = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)

    rec_base = rec_base.sort_values(
        ["_score", "_fx_proxy_score", "avg20_trading_value_num"],
        ascending=[False, False, False],
        na_position="last",
    ).head(recommend_n)

    rec_rows: List[Dict[str, Any]] = []

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
            "fx_proxy_score": row.get("_fx_proxy_score"),
            "fx_structure": row.get("_fx_structure", ""),
            "import_cost_risk": row.get("_import_cost_risk", ""),
            "liquidity_flag": bool(row.get("_liquidity_flag")),
            "overheat_flag": bool(row.get("_overheat_flag")),
            "operating_loss_flag": op_loss,
            "reason": row.get("_reason", ""),
        }

        rec_rows.append(row_to_output(row, rank, flag, scoring))

    recommends = pd.DataFrame(rec_rows, columns=OUTPUT_COLUMNS)

    log_lines.append(f"fx_weakness_candidates_rows={len(candidates)}")
    log_lines.append(f"fx_weakness_recommend_rows={len(recommends)}")

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
        "method=sector_name_proxy_plus_price_liquidity_position",
        "note=환헤지비율/달러매출비중/외화부채 재무주석 직접 추출은 아님",
    ]

    input_path = output_dir / "kospi_universe_summary_latest.csv"
    candidates_path = output_dir / "kospi_fx_weakness_candidates_30_latest.csv"
    recommends_path = output_dir / "kospi_fx_weakness_recommend_7_latest.csv"
    log_path = output_dir / "kospi_fx_weakness_run_log_latest.txt"

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

        log_lines.append(f"fx_weakness_actual_data_last_date={actual_date}")

        candidates, recommends = build_fx_weakness_table(
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
