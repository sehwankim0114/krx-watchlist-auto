#!/usr/bin/env python3
"""Official daily-low swing references and entry-dated trailing-stop policy.

The public-universe output is a reference only. An actual stop requires an
explicit, private tracking start date and is never written to the public cache.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

CONTRACT = "2026-10-21-confirmed-swing-low-3x3-close-trigger-v1"
LEFT = RIGHT = 3
REFERENCE_LOOKBACK = 60


def number(value):
    try:
        result = float(str(value).replace(",", ""))
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def valid_bar(row):
    values = {key: number(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in values.values()):
        return False
    return values["low"] <= min(values["open"], values["close"]) and max(values["open"], values["close"]) <= values["high"]


def pivot_events(by_date, sessions):
    """A pivot is usable only after three subsequent complete official bars."""
    events = []
    for pos in range(LEFT, len(sessions) - RIGHT):
        window = [by_date.get(sessions[i]) for i in range(pos - LEFT, pos + RIGHT + 1)]
        if any(row is None or not valid_bar(row) for row in window):
            continue
        low = number(window[LEFT]["low"])
        if all(low < number(row["low"]) for offset, row in enumerate(window) if offset != LEFT):
            events.append({
                "pivot_date": sessions[pos],
                "confirmation_date": sessions[pos + RIGHT],
                "pivot_low": low,
                "pivot_session_index": pos,
            })
    return events


def public_reference(events, by_date, sessions):
    recent_start = max(0, len(sessions) - REFERENCE_LOOKBACK)
    candidates = [event for event in events if event["pivot_session_index"] >= recent_start]
    if not candidates:
        return {"status": "NO_CONFIRMED_PIVOT_IN_60_SESSIONS", "pivot_low": None}
    event = candidates[-1]
    confirm_index = sessions.index(event["confirmation_date"])
    breach_date = None
    missing_date = None
    for date in sessions[confirm_index:]:
        row = by_date.get(date)
        if row is None or not valid_bar(row):
            missing_date = date
            break
        if number(row["close"]) <= event["pivot_low"]:
            breach_date = date
            break
    return {
        "status": "REFERENCE_BREACHED" if breach_date else
                  "REFERENCE_UNKNOWN_MISSING_BAR" if missing_date else "REFERENCE_UNBREACHED",
        "pivot_date": event["pivot_date"],
        "confirmation_date": event["confirmation_date"],
        "pivot_low": event["pivot_low"],
        "first_close_breach_date": breach_date,
        "first_missing_or_invalid_bar_date": missing_date,
        "actual_trailing_stop": None,
    }


def trailing_stop_for_start(events, by_date, sessions, start_date):
    """Pure runtime calculation; callers must keep the user's date private."""
    if start_date not in sessions or start_date not in by_date:
        return {"status": "START_DATE_NOT_IN_OFFICIAL_HISTORY", "stop": None}
    stop = None
    chosen = None
    events_by_confirmation = defaultdict(list)
    for event in events:
        if event["pivot_date"] >= start_date:
            events_by_confirmation[event["confirmation_date"]].append(event)
    for date in sessions[sessions.index(start_date):]:
        row = by_date.get(date)
        if row is None or not valid_bar(row):
            return {"status": "OFFICIAL_BAR_MISSING_OR_INVALID_AFTER_START", "stop": None, "date": date}
        for event in events_by_confirmation.get(date, []):
            if stop is None or event["pivot_low"] > stop:
                stop = event["pivot_low"]
                chosen = event
        if stop is not None and number(row["close"]) <= stop:
            return {
                "status": "TRIGGERED_BY_OFFICIAL_CLOSE", "stop": stop,
                "trigger_date": date, "source_pivot_date": chosen["pivot_date"],
                "confirmation_date": chosen["confirmation_date"],
            }
    if stop is None:
        return {"status": "NO_CONFIRMED_PIVOT_AFTER_START", "stop": None}
    return {
        "status": "ACTIVE", "stop": stop,
        "source_pivot_date": chosen["pivot_date"],
        "confirmation_date": chosen["confirmation_date"],
    }


