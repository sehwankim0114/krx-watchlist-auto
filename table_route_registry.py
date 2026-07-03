#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
table_route_registry.py v1.0.0-thirteen-table-contract

국내·미국 주식표 13종의 생성경로를 하나의 계약으로 관리한다.

검사 대상
1. 관종표
2. 분석표
3. 코피표
4. 코피표1개월
5. 코닥표
6. 코닥표1개월
7. 코급표
8. 월사이클표
9. 단상표
10. 환율약세표
11. 시장상태표
12. 보유종목표
13. 미관종표

상태
- READY_DIRECT: 전용 원본 + API + Custom GPT Action 존재
- READY_SHARED: 다른 본표 경로를 의도적으로 공유
- READY_COMPOSITE: 여러 상태 API를 조합
- MISSING: 생성경로 일부 또는 전부 없음
- BROKEN: 있어야 하는 기존 경로가 손상됨

현재 v6 전환 기준
- 기존 정상경로 9개는 반드시 유지되어야 한다.
- 계획된 미완성 경로 4개는 MISSING으로 명시한다.
- 누락을 숨기거나 READY로 가장하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional


# ONE_MONTH_ROUTES_READY_V6
# HOLDINGS_PRIVATE_RUNTIME_READY_V6
# US_WATCHLIST_ROUTE_READY_V6
SCRIPT_VERSION = "table_route_registry.py v1.0.0-thirteen-table-contract"
POLICY_VERSION = "2026-07-01-v6.0-thirteen-table-route-contract"
KST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "latest"
API = ROOT / "api"
DOCS = ROOT / "docs"

BUILD_SCRIPT = ROOT / "build_api_json.py"
ACTION_SCHEMA = DOCS / "custom_gpt_action_schema.yaml"
RULES_FILE = DOCS / "stock_table_rules_latest.md"

OUTPUT_JSON = LATEST / "table_route_registry_latest.json"
OUTPUT_CSV = LATEST / "table_route_registry_latest.csv"
OUTPUT_LOG = LATEST / "table_route_registry_run_log_latest.txt"


@dataclass(frozen=True)
class RouteContract:
    route_id: str
    display_name: str
    request_terms: tuple[str, ...]
    generation_mode: str
    source_candidates: tuple[str, ...]
    api_files: tuple[str, ...]
    operation_ids: tuple[str, ...]
    shared_with: str = ""
    required_now: bool = False
    planned_missing: bool = False
    next_step: str = ""


