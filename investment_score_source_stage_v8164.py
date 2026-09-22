#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.16.4-stage-source-cache-refresh-gate-repair"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8163_VERSION = "2026-09-22-v8.16.3-shadow-current-source-cache-refresh-gate-repair"
V8163_RESULT_COMMIT = "81495d613c0cf34dfba3e7c3e9a10ea6bfa14601"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD_RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
CAND_RAW = ROOT / "latest/investment_score_source_cache_candidate_v8163.csv"
V8163_JSON = ROOT / "latest/investment_score_source_shadow_v8163_summary_latest.json"

STAGED_RAW = ROOT / "latest/investment_score_source_cache_candidate_v8164.csv"
OUT_JSON = ROOT / "latest/investment_score_source_stage_v8164_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_source_stage_v8164_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_source_stage_v8164.md"

BASE_CSV = Path("/tmp/v8164_base.csv")
BASE_JSON = Path("/tmp/v8164_base.json")
BASE_LOG = Path("/tmp/v8164_base.log")
BASE_DOC = Path("/tmp/v8164_base.md")
CAND_CSV = Path("/tmp/v8164_candidate.csv")
CAND_JSON = Path("/tmp/v8164_candidate.json")
CAND_LOG = Path("/tmp/v8164_candidate.log")
CAND_DOC = Path("/tmp/v8164_candidate.md")

EXPECTED_ADDED = {
    "000050","001020","001460","002450","002990","003060","003480",
    "003850","004990","006060","006220","008250","011330","013890",
    "016590","023530","024090","058650","070960","071950","097520",
    "145990","241590","298000","298050","363280","446070",
}

EXPECTED_CHANGED = EXPECTED_ADDED | {"002995"}

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])

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

def total_blockers(rows):
    return sum(
        int(r.get("missing_component_count") or 0)
        for r in rows.values()
    )

