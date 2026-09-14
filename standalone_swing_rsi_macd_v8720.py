#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_rsi_macd_v8720.py v1.0.0"
CONTRACT_VERSION = "2026-09-14-v8.7.20-standalone-swing-rsi-macd-source"
INTEGRATED_CONTRACT = "2026-09-14-v8.7.20-standalone-swing-integrated-rsi-macd-source"
READINESS_CONTRACT = "2026-09-14-v8.7.20-standalone-swing-readiness-rsi-macd-sync"

HISTORY = Path("latest/active_stock_long_history_260d_latest.csv")
HISTORY_META = Path("latest/active_stock_long_history_260d_meta_latest.json")
INTEGRATED = Path("latest/standalone_swing_integrated_latest.json")
INTEGRATED_META = Path("latest/standalone_swing_integrated_meta_latest.json")
INTEGRATED_CSV = Path("latest/standalone_swing_integrated_latest.csv")
PREPROD = Path("latest/standalone_swing_preproduction_readiness_latest.json")
PREPROD_META = Path("latest/standalone_swing_preproduction_readiness_meta_latest.json")
DISPLAY = Path("latest/standalone_swing_display_merge_readiness_latest.json")
DISPLAY_META = Path("latest/standalone_swing_display_merge_readiness_meta_latest.json")
MANIFEST = Path("api/manifest.json")

OUT_TECH = Path("latest/standalone_swing_rsi_macd_latest.json")
OUT_TECH_META = Path("latest/standalone_swing_rsi_macd_meta_latest.json")
OUT_TECH_LOG = Path("latest/standalone_swing_rsi_macd_run_log_latest.txt")
OUT_INTEGRATED_LOG = Path("latest/standalone_swing_integrated_run_log_latest.txt")
OUT_PREPROD_LOG = Path("latest/standalone_swing_preproduction_readiness_run_log_latest.txt")
OUT_DISPLAY_LOG = Path("latest/standalone_swing_display_merge_readiness_run_log_latest.txt")

EXPECTED_OLD_INTEGRATED = "2026-09-13-v8.7.17-standalone-swing-integrated-returns-source"

RSI_CONTRACT = {
    "name": "WILDER_RSI_14_SMA_SEEDED",
    "period": 14,
    "input": "confirmed_daily_close",
    "gain_loss_seed": "SMA_FIRST_14_CHANGES",
    "smoothing": "WILDER_RECURSIVE_ALPHA_1_OVER_14",
    "formula": "RSI=100-100/(1+avg_gain/avg_loss)",
    "zones": {
        "overbought": ">=70",
        "oversold": "<=30",
        "neutral": "otherwise",
    },
}

MACD_CONTRACT = {
    "name": "PERIOD_EMA_MACD_12_26_9_SMA_SEEDED",
    "input": "confirmed_daily_close",
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9,
    "ema_alpha": "2/(period+1)",
    "ema_seed": "SMA_FIRST_PERIOD_VALUES",
    "line": "EMA12-EMA26",
    "signal": "EMA9(MACD_LINE)",
    "histogram": "MACD_LINE-SIGNAL",
    "fixed_factor_macdfix_selected": False,
}

REMAINING_BLOCKERS = [
    "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
    "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
    "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
    "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
    "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
    "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
]

PENDING_METRICS = [
    "investment_score_100",
    "earnings_outlook_change",
    "confirmed_swing_low_stop",
]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_json(path: Path, obj):
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def fnum(value):
    try:
        x = float(str(value).replace(",", ""))
        if math.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return None

def rsi_wilder_14(closes):
    period = 14
    if len(closes) < period + 1:
        return {"status": "INSUFFICIENT_HISTORY", "value": None, "zone": "UNAVAILABLE"}

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period

    if avg_loss == 0.0 and avg_gain == 0.0:
        return {"status": "FLAT_EDGE_CASE", "value": None, "zone": "UNAVAILABLE"}
    if avg_loss == 0.0:
        value = 100.0
    else:
        rs = avg_gain / avg_loss
        value = 100.0 - 100.0 / (1.0 + rs)

    if value >= 70:
        zone = "OVERBOUGHT_70"
    elif value <= 30:
        zone = "OVERSOLD_30"
    else:
        zone = "NEUTRAL"

    return {
        "status": "OK",
        "value": round(value, 6),
        "zone": zone,
    }

