#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V8.2 contract for the 13 Korean table commands exposed to Custom GPT."""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional


CONTRACT_VERSION = "2026-07-15-v8.2-command-route-contract"
SCHEMA_VERSION = "8.2"
WORKER_ORIGIN = "https://krx-live-price-ksh.diaconos.workers.dev"

# This list is copied from the Action operation list verified in the Custom GPT
# end-to-end inspection on 2026-07-15 KST.  V8.2 does not add an Action and does
# not add another domain; it only describes how existing operations form the
# 13 user-facing table commands.
ACTION_OPERATION_IDS = frozenset(
    {
        "getRequestTimePriceHealth",
        "getRequestTimePrices",
        "getApiStatus",
        "getApiManifest",
        "getApiValidationReport",
        "getStockTableRules",
        "getWatchlist",
        "getKospiWatchlist",
        "getKosdaqWatchlist",
        "getKospiCandidates",
        "getKosdaqCandidates",
        "getKospiOneMonthCandidates",
        "getKospiOneMonthRecommendations",
        "getKosdaqOneMonthCandidates",
        "getKosdaqOneMonthRecommendations",
        "getKospiGainers",
        "getMonthlyCycle",
        "getFxWeaknessCandidates",
        "getShortTermCandidates",
        "getOfficialDataStatus",
        "getCurrentPriceBasis",
        "getDataFreshnessNotice",
        "getTableHealth",
        "getMarketStatus",
        "getMacroLeverage",
        "getBubbleRisk",
        "getHoldingsReferenceManifest",
        "getStockReferenceShard",
        "getUsWatchlist",
        "getUsWatchlistRecommendations",
    }
)


