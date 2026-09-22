#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
from investment_score_current_blocker_reaudit_v8148 import classify

VERSION = "2026-09-22-v8.15.9-stage-current-production-financial-cache-refresh"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8158_VERSION = "2026-09-22-v8.15.8-current-production-financial-refresh-shadow"
V8158_FIX = "2026-09-22-v8.15.8b-target-only-merge-fix"
V8158_RESULT_COMMIT = "81d3f459fd6f317bd080ef4a48a619f7aa021bf9"
NEXT_STEP = "CONTROLLED_PRODUCTION_FINANCIAL_CACHE_REFRESH_V8160"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD_FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
V8158_CAND = ROOT / "latest/investment_score_financial_refresh_candidate_v8158.csv"
V8158_SUMMARY = ROOT / "latest/investment_score_financial_refresh_shadow_v8158_summary_latest.json"

STAGED_FIN = ROOT / "latest/financial_valuation_cache_candidate_v8159.csv"
REGRESSION_CSV = ROOT / "latest/investment_score_financial_cache_stage_v8159_regression.csv"
SUMMARY_OUT = ROOT / "latest/investment_score_financial_cache_stage_v8159_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_financial_cache_stage_v8159_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_financial_cache_stage_v8159.md"

BASE_CSV = Path("/tmp/v8159_base_score.csv")
BASE_JSON = Path("/tmp/v8159_base_score.json")
BASE_LOG = Path("/tmp/v8159_base_score.log")
BASE_DOC = Path("/tmp/v8159_base_score.md")
CAND_CSV = Path("/tmp/v8159_candidate_score.csv")
CAND_JSON = Path("/tmp/v8159_candidate_score.json")
CAND_LOG = Path("/tmp/v8159_candidate_score.log")
CAND_DOC = Path("/tmp/v8159_candidate_score.md")

TARGET_GROUP = "FINANCIAL_VALUATION_CACHE"
EXPECTED_PARTIAL = {"014825"}

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return rows, fields

def write_rows(path, rows, fields):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

def row_map(path):
    rows, _ = read_rows(path)
    return {
        ticker(r.get("ticker")): r
        for r in rows
        if ticker(r.get("ticker"))
    }

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def split_missing(value):
    return [x for x in str(value or "").split(";") if x]

def group_count(row, group):
    n = 0
    for reason in split_missing(row.get("missing_components")):
        _, source_group = classify(reason)
        if source_group == group:
            n += 1
    return n

def total_blockers(rows):
    return sum(
        int(r.get("missing_component_count") or 0)
        for r in rows.values()
    )

def production_codes():
    out = set()
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in payload.get("rows") or []:
            code = ticker(row.get("ticker"))
            if code:
                out.add(code)
    return out

