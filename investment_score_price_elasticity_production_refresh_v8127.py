#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

REFRESH_VERSION = "2026-09-21-v8.12.7-controlled-production-price-elasticity-refresh"
SOURCE_CONTRACT_VERSION = "2026-09-12-v8.7.5-price-elasticity-20-session-source"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8126_VERSION = "2026-09-21-v8.12.6-stage-current-universe-price-elasticity-refresh"
V8126_RESULT_COMMIT = "f959c3a5cf2645fc97304e6fffe355dadd1162ba"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD_CSV = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
PROD_META = ROOT / "latest/investment_score_price_elasticity_20d_latest.json"
PROD_LOG = ROOT / "latest/investment_score_price_elasticity_20d_run_log_latest.txt"

CANDIDATE_CSV = ROOT / "latest/investment_score_price_elasticity_candidate_v8126.csv"
CANDIDATE_META = ROOT / "latest/investment_score_price_elasticity_candidate_v8126_summary_latest.json"
CANDIDATE_REGRESSION = ROOT / "latest/investment_score_price_elasticity_candidate_v8126_regression_summary_latest.json"

SUMMARY_OUT = ROOT / "latest/investment_score_price_elasticity_production_refresh_v8127_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_price_elasticity_production_refresh_v8127_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_price_elasticity_production_refresh_v8127.md"

BASE_CSV = Path("/tmp/v8127_baseline_score.csv")
BASE_JSON = Path("/tmp/v8127_baseline_score.json")
BASE_LOG = Path("/tmp/v8127_baseline_score.log")
BASE_DOC = Path("/tmp/v8127_baseline_score.md")
CAND_CSV = Path("/tmp/v8127_candidate_score.csv")
CAND_JSON = Path("/tmp/v8127_candidate_score.json")
CAND_LOG = Path("/tmp/v8127_candidate_score.log")
CAND_DOC = Path("/tmp/v8127_candidate_score.md")
POST_CSV = Path("/tmp/v8127_post_score.csv")
POST_JSON = Path("/tmp/v8127_post_score.json")
POST_LOG = Path("/tmp/v8127_post_score.log")
POST_DOC = Path("/tmp/v8127_post_score.md")

