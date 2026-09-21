#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-21-v8.13.3a-controlled-production-ocf-refresh"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
CANDIDATE_VERSION = "2026-09-21-v8.13.2-stage-current-universe-ocf-refresh"
OCF_CONTRACT_VERSION = "2026-09-12-v8.7.4-audited-operating-cash-flow-source"
IFRS_OCF_ID = "ifrs-full_CashFlowsFromUsedInOperatingActivities"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

CAND_CSV = ROOT / "latest/investment_score_ocf_candidate_v8132.csv"
CAND_JSON = ROOT / "latest/investment_score_ocf_candidate_v8132_summary_latest.json"

PROD_CSV = ROOT / "latest/investment_score_ocf_source_latest.csv"
PROD_JSON = ROOT / "latest/investment_score_ocf_source_latest.json"
PROD_LOG = ROOT / "latest/investment_score_ocf_source_run_log_latest.txt"

OUT_JSON = ROOT / "latest/investment_score_ocf_production_refresh_v8133a_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_ocf_production_refresh_v8133a_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_ocf_production_refresh_v8133a.md"

BASE_CSV = Path("/tmp/v8133a_baseline_score.csv")
BASE_JSON = Path("/tmp/v8133a_baseline_score.json")
BASE_LOG = Path("/tmp/v8133a_baseline_score.log")
BASE_DOC = Path("/tmp/v8133a_baseline_score.md")
CAND_SCORE_CSV = Path("/tmp/v8133a_candidate_score.csv")
CAND_SCORE_JSON = Path("/tmp/v8133a_candidate_score.json")
CAND_SCORE_LOG = Path("/tmp/v8133a_candidate_score.log")
CAND_SCORE_DOC = Path("/tmp/v8133a_candidate_score.md")
POST_CSV = Path("/tmp/v8133a_post_score.csv")
POST_JSON = Path("/tmp/v8133a_post_score.json")
POST_LOG = Path("/tmp/v8133a_post_score.log")
POST_DOC = Path("/tmp/v8133a_post_score.md")

