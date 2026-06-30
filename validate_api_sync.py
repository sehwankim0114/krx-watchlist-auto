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
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_VERSION = "validate_api_sync.py v1.2_strict_contract"


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
