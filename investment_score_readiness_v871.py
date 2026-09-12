#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-12-v8.7.1-investment-score-readiness-audit"
SCORE_POLICY_VERSION = "2026-07-01-v6.0-score-policy"
SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"
TWO_TABLE_VERSION = "2026-09-12-v8.7.0-sector-rs-production-release"
KST = ZoneInfo("Asia/Seoul")

BASE = Path(".")
TWO = BASE / "api" / "two_table_v1"
FIN = BASE / "latest" / "financial_valuation_cache_latest.csv"
RAW = BASE / "latest" / "investment_score_source_cache_latest.csv"
OUT_JSON = BASE / "latest" / "investment_score_readiness_latest.json"
OUT_CSV = BASE / "latest" / "investment_score_readiness_components_latest.csv"
OUT_LOG = BASE / "latest" / "investment_score_readiness_run_log_latest.txt"
OUT_DOC = BASE / "docs" / "investment_score_readiness_contract_v871.md"

COMPONENTS = [
    ("financial", "매출 성장과 안정성", 5, "annual_revenue_y0/y1/y2", "THREE_YEAR_RAW"),
    ("financial", "영업이익 성장과 흑자 여부", 7, "annual_operating_profit_y0/y1/y2", "THREE_YEAR_RAW"),
    ("financial", "순이익 흐름", 3, "annual_net_income_y0/y1/y2", "THREE_YEAR_RAW"),
    ("financial", "영업이익률", 4, "operating_margin_pct", "FINANCIAL_CACHE"),
    ("financial", "ROE", 4, "roe_annualized_pct", "FINANCIAL_CACHE"),
    ("financial", "부채비율", 3, "debt_ratio_pct", "FINANCIAL_CACHE"),
    ("financial", "영업현금흐름", 4, "운영 원천 없음", "SOURCE_NOT_CONNECTED"),

    ("valuation", "PER", 8, "per_annualized", "FINANCIAL_CACHE"),
    ("valuation", "PBR", 5, "pbr", "FINANCIAL_CACHE"),
    ("valuation", "EV/EBITDA", 4, "ev_ebitda_value", "EV_EBITDA_POLICY_PENDING"),
    ("valuation", "PSR 또는 대체 가치지표", 3, "market_cap+revenue는 있으나 공식 점수계약 없음", "DERIVABLE_POLICY_UNDEFINED"),

    ("growth_value", "최근 3년 매출 성장률", 4, "annual_revenue_y0/y1/y2", "THREE_YEAR_RAW"),
    ("growth_value", "최근 3년 영업이익 성장률", 4, "annual_operating_profit_y0/y1/y2", "THREE_YEAR_RAW"),
    ("growth_value", "최근 분기 실적 가속·둔화", 3, "q2_*_yoy_pct", "QUARTER_CLASS_POLICY_PENDING"),
    ("growth_value", "흑자 지속성과 이익 안정성", 2, "earnings_trend + 3년 이익 원자료", "PROFIT_PERSISTENCE_RAW"),
    ("growth_value", "순현금·기업가치 상태", 2, "cash/debt candidates", "NET_CASH_POLICY_PENDING"),

    ("price_position", "1개월 가격흐름", 4, "metrics.returns.1.pct", "TWO_TABLE_METRIC"),
    ("price_position", "3개월 가격흐름", 3, "metrics.returns.3.pct", "TWO_TABLE_METRIC"),
    ("price_position", "기간 저가·고가 대비 현재위치", 5, "metrics.range_3m.position_pct", "TWO_TABLE_METRIC"),
    ("price_position", "과열·급락 위험", 3, "metrics.swing/returns/atr14", "INPUT_READY_THRESHOLD_UNDEFINED"),

    ("liquidity_elasticity", "20일 평균 거래대금과 거래량", 6, "metrics.activity", "TWO_TABLE_METRIC"),
    ("liquidity_elasticity", "하루평균 절대등락률", 4, "avg_daily_range_20_pct는 고저폭이라 동일 지표 아님", "SOURCE_NOT_CONNECTED"),

    ("supply_disclosure", "수급·공시부담", 10, "analysis.supply_level/status/keywords", "RANGE_POLICY_ONLY"),
]

