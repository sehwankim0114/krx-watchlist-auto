#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_remaining_blocker_audit_v890 as base

VERSION = "2026-09-15-v8.9.5-refresh-remaining-blocker-audit"
V894_VERSION = "2026-09-15-v8.9.4-extend-da-source-and-rerun-dry-run"
V890_VERSION = "2026-09-15-v8.9.0-investment-score-remaining-blocker-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V894_CSV = ROOT / "latest/investment_score_v880_dry_run_v894_latest.csv"
V894_JSON = ROOT / "latest/investment_score_v880_dry_run_v894_summary_latest.json"

OUT_CSV = ROOT / "latest/investment_score_remaining_blockers_v895.csv"
OUT_JSON = ROOT / "latest/investment_score_remaining_blockers_v895_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_remaining_blockers_v895_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_remaining_blockers_v895.md"

POLICY_ONLY_GROUPS = {"V880_SCORING_CONTRACT"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_reasons(text):
    return [x for x in str(text or "").split(";") if x]


def main():
    if base.VERSION != V890_VERSION:
        raise RuntimeError("BASE_V890_VERSION_MISMATCH")
    if base.POLICY_VERSION != POLICY_VERSION:
        raise RuntimeError("BASE_V890_POLICY_VERSION_MISMATCH")

    s894 = read_json(V894_JSON)
    rows894 = read_csv(V894_CSV)

    if s894.get("version") != V894_VERSION:
        raise RuntimeError("V894_VERSION_MISMATCH")
    if s894.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("POLICY_VERSION_MISMATCH")
    if s894.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V894_STATUS_MISMATCH")
    if len(rows894) != 112:
        raise RuntimeError(f"V894_ROW_COUNT:{len(rows894)}")

    ready = [r for r in rows894 if r.get("score_status") == "READY"]
    limited = [r for r in rows894 if r.get("score_status") == "LIMITED"]
    if len(ready) != 42 or len(limited) != 70:
        raise RuntimeError(
            f"V894_READY_LIMITED_MISMATCH:{len(ready)}:{len(limited)}"
        )

    out_rows = []
    reason_counter = Counter()
    category_counter = Counter()
    source_counter = Counter()
    single_counter = Counter()

    for row in limited:
        reasons = split_reasons(row.get("missing_components"))
        if not reasons:
            raise RuntimeError(
                "LIMITED_WITHOUT_MISSING_COMPONENTS:" + str(row.get("ticker"))
            )

        for reason in reasons:
            category, source_group, note = base.classify(reason)
            reason_counter[reason] += 1
            category_counter[category] += 1
            source_counter[source_group] += 1
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

    if not out_rows:
        raise RuntimeError("NO_BLOCKER_ROWS")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)

    ev_reason_counts = {
        reason: count
        for reason, count in reason_counter.items()
        if reason.startswith("EV/EBITDA:")
    }
    ev_total = sum(ev_reason_counts.values())
    if ev_total != 30:
        raise RuntimeError(f"V894_EV_BLOCKER_COUNT_MISMATCH:{ev_total}")

    ev_da_missing = sum(
        count for reason, count in ev_reason_counts.items()
        if reason.endswith(":NO_EXACT_CANDIDATE")
    )
    ev_exact_ok_other = sum(
        count for reason, count in ev_reason_counts.items()
        if reason.endswith(":OK:OK")
    )

    single_blocker_tickers = sorted({
        r["ticker"]
        for r in out_rows
        if r["single_blocker_ticker"] == "TRUE"
    })

    occurrence_priority = [
        {
            "source_group": source,
            "blocker_occurrences": count,
            "single_blocker_tickers": single_counter.get(source, 0),
        }
        for source, count in source_counter.most_common()
    ]

    recovery_candidates = [
        {
            "source_group": source,
            "single_blocker_tickers": single_counter.get(source, 0),
            "blocker_occurrences": source_counter[source],
        }
        for source in source_counter
        if source not in POLICY_ONLY_GROUPS
    ]
    recovery_candidates.sort(
        key=lambda x: (
            -x["single_blocker_tickers"],
            -x["blocker_occurrences"],
            x["source_group"],
        )
    )

    highest_impact_source_group = (
        recovery_candidates[0]["source_group"]
        if recovery_candidates else "NONE"
    )
    highest_impact_single_count = (
        recovery_candidates[0]["single_blocker_tickers"]
        if recovery_candidates else 0
    )

    if highest_impact_source_group == "EXACT_DA_SOURCE":
        next_step = "CONTINUE_EXACT_DA_RECOVERY_FROM_V891_REMAINING_LANES"
    elif highest_impact_source_group == "FINANCIAL_VALUATION_CACHE":
        next_step = "AUDIT_FINANCIAL_VALUATION_CACHE_RECOVERY"
    elif highest_impact_source_group == "PRODUCTION_ANALYSIS_SUPPLY":
        next_step = "AUDIT_SUPPLY_EVIDENCE_COMPLETENESS"
    elif highest_impact_source_group == "INVESTMENT_SCORE_SOURCE_CACHE":
        next_step = "AUDIT_RAW_FINANCIAL_SOURCE_CACHE_RECOVERY"
    elif highest_impact_source_group == "PRODUCTION_PRICE_METRICS":
        next_step = "AUDIT_PRODUCTION_PRICE_METRIC_RECOVERY"
    elif highest_impact_source_group == "OCF_AND_REVENUE_SOURCE":
        next_step = "AUDIT_OCF_AND_REVENUE_SOURCE_RECOVERY"
    elif highest_impact_source_group == "EXACT_CORE_DEBT_SOURCE":
        next_step = "AUDIT_EXACT_CORE_DEBT_SOURCE_RECOVERY"
    else:
        next_step = "REVIEW_V895_SOURCE_RECOVERY_PRIORITY"

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "v894_version": V894_VERSION,
        "base_classifier_version": V890_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "production_unique_tickers": 112,
        "ready_count": 42,
        "limited_count": 70,
        "limited_blocker_occurrences": len(out_rows),
        "single_blocker_ticker_count": len(single_blocker_tickers),
        "single_blocker_tickers": single_blocker_tickers,
        "blocker_category_counts": dict(category_counter),
        "source_group_counts": dict(source_counter),
        "source_priority_by_occurrences": occurrence_priority,
        "source_recovery_priority_by_single_blocker": recovery_candidates,
        "highest_impact_source_group": highest_impact_source_group,
        "highest_impact_single_blocker_ticker_count": highest_impact_single_count,
        "top_blocker_reasons": reason_counter.most_common(40),
        "ev_ebitda_audit": {
            "total_blocker_occurrences": ev_total,
            "reason_counts": ev_reason_counts,
            "da_no_exact_candidate_occurrences": ev_da_missing,
            "exact_debt_and_da_but_other_input_missing_occurrences": ev_exact_ok_other,
        },
        "policy_semantic_blockers": {
            "annual_op_denom_nonpositive_count": reason_counter.get(
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
            "v894_da_source_mutated": False,
        },
        "next_step": next_step,
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.9.5 V8.9.4 기준 남은 blocker 재감사",
            "",
            f"- 버전: `{VERSION}`",
            f"- 기준 dry-run: `{V894_VERSION}`",
            "- READY 42 / LIMITED 70",
            "- 상태: AUDIT_ONLY",
            "",
            "## 목적",
            "",
            "삼익악기 D&A 복구 후 남은 LIMITED blocker를 V8.9.0과 같은 분류기로 다시 계산한다.",
            "source 발생 건수뿐 아니라 한 source만 해결하면 READY가 되는 single-blocker 수를 우선순위에 반영한다.",
            "",
            "## 안전 원칙",
            "",
            "- 점수 공식·가중치·구간 변경 없음.",
            "- production score 기록 없음.",
            "- 결측값 임의 대체 없음.",
            "- 정책 semantic blocker는 자동 규칙 변경 대상에서 제외.",
            "",
            "## 다음 단계",
            "",
            f"최우선 source group: `{highest_impact_source_group}`",
            f"single-blocker 잠재 해소 종목: `{highest_impact_single_count}`",
            f"`{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY",
        "READY_COUNT=42",
        "LIMITED_COUNT=70",
        f"LIMITED_BLOCKER_OCCURRENCES={len(out_rows)}",
        f"SINGLE_BLOCKER_TICKER_COUNT={len(single_blocker_tickers)}",
        f"EV_EBITDA_BLOCKERS={ev_total}",
        f"EV_DA_NO_EXACT_CANDIDATE={ev_da_missing}",
        f"EV_EXACT_OK_OTHER_INPUT_MISSING={ev_exact_ok_other}",
        f"HIGHEST_IMPACT_SOURCE_GROUP={highest_impact_source_group}",
        f"HIGHEST_IMPACT_SINGLE_BLOCKER_COUNT={highest_impact_single_count}",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_SOURCE_VALUE_IMPUTED=false",
        "V894_DA_SOURCE_MUTATED=false",
        "STATUS=OK",
        f"NEXT_STEP={next_step}",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    print("V895_REMAINING_BLOCKER_REFRESH=PASS")
    print("\n".join(log))


if __name__ == "__main__":
    main()