ROUTES: tuple[RouteContract, ...] = (
    RouteContract(
        route_id="watchlist",
        display_name="관종표",
        request_terms=("관종표",),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/watchlist_summary_current_basis_latest.csv",
            "latest/watchlist_summary_latest.csv",
        ),
        api_files=("api/watchlist.json",),
        operation_ids=("getWatchlist",),
        required_now=True,
    ),
    RouteContract(
        route_id="analysis",
        display_name="분석표",
        request_terms=("분석표", "개별 기업 분석"),
        generation_mode="SHARED",
        source_candidates=(),
        api_files=(),
        operation_ids=(),
        shared_with="watchlist",
        required_now=True,
        next_step=(
            "관심종목 비교는 관종표 경로를 공유하고, 개별 기업은 "
            "같은 행을 심화 해석한다."
        ),
    ),
    RouteContract(
        route_id="kospi",
        display_name="코피표",
        request_terms=("코피표", "코스피", "코스피 줘"),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_candidates_30_current_basis_latest.csv",
            "latest/kospi_candidates_30_latest.csv",
        ),
        api_files=("api/kospi_candidates_30.json",),
        operation_ids=("getKospiCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="kospi_1m",
        display_name="코피표1개월",
        request_terms=("코피표1개월", "코스피 1개월"),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_1m_candidates_30_current_basis_latest.csv",
            "latest/kospi_1m_candidates_30_latest.csv",
        ),
        api_files=("api/kospi_1m_candidates_30.json",),
        operation_ids=("getKospiOneMonthCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="kosdaq",
        display_name="코닥표",
        request_terms=("코닥표", "코스닥", "코스닥 줘"),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kosdaq_candidates_10_current_basis_latest.csv",
            "latest/kosdaq_candidates_10_latest.csv",
        ),
        api_files=("api/kosdaq_candidates_10.json",),
        operation_ids=("getKosdaqCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="kosdaq_1m",
        display_name="코닥표1개월",
        request_terms=("코닥표1개월", "코스닥 1개월"),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kosdaq_1m_candidates_10_current_basis_latest.csv",
            "latest/kosdaq_1m_candidates_10_latest.csv",
        ),
        api_files=("api/kosdaq_1m_candidates_10.json",),
        operation_ids=("getKosdaqOneMonthCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="kospi_gainers",
        display_name="코급표",
        request_terms=("코급표",),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_gainers_1m_current_basis_latest.csv",
            "latest/kospi_gainers_1m_latest.csv",
        ),
        api_files=("api/kospi_gainers_1m.json",),
        operation_ids=("getKospiGainers",),
        required_now=True,
    ),
    RouteContract(
        route_id="monthly_cycle",
        display_name="월사이클표",
        request_terms=("월사이클표",),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_monthly_cycle_latest.csv",
        ),
        api_files=("api/kospi_monthly_cycle.json",),
        operation_ids=("getMonthlyCycle",),
        required_now=True,
    ),
    RouteContract(
        route_id="short_term",
        display_name="단상표",
        request_terms=("단상표",),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_short_term_candidates_30_latest.csv",
        ),
        api_files=("api/kospi_short_term_candidates_30.json",),
        operation_ids=("getShortTermCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="fx_weakness",
        display_name="환율약세표",
        request_terms=("환율약세표",),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/kospi_fx_weakness_candidates_30_latest.csv",
        ),
        api_files=("api/kospi_fx_weakness_candidates_30.json",),
        operation_ids=("getFxWeaknessCandidates",),
        required_now=True,
    ),
    RouteContract(
        route_id="market_status",
        display_name="시장상태표",
        request_terms=("시장상태표", "시장 상태"),
        generation_mode="COMPOSITE",
        source_candidates=(
            "latest/data_status_latest.json",
            "latest/macro_leverage_latest.json",
            "latest/bubble_risk_latest.json",
        ),
        api_files=(
            "api/market_status.json",
            "api/macro_leverage.json",
            "api/bubble_risk.json",
        ),
        operation_ids=(
            "getMarketStatus",
            "getMacroLeverage",
            "getBubbleRisk",
        ),
        required_now=True,
    ),
    RouteContract(
        route_id="holdings",
        display_name="보유종목표",
        request_terms=("보유종목표", "보유주식표"),
        generation_mode="PRIVATE_RUNTIME",
        source_candidates=(
            "holdings_table.py",
            "build_stock_reference_api.py",
            "docs/holdings_private_runtime_contract.md",
        ),
        api_files=(
            "api/stock_reference_manifest.json",
        ),
        operation_ids=(
            "getHoldingsReferenceManifest",
            "getStockReferenceShard",
        ),
        required_now=True,
        next_step=(
            "사용자 보유수량·평균매수가는 대화에서만 사용하고 "
            "공개 종목 참고 shard와 결합해 응답 시점에 계산한다."
        ),
    ),
    RouteContract(
        route_id="us_watchlist",
        display_name="미관종표",
        request_terms=("미관종표", "미국 관종표"),
        generation_mode="DIRECT",
        source_candidates=(
            "latest/us_sp500_watchlist_latest.csv",
        ),
        api_files=("api/us_watchlist.json",),
        operation_ids=("getUsWatchlist",),
        required_now=True,
    ),
)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def existing_paths(candidates: Iterable[str]) -> list[str]:
    return [
        path
        for path in candidates
        if (ROOT / path).exists()
    ]


def missing_paths(candidates: Iterable[str]) -> list[str]:
    return [
        path
        for path in candidates
        if not (ROOT / path).exists()
    ]


def operation_presence(
    operation_ids: Iterable[str],
    schema_text: str,
) -> tuple[list[str], list[str]]:
    present = []
    missing = []
    for operation_id in operation_ids:
        marker = f"operationId: {operation_id}"
        if marker in schema_text:
            present.append(operation_id)
        else:
            missing.append(operation_id)
    return present, missing


