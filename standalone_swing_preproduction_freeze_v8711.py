#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_preproduction_freeze_v8711.py v1.0.2-manifest-structural-guard"
CONTRACT_VERSION = "2026-09-13-v8.7.11-standalone-swing-preproduction-freeze"

INTEGRATED = Path("latest/standalone_swing_integrated_latest.json")
INTEGRATED_META = Path("latest/standalone_swing_integrated_meta_latest.json")
MANIFEST = Path("api/manifest.json")
SCHEMA = Path("docs/custom_gpt_action_schema.yaml")
WORKER = Path("worker/krx-live-price-worker.js")
METRICS = Path("stock_table_metrics_v850.py")

OUT_JSON = Path("latest/standalone_swing_preproduction_readiness_latest.json")
OUT_META = Path("latest/standalone_swing_preproduction_readiness_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_preproduction_readiness_run_log_latest.txt")

WORKER_BASE = "https://krx-live-price-ksh.diaconos.workers.dev"
PRICE_OPERATION_ID = "getRequestTimePrices"

PENDING = [
    "return_1w",
    "return_ytd",
    "return_52w",
    "rsi",
    "macd",
    "investment_score_100",
    "earnings_outlook_change",
    "confirmed_swing_low_stop",
]

ACTIVATION_BLOCKERS = [
    "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
    "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
    "REQUEST_TIME_DISPLAY_MERGE_CONTRACT_NOT_FROZEN_FOR_STANDALONE",
    "1W_YTD_52W_FORMULAS_NOT_APPROVED",
    "RSI_MACD_FORMULAS_NOT_APPROVED",
    "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
    "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
    "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
    "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def write_json(path: Path, obj):
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

def main():
    required = [INTEGRATED, INTEGRATED_META, MANIFEST, SCHEMA, WORKER, METRICS]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    src = read_json(INTEGRATED)
    meta = read_json(INTEGRATED_META)

    if src.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("INTEGRATED_SOURCE_NOT_READY")
    if meta.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("INTEGRATED_META_NOT_READY")
    if src.get("source_only") is not True or meta.get("source_only") is not True:
        raise SystemExit("INTEGRATED_NOT_SOURCE_ONLY")
    if src.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("STANDALONE_TABLE_ALREADY_ENABLED")
    if src.get("action_route_enabled") is not False:
        raise SystemExit("STANDALONE_ROUTE_ALREADY_ENABLED")
    if src.get("request_time_price_eligible") is not False:
        raise SystemExit("SOURCE_REQUEST_PRICE_ELIGIBILITY_UNEXPECTED")

    basis = src.get("basis_date")
    if not basis or meta.get("basis_date") != basis:
        raise SystemExit("BASIS_MISMATCH")

    rows = src.get("rows") or []
    if len(rows) != int(src.get("row_count") or 0):
        raise SystemExit("ROW_COUNT_MISMATCH")
    if len(rows) != int(meta.get("row_count") or 0):
        raise SystemExit("META_ROW_COUNT_MISMATCH")

    if set(src.get("pending_metrics") or []) != set(PENDING):
        raise SystemExit("TOP_LEVEL_PENDING_SET_MISMATCH")
    if set(meta.get("pending_metrics") or []) != set(PENDING):
        raise SystemExit("META_PENDING_SET_MISMATCH")

    counts = {
        "row_count": len(rows),
        "kospi": 0,
        "kosdaq": 0,
        "return_1m_ready": 0,
        "return_3m_ready": 0,
        "return_6m_ready": 0,
        "return_6m_missing": 0,
        "swing_ready": 0,
        "ma_full_ready": 0,
        "ma_gap": 0,
        "atr14_ready": 0,
        "atr14_gap": 0,
        "range20_ready": 0,
        "range20_gap": 0,
        "rs_kospi_ready": 0,
        "rs_sector_ready": 0,
        "rs_sector_null": 0,
        "confirmed_stop_ready": 0,
        "pending_nonnull_violations": 0,
    }

    for row in rows:
        market = row.get("market")
        if market == "KOSPI":
            counts["kospi"] += 1
        elif market == "KOSDAQ":
            counts["kosdaq"] += 1
        else:
            raise SystemExit("UNKNOWN_MARKET:" + str(market))

        perf = row.get("price_performance") or {}
        if (perf.get("1m") or {}).get("status") == "OK":
            counts["return_1m_ready"] += 1
        if (perf.get("3m") or {}).get("status") == "OK":
            counts["return_3m_ready"] += 1
        if (perf.get("6m") or {}).get("status") == "OK":
            counts["return_6m_ready"] += 1
        else:
            counts["return_6m_missing"] += 1

        swing = row.get("swing") or {}
        if swing.get("phase") and swing.get("phase_ko"):
            counts["swing_ready"] += 1

        ma = row.get("ma") or {}
        ma_ok = all(
            (ma.get(str(p)) or {}).get("value") is not None
            and (ma.get(str(p)) or {}).get("direction") is not None
            for p in (5, 20, 60, 120)
        )
        counts["ma_full_ready" if ma_ok else "ma_gap"] += 1

        atr = row.get("atr14") or {}
        counts["atr14_ready" if atr.get("pct") is not None else "atr14_gap"] += 1

        range20 = row.get("avg_daily_range_20_pct")
        counts["range20_ready" if range20 is not None else "range20_gap"] += 1

        rsk = row.get("rs_kospi_pp") or {}
        if rsk.get("1") is not None and rsk.get("3") is not None:
            counts["rs_kospi_ready"] += 1

        rss = row.get("rs_sector_pp") or {}
        if rss.get("1") is not None and rss.get("3") is not None:
            counts["rs_sector_ready"] += 1
        else:
            counts["rs_sector_null"] += 1

        trailing = row.get("trailing_reference") or {}
        if trailing.get("confirmed_swing_low_stop") is not None:
            counts["confirmed_stop_ready"] += 1

        pending = row.get("pending_metrics") or {}
        if set(pending) != set(PENDING):
            raise SystemExit("ROW_PENDING_SET_MISMATCH:" + str(row.get("ticker")))
        if any(v is not None for v in pending.values()):
            counts["pending_nonnull_violations"] += 1

        if perf.get("1w") is not None or perf.get("ytd") is not None or perf.get("52w") is not None:
            counts["pending_nonnull_violations"] += 1

    if counts["kospi"] != int((src.get("market_counts") or {}).get("KOSPI") or 0):
        raise SystemExit("KOSPI_COUNT_MISMATCH")
    if counts["kosdaq"] != int((src.get("market_counts") or {}).get("KOSDAQ") or 0):
        raise SystemExit("KOSDAQ_COUNT_MISMATCH")
    if counts["return_6m_ready"] != int(src.get("return_6m_ready_count") or 0):
        raise SystemExit("RETURN_6M_READY_MISMATCH")
    if counts["return_6m_missing"] != int(src.get("return_6m_missing_count") or 0):
        raise SystemExit("RETURN_6M_MISSING_MISMATCH")
    if counts["rs_sector_ready"] != int(src.get("kospi_sector_rs_ready_count") or 0):
        raise SystemExit("SECTOR_RS_READY_MISMATCH")
    if counts["rs_sector_null"] != int(src.get("kosdaq_sector_rs_null_count") or 0):
        raise SystemExit("SECTOR_RS_NULL_MISMATCH")
    if counts["confirmed_stop_ready"] != 0:
        raise SystemExit("CONFIRMED_STOP_SHOULD_REMAIN_NULL")
    if counts["pending_nonnull_violations"] != 0:
        raise SystemExit("PENDING_METRIC_NON_NULL_VIOLATION")

    # Freeze current validated snapshot. Any unexpected drift must cause a review.
    expected_snapshot = {
        "row_count": 235,
        "kospi": 210,
        "kosdaq": 25,
        "return_1m_ready": 235,
        "return_3m_ready": 235,
        "return_6m_ready": 234,
        "return_6m_missing": 1,
        "swing_ready": 235,
        "ma_full_ready": 234,
        "ma_gap": 1,
        "atr14_ready": 209,
        "atr14_gap": 26,
        "range20_ready": 225,
        "range20_gap": 10,
        "rs_kospi_ready": 235,
        "rs_sector_ready": 210,
        "rs_sector_null": 25,
        "confirmed_stop_ready": 0,
        "pending_nonnull_violations": 0,
    }
    if counts != expected_snapshot:
        raise SystemExit(
            "PREPRODUCTION_SNAPSHOT_DRIFT:"
            + json.dumps({"expected": expected_snapshot, "actual": counts}, ensure_ascii=False)
        )

    manifest = read_json(MANIFEST)
    schema_text = SCHEMA.read_text(encoding="utf-8-sig")

    if manifest.get("status") != "READY":
        raise SystemExit("API_MANIFEST_NOT_READY")
    if manifest.get("api_sync_ok") is not True:
        raise SystemExit("API_MANIFEST_SYNC_NOT_OK")
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise SystemExit("API_MANIFEST_NOT_SAFE_TO_ANALYZE")

    route = manifest.get("command_route_contract") or {}
    if route.get("command_count") != 13:
        raise SystemExit("MANIFEST_CORE_COMMAND_COUNT_MISMATCH")
    if route.get("ready_count") != 13:
        raise SystemExit("MANIFEST_CORE_READY_COUNT_MISMATCH")
    if route.get("action_domain_count") != 1:
        raise SystemExit("MANIFEST_ACTION_DOMAIN_COUNT_MISMATCH")
    if route.get("single_action_domain") != WORKER_BASE:
        raise SystemExit("MANIFEST_ACTION_DOMAIN_MISMATCH")
    if route.get("raw_github_action_required") is not False:
        raise SystemExit("MANIFEST_RAW_GITHUB_ACTION_UNEXPECTED")

    two = route.get("two_table_release") or {}
    if two.get("core_command_count") != 13:
        raise SystemExit("MANIFEST_TWO_TABLE_CORE_COMMAND_COUNT_MISMATCH")
    if two.get("additional_command_count") != 2:
        raise SystemExit("MANIFEST_TWO_TABLE_ADDITIONAL_COMMAND_COUNT_MISMATCH")
    if two.get("effective_command_count") != 15:
        raise SystemExit("MANIFEST_EFFECTIVE_COMMAND_COUNT_MISMATCH")
    if two.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("MANIFEST_STANDALONE_SWING_MUST_REMAIN_DISABLED")

    price_policy = manifest.get("request_time_price_policy") or {}
    if price_policy.get("enabled") is not True:
        raise SystemExit("MANIFEST_REQUEST_PRICE_POLICY_DISABLED")
    if price_policy.get("action_operation_id") != PRICE_OPERATION_ID:
        raise SystemExit("MANIFEST_PRICE_OPERATION_ID_MISMATCH")
    if price_policy.get("api_base_url") != WORKER_BASE:
        raise SystemExit("MANIFEST_PRICE_API_BASE_URL_MISMATCH")
    if price_policy.get("initial_batch_size") != 10:
        raise SystemExit("MANIFEST_INITIAL_BATCH_SIZE_MISMATCH")
    if price_policy.get("max_batch_size") != 10:
        raise SystemExit("MANIFEST_MAX_BATCH_SIZE_MISMATCH")
    if price_policy.get("retry_failed_quotes") is not True:
        raise SystemExit("MANIFEST_RETRY_FAILED_QUOTES_DISABLED")
    if price_policy.get("retry_only_failed") is not True:
        raise SystemExit("MANIFEST_RETRY_ONLY_FAILED_DISABLED")
    if price_policy.get("retry_rounds") != 2:
        raise SystemExit("MANIFEST_RETRY_ROUNDS_MISMATCH")
    if price_policy.get("retry_batch_sizes") != [5, 2]:
        raise SystemExit("MANIFEST_RETRY_BATCH_SIZES_MISMATCH")
    if price_policy.get("failed_quote_behavior") != "after_all_retries_keep_row_mark_white_circle_do_not_fake_price":
        raise SystemExit("MANIFEST_FAILED_QUOTE_BEHAVIOR_MISMATCH")

    # The Action schema only needs to expose the validated existing operation.
    if f"operationId: {PRICE_OPERATION_ID}" not in schema_text:
        raise SystemExit("PRICE_OPERATION_ID_MISSING_FROM_ACTION_SCHEMA")

    evidence = {
        "v879_data_quality_gate": {
            "run_id": 34686320783,
            "artifact_id": 10295129036,
            "artifact_sha256": "c520f51ab28a5d06e9453b53b1b6020215d6983d0bde07495d9e5ccaaaaa8ad3",
            "result": "PASS",
            "key_findings": {
                "unexplained_ma_gap_count": 0,
                "unexpected_return_6m_gap_count": 0,
                "unexplained_atr_gap_count": 0,
                "positive_ohlc_relation_error_day_count": 0,
                "other_invalid_ohlc_day_count": 0,
                "zero_no_trade_invalid_rows": 532,
            },
        },
        "v8710_request_time_price_path": {
            "run_id": 34718370007,
            "artifact_id": 10305686277,
            "artifact_sha256": "4dd845a83686430496aac4c07bccef29e7574428537efaa39796435c22c006c4",
            "result": "PASS",
            "source_rows": 235,
            "success_count": 235,
            "failed_count": 0,
            "coverage_pct": 100.0,
            "static_price_substitution_count": 0,
            "invalid_success_count": 0,
            "worker_build": "1.4.1-two-table-dual-schema",
        },
    }

    readiness = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "preproduction_contract_frozen": True,
        "data_layer_ready_for_preproduction": True,
        "request_time_price_path_ready_for_preproduction": True,
        "production_activation_allowed": False,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "standalone_command_defined": False,
        "final_header_selected": False,
        "basis_date": basis,
        "snapshot_counts": counts,
        "accepted_missing_policy": {
            "return_6m": "자료 미제공 when calendar history is insufficient; no imputation",
            "ma": "자료 미제공 when required history is insufficient; no fabricated MA",
            "atr14": "자료 미제공 when official lookback contains zero/no-trade OHLC rows; no imputation",
            "avg_daily_range_20_pct": "자료 미제공 when recent official OHLC contains zero/no-trade rows",
            "kosdaq_sector_rs": "자료 미제공 under current KOSPI-only official sector-RS contract",
            "pending_metrics": "자료 미제공 until separately approved contracts exist",
        },
        "request_time_price_contract": {
            "worker_base_url": WORKER_BASE,
            "operation_id": PRICE_OPERATION_ID,
            "initial_batch_max": 10,
            "retry_failed_batch_max": 5,
            "final_retry_failed_batch_max": 2,
            "final_failure_display": "⚪ 현재가 확인 실패",
            "static_price_fallback_allowed": False,
            "official_close_is_reference_only_not_request_time_price": True,
            "new_price_action_required": False,
            "must_revalidate_at_activation": True,
            "manifest_build_id": manifest.get("build_id"),
            "manifest_route_contract_version": route.get("contract_version"),
            "manifest_effective_command_count": two.get("effective_command_count"),
            "manifest_standalone_swing_table_enabled": two.get("standalone_swing_table_enabled"),
        },
        "pending_metrics": PENDING,
        "activation_blockers": ACTIVATION_BLOCKERS,
        "evidence": evidence,
        "source_contract_version": src.get("contract_version"),
        "source_lineage": src.get("source_lineage"),
        "source_sha256": {
            str(p): sha256(p)
            for p in required
        },
        "safety": {
            "production_table_changed": False,
            "worker_changed": False,
            "action_schema_changed": False,
            "metric_formula_changed": False,
            "request_time_price_substitution": False,
            "new_command_invented": False,
            "new_route_invented": False,
            "final_header_invented": False,
            "pending_metric_autofill": False,
        },
    }
    write_json(OUT_JSON, readiness)

    meta_out = {
        "contract_version": CONTRACT_VERSION,
        "status": readiness["status"],
        "preproduction_contract_frozen": True,
        "production_activation_allowed": False,
        "basis_date": basis,
        "row_count": counts["row_count"],
        "snapshot_counts": counts,
        "price_operation_id": PRICE_OPERATION_ID,
        "price_retry_policy": [10, 5, 2],
        "activation_blocker_count": len(ACTIVATION_BLOCKERS),
        "activation_blockers": ACTIVATION_BLOCKERS,
        "pending_metrics": PENDING,
        "evidence_run_ids": [34686320783, 34718370007],
        "source_contract_version": src.get("contract_version"),
        "source_sha256": readiness["source_sha256"],
        "safety": readiness["safety"],
    }
    write_json(OUT_META, meta_out)

    lines = [
        "V8711_PREPRODUCTION_FREEZE_STATUS=FROZEN_PREPRODUCTION_READY",
        f"BASIS_DATE={basis}",
        f"ROW_COUNT={counts['row_count']}",
        f"KOSPI_ROWS={counts['kospi']}",
        f"KOSDAQ_ROWS={counts['kosdaq']}",
        f"RETURN_6M_READY={counts['return_6m_ready']}",
        f"MA_FULL_READY={counts['ma_full_ready']}",
        f"ATR14_READY={counts['atr14_ready']}",
        f"RANGE20_READY={counts['range20_ready']}",
        f"KOSPI_SECTOR_RS_READY={counts['rs_sector_ready']}",
        f"KOSDAQ_SECTOR_RS_NULL={counts['rs_sector_null']}",
        "V879_DATA_QUALITY_EVIDENCE=PASS",
        "V8710_REQUEST_PRICE_EVIDENCE=PASS",
        "REQUEST_PRICE_OPERATION_ID=getRequestTimePrices",
        "REQUEST_PRICE_RETRY_POLICY=10-5-2",
        "MANIFEST_CORE_COMMAND_COUNT=13",
        "MANIFEST_ADDITIONAL_COMMAND_COUNT=2",
        "MANIFEST_EFFECTIVE_COMMAND_COUNT=15",
        "MANIFEST_STANDALONE_SWING_TABLE_ENABLED=false",
        "STATIC_PRICE_FALLBACK_ALLOWED=false",
        "NEW_PRICE_ACTION_REQUIRED=false",
        "PREPRODUCTION_CONTRACT_FROZEN=true",
        "DATA_LAYER_READY_FOR_PREPRODUCTION=true",
        "REQUEST_TIME_PRICE_PATH_READY_FOR_PREPRODUCTION=true",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        f"ACTIVATION_BLOCKER_COUNT={len(ACTIVATION_BLOCKERS)}",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_SOURCE_CHANGED=false",
        "ACTION_SCHEMA_CHANGED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "NEW_COMMAND_INVENTED=false",
        "NEW_ROUTE_INVENTED=false",
        "FINAL_HEADER_INVENTED=false",
        "PENDING_METRIC_AUTOFILL=false",
        "V8711_PREPRODUCTION_CONTRACT_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
