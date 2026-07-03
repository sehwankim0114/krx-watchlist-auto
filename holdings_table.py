#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
holdings_table.py v1.0.0

사용자 보유내역과 KOSPI/KOSDAQ 최신 요약자료를 결합하여
최신 개선형 보유종목표를 생성한다.

기본 입력
- input/holdings_input.csv
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv

출력
- latest/holdings_latest.csv
- latest/holdings_status_latest.json
- latest/holdings_run_log_latest.txt

보안 주의
- 보유수량·평균매수가는 개인 금융정보다.
- 공개 저장소에 입력·출력 파일을 올리면 누구나 볼 수 있다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "holdings_table.py v1.0.0-separate-cash-credit-lots"
POLICY_VERSION = "2026-07-03-v6.0-holdings-table"
KST = timezone(timedelta(hours=9))

REQUIRED_HOLDING_COLUMNS = {
    "ticker",
    "name",
    "market",
    "quantity",
    "average_price",
    "financing_type",
}

REQUIRED_SUMMARY_COLUMNS = {
    "name",
    "ticker",
    "market",
    "status",
    "last_date",
    "current_close",
    "split_buy_low_ref",
    "split_buy_high_ref",
    "target1_ref",
    "target2_ref",
    "stop_ref",
    "low_3m_intraday",
    "high_3m_intraday",
    "low_3m_close",
    "high_3m_close",
    "position_in_3m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "low_liquidity",
    "operating_loss_flag",
    "operating_loss_basis",
    "supply_burden_flag",
    "supply_burden_level",
    "supply_burden_keywords",
    "trading_activity_label",
    "price_elasticity_label",
}

OUTPUT_COLUMNS = [
    "position_no",
    "holding_display",
    "holding_type",
    "code",
    "name",
    "market",
    "quantity",
    "average_buy_price",
    "current_price",
    "cost_basis",
    "market_value",
    "evaluation_profit_loss",
    "return_pct",
    "additional_buy_range",
    "sell_range",
    "risk_reduction_rule",
    "low_3m",
    "high_3m",
    "three_month_range_text",
    "position_in_3m_range_pct",
    "current_position_label",
    "supply_burden_text",
    "value_flow_assessment",
    "holding_action",
    "sector_theme",
    "analysis_basis_date",
    "summary_status",
    "operating_loss_flag",
    "supply_burden_flag",
    "low_liquidity",
    "trading_activity_label",
    "price_elasticity_label",
]


@dataclass(frozen=True)
class PortfolioTotals:
    position_rows: int
    unique_tickers: int
    cash_rows: int
    credit_rows: int
    total_quantity: float
    total_cost_basis: float
    total_market_value: float
    total_profit_loss: float
    total_return_pct: float | None
    credit_cost_basis: float
    credit_market_value: float
    credit_share_of_cost_pct: float | None


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def clean_ticker(value: Any) -> str:
    text = str(value).strip()
    if text.lower() in {"nan", "none", ""}:
        return ""
    text = re.sub(r"\.0$", "", text)
    digits = re.sub(r"\D", "", text)
    if not digits:
        return text.upper()
    return digits.zfill(6)


def normalize_market(value: Any) -> str:
    text = str(value).strip().upper()
    aliases = {
        "KS": "KOSPI",
        "KOSPI": "KOSPI",
        "코스피": "KOSPI",
        "KQ": "KOSDAQ",
        "KOSDAQ": "KOSDAQ",
        "코스닥": "KOSDAQ",
    }
    return aliases.get(text, text)


def normalize_financing_type(value: Any) -> tuple[str, bool]:
    text = str(value).strip().lower().replace(" ", "")
    credit_terms = (
        "신용",
        "융자",
        "자기융자",
        "credit",
        "loan",
        "margin",
    )
    if any(term in text for term in credit_terms):
        if "자기" in text:
            return "신용(자기융자)", True
        return "신용", True
    return "현금", False


def as_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {
        "true",
        "1",
        "yes",
        "y",
        "t",
        "예",
        "네",
    }


