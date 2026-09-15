#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-15-v8.9.0-investment-score-remaining-blocker-audit"
V889_VERSION = "2026-09-15-v8.8.9-investment-score-da-dry-run-recheck"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V889_CSV = ROOT / "latest/investment_score_v880_dry_run_v889_latest.csv"
V889_JSON = ROOT / "latest/investment_score_v880_dry_run_v889_summary_latest.json"

OUT_CSV = ROOT / "latest/investment_score_remaining_blockers_v890.csv"
OUT_JSON = ROOT / "latest/investment_score_remaining_blockers_v890_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_remaining_blockers_v890_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_remaining_blockers_v890.md"

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def split_reasons(text):
    return [x for x in str(text or "").split(";") if x]

def classify(reason):
    if reason == "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE":
        return (
            "SOURCE_EVIDENCE_GAP",
            "PRODUCTION_ANALYSIS_SUPPLY",
            "공시·수급 없음 판정을 확정할 만큼 source completeness가 부족함",
        )

    if reason == "최근 분기 실적 가속·둔화:ANNUAL_OP_DENOM_NONPOSITIVE":
        return (
            "POLICY_SEMANTIC_BLOCKER",
            "V880_SCORING_CONTRACT",
            "전년도 연간 영업이익 분모가 비양수이며 승인 계약상 turnaround 예외에도 해당하지 않음",
        )

    if reason.startswith("PER:") or reason.startswith("PBR:"):
        return (
            "SOURCE_DATA_GAP",
            "FINANCIAL_VALUATION_CACHE",
            "밸류에이션 또는 관련 이익·ROE 입력 보강 필요",
        )

    if reason.startswith("EV/EBITDA:"):
        tail = reason.split("EV/EBITDA:", 1)[1]
        parts = tail.split(":")
        debt_status = parts[-2] if len(parts) >= 2 else ""
        da_status = parts[-1] if parts else ""
        if da_status == "NO_EXACT_CANDIDATE":
            return (
                "SOURCE_DATA_GAP",
                "EXACT_DA_SOURCE",
                f"승인 exact D&A 원천 부족; debt_status={debt_status}, da_status={da_status}",
            )
        if debt_status == "NO_EXACT_CANDIDATE":
            return (
                "SOURCE_DATA_GAP",
                "EXACT_CORE_DEBT_SOURCE",
                f"승인 exact core-debt 원천 부족; debt_status={debt_status}, da_status={da_status}",
            )
        if debt_status in {"OK", "EMPTY_AS_ZERO"} and da_status in {"OK", "EMPTY_AS_ZERO"}:
            return (
                "SOURCE_DATA_GAP",
                "EV_EBITDA_OTHER_INPUT",
                "D&A/debt exact 상태는 통과했으므로 시가총액·현금·영업이익 입력 중 누락 점검 필요",
            )
        return (
            "SOURCE_DATA_GAP",
            "EV_EBITDA_INPUT",
            f"EV/EBITDA 입력 상태 재감사 필요: {tail}",
        )

    if reason.startswith("PSR 또는 대체 가치지표:"):
        return (
            "SOURCE_DATA_GAP",
            "FINANCIAL_AND_RAW_SOURCE",
            "시가총액 또는 연간 매출 입력 보강 필요",
        )

    raw_prefixes = (
        "매출 성장과 안정성:",
        "최근 3년 매출 성장률:",
        "최근 3년 영업이익 성장률:",
        "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
    )
    if reason.startswith(raw_prefixes):
        return (
            "SOURCE_DATA_GAP",
            "INVESTMENT_SCORE_SOURCE_CACHE",
            "연간/분기 재무 raw source 보강 필요",
        )

    financial_prefixes = (
        "영업이익 성장과 흑자 여부:",
        "순이익 흐름:",
        "영업이익률:",
        "ROE:",
        "부채비율:",
        "흑자 지속성과 이익 안정성:",
    )
    if reason.startswith(financial_prefixes):
        return (
            "SOURCE_DATA_GAP",
            "FINANCIAL_VALUATION_CACHE",
            "재무·수익성 cache 입력 보강 필요",
        )

    if reason.startswith("영업현금흐름:"):
        return (
            "SOURCE_DATA_GAP",
            "OCF_AND_REVENUE_SOURCE",
            "영업현금흐름 또는 연간 매출 입력 보강 필요",
        )

    price_prefixes = (
        "1개월 가격흐름:",
        "3개월 가격흐름:",
        "기간 저가·고가 대비 현재위치:",
        "과열·급락 위험:",
        "20일 평균 거래대금과 거래량:",
    )
    if reason.startswith(price_prefixes):
        return (
            "SOURCE_DATA_GAP",
            "PRODUCTION_PRICE_METRICS",
            "가격·스윙·ATR·거래활동 metric 보강 필요",
        )

    if reason.startswith("하루평균 절대등락률:"):
        return (
            "SOURCE_DATA_GAP",
            "PRICE_ELASTICITY_20D",
            "20거래일 가격탄력 source 보강 필요",
        )

    if reason.startswith("순현금·기업가치 상태:"):
        return (
            "SOURCE_DATA_GAP",
            "NETCASH_INPUT",
            "시가총액·현금·승인 core debt 원천 보강 필요",
        )

    return (
        "UNCLASSIFIED_REVIEW",
        "UNKNOWN",
        "자동 분류되지 않은 blocker이므로 사람 검토 필요",
    )

