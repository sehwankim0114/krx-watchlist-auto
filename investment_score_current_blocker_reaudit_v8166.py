#!/usr/bin/env python3
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
from investment_score_current_blocker_reaudit_v8148 import classify
from investment_score_current_blocker_reaudit_v8161 import (
    recovery_status,
    ticker,
    split_reasons,
)

VERSION = "2026-09-23-v8.16.6-post-source-apply-current-blocker-reaudit"
POLICY = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8165_VERSION = "2026-09-22-v8.16.5-controlled-production-source-cache-apply-gate-repair"
V8165_COMMIT = "3cdd1bd7c2e1e74d01a3898de8a7f95b41b767ed"
V8156_VERSION = "2026-09-22-v8.15.6-mastern-q2-exhausted-dynamic-reaudit"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")
V8165 = ROOT / "latest/investment_score_source_production_v8165_summary_latest.json"
V8156 = ROOT / "latest/investment_score_current_blockers_v8156_summary_latest.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

TMP_CSV = Path("/tmp/v8166_score.csv")
TMP_JSON = Path("/tmp/v8166_score.json")
TMP_LOG = Path("/tmp/v8166_score.log")
TMP_DOC = Path("/tmp/v8166_score.md")
OUT_CSV = ROOT / "latest/investment_score_current_blockers_v8166.csv"
OUT_JSON = ROOT / "latest/investment_score_current_blockers_v8166_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_current_blockers_v8166_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_current_blockers_v8166.md"

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def run_scorer():
    old = {k: getattr(scorer, k) for k in (
        "VERSION","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC"
    )}
    try:
        scorer.VERSION = VERSION
        scorer.OUT_CSV = TMP_CSV
        scorer.OUT_JSON = TMP_JSON
        scorer.OUT_LOG = TMP_LOG
        scorer.OUT_DOC = TMP_DOC
        rc = scorer.main()
    finally:
        for k, v in old.items():
            setattr(scorer, k, v)
    if rc not in (None, 0):
        raise RuntimeError("V8166_SCORER_FAILED")

