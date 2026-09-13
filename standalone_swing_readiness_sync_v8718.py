#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_readiness_sync_v8718.py v1.0.0"
CONTRACT_VERSION = "2026-09-13-v8.7.18-standalone-swing-readiness-sync"

INTEGRATED = Path("latest/standalone_swing_integrated_latest.json")
INTEGRATED_META = Path("latest/standalone_swing_integrated_meta_latest.json")
EXTENDED = Path("latest/standalone_swing_extended_returns_latest.json")
PREPROD = Path("latest/standalone_swing_preproduction_readiness_latest.json")
PREPROD_META = Path("latest/standalone_swing_preproduction_readiness_meta_latest.json")
DISPLAY = Path("latest/standalone_swing_display_merge_readiness_latest.json")
DISPLAY_META = Path("latest/standalone_swing_display_merge_readiness_meta_latest.json")
MANIFEST = Path("api/manifest.json")
SCHEMA = Path("docs/custom_gpt_action_schema.yaml")
WORKER = Path("worker/krx-live-price-worker.js")
METRICS = Path("stock_table_metrics_v850.py")

PREPROD_LOG = Path("latest/standalone_swing_preproduction_readiness_run_log_latest.txt")
DISPLAY_LOG = Path("latest/standalone_swing_display_merge_readiness_run_log_latest.txt")

EXPECTED_INTEGRATED_CONTRACT = (
    "2026-09-13-v8.7.17-standalone-swing-integrated-returns-source"
)
EXPECTED_EXTENDED_CONTRACT = (
    "2026-09-13-v8.7.17-standalone-swing-return-basis-source"
)

RESOLVED_BLOCKERS = [
    "REQUEST_TIME_DISPLAY_MERGE_CONTRACT_NOT_FROZEN_FOR_STANDALONE",
    "1W_YTD_52W_FORMULAS_NOT_APPROVED",
]

REMAINING_BLOCKERS = [
    "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
    "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
    "RSI_MACD_FORMULAS_NOT_APPROVED",
    "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
    "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
    "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
    "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
]