def run_scorer(fin_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "FIN": scorer.FIN,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.FIN = Path(fin_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8159_SCORER_FAILED:" + str(rc))

def validate_v8158(summary):
    if summary.get("version") != V8158_VERSION:
        raise RuntimeError("V8159_V8158_VERSION_MISMATCH")
    if summary.get("fix_revision") != V8158_FIX:
        raise RuntimeError("V8159_V8158_FIX_MISMATCH")
    if summary.get("status") != "SHADOW_ONLY_CURRENT_PRODUCTION_FINANCIAL_REFRESH_PASS":
        raise RuntimeError("V8159_V8158_STATUS_MISMATCH")
    if summary.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8159_POLICY_VERSION_MISMATCH")
    exact = {
        "target_count": 28,
        "production_financial_cache_rows": 271,
        "fresh_current_target_refresh_rows": 228,
        "shadow_financial_cache_rows": 299,
        "financial_cache_row_delta": 28,
        "existing_non_target_financial_row_changed_count": 0,
        "scorer_universe_count": 120,
        "baseline_ready_count": 21,
        "baseline_limited_count": 99,
        "shadow_ready_count": 21,
        "shadow_limited_count": 99,
        "ready_delta": 0,
        "limited_delta": 0,
        "baseline_total_blocker_occurrences": 688,
        "shadow_total_blocker_occurrences": 475,
        "total_blocker_occurrences_reduced_by": 213,
        "baseline_target_financial_blocker_occurrences": 221,
        "shadow_target_financial_blocker_occurrences": 8,
        "target_financial_blocker_occurrences_reduced_by": 213,
        "changed_target_score_row_count": 27,
        "non_target_score_row_changed_count": 0,
        "newly_ready_count": 0,
        "fully_financial_resolved_count": 27,
        "partial_financial_remaining_count": 1,
    }
    for key, value in exact.items():
        if summary.get(key) != value:
            raise RuntimeError(
                f"V8159_V8158_EXACT_MISMATCH:{key}:{summary.get(key)}:{value}"
            )
    if set(summary.get("partial_financial_remaining_tickers") or []) != EXPECTED_PARTIAL:
        raise RuntimeError("V8159_V8158_PARTIAL_SET_MISMATCH")
    if summary.get("merge_mode") != "PRESERVE_PRODUCTION_ROWS_AND_ADD_TARGET_ONLY":
        raise RuntimeError("V8159_V8158_MERGE_MODE_MISMATCH")
    if summary.get("automatic_promotion", {}).get("allowed") is not False:
        raise RuntimeError("V8159_V8158_AUTOPROMOTION_NOT_FALSE")
    if any(bool(v) for v in (summary.get("hard_guards") or {}).values()):
        raise RuntimeError("V8159_V8158_HARD_GUARD_TRUE")
    if summary.get("next_step") != "STAGE_CURRENT_PRODUCTION_FINANCIAL_CACHE_REFRESH_V8159":
        raise RuntimeError("V8159_V8158_NEXT_STEP_MISMATCH")

def main():
    for p in (PROD_FIN, V8158_CAND, V8158_SUMMARY):
        if not p.is_file():
            raise RuntimeError("V8159_MISSING_INPUT:" + str(p))

    prior = read_json(V8158_SUMMARY)
    validate_v8158(prior)

    targets = set(prior.get("target_tickers") or [])
    resolved = set(prior.get("fully_financial_resolved_tickers") or [])
    partial = set(prior.get("partial_financial_remaining_tickers") or [])
    changed_prior = set(prior.get("changed_target_score_tickers") or [])

    if len(targets) != 28:
        raise RuntimeError("V8159_TARGET_SET_NOT_28")
    if len(resolved) != 27 or partial != EXPECTED_PARTIAL:
        raise RuntimeError("V8159_RESOLUTION_SET_BAD")
    if resolved | partial != targets or resolved & partial:
        raise RuntimeError("V8159_TARGET_PARTITION_BAD")
    if changed_prior != resolved:
        raise RuntimeError("V8159_CHANGED_TARGETS_NOT_RESOLVED_SET")

    prod_rows, prod_fields = read_rows(PROD_FIN)
    cand_rows, cand_fields = read_rows(V8158_CAND)
    if prod_fields != cand_fields:
        raise RuntimeError("V8159_FINANCIAL_SCHEMA_MISMATCH")
    if len(prod_rows) != 271:
        raise RuntimeError("V8159_PROD_ROWS_NOT_271:" + str(len(prod_rows)))
    if len(cand_rows) != 28:
        raise RuntimeError("V8159_SOURCE_CANDIDATE_ROWS_NOT_28")

    prod_map = {
        ticker(r.get("ticker")): r
        for r in prod_rows
        if ticker(r.get("ticker"))
    }
    cand_map = {
        ticker(r.get("ticker")): r
        for r in cand_rows
        if ticker(r.get("ticker"))
    }
    if len(prod_map) != 271:
        raise RuntimeError("V8159_PROD_DUPLICATE_TICKER")
    if set(cand_map) != targets:
        raise RuntimeError("V8159_SOURCE_CANDIDATE_TARGET_SET_BAD")
    overlap = set(prod_map) & targets
    if overlap:
        raise RuntimeError("V8159_TARGET_ALREADY_IN_PRODUCTION:" + ",".join(sorted(overlap)))

    merged = dict(prod_map)
    merged.update(cand_map)
    if len(merged) != 299:
        raise RuntimeError("V8159_STAGED_ROWS_NOT_299:" + str(len(merged)))

    for code in prod_map:
        if stable(merged[code]) != stable(prod_map[code]):
            raise RuntimeError("V8159_EXISTING_PROD_ROW_CHANGED:" + code)
    for code in targets:
        if stable(merged[code]) != stable(cand_map[code]):
            raise RuntimeError("V8159_TARGET_ROW_CHANGED:" + code)

    write_rows(
        STAGED_FIN,
        [merged[code] for code in sorted(merged)],
        prod_fields,
    )

    run_scorer(PROD_FIN, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC)
    run_scorer(STAGED_FIN, CAND_CSV, CAND_JSON, CAND_LOG, CAND_DOC)

    base = row_map(BASE_CSV)
    cand = row_map(CAND_CSV)
    base_summary = read_json(BASE_JSON)
    cand_summary = read_json(CAND_JSON)
    active = production_codes()

    if set(base) != set(cand) or set(base) != active:
        raise RuntimeError("V8159_SCORER_UNIVERSE_DRIFT")
    if len(active) != 120:
        raise RuntimeError("V8159_SCORER_UNIVERSE_NOT_120:" + str(len(active)))

    non_target_changed = [
        code for code in sorted(active - targets)
        if stable(base[code]) != stable(cand[code])
    ]
    if non_target_changed:
        raise RuntimeError("V8159_NON_TARGET_SCORE_DRIFT:" + ",".join(non_target_changed[:20]))

    target_changed = [
        code for code in sorted(targets)
        if stable(base[code]) != stable(cand[code])
    ]
    if set(target_changed) != resolved:
        raise RuntimeError("V8159_TARGET_CHANGED_SET_MISMATCH")

    lost_ready = [
        code for code in sorted(active)
        if base[code].get("score_status") == "READY"
        and cand[code].get("score_status") != "READY"
    ]
    if lost_ready:
        raise RuntimeError("V8159_LOST_READY:" + ",".join(lost_ready))

    newly_ready = [
        code for code in sorted(active)
        if base[code].get("score_status") != "READY"
        and cand[code].get("score_status") == "READY"
    ]
    if newly_ready:
        raise RuntimeError("V8159_UNEXPECTED_NEW_READY:" + ",".join(newly_ready))

    base_total = total_blockers(base)
    cand_total = total_blockers(cand)
    target_fin_base = sum(group_count(base[c], TARGET_GROUP) for c in targets)
    target_fin_cand = sum(group_count(cand[c], TARGET_GROUP) for c in targets)

    exact_checks = {
        "base_ready": int(base_summary.get("ready_count") or 0),
        "cand_ready": int(cand_summary.get("ready_count") or 0),
        "base_limited": int(base_summary.get("limited_count") or 0),
        "cand_limited": int(cand_summary.get("limited_count") or 0),
        "base_total": base_total,
        "cand_total": cand_total,
        "target_fin_base": target_fin_base,
        "target_fin_cand": target_fin_cand,
    }
    expected = {
        "base_ready": 21,
        "cand_ready": 21,
        "base_limited": 99,
        "cand_limited": 99,
        "base_total": 688,
        "cand_total": 475,
        "target_fin_base": 221,
        "target_fin_cand": 8,
    }
    if exact_checks != expected:
        raise RuntimeError(
            "V8159_REGRESSION_EXACT_MISMATCH:"
            + json.dumps(exact_checks, sort_keys=True)
        )

    regression_rows = []
    for code in sorted(targets):
        regression_rows.append({
            "ticker": code,
            "baseline_score_status": base[code].get("score_status", ""),
            "candidate_score_status": cand[code].get("score_status", ""),
            "baseline_missing_component_count": base[code].get("missing_component_count", ""),
            "candidate_missing_component_count": cand[code].get("missing_component_count", ""),
            "baseline_financial_blockers": group_count(base[code], TARGET_GROUP),
            "candidate_financial_blockers": group_count(cand[code], TARGET_GROUP),
            "score_row_changed": "true" if code in target_changed else "false",
            "financial_resolution": "FULL" if code in resolved else "PARTIAL_NO_CORP_CODE",
        })
    write_rows(
        REGRESSION_CSV,
        regression_rows,
        list(regression_rows[0].keys()),
    )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "STAGED_FINANCIAL_CACHE_CANDIDATE_REGRESSION_PASS",
        "policy_version": POLICY_VERSION,
        "v8158_version": V8158_VERSION,
        "v8158_fix_revision": V8158_FIX,
        "v8158_result_commit": V8158_RESULT_COMMIT,
        "staged_cache": {
            "production_row_count": 271,
            "source_candidate_row_count": 28,
            "staged_row_count": 299,
            "target_count": 28,
            "fully_financial_resolved_count": 27,
            "partial_financial_remaining_count": 1,
            "partial_financial_remaining_tickers": sorted(partial),
            "merge_mode": "PRESERVE_PRODUCTION_ROWS_AND_ADD_V8158_TARGETS",
        },
        "scorer_regression": {
            "universe_count": 120,
            "baseline_ready_count": 21,
            "candidate_ready_count": 21,
            "baseline_limited_count": 99,
            "candidate_limited_count": 99,
            "baseline_total_blocker_occurrences": 688,
            "candidate_total_blocker_occurrences": 475,
            "blocker_occurrences_reduced_by": 213,
            "baseline_target_financial_blocker_occurrences": 221,
            "candidate_target_financial_blocker_occurrences": 8,
            "target_financial_blocker_occurrences_reduced_by": 213,
            "changed_target_score_row_count": 27,
            "changed_target_score_tickers": target_changed,
            "non_target_score_row_changed_count": 0,
            "newly_ready_count": 0,
            "lost_ready_count": 0,
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_financial_cache_modified": False,
            "production_financial_run_log_modified": False,
            "production_raw_score_cache_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "corp_identity_policy_modified": False,
            "source_value_imputed": False,
            "non_target_score_row_changed": False,
        },
        "next_step": NEXT_STEP,
    }
    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=STAGED_FINANCIAL_CACHE_CANDIDATE_REGRESSION_PASS",
            "PROD_FIN_ROWS=271",
            "SOURCE_CANDIDATE_ROWS=28",
            "STAGED_FIN_ROWS=299",
            "TARGET_COUNT=28",
            "FULLY_FINANCIAL_RESOLVED=27",
            "PARTIAL_FINANCIAL_REMAINING=1",
            "PARTIAL_TICKERS=014825",
            "SCORER_UNIVERSE=120",
            "BASE_READY=21",
            "CANDIDATE_READY=21",
            "BASE_LIMITED=99",
            "CANDIDATE_LIMITED=99",
            "BASE_TOTAL_BLOCKERS=688",
            "CANDIDATE_TOTAL_BLOCKERS=475",
            "TOTAL_BLOCKER_REDUCTION=213",
            "BASE_TARGET_FIN_BLOCKERS=221",
            "CANDIDATE_TARGET_FIN_BLOCKERS=8",
            "TARGET_FIN_BLOCKER_REDUCTION=213",
            "CHANGED_TARGET_SCORE_ROWS=27",
            "NON_TARGET_SCORE_ROW_CHANGED=0",
            "NEWLY_READY=0",
            "LOST_READY=0",
            "AUTOMATIC_PROMOTION=false",
            "PRODUCTION_DATA_MODIFIED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={NEXT_STEP}",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.15.9 staged financial cache candidate",
            "",
            "- Stages the exact V8.15.8B target-only financial-cache result for controlled production promotion.",
            "- Production financial cache remains unchanged in this step.",
            "- Production rows: 271; V8.15.8 target rows: 28; staged rows: 299.",
            "- 27 targets fully resolve financial blockers; 014825 remains NO_CORP_CODE with 8 blockers.",
            "- Scorer READY/LIMITED remains 21/99.",
            "- Total blockers reproduce V8.15.8B exactly: 688 -> 475 (-213).",
            "- Target financial blockers reproduce exactly: 221 -> 8 (-213).",
            "- Non-target score drift: 0; newly READY: 0; lost READY: 0.",
            "- No production cache/API/policy file is modified.",
            "",
            "Next: CONTROLLED_PRODUCTION_FINANCIAL_CACHE_REFRESH_V8160",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8159_STAGE_REGRESSION=PASS")
    print("V8159_STAGED_FIN_ROWS=299")
    print("V8159_TARGET_FIN_BLOCKERS=221->8")
    print("V8159_TOTAL_BLOCKERS=688->475")
    print("V8159_NEXT_STEP=" + NEXT_STEP)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
