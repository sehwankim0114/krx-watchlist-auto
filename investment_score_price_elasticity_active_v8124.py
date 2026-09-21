#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import collect_universe as universe

VERSION = "2026-09-21-v8.12.4-current-active-price-elasticity-20d-official-audit"
V8123_VERSION = "2026-09-21-v8.12.3-current-blocker-reaudit-after-universe-drift"
V8123_RESULT_COMMIT = "284e7c3cbf5bbe8876916251365ae678797a5a11"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8123.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8123_summary_latest.json"
HISTORY = ROOT / "latest/universe_raw_history_latest.csv"
PRICE_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_price_elasticity_active_v8124.csv"
OUT_JSON = ROOT / "latest/investment_score_price_elasticity_active_v8124_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_price_elasticity_active_v8124_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_price_elasticity_active_v8124.md"

EXPECTED = {
    "000320": "노루홀딩스",
    "001800": "오리온홀딩스",
    "003470": "유안타증권",
    "003540": "대신증권",
    "005440": "현대지에프홀딩스",
    "006840": "AK홀딩스",
    "026890": "스틱인베스트먼트",
    "034830": "한국토지신탁",
    "039490": "키움증권",
    "107590": "미원홀딩스",
    "244920": "에이플러스에셋",
    "323410": "카카오뱅크",
}

PRICE_REASON = "하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS = 20
MIN_VALID_CLOSES = 21
CALENDAR_BUFFER_SESSIONS = 40


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def valid_close(row):
    x = num(row.get("close"))
    return x is not None and x > 0


def calc(rows):
    ordered = sorted(rows, key=lambda r: pd.Timestamp(r["date"]))
    closes = [num(r.get("close")) for r in ordered]
    if len(closes) < MIN_VALID_CLOSES:
        return None, [], []
    returns = []
    dates = []
    for i in range(1, len(closes)):
        p, c = closes[i - 1], closes[i]
        if p is None or c is None or p <= 0 or c <= 0:
            continue
        returns.append(c / p - 1.0)
        dates.append(pd.Timestamp(ordered[i]["date"]).date().isoformat())
    if len(returns) < WINDOW_RETURNS:
        return None, returns, dates
    last = returns[-WINDOW_RETURNS:]
    last_dates = dates[-WINDOW_RETURNS:]
    pct = round(sum(abs(x) for x in last) / WINDOW_RETURNS * 100.0, 2)
    return pct, last, last_dates