EXPECTED_AREA_MAX = {
    "financial": 30,
    "valuation": 20,
    "growth_value": 15,
    "price_position": 15,
    "liquidity_elasticity": 10,
    "supply_disclosure": 10,
}

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def read_csv_map(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return {
            str(r.get("ticker") or "").strip().zfill(6): r
            for r in csv.DictReader(f)
            if str(r.get("ticker") or "").strip()
        }

def num(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "None", "null", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def build_universe():
    manifest = read_json(TWO / "manifest.json")
    if manifest.get("version") != TWO_TABLE_VERSION:
        raise RuntimeError("TWO_TABLE_VERSION_MISMATCH")
    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError("TWO_TABLE_NOT_PRODUCTION")
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError("TWO_TABLE_NOT_SAFE_LATEST")

    rows_by_ticker = {}
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(TWO / f"{table}.json")
        for row in payload.get("rows") or []:
            code = str(row["ticker"]).zfill(6)
            rows_by_ticker.setdefault(code, row)
    return manifest, rows_by_ticker

def source_ready(kind, fin, raw, row):
    if kind == "THREE_YEAR_RAW":
        return bool(raw and raw.get("three_year_source_status") == "READY")
    if kind == "FINANCIAL_CACHE":
        return bool(fin)
    if kind == "SOURCE_NOT_CONNECTED":
        return False
    if kind == "EV_EBITDA_POLICY_PENDING":
        return bool(raw and num(raw.get("ev_ebitda_value")) is not None)
    if kind == "DERIVABLE_POLICY_UNDEFINED":
        return bool(
            fin
            and num(fin.get("market_cap")) is not None
            and num(fin.get("revenue")) not in (None, 0)
        )
    if kind == "QUARTER_CLASS_POLICY_PENDING":
        return bool(
            raw
            and raw.get("quarter_source_status") == "READY_Q2_SOURCE"
            and any(
                num(raw.get(k)) is not None
                for k in (
                    "q2_revenue_yoy_pct",
                    "q2_operating_profit_yoy_pct",
                    "q2_net_income_yoy_pct",
                )
            )
        )
    if kind == "PROFIT_PERSISTENCE_RAW":
        return bool(
            fin
            and str(fin.get("earnings_trend") or "").strip()
            and raw
            and raw.get("three_year_source_status") == "READY"
        )
    if kind == "NET_CASH_POLICY_PENDING":
        return bool(
            raw
            and num(raw.get("cash_and_cash_equivalents")) is not None
            and str(raw.get("core_debt_candidates_json") or "").strip()
        )
    if kind == "TWO_TABLE_METRIC":
        return bool(row and (row.get("metrics") or {}).get("status") == "OK")
    if kind == "INPUT_READY_THRESHOLD_UNDEFINED":
        metrics = (row or {}).get("metrics") or {}
        return bool(metrics.get("swing") and metrics.get("returns") and metrics.get("atr14"))
    if kind == "RANGE_POLICY_ONLY":
        analysis = (row or {}).get("analysis") or {}
        return bool(str(analysis.get("supply_level") or "").strip())
    raise RuntimeError("UNKNOWN_COMPONENT_TYPE:" + kind)

def status_label(kind, ready_count, universe_count):
    if kind == "SOURCE_NOT_CONNECTED":
        return "SOURCE_NOT_CONNECTED"
    if kind in {
        "EV_EBITDA_POLICY_PENDING",
        "DERIVABLE_POLICY_UNDEFINED",
        "QUARTER_CLASS_POLICY_PENDING",
        "NET_CASH_POLICY_PENDING",
        "INPUT_READY_THRESHOLD_UNDEFINED",
    }:
        return (
            "SOURCE_INPUT_PRESENT_POLICY_UNDEFINED"
            if ready_count > 0
            else "SOURCE_NOT_READY_POLICY_UNDEFINED"
        )
    if kind == "RANGE_POLICY_ONLY":
        return "SOURCE_PRESENT_RANGE_POLICY_ONLY"
    if ready_count == universe_count:
        return "SOURCE_READY_THRESHOLD_UNDEFINED"
    if ready_count > 0:
        return "SOURCE_PARTIAL_THRESHOLD_UNDEFINED"
    return "SOURCE_NOT_READY_THRESHOLD_UNDEFINED"

def main():
    manifest, table_rows = build_universe()
    fin_map = read_csv_map(FIN)
    raw_map = read_csv_map(RAW)
    tickers = sorted(table_rows)
    universe_count = len(tickers)
    if universe_count <= 0:
        raise RuntimeError("EMPTY_UNIVERSE")

    component_rows = []
    for area, item, max_points, source, kind in COMPONENTS:
        ready_count = sum(
            1
            for code in tickers
            if source_ready(
                kind,
                fin_map.get(code),
                raw_map.get(code),
                table_rows.get(code),
            )
        )
        component_rows.append({
            "area": area,
            "item": item,
            "max_points": max_points,
            "source_basis": source,
            "readiness_type": kind,
            "source_ready_count": ready_count,
            "universe_count": universe_count,
            "coverage_pct": round(100 * ready_count / universe_count, 2),
            "status": status_label(kind, ready_count, universe_count),
            "score_threshold_defined": False,
            "score_value_generated": False,
        })

    area_sums = {}
    for row in component_rows:
        area_sums[row["area"]] = area_sums.get(row["area"], 0) + row["max_points"]
    if area_sums != EXPECTED_AREA_MAX:
        raise RuntimeError("V6_WEIGHT_MISMATCH")
    if sum(area_sums.values()) != 100:
        raise RuntimeError("TOTAL_WEIGHT_NOT_100")

    blockers = sorted({
        row["status"]
        for row in component_rows
        if row["status"] != "SOURCE_READY_THRESHOLD_UNDEFINED"
    })

    payload = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "READY_AUDIT_ONLY",
        "source_build_id": manifest.get("source_build_id"),
        "basis_date": manifest.get("basis_date"),
        "score_policy_version": SCORE_POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "two_table_version": TWO_TABLE_VERSION,
        "universe": {
            "scope": "unique tickers in current production kospi/decliners/decliners24",
            "unique_ticker_count": universe_count,
            "financial_cache_matches": sum(code in fin_map for code in tickers),
            "investment_raw_cache_matches": sum(code in raw_map for code in tickers),
        },
        "area_max_points": EXPECTED_AREA_MAX,
        "component_count": len(component_rows),
        "components": component_rows,
        "hard_guards": {
            "investment_score_100_calculated": False,
            "component_points_calculated": False,
            "raw_value_to_point_thresholds_invented": False,
            "legacy_score_rescaled": False,
            "production_api_changed_by_audit": False,
        },
        "overall": {
            "investment_score_status": "NOT_CALCULATED",
            "score_threshold_policy_status": "NOT_DEFINED",
            "ready_for_100_point_calculation": False,
            "blocker_statuses": blockers,
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fields = [
        "area", "item", "max_points", "source_basis", "readiness_type",
        "source_ready_count", "universe_count", "coverage_pct", "status",
        "score_threshold_defined", "score_value_generated",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(component_rows)

    log = [
        f"VERSION={VERSION}",
        f"BASIS_DATE={manifest.get('basis_date')}",
        f"SOURCE_BUILD_ID={manifest.get('source_build_id')}",
        f"UNIQUE_TICKERS={universe_count}",
        f"FINANCIAL_CACHE_MATCHES={payload['universe']['financial_cache_matches']}",
        f"INVESTMENT_RAW_CACHE_MATCHES={payload['universe']['investment_raw_cache_matches']}",
        f"COMPONENT_COUNT={len(component_rows)}",
        "TOTAL_MAX_POINTS=100",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "COMPONENT_POINTS_CALCULATED=false",
        "SCORE_THRESHOLD_POLICY_STATUS=NOT_DEFINED",
        "READY_FOR_100_POINT_CALCULATION=false",
        "LEGACY_SCORE_RESCALED=false",
        "PRODUCTION_API_CHANGED=false",
    ]
    for row in component_rows:
        log.append(
            "COMPONENT="
            + row["item"].replace("=", " ")
            + f"|max={row['max_points']}"
            + f"|coverage={row['source_ready_count']}/{universe_count}"
            + f"|status={row['status']}"
        )
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc_lines = [
        "# V8.7.1 투자종합점수 계산준비도 계약",
        "",
        f"버전: `{VERSION}`",
        "",
        "## 목적",
        "",
        "이 단계는 V6 100점 체계를 계산하지 않고 각 세부 평가항목의 원천자료 준비 상태와 아직 정의되지 않은 정책을 점검한다.",
        "",
        "## 절대 금지",
        "",
        "- investment_score_100 생성 금지",
        "- legacy_market_score의 100점 환산 금지",
        "- 프로젝트 소스에 없는 원자료→점수 구간 임의 생성 금지",
        "- 영업현금흐름 대체치 임의 사용 금지",
        "- avg_daily_range_20_pct를 하루평균 절대등락률로 대체 금지",
        "- 현금·부채 후보를 임의 합산하여 순현금 계산 금지",
        "- 감가상각 후보만으로 EV/EBITDA 계산 금지",
        "",
        "## 감사 범위",
        "",
        "현재 production kospi, decliners, decliners24의 고유 종목을 기준으로 한다.",
        "",
        "V6 배점은 실적·재무 30, 밸류 20, 성장성·기업가치 15, 가격흐름·현재위치 15, 거래활발·가격탄력 10, 수급·공시부담 10으로 합계 100점이다.",
        "",
        "## 100점 계산 전 필수 완료사항",
        "",
        "1. V6 필수 원천 연결",
        "2. 각 원자료→점수 구간 별도 계약 확정",
        "3. 순현금 부채범위 정책 확정",
        "4. EV/EBITDA D&A 원천 정책 검증",
        "5. 분기 가속·둔화 판정구간 확정",
        "6. 수급 점수 범위 안의 세부 배점 규칙 확정",
        "",
        "이 문서는 점수 공식이 아니라 계산준비도 계약이다.",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc_lines), encoding="utf-8")

    print("\n".join(log))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
