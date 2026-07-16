#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
validate_api_sync.py v1.1_single_table

API 구조 오류는 실패 처리한다.
공식 KRX 게시 지연은 구조 오류가 아니므로 경고로 기록하고 API에는 반영한다.
그 결과 Custom GPT가 오래된 자료를 최신이라고 오인하지 않게 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_VERSION = "validate_api_sync.py v1.5_holdings_exact_ticker_v824"


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    args = parser.parse_args()

    api = Path(args.api_dir)
    status = read_json(api / "status.json")
    manifest = read_json(api / "manifest.json")
    rules = read_json(api / "stock_table_rules.json")

    errors: List[str] = []
    warnings: List[str] = []

    if not status:
        errors.append("status.json missing or invalid")
    if not manifest:
        errors.append("manifest.json missing or invalid")
    if not rules:
        errors.append("stock_table_rules.json missing or invalid")

    build_ids = {
        value for value in (
            status.get("build_id"),
            manifest.get("build_id"),
            rules.get("build_id"),
        ) if value
    }
    if len(build_ids) != 1:
        errors.append(f"control file build_id mismatch: {sorted(build_ids)}")

    if status and not status.get("api_sync_ok"):
        errors.extend(str(item) for item in status.get("critical_errors", []))
    if status and not status.get("official_fresh_now"):
        warnings.append(
            "Official data is not fresh for the current expected trading date. "
            "API is published with safe_to_analyze_as_latest=false."
        )

    status_policy = status.get("presentation_policy", {}) if status else {}
    manifest_policy = manifest.get("presentation_policy", {}) if manifest else {}
    if not status_policy or not manifest_policy:
        errors.append("presentation_policy missing from status or manifest")
    elif status_policy != manifest_policy:
        errors.append("presentation_policy mismatch between status and manifest")
    else:
        if status_policy.get("default_output_mode") != "single_main_table":
            errors.append("presentation_policy.default_output_mode must be single_main_table")
        if status_policy.get("separate_recommendation_table_default") is not False:
            errors.append("separate recommendation table must be disabled by default")
        if status_policy.get("duplicate_rows_across_main_and_shortlist_tables") is not False:
            errors.append("duplicate rows across main and shortlist tables must be disabled")

    manifest_tables = manifest.get("tables", []) if isinstance(manifest, dict) else []
    required_seen = 0
    rules_hash = rules.get("rules_sha256")
    for item in manifest_tables:
        if not isinstance(item, dict):
            errors.append("manifest contains invalid table entry")
            continue
        path_text = item.get("api_file")
        if not path_text:
            errors.append(f"{item.get('table_id')}: api_file missing")
            continue
        path = Path(path_text)
        if path.parts and path.parts[0] == api.name:
            path = api.parent / path
        elif not path.is_absolute():
            path = api / path.name
        payload = read_json(path)
        if not payload:
            errors.append(f"{item.get('table_id')}: table JSON missing or invalid")
            continue
        if item.get("required"):
            required_seen += 1
            if payload.get("status") != "OK":
                errors.append(
                    f"{item.get('table_id')}: required table status={payload.get('status')}"
                )
        if payload.get("build_id") not in build_ids:
            errors.append(f"{item.get('table_id')}: build_id mismatch")
        if payload.get("rules", {}).get("sha256") != rules_hash:
            errors.append(f"{item.get('table_id')}: rules hash mismatch")
        if payload.get("row_count") != len(payload.get("rows", [])):
            errors.append(f"{item.get('table_id')}: row_count does not match rows length")


    # STRICT_CONTRACT_V5_BEGIN
    if status_policy.get("recommendation_markings_embedded_in_main_table") is not True:
        errors.append("recommendation markings must be embedded in main table")

    rules_version = rules.get("rules_version")
    strict_tables = {}
    for item in manifest_tables:
        if not isinstance(item, dict) or not item.get("api_file"):
            continue
        path = Path(item["api_file"])
        if path.parts and path.parts[0] == api.name:
            path = api.parent / path
        elif not path.is_absolute():
            path = api / path.name
        payload = read_json(path)
        if not payload:
            continue
        table_id = item.get("table_id")
        strict_tables[table_id] = (item, payload)
        if payload.get("rules_version") != rules_version:
            errors.append(f"{table_id}: top-level rules_version mismatch")
        if payload.get("rules_sha256") != rules_hash:
            errors.append(f"{table_id}: top-level rules_sha256 mismatch")
        if payload.get("presentation_policy") != status_policy:
            errors.append(f"{table_id}: presentation_policy mismatch")
        if payload.get("default_output") != item.get("default_output"):
            errors.append(f"{table_id}: default_output mismatch")
        if payload.get("explicit_request_only") != item.get("explicit_request_only"):
            errors.append(f"{table_id}: explicit_request_only mismatch")

    core = strict_tables.get("kospi_monthly_cycle")
    full = strict_tables.get("kospi_monthly_cycle_candidates")
    if core:
        item, payload = core
        if item.get("default_output") is not True or payload.get("default_output") is not True:
            errors.append("kospi_monthly_cycle must be default")
        if item.get("explicit_request_only") is not False or payload.get("explicit_request_only") is not False:
            errors.append("kospi_monthly_cycle explicit flag invalid")
    if full:
        item, payload = full
        if item.get("default_output") is not False or payload.get("default_output") is not False:
            errors.append("kospi_monthly_cycle_candidates must not be default")
        if item.get("explicit_request_only") is not True or payload.get("explicit_request_only") is not True:
            errors.append("kospi_monthly_cycle_candidates must be explicit-only")

    expected_safe = bool(
        status
        and status.get("api_sync_ok")
        and status.get("official_fresh_now")
        and not status.get("critical_errors")
    )
    if status and bool(status.get("safe_to_analyze_as_latest")) != expected_safe:
        errors.append("safe_to_analyze_as_latest strict-gate mismatch")
    # STRICT_CONTRACT_V5_END

    expected_required = status.get("required_table_count") if status else None
    if expected_required is not None and required_seen != expected_required:
        errors.append(
            f"required table count mismatch: manifest={required_seen}, status={expected_required}"
        )


    # RULES_VERSION_CONTRACT_BEGIN
    rules_source = api.parent / "docs" / "stock_table_rules_latest.md"
    canonical_rules_version = None
    canonical_rules_hash = None

    if not rules_source.exists():
        errors.append("canonical rules source missing: docs/stock_table_rules_latest.md")
    else:
        rules_text = rules_source.read_text(encoding="utf-8")
        canonical_rules_hash = hashlib.sha256(
            rules_text.encode("utf-8")
        ).hexdigest()
        version_match = re.search(
            r"(?:규칙 버전|rules_version)\s*[:：]\s*`?([0-9A-Za-z._-]+)`?",
            rules_text,
        )
        if version_match is None:
            errors.append("canonical rules_version could not be extracted")
        else:
            canonical_rules_version = version_match.group(1)

    if canonical_rules_version:
        control_versions = {
            "status.json": status.get("rules_version"),
            "manifest.json": (
                manifest.get("rules_version")
                or manifest.get("rules", {}).get("version")
            ),
            "stock_table_rules.json": rules.get("rules_version"),
        }
        for filename, actual_version in control_versions.items():
            if actual_version != canonical_rules_version:
                errors.append(
                    f"{filename}: rules_version mismatch "
                    f"actual={actual_version}, expected={canonical_rules_version}"
                )

    if canonical_rules_hash:
        control_hashes = {
            "status.json": status.get("rules_sha256"),
            "manifest.json": (
                manifest.get("rules_sha256")
                or manifest.get("rules", {}).get("sha256")
            ),
            "stock_table_rules.json": rules.get("rules_sha256"),
        }
        for filename, actual_hash in control_hashes.items():
            if actual_hash != canonical_rules_hash:
                errors.append(
                    f"{filename}: rules_sha256 mismatch with canonical rules file"
                )

    for item in manifest_tables:
        if not isinstance(item, dict) or not item.get("api_file"):
            continue
        table_path = Path(item["api_file"])
        if table_path.parts and table_path.parts[0] == api.name:
            table_path = api.parent / table_path
        elif not table_path.is_absolute():
            table_path = api / table_path.name

        table_payload = read_json(table_path)
        if not table_payload:
            continue

        table_id = item.get("table_id")
        table_rules_version = (
            table_payload.get("rules_version")
            or table_payload.get("rules", {}).get("version")
        )
        table_rules_hash = (
            table_payload.get("rules_sha256")
            or table_payload.get("rules", {}).get("sha256")
        )

        if (
            canonical_rules_version
            and table_rules_version != canonical_rules_version
        ):
            errors.append(
                f"{table_id}: canonical rules_version mismatch "
                f"actual={table_rules_version}, expected={canonical_rules_version}"
            )

        if canonical_rules_hash and table_rules_hash != canonical_rules_hash:
            errors.append(
                f"{table_id}: canonical rules_sha256 mismatch"
            )
    # RULES_VERSION_CONTRACT_END

    # REQUEST_TIME_PRICE_CONTRACT_V51_BEGIN
    request_policy = status.get("request_time_price_policy") or {}
    required_request_policy = {
        "enabled": True,
        "mode": "request_time_dynamic_overlay",
        "lookup_scope": "all_rows_in_requested_table",
        "action_operation_id": "getRequestTimePrices",
        "health_operation_id": "getRequestTimePriceHealth",
        "api_base_url": "https://krx-live-price-ksh.diaconos.workers.dev",
        "max_batch_size": 10,
        "preserve_official_history": True,
        "allow_last_confirmed_official_when_delayed": True,
    }

    for policy_key, expected_value in required_request_policy.items():
        actual_value = request_policy.get(policy_key)
        if actual_value != expected_value:
            errors.append(
                "request_time_price_policy mismatch: "
                f"{policy_key}={actual_value!r}, expected={expected_value!r}"
            )

    for control_name, control_payload in (
        ("manifest.json", manifest),
        ("stock_table_rules.json", rules),
    ):
        if control_payload.get("request_time_price_policy") != request_policy:
            errors.append(
                f"{control_name}: request_time_price_policy mismatch"
            )

    quote_key_candidates = {
        "ticker",
        "symbol",
        "code",
        "종목코드",
        "stock_code",
    }
    manifest_tables_v51 = manifest.get("tables", [])
    if not isinstance(manifest_tables_v51, list) or not manifest_tables_v51:
        errors.append("manifest tables missing for request-time price validation")
    else:
        for table_item in manifest_tables_v51:
            if not isinstance(table_item, dict):
                errors.append("manifest table item is not an object")
                continue

            table_id = table_item.get("table_id")
            api_file = table_item.get("api_file")
            if not api_file:
                errors.append(f"{table_id}: api_file missing")
                continue

            table_path = Path(str(api_file))
            if table_path.parts and table_path.parts[0] == api.name:
                table_path = api.parent / table_path
            elif not table_path.is_absolute():
                table_path = api / table_path.name

            table_payload = read_json(table_path)
            if not table_payload:
                errors.append(f"{table_id}: table API missing or invalid")
                continue

            if table_payload.get("request_time_price_policy") != request_policy:
                errors.append(
                    f"{table_id}: request_time_price_policy mismatch"
                )

            row_count = int(table_payload.get("row_count") or 0)
            columns = set(table_payload.get("columns") or [])
            if row_count > 0 and not (columns & quote_key_candidates):
                errors.append(
                    f"{table_id}: quote key column missing for live lookup (ticker/symbol/code/종목코드/stock_code)"
                )

    # HOLDINGS_EXACT_TICKER_CONTRACT_V824_BEGIN
    holdings_manifest = read_json(
        api / "stock_reference_manifest.json"
    )
    if not holdings_manifest:
        errors.append(
            "stock_reference_manifest.json missing or invalid"
        )
    else:
        action_contract = holdings_manifest.get(
            "action_contract"
        ) or {}
        usage = holdings_manifest.get("usage") or {}
        if action_contract.get("operation_id") != (
            "getStockReferenceShard"
        ):
            errors.append(
                "holdings exact-ticker operation contract missing"
            )
        if action_contract.get("required_parameters") != [
            "prefix",
            "ticker",
        ]:
            errors.append(
                "holdings required parameters must be prefix+ticker"
            )
        if action_contract.get(
            "prefix_only_call_forbidden"
        ) is not True:
            errors.append(
                "holdings prefix-only call must be forbidden"
            )
        if usage.get("prefix_only_call_forbidden") is not True:
            errors.append(
                "holdings usage allows prefix-only call"
            )
        step_3 = str(usage.get("step_3") or "")
        if not all(
            token in step_3
            for token in ("prefix", "ticker", "market")
        ):
            errors.append(
                "holdings usage step_3 lacks exact parameters"
            )

    canonical_schema_path = (
        api.parent / "docs" / "custom_gpt_action_schema.yaml"
    )
    if not canonical_schema_path.exists():
        errors.append("canonical custom GPT schema missing")
    else:
        schema_text = canonical_schema_path.read_text(
            encoding="utf-8"
        )
        required_tokens = (
            "version: 7.0.1",
            "https://krx-live-price-ksh.diaconos.workers.dev",
            "operationId: getStockReferenceShard",
            "name: ticker",
            "name: market",
        )
        for token in required_tokens:
            if token not in schema_text:
                errors.append(
                    "canonical custom GPT schema missing token: "
                    + token
                )
        if "https://raw.githubusercontent.com" in schema_text:
            errors.append(
                "raw GitHub Action domain is forbidden"
            )
        if schema_text.count("\n- url: ") != 1:
            errors.append(
                "canonical custom GPT schema must use one server"
            )

    instructions_path = (
        api.parent / "docs" / "custom_gpt_instructions.md"
    )
    if not instructions_path.exists():
        errors.append("canonical custom GPT instructions missing")
    else:
        instructions_text = instructions_path.read_text(
            encoding="utf-8"
        )
        instruction_tokens = (
            "2026-07-16-v6.8.1-holdings-exact-filter",
            "## 12. 보유종목표 개인정보 비저장 런타임",
            "getStockReferenceShard를 prefix만으로 호출하지 않는다.",
        )
        for token in instruction_tokens:
            if token not in instructions_text:
                errors.append(
                    "canonical custom GPT instructions missing "
                    "token: " + token
                )
    # HOLDINGS_EXACT_TICKER_CONTRACT_V824_END

    live_schema_path = (
        api.parent / "docs" / "custom_gpt_live_price_action_schema.yaml"
    )
    if not live_schema_path.exists():
        errors.append("custom_gpt_live_price_action_schema.yaml missing")
    else:
        live_schema_text = live_schema_path.read_text(encoding="utf-8")
        required_schema_tokens = (
            "operationId: getRequestTimePriceHealth",
            "operationId: getRequestTimePrices",
            "https://krx-live-price-ksh.diaconos.workers.dev",
        )
        for schema_token in required_schema_tokens:
            if schema_token not in live_schema_text:
                errors.append(
                    f"live price action schema missing token: {schema_token}"
                )
    # REQUEST_TIME_PRICE_CONTRACT_V51_END

    report = {
        "script": SCRIPT_VERSION,
        "validated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "PASS" if not errors else "FAIL",
        "build_id": next(iter(build_ids)) if len(build_ids) == 1 else None,
        "api_sync_ok": not errors,
        "official_fresh_now": status.get("official_fresh_now") if status else None,
        "safe_to_analyze_as_latest": bool(
            not errors and status.get("official_fresh_now") if status else False
        ),
        "errors": errors,
        "warnings": warnings,
    }
    write_json(api / "validation_report.json", report)

    print(f"API_VALIDATION_STATUS={report['status']}")
    print(f"API_VALIDATION_ERROR_COUNT={len(errors)}")
    print(f"API_VALIDATION_WARNING_COUNT={len(warnings)}")
    for error in errors:
        print(f"ERROR: {error}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