def ema_sma_seed(values, period):
    if len(values) < period:
        return [None] * len(values)
    alpha = 2.0 / (period + 1.0)
    out = [None] * len(values)
    seed_index = period - 1
    seed = sum(values[:period]) / period
    out[seed_index] = seed
    prev = seed
    for i in range(seed_index + 1, len(values)):
        prev = prev + alpha * (values[i] - prev)
        out[i] = prev
    return out

def signal_from_macd(macd_values, period=9):
    indices = [i for i, value in enumerate(macd_values) if value is not None]
    if len(indices) < period:
        return [None] * len(macd_values)
    compact = [macd_values[i] for i in indices]
    compact_signal = ema_sma_seed(compact, period)
    out = [None] * len(macd_values)
    for pos, idx in enumerate(indices):
        out[idx] = compact_signal[pos]
    return out

def sign(value, eps=1e-12):
    if value is None:
        return "UNAVAILABLE"
    if value > eps:
        return "POSITIVE"
    if value < -eps:
        return "NEGATIVE"
    return "ZERO"

def macd_12_26_9(closes):
    if len(closes) < 34:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "line": None,
            "signal": None,
            "hist": None,
            "line_sign": "UNAVAILABLE",
            "hist_sign": "UNAVAILABLE",
            "crossover_state": "UNAVAILABLE",
        }

    fast = ema_sma_seed(closes, 12)
    slow = ema_sma_seed(closes, 26)
    line_series = [
        fast[i] - slow[i]
        if fast[i] is not None and slow[i] is not None
        else None
        for i in range(len(closes))
    ]
    signal_series = signal_from_macd(line_series, 9)
    idx = len(closes) - 1

    if line_series[idx] is None or signal_series[idx] is None:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "line": None,
            "signal": None,
            "hist": None,
            "line_sign": "UNAVAILABLE",
            "hist_sign": "UNAVAILABLE",
            "crossover_state": "UNAVAILABLE",
        }

    line = line_series[idx]
    signal_value = signal_series[idx]
    hist = line - signal_value

    return {
        "status": "OK",
        "line": round(line, 6),
        "signal": round(signal_value, 6),
        "hist": round(hist, 6),
        "line_sign": sign(line),
        "hist_sign": sign(hist),
        "crossover_state": sign(line - signal_value),
    }