def direct_status(
    contract: RouteContract,
    schema_text: str,
) -> dict:
    source_existing = existing_paths(contract.source_candidates)
    api_existing = existing_paths(contract.api_files)
    operation_existing, operation_missing = operation_presence(
        contract.operation_ids,
        schema_text,
    )

    source_ok = bool(source_existing)
    api_ok = len(api_existing) == len(contract.api_files)
    operation_ok = (
        len(operation_existing) == len(contract.operation_ids)
    )

    if source_ok and api_ok and operation_ok:
        status = "READY_DIRECT"
    elif contract.planned_missing:
        status = "MISSING"
    elif contract.required_now:
        status = "BROKEN"
    else:
        status = "MISSING"

    missing_components = []
    if not source_ok:
        missing_components.append("SOURCE")
    if not api_ok:
        missing_components.append("API")
    if not operation_ok:
        missing_components.append("ACTION")

    return {
        "status": status,
        "source_existing": source_existing,
        "source_missing": missing_paths(contract.source_candidates),
        "api_existing": api_existing,
        "api_missing": missing_paths(contract.api_files),
        "operation_existing": operation_existing,
        "operation_missing": operation_missing,
        "missing_components": missing_components,
    }


def composite_status(
    contract: RouteContract,
    schema_text: str,
) -> dict:
    source_existing = existing_paths(contract.source_candidates)
    api_existing = existing_paths(contract.api_files)
    operation_existing, operation_missing = operation_presence(
        contract.operation_ids,
        schema_text,
    )

    source_ok = len(source_existing) == len(contract.source_candidates)
    api_ok = len(api_existing) == len(contract.api_files)
    operation_ok = (
        len(operation_existing) == len(contract.operation_ids)
    )

    status = (
        "READY_COMPOSITE"
        if source_ok and api_ok and operation_ok
        else "BROKEN"
    )

    missing_components = []
    if not source_ok:
        missing_components.append("SOURCE")
    if not api_ok:
        missing_components.append("API")
    if not operation_ok:
        missing_components.append("ACTION")

    return {
        "status": status,
        "source_existing": source_existing,
        "source_missing": missing_paths(contract.source_candidates),
        "api_existing": api_existing,
        "api_missing": missing_paths(contract.api_files),
        "operation_existing": operation_existing,
        "operation_missing": operation_missing,
        "missing_components": missing_components,
    }


def private_runtime_status(
    contract: RouteContract,
    schema_text: str,
) -> dict:
    source_existing = existing_paths(contract.source_candidates)
    api_existing = existing_paths(contract.api_files)
    operation_existing, operation_missing = operation_presence(
        contract.operation_ids,
        schema_text,
    )
    source_ok = (
        len(source_existing) == len(contract.source_candidates)
    )
    api_ok = len(api_existing) == len(contract.api_files)
    operation_ok = (
        len(operation_existing) == len(contract.operation_ids)
    )
    if source_ok and api_ok and operation_ok:
        status = "READY_PRIVATE_RUNTIME"
    elif contract.required_now:
        status = "BROKEN"
    else:
        status = "MISSING"
    missing_components = []
    if not source_ok:
        missing_components.append("SOURCE")
    if not api_ok:
        missing_components.append("API")
    if not operation_ok:
        missing_components.append("ACTION")
    return {
        "status": status,
        "source_existing": source_existing,
        "source_missing": missing_paths(
            contract.source_candidates
        ),
        "api_existing": api_existing,
        "api_missing": missing_paths(contract.api_files),
        "operation_existing": operation_existing,
        "operation_missing": operation_missing,
        "missing_components": missing_components,
    }