EXPECTED_UNRESOLVED = {"000480", "002200"}

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def run_scorer(ocf_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "OCF": scorer.OCF,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.OCF = Path(ocf_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8133A_SCORER_FAILED:" + str(rc))

def score_map(path):
    return {
        ticker(r.get("ticker")): r
        for r in read_rows(path)
        if ticker(r.get("ticker"))
    }

def main():
    candidate_commit = os.environ.get(
        "V8133A_CANDIDATE_COMMIT", ""
    ).strip()
    if not candidate_commit:
        raise RuntimeError("V8133A_CANDIDATE_COMMIT_MISSING")

    for p in (CAND_CSV, CAND_JSON, PROD_CSV, PROD_JSON, PROD_LOG):
        if not p.is_file():
            raise RuntimeError("V8133A_MISSING_INPUT:" + str(p))

    staged = read_json(CAND_JSON)
    if staged.get("version") != CANDIDATE_VERSION:
        raise RuntimeError("V8133A_CANDIDATE_VERSION_MISMATCH")
    if staged.get("status") != "STAGED_CANDIDATE_REGRESSION_PASS":
        raise RuntimeError("V8133A_CANDIDATE_STATUS_MISMATCH")
    if staged.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8133A_POLICY_VERSION_MISMATCH")
    if staged.get("ocf_contract_version") != OCF_CONTRACT_VERSION:
        raise RuntimeError("V8133A_OCF_CONTRACT_VERSION_MISMATCH")
    if staged.get("next_step") != "CONTROLLED_PRODUCTION_OCF_REFRESH_V8133":
        raise RuntimeError("V8133A_NEXT_STEP_MISMATCH")
    if int(staged.get("current_scorer_universe_count") or 0) != 149:
        raise RuntimeError("V8133A_UNIVERSE_NOT_149")

    candidate_meta = staged.get("candidate_ocf") or {}
    regression = staged.get("scorer_regression") or {}
    hard = staged.get("hard_guards") or {}

    if int(candidate_meta.get("row_count") or 0) != 149:
        raise RuntimeError("V8133A_CANDIDATE_ROWS_NOT_149")
    if (
        int(candidate_meta.get("ready_count") or 0),
        int(candidate_meta.get("limited_count") or 0),
    ) != (147, 2):
        raise RuntimeError("V8133A_CANDIDATE_SOURCE_COUNT_NOT_147_2")
    if int(candidate_meta.get("strict_identity_unresolved_count") or 0) != 2:
        raise RuntimeError("V8133A_UNRESOLVED_COUNT_NOT_2")
    if set(
        candidate_meta.get("strict_identity_unresolved_tickers") or []
    ) != EXPECTED_UNRESOLVED:
        raise RuntimeError("V8133A_UNRESOLVED_SET_CHANGED")

    if int(regression.get("baseline_ready_count") or 0) != 19:
        raise RuntimeError("V8133A_BASELINE_READY_NOT_19")
    if int(regression.get("baseline_limited_count") or 0) != 130:
        raise RuntimeError("V8133A_BASELINE_LIMITED_NOT_130")
    if int(regression.get("baseline_blocker_occurrences") or 0) != 796:
        raise RuntimeError("V8133A_BASELINE_BLOCKERS_NOT_796")
    if int(regression.get("candidate_ready_count") or 0) != 23:
        raise RuntimeError("V8133A_CANDIDATE_READY_NOT_23")
    if int(regression.get("ready_delta") or 0) != 4:
        raise RuntimeError("V8133A_READY_DELTA_NOT_4")
    if int(regression.get("blocker_occurrences_reduced_by") or 0) != 64:
        raise RuntimeError("V8133A_BLOCKER_REDUCTION_NOT_64")
    if int(regression.get("ocf_reason_removed_count") or 0) != 64:
        raise RuntimeError("V8133A_OCF_REMOVAL_NOT_64")
    if int(regression.get("lost_ready_count") or 0) != 0:
        raise RuntimeError("V8133A_LOST_READY_NOT_ZERO")
    if int(
        regression.get(
            "previously_ready_score_or_band_changed_count"
        ) or 0
    ) != 0:
        raise RuntimeError("V8133A_PRIOR_READY_SCORE_CHANGED")
    if int(regression.get("non_ocf_missing_reason_drift_count") or 0) != 0:
        raise RuntimeError("V8133A_NON_OCF_DRIFT")
    if int(regression.get("added_missing_reason_count") or 0) != 0:
        raise RuntimeError("V8133A_ADDED_MISSING_REASON")
    if any(bool(v) for v in hard.values()):
        raise RuntimeError("V8133A_CANDIDATE_HARD_GUARD_NOT_FALSE")

    prod_meta_before = read_json(PROD_JSON)
    if prod_meta_before.get("version") != OCF_CONTRACT_VERSION:
        raise RuntimeError("V8133A_PROD_CONTRACT_VERSION_MISMATCH")
    if prod_meta_before.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError("V8133A_PROD_STATUS_MISMATCH")
    if prod_meta_before.get("account_id_policy") != (
        "EXACT_ONLY:" + IFRS_OCF_ID
    ):
        raise RuntimeError("V8133A_PROD_ACCOUNT_POLICY_MISMATCH")

    prod_rows_before = read_rows(PROD_CSV)
    if len(prod_rows_before) != 112:
        raise RuntimeError(
            "V8133A_PROD_BEFORE_ROWS_NOT_112:"
            + str(len(prod_rows_before))
        )

    candidate_rows = read_rows(CAND_CSV)
    if len(candidate_rows) != 149:
        raise RuntimeError("V8133A_CANDIDATE_CSV_ROWS_NOT_149")
    if len({
        ticker(r.get("ticker")) for r in candidate_rows
    }) != 149:
        raise RuntimeError("V8133A_CANDIDATE_DUPLICATE_TICKER")
    if any(
        r.get("account_id") != IFRS_OCF_ID
        for r in candidate_rows
    ):
        raise RuntimeError("V8133A_CANDIDATE_ACCOUNT_ID_DRIFT")

    source_counts = Counter(
        r.get("source_mode") or "MISSING"
        for r in candidate_rows
    )
    ready_rows = [
        r for r in candidate_rows
        if r.get("source_status") == "READY"
    ]
    limited_rows = [
        r for r in candidate_rows
        if r.get("source_status") != "READY"
    ]
    if len(ready_rows) != int(candidate_meta["ready_count"]):
        raise RuntimeError("V8133A_CANDIDATE_READY_COUNT_MISMATCH")
    if len(limited_rows) != int(candidate_meta["limited_count"]):
        raise RuntimeError("V8133A_CANDIDATE_LIMITED_COUNT_MISMATCH")

    unresolved_rows = {
        ticker(r.get("ticker"))
        for r in limited_rows
        if r.get("source_mode") == "UNRESOLVED_CURRENT_IDENTITY"
    }
    if not EXPECTED_UNRESOLVED <= unresolved_rows:
        raise RuntimeError("V8133A_UNRESOLVED_ROWS_NOT_PRESERVED")

    run_scorer(
        PROD_CSV,
        BASE_CSV,
        BASE_JSON,
        BASE_LOG,
        BASE_DOC,
    )
    run_scorer(
        CAND_CSV,
        CAND_SCORE_CSV,
        CAND_SCORE_JSON,
        CAND_SCORE_LOG,
        CAND_SCORE_DOC,
    )

    bsum = read_json(BASE_JSON)
    csum = read_json(CAND_SCORE_JSON)

    if (
        int(bsum.get("ready_count") or 0),
        int(bsum.get("limited_count") or 0),
    ) != (19, 130):
        raise RuntimeError("V8133A_RECHECK_BASELINE_COUNT_DRIFT")

    base_map = score_map(BASE_CSV)
    cand_map = score_map(CAND_SCORE_CSV)
    b_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in base_map.values()
    )
    c_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in cand_map.values()
    )
    if b_blockers != 796:
        raise RuntimeError("V8133A_RECHECK_BASELINE_BLOCKER_DRIFT")

    expected_c_ready = int(regression["candidate_ready_count"])
    expected_c_limited = int(regression["candidate_limited_count"])
    expected_c_blockers = int(
        regression["candidate_blocker_occurrences"]
    )
    if (
        int(csum.get("ready_count") or 0),
        int(csum.get("limited_count") or 0),
        c_blockers,
    ) != (
        expected_c_ready,
        expected_c_limited,
        expected_c_blockers,
    ):
        raise RuntimeError("V8133A_CANDIDATE_RECHECK_MISMATCH")

    for code, brow in base_map.items():
        if brow.get("score_status") == "READY":
            crow = cand_map[code]
            if (
                crow.get("score_status") != "READY"
                or brow.get("score_total") != crow.get("score_total")
                or brow.get("score_band") != crow.get("score_band")
            ):
                raise RuntimeError(
                    "V8133A_PRIOR_READY_RECHECK_CHANGED:" + code
                )

    shutil.copyfile(CAND_CSV, PROD_CSV)

    refresh_meta = {
        "version": OCF_CONTRACT_VERSION,
        "refresh_version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "READY_SOURCE_ONLY",
        "production_unique_tickers": 149,
        "operating_cash_flow_ready": len(ready_rows),
        "operating_cash_flow_limited": len(limited_rows),
        "account_id_policy": "EXACT_ONLY:" + IFRS_OCF_ID,
        "preferred_inheritance_policy": (
            "APPROVED_CURRENT_FINANCIAL_IDENTITY_OR_EXACT_DART_"
            "STOCK_CODE_NAME_OR_VERIFIED_PREFERRED_COMMON_ONLY"
        ),
        "promoted_from_candidate_version": CANDIDATE_VERSION,
        "promoted_from_candidate_commit": candidate_commit,
        "strict_identity_unresolved_count": 2,
        "strict_identity_unresolved_tickers": sorted(
            EXPECTED_UNRESOLVED
        ),
        "source_mode_counts": dict(source_counts),
        "scorer_validation": {
            "baseline_ready_count": 19,
            "post_ready_count": expected_c_ready,
            "ready_delta": expected_c_ready - 19,
            "baseline_blocker_occurrences": 796,
            "post_blocker_occurrences": expected_c_blockers,
            "blocker_occurrences_reduced_by": (
                796 - expected_c_blockers
            ),
        },
        "hard_guards": {
            "investment_score_100_calculated": False,
            "score_thresholds_changed": False,
            "production_api_changed": False,
            "source_value_imputed": False,
            "alternate_ocf_account_id_used": False,
            "unresolved_identity_force_mapped": False,
        },
    }
    PROD_JSON.write_text(
        json.dumps(refresh_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    PROD_LOG.write_text(
        "\n".join([
            f"VERSION={OCF_CONTRACT_VERSION}",
            f"REFRESH_VERSION={VERSION}",
            "PRODUCTION_UNIQUE_TICKERS=149",
            f"OPERATING_CASH_FLOW_READY={len(ready_rows)}",
            f"OPERATING_CASH_FLOW_LIMITED={len(limited_rows)}",
            f"SCORER_READY={expected_c_ready}",
            f"SCORER_LIMITED={expected_c_limited}",
            f"SCORER_BLOCKERS={expected_c_blockers}",
            f"READY_DELTA={expected_c_ready-19}",
            f"BLOCKER_REDUCED_BY={796-expected_c_blockers}",
            "STRICT_IDENTITY_UNRESOLVED_COUNT=2",
            "PRODUCTION_OCF_CACHE_MODIFIED=true",
            "PRODUCTION_SCORE_WRITTEN=false",
            "PRODUCTION_API_CHANGED=false",
            "SCORING_POLICY_CHANGED=false",
            "STATUS=OK",
        ]) + "\n",
        encoding="utf-8",
    )

    run_scorer(
        PROD_CSV,
        POST_CSV,
        POST_JSON,
        POST_LOG,
        POST_DOC,
    )
    post_sum = read_json(POST_JSON)
    post_map = score_map(POST_CSV)

    if (
        int(post_sum.get("ready_count") or 0),
        int(post_sum.get("limited_count") or 0),
    ) != (
        expected_c_ready,
        expected_c_limited,
    ):
        raise RuntimeError("V8133A_POST_SCORE_COUNT_MISMATCH")

    post_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in post_map.values()
    )
    if post_blockers != expected_c_blockers:
        raise RuntimeError("V8133A_POST_BLOCKER_COUNT_MISMATCH")
    if set(post_map) != set(cand_map):
        raise RuntimeError("V8133A_POST_UNIVERSE_MISMATCH")
    changed = [
        code for code in sorted(post_map)
        if stable(post_map[code]) != stable(cand_map[code])
    ]
    if changed:
        raise RuntimeError(
            "V8133A_POST_NOT_EQUAL_STAGED_CANDIDATE:"
            + ",".join(changed[:20])
        )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "PRODUCTION_OCF_REFRESH_APPLIED_POST_REGRESSION_PASS",
        "policy_version": POLICY_VERSION,
        "ocf_contract_version": OCF_CONTRACT_VERSION,
        "candidate_version": CANDIDATE_VERSION,
        "candidate_result_commit": candidate_commit,
        "production_before": {
            "row_count": 112,
            "scorer_ready_count": 19,
            "scorer_limited_count": 130,
            "blocker_occurrences": 796,
        },
        "production_after": {
            "row_count": 149,
            "source_ready_count": len(ready_rows),
            "source_limited_count": len(limited_rows),
            "scorer_ready_count": expected_c_ready,
            "scorer_limited_count": expected_c_limited,
            "blocker_occurrences": expected_c_blockers,
        },
        "ready_delta": expected_c_ready - 19,
        "blocker_occurrences_reduced_by": 796 - expected_c_blockers,
        "strict_identity_unresolved_count": 2,
        "strict_identity_unresolved_tickers": sorted(
            EXPECTED_UNRESOLVED
        ),
        "post_score_equals_staged_candidate": True,
        "hard_guards": {
            "production_ocf_cache_modified": True,
            "production_ocf_metadata_modified": True,
            "production_ocf_run_log_modified": True,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "production_score_written": False,
            "source_value_imputed": False,
            "alternate_ocf_account_id_used": False,
            "unresolved_identity_force_mapped": False,
            "ready_regression_count": 0,
        },
        "next_step": "POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8134",
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=PRODUCTION_OCF_REFRESH_APPLIED_POST_REGRESSION_PASS",
            f"CANDIDATE_RESULT_COMMIT={candidate_commit}",
            "PRODUCTION_BEFORE_ROWS=112",
            "PRODUCTION_AFTER_ROWS=149",
            f"SOURCE_READY={len(ready_rows)}",
            f"SOURCE_LIMITED={len(limited_rows)}",
            "BASELINE_READY=19",
            f"POST_READY={expected_c_ready}",
            f"READY_DELTA={expected_c_ready-19}",
            "BASELINE_BLOCKERS=796",
            f"POST_BLOCKERS={expected_c_blockers}",
            f"BLOCKER_REDUCED_BY={796-expected_c_blockers}",
            "STRICT_IDENTITY_UNRESOLVED_COUNT=2",
            "POST_SCORE_EQUALS_STAGED_CANDIDATE=true",
            "PRODUCTION_SCORE_WRITTEN=false",
            "PRODUCTION_API_CHANGED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8134",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.13.3 controlled production OCF refresh",
            "",
            "- Promotes only the V8.13.2B candidate after re-running scorer regression.",
            "- Production OCF cache is replaced only after candidate guards pass.",
            "- Production score outputs, API files, scoring policy, financial cache, and raw source cache are not modified.",
            "- CR홀딩스(000480) and 한국수출포장(002200) remain unresolved rather than being force-mapped.",
            "",
            f"- Production OCF rows: 112 -> 149",
            f"- OCF READY/LIMITED: {len(ready_rows)}/{len(limited_rows)}",
            f"- Scorer READY: 19 -> {expected_c_ready}",
            f"- Blockers: 796 -> {expected_c_blockers}",
            "",
            "Next: `POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8134`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8133A_CONTROLLED_PRODUCTION_OCF_REFRESH=PASS")

if __name__ == "__main__":
    main()