def build(history_path, meta_path, source_path):
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if meta.get("status") != "READY" or source.get("status") != "READY_SOURCE_ONLY":
        raise ValueError("OFFICIAL_HISTORY_OR_SWING_SOURCE_NOT_READY")
    basis = meta.get("cache_max_date")
    if source.get("basis_date") != basis or source.get("standalone_swing_table_enabled") is not False:
        raise ValueError("SOURCE_BASIS_OR_ACTIVATION_MISMATCH")
    target = {str(t).zfill(6) for t in meta.get("target_tickers") or []}
    source_tickers = {str(row["ticker"]).zfill(6) for row in source.get("rows") or []}
    if len(target) != meta.get("target_ticker_count") or target != source_tickers:
        raise ValueError("TARGET_TICKER_MISMATCH")
    grouped = defaultdict(dict)
    sessions = set()
    with history_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ticker = str(row["ticker"]).zfill(6)
            if ticker not in target or row["date"] > basis:
                continue
            if row["date"] in grouped[ticker]:
                raise ValueError("DUPLICATE_OFFICIAL_BAR:" + ticker + ":" + row["date"])
            grouped[ticker][row["date"]] = row
            sessions.add(row["date"])
    sessions = sorted(sessions)
    if not sessions or sessions[-1] != basis:
        raise ValueError("HISTORY_BASIS_MISMATCH")
    if set(grouped) != target:
        raise ValueError("TARGET_HISTORY_MISSING")
    rows = []
    for ticker in sorted(target):
        events = pivot_events(grouped[ticker], sessions)
        rows.append({
            "ticker": ticker,
            "reference": public_reference(events, grouped[ticker], sessions),
            "confirmed_pivot_count": len(events),
        })
    return {
        "contract_version": CONTRACT,
        "status": "READY_REFERENCE_ONLY",
        "basis_date": basis,
        "row_count": len(rows),
        "pivot_definition": "STRICT_LOW_BELOW_3_PREVIOUS_AND_3_FOLLOWING_COMPLETE_BARS",
        "confirmation_lag_sessions": RIGHT,
        "breach_basis": "OFFICIAL_DAILY_CLOSE_LE_PIVOT_LOW",
        "public_reference_lookback_sessions": REFERENCE_LOOKBACK,
        "actual_trailing_stop_requires_explicit_start_date": True,
        "ratchet_down_allowed": False,
        "buffer_applied": False,
        "production_activation_allowed": False,
        "standalone_swing_table_enabled": False,
        "rows": rows,
    }


def self_test():
    sessions = [f"D{i:02}" for i in range(12)]
    lows = [12, 11, 10, 8, 10, 11, 12, 9, 10, 11, 12, 13]
    by_date = {
        day: {"open": str(low + 1), "high": str(low + 2), "low": str(low),
              "close": str(low + 1), "volume": "100"}
        for day, low in zip(sessions, lows)
    }
    events = pivot_events(by_date, sessions)
    assert len(events) == 2 and events[0]["pivot_date"] == "D03"
    assert events[0]["confirmation_date"] == "D06"
    assert public_reference(events, by_date, sessions)["pivot_date"] == "D07"
    assert trailing_stop_for_start(events, by_date, sessions, "D00")["stop"] == 9
    by_date["D11"].update({"open": "10", "high": "11", "low": "8", "close": "8"})
    assert trailing_stop_for_start(events, by_date, sessions, "D00")["status"] == "TRIGGERED_BY_OFFICIAL_CLOSE"
    by_date["D09"]["volume"] = "0"
    assert trailing_stop_for_start(events, by_date, sessions, "D00")["status"] == "OFFICIAL_BAR_MISSING_OR_INVALID_AFTER_START"
    print("CONFIRMED_SWING_LOW_POLICY_SELF_TEST=PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=Path("latest/active_stock_long_history_260d_latest.csv"))
    parser.add_argument("--meta", type=Path, default=Path("latest/active_stock_long_history_260d_meta_latest.json"))
    parser.add_argument("--source", type=Path, default=Path("latest/standalone_swing_source_latest.json"))
    parser.add_argument("--out", type=Path, default=Path("latest/confirmed_swing_low_reference_latest.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    payload = build(args.history, args.meta, args.source)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = defaultdict(int)
    for row in payload["rows"]:
        counts[row["reference"]["status"]] += 1
    print("CONFIRMED_SWING_LOW_REFERENCE=PASS")
    print("BASIS_DATE=" + payload["basis_date"])
    print("ROW_COUNT=" + str(payload["row_count"]))
    print("REFERENCE_STATUS_COUNTS=" + json.dumps(dict(counts), sort_keys=True))
    print("PRODUCTION_ACTIVATION_ALLOWED=false")


if __name__ == "__main__":
    main()