def evaluate_routes() -> list[dict]:
    schema_text = read_text(ACTION_SCHEMA)
    results: list[dict] = []
    by_id: dict[str, dict] = {}

    for contract in ROUTES:
        base = asdict(contract)
        base["request_terms"] = list(contract.request_terms)
        base["source_candidates"] = list(contract.source_candidates)
        base["api_files"] = list(contract.api_files)
        base["operation_ids"] = list(contract.operation_ids)

        if contract.generation_mode == "SHARED":
            shared = by_id.get(contract.shared_with)
            if shared and shared["status"].startswith("READY"):
                check = {
                    "status": "READY_SHARED",
                    "source_existing": shared["source_existing"],
                    "source_missing": [],
                    "api_existing": shared["api_existing"],
                    "api_missing": [],
                    "operation_existing": shared["operation_existing"],
                    "operation_missing": [],
                    "missing_components": [],
                }
            else:
                check = {
                    "status": "BROKEN",
                    "source_existing": [],
                    "source_missing": [],
                    "api_existing": [],
                    "api_missing": [],
                    "operation_existing": [],
                    "operation_missing": [],
                    "missing_components": ["SHARED_ROUTE"],
                }
        elif contract.generation_mode == "PRIVATE_RUNTIME":
            check = private_runtime_status(
                contract,
                schema_text,
            )
        elif contract.generation_mode == "COMPOSITE":
            check = composite_status(contract, schema_text)
        else:
            check = direct_status(contract, schema_text)

        result = {**base, **check}
        results.append(result)
        by_id[contract.route_id] = result

    return results


def write_outputs(results: list[dict]) -> dict:
    LATEST.mkdir(parents=True, exist_ok=True)

    counts = {
        "total": len(results),
        "ready_direct": sum(
            row["status"] == "READY_DIRECT" for row in results
        ),
        "ready_shared": sum(
            row["status"] == "READY_SHARED" for row in results
        ),
        "ready_composite": sum(
            row["status"] == "READY_COMPOSITE" for row in results
        ),
        "ready_private_runtime": sum(
            row["status"] == "READY_PRIVATE_RUNTIME"
            for row in results
        ),
        "missing": sum(
            row["status"] == "MISSING" for row in results
        ),
        "broken": sum(
            row["status"] == "BROKEN" for row in results
        ),
    }
    counts["ready_total"] = (
        counts["ready_direct"]
        + counts["ready_shared"]
        + counts["ready_composite"]
        + counts["ready_private_runtime"]
    )

    payload = {
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": now_kst(),
        "contract_table_count": 13,
        "counts": counts,
        "all_existing_routes_healthy": counts["broken"] == 0,
        "all_thirteen_routes_complete": (
            counts["ready_total"] == 13
            and counts["missing"] == 0
            and counts["broken"] == 0
        ),
        "routes": results,
        "next_build_order": [],
    }

    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fieldnames = [
        "route_id",
        "display_name",
        "generation_mode",
        "status",
        "shared_with",
        "missing_components",
        "source_existing",
        "api_existing",
        "operation_existing",
        "next_step",
    ]
    with OUTPUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "route_id": row["route_id"],
                    "display_name": row["display_name"],
                    "generation_mode": row["generation_mode"],
                    "status": row["status"],
                    "shared_with": row["shared_with"],
                    "missing_components": ",".join(
                        row["missing_components"]
                    ),
                    "source_existing": ",".join(
                        row["source_existing"]
                    ),
                    "api_existing": ",".join(
                        row["api_existing"]
                    ),
                    "operation_existing": ",".join(
                        row["operation_existing"]
                    ),
                    "next_step": row["next_step"],
                }
            )

    log_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"RUN_AT_KST={payload['generated_at_kst']}",
        "CONTRACT_TABLE_COUNT=13",
        f"READY_DIRECT_COUNT={counts['ready_direct']}",
        f"READY_SHARED_COUNT={counts['ready_shared']}",
        f"READY_COMPOSITE_COUNT={counts['ready_composite']}",
        f"READY_PRIVATE_RUNTIME_COUNT={counts['ready_private_runtime']}",
        f"READY_TOTAL_COUNT={counts['ready_total']}",
        f"MISSING_COUNT={counts['missing']}",
        f"BROKEN_COUNT={counts['broken']}",
        "EXPECTED_CURRENT_READY_COUNT=13",
        "EXPECTED_CURRENT_MISSING_COUNT=0",
        "EXPECTED_MISSING_ROUTES=",
        "NEXT_BUILD_ORDER=",
        "ALL_EXISTING_ROUTES_HEALTHY="
        + str(payload["all_existing_routes_healthy"]).lower(),
        "ALL_THIRTEEN_ROUTES_COMPLETE="
        + str(payload["all_thirteen_routes_complete"]).lower(),
        "",
        "[ROUTES]",
    ]
    for row in results:
        log_lines.append(
            "ROUTE="
            f"{row['route_id']}"
            f"|display={row['display_name']}"
            f"|mode={row['generation_mode']}"
            f"|status={row['status']}"
            f"|missing={','.join(row['missing_components'])}"
        )

    OUTPUT_LOG.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    return payload