def won(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "자료없음"
    return f"{int(round(value)):,}원"


def price_range(low: float | None, high: float | None) -> str:
    if (
        low is None
        or high is None
        or low <= 0
        or high <= 0
        or high < low
    ):
        return "자료없음"
    return f"{int(round(low)):,}원~{int(round(high)):,}원"


def percent(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "자료없음"
    return f"{value:+.{digits}f}%"


def position_label(position_pct: float | None) -> str:
    if position_pct is None:
        return "위치확인제한"
    if position_pct <= 20:
        return "저점권"
    if position_pct <= 35:
        return "저점권반등초입"
    if position_pct <= 65:
        return "중간권"
    if position_pct <= 80:
        return "중상단권"
    if position_pct <= 92:
        return "상단권부담"
    return "고점권과열"


def choose_three_month_range(row: pd.Series) -> tuple[float | None, float | None, str]:
    low_intra = as_number(row.get("low_3m_intraday"))
    high_intra = as_number(row.get("high_3m_intraday"))
    if (
        low_intra is not None
        and high_intra is not None
        and low_intra > 0
        and high_intra > low_intra
    ):
        return low_intra, high_intra, "3개월 장중 저가~고가"

    low_close = as_number(row.get("low_3m_close"))
    high_close = as_number(row.get("high_3m_close"))
    if (
        low_close is not None
        and high_close is not None
        and low_close > 0
        and high_close > low_close
    ):
        return low_close, high_close, "3개월 종가 저가~고가 대체"

    return None, None, "3개월 범위 확인제한"


def compute_position(
    current: float | None,
    low: float | None,
    high: float | None,
) -> float | None:
    if (
        current is None
        or low is None
        or high is None
        or high <= low
    ):
        return None
    value = (current - low) / (high - low) * 100
    return round(max(0.0, min(100.0, value)), 2)


def supply_text(row: pd.Series) -> str:
    low_liquidity = bool_value(row.get("low_liquidity"))
    supply_flag = bool_value(row.get("supply_burden_flag"))
    level = str(row.get("supply_burden_level", "")).strip()
    keywords = str(row.get("supply_burden_keywords", "")).strip()
    if keywords.lower() in {"nan", "none"}:
        keywords = ""

    parts: list[str] = []
    if low_liquidity:
        parts.append("저유동성")
    if supply_flag:
        if level and level.lower() not in {"nan", "none"}:
            parts.append(f"수급 {level}")
        else:
            parts.append("수급부담")
        if keywords:
            parts.append(keywords)

    if not parts:
        return "뚜렷한 부담 미확인"
    return " · ".join(parts)


def severe_supply(row: pd.Series) -> bool:
    if bool_value(row.get("low_liquidity")):
        return True
    if not bool_value(row.get("supply_burden_flag")):
        return False

    level = str(row.get("supply_burden_level", "")).strip()
    keywords = str(row.get("supply_burden_keywords", "")).strip()
    severe_terms = (
        "위험",
        "CB",
        "BW",
        "EB",
        "유상증자",
        "전환청구",
        "보호예수",
        "블록딜",
        "대주주",
        "자사주처분",
        "최대주주변경",
    )
    combined = f"{level},{keywords}"
    return any(term in combined for term in severe_terms)


def value_flow_text(row: pd.Series) -> str:
    operating_loss = bool_value(row.get("operating_loss_flag"))
    operating_basis = str(row.get("operating_loss_basis", "")).strip()
    return_1m = as_number(row.get("return_1m_pct"))
    return_3m = as_number(row.get("return_3m_pct"))
    elasticity = str(row.get("price_elasticity_label", "")).strip()
    activity = str(row.get("trading_activity_label", "")).strip()

    parts: list[str] = []
    if operating_loss:
        basis = (
            operating_basis
            if operating_basis
            and operating_basis.lower() not in {"nan", "none"}
            else "최근 보고서"
        )
        parts.append(f"{basis} 영업손실로 보수적 접근")
    else:
        parts.append("최근 보고서 영업흑자 확인")

    if return_3m is not None:
        if return_3m >= 100:
            parts.append("3개월 급등폭이 매우 커 되돌림 위험 큼")
        elif return_3m >= 40:
            parts.append("3개월 상승흐름 강하나 변동성 주의")
        elif return_3m <= -30:
            parts.append("3개월 약세가 커 반등 확인 필요")
        elif return_3m <= -10:
            parts.append("3개월 흐름 약세")
        else:
            parts.append("3개월 흐름 중립")

    if return_1m is not None and return_1m <= -20:
        parts.append("최근 1개월 낙폭 큼")
    elif return_1m is not None and return_1m >= 20:
        parts.append("최근 1개월 단기과열 가능")

    if elasticity:
        parts.append(elasticity)
    if activity:
        parts.append(f"거래 {activity}")

    return " · ".join(parts)


def holding_action(
    *,
    current: float | None,
    average_price: float,
    return_pct: float | None,
    buy_low: float | None,
    buy_high: float | None,
    target1: float | None,
    stop: float | None,
    position_pct: float | None,
    is_credit: bool,
    risky_supply: bool,
) -> str:
    if current is None:
        return "⚪ 현재가 확인 후 판단"

    if stop is not None and current <= stop:
        if is_credit:
            return "⚠️ 신용 손실확대 방지를 위해 비중축소 우선 검토"
        return "⚠️ 손절·비중축소 기준 이탈, 보유근거 재점검"

    if target1 is not None and current >= target1:
        return "✅ 1차 익절구간 진입, 분할매도 검토"

    if is_credit:
        if return_pct is not None and return_pct <= -5:
            return "⚠️ 신용 손실구간, 추가매수 금지·반등 시 일부축소 검토"
        if risky_supply:
            return "⚠️ 신용·수급부담 동시 존재, 비중축소 우선"
        return "🟡 신용 추가매수 금지, 보유기간·이자비용 점검"

    in_buy_range = (
        buy_low is not None
        and buy_high is not None
        and buy_low <= current <= buy_high
    )
    if risky_supply:
        return "⚠️ 추가매수 보류, 수급·유동성 확인 후 보유 판단"
    if in_buy_range and position_pct is not None and position_pct <= 35:
        return "🟡 현금 분할추가매수 검토 가능"
    if position_pct is not None and position_pct >= 80:
        return "🟡 상단권부담, 반등 시 분할매도 검토"
    if current < average_price:
        return "🟡 보유 유지, 추가매수는 가치구간 도달 후 검토"
    return "🟡 보유 유지, 목표가 접근 시 분할익절 검토"


def additional_buy_text(
    *,
    buy_low: float | None,
    buy_high: float | None,
    is_credit: bool,
    risky_supply: bool,
) -> str:
    range_text = price_range(buy_low, buy_high)
    if is_credit:
        return f"신용 추가매수 금지 · 현금 참고 {range_text}"
    if risky_supply:
        return f"추가매수 보류 · 참고 {range_text}"
    return range_text


def risk_rule_text(
    *,
    stop: float | None,
    is_credit: bool,
) -> str:
    if stop is None:
        return (
            "신용담보·손실률 기준으로 우선 축소"
            if is_credit
            else "보유근거 훼손 시 비중축소"
        )
    if is_credit:
        return f"{won(stop)} 이탈 또는 담보부담 확대 시 우선축소"
    return f"{won(stop)} 종가 이탈 시 비중축소 재검토"


def load_holdings(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"보유내역 입력파일이 없습니다: {path}")

    frame = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"ticker": str},
    )
    missing = REQUIRED_HOLDING_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            "보유내역 필수열 누락: " + ",".join(sorted(missing))
        )

    frame = frame.copy()
    frame["ticker"] = frame["ticker"].map(clean_ticker)
    frame["market"] = frame["market"].map(normalize_market)
    frame["quantity"] = pd.to_numeric(
        frame["quantity"],
        errors="coerce",
    )
    frame["average_price"] = pd.to_numeric(
        frame["average_price"],
        errors="coerce",
    )

    if frame["ticker"].eq("").any():
        raise ValueError("종목코드가 비어 있는 보유행이 있습니다.")
    if frame["quantity"].isna().any() or frame["quantity"].le(0).any():
        raise ValueError("보유수량은 0보다 커야 합니다.")
    if (
        frame["average_price"].isna().any()
        or frame["average_price"].le(0).any()
    ):
        raise ValueError("평균매수가는 0보다 커야 합니다.")

    financing = frame["financing_type"].map(normalize_financing_type)
    frame["holding_type"] = financing.map(lambda item: item[0])
    frame["is_credit"] = financing.map(lambda item: item[1])

    if "sector_theme" not in frame.columns:
        frame["sector_theme"] = ""

    frame.insert(
        0,
        "position_no",
        np.arange(1, len(frame) + 1),
    )
    return frame


