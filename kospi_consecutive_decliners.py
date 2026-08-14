#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KOSPI 연속하락표 전용 생성기

입력
- latest/universe_raw_history_latest.csv
- latest/kospi_universe_summary_latest.csv
- latest/krx_sector_theme_latest.csv (있으면 사용)
- api/stock_reference_shards/*.json (있으면 사용)
- Cloudflare Worker /quotes 현재가

출력
- api/kospi_consecutive_decliners.json
- latest/kospi_consecutive_decliners_latest.csv
- latest/kospi_consecutive_decliners_latest.json
- latest/kospi_consecutive_decliners_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import requests


KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent

DEFAULT_PRICE_API_BASE = (
    "https://krx-live-price-ksh.diaconos.workers.dev"
)

SCRIPT_VERSION = "kospi_consecutive_decliners.py v1.0.0"


# ---------------------------------------------------------------------
# 기본 함수
# ---------------------------------------------------------------------

def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def normalize_ticker(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip().replace("'", "")

    if text.endswith(".0"):
        text = text[:-2]

    digits = "".join(ch for ch in text if ch.isdigit())

    if len(digits) >= 6:
        return digits[-6:]

    return digits.zfill(6) if digits else ""


def to_number(value: Any) -> Optional[float]:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    text = str(value).replace(",", "").strip()

    if text in {"", "-", "None", "nan", "NaN"}:
        return None

    try:
        return float(text)
    except Exception:
        return None


def json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype={"ticker": str, "code": str},
            low_memory=False,
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            path,
            dtype={"ticker": str, "code": str},
            low_memory=False,
        )


def fmt_price(value: Any) -> Optional[str]:
    number = to_number(value)

    if number is None:
        return None

    return f"{int(round(number)):,}원"


def fmt_range(low: Any, high: Any) -> Optional[str]:
    lo = fmt_price(low)
    hi = fmt_price(high)

    if lo and hi:
        return f"{lo}~{hi}"

    return lo or hi


# ---------------------------------------------------------------------
# 최근 방향성 / 연속하락 계산
# ---------------------------------------------------------------------

def consecutive_decline_days(closes: Iterable[float]) -> int:
    values = [
        float(x)
        for x in closes
        if x is not None and pd.notna(x)
    ]

    if len(values) < 2:
        return 0

    streak = 0

    for i in range(len(values) - 1, 0, -1):
        if values[i] < values[i - 1]:
            streak += 1
        else:
            break

    return streak


def streak_change_pct(
    closes: Iterable[float],
    streak_days: int,
) -> Optional[float]:
    values = [
        float(x)
        for x in closes
        if x is not None and pd.notna(x)
    ]

    if streak_days <= 0:
        return 0.0

    if len(values) < streak_days + 1:
        return None

    start = values[-(streak_days + 1)]
    end = values[-1]

    if start <= 0:
        return None

    return round((end / start - 1.0) * 100.0, 2)


def average_direction_run_days(
    closes: Iterable[float],
    lookback_days: int,
) -> Optional[float]:
    values = pd.Series(
        [
            float(x)
            for x in closes
            if x is not None and pd.notna(x)
        ],
        dtype=float,
    )

    if len(values) < 5:
        return None

    values = values.tail(lookback_days + 1)

    signs = np.sign(values.diff()).iloc[1:]

    # 보합일은 직전 방향의 연장으로 처리
    signs = signs.replace(0, np.nan).ffill().dropna()

    if signs.empty:
        return None

    runs: List[int] = []
    current_sign = signs.iloc[0]
    current_length = 1

    for sign in signs.iloc[1:]:
        if sign == current_sign:
            current_length += 1
        else:
            runs.append(current_length)
            current_sign = sign
            current_length = 1

    runs.append(current_length)

    if not runs:
        return None

    return round(float(np.mean(runs)), 1)


# ---------------------------------------------------------------------
# 이동평균 추세
# ---------------------------------------------------------------------

def ma_trend_arrow(
    closes: Iterable[float],
    window: int,
) -> str:
    series = pd.Series(
        [
            float(x)
            for x in closes
            if x is not None and pd.notna(x)
        ],
        dtype=float,
    )

    if len(series) < window:
        return "?"

    ma = series.rolling(window).mean().dropna()

    if ma.empty:
        return "?"

    compare_gap = min(5, len(ma) - 1)

    if compare_gap <= 0:
        return "→"

    current = float(ma.iloc[-1])
    previous = float(ma.iloc[-1 - compare_gap])

    if previous == 0:
        return "→"

    change_pct = (current / previous - 1.0) * 100.0

    if change_pct > 0.35:
        return "↗"

    if change_pct < -0.35:
        return "↘"

    return "→"


# ---------------------------------------------------------------------
# 위치·거래활발·탄력
# ---------------------------------------------------------------------

def position_pct(
    current: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    if (
        current is None
        or low is None
        or high is None
        or high <= low
    ):
        return None

    return round(
        (current - low) / (high - low) * 100.0,
        1,
    )


def position_label(value: Optional[float]) -> str:
    if value is None:
        return "확인필요"

    if value <= 15:
        return "바닥권"

    if value <= 35:
        return "중하단"

    if value <= 65:
        return "중간"

    if value <= 85:
        return "중상단"

    return "상단"


def activity_label(
    avg_trading_value: Optional[float],
) -> str:
    if avg_trading_value is None:
        return "확인필요"

    if avg_trading_value >= 100_000_000_000:
        return "매우 활발"

    if avg_trading_value >= 30_000_000_000:
        return "활발"

    if avg_trading_value >= 5_000_000_000:
        return "보통"

    return "낮음"


def elasticity_label(
    avg_move_pct: Optional[float],
) -> str:
    if avg_move_pct is None:
        return "확인필요"

    value = abs(avg_move_pct)

    if value >= 6.0:
        return "매우 높음·고위험"

    if value >= 4.0:
        return "높음"

    if value >= 2.0:
        return "보통"

    return "낮음"


# ---------------------------------------------------------------------
# 종목 참고 shard
# ---------------------------------------------------------------------

def load_stock_reference() -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}

    shard_dir = ROOT / "api" / "stock_reference_shards"

    if not shard_dir.exists():
        return result

    for path in sorted(shard_dir.glob("*.json")):
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            continue

        rows = payload.get("rows", [])

        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            if str(row.get("market", "")).upper() != "KOSPI":
                continue

            ticker = normalize_ticker(
                row.get("ticker")
            )

            if ticker:
                result[ticker] = row

    return result


# ---------------------------------------------------------------------
# 섹터/테마
# ---------------------------------------------------------------------

def load_sector_theme() -> Dict[str, Dict[str, Any]]:
    path = ROOT / "latest" / "krx_sector_theme_latest.csv"

    df = read_csv(path)

    result: Dict[str, Dict[str, Any]] = {}

    if df.empty:
        return result

    for _, row in df.iterrows():
        ticker = normalize_ticker(
            row.get("code", row.get("ticker"))
        )

        if not ticker:
            continue

        result[ticker] = {
            "sector": row.get("sector"),
            "theme": row.get("theme"),
            "sector_theme": row.get("sector_theme"),
        }

    return result


# ---------------------------------------------------------------------
# Worker 현재가
# ---------------------------------------------------------------------

def chunked(
    values: List[str],
    size: int,
) -> Iterable[List[str]]:
    for i in range(0, len(values), size):
        yield values[i:i + size]


def fetch_quote_batch(
    session: requests.Session,
    base_url: str,
    tickers: List[str],
) -> Dict[str, Dict[str, Any]]:
    items = ",".join(
        f"{ticker}|KOSPI"
        for ticker in tickers
    )

    response = session.get(
        f"{base_url.rstrip('/')}/quotes",
        params={"items": items},
        timeout=30,
    )

    response.raise_for_status()

    payload = response.json()

    result: Dict[str, Dict[str, Any]] = {}

    for row in payload.get("quotes", []):
        if not isinstance(row, dict):
            continue

        ticker = normalize_ticker(
            row.get("code")
            or row.get("quote_key")
            or row.get("ticker")
        )

        if ticker and row.get("ok") is True:
            result[ticker] = row

    return result


def fetch_all_quotes(
    tickers: List[str],
    base_url: str,
    log_lines: List[str],
) -> Dict[str, Dict[str, Any]]:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent":
                "krx-watchlist-consecutive-decliners/1.0"
        }
    )

    results: Dict[str, Dict[str, Any]] = {}

    pending = list(dict.fromkeys(tickers))

    batch_sizes = [40, 20, 10]

    for attempt, batch_size in enumerate(
        batch_sizes,
        start=1,
    ):
        if not pending:
            break

        log_lines.append(
            f"QUOTE_ATTEMPT_{attempt}_START "
            f"pending={len(pending)} batch={batch_size}"
        )

        for batch in chunked(pending, batch_size):
            try:
                batch_result = fetch_quote_batch(
                    session,
                    base_url,
                    batch,
                )

                results.update(batch_result)

            except Exception as exc:
                log_lines.append(
                    f"QUOTE_BATCH_FAIL "
                    f"attempt={attempt} "
                    f"size={len(batch)} "
                    f"error={repr(exc)}"
                )

            time.sleep(0.10)

        pending = [
            ticker
            for ticker in pending
            if ticker not in results
        ]

        log_lines.append(
            f"QUOTE_ATTEMPT_{attempt}_END "
            f"ok={len(results)} "
            f"remaining={len(pending)}"
        )

    return results


# ---------------------------------------------------------------------
# 수급/기업가치 설명
# ---------------------------------------------------------------------

def supply_note(
    reference: Dict[str, Any],
    low_liquidity: bool,
    avg_move_pct: Optional[float],
) -> str:
    burden = bool(
        reference.get("supply_burden_flag")
        or reference.get("supply_burden_detected")
    )

    level = (
        reference.get("supply_burden_level")
        or ""
    )

    keywords = (
        reference.get("supply_burden_keywords")
        or ""
    )

    if burden:
        text = f"수급부담 {level or '주의'}"

        if keywords:
            text += f": {keywords}"

        return text

    warnings = []

    if low_liquidity:
        warnings.append("거래유동성 낮음")

    if (
        avg_move_pct is not None
        and abs(avg_move_pct) >= 5
    ):
        warnings.append("일중 변동성 큼")

    if warnings:
        return (
            "특별한 공개 수급부담 신호는 없지만 "
            + "·".join(warnings)
            + "에 주의"
        )

    return (
        "현재 참조자료상 특별한 수급부담 신호는 확인되지 않음. "
        "외국인·기관 당일 순매수는 별도 확인 필요"
    )


def corporate_value_note(
    reference: Dict[str, Any],
) -> str:
    operating_loss = bool(
        reference.get("operating_loss_flag")
    )

    if operating_loss:
        return (
            "최근 공개 실적자료에서 영업적자 경고가 있어 "
            "낙폭만 보고 매수하기보다 실적 회복 확인이 필요"
        )

    return (
        "공개 참조자료상 영업적자 경고는 없음. "
        "PER·PBR·매출·영업이익 성장성은 종목별 추가 확인 필요"
    )


# ---------------------------------------------------------------------
# 간단 기술점수
# ---------------------------------------------------------------------

def technical_score(
    streak: int,
    pos_pct: Optional[float],
    avg_move_pct: Optional[float],
    avg_trading_value: Optional[float],
) -> int:
    score = 50

    score += min(streak, 6) * 5

    if pos_pct is not None:
        if 15 <= pos_pct <= 40:
            score += 12
        elif pos_pct < 15:
            score += 5
        elif pos_pct >= 85:
            score -= 8

    if avg_move_pct is not None:
        move = abs(avg_move_pct)

        if 1.5 <= move <= 4.0:
            score += 7
        elif move > 6:
            score -= 8

    if avg_trading_value is not None:
        if avg_trading_value >= 30_000_000_000:
            score += 8
        elif avg_trading_value < 5_000_000_000:
            score -= 10

    return int(max(0, min(100, score)))


def recommendation_icon(score: int) -> str:
    if score >= 80:
        return "🟢"

    if score >= 68:
        return "🟡"

    return "⚠️"


# ---------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--min-streak",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--lookback-days",
        type=int,
        default=60,
    )

    parser.add_argument(
        "--output-dir",
        default="latest",
    )

    parser.add_argument(
        "--api-dir",
        default="api",
    )

    args = parser.parse_args()

    if args.min_streak < 3:
        raise SystemExit(
            "--min-streak must be >= 3"
        )

    if args.lookback_days < 20:
        raise SystemExit(
            "--lookback-days must be >= 20"
        )

    output_dir = ROOT / args.output_dir
    api_dir = ROOT / args.api_dir

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    api_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_lines: List[str] = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"STARTED_AT_KST={now_kst()}",
        f"MIN_STREAK={args.min_streak}",
        f"LOOKBACK_DAYS={args.lookback_days}",
    ]

    history_path = (
        ROOT
        / "latest"
        / "universe_raw_history_latest.csv"
    )

    summary_path = (
        ROOT
        / "latest"
        / "kospi_universe_summary_latest.csv"
    )

    history = read_csv(history_path)
    summary = read_csv(summary_path)

    if history.empty:
        raise RuntimeError(
            f"history missing or empty: {history_path}"
        )

    if summary.empty:
        raise RuntimeError(
            f"summary missing or empty: {summary_path}"
        )

    history["ticker"] = history["ticker"].map(
        normalize_ticker
    )

    history["market"] = (
        history["market"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    history["date"] = pd.to_datetime(
        history["date"],
        errors="coerce",
    )

    history["close"] = pd.to_numeric(
        history["close"],
        errors="coerce",
    )

    history = history[
        (history["market"] == "KOSPI")
        & history["ticker"].str.fullmatch(
            r"\d{6}",
            na=False,
        )
    ].copy()

    history = history.dropna(
        subset=["date", "close"]
    )

    summary["ticker"] = summary["ticker"].map(
        normalize_ticker
    )

    if "market" in summary.columns:
        summary = summary[
            summary["market"]
            .astype(str)
            .str.upper()
            .eq("KOSPI")
        ].copy()

    summary = summary.drop_duplicates(
        subset=["ticker"],
        keep="last",
    )

    universe = sorted(
        ticker
        for ticker in summary["ticker"].tolist()
        if len(ticker) == 6
    )

    log_lines.append(
        f"UNIVERSE_COUNT={len(universe)}"
    )

    if len(universe) < 800:
        raise RuntimeError(
            f"KOSPI universe too small: {len(universe)}"
        )

    summary_map = {
        row["ticker"]: row
        for _, row in summary.iterrows()
    }

    sector_map = load_sector_theme()
    reference_map = load_stock_reference()

    price_api_base = os.environ.get(
        "PRICE_API_BASE",
        DEFAULT_PRICE_API_BASE,
    )

    quotes = fetch_all_quotes(
        universe,
        price_api_base,
        log_lines,
    )

    log_lines.append(
        f"QUOTE_OK_COUNT={len(quotes)}"
    )

    quote_fail_count = (
        len(universe) - len(quotes)
    )

    log_lines.append(
        f"QUOTE_FAIL_COUNT={quote_fail_count}"
    )

    current_day = pd.Timestamp(
        datetime.now(KST).date()
    )

    rows: List[Dict[str, Any]] = []

    for ticker in universe:
        stock_hist = history[
            history["ticker"] == ticker
        ].sort_values("date").copy()

        if stock_hist.empty:
            continue

        summary_row = summary_map.get(ticker)

        if summary_row is None:
            continue

        name = str(
            summary_row.get(
                "name",
                stock_hist["name"].iloc[-1]
                if "name" in stock_hist.columns
                else ticker,
            )
        )

        quote = quotes.get(ticker)

        official_last_date = stock_hist["date"].max()

        current_price = None
        current_price_source = "KRX_OFFICIAL"

        if quote:
            current_price = to_number(
                quote.get("current_price")
                or quote.get("price")
            )

        # 공식 일봉보다 날짜가 뒤인 경우에만
        # Worker 현재가를 새 거래일 값으로 추가
        if (
            current_price is not None
            and official_last_date.normalize()
            < current_day
        ):
            new_row = {
                "date": current_day,
                "market": "KOSPI",
                "ticker": ticker,
                "name": name,
                "close": current_price,
            }

            stock_hist = pd.concat(
                [
                    stock_hist,
                    pd.DataFrame([new_row]),
                ],
                ignore_index=True,
            )

            stock_hist = (
                stock_hist
                .drop_duplicates(
                    subset=["date"],
                    keep="last",
                )
                .sort_values("date")
            )

            current_price_source = (
                quote.get("source")
                or "NAVER_AUXILIARY"
            )

        else:
            current_price = float(
                stock_hist["close"].iloc[-1]
            )

        closes = (
            stock_hist["close"]
            .dropna()
            .astype(float)
            .tolist()
        )

        streak = consecutive_decline_days(
            closes
        )

        if streak < args.min_streak:
            continue

        decline_pct = streak_change_pct(
            closes,
            streak,
        )

        avg_run = average_direction_run_days(
            closes,
            args.lookback_days,
        )

        ma5 = ma_trend_arrow(closes, 5)
        ma20 = ma_trend_arrow(closes, 20)
        ma60 = ma_trend_arrow(closes, 60)
        ma120 = ma_trend_arrow(closes, 120)

        low_3m = to_number(
            summary_row.get(
                "low_3m_intraday"
            )
        )

        high_3m = to_number(
            summary_row.get(
                "high_3m_intraday"
            )
        )

        pos_pct = position_pct(
            current_price,
            low_3m,
            high_3m,
        )

        avg_move_abs = to_number(
            summary_row.get(
                "avg_daily_move_abs"
            )
        )

        avg_move_pct = to_number(
            summary_row.get(
                "avg_daily_move_pct"
            )
        )

        avg_trading_value = to_number(
            summary_row.get(
                "avg20_trading_value"
            )
        )

        low_liquidity = bool(
            summary_row.get(
                "low_liquidity",
                False,
            )
        )

        reference = reference_map.get(
            ticker,
            {},
        )

        sector_info = sector_map.get(
            ticker,
            {},
        )

        activity = (
            reference.get(
                "trading_activity_label"
            )
            or activity_label(
                avg_trading_value
            )
        )

        elasticity = (
            reference.get(
                "price_elasticity_label"
            )
            or elasticity_label(
                avg_move_pct
            )
        )

        score = technical_score(
            streak,
            pos_pct,
            avg_move_pct,
            avg_trading_value,
        )

        icon = recommendation_icon(score)

        value_buy_range = fmt_range(
            summary_row.get(
                "split_buy_low_ref"
            ),
            summary_row.get(
                "split_buy_high_ref"
            ),
        )

        sell_range = fmt_range(
            summary_row.get(
                "target1_ref"
            ),
            summary_row.get(
                "target2_ref"
            ),
        )

        if (
            avg_move_pct is not None
            and avg_move_abs is not None
        ):
            avg_daily_move_text = (
                f"{abs(avg_move_pct):.2f}% / "
                f"±{int(round(abs(avg_move_abs))):,}원"
            )

        elif avg_move_pct is not None:
            avg_daily_move_text = (
                f"{abs(avg_move_pct):.2f}%"
            )

        else:
            avg_daily_move_text = None

        row = {
            "rank": 0,
            "recommendation": icon,
            "name": name,
            "code": ticker,
            "market": "KOSPI",

            "current_price":
                int(round(current_price))
                if current_price is not None
                else None,

            "current_price_source":
                current_price_source,

            "streak_days": streak,
            "streak_change_pct":
                decline_pct,

            "avg_direction_run_days":
                avg_run,

            "value_buy_range":
                value_buy_range,

            "first_sell_target_range":
                sell_range,

            "low_3m":
                int(round(low_3m))
                if low_3m is not None
                else None,

            "high_3m":
                int(round(high_3m))
                if high_3m is not None
                else None,

            "return_1m_pct":
                to_number(
                    summary_row.get(
                        "return_1m_pct"
                    )
                ),

            "trading_activity":
                activity,

            "price_elasticity":
                elasticity,

            "position_in_3m_range_pct":
                pos_pct,

            "current_position":
                position_label(pos_pct),

            "ma5_trend": ma5,
            "ma20_trend": ma20,
            "ma60_trend": ma60,
            "ma120_trend": ma120,

            "trend_text":
                f"5{ma5} 20{ma20} "
                f"60{ma60} 120{ma120}",

            "avg_daily_move_pct":
                avg_move_pct,

            "avg_daily_move_abs":
                int(round(avg_move_abs))
                if avg_move_abs is not None
                else None,

            "avg_daily_move_text":
                avg_daily_move_text,

            "supply_risk_note":
                supply_note(
                    reference,
                    low_liquidity,
                    avg_move_pct,
                ),

            "corporate_value_note":
                corporate_value_note(
                    reference
                ),

            "technical_score":
                score,

            "sector":
                sector_info.get("sector"),

            "theme":
                sector_info.get("theme"),

            "sector_theme":
                sector_info.get(
                    "sector_theme"
                ),

            "asof_date":
                str(
                    stock_hist[
                        "date"
                    ].max().date()
                ),
        }

        rows.append(row)

    # 연속하락일 우선,
    # 같은 일수에서는 기술점수 우선
    rows.sort(
        key=lambda x: (
            -int(x.get("streak_days") or 0),
            -int(x.get("technical_score") or 0),
            float(
                x.get(
                    "streak_change_pct"
                )
                or 0
            ),
        )
    )

    for rank, row in enumerate(
        rows,
        start=1,
    ):
        row["rank"] = rank

    payload = {
        "status": "OK",
        "schema_version": "1.0",
        "script_version":
            SCRIPT_VERSION,

        "table_id":
            "kospi_consecutive_decliners",

        "display_name":
            "연속하락표",

        "generated_at_kst":
            now_kst(),

        "market":
            "KOSPI",

        "universe_count":
            len(universe),

        "quote_ok_count":
            len(quotes),

        "quote_fail_count":
            quote_fail_count,

        "min_streak_days":
            args.min_streak,

        "lookback_days":
            args.lookback_days,

        "row_count":
            len(rows),

        "today_price_policy":
            (
                "KRX official history + "
                "request-time NAVER auxiliary "
                "price when official daily data "
                "has not yet advanced"
            ),

        "average_direction_run_definition":
            (
                "최근 lookback 거래일 동안 "
                "상승·하락 동일 방향이 지속된 "
                "연속구간 길이의 평균"
            ),

        "rows": rows,
    }

    payload = json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=json_safe,
        )
    )

    api_path = (
        api_dir
        / "kospi_consecutive_decliners.json"
    )

    latest_json_path = (
        output_dir
        / "kospi_consecutive_decliners_latest.json"
    )

    latest_csv_path = (
        output_dir
        / "kospi_consecutive_decliners_latest.csv"
    )

    log_path = (
        output_dir
        / "kospi_consecutive_decliners_run_log_latest.txt"
    )

    json_text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    api_path.write_text(
        json_text,
        encoding="utf-8",
    )

    latest_json_path.write_text(
        json_text,
        encoding="utf-8",
    )

    csv_df = pd.DataFrame(rows)

    csv_df.to_csv(
        latest_csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    log_lines.extend(
        [
            f"ROW_COUNT={len(rows)}",
            f"API_OUTPUT={api_path}",
            f"CSV_OUTPUT={latest_csv_path}",
            "STATUS=OK",
            f"FINISHED_AT_KST={now_kst()}",
        ]
    )

    log_path.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    print("CONSECUTIVE_DECLINERS_BUILD=OK")
    print(
        f"UNIVERSE_COUNT={len(universe)}"
    )
    print(
        f"QUOTE_OK_COUNT={len(quotes)}"
    )
    print(
        f"QUOTE_FAIL_COUNT={quote_fail_count}"
    )
    print(
        f"MIN_STREAK_DAYS={args.min_streak}"
    )
    print(
        f"ROW_COUNT={len(rows)}"
    )
    print(
        f"OUTPUT={api_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