def run_scorer(raw_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "RAW": scorer.RAW,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.RAW = Path(raw_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8164_SCORER_FAILED:" + str(rc))

def last_commit(path):
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", str(path)],
        text=True,
    ).strip()

def main():
    s = read_json(V8163_JSON)
    if s.get("version") != V8163_VERSION:
        raise RuntimeError("V8164_V8163_VERSION_MISMATCH")
    if s.get("status") != "SHADOW_ONLY_CURRENT_SOURCE_CACHE_REFRESH_PASS":
        raise RuntimeError("V8164_V8163_STATUS_MISMATCH")
    if s.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8164_POLICY_VERSION_MISMATCH")
    if s.get("next_step") != "STAGE_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_V8164":
        raise RuntimeError("V8164_PREDECESSOR_NEXT_STEP_MISMATCH")

    sc = s.get("source_cache") or {}
    rg = s.get("scorer_regression") or {}
    gate = s.get("gate_repair_candidate") or {}

    if (
        int(sc.get("production_row_count") or 0),
        int(sc.get("shadow_row_count") or 0),
        int(sc.get("row_delta") or 0),
        int(sc.get("actual_added_ticker_count") or 0),
    ) != (254, 281, 27, 27):
        raise RuntimeError("V8164_SOURCE_CACHE_EXACT_MISMATCH")

    if set(sc.get("actual_added_tickers") or []) != EXPECTED_ADDED:
        raise RuntimeError("V8164_ADDED_SET_MISMATCH")

    exact_reg = (
        int(rg.get("universe_count") or 0),
        int(rg.get("baseline_ready_count") or 0),
        int(rg.get("shadow_ready_count") or 0),
        int(rg.get("baseline_limited_count") or 0),
        int(rg.get("shadow_limited_count") or 0),
        int(rg.get("baseline_blocker_occurrences") or 0),
        int(rg.get("shadow_blocker_occurrences") or 0),
        int(rg.get("blocker_occurrences_reduced_by") or 0),
        int(rg.get("changed_selected_score_row_count") or 0),
        int(rg.get("non_selected_score_row_changed_count") or 0),
        int(rg.get("newly_ready_count") or 0),
        int(rg.get("lost_ready_count") or 0),
    )
    if exact_reg != (120, 21, 21, 99, 99, 475, 322, 153, 28, 0, 0, 0):
        raise RuntimeError("V8164_REGRESSION_EXACT_MISMATCH:" + repr(exact_reg))

    if set(rg.get("changed_selected_score_tickers") or []) != EXPECTED_CHANGED:
        raise RuntimeError("V8164_CHANGED_SCORE_SET_MISMATCH")

    if gate.get("strategy") != "GIT_LAST_MODIFY_COMMIT_ANCESTRY":
        raise RuntimeError("V8164_GATE_STRATEGY_MISMATCH")
    if gate.get("need_refresh") is not True:
        raise RuntimeError("V8164_GATE_SHOULD_NEED_REFRESH")
    if gate.get("reason") != "financial_cache_changed_after_source_cache":
        raise RuntimeError("V8164_GATE_REASON_MISMATCH")
    if gate.get("uses_run_at_kst") is not False:
        raise RuntimeError("V8164_GATE_MUST_NOT_USE_RUN_AT_KST")

    prod_rows, prod_fields = read_rows(PROD_RAW)
    cand_rows, cand_fields = read_rows(CAND_RAW)
    if prod_fields != cand_fields:
        raise RuntimeError("V8164_SCHEMA_MISMATCH")
    if len(prod_rows) != 254 or len(cand_rows) != 281:
        raise RuntimeError("V8164_ROW_COUNT_MISMATCH")

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
    if len(prod_map) != 254 or len(cand_map) != 281:
        raise RuntimeError("V8164_DUPLICATE_TICKER")
    if not set(prod_map) < set(cand_map):
        raise RuntimeError("V8164_PROD_NOT_SUBSET")
    if set(cand_map) - set(prod_map) != EXPECTED_ADDED:
        raise RuntimeError("V8164_CANDIDATE_ADDED_SET_BAD")

    # Existing rows may be refreshed by the current enricher.
    # Stage the exact complete candidate rather than merging rows.
    STAGED_RAW.write_bytes(CAND_RAW.read_bytes())

    run_scorer(
        PROD_RAW, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC
    )
    run_scorer(
        STAGED_RAW, CAND_CSV, CAND_JSON, CAND_LOG, CAND_DOC
    )

    base = row_map(BASE_CSV)
    cand = row_map(CAND_CSV)
    base_s = read_json(BASE_JSON)
    cand_s = read_json(CAND_JSON)

    if set(base) != set(cand) or len(base) != 120:
        raise RuntimeError("V8164_SCORER_UNIVERSE_DRIFT")

    exact_now = (
        int(base_s.get("ready_count") or 0),
        int(cand_s.get("ready_count") or 0),
        int(base_s.get("limited_count") or 0),
        int(cand_s.get("limited_count") or 0),
        total_blockers(base),
        total_blockers(cand),
    )
    if exact_now != (21, 21, 99, 99, 475, 322):
        raise RuntimeError("V8164_STAGE_REPRO_MISMATCH:" + repr(exact_now))

    changed = {
        code for code in base
        if stable(base[code]) != stable(cand[code])
    }
    if changed != EXPECTED_CHANGED:
        raise RuntimeError(
            "V8164_REPRO_CHANGED_SET_MISMATCH:"
            + ",".join(sorted(changed))
        )

    lost_ready = [
        code for code in base
        if base[code].get("score_status") == "READY"
        and cand[code].get("score_status") != "READY"
    ]
    if lost_ready:
        raise RuntimeError("V8164_LOST_READY:" + ",".join(sorted(lost_ready)))

    fin_commit = last_commit("latest/financial_valuation_cache_latest.csv")
    source_commit = last_commit("latest/investment_score_source_cache_latest.csv")
    if fin_commit != gate.get("financial_cache_commit"):
        raise RuntimeError("V8164_FIN_COMMIT_DRIFT")
    if source_commit != gate.get("source_cache_commit"):
        raise RuntimeError("V8164_SOURCE_COMMIT_DRIFT")
    if not subprocess.call(
        ["git", "merge-base", "--is-ancestor", source_commit, fin_commit]
    ) == 0:
        raise RuntimeError("V8164_COMMIT_ANCESTRY_GATE_NOT_REPRODUCIBLE")

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "STAGED_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_PASS",
        "policy_version": POLICY_VERSION,
        "v8163_version": V8163_VERSION,
        "v8163_result_commit": V8163_RESULT_COMMIT,
        "staged_source_cache": {
            "production_row_count": 254,
            "staged_row_count": 281,
            "row_delta": 27,
            "added_ticker_count": 27,
            "added_tickers": sorted(EXPECTED_ADDED),
        },
        "scorer_regression": {
            "universe_count": 120,
            "baseline_ready_count": 21,
            "staged_ready_count": 21,
            "baseline_limited_count": 99,
            "staged_limited_count": 99,
            "baseline_blocker_occurrences": 475,
            "staged_blocker_occurrences": 322,
            "blocker_occurrences_reduced_by": 153,
            "changed_score_row_count": 28,
            "changed_score_tickers": sorted(EXPECTED_CHANGED),
            "non_selected_score_row_changed_count": 0,
            "newly_ready_count": 0,
            "lost_ready_count": 0,
        },
        "gate_repair_stage": {
            "strategy": "GIT_LAST_MODIFY_COMMIT_ANCESTRY",
            "financial_cache_commit": fin_commit,
            "source_cache_commit": source_commit,
            "need_refresh_before_apply": True,
            "reason": "financial_cache_changed_after_source_cache",
            "uses_run_at_kst": False,
            "manual_dispatch_force_refresh_preserved": True,
            "production_workflow_modified": False,
        },
        "automatic_promotion": {
            "allowed": False,
            "production_source_cache_modified": False,
            "production_gate_workflow_modified": False,
        },
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_financial_run_log_modified": False,
            "production_gate_workflow_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "non_selected_score_row_changed": False,
        },
        "next_step": "CONTROLLED_SOURCE_CACHE_APPLY_AND_GATE_REPAIR_V8165",
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=STAGED_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_PASS",
            "PRODUCTION_SOURCE_ROWS=254",
            "STAGED_SOURCE_ROWS=281",
            "SOURCE_ROW_DELTA=27",
            "ADDED_TICKERS=27",
            "SCORER_UNIVERSE=120",
            "BASELINE_READY=21",
            "STAGED_READY=21",
            "BASELINE_LIMITED=99",
            "STAGED_LIMITED=99",
            "BASELINE_BLOCKERS=475",
            "STAGED_BLOCKERS=322",
            "BLOCKER_REDUCED_BY=153",
            "CHANGED_SCORE_ROWS=28",
            "NON_SELECTED_SCORE_ROW_CHANGED=0",
            "NEWLY_READY=0",
            "LOST_READY=0",
            "GATE_STRATEGY=GIT_LAST_MODIFY_COMMIT_ANCESTRY",
            "GATE_USES_RUN_AT_KST=false",
            "GATE_REPRODUCIBLE=true",
            "PRODUCTION_DATA_MODIFIED=false",
            "PRODUCTION_GATE_WORKFLOW_MODIFIED=false",
            "AUTOMATIC_PROMOTION=false",
            "STATUS_OK=true",
            "NEXT_STEP=CONTROLLED_SOURCE_CACHE_APPLY_AND_GATE_REPAIR_V8165",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.16.4 source-cache refresh and gate-repair stage",
            "",
            "- Exact V8.16.3 281-row source-cache candidate is staged.",
            "- Production source cache remains 254 rows in this step.",
            "- Scorer blockers reproduce 475 -> 322 (-153).",
            "- READY / LIMITED remains 21 / 99.",
            "- 28 selected score rows change; no other score row changes.",
            "- No READY ticker is lost.",
            "- Git last-modifying commit ancestry reproduces NEED_REFRESH=true.",
            "- Production V8.5.4 workflow is not modified in this stage.",
            "",
            "Next: CONTROLLED_SOURCE_CACHE_APPLY_AND_GATE_REPAIR_V8165",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8164_STAGE=PASS")
    print("V8164_SOURCE_ROWS=254->281")
    print("V8164_BLOCKERS=475->322")
    print("V8164_BLOCKER_REDUCTION=153")
    print("V8164_CHANGED_SCORE_ROWS=28")
    print("V8164_GATE_REPRODUCIBLE=true")
    print("V8164_NEXT_STEP=CONTROLLED_SOURCE_CACHE_APPLY_AND_GATE_REPAIR_V8165")

if __name__ == "__main__":
    main()