def load_summary(paths: Iterable[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"요약자료가 없습니다: {path}")
        part = pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype={"ticker": str},
        )
        missing = REQUIRED_SUMMARY_COLUMNS - set(part.columns)
        if missing:
            raise ValueError(
                f"{path.name} 필수열 누락: "
                + ",".join(sorted(missing))
            )
        part = part.copy()
        part["ticker"] = part["ticker"].map(clean_ticker)
        part["market"] = part["market"].map(normalize_market)
        parts.append(part)

    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["market", "ticker"],
        keep="last",
    )
    return combined


def build_holdings(
    holdings: pd.DataFrame,
    summary: pd.DataFrame,
) -> tuple[pd.DataFrame, PortfolioTotals, dict[str, Any]]:
    merged = holdings.merge(
        summary,
        how="left",
        on=["market", "ticker"],
        suffixes=("_holding", "_summary"),
        validate="many_to_one",
    )

    missing_summary = merged["current_close"].isna()
    if missing_summary.any():
        missing_rows = merged.loc[
            missing_summary,
            ["ticker", "name_holding", "market"],
        ].to_dict("records")
        raise ValueError(
            "요약자료에서 찾지 못한 보유종목: "
            + json.dumps(missing_rows, ensure_ascii=False)
        )

    output_rows: list[dict[str, Any]] = []
    fallback_range_rows = 0

    for _, row in merged.iterrows():
        current = as_number(row.get("current_close"))
        quantity = float(row["quantity"])
        average = float(row["average_price"])
        cost_basis = average * quantity
        market_value = (
            current * quantity
            if current is not None
            else None
        )
        profit_loss = (
            market_value - cost_basis
            if market_value is not None
            else None
        )
        return_pct = (
            profit_loss / cost_basis * 100
            if profit_loss is not None and cost_basis > 0
            else None
        )

        low_3m, high_3m, range_basis = choose_three_month_range(row)
        if "대체" in range_basis:
            fallback_range_rows += 1
        position_pct = compute_position(current, low_3m, high_3m)

        buy_low = as_number(row.get("split_buy_low_ref"))
        buy_high = as_number(row.get("split_buy_high_ref"))
        target1 = as_number(row.get("target1_ref"))
        target2 = as_number(row.get("target2_ref"))
        stop = as_number(row.get("stop_ref"))
        is_credit = bool(row["is_credit"])
        risky_supply = severe_supply(row)

        display_name = str(row["name_holding"]).strip()
        summary_name = str(row.get("name_summary", "")).strip()
        if not display_name or display_name.lower() in {"nan", "none"}:
            display_name = summary_name

        holding_type = str(row["holding_type"])
        holding_display = f"{holding_type} {display_name}"

        sector_theme = str(row.get("sector_theme", "")).strip()
        if sector_theme.lower() in {"nan", "none"}:
            sector_theme = ""
        if not sector_theme:
            sector_theme = "자료 미연결"

        output_rows.append(
            {
                "position_no": int(row["position_no"]),
                "holding_display": holding_display,
                "holding_type": holding_type,
                "code": clean_ticker(row["ticker"]),
                "name": display_name,
                "market": normalize_market(row["market"]),
                "quantity": quantity,
                "average_buy_price": average,
                "current_price": current,
                "cost_basis": round(cost_basis, 2),
                "market_value": (
                    round(market_value, 2)
                    if market_value is not None
                    else np.nan
                ),
                "evaluation_profit_loss": (
                    round(profit_loss, 2)
                    if profit_loss is not None
                    else np.nan
                ),
                "return_pct": (
                    round(return_pct, 2)
                    if return_pct is not None
                    else np.nan
                ),
                "additional_buy_range": additional_buy_text(
                    buy_low=buy_low,
                    buy_high=buy_high,
                    is_credit=is_credit,
                    risky_supply=risky_supply,
                ),
                "sell_range": price_range(target1, target2),
                "risk_reduction_rule": risk_rule_text(
                    stop=stop,
                    is_credit=is_credit,
                ),
                "low_3m": (
                    low_3m if low_3m is not None else np.nan
                ),
                "high_3m": (
                    high_3m if high_3m is not None else np.nan
                ),
                "three_month_range_text": (
                    f"{price_range(low_3m, high_3m)} "
                    f"({range_basis})"
                ),
                "position_in_3m_range_pct": (
                    position_pct
                    if position_pct is not None
                    else np.nan
                ),
                "current_position_label": position_label(position_pct),
                "supply_burden_text": supply_text(row),
                "value_flow_assessment": value_flow_text(row),
                "holding_action": holding_action(
                    current=current,
                    average_price=average,
                    return_pct=return_pct,
                    buy_low=buy_low,
                    buy_high=buy_high,
                    target1=target1,
                    stop=stop,
                    position_pct=position_pct,
                    is_credit=is_credit,
                    risky_supply=risky_supply,
                ),
                "sector_theme": sector_theme,
                "analysis_basis_date": str(row.get("last_date", "")),
                "summary_status": str(row.get("status", "")),
                "operating_loss_flag": bool_value(
                    row.get("operating_loss_flag")
                ),
                "supply_burden_flag": bool_value(
                    row.get("supply_burden_flag")
                ),
                "low_liquidity": bool_value(
                    row.get("low_liquidity")
                ),
                "trading_activity_label": str(
                    row.get("trading_activity_label", "")
                ),
                "price_elasticity_label": str(
                    row.get("price_elasticity_label", "")
                ),
            }
        )

    output = pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS)

    total_cost = float(output["cost_basis"].sum())
    total_market = float(output["market_value"].sum())
    total_profit = total_market - total_cost
    total_return = (
        total_profit / total_cost * 100
        if total_cost > 0
        else None
    )

    credit_mask = output["holding_type"].str.startswith("신용")
    credit_cost = float(
        output.loc[credit_mask, "cost_basis"].sum()
    )
    credit_market = float(
        output.loc[credit_mask, "market_value"].sum()
    )
    credit_share = (
        credit_cost / total_cost * 100
        if total_cost > 0
        else None
    )

    totals = PortfolioTotals(
        position_rows=int(len(output)),
        unique_tickers=int(output["code"].nunique()),
        cash_rows=int((~credit_mask).sum()),
        credit_rows=int(credit_mask.sum()),
        total_quantity=float(output["quantity"].sum()),
        total_cost_basis=round(total_cost, 2),
        total_market_value=round(total_market, 2),
        total_profit_loss=round(total_profit, 2),
        total_return_pct=(
            round(total_return, 2)
            if total_return is not None
            else None
        ),
        credit_cost_basis=round(credit_cost, 2),
        credit_market_value=round(credit_market, 2),
        credit_share_of_cost_pct=(
            round(credit_share, 2)
            if credit_share is not None
            else None
        ),
    )

    metadata = {
        "fallback_three_month_range_rows": fallback_range_rows,
        "analysis_basis_date_min": str(
            output["analysis_basis_date"].min()
        ),
        "analysis_basis_date_max": str(
            output["analysis_basis_date"].max()
        ),
        "all_summary_status_ok": bool(
            output["summary_status"].eq("OK").all()
        ),
        "duplicate_ticker_lots_preserved": bool(
            len(output) > output["code"].nunique()
        ),
    }

    return output, totals, metadata


