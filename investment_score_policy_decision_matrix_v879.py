#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-13-v8.7.9-investment-score-policy-decision-matrix"
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

READINESS = ROOT / "latest/investment_score_readiness_latest.json"
POLICY = ROOT / "latest/investment_score_policy_evidence_latest.json"
CALIBRATION = ROOT / "latest/investment_score_calibration_evidence_latest.json"

OUT_JSON = ROOT / "latest/investment_score_policy_decision_matrix_latest.json"
OUT_CSV = ROOT / "latest/investment_score_policy_decision_matrix_latest.csv"
OUT_LOG = ROOT / "latest/investment_score_policy_decision_matrix_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_policy_decision_matrix_v879.md"

NUMERIC_BINDINGS = {
    "영업이익률": "operating_margin_pct",
    "ROE": "roe_annualized_pct",
    "부채비율": "debt_ratio_pct",
    "PER": "per_annualized",
    "PBR": "pbr",
    "최근 분기 실적 가속·둔화": "q2_operating_profit_yoy_pct",
    "1개월 가격흐름": "return_1m_pct",
    "3개월 가격흐름": "return_3m_pct",
    "기간 저가·고가 대비 현재위치": "position_3m_pct",
    "과열·급락 위험": "atr14_pct",
    "20일 평균 거래대금과 거래량": "avg20_trading_value_krw",
    "하루평균 절대등락률": "elasticity_20d_pct",
}

DECISION_KIND = {
    "매출 성장과 안정성": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "영업이익 성장과 흑자 여부": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "순이익 흐름": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "영업이익률": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "ROE": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "부채비율": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "영업현금흐름": "NORMALIZATION_AND_THRESHOLD_REQUIRED",
    "PER": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "PBR": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "EV/EBITDA": "SOURCE_FORMULA_POLICY_REQUIRED",
    "PSR 또는 대체 가치지표": "FORMULA_AND_THRESHOLD_POLICY_REQUIRED",
    "최근 3년 매출 성장률": "GROWTH_FORMULA_AND_THRESHOLD_REQUIRED",
    "최근 3년 영업이익 성장률": "GROWTH_FORMULA_AND_THRESHOLD_REQUIRED",
    "최근 분기 실적 가속·둔화": "CLASSIFICATION_AND_THRESHOLD_REQUIRED",
    "흑자 지속성과 이익 안정성": "CATEGORY_TO_POINT_MAPPING_REQUIRED",
    "순현금·기업가치 상태": "DEBT_SCOPE_AND_POINT_POLICY_REQUIRED",
    "1개월 가격흐름": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "3개월 가격흐름": "RAW_TO_POINT_THRESHOLD_REQUIRED",
    "기간 저가·고가 대비 현재위치": "EXISTING_LABEL_TO_POINT_MAPPING_REQUIRED",
    "과열·급락 위험": "COMPOSITE_RISK_POINT_POLICY_REQUIRED",
    "20일 평균 거래대금과 거래량": "EXISTING_LABEL_TO_POINT_MAPPING_REQUIRED",
    "하루평균 절대등락률": "EXISTING_LABEL_TO_POINT_MAPPING_REQUIRED",
    "수급·공시부담": "EXISTING_RANGE_TO_EXACT_POINT_RULE_REQUIRED",
}

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def robustness(summary):
    if not summary or not summary.get("count"):
        return "NO_EMPIRICAL_REFERENCE"
    p10 = summary.get("p10")
    p50 = summary.get("p50")
    p90 = summary.get("p90")
    mean = summary.get("mean")
    if None in (p10, p50, p90, mean):
        return "REFERENCE_AVAILABLE"
    spread = abs(p90 - p10)
    mean_gap = abs(mean - p50)
    base = max(abs(p50), 1.0)
    if mean_gap / base >= 1.0:
        return "HIGH_OUTLIER_SENSITIVITY"
    if spread / base >= 4.0:
        return "WIDE_DISTRIBUTION"
    return "REFERENCE_STABLE_ENOUGH_FOR_REVIEW"