EXPECTED_UNIVERSE_COUNT = 149
EXPECTED_BASELINE_READY = 7
EXPECTED_POST_READY = 19
EXPECTED_BASELINE_BLOCKERS = 911
EXPECTED_POST_BLOCKERS = 796
EXPECTED_BLOCKER_REDUCTION = 115
EXPECTED_READY_DELTA = 12
EXPECTED_BASIS = "2026-09-18"

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def run_scorer(elasticity_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "ELASTICITY": scorer.ELASTICITY,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = REFRESH_VERSION
        scorer.ELASTICITY = Path(elasticity_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for k, v in old.items():
            setattr(scorer, k, v)
    if rc not in (None, 0):
        raise RuntimeError(f"V8127_SCORER_FAILED:{rc}")

def row_map(path):
    return {
        ticker(r.get("ticker")): r
        for r in read_rows(path)
        if ticker(r.get("ticker"))
    }

def blocker_count(rows):
    return sum(int(r.get("missing_component_count") or 0) for r in rows.values())

def stable(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def main():
    for p in (PROD_CSV, PROD_META, PROD_LOG, CANDIDATE_CSV, CANDIDATE_META, CANDIDATE_REGRESSION):
        if not p.is_file():
            raise RuntimeError("V8127_MISSING_INPUT:" + str(p))

    subprocess.run(
        ["git", "merge-base", "--is-ancestor", V8126_RESULT_COMMIT, "HEAD"],
        check=True,
    )

    cmeta = read_json(CANDIDATE_META)
    reg = read_json(CANDIDATE_REGRESSION)
    pmeta = read_json(PROD_META)

    if cmeta.get("version") != V8126_VERSION:
        raise RuntimeError("V8127_CANDIDATE_VERSION_MISMATCH")
    if cmeta.get("status") != "STAGED_CANDIDATE_ONLY":
        raise RuntimeError("V8127_CANDIDATE_STATUS_MISMATCH")
    if int(cmeta.get("candidate_cache_row_count") or 0) != EXPECTED_UNIVERSE_COUNT:
        raise RuntimeError("V8127_CANDIDATE_COUNT_MISMATCH")
    if cmeta.get("candidate_cache_basis_date") != EXPECTED_BASIS:
        raise RuntimeError("V8127_CANDIDATE_BASIS_MISMATCH")
    if int(cmeta.get("ready_ticker_count") or 0) != EXPECTED_UNIVERSE_COUNT:
        raise RuntimeError("V8127_CANDIDATE_READY_NOT_149")
    if int(cmeta.get("limited_ticker_count") or 0) != 0:
        raise RuntimeError("V8127_CANDIDATE_LIMITED_NOT_ZERO")
    if cmeta.get("limited_tickers") not in ([], None):
        raise RuntimeError("V8127_CANDIDATE_LIMITED_SET_NOT_EMPTY")

    if reg.get("version") != V8126_VERSION:
        raise RuntimeError("V8127_REGRESSION_VERSION_MISMATCH")
    if reg.get("status") != "STAGED_CANDIDATE_REGRESSION_PASS":
        raise RuntimeError("V8127_REGRESSION_STATUS_MISMATCH")
    if int(reg.get("current_scorer_universe_count") or 0) != EXPECTED_UNIVERSE_COUNT:
        raise RuntimeError("V8127_REGRESSION_UNIVERSE_MISMATCH")
    if int(reg.get("baseline_ready_count") or 0) != EXPECTED_BASELINE_READY:
        raise RuntimeError("V8127_REGRESSION_BASE_READY_CHANGED")
    if int(reg.get("candidate_ready_count") or 0) != EXPECTED_POST_READY:
        raise RuntimeError("V8127_REGRESSION_CAND_READY_CHANGED")
    if int(reg.get("ready_delta") or 0) != EXPECTED_READY_DELTA:
        raise RuntimeError("V8127_REGRESSION_READY_DELTA_CHANGED")
    if int(reg.get("baseline_blocker_occurrences") or 0) != EXPECTED_BASELINE_BLOCKERS:
        raise RuntimeError("V8127_REGRESSION_BASE_BLOCKERS_CHANGED")
    if int(reg.get("candidate_blocker_occurrences") or 0) != EXPECTED_POST_BLOCKERS:
        raise RuntimeError("V8127_REGRESSION_POST_BLOCKERS_CHANGED")
    if int(reg.get("blocker_occurrences_reduced_by") or 0) != EXPECTED_BLOCKER_REDUCTION:
        raise RuntimeError("V8127_REGRESSION_BLOCKER_DELTA_CHANGED")
    for key in (
        "lost_ready_count",
        "non_elasticity_component_drift_count",
        "unexpected_non_elasticity_missing_change_count",
        "elasticity_regression_introduced_count",
        "previously_ready_score_or_band_changed_count",
    ):
        if int(reg.get(key) or 0) != 0:
            raise RuntimeError("V8127_REGRESSION_GUARD_FAILED:" + key)

    if pmeta.get("version") != SOURCE_CONTRACT_VERSION:
        raise RuntimeError("V8127_PROD_SOURCE_CONTRACT_VERSION_CHANGED")
    if pmeta.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError("V8127_PROD_STATUS_CHANGED")
    if pmeta.get("basis_date") != "2026-09-11":
        raise RuntimeError("V8127_PROD_BASIS_NOT_PRE_REFRESH")
    if int(pmeta.get("production_unique_tickers") or 0) != 112:
        raise RuntimeError("V8127_PROD_COUNT_NOT_PRE_REFRESH")

    prod_rows = row_map(PROD_CSV)
    cand_rows = row_map(CANDIDATE_CSV)
    if len(prod_rows) != 112:
        raise RuntimeError("V8127_PROD_CSV_COUNT_NOT_112")
    if len(cand_rows) != EXPECTED_UNIVERSE_COUNT:
        raise RuntimeError("V8127_CANDIDATE_CSV_COUNT_NOT_149")
    if {r.get("basis_date") for r in cand_rows.values()} != {EXPECTED_BASIS}:
        raise RuntimeError("V8127_CANDIDATE_ROW_BASIS_MISMATCH")
    if {r.get("source_status") for r in cand_rows.values()} != {"READY"}:
        raise RuntimeError("V8127_CANDIDATE_ROW_STATUS_NOT_ALL_READY")

    live_universe = scorer.production_rows()
    if len(live_universe) != EXPECTED_UNIVERSE_COUNT:
        raise RuntimeError(f"V8127_LIVE_UNIVERSE_NOT_149:{len(live_universe)}")
    if set(live_universe) != set(cand_rows):
        missing = sorted(set(live_universe) - set(cand_rows))
        extra = sorted(set(cand_rows) - set(live_universe))
        raise RuntimeError(
            "V8127_CANDIDATE_UNIVERSE_MISMATCH:"
            + "missing=" + ",".join(missing[:20])
            + ";extra=" + ",".join(extra[:20])
        )

    run_scorer(PROD_CSV, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC)
    run_scorer(CANDIDATE_CSV, CAND_CSV, CAND_JSON, CAND_LOG, CAND_DOC)

    baseline = row_map(BASE_CSV)
    candidate_score = row_map(CAND_CSV)
    if set(baseline) != set(candidate_score) or set(baseline) != set(cand_rows):
        raise RuntimeError("V8127_SCORER_UNIVERSE_MISMATCH")

    base_summary = read_json(BASE_JSON)
    cand_summary = read_json(CAND_JSON)
    base_ready = int(base_summary.get("ready_count") or 0)
    cand_ready = int(cand_summary.get("ready_count") or 0)
    base_blockers = blocker_count(baseline)
    cand_blockers = blocker_count(candidate_score)

    if (base_ready, cand_ready) != (EXPECTED_BASELINE_READY, EXPECTED_POST_READY):
        raise RuntimeError(f"V8127_READY_COUNTS_CHANGED:{base_ready}:{cand_ready}")
    if (base_blockers, cand_blockers) != (EXPECTED_BASELINE_BLOCKERS, EXPECTED_POST_BLOCKERS):
        raise RuntimeError(f"V8127_BLOCKER_COUNTS_CHANGED:{base_blockers}:{cand_blockers}")
    if cand_ready - base_ready != EXPECTED_READY_DELTA:
        raise RuntimeError("V8127_READY_DELTA_NOT_12")
    if base_blockers - cand_blockers != EXPECTED_BLOCKER_REDUCTION:
        raise RuntimeError("V8127_BLOCKER_REDUCTION_NOT_115")

    lost_ready = [
        code for code in sorted(baseline)
        if baseline[code].get("score_status") == "READY"
        and candidate_score[code].get("score_status") != "READY"
    ]
    if lost_ready:
        raise RuntimeError("V8127_READY_REGRESSION:" + ",".join(lost_ready))

    changed_previously_ready = [
        code for code in sorted(baseline)
        if baseline[code].get("score_status") == "READY"
        and (
            baseline[code].get("score_total") != candidate_score[code].get("score_total")
            or baseline[code].get("score_band") != candidate_score[code].get("score_band")
        )
    ]
    if changed_previously_ready:
        raise RuntimeError(
            "V8127_PREVIOUS_READY_SCORE_CHANGED:" + ",".join(changed_previously_ready)
        )

    shutil.copyfile(CANDIDATE_CSV, PROD_CSV)

    now = datetime.now(KST).isoformat(timespec="seconds")
    new_meta = {
        "version": SOURCE_CONTRACT_VERSION,
        "refresh_version": REFRESH_VERSION,
        "generated_at_kst": now,
        "status": "READY_SOURCE_ONLY",
        "basis_date": EXPECTED_BASIS,
        "production_unique_tickers": EXPECTED_UNIVERSE_COUNT,
        "ready_tickers": EXPECTED_UNIVERSE_COUNT,
        "limited_tickers": 0,
        "formula": "mean(abs(close_t/close_t_minus_1-1)*100) for latest 20 trading-session returns",
        "close_observations_required": 21,
        "daily_return_observations_required": 20,
        "source": "official KRX STK_BYDD_TRD current-universe full refresh promoted from v8.12.6",
        "promoted_from_version": V8126_VERSION,
        "promoted_from_commit": V8126_RESULT_COMMIT,
        "hard_guards": {
            "investment_score_100_calculated": False,
            "score_thresholds_defined": False,
            "avg_daily_range_20_pct_substituted": False,
            "production_api_changed": False,
        },
    }
    PROD_META.write_text(
        json.dumps(new_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    PROD_LOG.write_text(
        "\n".join([
            f"VERSION={SOURCE_CONTRACT_VERSION}",
            f"REFRESH_VERSION={REFRESH_VERSION}",
            f"BASIS_DATE={EXPECTED_BASIS}",
            f"PRODUCTION_UNIQUE_TICKERS={EXPECTED_UNIVERSE_COUNT}",
            f"PRICE_ELASTICITY_20D_READY={EXPECTED_UNIVERSE_COUNT}",
            "PRICE_ELASTICITY_20D_LIMITED=0",
            "CLOSE_OBSERVATIONS_REQUIRED=21",
            "DAILY_RETURN_OBSERVATIONS_REQUIRED=20",
            "AVG_DAILY_RANGE_20_PCT_SUBSTITUTED=false",
            "INVESTMENT_SCORE_100_CALCULATED=false",
            "SCORE_THRESHOLDS_DEFINED=false",
            "PRODUCTION_DATA_CHANGED=true",
            "PRODUCTION_API_CHANGED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "STATUS=OK",
        ]) + "\n",
        encoding="utf-8",
    )

    if PROD_CSV.read_bytes() != CANDIDATE_CSV.read_bytes():
        raise RuntimeError("V8127_PRODUCTION_BYTES_NOT_EQUAL_CANDIDATE")

    run_scorer(PROD_CSV, POST_CSV, POST_JSON, POST_LOG, POST_DOC)
    post = row_map(POST_CSV)
    post_summary = read_json(POST_JSON)

    if set(post) != set(candidate_score):
        raise RuntimeError("V8127_POST_SCORER_UNIVERSE_MISMATCH")
    mismatched = [
        code for code in sorted(post)
        if stable(post[code]) != stable(candidate_score[code])
    ]
    if mismatched:
        raise RuntimeError(
            "V8127_POST_SCORE_NOT_EQUAL_STAGED_CANDIDATE:"
            + ",".join(mismatched[:20])
        )

    post_ready = int(post_summary.get("ready_count") or 0)
    post_blockers = blocker_count(post)
    if post_ready != EXPECTED_POST_READY:
        raise RuntimeError(f"V8127_POST_READY_NOT_19:{post_ready}")
    if post_blockers != EXPECTED_POST_BLOCKERS:
        raise RuntimeError(f"V8127_POST_BLOCKERS_NOT_796:{post_blockers}")

    newly_ready = sorted(
        code for code in baseline
        if baseline[code].get("score_status") != "READY"
        and post[code].get("score_status") == "READY"
    )
    if len(newly_ready) != EXPECTED_READY_DELTA:
        raise RuntimeError(
            "V8127_NEWLY_READY_COUNT_NOT_12:" + str(len(newly_ready))
        )

    summary = {
        "version": REFRESH_VERSION,
        "generated_at_kst": now,
        "status": "PRODUCTION_PRICE_ELASTICITY_REFRESH_APPLIED_POST_REGRESSION_PASS",
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "v8126_version": V8126_VERSION,
        "v8126_result_commit": V8126_RESULT_COMMIT,
        "production_before": {
            "row_count": 112,
            "basis_date": "2026-09-11",
            "scorer_ready_count": base_ready,
            "blocker_occurrences": base_blockers,
        },
        "production_after": {
            "row_count": EXPECTED_UNIVERSE_COUNT,
            "basis_date": EXPECTED_BASIS,
            "source_ready_count": EXPECTED_UNIVERSE_COUNT,
            "source_limited_count": 0,
            "scorer_ready_count": post_ready,
            "blocker_occurrences": post_blockers,
        },
        "ready_delta": post_ready - base_ready,
        "newly_ready_count": len(newly_ready),
        "newly_ready_tickers": newly_ready,
        "blocker_occurrences_reduced_by": base_blockers - post_blockers,
        "lost_ready_count": 0,
        "previously_ready_score_or_band_changed_count": 0,
        "post_score_equals_staged_candidate": True,
        "hard_guards": {
            "production_price_elasticity_cache_modified": True,
            "production_price_elasticity_metadata_modified": True,
            "production_price_elasticity_run_log_modified": True,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "production_score_written": False,
            "atr_substituted": False,
            "nonofficial_price_source_used": False,
            "ready_regression_count": 0,
        },
        "next_step": "POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8128",
    }
    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={REFRESH_VERSION}",
            "STATUS=PRODUCTION_PRICE_ELASTICITY_REFRESH_APPLIED_POST_REGRESSION_PASS",
            "PRODUCTION_ROWS_BEFORE=112",
            f"PRODUCTION_ROWS_AFTER={EXPECTED_UNIVERSE_COUNT}",
            "PRODUCTION_BASIS_BEFORE=2026-09-11",
            f"PRODUCTION_BASIS_AFTER={EXPECTED_BASIS}",
            f"BASELINE_READY={base_ready}",
            f"POST_APPLY_READY={post_ready}",
            f"READY_DELTA={post_ready-base_ready}",
            f"BASELINE_BLOCKERS={base_blockers}",
            f"POST_APPLY_BLOCKERS={post_blockers}",
            f"BLOCKER_REDUCED_BY={base_blockers-post_blockers}",
            "LOST_READY=0",
            "PREVIOUSLY_READY_SCORE_OR_BAND_CHANGED=0",
            "POST_SCORE_EQUALS_STAGED_CANDIDATE=true",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8128",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.12.7 controlled production price-elasticity refresh",
            "",
            "- Promoted the V8.12.6 validated candidate into the production price-elasticity cache.",
            "- Production source rows: 112 -> 149.",
            "- Basis date: 2026-09-11 -> 2026-09-18.",
            f"- Scorer READY: {base_ready} -> {post_ready}.",
            f"- Blocker occurrences: {base_blockers} -> {post_blockers}.",
            "- READY regression: 0.",
            "- Previously READY score/band drift: 0.",
            "- Post-apply scorer output exactly matches the staged candidate scorer output.",
            "- API, scoring policy, source cache, financial cache, OCF cache, and production score artifacts were not modified.",
            "",
            "Next: POST_APPLY_CURRENT_BLOCKER_REAUDIT_V8128",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8127_CONTROLLED_PRODUCTION_ELASTICITY_REFRESH=PASS")

if __name__ == "__main__":
    main()