PENDING_METRICS = [
    "rsi",
    "macd",
    "investment_score_100",
    "earnings_outlook_change",
    "confirmed_swing_low_stop",
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
    required = [
        INTEGRATED,
        INTEGRATED_META,
        EXTENDED,
        PREPROD,
        PREPROD_META,
        DISPLAY,
        DISPLAY_META,
        MANIFEST,
        SCHEMA,
        WORKER,
        METRICS,
    ]
    for p in required:
        if not p.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(p))

    integrated = read_json(INTEGRATED)
    integrated_meta = read_json(INTEGRATED_META)
    extended = read_json(EXTENDED)
    old_preprod = read_json(PREPROD)
    old_preprod_meta = read_json(PREPROD_META)
    old_display = read_json(DISPLAY)
    old_display_meta = read_json(DISPLAY_META)
    manifest = read_json(MANIFEST)

    if integrated.get("contract_version") != EXPECTED_INTEGRATED_CONTRACT:
        raise SystemExit("INTEGRATED_CONTRACT_MISMATCH")
    if integrated_meta.get("contract_version") != EXPECTED_INTEGRATED_CONTRACT:
        raise SystemExit("INTEGRATED_META_CONTRACT_MISMATCH")
    if extended.get("contract_version") != EXPECTED_EXTENDED_CONTRACT:
        raise SystemExit("EXTENDED_CONTRACT_MISMATCH")

    for payload, label in (
        (integrated, "INTEGRATED"),
        (integrated_meta, "INTEGRATED_META"),
        (extended, "EXTENDED"),
    ):
        if payload.get("status") != "READY_SOURCE_ONLY":
            raise SystemExit(label + "_NOT_READY_SOURCE_ONLY")
        if payload.get("source_only") is not True:
            raise SystemExit(label + "_NOT_SOURCE_ONLY")
        if payload.get("standalone_swing_table_enabled") is not False:
            raise SystemExit(label + "_TABLE_ENABLED")
        if payload.get("action_route_enabled") is not False:
            raise SystemExit(label + "_ROUTE_ENABLED")

    if integrated.get("request_time_price_eligible") is not False:
        raise SystemExit("INTEGRATED_REQUEST_TIME_PRICE_ELIGIBLE_UNEXPECTEDLY")
    if integrated_meta.get("request_time_price_eligible") is not False:
        raise SystemExit("INTEGRATED_META_REQUEST_TIME_PRICE_ELIGIBLE_UNEXPECTEDLY")

    if old_preprod.get("status") != "FROZEN_PREPRODUCTION_READY":
        raise SystemExit("OLD_PREPROD_NOT_FROZEN")
    if old_display.get("status") != "FROZEN_PREPRODUCTION_READY":
        raise SystemExit("OLD_DISPLAY_NOT_FROZEN")
    if old_display.get("display_merge_contract_frozen") is not True:
        raise SystemExit("DISPLAY_MERGE_FREEZE_MISSING")

    basis = integrated.get("basis_date")
    if not basis or integrated_meta.get("basis_date") != basis:
        raise SystemExit("INTEGRATED_BASIS_MISMATCH")
    if extended.get("basis_date") != basis:
        raise SystemExit("EXTENDED_BASIS_MISMATCH")
    if old_preprod.get("basis_date") != basis:
        raise SystemExit("PREPROD_BASIS_MISMATCH")
    if old_display.get("basis_date") != basis:
        raise SystemExit("DISPLAY_BASIS_MISMATCH")

    if int(integrated.get("row_count") or 0) != 235:
        raise SystemExit("INTEGRATED_ROW_COUNT_NOT_235")
    if int(integrated_meta.get("row_count") or 0) != 235:
        raise SystemExit("INTEGRATED_META_ROW_COUNT_NOT_235")

    return_ready = integrated.get("return_ready_count") or {}
    expected_return_ready = {
        "1w": 235,
        "1m": 235,
        "3m": 235,
        "6m": 234,
        "ytd": 234,
        "52w": 233,
    }
    if return_ready != expected_return_ready:
        raise SystemExit(
            "RETURN_READY_COUNT_MISMATCH:"
            + json.dumps(return_ready, ensure_ascii=False)
        )

    if integrated.get("pending_metrics") != PENDING_METRICS:
        raise SystemExit(
            "INTEGRATED_PENDING_METRICS_MISMATCH:"
            + json.dumps(integrated.get("pending_metrics"), ensure_ascii=False)
        )

    return_basis = integrated.get("return_basis") or {}
    expected_basis = {
        "1w": "CALENDAR_DAYS_7_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "1m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "3m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "6m": "CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER",
        "ytd": "PRIOR_YEAR_FINAL_MARKET_SESSION_CLOSE",
        "52w": "CALENDAR_WEEKS_52_FIRST_MARKET_SESSION_ON_OR_AFTER",
    }
    if return_basis != expected_basis:
        raise SystemExit(
            "RETURN_BASIS_MISMATCH:"
            + json.dumps(return_basis, ensure_ascii=False)
        )

    if integrated.get("return_start_dates") != {
        "1w": "2026-09-04",
        "ytd": "2025-12-30",
        "52w": "2025-09-12",
    }:
        raise SystemExit("RETURN_START_DATES_MISMATCH")

    # Existing request-time display merge must remain unchanged in semantics.
    merge = old_display.get("request_time_display_merge_contract") or {}
    if merge.get("price_source_operation_id") != "getRequestTimePrices":
        raise SystemExit("DISPLAY_PRICE_OPERATION_MISMATCH")
    if merge.get("retry_policy") != [10, 5, 2]:
        raise SystemExit("DISPLAY_RETRY_POLICY_MISMATCH")
    if merge.get("static_price_fallback_allowed") is not False:
        raise SystemExit("STATIC_PRICE_FALLBACK_ALLOWED_UNEXPECTEDLY")
    if merge.get("confirmed_metrics_recomputed") is not False:
        raise SystemExit("CONFIRMED_METRIC_RECOMPUTATION_UNEXPECTEDLY")

    # Manifest still governs the 15 current production commands.
    route = manifest.get("command_route_contract") or {}
    two = route.get("two_table_release") or {}
    if two.get("effective_command_count") != 15:
        raise SystemExit("MANIFEST_EFFECTIVE_COMMAND_COUNT_NOT_15")
    if two.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("MANIFEST_STANDALONE_ALREADY_ENABLED")

    snapshot_counts = dict(old_preprod.get("snapshot_counts") or {})
    snapshot_counts.update({
        "row_count": 235,
        "kospi": 210,
        "kosdaq": 25,
        "return_1w_ready": 235,
        "return_1w_missing": 0,
        "return_1m_ready": 235,
        "return_3m_ready": 235,
        "return_6m_ready": 234,
        "return_6m_missing": 1,
        "return_ytd_ready": 234,
        "return_ytd_missing": 1,
        "return_52w_ready": 233,
        "return_52w_missing": 2,
    })

    accepted_missing = dict(old_preprod.get("accepted_missing_policy") or {})
    accepted_missing.update({
        "return_1w": "fully available at current basis under approved 7-calendar-day official-session contract",
        "return_6m": "자료 미제공 when calendar history is insufficient; no imputation",
        "return_ytd": "자료 미제공 when prior-year final official-session close is unavailable due listing/history limits",
        "return_52w": "자료 미제공 when exact globally resolved 52-week official-session start close is unavailable; no post-listing substitution",
    })

    evidence = dict(old_preprod.get("evidence") or {})
    evidence["v8712_request_time_display_merge_preview"] = old_display.get("evidence", {}).get(
        "v8712_request_time_display_merge_preview"
    )
    evidence["v8717_return_basis_source_release"] = {
        "commit_sha": "cf26e2447d301296e838d01dbf40edd90c638611",
        "result": "PASS",
        "extended_contract_version": EXPECTED_EXTENDED_CONTRACT,
        "integrated_contract_version": EXPECTED_INTEGRATED_CONTRACT,
        "return_basis": return_basis,
        "return_start_dates": integrated.get("return_start_dates"),
        "return_ready_count": return_ready,
        "return_missing_count": integrated.get("return_missing_count"),
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
    }

    source_lineage = dict(integrated.get("source_lineage") or {})
    source_hashes = {
        str(INTEGRATED): sha256(INTEGRATED),
        str(INTEGRATED_META): sha256(INTEGRATED_META),
        str(EXTENDED): sha256(EXTENDED),
        str(MANIFEST): sha256(MANIFEST),
        str(SCHEMA): sha256(SCHEMA),
        str(WORKER): sha256(WORKER),
        str(METRICS): sha256(METRICS),
    }

    preprod = dict(old_preprod)
    preprod.update({
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "preproduction_contract_frozen": True,
        "data_layer_ready_for_preproduction": True,
        "request_time_price_path_ready_for_preproduction": True,
        "request_time_display_merge_contract_frozen": True,
        "return_basis_contract_frozen": True,
        "production_activation_allowed": False,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "standalone_command_defined": False,
        "final_header_selected": False,
        "basis_date": basis,
        "snapshot_counts": snapshot_counts,
        "accepted_missing_policy": accepted_missing,
        "return_basis": return_basis,
        "return_start_dates": integrated.get("return_start_dates"),
        "pending_metrics": PENDING_METRICS,
        "activation_blockers": REMAINING_BLOCKERS,
        "resolved_activation_blockers": RESOLVED_BLOCKERS,
        "evidence": evidence,
        "source_contract_version": EXPECTED_INTEGRATED_CONTRACT,
        "source_lineage": source_lineage,
        "source_sha256": source_hashes,
    })

    # Retain price-path contract and add current manifest evidence.
    price_contract = dict(preprod.get("request_time_price_contract") or {})
    price_contract.update({
        "operation_id": "getRequestTimePrices",
        "initial_batch_max": 10,
        "retry_failed_batch_max": 5,
        "final_retry_failed_batch_max": 2,
        "final_failure_display": "⚪ 현재가 확인 실패",
        "static_price_fallback_allowed": False,
        "official_close_is_reference_only_not_request_time_price": True,
        "new_price_action_required": False,
        "must_revalidate_at_activation": True,
        "manifest_effective_command_count": 15,
        "manifest_standalone_swing_table_enabled": False,
    })
    preprod["request_time_price_contract"] = price_contract

    safety = dict(old_preprod.get("safety") or {})
    safety.update({
        "production_table_changed": False,
        "worker_changed": False,
        "action_schema_changed": False,
        "metric_formula_changed": False,
        "request_time_price_substitution": False,
        "new_command_invented": False,
        "new_route_invented": False,
        "final_header_invented": False,
        "pending_metric_autofill": False,
    })
    preprod["safety"] = safety
    write_json(PREPROD, preprod)

    preprod_meta = {
        "contract_version": CONTRACT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "preproduction_contract_frozen": True,
        "request_time_display_merge_contract_frozen": True,
        "return_basis_contract_frozen": True,
        "production_activation_allowed": False,
        "basis_date": basis,
        "row_count": 235,
        "snapshot_counts": snapshot_counts,
        "price_operation_id": "getRequestTimePrices",
        "price_retry_policy": [10, 5, 2],
        "activation_blocker_count": len(REMAINING_BLOCKERS),
        "activation_blockers": REMAINING_BLOCKERS,
        "resolved_activation_blockers": RESOLVED_BLOCKERS,
        "pending_metrics": PENDING_METRICS,
        "source_contract_version": EXPECTED_INTEGRATED_CONTRACT,
        "source_lineage": source_lineage,
        "return_basis": return_basis,
        "return_start_dates": integrated.get("return_start_dates"),
        "source_sha256": source_hashes,
        "safety": safety,
    }
    write_json(PREPROD_META, preprod_meta)

    display = dict(old_display)
    display.update({
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "display_merge_contract_frozen": True,
        "return_basis_contract_frozen": True,
        "production_activation_allowed": False,
        "standalone_swing_table_enabled": False,
        "action_route_enabled": False,
        "standalone_command_defined": False,
        "final_header_selected": False,
        "basis_date": basis,
        "source_row_count": 235,
        "return_basis": return_basis,
        "return_start_dates": integrated.get("return_start_dates"),
        "pending_metrics": PENDING_METRICS,
        "resolved_activation_blockers": RESOLVED_BLOCKERS,
        "remaining_activation_blockers": REMAINING_BLOCKERS,
        "source_contracts": {
            "integrated_source": EXPECTED_INTEGRATED_CONTRACT,
            "extended_returns_source": EXPECTED_EXTENDED_CONTRACT,
            "preproduction_freeze": CONTRACT_VERSION,
            "display_merge_base_contract": "2026-09-13-v8.7.13-standalone-swing-display-merge-freeze",
            "manifest_route_contract_version": route.get("contract_version"),
        },
        "source_sha256": source_hashes,
    })
    display.pop("resolved_activation_blocker", None)
    display["safety"] = dict(old_display.get("safety") or {})
    display["safety"].update({
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
    })
    write_json(DISPLAY, display)

    display_meta = {
        "contract_version": CONTRACT_VERSION,
        "status": "FROZEN_PREPRODUCTION_READY",
        "display_merge_contract_frozen": True,
        "return_basis_contract_frozen": True,
        "production_activation_allowed": False,
        "basis_date": basis,
        "source_row_count": 235,
        "range3m_position_ready": int(
            (display.get("range3m_position_capacity") or {}).get("ready") or 0
        ),
        "range3m_position_unavailable": int(
            (display.get("range3m_position_capacity") or {}).get("unavailable") or 0
        ),
        "resolved_activation_blockers": RESOLVED_BLOCKERS,
        "remaining_activation_blocker_count": len(REMAINING_BLOCKERS),
        "remaining_activation_blockers": REMAINING_BLOCKERS,
        "pending_metrics": PENDING_METRICS,
        "return_basis": return_basis,
        "return_start_dates": integrated.get("return_start_dates"),
        "source_contract_version": EXPECTED_INTEGRATED_CONTRACT,
        "source_sha256": source_hashes,
        "safety": display["safety"],
    }
    write_json(DISPLAY_META, display_meta)

    preprod_log = [
        "V8718_PREPRODUCTION_READINESS_SYNC=FROZEN_PREPRODUCTION_READY",
        f"BASIS_DATE={basis}",
        "SOURCE_ROWS=235",
        "RETURN_1W_READY=235",
        "RETURN_1M_READY=235",
        "RETURN_3M_READY=235",
        "RETURN_6M_READY=234",
        "RETURN_YTD_READY=234",
        "RETURN_52W_READY=233",
        "PENDING_METRICS=rsi,macd,investment_score_100,earnings_outlook_change,confirmed_swing_low_stop",
        "RESOLVED_BLOCKER_REQUEST_TIME_DISPLAY_MERGE=true",
        "RESOLVED_BLOCKER_1W_YTD_52W=true",
        f"ACTIVATION_BLOCKER_COUNT={len(REMAINING_BLOCKERS)}",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "ACTION_SCHEMA_CHANGED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V8718_PREPRODUCTION_READINESS_VALIDATION=PASS",
    ]
    PREPROD_LOG.write_text("\n".join(preprod_log) + "\n", encoding="utf-8")

    display_log = [
        "V8718_DISPLAY_MERGE_READINESS_SYNC=FROZEN_PREPRODUCTION_READY",
        f"BASIS_DATE={basis}",
        "SOURCE_ROWS=235",
        "DISPLAY_MERGE_CONTRACT_FROZEN=true",
        "RETURN_BASIS_CONTRACT_FROZEN=true",
        f"REMAINING_ACTIVATION_BLOCKER_COUNT={len(REMAINING_BLOCKERS)}",
        "PENDING_METRICS=rsi,macd,investment_score_100,earnings_outlook_change,confirmed_swing_low_stop",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "ACTION_SCHEMA_CHANGED=false",
        "METRIC_FORMULA_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "V8718_DISPLAY_MERGE_READINESS_VALIDATION=PASS",
    ]
    DISPLAY_LOG.write_text("\n".join(display_log) + "\n", encoding="utf-8")

    print("\n".join(preprod_log))
    print("\n".join(display_log))

if __name__ == "__main__":
    main()