COMMAND_ROUTES: List[Dict[str, Any]] = [
    {
        "command": "관종표",
        "table_id": "watchlist",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getWatchlist",
        "operation_ids": ["getWatchlist"],
        "api_file": "api/watchlist.json",
        "manifest_collection": "tables",
        "manifest_id": "watchlist",
        "actual_output_available": True,
    },
    {
        "command": "분석표",
        "table_id": "analysis",
        "source_table_id": "watchlist",
        "alias_of": "관종표",
        "route_mode": "ALIAS_RENDER",
        "status": "READY_ALIAS",
        "operation_id": "getWatchlist",
        "operation_ids": ["getWatchlist"],
        "api_file": "api/watchlist.json",
        "manifest_collection": "tables",
        "manifest_id": "watchlist",
        "actual_output_available": True,
        "note": "관종표 데이터를 종목 분석 보기로 출력하는 의도된 별칭",
    },
    {
        "command": "코피표",
        "table_id": "kospi_watchlist",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getKospiWatchlist",
        "operation_ids": ["getKospiWatchlist", "getKospiCandidates"],
        "api_file": "api/kospi_watchlist.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_watchlist",
        "actual_output_available": True,
    },
    {
        "command": "코피표1개월",
        "table_id": "kospi_1m_candidates_30",
        "route_mode": "DIRECT_ACTION_WITH_RECOMMENDATION_VIEW",
        "status": "READY_DIRECT",
        "operation_id": "getKospiOneMonthCandidates",
        "operation_ids": [
            "getKospiOneMonthCandidates",
            "getKospiOneMonthRecommendations",
        ],
        "api_file": "api/kospi_1m_candidates_30.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_1m_candidates_30",
        "actual_output_available": True,
    },
    {
        "command": "코닥표",
        "table_id": "kosdaq_watchlist",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getKosdaqWatchlist",
        "operation_ids": ["getKosdaqWatchlist", "getKosdaqCandidates"],
        "api_file": "api/kosdaq_watchlist.json",
        "manifest_collection": "tables",
        "manifest_id": "kosdaq_watchlist",
        "actual_output_available": True,
    },
    {
        "command": "코닥표1개월",
        "table_id": "kosdaq_1m_candidates_10",
        "route_mode": "DIRECT_ACTION_WITH_RECOMMENDATION_VIEW",
        "status": "READY_DIRECT",
        "operation_id": "getKosdaqOneMonthCandidates",
        "operation_ids": [
            "getKosdaqOneMonthCandidates",
            "getKosdaqOneMonthRecommendations",
        ],
        "api_file": "api/kosdaq_1m_candidates_10.json",
        "manifest_collection": "tables",
        "manifest_id": "kosdaq_1m_candidates_10",
        "actual_output_available": True,
    },
    {
        "command": "코급표",
        "table_id": "kospi_gainers_1m",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getKospiGainers",
        "operation_ids": ["getKospiGainers"],
        "api_file": "api/kospi_gainers_1m.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_gainers_1m",
        "actual_output_available": True,
    },
    {
        "command": "월사이클표",
        "table_id": "kospi_monthly_cycle",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getMonthlyCycle",
        "operation_ids": ["getMonthlyCycle"],
        "api_file": "api/kospi_monthly_cycle.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_monthly_cycle",
        "actual_output_available": True,
    },
    {
        "command": "단상표",
        "table_id": "kospi_short_term_candidates_30",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getShortTermCandidates",
        "operation_ids": ["getShortTermCandidates"],
        "api_file": "api/kospi_short_term_candidates_30.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_short_term_candidates_30",
        "actual_output_available": True,
    },
    {
        "command": "환율약세표",
        "table_id": "kospi_fx_weakness_candidates_30",
        "route_mode": "DIRECT_ACTION",
        "status": "READY_DIRECT",
        "operation_id": "getFxWeaknessCandidates",
        "operation_ids": ["getFxWeaknessCandidates"],
        "api_file": "api/kospi_fx_weakness_candidates_30.json",
        "manifest_collection": "tables",
        "manifest_id": "kospi_fx_weakness_candidates_30",
        "actual_output_available": True,
    },
    {
        "command": "시장상태표",
        "table_id": "market_status",
        "route_mode": "SNAPSHOT_ACTION",
        "status": "READY_SNAPSHOT",
        "operation_id": "getMarketStatus",
        "operation_ids": ["getMarketStatus"],
        "api_file": "api/market_status.json",
        "manifest_collection": "snapshots",
        "manifest_id": "market_status",
        "actual_output_available": True,
    },
    {
        "command": "보유종목표",
        "table_id": "holdings_private_runtime",
        "route_mode": "PRIVATE_RUNTIME_COMPOSITE",
        "status": "READY_PRIVATE_RUNTIME",
        "operation_id": "getHoldingsReferenceManifest",
        "operation_ids": [
            "getHoldingsReferenceManifest",
            "getStockReferenceShard",
        ],
        "api_file": None,
        "manifest_collection": None,
        "manifest_id": None,
        "actual_output_available": True,
        "private_runtime_input_required": True,
        "public_holdings_storage": False,
        "missing_public_file_is_error": False,
        "note": (
            "보유수량·매입가는 공개 저장소에 저장하지 않고 대화 시점의 "
            "비공개 입력과 공개 종목 참고자료를 런타임에서 결합"
        ),
    },
    {
        "command": "미관종표",
        "table_id": "us_watchlist",
        "route_mode": "DIRECT_ACTION_WITH_RECOMMENDATION_VIEW",
        "status": "READY_DIRECT",
        "operation_id": "getUsWatchlist",
        "operation_ids": ["getUsWatchlist", "getUsWatchlistRecommendations"],
        "api_file": "api/us_watchlist.json",
        "manifest_collection": "tables",
        "manifest_id": "us_watchlist",
        "actual_output_available": True,
    },
]


def _manifest_item(
    manifest: Mapping[str, Any],
    collection: Optional[str],
    item_id: Optional[str],
) -> Optional[Mapping[str, Any]]:
    if not collection or not item_id:
        return None
    id_key = "table_id" if collection == "tables" else "snapshot_id"
    entries = manifest.get(collection)
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get(id_key) == item_id:
            return entry
    return None