def main():
    s65 = read_json(V8165)
    s56 = read_json(V8156)
    mf = read_json(MANIFEST)

    assert s65["version"] == V8165_VERSION
    assert s65["status"] == "PRODUCTION_SOURCE_CACHE_APPLIED_GATE_COMPATIBILITY_REPAIRED"
    assert s65["policy_version"] == POLICY
    assert s65["next_step"] == "POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8166"
    assert s65["production_source_cache"]["row_count_after"] == 281
    assert s65["scorer_regression"]["blockers_after"] == 322
    assert s65["gate_repair"]["scheduled_gate_need_refresh_after_apply"] is False

    assert s56["version"] == V8156_VERSION
    ev = s56["known_exhausted_evidence"]
    da = set(ev["exact_da_exhausted_union_tickers"])
    q2 = set(ev["score_cache_q2_exhausted_tickers"])
    v8104 = set(ev["v8104_exhausted_tickers"])
    assert len(da) == 67
    assert q2 == {"357430","365550"}
    assert v8104 == {"001020","357250"}

    assert mf["release_stage"] == "PRODUCTION"
    assert mf["safe_to_analyze_as_latest"] is True

    run_scorer()
    with TMP_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ready = [r for r in rows if r["score_status"] == "READY"]
    limited = [r for r in rows if r["score_status"] == "LIMITED"]
    assert len(rows) == 120
    assert len(ready) == 21 and len(limited) == 99

    out = []
    cats = Counter()
    groups = Counter()
    gt = defaultdict(set)
    rec = Counter()
    single_counts = Counter()
    single_tickers = defaultdict(set)
    multi_counts = Counter()
    multi_tickers = defaultdict(set)

    for row in limited:
        reasons = split_reasons(row.get("missing_components"))
        code = ticker(row.get("ticker"))
        if not reasons:
            raise RuntimeError("LIMITED_WITHOUT_REASON:" + code)
        single = len(reasons) == 1
        for reason in reasons:
            cat, group = classify(reason)
            if group == "UNKNOWN":
                raise RuntimeError("UNCLASSIFIED:" + code + ":" + reason)
            status = recovery_status(
                code, group, single, da, q2, v8104
            )
            cats[cat] += 1
            groups[group] += 1
            gt[group].add(code)
            rec[status] += 1
            if single and status == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT":
                single_counts[group] += 1
                single_tickers[group].add(code)
            if not single:
                multi_counts[group] += 1
                multi_tickers[group].add(code)
            out.append({
                "ticker": code,
                "name": row.get("name",""),
                "market": row.get("market",""),
                "missing_component_count": len(reasons),
                "blocker_reason": reason,
                "blocker_category": cat,
                "source_group": group,
                "single_blocker_ticker": "TRUE" if single else "FALSE",
                "recovery_status": status,
            })

    assert len(out) == 322
    assert groups["FINANCIAL_VALUATION_CACHE"] == 49

    singles = sorted([
        {
            "source_group": g,
            "actionable_single_blocker_count": c,
            "actionable_single_blocker_tickers": sorted(single_tickers[g]),
            "total_group_blocker_occurrences": groups[g],
        }
        for g, c in single_counts.items() if c
    ], key=lambda x: (
        -x["actionable_single_blocker_count"],
        -x["total_group_blocker_occurrences"],
        x["source_group"],
    ))

    multis = sorted([
        {
            "source_group": g,
            "multi_blocker_occurrences": c,
            "multi_blocker_ticker_count": len(multi_tickers[g]),
            "multi_blocker_tickers": sorted(multi_tickers[g]),
            "total_group_blocker_occurrences": groups[g],
        }
        for g, c in multi_counts.items()
        if c and g != "V880_SCORING_CONTRACT"
    ], key=lambda x: (
        -x["multi_blocker_occurrences"],
        -x["multi_blocker_ticker_count"],
        x["source_group"],
    ))

    if singles:
        mode = "ACTIONABLE_SINGLE_BLOCKER"
        selected_group = singles[0]["source_group"]
        selected = singles[0]["actionable_single_blocker_tickers"]
        next_step = "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8167"
    elif multis:
        mode = "MULTI_BLOCKER_GROUP"
        selected_group = multis[0]["source_group"]
        selected = multis[0]["multi_blocker_tickers"]
        next_step = "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8167"
    else:
        mode = "NO_SOURCE_LANE"
        selected_group = ""
        selected = []
        next_step = "REVIEW_REMAINING_POLICY_ONLY_BLOCKERS"

    out.sort(key=lambda r: (
        int(r["missing_component_count"]), r["ticker"], r["blocker_reason"]
    ))
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_POST_SOURCE_APPLY_DYNAMIC_CURRENT_BLOCKERS",
        "policy_version": POLICY,
        "v8165_version": V8165_VERSION,
        "v8165_result_commit": V8165_COMMIT,
        "production_manifest": {
            "basis_date": mf.get("basis_date"),
            "source_build_id": mf.get("source_build_id"),
            "source_commit": mf.get("source_commit"),
            "kospi_rows": mf["tables"]["kospi"]["row_count"],
            "decliners_rows": mf["tables"]["decliners"]["row_count"],
            "decliners24_rows": mf["tables"]["decliners24"]["row_count"],
        },
        "scorer_universe_count": 120,
        "ready_count": 21,
        "limited_count": 99,
        "limited_blocker_occurrences": 322,
        "blocker_category_counts": dict(cats),
        "source_group_counts": dict(groups),
        "source_group_tickers": {g: sorted(v) for g, v in gt.items()},
        "recovery_status_counts": dict(rec),
        "known_exhausted_evidence": {
            "exact_da_exhausted_union_count": 67,
            "exact_da_exhausted_union_tickers": sorted(da),
            "score_cache_q2_exhausted_count": 2,
            "score_cache_q2_exhausted_tickers": sorted(q2),
            "v8104_exhausted_tickers": sorted(v8104),
        },
        "actionable_single_priority": singles,
        "multi_blocker_priority": multis,
        "selection_mode": mode,
        "selected_source_group": selected_group,
        "selected_ticker_count": len(selected),
        "selected_tickers": selected,
        "source_refresh_effect": {
            "pre_apply_blocker_occurrences": 475,
            "post_apply_blocker_occurrences": 322,
            "reduced_by": 153,
            "production_source_rows_before": 254,
            "production_source_rows_after": 281,
        },
        "operational_side_issue": {
            "build_api_run_id": 35737577552,
            "source_gate_run_id": 35737577494,
            "source_gate_failure_repaired_by_v8165": True,
            "build_api_failure_independent_of_source_gate": True,
            "build_api_failure_component": "PYKRX_KRX_LOGIN_RESPONSE_JSON_DECODE",
        },
        "hard_guards": {
            "production_data_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "exhausted_lane_auto_requeried": False,
        },
        "next_step": next_step,
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY_POST_SOURCE_APPLY_DYNAMIC_CURRENT_BLOCKERS",
        "SCORER_UNIVERSE=120",
        "READY=21",
        "LIMITED=99",
        "BLOCKER_OCCURRENCES=322",
        f"FINANCIAL_VALUATION_BLOCKERS={groups['FINANCIAL_VALUATION_CACHE']}",
        f"INVESTMENT_SCORE_SOURCE_CACHE_BLOCKERS={groups.get('INVESTMENT_SCORE_SOURCE_CACHE',0)}",
        f"ACTIONABLE_SINGLE_BLOCKERS={sum(single_counts.values())}",
        f"SELECTION_MODE={mode}",
        f"SELECTED_SOURCE_GROUP={selected_group}",
        f"SELECTED_TICKER_COUNT={len(selected)}",
        "BUILD_API_SIDE_ISSUE=PYKRX_KRX_LOGIN_RESPONSE_JSON_DECODE",
        "PRODUCTION_DATA_MODIFIED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={next_step}",
    ]) + "\n", encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join([
        "# V8.16.6 post-source-apply current blocker reaudit",
        "",
        "- Production scorer universe: 120.",
        "- READY / LIMITED: 21 / 99.",
        "- Current blockers: 322.",
        "- V8.16.5 reduced blockers by 153.",
        f"- Selected mode: {mode}.",
        f"- Selected source group: {selected_group}.",
        f"- Selected ticker count: {len(selected)}.",
        "- Build API failure is tracked separately as a pykrx/KRX login-response JSON decode issue.",
        "- No production data is modified.",
        "",
        f"Next: {next_step}",
        "",
    ]), encoding="utf-8")

    print("V8166_REAUDIT=PASS")
    print(f"V8166_SELECTED_SOURCE_GROUP={selected_group}")
    print(f"V8166_SELECTED_TICKER_COUNT={len(selected)}")
    print(f"V8166_NEXT_STEP={next_step}")

if __name__ == "__main__":
    main()