def main():
    summary889 = read_json(V889_JSON)
    rows889 = read_csv(V889_CSV)

    if summary889.get("version") != V889_VERSION:
        raise RuntimeError("V889_VERSION_MISMATCH")
    if summary889.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("POLICY_VERSION_MISMATCH")
    if summary889.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V889_STATUS_MISMATCH")
    if len(rows889) != 112:
        raise RuntimeError(f"V889_ROW_COUNT:{len(rows889)}")

    limited = [r for r in rows889 if r.get("score_status") == "LIMITED"]
    ready = [r for r in rows889 if r.get("score_status") == "READY"]
    if len(ready) != 41 or len(limited) != 71:
        raise RuntimeError(f"V889_READY_LIMITED_MISMATCH:{len(ready)}:{len(limited)}")

    out_rows = []
    reason_counter = Counter()
    category_counter = Counter()
    source_counter = Counter()
    single_counter = Counter()
    ticker_category_sets = defaultdict(set)

    for row in limited:
        reasons = split_reasons(row.get("missing_components"))
        for reason in reasons:
            category, source_group, note = classify(reason)
            reason_counter[reason] += 1
            category_counter[category] += 1
            source_counter[source_group] += 1
            ticker_category_sets[row["ticker"]].add(category)
            if len(reasons) == 1:
                single_counter[source_group] += 1

            out_rows.append({
                "ticker": row.get("ticker") or "",
                "name": row.get("name") or "",
                "market": row.get("market") or "",
                "financial_sector": row.get("financial_sector") or "",
                "raw_source_mode": row.get("raw_source_mode") or "",
                "missing_component_count": row.get("missing_component_count") or "",
                "blocker_reason": reason,
                "blocker_category": category,
                "source_group": source_group,
                "single_blocker_ticker": "TRUE" if len(reasons) == 1 else "FALSE",
                "audit_note": note,
            })

    out_rows.sort(
        key=lambda r: (
            int(r["missing_component_count"] or 999),
            r["ticker"],
            r["blocker_reason"],
        )
    )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    ev_reason_counts = {
        reason: count
        for reason, count in reason_counter.items()
        if reason.startswith("EV/EBITDA:")
    }
    ev_da_missing = sum(
        count for reason, count in ev_reason_counts.items()
        if reason.endswith(":NO_EXACT_CANDIDATE")
    )
    ev_other_exact_ok = sum(
        count for reason, count in ev_reason_counts.items()
        if reason.endswith(":OK:OK")
    )

    single_blocker_tickers = sorted({
        r["ticker"] for r in out_rows if r["single_blocker_ticker"] == "TRUE"
    })

    source_priority = [
        {
            "source_group": source,
            "blocker_occurrences": count,
            "single_blocker_tickers": single_counter.get(source, 0),
        }
        for source, count in source_counter.most_common()
    ]

    summary = {
        "version": VERSION,
        "v889_version": V889_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "production_unique_tickers": 112,
        "ready_count": 41,
        "limited_count": 71,
        "limited_blocker_occurrences": len(out_rows),
        "single_blocker_ticker_count": len(single_blocker_tickers),
        "single_blocker_tickers": single_blocker_tickers,
        "blocker_category_counts": dict(category_counter),
        "source_group_counts": dict(source_counter),
        "source_priority": source_priority,
        "top_blocker_reasons": reason_counter.most_common(40),
        "ev_ebitda_audit": {
            "total_blocker_occurrences": sum(ev_reason_counts.values()),
            "reason_counts": ev_reason_counts,
            "da_no_exact_candidate_occurrences": ev_da_missing,
            "exact_debt_and_da_but_other_input_missing_occurrences": ev_other_exact_ok,
        },
        "policy_semantic_blockers": {
            "annual_op_denom_nonpositive_count":
                reason_counter.get(
                    "최근 분기 실적 가속·둔화:ANNUAL_OP_DENOM_NONPOSITIVE",
                    0,
                ),
            "automatic_rule_change_allowed": False,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_source_value_imputed": False,
            "limited_score_promoted": False,
        },
        "next_step": (
            "REVIEW_SOURCE_PRIORITY_AND_RECOVER_HIGHEST_IMPACT_SOURCE_GAP_"
            "WITHOUT_POLICY_CHANGE"
        ),
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    doc = [
        "# V8.9.0 투자종합점수 남은 blocker 감사",
        "",
        f"- 버전: `{VERSION}`",
        f"- 기준 dry-run: `{V889_VERSION}`",
        "- 상태: AUDIT_ONLY",
        "",
        "## 목적",
        "",
        "V8.8.9의 LIMITED 71종목을 source gap, evidence gap, "
        "policy semantic blocker로 분해한다.",
        "",
        "## 안전 원칙",
        "",
        "- 점수 공식·가중치·구간 변경 없음.",
        "- production investment_score_100 기록 없음.",
        "- 결측값 임의 대체 없음.",
        "- ANNUAL_OP_DENOM_NONPOSITIVE는 승인 계약을 바꾸지 않고 별도 분류만 한다.",
        "- source 보강 우선순위는 blocker 발생 수와 single-blocker 해소 가능성을 함께 본다.",
        "",
        "## 다음 단계",
        "",
        "source_priority 결과를 보고 정책 변경 없이 복구 가능한 가장 영향도 높은 "
        "source group부터 별도 audit/recovery를 진행한다.",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    log = [
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY",
        f"READY_COUNT={len(ready)}",
        f"LIMITED_COUNT={len(limited)}",
        f"LIMITED_BLOCKER_OCCURRENCES={len(out_rows)}",
        f"SINGLE_BLOCKER_TICKER_COUNT={len(single_blocker_tickers)}",
        f"EV_EBITDA_BLOCKERS={sum(ev_reason_counts.values())}",
        f"EV_DA_NO_EXACT_CANDIDATE={ev_da_missing}",
        f"EV_EXACT_OK_OTHER_INPUT_MISSING={ev_other_exact_ok}",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_SOURCE_VALUE_IMPUTED=false",
        "STATUS=OK",
        "NEXT_STEP=REVIEW_SOURCE_PRIORITY_AND_RECOVER_HIGHEST_IMPACT_SOURCE_GAP",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    print("V890_REMAINING_BLOCKER_AUDIT=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()

