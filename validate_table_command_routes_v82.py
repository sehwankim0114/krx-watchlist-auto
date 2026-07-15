#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the generated V8.2 13-command route contract."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from table_command_routes_v82 import (
    ACTION_OPERATION_IDS,
    CONTRACT_VERSION,
    WORKER_ORIGIN,
)


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "api" / "manifest.json"
EXPECTED_COMMANDS = [
    "관종표",
    "분석표",
    "코피표",
    "코피표1개월",
    "코닥표",
    "코닥표1개월",
    "코급표",
    "월사이클표",
    "단상표",
    "환율약세표",
    "시장상태표",
    "보유종목표",
    "미관종표",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"object required: {path}")
    return data


def operation_usage(
    routes: Iterable[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = defaultdict(list)
    for route in routes:
        for operation_id in route["operation_ids"]:
            result[operation_id].append(route["command"])
    return dict(result)


def main() -> int:
    require(MANIFEST.exists(), f"missing manifest: {MANIFEST}")
    manifest = load_json(MANIFEST)
    contract = manifest.get("command_route_contract")
    summary = manifest.get("command_route_summary")
    require(isinstance(contract, dict), "command_route_contract missing")
    require(isinstance(summary, dict), "command_route_summary missing")

    require(
        contract.get("contract_version") == CONTRACT_VERSION,
        "contract_version mismatch",
    )
    require(
        contract.get("single_action_domain") == WORKER_ORIGIN,
        "single Worker origin mismatch",
    )
    require(contract.get("action_domain_count") == 1, "domain count must be 1")
    require(
        contract.get("raw_github_action_required") is False,
        "raw GitHub Action must remain disabled",
    )
    require(contract.get("command_count") == 13, "command_count must be 13")
    require(contract.get("ready_count") == 13, "ready_count must be 13")
    require(
        contract.get("actual_output_available_count") == 13,
        "all 13 commands must be output-capable",
    )
    require(contract.get("structure_ok") is True, "structure_ok must be true")
    require(
        contract.get("duplicate_operation_id_conflicts") == {},
        "operationId conflicts must be empty",
    )

    routes = contract.get("commands")
    require(isinstance(routes, list), "commands must be a list")
    require(
        [route.get("command") for route in routes] == EXPECTED_COMMANDS,
        "command order or names differ",
    )
    by_command = {route["command"]: route for route in routes}

    for route in routes:
        require(
            str(route.get("status", "")).startswith("READY_"),
            f"not ready: {route['command']}",
        )
        require(
            route.get("actual_output_available") is True,
            f"not output-capable: {route['command']}",
        )
        operations = route.get("operation_ids")
        require(isinstance(operations, list) and operations, "operations missing")
        require(
            route.get("operation_id") == operations[0],
            f"primary operation mismatch: {route['command']}",
        )
        require(
            set(operations).issubset(ACTION_OPERATION_IDS),
            f"unknown Action operation: {route['command']}",
        )
        api_file = route.get("api_file")
        if api_file:
            require((ROOT / api_file).exists(), f"missing API file: {api_file}")

    analysis = by_command["분석표"]
    require(analysis.get("route_mode") == "ALIAS_RENDER", "analysis alias lost")
    require(analysis.get("alias_of") == "관종표", "analysis alias target differs")
    require(
        analysis.get("operation_id") == "getWatchlist",
        "analysis must intentionally share getWatchlist",
    )
    require(
        analysis.get("manifest_item_present") is True,
        "analysis source watchlist is absent",
    )

    holdings = by_command["보유종목표"]
    require(
        holdings.get("status") == "READY_PRIVATE_RUNTIME",
        "holdings private runtime status lost",
    )
    require(holdings.get("api_file") is None, "public holdings file is forbidden")
    require(
        holdings.get("public_holdings_storage") is False,
        "public holdings storage must be false",
    )
    require(
        holdings.get("missing_public_file_is_error") is False,
        "missing public holdings file must not be an error",
    )
    require(
        holdings.get("operation_ids")
        == ["getHoldingsReferenceManifest", "getStockReferenceShard"],
        "holdings reference operations differ",
    )

    require(
        by_command["미관종표"].get("status") == "READY_DIRECT",
        "US watchlist must be READY_DIRECT",
    )
    require(
        by_command["시장상태표"].get("manifest_collection") == "snapshots",
        "market status must use snapshot collection",
    )

    shared = {
        key: value
        for key, value in operation_usage(routes).items()
        if len(value) > 1
    }
    require(
        shared == {"getWatchlist": ["관종표", "분석표"]},
        f"unexpected operation sharing: {shared}",
    )

    serialized = json.dumps(manifest, ensure_ascii=False)
    require(
        "raw.githubusercontent.com" not in serialized,
        "raw GitHub domain must not appear in the manifest contract",
    )
    require(summary.get("ready_count") == 13, "summary ready_count differs")
    require(summary.get("structure_ok") is True, "summary structure failed")

    print(f"CONTRACT_VERSION={CONTRACT_VERSION}")
    print("COMMAND_COUNT=13")
    print("READY_COUNT=13")
    print("ACTUAL_OUTPUT_AVAILABLE_COUNT=13")
    print("ANALYSIS_ROUTE=READY_ALIAS:getWatchlist")
    print(
        "HOLDINGS_ROUTE=READY_PRIVATE_RUNTIME:"
        "getHoldingsReferenceManifest,getStockReferenceShard"
    )
    print("US_WATCHLIST_ROUTE=READY_DIRECT:getUsWatchlist")
    print("INTENTIONAL_SHARED_OPERATION=getWatchlist:관종표,분석표")
    print("DUPLICATE_OPERATION_ID_CONFLICTS=0")
    print(f"SINGLE_ACTION_DOMAIN={WORKER_ORIGIN}")
    print("RAW_GITHUB_ACTION_REQUIRED=false")
    print("THIRTEEN_COMMAND_ROUTE_CONTRACT_V82=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
