#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_display_merge_freeze_v8713.py v1.0.0"
CONTRACT_VERSION = "2026-09-13-v8.7.13-standalone-swing-display-merge-freeze"

SOURCE = Path("latest/standalone_swing_integrated_latest.json")
PREPROD = Path("latest/standalone_swing_preproduction_readiness_latest.json")
MANIFEST = Path("api/manifest.json")
SCHEMA = Path("docs/custom_gpt_action_schema.yaml")
WORKER = Path("worker/krx-live-price-worker.js")
METRICS = Path("stock_table_metrics_v850.py")

OUT_JSON = Path("latest/standalone_swing_display_merge_readiness_latest.json")
OUT_META = Path("latest/standalone_swing_display_merge_readiness_meta_latest.json")
OUT_LOG = Path("latest/standalone_swing_display_merge_readiness_run_log_latest.txt")

WORKER_BASE = "https://krx-live-price-ksh.diaconos.workers.dev"
PRICE_OPERATION_ID = "getRequestTimePrices"

REMOVED_BLOCKER = "REQUEST_TIME_DISPLAY_MERGE_CONTRACT_NOT_FROZEN_FOR_STANDALONE"

EXPECTED_REMAINING_BLOCKERS = [
    "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
    "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
    "1W_YTD_52W_FORMULAS_NOT_APPROVED",
    "RSI_MACD_FORMULAS_NOT_APPROVED",
    "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
    "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
    "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
    "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

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

def main():
    required = [SOURCE, PREPROD, MANIFEST, SCHEMA, WORKER, METRICS]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    source = read_json(SOURCE)
    preprod = read_json(PREPROD)
    manifest = read_json(MANIFEST)

    if source.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("INTEGRATED_SOURCE_NOT_READY")
    if preprod.get("status") != "FROZEN_PREPRODUCTION_READY":
        raise SystemExit("PREPRODUCTION_NOT_FROZEN")
    if preprod.get("preproduction_contract_frozen") is not True:
        raise SystemExit("PREPRODUCTION_FREEZE_FLAG_MISSING")

    # No premature activation.
    for obj, name in ((source, "SOURCE"), (preprod, "PREPROD")):
        if obj.get("standalone_swing_table_enabled") is not False:
            raise SystemExit(name + "_STANDALONE_TABLE_ALREADY_ENABLED")
        if obj.get("action_route_enabled") is not False:
            raise SystemExit(name + "_ROUTE_ALREADY_ENABLED")
    if preprod.get("production_activation_allowed") is not False:
        raise SystemExit("PRODUCTION_ALREADY_ALLOWED")
    if preprod.get("standalone_command_defined") is not False:
        raise SystemExit("COMMAND_ALREADY_DEFINED")
    if preprod.get("final_header_selected") is not False:
        raise SystemExit("FINAL_HEADER_ALREADY_SELECTED")

    # Structural live-operating contract from manifest; no prose matching.
    if manifest.get("status") != "READY":
        raise SystemExit("MANIFEST_NOT_READY")
    if manifest.get("api_sync_ok") is not True:
        raise SystemExit("MANIFEST_SYNC_NOT_OK")

    route = manifest.get("command_route_contract") or {}
    two = route.get("two_table_release") or {}
    if two.get("effective_command_count") != 15:
        raise SystemExit("EFFECTIVE_COMMAND_COUNT_MISMATCH")
    if two.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("MANIFEST_STANDALONE_MUST_REMAIN_DISABLED")
    if route.get("single_action_domain") != WORKER_BASE:
        raise SystemExit("SINGLE_ACTION_DOMAIN_MISMATCH")

    price = manifest.get("request_time_price_policy") or {}
    if price.get("enabled") is not True:
        raise SystemExit("REQUEST_PRICE_POLICY_DISABLED")
    if price.get("action_operation_id") != PRICE_OPERATION_ID:
        raise SystemExit("REQUEST_PRICE_OPERATION_MISMATCH")
    if price.get("api_base_url") != WORKER_BASE:
        raise SystemExit("REQUEST_PRICE_DOMAIN_MISMATCH")
    if price.get("initial_batch_size") != 10:
        raise SystemExit("REQUEST_PRICE_INITIAL_BATCH_MISMATCH")
    if price.get("retry_only_failed") is not True:
        raise SystemExit("REQUEST_PRICE_RETRY_SCOPE_MISMATCH")
    if price.get("retry_batch_sizes") != [5, 2]:
        raise SystemExit("REQUEST_PRICE_RETRY_BATCH_MISMATCH")
    if price.get("failed_quote_behavior") != "after_all_retries_keep_row_mark_white_circle_do_not_fake_price":
        raise SystemExit("FAILED_QUOTE_BEHAVIOR_MISMATCH")

    schema_text = SCHEMA.read_text(encoding="utf-8-sig")
    if f"operationId: {PRICE_OPERATION_ID}" not in schema_text:
        raise SystemExit("PRICE_OPERATION_MISSING_FROM_ACTION_SCHEMA")

    rows = source.get("rows") or []
    if len(rows) != int(source.get("row_count") or 0):
        raise SystemExit("SOURCE_ROW_COUNT_MISMATCH")
    if len(rows) != 235:
        raise SystemExit("SOURCE_ROW_COUNT_SNAPSHOT_DRIFT")

    range_ready = 0
    range_unavailable = 0
    range_unavailable_rows = []
    pending_violation_count = 0

    immutable_required = (
        "price_performance",
        "swing",
        "ma",
        "run",
        "streak",
        "rs_kospi_pp",
        "sector_benchmark",
        "rs_sector_pp",
        "atr14",
        "avg_daily_range_20_pct",
        "range_3m",
        "trailing_reference",
        "pending_metrics",
    )

    for row in rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        if any(field not in row for field in immutable_required):
            raise SystemExit("INTEGRATED_FIELD_MISSING:" + ticker)

        r3 = row.get("range_3m") or {}
        low = r3.get("low")
        high = r3.get("high")
        if (
            isinstance(low, (int, float))
            and isinstance(high, (int, float))
            and high > low
        ):
            range_ready += 1
        else:
            range_unavailable += 1
            range_unavailable_rows.append({
                "ticker": ticker,
                "name": row.get("name"),
                "market": row.get("market"),
                "low": low,
                "high": high,
                "display": "자료 미제공",
            })

        pending = row.get("pending_metrics") or {}
        if any(v is not None for v in pending.values()):
            pending_violation_count += 1

    # V8.7.12 deterministic source-side capacity observed on the same integrated source.
    if range_ready != 213 or range_unavailable != 22:
        raise SystemExit(
            "RANGE3M_CAPACITY_SNAPSHOT_DRIFT:"
            + json.dumps(
                {"ready": range_ready, "unavailable": range_unavailable},
                ensure_ascii=False,
            )
        )
    if pending_violation_count != 0:
        raise SystemExit("PENDING_METRIC_NON_NULL_VIOLATION")

    old_blockers = list(preprod.get("activation_blockers") or [])
    if REMOVED_BLOCKER not in old_blockers:
        raise SystemExit("EXPECTED_DISPLAY_MERGE_BLOCKER_NOT_PRESENT")
    remaining = [b for b in old_blockers if b != REMOVED_BLOCKER]
    if remaining != EXPECTED_REMAINING_BLOCKERS:
        raise SystemExit(
            "REMAINING_BLOCKER_SET_MISMATCH:"
            + json.dumps({"actual": remaining}, ensure_ascii=False)
        )

    evidence = {
        "v8712_request_time_display_merge_preview": {
            "run_id": 34741483044,
            "job_id": 103681809815,
            "artifact_id": 10312955901,
            "artifact_sha256": "ac6667c33c41bba84f90b692ce371cada7841bd63f6fd175294919139c16e597",
            "result": "PASS",
            "run_head_sha": "926cf65c6284ba69115a5861bf5aa2303f85f516",
            "findings": {
                "source_rows": 235,
                "quote_success": 235,
                "quote_failed": 0,
                "position_ready": 213,
                "position_unavailable": 22,
                "position_below_range": 0,
                "position_inside_range": 213,
                "position_above_range": 0,
                "static_fallback_count": 0,
                "confirmed_metric_mutation_count": 0,
                "position_pct_clamped": False,
                "overlay_only": True,
            },
        }
    }

    contract = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "display_merge_contract_frozen": True,
        "production_activation_allowed": False,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "standalone_command_defined": False,
        "final_header_selected": False,
        "final_position_label_selected": False,
        "recommendation_contract_selected": False,
        "price_zone_contract_selected": False,
        "basis_date": source.get("basis_date"),
        "source_row_count": len(rows),
        "range3m_position_capacity": {
            "ready": range_ready,
            "unavailable": range_unavailable,
            "unavailable_display": "자료 미제공",
            "unavailable_reason_contract": "confirmed 3M low/high missing or non-usable; do not fabricate range",
            "unavailable_rows": range_unavailable_rows,
        },
        "request_time_display_merge_contract": {
            "price_source_operation_id": PRICE_OPERATION_ID,
            "worker_base_url": WORKER_BASE,
            "retry_policy": [10, 5, 2],
            "retry_only_failed": True,
            "final_failure_display": "⚪ 현재가 확인 실패",
            "request_time_price_is_overlay_only": True,
            "official_close_is_reference_only": True,
            "static_price_fallback_allowed": False,
            "position_range_source": "confirmed daily 3M low/high",
            "position_formula": "(request_time_price - low) / (high - low) * 100",
            "position_pct_clamped_to_0_100": False,
            "position_when_range_unavailable": None,
            "position_unavailable_display": "자료 미제공",
            "static_range_position_copied_as_request_position": False,
            "confirmed_metrics_recomputed": False,
            "confirmed_metrics_immutable": [
                "1M/3M/6M returns",
                "swing phase/anchors",
                "MA5/20/60/120",
                "mean run days",
                "current streak",
                "KOSPI RS",
                "sector RS",
                "ATR14",
                "20-day average intraday range",
                "confirmed 3M low/high",
                "MA20 trailing reference",
                "pending metrics",
            ],
            "request_vs_official_close_icon": {
                "absolute_difference_basis": True,
                "none": "abs(diff) < 0.5%",
                "blue": "0.5% <= abs(diff) < 1.5%",
                "orange": "1.5% <= abs(diff) < 3.0%",
                "red": "abs(diff) >= 3.0%",
                "failure": "⚪",
                "icons": {
                    "blue": "🟦",
                    "orange": "🟠",
                    "red": "🔴",
                    "failure": "⚪",
                },
            },
        },
        "not_frozen_yet": [
            "final_position_label_bands",
            "price_zone",
            "recommendation_mark",
            "final_table_header",
            "standalone_command_name",
            "standalone_route",
        ],
        "resolved_activation_blocker": REMOVED_BLOCKER,
        "remaining_activation_blockers": remaining,
        "evidence": evidence,
        "source_contracts": {
            "integrated_source": source.get("contract_version"),
            "preproduction_freeze": preprod.get("contract_version"),
            "manifest_build_id": manifest.get("build_id"),
            "manifest_route_contract_version": route.get("contract_version"),
        },
        "source_sha256": {str(p): sha256(p) for p in required},
        "safety": {
            "repository_source_data_mutated": False,
            "production_table_changed": False,
            "worker_changed": False,
            "action_schema_changed": False,
            "metric_formula_changed": False,
            "static_price_substitution": False,
            "confirmed_metric_recomputation": False,
            "new_command_invented": False,
            "new_route_invented": False,
            "final_header_invented": False,
            "final_position_label_invented": False,
            "recommendation_contract_invented": False,
            "price_zone_contract_invented": False,
        },
    }
    write_json(OUT_JSON, contract)

    meta = {
        "contract_version": CONTRACT_VERSION,
        "status": contract["status"],
        "display_merge_contract_frozen": True,
        "production_activation_allowed": False,
        "basis_date": contract["basis_date"],
        "source_row_count": len(rows),
        "range3m_position_ready": range_ready,
        "range3m_position_unavailable": range_unavailable,
        "resolved_activation_blocker": REMOVED_BLOCKER,
        "remaining_activation_blocker_count": len(remaining),
        "remaining_activation_blockers": remaining,
        "v8712_run_id": 34741483044,
        "v8712_artifact_id": 10312955901,
        "v8712_artifact_sha256": evidence["v8712_request_time_display_merge_preview"]["artifact_sha256"],
        "source_sha256": contract["source_sha256"],
        "safety": contract["safety"],
    }
    write_json(OUT_META, meta)

    lines = [
        "V8713_DISPLAY_MERGE_FREEZE_STATUS=FROZEN_PREPRODUCTION_READY",
        f"BASIS_DATE={contract['basis_date']}",
        f"SOURCE_ROWS={len(rows)}",
        f"RANGE3M_POSITION_READY_CAPACITY={range_ready}",
        f"RANGE3M_POSITION_UNAVAILABLE={range_unavailable}",
        "V8712_DISPLAY_MERGE_EVIDENCE=PASS",
        "REQUEST_PRICE_OPERATION_ID=getRequestTimePrices",
        "REQUEST_PRICE_RETRY_POLICY=10-5-2",
        "REQUEST_TIME_PRICE_OVERLAY_ONLY=true",
        "OFFICIAL_CLOSE_REFERENCE_ONLY=true",
        "STATIC_PRICE_FALLBACK_ALLOWED=false",
        "POSITION_RANGE_SOURCE=CONFIRMED_DAILY_3M_LOW_HIGH",
        "POSITION_FORMULA=(request_time_price-low)/(high-low)*100",
        "POSITION_PCT_CLAMPED=false",
        "RANGE_UNAVAILABLE_DISPLAY=자료 미제공",
        "CONFIRMED_METRICS_RECOMPUTED=false",
        "STATIC_RANGE_POSITION_COPIED=false",
        f"RESOLVED_ACTIVATION_BLOCKER={REMOVED_BLOCKER}",
        f"REMAINING_ACTIVATION_BLOCKER_COUNT={len(remaining)}",
        "FINAL_POSITION_LABEL_SELECTED=false",
        "RECOMMENDATION_CONTRACT_SELECTED=false",
        "PRICE_ZONE_CONTRACT_SELECTED=false",
        "FINAL_HEADER_SELECTED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_SOURCE_CHANGED=false",
        "ACTION_SCHEMA_CHANGED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V8713_DISPLAY_MERGE_CONTRACT_VALIDATION=PASS",
    ]
    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