def write_outputs(
    *,
    output: pd.DataFrame,
    totals: PortfolioTotals,
    metadata: dict[str, Any],
    output_dir: Path,
    input_path: Path,
    kospi_summary: Path,
    kosdaq_summary: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "holdings_latest.csv"
    status_path = output_dir / "holdings_status_latest.json"
    log_path = output_dir / "holdings_run_log_latest.txt"

    output.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    status = {
        "status": "OK",
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": now_kst(),
        "table_id": "holdings",
        "display_name": "보유종목표",
        "input_file": str(input_path),
        "summary_files": [
            str(kospi_summary),
            str(kosdaq_summary),
        ],
        "output_file": str(csv_path),
        "row_count": int(len(output)),
        "unique_ticker_count": int(output["code"].nunique()),
        "header_contract": [
            "보유/종목",
            "보유수량",
            "평균매수가",
            "현재가",
            "평가손익",
            "수익률",
            "추가매수구간",
            "1차 매도/익절가",
            "손절/비중축소 기준",
            "3개월저~고",
            "현재위치",
            "수급부담",
            "기업가치/흐름 평가",
            "보유·추가매수·매도 판단",
            "시장·티커",
            "섹터/테마",
        ],
        "portfolio_totals": totals.__dict__,
        "metadata": metadata,
        "privacy_notice": (
            "보유수량·평균매수가·평가손익은 개인 금융정보입니다. "
            "공개 저장소에 출력 파일을 커밋하면 누구나 볼 수 있습니다."
        ),
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={status['generated_at_kst']}",
        "TABLE_ID=holdings",
        "DISPLAY_NAME=보유종목표",
        f"INPUT_FILE={input_path}",
        f"OUTPUT_FILE={csv_path}",
        f"POSITION_ROWS={totals.position_rows}",
        f"UNIQUE_TICKERS={totals.unique_tickers}",
        f"CASH_ROWS={totals.cash_rows}",
        f"CREDIT_ROWS={totals.credit_rows}",
        f"TOTAL_COST_BASIS={totals.total_cost_basis}",
        f"TOTAL_MARKET_VALUE={totals.total_market_value}",
        f"TOTAL_PROFIT_LOSS={totals.total_profit_loss}",
        f"TOTAL_RETURN_PCT={totals.total_return_pct}",
        f"CREDIT_SHARE_OF_COST_PCT={totals.credit_share_of_cost_pct}",
        (
            "DUPLICATE_TICKER_LOTS_PRESERVED="
            + str(
                metadata["duplicate_ticker_lots_preserved"]
            ).lower()
        ),
        (
            "FALLBACK_THREE_MONTH_RANGE_ROWS="
            + str(
                metadata["fallback_three_month_range_rows"]
            )
        ),
        (
            "ALL_SUMMARY_STATUS_OK="
            + str(
                metadata["all_summary_status_ok"]
            ).lower()
        ),
        "HOLDINGS_TABLE_STATUS=OK",
    ]
    log_path.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    return {
        "csv": csv_path,
        "status": status_path,
        "log": log_path,
        "payload": status,
    }


def synthetic_holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "000001",
                "name": "테스트대형주",
                "market": "KOSPI",
                "quantity": 10,
                "average_price": 100_000,
                "financing_type": "현금",
                "sector_theme": "테스트",
            },
            {
                "ticker": "000001",
                "name": "테스트대형주",
                "market": "KOSPI",
                "quantity": 5,
                "average_price": 110_000,
                "financing_type": "자기융자",
                "sector_theme": "테스트",
            },
            {
                "ticker": "000002",
                "name": "테스트소형주",
                "market": "KOSDAQ",
                "quantity": 20,
                "average_price": 12_000,
                "financing_type": "현금",
                "sector_theme": "",
            },
        ]
    )


