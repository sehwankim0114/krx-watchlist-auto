#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

SCRIPT_VERSION = "standalone_swing_stop_policy_v8721.py v1.0.0"
CONTRACT_VERSION = "2026-09-14-v8.7.21-standalone-swing-stop-policy"
INTEGRATED_CONTRACT = "2026-09-14-v8.7.21-standalone-swing-integrated-stop-policy"
READINESS_CONTRACT = "2026-09-14-v8.7.21-standalone-swing-readiness-stop-policy-sync"

OLD_INTEGRATED_CONTRACT = "2026-09-14-v8.7.20-standalone-swing-integrated-rsi-macd-source"

INTEGRATED = Path("latest/standalone_swing_integrated_latest.json")
INTEGRATED_META = Path("latest/standalone_swing_integrated_meta_latest.json")
PREPROD = Path("latest/standalone_swing_preproduction_readiness_latest.json")
PREPROD_META = Path("latest/standalone_swing_preproduction_readiness_meta_latest.json")
DISPLAY = Path("latest/standalone_swing_display_merge_readiness_latest.json")
DISPLAY_META = Path("latest/standalone_swing_display_merge_readiness_meta_latest.json")
MANIFEST = Path("api/manifest.json")

OUT_POLICY = Path("latest/standalone_swing_stop_policy_latest.json")
OUT_POLICY_META = Path("latest/standalone_swing_stop_policy_meta_latest.json")
OUT_POLICY_LOG = Path("latest/standalone_swing_stop_policy_run_log_latest.txt")
OUT_INTEGRATED_LOG = Path("latest/standalone_swing_integrated_run_log_latest.txt")
OUT_PREPROD_LOG = Path("latest/standalone_swing_preproduction_readiness_run_log_latest.txt")
OUT_DISPLAY_LOG = Path("latest/standalone_swing_display_merge_readiness_run_log_latest.txt")

STOP_POLICY = {
    "confirmed_swing_low_stop_numeric_value_available": False,
    "confirmed_swing_low_stop_status": "NOT_PROVIDED_CURRENT_CONTRACT",
    "missing_display": "자료 미제공",
    "derive_or_invent_numeric_stop": False,
    "ma20_is_stop": False,
    "ma20_role": "REFERENCE_ONLY",
    "ma20_display_label": "20일선 참고선",
    "request_time_price_recomputes_stop": False,
    "static_official_close_recomputes_stop": False,
    "allowed_behavior": (
        "Keep confirmed swing-low stop null when no separately approved "
        "confirmed-stop source/algorithm exists. Show MA20 only as a reference."
    ),
}

REMAINING_BLOCKERS = [
    "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
    "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
    "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
    "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
    "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
]

PENDING_METRICS = [
    "investment_score_100",
    "earnings_outlook_change",
]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