def main():
    key = os.environ.get("KRX_AUTH_KEY", "").strip()
    if not key:
        raise RuntimeError("V8124_KRX_AUTH_KEY_MISSING")

    for p in (BLOCK_CSV, BLOCK_JSON, HISTORY, PRICE_CACHE):
        if not p.is_file():
            raise RuntimeError("V8124_MISSING_INPUT:" + str(p))

    s8123 = read_json(BLOCK_JSON)
    if s8123.get("version") != V8123_VERSION:
        raise RuntimeError("V8124_V8123_VERSION_MISMATCH")
    if s8123.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8124_V8123_STATUS_MISMATCH")
    if s8123.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8124_POLICY_VERSION_MISMATCH")
    if s8123.get("next_actionable_source_group") != "PRICE_ELASTICITY_20D":
        raise RuntimeError("V8124_NEXT_GROUP_NOT_ELASTICITY")
    if s8123.get("next_actionable_selection_reason") != "HIGHEST_ACTIONABLE_SINGLE_BLOCKER_COUNT":
        raise RuntimeError("V8124_SELECTION_REASON_CHANGED")

    blockers = read_rows(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker")): str(r.get("name") or "")
        for r in blockers
        if r.get("source_group") == "PRICE_ELASTICITY_20D"
        and r.get("single_blocker_ticker") == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        and r.get("blocker_reason") == PRICE_REASON
    }
    if set(actionable) != set(EXPECTED):
        raise RuntimeError(
            "V8124_ACTIONABLE_SET_MISMATCH:" + ",".join(sorted(actionable))
        )

    prod_cache = {
        ticker(r.get("ticker")): r
        for r in read_rows(PRICE_CACHE)
        if ticker(r.get("ticker"))
    }
    ready_overlap = sorted(
        code for code in EXPECTED
        if code in prod_cache
        and prod_cache[code].get("source_status") == "READY"
        and num(prod_cache[code].get("avg_daily_move_pct")) is not None
    )
    if ready_overlap:
        raise RuntimeError(
            "V8124_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE:"
            + ",".join(ready_overlap)
        )

    raw = universe.read_csv_if_exists(HISTORY)
    hist = universe.normalize_history_dtypes(raw)
    if hist.empty:
        raise RuntimeError("V8124_OFFICIAL_HISTORY_EMPTY")

    kospi_all = hist[hist["market"] == "KOSPI"].copy()
    sessions = sorted(
        pd.Timestamp(x).normalize()
        for x in kospi_all["date"].dropna().unique()
    )
    if len(sessions) < CALENDAR_BUFFER_SESSIONS:
        raise RuntimeError(
            f"V8124_SESSION_CALENDAR_TOO_SHORT:{len(sessions)}"
        )

    basis = sessions[-1]
    basis_source = "OFFICIAL_KRX_HISTORY_MAX_KOSPI_SESSION"
    target_sessions = sessions[-CALENDAR_BUFFER_SESSIONS:]
    target_set = set(target_sessions)

    by_code = {code: {} for code in EXPECTED}
    for _, row in kospi_all.iterrows():
        code = ticker(row.get("ticker"))
        if code not in EXPECTED:
            continue
        day = pd.Timestamp(row["date"]).normalize()
        if day not in target_set:
            continue
        data = row.to_dict()
        data["date"] = day
        if valid_close(data):
            by_code[code][day] = data

    initial_counts = {code: len(by_code[code]) for code in EXPECTED}

    missing_dates = sorted({
        day
        for code in EXPECTED
        for day in target_sessions
        if day not in by_code[code]
    })

    fetch_count = 0
    fetch_success = 0
    for day in missing_dates:
        bas_dd = day.strftime("%Y%m%d")
        logs = []
        raw_day = universe.request_krx_openapi(
            universe.OPENAPI_STOCK_URLS["KOSPI"],
            key,
            bas_dd,
            logs,
            "V8124_KOSPI_STOCK",
        )
        fetch_count += 1
        norm = universe.normalize_stock_rows(
            raw_day,
            "KOSPI",
            bas_dd,
            logs,
        )
        if norm is not None and not norm.empty:
            fetch_success += 1
            for code in EXPECTED:
                match = norm[norm["ticker"] == code]
                if match.empty:
                    continue
                data = match.iloc[-1].to_dict()
                data["date"] = pd.Timestamp(data["date"]).normalize()
                if valid_close(data):
                    by_code[code][day] = data
        time.sleep(0.08)

    out = []
    recoverable = []
    insufficient = []
    classes = Counter()

    for code in sorted(EXPECTED):
        rows = [
            by_code[code][d]
            for d in target_sessions
            if d in by_code[code] and valid_close(by_code[code][d])
        ]
        pct, returns, return_dates = calc(rows)

        if pct is None:
            cls = "INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
            insufficient.append(code)
        else:
            cls = "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
            recoverable.append(code)
        classes[cls] += 1

        used = sorted(rows, key=lambda r: pd.Timestamp(r["date"]))[-MIN_VALID_CLOSES:]
        used_dates = [
            pd.Timestamp(r["date"]).date().isoformat()
            for r in used
        ]

        out.append({
            "ticker": code,
            "name": EXPECTED[code],
            "basis_date": basis.date().isoformat(),
            "basis_source": basis_source,
            "calendar_buffer_sessions": len(target_sessions),
            "initial_valid_close_count": initial_counts[code],
            "final_valid_close_count": len(rows),
            "required_valid_close_count": MIN_VALID_CLOSES,
            "elasticity_window_sessions": WINDOW_RETURNS,
            "avg_daily_move_pct": f"{pct:.2f}" if pct is not None else "",
            "classification": cls,
            "used_close_dates_json": json.dumps(
                used_dates, ensure_ascii=False, separators=(",", ":")
            ),
            "last20_return_dates_json": json.dumps(
                return_dates[-WINDOW_RETURNS:],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "last20_returns_json": json.dumps(
                [round(x, 10) for x in returns[-WINDOW_RETURNS:]],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "source": "KRX_OFFICIAL_STK_BYDD_TRD",
        })

    if len(out) != 12:
        raise RuntimeError(f"V8124_OUTPUT_COUNT_NOT_12:{len(out)}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(out[0].keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "policy_version": POLICY_VERSION,
        "v8123_version": V8123_VERSION,
        "v8123_result_commit": V8123_RESULT_COMMIT,
        "metric_contract": {
            "metric": "avg_daily_move_pct",
            "definition": "mean(abs(close_t / close_t_minus_1 - 1)) over latest 20 official close returns * 100",
            "return_count": WINDOW_RETURNS,
            "minimum_valid_closes": MIN_VALID_CLOSES,
            "atr_substitution_allowed": False,
        },
        "target_count": 12,
        "target_tickers": sorted(EXPECTED),
        "basis_date": basis.date().isoformat(),
        "basis_source": basis_source,
        "calendar_buffer_sessions": len(target_sessions),
        "krx_refetch_date_count": fetch_count,
        "krx_refetch_success_date_count": fetch_success,
        "classification_counts": dict(classes),
        "recoverable_count": len(recoverable),
        "recoverable_tickers": sorted(recoverable),
        "insufficient_count": len(insufficient),
        "insufficient_tickers": sorted(insufficient),
        "hard_guards": {
            "production_price_elasticity_cache_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "atr_used_as_elasticity_substitute": False,
            "nonofficial_price_source_used": False,
            "source_promoted": False,
        },
        "next_step": (
            "FREEZE_ACTIVE_PRICE_ELASTICITY_AND_SHADOW_SCORE_V8125"
            if recoverable
            else "MOVE_TO_NEXT_ACTIONABLE_SOURCE_GROUP_FROM_V8123"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY",
            "TARGET_COUNT=12",
            f"BASIS_DATE={basis.date().isoformat()}",
            f"BASIS_SOURCE={basis_source}",
            f"KRX_REFETCH_DATE_COUNT={fetch_count}",
            f"KRX_REFETCH_SUCCESS_DATE_COUNT={fetch_success}",
            f"RECOVERABLE={len(recoverable)}",
            f"INSUFFICIENT={len(insufficient)}",
            "ATR_SUBSTITUTION_USED=false",
            "NONOFFICIAL_PRICE_SOURCE_USED=false",
            "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
            "SOURCE_PROMOTED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={summary['next_step']}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.12.4 current active price-elasticity audit",
            "",
            "- Targets: 12 current actionable single blockers.",
            "- Official KRX close prices only.",
            "- Latest 20 close-to-close returns.",
            "- ATR is not a substitute.",
            "- AUDIT_ONLY; no production cache mutation.",
            "",
            f"- Recoverable: {len(recoverable)}",
            f"- Insufficient: {len(insufficient)}",
            f"- Next: `{summary['next_step']}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8124_CURRENT_ACTIVE_PRICE_ELASTICITY_AUDIT=PASS")


if __name__ == "__main__":
    main()