def synthetic_summary() -> pd.DataFrame:
    rows = []
    for code, name, market, current in [
        ("000001", "테스트대형주", "KOSPI", 95_000),
        ("000002", "테스트소형주", "KOSDAQ", 10_000),
    ]:
        rows.append(
            {
                "name": name,
                "ticker": code,
                "market": market,
                "status": "OK",
                "last_date": "2026-07-02",
                "current_close": current,
                "split_buy_low_ref": current * 0.90,
                "split_buy_high_ref": current * 0.97,
                "target1_ref": current * 1.08,
                "target2_ref": current * 1.15,
                "stop_ref": current * 0.85,
                "low_3m_intraday": current * 0.70,
                "high_3m_intraday": current * 1.25,
                "low_3m_close": current * 0.72,
                "high_3m_close": current * 1.20,
                "position_in_3m_range_pct": 50,
                "return_1m_pct": -10,
                "return_3m_pct": 20,
                "low_liquidity": market == "KOSDAQ",
                "operating_loss_flag": False,
                "operating_loss_basis": "2026 1분기보고서",
                "supply_burden_flag": market == "KOSDAQ",
                "supply_burden_level": (
                    "위험" if market == "KOSDAQ" else ""
                ),
                "supply_burden_keywords": (
                    "CB,전환청구"
                    if market == "KOSDAQ"
                    else ""
                ),
                "trading_activity_label": (
                    "매우활발"
                    if market == "KOSPI"
                    else "부족"
                ),
                "price_elasticity_label": (
                    "탄력 보통"
                    if market == "KOSPI"
                    else "탄력 불안정"
                ),
            }
        )
    return pd.DataFrame(rows)


