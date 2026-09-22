#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import collect_universe as universe

VERSION = "2026-09-23-v8.16.7-current-actionable-price-elasticity-official-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8166_VERSION = "2026-09-23-v8.16.6-post-source-apply-current-blocker-reaudit"
V8166_RESULT_COMMIT = "0d0c32f25f4b104908d185de93a88da9edece4f3"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8166.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8166_summary_latest.json"
PRICE_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

OUT_CSV = ROOT / "latest/investment_score_price_elasticity_active_v8167.csv"
OUT_JSON = ROOT / "latest/investment_score_price_elasticity_active_v8167_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_price_elasticity_active_v8167_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_price_elasticity_active_v8167.md"

TARGET = "004990"
TARGET_NAME = "롯데지주"
PRICE_REASON = "하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS = 20
MIN_VALID_CLOSES = 21
CALENDAR_LOOKBACK_DAYS = 60
DESIRED_OFFICIAL_SESSIONS = 30

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

def calc(series):
    ordered = sorted(series, key=lambda x: x[0])
    if len(ordered) < MIN_VALID_CLOSES:
        return None, [], [], []

    closes = [x[1] for x in ordered]
    dates = [x[0] for x in ordered]
    returns = []
    return_dates = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            continue
        returns.append(cur / prev - 1.0)
        return_dates.append(dates[i])

    if len(returns) < WINDOW_RETURNS:
        return None, returns, return_dates, ordered

    last = returns[-WINDOW_RETURNS:]
    pct = round(
        sum(abs(x) for x in last) / WINDOW_RETURNS * 100.0,
        4,
    )
    return pct, returns, return_dates, ordered