def main():
    readiness = read_json(READINESS)
    policy = read_json(POLICY)
    calibration = read_json(CALIBRATION)

    if readiness.get("version") != (
        "2026-09-12-v8.7.6-readiness-with-ocf-and-20d-elasticity"
    ):
        raise RuntimeError("READINESS_VERSION_MISMATCH")
    if policy.get("version") != (
        "2026-09-13-v8.7.7-investment-score-policy-evidence-audit"
    ):
        raise RuntimeError("POLICY_VERSION_MISMATCH")
    if calibration.get("version") != (
        "2026-09-13-v8.7.8-investment-score-calibration-evidence"
    ):
        raise RuntimeError("CALIBRATION_VERSION_MISMATCH")

    if readiness["hard_guards"]["investment_score_100_calculated"] is not False:
        raise RuntimeError("READINESS_SCORE_GUARD_BROKEN")
    if policy["hard_guards"]["new_thresholds_created"] is not False:
        raise RuntimeError("POLICY_THRESHOLD_GUARD_BROKEN")
    if calibration["hard_guards"]["new_score_thresholds_created"] is not False:
        raise RuntimeError("CALIBRATION_THRESHOLD_GUARD_BROKEN")

    distributions = calibration["numeric_distributions"]
    rows = []

    for component in readiness["components"]:
        item = component["item"]
        binding = NUMERIC_BINDINGS.get(item)
        empirical = distributions.get(binding, {}) if binding else {}
        summary = empirical.get("summary") or {}

        coverage = float(component["coverage_pct"])
        if coverage == 100.0:
            source_state = "FULL_SOURCE_COVERAGE"
        elif coverage > 0:
            source_state = "PARTIAL_SOURCE_COVERAGE"
        else:
            source_state = "NO_SOURCE_VALUE_READY"

        existing_policy = ""
        if item == "수급·공시부담":
            existing_policy = "V6 range exists: 없음 9~10 / 주의 6~8 / 경계 3~5 / 위험 0~2"
        elif item == "20일 평균 거래대금과 거래량":
            existing_policy = "거래활발 5단계 라벨 임계값 존재"
        elif item == "하루평균 절대등락률":
            existing_policy = "가격탄력 4단계 라벨 임계값 존재"
        elif item == "기간 저가·고가 대비 현재위치":
            existing_policy = "현재위치 6단계 라벨 임계값 존재"
        elif item == "EV/EBITDA":
            existing_policy = "D&A 원천정책 미정; 값 생성 금지"
        elif item == "순현금·기업가치 상태":
            existing_policy = "현금·부채 후보만 존재; 부채범위 미정"
        elif item == "PSR 또는 대체 가치지표":
            existing_policy = "market_cap/revenue 원천 존재하나 공식 공식계약 없음"
        elif item in {"최근 3년 매출 성장률", "최근 3년 영업이익 성장률"}:
            existing_policy = "3개년 원자료 존재; 공식 성장률 산식계약 없음"

        row = {
            "area": component["area"],
            "item": item,
            "max_points": component["max_points"],
            "source_ready_count": component["source_ready_count"],
            "universe_count": component["universe_count"],
            "coverage_pct": component["coverage_pct"],
            "source_state": source_state,
            "decision_kind": DECISION_KIND[item],
            "existing_policy_evidence": existing_policy,
            "empirical_metric": binding or "",
            "empirical_count": summary.get("count", ""),
            "empirical_p25": summary.get("p25", ""),
            "empirical_p50": summary.get("p50", ""),
            "empirical_p75": summary.get("p75", ""),
            "empirical_p90": summary.get("p90", ""),
            "empirical_mean": summary.get("mean", ""),
            "distribution_review_flag": robustness(summary),
            "score_threshold_defined": False,
            "score_value_generated": False,
        }
        rows.append(row)

    decision_counts = {}
    for row in rows:
        decision_counts[row["decision_kind"]] = (
            decision_counts.get(row["decision_kind"], 0) + 1
        )

    partial_count = sum(
        1 for row in rows if row["source_state"] == "PARTIAL_SOURCE_COVERAGE"
    )
    no_source_count = sum(
        1 for row in rows if row["source_state"] == "NO_SOURCE_VALUE_READY"
    )
    full_count = sum(
        1 for row in rows if row["source_state"] == "FULL_SOURCE_COVERAGE"
    )

    payload = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "POLICY_DECISION_MATRIX_ONLY",
        "basis_date": readiness.get("basis_date"),
        "component_count": len(rows),
        "source_coverage_summary": {
            "full": full_count,
            "partial": partial_count,
            "none": no_source_count,
        },
        "decision_kind_counts": decision_counts,
        "rows": rows,
        "hard_guards": {
            "investment_score_100_calculated": False,
            "component_points_calculated": False,
            "new_thresholds_created": False,
            "percentiles_promoted_to_thresholds": False,
            "production_api_changed": False,
        },
        "next_step": (
            "EXPLICIT_NEW_SCORING_CONTRACT_REQUIRED_BEFORE_ANY 100-POINT SCORE ACTIVATION"
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fields = list(rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    log = [
        f"VERSION={VERSION}",
        f"BASIS_DATE={readiness.get('basis_date')}",
        f"COMPONENT_COUNT={len(rows)}",
        f"FULL_SOURCE_COVERAGE_COMPONENTS={full_count}",
        f"PARTIAL_SOURCE_COVERAGE_COMPONENTS={partial_count}",
        f"NO_SOURCE_VALUE_READY_COMPONENTS={no_source_count}",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "COMPONENT_POINTS_CALCULATED=false",
        "NEW_THRESHOLDS_CREATED=false",
        "PERCENTILES_PROMOTED_TO_THRESHOLDS=false",
        "PRODUCTION_DATA_CHANGED=false",
        "STATUS=OK",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.7.9 투자종합점수 정책 결정표",
        "",
        f"버전: `{VERSION}`",
        "",
        "## 목적",
        "",
        "V8.7.6~V8.7.8의 원천 준비도·기존정책·실제분포를 한 표로 묶는다.",
        "이 문서는 새 점수 컷을 만들지 않고, 무엇을 결정해야 하는지만 고정한다.",
        "",
        "## 원칙",
        "",
        "- empirical P25/P50/P75/P90은 참고자료이며 점수구간이 아니다.",
        "- 평균과 중앙값 괴리가 큰 지표는 극단치 민감으로 표시한다.",
        "- 기존 V6 라벨/범위는 보존하되 세부점수로 자동 변환하지 않는다.",
        "- 원천이 부분커버리지인 항목은 READY 전체점수 계산 전에 LIMITED 처리정책이 필요하다.",
        "",
        "## 다음 단계",
        "",
        "새 100점 세부점수 계약을 명시적으로 확정하기 전에는 investment_score_100을 활성화하지 않는다.",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("\n".join(log))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