def run_self_test() -> int:
    holdings = synthetic_holdings()
    financing = holdings["financing_type"].map(
        normalize_financing_type
    )
    holdings["holding_type"] = financing.map(
        lambda item: item[0]
    )
    holdings["is_credit"] = financing.map(
        lambda item: item[1]
    )
    holdings.insert(
        0,
        "position_no",
        np.arange(1, len(holdings) + 1),
    )

    output, totals, metadata = build_holdings(
        holdings,
        synthetic_summary(),
    )

    assert len(output) == 3
    assert output["code"].nunique() == 2
    assert totals.credit_rows == 1
    assert totals.cash_rows == 2
    assert metadata["duplicate_ticker_lots_preserved"] is True
    assert output["position_in_3m_range_pct"].notna().all()
    assert output["current_position_label"].notna().all()
    assert output["holding_action"].str.len().gt(0).all()
    assert output[
        "additional_buy_range"
    ].str.len().gt(0).all()
    assert output.loc[
        output["holding_type"].str.startswith("신용"),
        "additional_buy_range",
    ].str.contains("신용 추가매수 금지").all()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        output_paths = write_outputs(
            output=output,
            totals=totals,
            metadata=metadata,
            output_dir=root,
            input_path=root / "input.csv",
            kospi_summary=root / "kospi.csv",
            kosdaq_summary=root / "kosdaq.csv",
        )
        assert output_paths["csv"].exists()
        assert output_paths["status"].exists()
        assert output_paths["log"].exists()
        payload = json.loads(
            output_paths["status"].read_text(
                encoding="utf-8"
            )
        )
        assert payload["status"] == "OK"
        assert payload["row_count"] == 3

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "cash_credit_separate_rows,"
        "duplicate_ticker_lots,"
        "profit_loss,"
        "three_month_position,"
        "supply_burden,"
        "credit_additional_buy_block,"
        "portfolio_totals,"
        "output_files"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--holdings-input",
        default="input/holdings_input.csv",
    )
    parser.add_argument(
        "--kospi-summary",
        default="latest/kospi_universe_summary_latest.csv",
    )
    parser.add_argument(
        "--kosdaq-summary",
        default="latest/kosdaq_universe_summary_latest.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="latest",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    holdings_path = Path(args.holdings_input)
    kospi_path = Path(args.kospi_summary)
    kosdaq_path = Path(args.kosdaq_summary)
    output_dir = Path(args.output_dir)

    holdings = load_holdings(holdings_path)
    summary = load_summary((kospi_path, kosdaq_path))
    output, totals, metadata = build_holdings(
        holdings,
        summary,
    )
    paths = write_outputs(
        output=output,
        totals=totals,
        metadata=metadata,
        output_dir=output_dir,
        input_path=holdings_path,
        kospi_summary=kospi_path,
        kosdaq_summary=kosdaq_path,
    )

    print("HOLDINGS_TABLE_STATUS=OK")
    print(f"POSITION_ROWS={totals.position_rows}")
    print(f"UNIQUE_TICKERS={totals.unique_tickers}")
    print(f"CASH_ROWS={totals.cash_rows}")
    print(f"CREDIT_ROWS={totals.credit_rows}")
    print(f"TOTAL_COST_BASIS={totals.total_cost_basis}")
    print(f"TOTAL_MARKET_VALUE={totals.total_market_value}")
    print(f"TOTAL_PROFIT_LOSS={totals.total_profit_loss}")
    print(f"TOTAL_RETURN_PCT={totals.total_return_pct}")
    print(
        "CREDIT_SHARE_OF_COST_PCT="
        f"{totals.credit_share_of_cost_pct}"
    )
    print(f"OUTPUT_CSV={paths['csv']}")
    print(f"OUTPUT_STATUS={paths['status']}")
    print(f"OUTPUT_LOG={paths['log']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
