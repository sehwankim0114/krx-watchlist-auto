#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-12-v8.7.6-readiness-with-ocf-and-20d-elasticity"
OCF_VERSION = "2026-09-12-v8.7.4-audited-operating-cash-flow-source"
ELASTICITY_VERSION = "2026-09-12-v8.7.5-price-elasticity-20-session-source"
KST = ZoneInfo("Asia/Seoul")

BASE = Path(".")
READINESS = BASE / "latest/investment_score_readiness_latest.json"
OCF_META = BASE / "latest/investment_score_ocf_source_latest.json"
OCF_CSV = BASE / "latest/investment_score_ocf_source_latest.csv"
ELASTICITY_META = BASE / "latest/investment_score_price_elasticity_20d_latest.json"
ELASTICITY_CSV = BASE / "latest/investment_score_price_elasticity_20d_latest.csv"

OUT_JSON = BASE / "latest/investment_score_readiness_latest.json"
OUT_CSV = BASE / "latest/investment_score_readiness_components_latest.csv"
OUT_LOG = BASE / "latest/investment_score_readiness_run_log_latest.txt"
OUT_DOC = BASE / "docs/investment_score_readiness_contract_v876.md"

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def number(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "None", "null", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def component_status(ready_count: int, universe_count: int) -> str:
    if ready_count == universe_count:
        return "SOURCE_READY_THRESHOLD_UNDEFINED"
    if ready_count > 0:
        return "SOURCE_PARTIAL_THRESHOLD_UNDEFINED"
    return "SOURCE_NOT_READY_THRESHOLD_UNDEFINED"

def main():
    data = read_json(READINESS)
    ocf_meta = read_json(OCF_META)
    elasticity_meta = read_json(ELASTICITY_META)

    if data.get("status") != "READY_AUDIT_ONLY":
        raise RuntimeError("BASE_READINESS_NOT_READY")
    if data.get("component_count") != 23:
        raise RuntimeError("BASE_COMPONENT_COUNT_MISMATCH")
    if data.get("hard_guards", {}).get("investment_score_100_calculated") is not False:
        raise RuntimeError("BASE_SCORE_GUARD_BROKEN")

    universe_count = int(data["universe"]["unique_ticker_count"])
    basis_date = str(data.get("basis_date") or "")

    if ocf_meta.get("version") != OCF_VERSION:
        raise RuntimeError("OCF_VERSION_MISMATCH")
    if ocf_meta.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError("OCF_SOURCE_NOT_READY")
    if int(ocf_meta.get("production_unique_tickers") or 0) != universe_count:
        raise RuntimeError("OCF_UNIVERSE_MISMATCH")
    if ocf_meta.get("hard_guards", {}).get("investment_score_100_calculated") is not False:
        raise RuntimeError("OCF_SCORE_GUARD_BROKEN")
    if ocf_meta.get("hard_guards", {}).get("production_api_changed") is not False:
        raise RuntimeError("OCF_PRODUCTION_GUARD_BROKEN")

    if elasticity_meta.get("version") != ELASTICITY_VERSION:
        raise RuntimeError("ELASTICITY_VERSION_MISMATCH")
    if elasticity_meta.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError("ELASTICITY_SOURCE_NOT_READY")
    if int(elasticity_meta.get("production_unique_tickers") or 0) != universe_count:
        raise RuntimeError("ELASTICITY_UNIVERSE_MISMATCH")
    if str(elasticity_meta.get("basis_date") or "") != basis_date:
        raise RuntimeError("ELASTICITY_BASIS_DATE_MISMATCH")
    if elasticity_meta.get("hard_guards", {}).get("investment_score_100_calculated") is not False:
        raise RuntimeError("ELASTICITY_SCORE_GUARD_BROKEN")
    if elasticity_meta.get("hard_guards", {}).get("production_api_changed") is not False:
        raise RuntimeError("ELASTICITY_PRODUCTION_GUARD_BROKEN")
    if elasticity_meta.get("hard_guards", {}).get("avg_daily_range_20_pct_substituted") is not False:
        raise RuntimeError("ELASTICITY_RANGE_SUBSTITUTION_GUARD_BROKEN")

    ocf_rows = read_rows(OCF_CSV)
    elasticity_rows = read_rows(ELASTICITY_CSV)

    ocf_ready = sum(
        1
        for row in ocf_rows
        if row.get("source_status") == "READY"
        and number(row.get("operating_cash_flow_annual")) is not None
    )
    elasticity_ready = sum(
        1
        for row in elasticity_rows
        if row.get("source_status") == "READY"
        and number(row.get("avg_daily_move_pct")) is not None
        and int(row.get("daily_return_observation_count") or 0) == 20
    )

    if ocf_ready != int(ocf_meta.get("operating_cash_flow_ready") or -1):
        raise RuntimeError("OCF_READY_COUNT_MISMATCH")
    if elasticity_ready != int(elasticity_meta.get("ready_tickers") or -1):
        raise RuntimeError("ELASTICITY_READY_COUNT_MISMATCH")

    found_ocf = False
    found_elasticity = False

    for component in data["components"]:
        if component["item"] == "영업현금흐름":
            found_ocf = True
            component["source_basis"] = (
                "OpenDART exact IFRS operating cash flow; "
                "V8.7.0 exact preferred-common inheritance only"
            )
            component["readiness_type"] = "OCF_EXACT_IFRS_SOURCE"
            component["source_ready_count"] = ocf_ready
            component["universe_count"] = universe_count
            component["coverage_pct"] = round(100 * ocf_ready / universe_count, 2)
            component["status"] = component_status(ocf_ready, universe_count)
            component["score_threshold_defined"] = False
            component["score_value_generated"] = False

        if component["item"] == "하루평균 절대등락률":
            found_elasticity = True
            component["source_basis"] = (
                "official KRX latest 21 closes -> 20 absolute daily returns"
            )
            component["readiness_type"] = "PRICE_ELASTICITY_20D_SOURCE"
            component["source_ready_count"] = elasticity_ready
            component["universe_count"] = universe_count
            component["coverage_pct"] = round(
                100 * elasticity_ready / universe_count, 2
            )
            component["status"] = component_status(
                elasticity_ready, universe_count
            )
            component["score_threshold_defined"] = False
            component["score_value_generated"] = False

    if not found_ocf:
        raise RuntimeError("OCF_COMPONENT_NOT_FOUND")
    if not found_elasticity:
        raise RuntimeError("ELASTICITY_COMPONENT_NOT_FOUND")

    source_not_connected_count = sum(
        1
        for component in data["components"]
        if component["status"] == "SOURCE_NOT_CONNECTED"
    )

    blockers = sorted({
        component["status"]
        for component in data["components"]
        if component["status"] != "SOURCE_READY_THRESHOLD_UNDEFINED"
    })

    data["version"] = VERSION
    data["generated_at_kst"] = datetime.now(KST).isoformat(timespec="seconds")
    data["source_extensions"] = {
        "operating_cash_flow": {
            "version": OCF_VERSION,
            "ready_count": ocf_ready,
            "universe_count": universe_count,
            "coverage_pct": round(100 * ocf_ready / universe_count, 2),
        },
        "price_elasticity_20d": {
            "version": ELASTICITY_VERSION,
            "ready_count": elasticity_ready,
            "universe_count": universe_count,
            "coverage_pct": round(
                100 * elasticity_ready / universe_count, 2
            ),
            "basis_date": basis_date,
        },
    }
    data["hard_guards"]["investment_score_100_calculated"] = False
    data["hard_guards"]["component_points_calculated"] = False
    data["hard_guards"]["raw_value_to_point_thresholds_invented"] = False
    data["hard_guards"]["production_api_changed_by_audit"] = False
    data["overall"]["investment_score_status"] = "NOT_CALCULATED"
    data["overall"]["score_threshold_policy_status"] = "NOT_DEFINED"
    data["overall"]["ready_for_100_point_calculation"] = False
    data["overall"]["source_not_connected_component_count"] = (
        source_not_connected_count
    )
    data["overall"]["blocker_statuses"] = blockers

    OUT_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fields = [
        "area",
        "item",
        "max_points",
        "source_basis",
        "readiness_type",
        "source_ready_count",
        "universe_count",
        "coverage_pct",
        "status",
        "score_threshold_defined",
        "score_value_generated",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data["components"])

    log = [
        f"VERSION={VERSION}",
        f"BASIS_DATE={basis_date}",
        f"UNIQUE_TICKERS={universe_count}",
        f"OPERATING_CASH_FLOW_READY={ocf_ready}/{universe_count}",
        f"PRICE_ELASTICITY_20D_READY={elasticity_ready}/{universe_count}",
        f"SOURCE_NOT_CONNECTED_COMPONENT_COUNT={source_not_connected_count}",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "COMPONENT_POINTS_CALCULATED=false",
        "SCORE_THRESHOLD_POLICY_STATUS=NOT_DEFINED",
        "READY_FOR_100_POINT_CALCULATION=false",
        "PRODUCTION_API_CHANGED=false",
    ]
    for component in data["components"]:
        log.append(
            "COMPONENT="
            + component["item"].replace("=", " ")
            + f"|max={component['max_points']}"
            + f"|coverage={component['source_ready_count']}/{universe_count}"
            + f"|status={component['status']}"
        )
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.7.6 투자종합점수 계산준비도 계약",
        "",
        f"버전: `{VERSION}`",
        "",
        "## 이번 반영",
        "",
        f"- 영업현금흐름 공식 원천: {ocf_ready}/{universe_count}",
        f"- 최근 20거래일 하루평균 절대등락률: {elasticity_ready}/{universe_count}",
        f"- SOURCE_NOT_CONNECTED 세부항목: {source_not_connected_count}개",
        "",
        "## 계속 금지",
        "",
        "- investment_score_100 계산",
        "- 세부 원자료→점수 구간 임의 생성",
        "- 순현금 부채범위 임의 확정",
        "- EV/EBITDA D&A 정책 임의 확정",
        "- 분기 가속·둔화 구간 임의 확정",
        "- 수급 세부점수 규칙 임의 생성",
        "",
        "이 단계는 새 원천을 readiness에 반영하는 감사 단계이며 production API를 변경하지 않는다.",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("\n".join(log))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