def main():
    required = [
        INTEGRATED,
        INTEGRATED_META,
        PREPROD,
        PREPROD_META,
        DISPLAY,
        DISPLAY_META,
        MANIFEST,
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit("MISSING_REQUIRED_SOURCE:" + str(path))

    integrated = read_json(INTEGRATED)
    integrated_meta = read_json(INTEGRATED_META)
    preprod = read_json(PREPROD)
    preprod_meta = read_json(PREPROD_META)
    display = read_json(DISPLAY)
    display_meta = read_json(DISPLAY_META)
    manifest = read_json(MANIFEST)

    if integrated.get("contract_version") != OLD_INTEGRATED_CONTRACT:
        raise SystemExit("INTEGRATED_CONTRACT_MISMATCH")
    if integrated_meta.get("contract_version") != OLD_INTEGRATED_CONTRACT:
        raise SystemExit("INTEGRATED_META_CONTRACT_MISMATCH")

    if integrated.get("status") != "READY_SOURCE_ONLY":
        raise SystemExit("INTEGRATED_NOT_READY_SOURCE_ONLY")
    if integrated.get("source_only") is not True:
        raise SystemExit("INTEGRATED_NOT_SOURCE_ONLY")
    if integrated.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("STANDALONE_ALREADY_ENABLED")
    if integrated.get("action_route_enabled") is not False:
        raise SystemExit("ROUTE_ALREADY_ENABLED")

    if integrated.get("pending_metrics") != [
        "investment_score_100",
        "earnings_outlook_change",
        "confirmed_swing_low_stop",
    ]:
        raise SystemExit("OLD_PENDING_METRICS_MISMATCH")

    expected_old_blockers = [
        "NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT",
        "NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT",
        "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED",
        "INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED",
        "EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED",
        "KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED",
    ]
    if preprod.get("activation_blockers") != expected_old_blockers:
        raise SystemExit("OLD_PREPROD_BLOCKERS_MISMATCH")
    if display.get("remaining_activation_blockers") != expected_old_blockers:
        raise SystemExit("OLD_DISPLAY_BLOCKERS_MISMATCH")

    route = manifest.get("command_route_contract") or {}
    two = route.get("two_table_release") or {}
    if two.get("effective_command_count") != 15:
        raise SystemExit("MANIFEST_COMMAND_COUNT_NOT_15")
    if two.get("standalone_swing_table_enabled") is not False:
        raise SystemExit("MANIFEST_STANDALONE_ALREADY_ENABLED")

    rows = integrated.get("rows") or []
    if len(rows) != 235:
        raise SystemExit(f"INTEGRATED_ROW_COUNT_MISMATCH:{len(rows)}")

    confirmed_stop_null_count = 0
    ma20_reference_ready_count = 0
    unexpected_stop_values = []

    for row in rows:
        ticker = str(row.get("ticker") or "").zfill(6)
        trailing = row.get("trailing_reference") or {}

        stop_value = trailing.get("confirmed_swing_low_stop")
        if stop_value is None:
            confirmed_stop_null_count += 1
        else:
            unexpected_stop_values.append({
                "ticker": ticker,
                "value": stop_value,
            })

        if trailing.get("ma20_close_level") is not None:
            ma20_reference_ready_count += 1

    if unexpected_stop_values:
        raise SystemExit(
            "UNEXPECTED_CONFIRMED_STOP_VALUES:"
            + json.dumps(unexpected_stop_values, ensure_ascii=False)[:4000]
        )
    if confirmed_stop_null_count != 235:
        raise SystemExit(
            f"CONFIRMED_STOP_NULL_COUNT_MISMATCH:{confirmed_stop_null_count}"
        )
    if ma20_reference_ready_count != 235:
        raise SystemExit(
            f"MA20_REFERENCE_READY_COUNT_MISMATCH:{ma20_reference_ready_count}"
        )

    policy_payload = {
        "contract_version": CONTRACT_VERSION,
        "script_version": SCRIPT_VERSION,
        "status": "FROZEN_POLICY_ONLY",
        "source_only": True,
        "basis_date": integrated.get("basis_date"),
        "row_count": 235,
        "confirmed_stop_null_count": confirmed_stop_null_count,
        "ma20_reference_ready_count": ma20_reference_ready_count,
        "policy": STOP_POLICY,
        "project_rule_alignment": {
            "missing_confirmed_stop_display": "자료 미제공",
            "ma20_reference_only": True,
            "ma20_guaranteed_stop_price": False,
            "fabricated_stop_forbidden": True,
        },
        "safety": {
            "numeric_stop_created": False,
            "numeric_stop_inferred": False,
            "ma20_relabelled_as_stop": False,
            "request_time_price_used_to_make_stop": False,
            "production_table_changed": False,
            "worker_changed": False,
            "action_schema_changed": False,
            "new_command_defined": False,
            "route_enabled": False,
            "final_header_selected": False,
        },
    }
    write_json(OUT_POLICY, policy_payload)

    write_json(OUT_POLICY_META, {
        "contract_version": CONTRACT_VERSION,
        "status": "FROZEN_POLICY_ONLY",
        "basis_date": integrated.get("basis_date"),
        "row_count": 235,
        "confirmed_stop_null_count": confirmed_stop_null_count,
        "ma20_reference_ready_count": ma20_reference_ready_count,
        "policy": STOP_POLICY,
        "safety": policy_payload["safety"],
    })

    policy_log = [
        "V8721_STOP_POLICY_STATUS=FROZEN_POLICY_ONLY",
        "SOURCE_ROWS=235",
        "CONFIRMED_STOP_NULL_COUNT=235",
        "MA20_REFERENCE_READY_COUNT=235",
        "CONFIRMED_STOP_STATUS=NOT_PROVIDED_CURRENT_CONTRACT",
        "CONFIRMED_STOP_MISSING_DISPLAY=자료 미제공",
        "NUMERIC_STOP_CREATED=false",
        "NUMERIC_STOP_INFERRED=false",
        "MA20_IS_STOP=false",
        "MA20_ROLE=REFERENCE_ONLY",
        "MA20_DISPLAY_LABEL=20일선 참고선",
        "REQUEST_TIME_PRICE_RECOMPUTES_STOP=false",
        "V8721_STOP_POLICY_VALIDATION=PASS",
    ]
    OUT_POLICY_LOG.write_text("\n".join(policy_log) + "\n", encoding="utf-8")

    # Integrated source: preserve null numeric stop; add explicit status/policy.
    for row in rows:
        trailing = row.get("trailing_reference") or {}
        trailing["confirmed_swing_low_stop"] = None
        trailing["confirmed_swing_low_stop_status"] = (
            "NOT_PROVIDED_CURRENT_CONTRACT"
        )
        trailing["ma20_role"] = "REFERENCE_ONLY"
        trailing["ma20_display_label"] = "20일선 참고선"
        row["trailing_reference"] = trailing

        pending = dict(row.get("pending_metrics") or {})
        pending.pop("confirmed_swing_low_stop", None)
        row["pending_metrics"] = pending

    integrated["contract_version"] = INTEGRATED_CONTRACT
    integrated["script_version"] = SCRIPT_VERSION
    integrated["stop_policy_contract_version"] = CONTRACT_VERSION
    integrated["confirmed_swing_low_stop_policy"] = STOP_POLICY
    integrated["confirmed_swing_low_stop_ready_count"] = 0
    integrated["confirmed_swing_low_stop_status_count"] = {
        "NOT_PROVIDED_CURRENT_CONTRACT": 235
    }
    integrated["ma20_reference_ready_count"] = 235
    integrated["pending_metrics"] = PENDING_METRICS
    integrated["rows"] = rows
    integrated["source_lineage"] = dict(integrated.get("source_lineage") or {})
    integrated["source_lineage"]["stop_policy_contract_version"] = CONTRACT_VERSION
    integrated["safety"] = dict(integrated.get("safety") or {})
    integrated["safety"].update({
        "confirmed_swing_low_stop_calculated": False,
        "confirmed_swing_low_stop_invented": False,
        "ma20_relabelled_as_stop": False,
        "request_time_price_substitution": False,
        "production_table_changed": False,
        "worker_changed": False,
        "new_command_defined": False,
        "action_route_enabled": False,
        "standalone_swing_table_enabled": False,
    })
    write_json(INTEGRATED, integrated)

    integrated_meta["contract_version"] = INTEGRATED_CONTRACT
    integrated_meta["script_version"] = SCRIPT_VERSION
    integrated_meta["stop_policy_contract_version"] = CONTRACT_VERSION
    integrated_meta["confirmed_swing_low_stop_policy"] = STOP_POLICY
    integrated_meta["confirmed_swing_low_stop_ready_count"] = 0
    integrated_meta["confirmed_swing_low_stop_status_count"] = {
        "NOT_PROVIDED_CURRENT_CONTRACT": 235
    }
    integrated_meta["ma20_reference_ready_count"] = 235
    integrated_meta["pending_metrics"] = PENDING_METRICS
    integrated_meta["source_lineage"] = dict(
        integrated_meta.get("source_lineage") or {}
    )
    integrated_meta["source_lineage"][
        "stop_policy_contract_version"
    ] = CONTRACT_VERSION
    write_json(INTEGRATED_META, integrated_meta)

    integrated_log = [
        "V8721_INTEGRATED_SWING_SOURCE_STATUS=READY_SOURCE_ONLY",
        "INTEGRATED_ROWS=235",
        "CONFIRMED_SWING_LOW_STOP_READY=0",
        "CONFIRMED_SWING_LOW_STOP_STATUS_NOT_PROVIDED=235",
        "MA20_REFERENCE_READY=235",
        "PENDING_METRICS=investment_score_100,earnings_outlook_change",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "PRODUCTION_TABLE_CHANGED=false",
        "WORKER_CHANGED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
        "NEW_COMMAND_DEFINED=false",
        "V8721_INTEGRATED_SWING_SOURCE_VALIDATION=PASS",
    ]
    OUT_INTEGRATED_LOG.write_text(
        "\n".join(integrated_log) + "\n", encoding="utf-8"
    )

    resolved = list(preprod.get("resolved_activation_blockers") or [])
    if "CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED" not in resolved:
        resolved.append("CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED")

    accepted_missing = dict(preprod.get("accepted_missing_policy") or {})
    accepted_missing["confirmed_swing_low_stop"] = (
        "자료 미제공 under current contract; MA20 is reference only, "
        "never a guaranteed or substituted stop price"
    )

    preprod["contract_version"] = READINESS_CONTRACT
    preprod["script_version"] = SCRIPT_VERSION
    preprod["confirmed_swing_low_stop_policy_frozen"] = True
    preprod["confirmed_swing_low_stop_policy"] = STOP_POLICY
    preprod["pending_metrics"] = PENDING_METRICS
    preprod["activation_blockers"] = REMAINING_BLOCKERS
    preprod["resolved_activation_blockers"] = resolved
    preprod["accepted_missing_policy"] = accepted_missing
    preprod["source_contract_version"] = INTEGRATED_CONTRACT
    preprod["source_lineage"] = dict(preprod.get("source_lineage") or {})
    preprod["source_lineage"]["stop_policy_contract_version"] = CONTRACT_VERSION
    preprod["snapshot_counts"] = dict(preprod.get("snapshot_counts") or {})
    preprod["snapshot_counts"]["confirmed_stop_ready"] = 0
    preprod["snapshot_counts"]["confirmed_stop_not_provided"] = 235
    preprod["snapshot_counts"]["ma20_reference_ready"] = 235
    preprod["production_activation_allowed"] = False
    preprod["standalone_swing_table_enabled"] = False
    preprod["action_route_enabled"] = False
    preprod["standalone_command_defined"] = False
    preprod["final_header_selected"] = False
    write_json(PREPROD, preprod)

    preprod_meta["contract_version"] = READINESS_CONTRACT
    preprod_meta["confirmed_swing_low_stop_policy_frozen"] = True
    preprod_meta["confirmed_swing_low_stop_policy"] = STOP_POLICY
    preprod_meta["activation_blocker_count"] = 5
    preprod_meta["activation_blockers"] = REMAINING_BLOCKERS
    preprod_meta["resolved_activation_blockers"] = resolved
    preprod_meta["pending_metrics"] = PENDING_METRICS
    preprod_meta["source_contract_version"] = INTEGRATED_CONTRACT
    preprod_meta["source_lineage"] = dict(
        preprod_meta.get("source_lineage") or {}
    )
    preprod_meta["source_lineage"][
        "stop_policy_contract_version"
    ] = CONTRACT_VERSION
    preprod_meta["snapshot_counts"] = dict(
        preprod_meta.get("snapshot_counts") or {}
    )
    preprod_meta["snapshot_counts"]["confirmed_stop_ready"] = 0
    preprod_meta["snapshot_counts"]["confirmed_stop_not_provided"] = 235
    preprod_meta["snapshot_counts"]["ma20_reference_ready"] = 235
    preprod_meta["production_activation_allowed"] = False
    write_json(PREPROD_META, preprod_meta)

    display["contract_version"] = READINESS_CONTRACT
    display["script_version"] = SCRIPT_VERSION
    display["confirmed_swing_low_stop_policy_frozen"] = True
    display["confirmed_swing_low_stop_policy"] = STOP_POLICY
    display["pending_metrics"] = PENDING_METRICS
    display["remaining_activation_blockers"] = REMAINING_BLOCKERS
    display["resolved_activation_blockers"] = resolved
    display["source_contracts"] = dict(display.get("source_contracts") or {})
    display["source_contracts"]["integrated_source"] = INTEGRATED_CONTRACT
    display["source_contracts"]["stop_policy"] = CONTRACT_VERSION
    display["production_activation_allowed"] = False
    display["standalone_swing_table_enabled"] = False
    display["action_route_enabled"] = False
    display["standalone_command_defined"] = False
    display["final_header_selected"] = False
    write_json(DISPLAY, display)

    display_meta["contract_version"] = READINESS_CONTRACT
    display_meta["confirmed_swing_low_stop_policy_frozen"] = True
    display_meta["confirmed_swing_low_stop_policy"] = STOP_POLICY
    display_meta["pending_metrics"] = PENDING_METRICS
    display_meta["remaining_activation_blocker_count"] = 5
    display_meta["remaining_activation_blockers"] = REMAINING_BLOCKERS
    display_meta["resolved_activation_blockers"] = resolved
    display_meta["source_contract_version"] = INTEGRATED_CONTRACT
    display_meta["production_activation_allowed"] = False
    write_json(DISPLAY_META, display_meta)

    preprod_log = [
        "V8721_PREPRODUCTION_READINESS=FROZEN_PREPRODUCTION_READY",
        "CONFIRMED_SWING_LOW_STOP_POLICY_FROZEN=true",
        "CONFIRMED_STOP_NUMERIC_READY=0",
        "CONFIRMED_STOP_NOT_PROVIDED=235",
        "MA20_REFERENCE_READY=235",
        "ACTIVATION_BLOCKER_COUNT=5",
        "PENDING_METRIC_COUNT=2",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "V8721_PREPRODUCTION_READINESS_VALIDATION=PASS",
    ]
    OUT_PREPROD_LOG.write_text(
        "\n".join(preprod_log) + "\n", encoding="utf-8"
    )

    display_log = [
        "V8721_DISPLAY_MERGE_READINESS=FROZEN_PREPRODUCTION_READY",
        "CONFIRMED_SWING_LOW_STOP_POLICY_FROZEN=true",
        "REMAINING_ACTIVATION_BLOCKER_COUNT=5",
        "PENDING_METRIC_COUNT=2",
        "PRODUCTION_ACTIVATION_ALLOWED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "ACTION_ROUTE_ENABLED=false",
        "STANDALONE_COMMAND_DEFINED=false",
        "FINAL_HEADER_SELECTED=false",
        "V8721_DISPLAY_MERGE_READINESS_VALIDATION=PASS",
    ]
    OUT_DISPLAY_LOG.write_text(
        "\n".join(display_log) + "\n", encoding="utf-8"
    )

    print("\n".join(policy_log))
    print("\n".join(integrated_log))
    print("\n".join(preprod_log))
    print("\n".join(display_log))

if __name__ == "__main__":
    main()