def main():
    key = os.environ.get("KRX_AUTH_KEY", "").strip()
    if not key:
        raise RuntimeError("V8167_KRX_AUTH_KEY_MISSING")

    summary = read_json(BLOCK_JSON)
    manifest = read_json(MANIFEST)

    if summary.get("version") != V8166_VERSION:
        raise RuntimeError("V8167_V8166_VERSION_MISMATCH")
    if summary.get("status") != (
        "AUDIT_ONLY_POST_SOURCE_APPLY_DYNAMIC_CURRENT_BLOCKERS"
    ):
        raise RuntimeError("V8167_V8166_STATUS_MISMATCH")
    if summary.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8167_POLICY_VERSION_MISMATCH")
    if summary.get("selection_mode") != "ACTIONABLE_SINGLE_BLOCKER":
        raise RuntimeError("V8167_SELECTION_MODE_CHANGED")
    if summary.get("selected_source_group") != "PRICE_ELASTICITY_20D":
        raise RuntimeError("V8167_SELECTED_GROUP_CHANGED")
    if summary.get("selected_tickers") != [TARGET]:
        raise RuntimeError("V8167_SELECTED_TICKER_CHANGED")
    if summary.get("next_step") != (
        "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8167"
    ):
        raise RuntimeError("V8167_PREDECESSOR_NEXT_STEP_MISMATCH")

    blockers = read_rows(BLOCK_CSV)
    selected = [
        r for r in blockers
        if ticker(r.get("ticker")) == TARGET
        and r.get("source_group") == "PRICE_ELASTICITY_20D"
        and r.get("single_blocker_ticker") == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        and r.get("blocker_reason") == PRICE_REASON
    ]
    if len(selected) != 1:
        raise RuntimeError("V8167_SELECTED_BLOCKER_NOT_EXACTLY_ONE")
    if selected[0].get("name") != TARGET_NAME:
        raise RuntimeError("V8167_TARGET_NAME_CHANGED")

    prod_cache = {
        ticker(r.get("ticker")): r
        for r in read_rows(PRICE_CACHE)
        if ticker(r.get("ticker"))
    }
    if len(prod_cache) != 151:
        raise RuntimeError(
            "V8167_PRODUCTION_ELASTICITY_ROWS_NOT_151:"
            + str(len(prod_cache))
        )
    if TARGET in prod_cache:
        row = prod_cache[TARGET]
        if (
            row.get("source_status") == "READY"
            and num(row.get("avg_daily_move_pct")) is not None
        ):
            raise RuntimeError(
                "V8167_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE"
            )

    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError("V8167_MANIFEST_NOT_PRODUCTION")
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError("V8167_MANIFEST_NOT_SAFE_LATEST")

    basis_iso = str(manifest.get("basis_date") or "")
    if not basis_iso:
        raise RuntimeError("V8167_MANIFEST_BASIS_MISSING")
    basis = datetime.strptime(basis_iso, "%Y-%m-%d").date()

    # Build the session set only from official KRX responses.
    official_sessions = []
    target_series = []
    request_count = 0
    successful_session_count = 0
    target_found_count = 0
    transport_or_parse_fail_dates = []
    no_target_dates = []

    cursor = basis
    earliest = basis - timedelta(days=CALENDAR_LOOKBACK_DAYS)

    while cursor >= earliest and len(official_sessions) < DESIRED_OFFICIAL_SESSIONS:
        if cursor.weekday() < 5:
            bas_dd = cursor.strftime("%Y%m%d")
            logs = []
            try:
                raw_day = universe.request_krx_openapi(
                    universe.OPENAPI_STOCK_URLS["KOSPI"],
                    key,
                    bas_dd,
                    logs,
                    "V8167_KOSPI_STOCK",
                )
                request_count += 1
                norm = universe.normalize_stock_rows(
                    raw_day,
                    "KOSPI",
                    bas_dd,
                    logs,
                )
            except Exception:
                request_count += 1
                transport_or_parse_fail_dates.append(
                    cursor.isoformat()
                )
                norm = None

            if norm is not None and not norm.empty:
                successful_session_count += 1
                official_sessions.append(cursor.isoformat())
                match = norm[norm["ticker"] == TARGET]
                if not match.empty:
                    close = num(match.iloc[-1].get("close"))
                    if close is not None and close > 0:
                        target_series.append(
                            (cursor.isoformat(), close)
                        )
                        target_found_count += 1
                    else:
                        no_target_dates.append(cursor.isoformat())
                else:
                    no_target_dates.append(cursor.isoformat())

            time.sleep(0.08)

        cursor -= timedelta(days=1)

    # We walked backwards; restore chronological order.
    official_sessions = sorted(set(official_sessions))
    target_series = sorted(
        {d: c for d, c in target_series}.items()
    )

    pct, returns, return_dates, ordered = calc(target_series)

    if pct is not None:
        classification = (
            "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
        )
        recoverable = True
        next_step = (
            "FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8168"
        )
    else:
        classification = (
            "INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
        )
        recoverable = False
        next_step = (
            "AUDIT_NEXT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8168"
        )

    used = ordered[-MIN_VALID_CLOSES:] if len(ordered) >= MIN_VALID_CLOSES else ordered
    used_dates = [d for d, _ in used]

    audit_row = {
        "ticker": TARGET,
        "name": TARGET_NAME,
        "basis_date": basis_iso,
        "basis_source": "PRODUCTION_MANIFEST_BASIS_DATE",
        "official_request_count": request_count,
        "official_session_count": len(official_sessions),
        "target_valid_close_count": len(target_series),
        "required_valid_close_count": MIN_VALID_CLOSES,
        "elasticity_window_sessions": WINDOW_RETURNS,
        "avg_daily_move_pct": (
            f"{pct:.4f}" if pct is not None else ""
        ),
        "classification": classification,
        "recoverable": "TRUE" if recoverable else "FALSE",
        "used_close_dates_json": json.dumps(
            used_dates,
            ensure_ascii=False,
            separators=(",", ":"),
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
    }

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(audit_row.keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerow(audit_row)

    result = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY",
        "policy_version": POLICY_VERSION,
        "v8166_version": V8166_VERSION,
        "v8166_result_commit": V8166_RESULT_COMMIT,
        "target_count": 1,
        "target_tickers": [TARGET],
        "target_names": [TARGET_NAME],
        "production_price_elasticity_row_count": len(prod_cache),
        "target_present_in_production_cache": TARGET in prod_cache,
        "metric_contract": {
            "metric": "avg_daily_move_pct",
            "definition": (
                "mean(abs(close_t / close_t_minus_1 - 1)) "
                "over latest 20 official close returns * 100"
            ),
            "return_count": WINDOW_RETURNS,
            "minimum_valid_closes": MIN_VALID_CLOSES,
            "atr_substitution_allowed": False,
        },
        "basis_date": basis_iso,
        "basis_source": "PRODUCTION_MANIFEST_BASIS_DATE",
        "official_request_count": request_count,
        "official_session_count": len(official_sessions),
        "official_session_dates": official_sessions,
        "target_valid_close_count": len(target_series),
        "target_valid_close_dates": [d for d, _ in target_series],
        "transport_or_parse_fail_count": len(
            transport_or_parse_fail_dates
        ),
        "transport_or_parse_fail_dates": (
            transport_or_parse_fail_dates
        ),
        "official_sessions_without_valid_target_close_count": len(
            no_target_dates
        ),
        "official_sessions_without_valid_target_close_dates": (
            no_target_dates
        ),
        "classification": classification,
        "recoverable_count": 1 if recoverable else 0,
        "recoverable_tickers": [TARGET] if recoverable else [],
        "insufficient_count": 0 if recoverable else 1,
        "insufficient_tickers": [] if recoverable else [TARGET],
        "calculated_avg_daily_move_pct": pct,
        "hard_guards": {
            "production_price_elasticity_cache_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "atr_used_as_elasticity_substitute": False,
            "nonofficial_price_source_used": False,
            "source_promoted": False,
        },
        "next_step": next_step,
    }

    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY",
            "TARGET_COUNT=1",
            f"TARGET_TICKER={TARGET}",
            f"BASIS_DATE={basis_iso}",
            f"PRODUCTION_PRICE_ELASTICITY_ROWS={len(prod_cache)}",
            f"TARGET_PRESENT_IN_PRODUCTION_CACHE={str(TARGET in prod_cache).lower()}",
            f"OFFICIAL_REQUEST_COUNT={request_count}",
            f"OFFICIAL_SESSION_COUNT={len(official_sessions)}",
            f"TARGET_VALID_CLOSE_COUNT={len(target_series)}",
            f"TRANSPORT_OR_PARSE_FAIL_COUNT={len(transport_or_parse_fail_dates)}",
            f"CLASSIFICATION={classification}",
            f"RECOVERABLE={1 if recoverable else 0}",
            f"INSUFFICIENT={0 if recoverable else 1}",
            "ATR_SUBSTITUTION_USED=false",
            "NONOFFICIAL_PRICE_SOURCE_USED=false",
            "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
            "PRODUCTION_DATA_MODIFIED=false",
            "SOURCE_PROMOTED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.16.7 current actionable price-elasticity audit",
            "",
            "- Target: 롯데지주 (004990).",
            "- Source: official KRX daily close only.",
            "- Production basis date: " + basis_iso + ".",
            "- Metric: latest 20 close-to-close absolute returns mean.",
            "- 21 valid official closes are required.",
            "- ATR substitution and non-official price substitution are forbidden.",
            "- Production caches and API are not modified.",
            "",
            f"- Valid closes found: {len(target_series)}.",
            f"- Classification: {classification}.",
            f"- Recoverable: {recoverable}.",
            f"- Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8167_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AUDIT=PASS")
    print(f"V8167_TARGET_VALID_CLOSE_COUNT={len(target_series)}")
    print(f"V8167_CLASSIFICATION={classification}")
    print(f"V8167_RECOVERABLE={str(recoverable).lower()}")
    print(f"V8167_NEXT_STEP={next_step}")

if __name__ == "__main__":
    main()