def main():
    required = [
        HISTORY,
        HISTORY_META,
        INTEGRATED,
        INTEGRATED_META,
        INTEGRATED_CSV,
        PREPROD,
        PREPROD_META,
        DISPLAY,
        DISPLAY_META,
        MANIFEST,
    ]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    meta = read_json(HISTORY_META)
    integrated = read_json(INTEGRATED)
    integrated_meta = read_json(INTEGRATED_META)
    preprod = read_json(PREPROD)
    preprod_meta = read_json(PREPROD_META)
    display = read_json(DISPLAY)
    display_meta = read_json(DISPLAY_META)
    manifest = read_json(MANIFEST)

    if meta.get("status") != "READY":
        raise SystemExit("HISTORY_NOT_READY")
    if int(meta.get("distinct_market_dates") or 0) != 260:
        raise SystemExit("HISTORY_NOT_260_SESSIONS")

    if integrated.get("contract_version") != EXPECTED_OLD_INTEGRATED:
        raise SystemExit("OLD_INTEGRATED_CONTRACT_MISMATCH")
    if integrated_meta.get("contract_version") != EXPECTED_OLD_INTEGRATED:
        raise SystemExit("OLD_INTEGRATED_META_CONTRACT_MISMATCH")
    if integrated.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("INTEGRATED_NOT_READY_SOURCE_ONLY")
    if integrated.get("source_only") is not True:
        raise SystemExit("INTEGRATED_NOT_SOURCE_ONLY")
    if integrated.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("STANDALONE_ALREADY_ENABLED")
    if integrated.get("action_route_enabled") is not False:
        raise SystemExit("ROUTE_ALREADY_ENABLED")

    if integrated.get("pending_metrics") != [
        "rsi",
        "macd",
        "investment_score_100",
        "earnings_outlook_change",
        "confirmed_swing_low_stop",
    ]:
        raise SystemExit("OLD_PENDING_METRICS_MISMATCH")

    if preprod.get("activation_blockers") != [
        "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
        "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
        "RSI_MACD_FORMULAS_NOT_APPROVED",
        "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
        "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
        "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
        "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
    ]:
        raise SystemExit("OLD_BLOCKER_SET_MISMATCH")

    basis = integrated.get("basis_date")
    if not basis or meta.get("cache_max_date") != basis:
        raise SystemExit("BASIS_MISMATCH")
    if preprod.get("basis_date") != basis or display.get("basis_date") != basis:
        raise SystemExit("READINESS_BASIS_MISMATCH")

    route = manifest.get("command_route_contract") or {}
    two = route.get("two_table_release") or {}
    if two.get("effective_command_count") != 15:
        raise SystemExit("MANIFEST_COMMAND_COUNT_NOT_15")
    if two.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("MANIFEST_STANDALONE_ENABLED_UNEXPECTEDLY")

    target = [str(x).zfill(6) for x in meta.get("target_tickers", [])]
    if len(target) != 235 or len(set(target)) != 235:
        raise SystemExit("TARGET_UNIVERSE_NOT_235")

    history_rows = read_csv(HISTORY)
    by_ticker = defaultdict(list)
    identity = {}

    target_set = set(target)
    for row in history_rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        if ticker not in target_set:
            continue
        close = fnum(row.get("close"))
        ds = str(row.get("date") or "")
        if close is None or not ds or ds > basis:
            continue
        by_ticker[ticker].append((ds, close))
        identity[ticker] = {
            "name": str(row.get("name") or ""),
            "market": str(row.get("market") or ""),
        }

    for ticker in by_ticker:
        dedup = {}
        for ds, close in by_ticker[ticker]:
            dedup[ds] = close
        by_ticker[ticker] = sorted(dedup.items())

    if set(by_ticker) != target_set:
        raise SystemExit("HISTORY_TICKER_SET_MISMATCH")

    integrated_rows = {
        str(row.get("ticker") or "").zfill(6): row
        for row in integrated.get("rows") or []
    }
    if set(integrated_rows) != target_set:
        raise SystemExit("INTEGRATED_TICKER_SET_MISMATCH")

    technical_rows = []
    rsi_ready = 0
    macd_ready = 0

    for ticker in sorted(target):
        closes = [close for _, close in by_ticker[ticker]]
        rsi = rsi_wilder_14(closes)
        macd = macd_12_26_9(closes)

        if rsi["status"] == "OK":
            rsi_ready += 1
        if macd["status"] == "OK":
            macd_ready += 1

        technical_rows.append({
            "ticker": ticker,
            "name": identity[ticker]["name"],
            "market": identity[ticker]["market"],
            "basis_date": basis,
            "history_rows": len(closes),
            "rsi": rsi,
            "macd": macd,
        })

        row = integrated_rows[ticker]
        row["rsi"] = rsi
        row["macd"] = macd
        row["pending_metrics"] = {
            "investment_score_100": None,
            "earnings_outlook_change": None,
            "confirmed_swing_low_stop": None,
        }

    if rsi_ready != 235:
        raise SystemExit(f"RSI_READY_COUNT_MISMATCH:{rsi_ready}")
    if macd_ready != 235:
        raise SystemExit(f"MACD_READY_COUNT_MISMATCH:{macd_ready}")

    tech_payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "request_time_price_eligible": False,
        "basis_date": basis,
        "row_count": 235,
        "rsi_contract": RSI_CONTRACT,
        "macd_contract": MACD_CONTRACT,
        "rsi_ready_count": rsi_ready,
        "macd_ready_count": macd_ready,
        "evidence": {
            "v8719_run_id": 34790950755,
            "v8719_job_id": 103814938056,
            "v8719_artifact_id": 10328676199,
            "v8719_artifact_sha256": "7bcaf1c9bf5d8d2626b8cda02838032d316aa75714ab2ae71b06556c8d49c432",
            "rsi_zone_mismatch_between_candidates": 31,
            "macd_line_sign_mismatch_between_candidates": 1,
            "macd_hist_sign_mismatch_between_candidates": 1,
            "macd_crossover_state_mismatch_between_candidates": 1,
        },
        "authoritative_reference_contract": {
            "rsi": "Wilder RSI(14)",
            "macd": "EMA12-EMA26 with EMA9 signal",
            "ema_alpha": "2/(period+1)",
            "ema_seed": "SMA first period values",
            "macdfix_fixed_015_0075_selected": False,
        },
        "rows": technical_rows,
        "safety": {
            "confirmed_daily_close_only": True,
            "request_time_price_used": False,
            "production_table_changed": False,
            "worker_changed": False,
            "action_schema_changed": False,
            "new_command_defined": False,
            "route_enabled": False,
            "final_header_selected": False,
        },
    }
    write_json(OUT_TECH, tech_payload)

    tech_meta = {
        "contract_version": CONTRACT_VERSION,
        "status": "READY_SOURCE_ONLY",
        "basis_date": basis,
        "row_count": 235,
        "rsi_ready_count": 235,
        "macd_ready_count": 235,
        "rsi_contract": RSI_CONTRACT,
        "macd_contract": MACD_CONTRACT,
        "evidence": tech_payload["evidence"],
        "safety": tech_payload["safety"],
    }
    write_json(OUT_TECH_META, tech_meta)

    tech_log = [
        "V8720_RSI_MACD_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        "SOURCE_ROWS=235",
        "RSI_CONTRACT=WILDER_RSI_14_SMA_SEEDED",
        "RSI_READY=235",
        "MACD_CONTRACT=PERIOD_EMA_MACD_12_26_9_SMA_SEEDED",
        "MACD_READY=235",
        "MACDFIX_FIXED_015_0075_SELECTED=false",
        "REQUEST_TIME_PRICE_USED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "V8720_RSI_MACD_SOURCE_VALIDATION=PASS",
    ]
    OUT_TECH_LOG.write_text("\n".join(tech_log) + "\n", encoding="utf-8")

    # Update integrated JSON atomically with the new technical source.
    integrated["contract_version"] = INTEGRATED_CONTRACT
    integrated["script_version"] = SCRIPT_VERSION
    integrated["rsi_macd_contract_version"] = CONTRACT_VERSION
    integrated["rsi_contract"] = RSI_CONTRACT
    integrated["macd_contract"] = MACD_CONTRACT
    integrated["rsi_ready_count"] = 235
    integrated["macd_ready_count"] = 235
    integrated["pending_metrics"] = PENDING_METRICS
    integrated["rows"] = [integrated_rows[t] for t in sorted(integrated_rows)]
    integrated["source_lineage"] = dict(integrated.get("source_lineage") or {})
    integrated["source_lineage"]["rsi_macd_contract_version"] = CONTRACT_VERSION
    integrated["safety"] = dict(integrated.get("safety") or {})
    integrated["safety"].update({
        "rsi_calculated": True,
        "macd_calculated": True,
        "production_table_changed": False,
        "worker_changed": False,
        "request_time_price_substitution": False,
        "new_command_defined": False,
        "action_route_enabled": False,
        "standalone_swing_table_enabled": False,
    })
    write_json(INTEGRATED, integrated)

    integrated_meta["contract_version"] = INTEGRATED_CONTRACT
    integrated_meta["script_version"] = SCRIPT_VERSION
    integrated_meta["rsi_macd_contract_version"] = CONTRACT_VERSION
    integrated_meta["rsi_contract"] = RSI_CONTRACT
    integrated_meta["macd_contract"] = MACD_CONTRACT
    integrated_meta["rsi_ready_count"] = 235
    integrated_meta["macd_ready_count"] = 235
    integrated_meta["pending_metrics"] = PENDING_METRICS
    integrated_meta["source_lineage"] = dict(integrated_meta.get("source_lineage") or {})
    integrated_meta["source_lineage"]["rsi_macd_contract_version"] = CONTRACT_VERSION
    integrated_meta["safety"] = dict(integrated_meta.get("safety") or {})
    integrated_meta["safety"].update({
        "rsi_calculated": True,
        "macd_calculated": True,
        "production_table_changed": False,
        "worker_changed": False,
        "request_time_price_substitution": False,
        "new_command_defined": False,
        "action_route_enabled": False,
        "standalone_swing_table_enabled": False,
    })
    write_json(INTEGRATED_META, integrated_meta)

    # Update integrated CSV existing RSI/MACD columns.
    csv_rows = read_csv(INTEGRATED_CSV)
    if len(csv_rows) != 235:
        raise SystemExit(f"INTEGRATED_CSV_ROW_COUNT_MISMATCH:{len(csv_rows)}")

    fieldnames = list(csv_rows[0].keys())
    if "rsi" not in fieldnames or "macd" not in fieldnames:
        raise SystemExit("INTEGRATED_CSV_RSI_MACD_COLUMNS_MISSING")

    tech_by_ticker = {
        row["ticker"]: row for row in technical_rows
    }

    for row in csv_rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        tech = tech_by_ticker[ticker]
        row["rsi"] = tech["rsi"]["value"]
        row["macd"] = json.dumps(
            {
                "line": tech["macd"]["line"],
                "signal": tech["macd"]["signal"],
                "hist": tech["macd"]["hist"],
                "status": tech["macd"]["status"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    with INTEGRATED_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(csv_rows)

    integrated_log = [
        "V8720_INTEGRATED_SWING_SOURCE_STATUS=READY_SOURCE_ONLY",
        f"BASIS_DATE={basis}",
        "INTEGRATED_ROWS=235",
        "RSI_READY=235",
        "MACD_READY=235",
        "PENDING_METRICS=investment_score_100,earnings_outlook_change,confirmed_swing_low_stop",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "NEW_COMMAND_DEFINED=false",
        "V8720_INTEGRATED_SWING_SOURCE_VALIDATION=PASS",
    ]
    OUT_INTEGRATED_LOG.write_text(
        "\n".join(integrated_log) + "\n", encoding="utf-8"
    )

    # Synchronize readiness layers: blocker 7 -> 6, pending 5 -> 3.
    resolved = list(preprod.get("resolved_activation_blockers") or [])
    if "RSI_MACD_FORMULAS_NOT_APPROVED" not in resolved:
        resolved.append("RSI_MACD_FORMULAS_NOT_APPROVED")

    preprod["contract_version"] = READINESS_CONTRACT
    preprod["script_version"] = SCRIPT_VERSION
    preprod["rsi_macd_contract_frozen"] = True
    preprod["rsi_contract"] = RSI_CONTRACT
    preprod["macd_contract"] = MACD_CONTRACT
    preprod["pending_metrics"] = PENDING_METRICS
    preprod["activation_blockers"] = REMAINING_BLOCKERS
    preprod["resolved_activation_blockers"] = resolved
    preprod["source_contract_version"] = INTEGRATED_CONTRACT
    preprod["source_lineage"] = dict(preprod.get("source_lineage") or {})
    preprod["source_lineage"]["rsi_macd_contract_version"] = CONTRACT_VERSION
    preprod["snapshot_counts"] = dict(preprod.get("snapshot_counts") or {})
    preprod["snapshot_counts"]["rsi_ready"] = 235
    preprod["snapshot_counts"]["macd_ready"] = 235
    preprod["production_activation_allowed"] = False
    preprod["standalone_swing_table_enabled"] = False
    preprod["action_route_enabled"] = False
    preprod["standalone_command_defined"] = False
    preprod["final_header_selected"] = False
    preprod["safety"] = dict(preprod.get("safety") or {})
    preprod["safety"].update({
        "production_table_changed": False,
        "worker_changed": False,
        "action_schema_changed": False,
        "request_time_price_substitution": False,
        "new_command_invented": False,
        "new_route_invented": False,
        "final_header_invented": False,
        "pending_metric_autofill": False,
    })
    write_json(PREPROD, preprod)

    preprod_meta["contract_version"] = READINESS_CONTRACT
    preprod_meta["rsi_macd_contract_frozen"] = True
    preprod_meta["rsi_contract"] = RSI_CONTRACT
    preprod_meta["macd_contract"] = MACD_CONTRACT
    preprod_meta["activation_blocker_count"] = 6
    preprod_meta["activation_blockers"] = REMAINING_BLOCKERS
    preprod_meta["resolved_activation_blockers"] = resolved
    preprod_meta["pending_metrics"] = PENDING_METRICS
    preprod_meta["source_contract_version"] = INTEGRATED_CONTRACT
    preprod_meta["source_lineage"] = dict(preprod_meta.get("source_lineage") or {})
    preprod_meta["source_lineage"]["rsi_macd_contract_version"] = CONTRACT_VERSION
    preprod_meta["snapshot_counts"] = dict(preprod_meta.get("snapshot_counts") or {})
    preprod_meta["snapshot_counts"]["rsi_ready"] = 235
    preprod_meta["snapshot_counts"]["macd_ready"] = 235
    preprod_meta["production_activation_allowed"] = False
    write_json(PREPROD_META, preprod_meta)

    display["contract_version"] = READINESS_CONTRACT
    display["script_version"] = SCRIPT_VERSION
    display["rsi_macd_contract_frozen"] = True
    display["rsi_contract"] = RSI_CONTRACT
    display["macd_contract"] = MACD_CONTRACT
    display["pending_metrics"] = PENDING_METRICS
    display["remaining_activation_blockers"] = REMAINING_BLOCKERS
    display["resolved_activation_blockers"] = resolved
    display["source_contracts"] = dict(display.get("source_contracts") or {})
    display["source_contracts"]["integrated_source"] = INTEGRATED_CONTRACT
    display["source_contracts"]["rsi_macd_source"] = CONTRACT_VERSION
    display["production_activation_allowed"] = False
    display["standalone_swing_table_enabled"] = False
    display["action_route_enabled"] = False
    display["standalone_command_defined"] = False
    display["final_header_selected"] = False
    write_json(DISPLAY, display)

    display_meta["contract_version"] = READINESS_CONTRACT
    display_meta["rsi_macd_contract_frozen"] = True
    display_meta["rsi_contract"] = RSI_CONTRACT
    display_meta["macd_contract"] = MACD_CONTRACT
    display_meta["pending_metrics"] = PENDING_METRICS
    display_meta["remaining_activation_blocker_count"] = 6
    display_meta["remaining_activation_blockers"] = REMAINING_BLOCKERS
    display_meta["resolved_activation_blockers"] = resolved
    display_meta["source_contract_version"] = INTEGRATED_CONTRACT
    display_meta["production_activation_allowed"] = False
    write_json(DISPLAY_META, display_meta)

    preprod_log = [
        "V8720_PREPRODUCTION_READINESS=FROZEN_PREPRODUCTION_READY",
        "RSI_MACD_CONTRACT_FROZEN=true",
        "RSI_READY=235",
        "MACD_READY=235",
        "ACTIVATION_BLOCKER_COUNT=6",
        "PENDING_METRIC_COUNT=3",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "V8720_PREPRODUCTION_READINESS_VALIDATION=PASS",
    ]
    OUT_PREPROD_LOG.write_text(
        "\n".join(preprod_log) + "\n", encoding="utf-8"
    )

    display_log = [
        "V8720_DISPLAY_MERGE_READINESS=FROZEN_PREPRODUCTION_READY",
        "RSI_MACD_CONTRACT_FROZEN=true",
        "REMAINING_ACTIVATION_BLOCKER_COUNT=6",
        "PENDING_METRIC_COUNT=3",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "V8720_DISPLAY_MERGE_READINESS_VALIDATION=PASS",
    ]
    OUT_DISPLAY_LOG.write_text(
        "\n".join(display_log) + "\n", encoding="utf-8"
    )

    print("\n".join(tech_log))
    print("\n".join(integrated_log))
    print("\n".join(preprod_log))
    print("\n".join(display_log))

if __name__ == "__main__":
    main()