def _operation_usage(
    routes: Iterable[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    usage: Dict[str, List[str]] = defaultdict(list)
    for route in routes:
        for operation_id in route.get("operation_ids", []):
            usage[str(operation_id)].append(str(route["command"]))
    return {key: value for key, value in sorted(usage.items())}


def validate_static_contract() -> None:
    commands = [route["command"] for route in COMMAND_ROUTES]
    if len(commands) != 13 or len(commands) != len(set(commands)):
        raise ValueError(f"13 unique commands required: {commands}")

    for route in COMMAND_ROUTES:
        operations = route.get("operation_ids")
        if not isinstance(operations, list) or not operations:
            raise ValueError(f"operation_ids missing: {route['command']}")
        if route.get("operation_id") != operations[0]:
            raise ValueError(f"primary operation mismatch: {route['command']}")
        unknown = set(operations) - ACTION_OPERATION_IDS
        if unknown:
            raise ValueError(f"unknown Action operation: {sorted(unknown)}")
        if not str(route.get("status", "")).startswith("READY_"):
            raise ValueError(f"route not ready: {route['command']}")

    holdings = next(
        route for route in COMMAND_ROUTES if route["command"] == "보유종목표"
    )
    if holdings.get("api_file") is not None:
        raise ValueError("holdings must not have a public API file")
    if holdings.get("public_holdings_storage") is not False:
        raise ValueError("public holdings storage must remain disabled")

    usage = _operation_usage(COMMAND_ROUTES)
    shared = {key: value for key, value in usage.items() if len(value) > 1}
    expected = {"getWatchlist": ["관종표", "분석표"]}
    if shared != expected:
        raise ValueError(f"unexpected shared operations: {shared}")


def build_command_route_contract_v82(
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    validate_static_contract()
    routes = copy.deepcopy(COMMAND_ROUTES)

    for route in routes:
        item = _manifest_item(
            manifest,
            route.get("manifest_collection"),
            route.get("manifest_id"),
        )
        route["manifest_item_present"] = item is not None
        if item is not None:
            route["data_status"] = item.get("status")
            if "row_count" in item:
                route["row_count"] = item.get("row_count")
        elif route["route_mode"] == "PRIVATE_RUNTIME_COMPOSITE":
            route["data_status"] = "PRIVATE_INPUT_AT_REQUEST_TIME"
        else:
            route["data_status"] = "MANIFEST_ITEM_NOT_PRESENT"

    usage = _operation_usage(routes)
    shared = {key: value for key, value in usage.items() if len(value) > 1}
    intentional = {"getWatchlist": ["관종표", "분석표"]}
    conflicts = {
        key: value for key, value in shared.items() if intentional.get(key) != value
    }

    ready_count = sum(
        1 for route in routes if str(route["status"]).startswith("READY_")
    )
    output_count = sum(bool(route["actual_output_available"]) for route in routes)

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "single_action_domain": WORKER_ORIGIN,
        "action_domain_count": 1,
        "raw_github_action_required": False,
        "command_count": len(routes),
        "ready_count": ready_count,
        "actual_output_available_count": output_count,
        "structure_ok": (
            len(routes) == 13
            and ready_count == 13
            and output_count == 13
            and not conflicts
        ),
        "intentional_shared_operation_ids": intentional,
        "duplicate_operation_id_conflicts": conflicts,
        "commands": routes,
    }


def attach_command_route_contract_v82(
    manifest: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    contract = build_command_route_contract_v82(manifest)
    # Preserve the 13-command core; explicit two-command extension is versioned.
    from two_table_release_v853 import attach_routes
    attach_routes(contract)
    manifest["command_route_contract"] = contract
    manifest["command_route_summary"] = {
        "contract_version": contract["contract_version"],
        "command_count": contract["command_count"],
        "ready_count": contract["ready_count"],
        "actual_output_available_count": contract[
            "actual_output_available_count"
        ],
        "structure_ok": contract["structure_ok"],
        "single_action_domain": contract["single_action_domain"],
    }
    return manifest


def self_test() -> None:
    fake_manifest = {
        "tables": [
            {
                "table_id": route["manifest_id"],
                "status": "OK",
                "row_count": 1,
            }
            for route in COMMAND_ROUTES
            if route.get("manifest_collection") == "tables"
            and route["command"] != "분석표"
        ],
        "snapshots": [
            {"snapshot_id": "market_status", "status": "OK"}
        ],
    }
    attached = attach_command_route_contract_v82(fake_manifest)
    contract = attached["command_route_contract"]
    assert contract["command_count"] == 13
    assert contract["ready_count"] == 13
    assert contract["actual_output_available_count"] == 13
    assert contract["structure_ok"] is True
    analysis = next(
        row for row in contract["commands"] if row["command"] == "분석표"
    )
    assert analysis["manifest_item_present"] is True
    holdings = next(
        row for row in contract["commands"] if row["command"] == "보유종목표"
    )
    assert holdings["manifest_item_present"] is False
    assert holdings["data_status"] == "PRIVATE_INPUT_AT_REQUEST_TIME"
    print("TABLE_COMMAND_ROUTES_V82_SELF_TEST=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