def validate_contract_definition() -> None:
    if len(ROUTES) != 13:
        raise RuntimeError(
            f"Route contract must contain 13 tables, got {len(ROUTES)}"
        )

    route_ids = [route.route_id for route in ROUTES]
    if len(route_ids) != len(set(route_ids)):
        raise RuntimeError("Duplicate route_id found")

    expected = {
        "watchlist",
        "analysis",
        "kospi",
        "kospi_1m",
        "kosdaq",
        "kosdaq_1m",
        "kospi_gainers",
        "monthly_cycle",
        "short_term",
        "fx_weakness",
        "market_status",
        "holdings",
        "us_watchlist",
    }
    if set(route_ids) != expected:
        raise RuntimeError(
            "Route IDs differ from thirteen-table contract"
        )

    planned_missing = {
        route.route_id
        for route in ROUTES
        if route.planned_missing
    }
    if planned_missing:
        raise RuntimeError(
            "No planned missing routes are allowed"
        )


def run_self_test() -> int:
    validate_contract_definition()

    assert len(ROUTES) == 13
    assert sum(route.required_now for route in ROUTES) == 13
    assert sum(route.planned_missing for route in ROUTES) == 0

    analysis = next(
        route for route in ROUTES if route.route_id == "analysis"
    )
    assert analysis.generation_mode == "SHARED"
    assert analysis.shared_with == "watchlist"

    market = next(
        route for route in ROUTES if route.route_id == "market_status"
    )
    assert market.generation_mode == "COMPOSITE"
    assert len(market.api_files) == 3
    assert len(market.operation_ids) == 3

    us_route = next(
        item for item in ROUTES
        if item.route_id == "us_watchlist"
    )
    assert us_route.required_now is True
    assert us_route.planned_missing is False

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "thirteen_route_count,"
        "thirteen_current_routes,"
        "zero_planned_missing_routes,"
        "analysis_shared_route,"
        "market_composite_route,"
        "unique_route_ids"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--strict-current-baseline",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    validate_contract_definition()
    results = evaluate_routes()
    payload = write_outputs(results)
    counts = payload["counts"]

    print(f"TABLE_ROUTE_REGISTRY_STATUS={'OK' if counts['broken'] == 0 else 'BROKEN'}")
    print(f"CONTRACT_TABLE_COUNT={counts['total']}")
    print(f"READY_TOTAL_COUNT={counts['ready_total']}")
    print(f"MISSING_COUNT={counts['missing']}")
    print(f"BROKEN_COUNT={counts['broken']}")
    print(f"OUTPUT_JSON={OUTPUT_JSON}")
    print(f"OUTPUT_CSV={OUTPUT_CSV}")
    print(f"OUTPUT_LOG={OUTPUT_LOG}")

    if args.strict_current_baseline:
        if counts["ready_total"] != 13:
            raise SystemExit(
                f"Expected 13 ready routes, got {counts['ready_total']}"
            )
        if counts["missing"] != 0:
            raise SystemExit(
                f"Expected 0 missing routes, got {counts['missing']}"
            )
        if counts["broken"] != 0:
            raise SystemExit(
                f"Existing route breakage detected: {counts['broken']}"
            )

        missing_ids = {
            row["route_id"]
            for row in results
            if row["status"] == "MISSING"
        }
        expected_missing = set()
        if missing_ids != expected_missing:
            raise SystemExit(
                "Missing route set differs from expected baseline: "
                + ",".join(sorted(missing_ids))
            )

        print("CURRENT_BASELINE_VERIFICATION=OK")

    return 0 if counts["broken"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
