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

VERSION = "2026-09-17-v8.12.1-current-actionable-price-elasticity-20d-official-recovery-audit"
V8119_VERSION = "2026-09-17-v8.11.9-post-commit-source-contract-and-current-blocker-reaudit"
V8119_RESULT_COMMIT = "f470876fe7365e9590bcc5f61b88a2131d3322b5"
V8120_VERSION = "2026-09-17-v8.12.0-current-actionable-exact-da-official-recovery-audit"
V8120_RESULT_COMMIT = "f7bebe27d13aa2759d35a0af58679b698a130deb"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8119.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8119_summary_latest.json"
V8120_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8120_summary_latest.json"
HISTORY = ROOT / "latest/universe_raw_history_latest.csv"
PRICE_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
API_FILES = [
    ROOT / "api/two_table_v1/kospi.json",
    ROOT / "api/two_table_v1/decliners.json",
    ROOT / "api/two_table_v1/decliners24.json",
]

OUT_CSV = ROOT / "latest/investment_score_price_elasticity_actionable_v8121.csv"
OUT_JSON = ROOT / "latest/investment_score_price_elasticity_actionable_v8121_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_price_elasticity_actionable_v8121_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_price_elasticity_actionable_v8121.md"

EXPECTED_ACTIONABLE = {
    "003530": "한화투자증권",
    "004800": "효성",
    "006260": "LS",
    "006800": "미래에셋증권",
    "008060": "대덕",
    "010060": "OCI홀딩스",
    "027410": "BGF",
    "034730": "SK",
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


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def recursive_hits(obj, code):
    hits = []
    if isinstance(obj, dict):
        direct = ticker(obj.get("ticker") or obj.get("code") or obj.get("stock_code"))
        if direct == code:
            hits.append(obj)
        for value in obj.values():
            hits.extend(recursive_hits(value, code))
    elif isinstance(obj, list):
        for value in obj:
            hits.extend(recursive_hits(value, code))
    return hits


def extract_basis_from_hit(hit):
    metrics = hit.get("metrics") if isinstance(hit.get("metrics"), dict) else {}
    for value in (
        metrics.get("basis_date"),
        hit.get("basis_date"),
        hit.get("asof_date"),
        hit.get("date"),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        try:
            return pd.Timestamp(text).normalize()
        except Exception:
            pass
    return None


def current_basis_by_ticker():
    basis = {}
    hit_counts = Counter()
    for path in API_FILES:
        if not path.is_file():
            continue
        payload = read_json(path)
        for code in EXPECTED_ACTIONABLE:
            for hit in recursive_hits(payload, code):
                day = extract_basis_from_hit(hit)
                if day is not None:
                    basis.setdefault(code, set()).add(day)
                    hit_counts[code] += 1

    resolved = {}
    for code in sorted(EXPECTED_ACTIONABLE):
        days = sorted(basis.get(code, set()))
        if not days:
            raise RuntimeError("V8121_API_BASIS_MISSING:" + code)
        resolved[code] = days[-1]

    unique = sorted(set(resolved.values()))
    if len(unique) != 1:
        raise RuntimeError(
            "V8121_TARGET_BASIS_DATES_DIVERGED:"
            + ",".join(str(x.date()) for x in unique)
        )
    return resolved, unique[0], hit_counts


def valid_close_row(row):
    close = num(row.get("close"))
    return close is not None and close > 0


def calc_avg_daily_move_pct(rows):
    ordered = sorted(rows, key=lambda r: pd.Timestamp(r["date"]))
    closes = [num(r.get("close")) for r in ordered]
    if len(closes) < MIN_VALID_CLOSES:
        return None, [], []

    returns = []
    return_dates = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            continue
        returns.append(cur / prev - 1.0)
        return_dates.append(pd.Timestamp(ordered[i]["date"]).date().isoformat())

    if len(returns) < WINDOW_RETURNS:
        return None, returns, return_dates

    last20 = returns[-WINDOW_RETURNS:]
    last20_dates = return_dates[-WINDOW_RETURNS:]
    value = round(sum(abs(x) for x in last20) / WINDOW_RETURNS * 100.0, 2)
    return value, last20, last20_dates


def main():
    krx_key = os.environ.get("KRX_AUTH_KEY", "").strip()
    if not krx_key:
        raise RuntimeError("V8121_KRX_AUTH_KEY_MISSING")

    for path in (BLOCK_CSV, BLOCK_JSON, V8120_JSON, HISTORY, PRICE_CACHE):
        if not path.is_file():
            raise RuntimeError("V8121_MISSING_INPUT:" + str(path))

    s8119 = read_json(BLOCK_JSON)
    if s8119.get("version") != V8119_VERSION or s8119.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8121_V8119_CONTRACT_MISMATCH")
    if s8119.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8121_POLICY_VERSION_MISMATCH")

    rows8119 = read_csv(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker")): str(r.get("name") or "")
        for r in rows8119
        if r.get("source_group") == "PRICE_ELASTICITY_20D"
        and str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        and r.get("blocker_reason") == PRICE_REASON
    }
    if set(actionable) != set(EXPECTED_ACTIONABLE):
        raise RuntimeError("V8121_ACTIONABLE_SET_MISMATCH:" + ",".join(sorted(actionable)))

    s8120 = read_json(V8120_JSON)
    if s8120.get("version") != V8120_VERSION or s8120.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8121_V8120_CONTRACT_MISMATCH")
    if s8120.get("next_step") != "MOVE_TO_NEXT_ACTIONABLE_LANE_PRICE_ELASTICITY_20D":
        raise RuntimeError("V8121_V8120_HANDOFF_MISMATCH")
    if int(s8120.get("both_approved_exact_recoverable_count") or 0) != 0:
        raise RuntimeError("V8121_DA_RECOVERABLE_NOT_ZERO")

    existing = {
        ticker(r.get("ticker")): r
        for r in read_csv(PRICE_CACHE)
        if ticker(r.get("ticker"))
    }
    already_ready = {
        code for code in EXPECTED_ACTIONABLE
        if code in existing
        and str(existing[code].get("elasticity_source_status") or "") == "READY"
        and num(existing[code].get("avg_daily_move_pct")) is not None
        and (num(existing[code].get("elasticity_window_sessions")) or 0) >= WINDOW_RETURNS
    }
    if already_ready:
        raise RuntimeError(
            "V8121_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE:"
            + ",".join(sorted(already_ready))
        )

    raw = universe.read_csv_if_exists(HISTORY)
    hist = universe.normalize_history_dtypes(raw)
    if hist.empty:
        raise RuntimeError("V8121_OFFICIAL_HISTORY_EMPTY")

    kospi_all = hist[hist["market"] == "KOSPI"].copy()
    sessions = sorted(
        pd.Timestamp(x).normalize()
        for x in kospi_all["date"].dropna().unique()
    )
    if not sessions:
        raise RuntimeError("V8121_KOSPI_SESSION_CALENDAR_EMPTY")

    basis = sessions[-1]
    basis_source = "OFFICIAL_KRX_HISTORY_MAX_KOSPI_SESSION"
    kospi = kospi_all[kospi_all["date"] <= basis].copy()

    if len(sessions) < CALENDAR_BUFFER_SESSIONS:
        raise RuntimeError(f"V8121_SESSION_CALENDAR_TOO_SHORT:{len(sessions)}")

    target_sessions = sessions[-CALENDAR_BUFFER_SESSIONS:]
    target_set = set(target_sessions)
    by_ticker = {code: {} for code in EXPECTED_ACTIONABLE}

    for _, row in kospi.iterrows():
        code = ticker(row.get("ticker"))
        if code not in EXPECTED_ACTIONABLE:
            continue
        day = pd.Timestamp(row["date"]).normalize()
        if day not in target_set:
            continue
        data = row.to_dict()
        data["date"] = day
        if valid_close_row(data):
            by_ticker[code][day] = data

    initial_counts = {code: len(by_ticker[code]) for code in EXPECTED_ACTIONABLE}
    missing_dates = sorted({
        day
        for code in EXPECTED_ACTIONABLE
        for day in target_sessions
        if day not in by_ticker[code]
    })

    fetch_date_count = 0
    fetch_success_date_count = 0
    for day in missing_dates:
        bas_dd = day.strftime("%Y%m%d")
        logs = []
        raw_day = universe.request_krx_openapi(
            universe.OPENAPI_STOCK_URLS["KOSPI"],
            krx_key,
            bas_dd,
            logs,
            "V8121_KOSPI_STOCK",
        )
        fetch_date_count += 1
        norm = universe.normalize_stock_rows(raw_day, "KOSPI", bas_dd, logs)
        if norm is not None and not norm.empty:
            fetch_success_date_count += 1
            for code in EXPECTED_ACTIONABLE:
                match = norm[norm["ticker"] == code]
                if match.empty:
                    continue
                data = match.iloc[-1].to_dict()
                data["date"] = pd.Timestamp(data["date"]).normalize()
                if valid_close_row(data):
                    by_ticker[code][day] = data
        time.sleep(0.08)

    out_rows = []
    recoverable, insufficient = [], []
    classes = Counter()

    for code in sorted(EXPECTED_ACTIONABLE):
        valid_rows = [
            by_ticker[code][day]
            for day in target_sessions
            if day in by_ticker[code] and valid_close_row(by_ticker[code][day])
        ]
        avg_move, returns, return_dates = calc_avg_daily_move_pct(valid_rows)

        if avg_move is not None:
            classification = "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
            recoverable.append(code)
        else:
            classification = "INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
            insufficient.append(code)
        classes[classification] += 1

        used_rows = sorted(valid_rows, key=lambda r: pd.Timestamp(r["date"]))[-MIN_VALID_CLOSES:]
        used_close_dates = [pd.Timestamp(r["date"]).date().isoformat() for r in used_rows]

        out_rows.append({
            "ticker": code,
            "name": EXPECTED_ACTIONABLE[code],
            "basis_date": basis.date().isoformat(),
            "basis_source": basis_source,
                                  "calendar_buffer_sessions": len(target_sessions),
            "initial_valid_close_count": initial_counts[code],
            "final_valid_close_count": len(valid_rows),
            "required_valid_close_count": MIN_VALID_CLOSES,
            "elasticity_window_sessions": WINDOW_RETURNS,
            "avg_daily_move_pct": f"{avg_move:.2f}" if avg_move is not None else "",
            "classification": classification,
            "used_close_dates_json": json.dumps(
                used_close_dates, ensure_ascii=False, separators=(",", ":")
            ),
            "last20_return_dates_json": json.dumps(
                return_dates[-WINDOW_RETURNS:], ensure_ascii=False, separators=(",", ":")
            ),
            "last20_returns_json": json.dumps(
                [round(x, 10) for x in returns[-WINDOW_RETURNS:]],
                ensure_ascii=False, separators=(",", ":")
            ),
            "source": "KRX_OFFICIAL_STK_BYDD_TRD",
        })

    if len(out_rows) != 8:
        raise RuntimeError(f"V8121_OUTPUT_COUNT_NOT_8:{len(out_rows)}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "policy_version": POLICY_VERSION,
        "v8119_version": V8119_VERSION,
        "v8119_result_commit": V8119_RESULT_COMMIT,
        "v8120_version": V8120_VERSION,
        "v8120_result_commit": V8120_RESULT_COMMIT,
        "metric_contract": {
            "metric": "avg_daily_move_pct",
            "definition": "mean(abs(close_t / close_t_minus_1 - 1)) over latest 20 official close returns * 100",
            "return_count": WINDOW_RETURNS,
            "minimum_valid_closes": MIN_VALID_CLOSES,
            "atr_substitution_allowed": False,
        },
        "target_count": 8,
        "target_tickers": sorted(EXPECTED_ACTIONABLE),
        "basis_date": basis.date().isoformat(),
            "basis_source": basis_source,
        "calendar_buffer_sessions": len(target_sessions),
        "krx_refetch_date_count": fetch_date_count,
        "krx_refetch_success_date_count": fetch_success_date_count,
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
            "FREEZE_RECOVERABLE_PRICE_ELASTICITY_AND_SHADOW_SCORE"
            if recoverable
            else "AUDIT_ACTIONABLE_SUPPLY_SINGLE_FROM_V8119"
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
            "TARGET_COUNT=8",
            f"BASIS_DATE={basis.date().isoformat()}",
            f"BASIS_SOURCE={basis_source}",
            f"CALENDAR_BUFFER_SESSIONS={len(target_sessions)}",
            f"KRX_REFETCH_DATE_COUNT={fetch_date_count}",
            f"KRX_REFETCH_SUCCESS_DATE_COUNT={fetch_success_date_count}",
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
            "# V8.12.1 current actionable price-elasticity official recovery audit",
            "",
            "- Official KRX close prices only.",
            "- Latest 20 close-to-close returns.",
            "- avg_daily_move_pct = mean(abs(return)) * 100.",
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

    print("V8121_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AUDIT=PASS")


if __name__ == "__main__":
    main()
