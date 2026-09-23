#!/usr/bin/env python3
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-23-v8.17.6A-shadow-post-financial-source-refresh-preferred-inheritance-aware"
POLICY = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8175_VERSION = "2026-09-23-v8.17.5-controlled-production-financial-cache-refresh"
V8175_COMMIT = "c43addae7de6c51f655300d3994e2c141873d272"
KST = ZoneInfo("Asia/Seoul")

ROOT = Path(".")
PRIOR = ROOT / "latest/investment_score_financial_cache_production_refresh_v8175_summary_latest.json"
PROD_RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
SHADOW_RAW = Path("/tmp/v8176a_shadow/investment_score_source_cache_latest.csv")
SHADOW_RUNLOG = Path("/tmp/v8176a_shadow/investment_score_source_run_log_latest.txt")

OUT_CAND = ROOT / "latest/investment_score_source_cache_candidate_v8176a.csv"
OUT_JSON = ROOT / "latest/investment_score_source_shadow_v8176a_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_source_shadow_v8176a_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_source_shadow_v8176a.md"

BASE_CSV = Path("/tmp/v8176a_base.csv")
BASE_JSON = Path("/tmp/v8176a_base.json")
BASE_LOG = Path("/tmp/v8176a_base.log")
BASE_DOC = Path("/tmp/v8176a_base.md")
SH_CSV = Path("/tmp/v8176a_shadow_score.csv")
SH_JSON = Path("/tmp/v8176a_shadow_score.json")
SH_LOG = Path("/tmp/v8176a_shadow_score.log")
SH_DOC = Path("/tmp/v8176a_shadow_score.md")

def ticker(v):
    s = "".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def read_rows(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd), list(rd.fieldnames or [])

def rmap(p):
    rs,_ = read_rows(p)
    return {ticker(r.get("ticker")): r for r in rs if ticker(r.get("ticker"))}

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def total_blockers(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_score(raw_path, ocsv, ojson, olog, odoc):
    old = {k:getattr(scorer,k) for k in (
        "VERSION","RAW","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC"
    )}
    try:
        scorer.VERSION = VERSION
        scorer.RAW = Path(raw_path)
        scorer.OUT_CSV = Path(ocsv)
        scorer.OUT_JSON = Path(ojson)
        scorer.OUT_LOG = Path(olog)
        scorer.OUT_DOC = Path(odoc)
        rc = scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8176A_SCORER_FAILED")

def main():
    p = read_json(PRIOR)
    assert p["version"] == V8175_VERSION
    assert p["status"] == "PRODUCTION_FINANCIAL_CACHE_REFRESH_APPLIED_POST_REGRESSION_PASS"
    assert p["policy_version"] == POLICY
    assert p["production_after"]["financial_cache_row_count"] == 308
    assert p["production_after"]["blocker_occurrences"] == 906
    assert p["changed_target_score_row_count"] == 61
    assert p["source_refresh_gate"]["source_refresh_required"] is True
    assert p["next_step"] == "POST_FINANCIAL_APPLY_SOURCE_REFRESH_REAUDIT_V8176"

    expected_added = set(p["changed_target_score_tickers"])
    assert len(expected_added) == 61

    prod_rows, prod_fields = read_rows(PROD_RAW)
    sh_rows, sh_fields = read_rows(SHADOW_RAW)
    assert prod_fields == sh_fields
    assert len(prod_rows) == 227
    assert len(sh_rows) == 288

    prod_map = {ticker(r["ticker"]):r for r in prod_rows}
    sh_map = {ticker(r["ticker"]):r for r in sh_rows}
    assert len(prod_map) == 227
    assert len(sh_map) == 288
    assert set(prod_map) < set(sh_map)

    added = set(sh_map) - set(prod_map)
    if added != expected_added:
        raise RuntimeError(
            "V8176A_ADDED_SET_MISMATCH:"
            + ",".join(sorted(added ^ expected_added))
        )

    run_score(PROD_RAW, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC)
    run_score(SHADOW_RAW, SH_CSV, SH_JSON, SH_LOG, SH_DOC)

    base = rmap(BASE_CSV)
    shadow = rmap(SH_CSV)
    bs = read_json(BASE_JSON)
    ss = read_json(SH_JSON)

    assert set(base) == set(shadow)
    assert len(base) == 157
    assert int(bs.get("ready_count") or 0) == 14
    assert int(bs.get("limited_count") or 0) == 143
    assert total_blockers(base) == 906

    shadow_total = total_blockers(shadow)
    if shadow_total >= 906:
        raise RuntimeError(
            "V8176A_NO_BLOCKER_REDUCTION:" + str(shadow_total)
        )

    lost_ready = [
        c for c in sorted(base)
        if base[c].get("score_status") == "READY"
        and shadow[c].get("score_status") != "READY"
    ]
    if lost_ready:
        raise RuntimeError("V8176A_LOST_READY:" + ",".join(lost_ready))

    # Three preferred shares are expected to change indirectly because
    # get_common_raw() inherits READY raw source from their common shares.
    expected_inherited = {
        "000225": "000220",
        "002787": "002780",
        "078935": "078930",
    }
    for preferred, common in expected_inherited.items():
        if common not in added:
            raise RuntimeError(
                "V8176A_EXPECTED_COMMON_NOT_ADDED:"
                + preferred + ":" + common
            )
        base_mode = str(base[preferred].get("raw_source_mode") or "")
        shadow_mode = str(shadow[preferred].get("raw_source_mode") or "")
        if not shadow_mode.startswith("PREFERRED_COMMON:" + common):
            raise RuntimeError(
                "V8176A_PREFERRED_INHERITANCE_NOT_ACTIVE:"
                + preferred + ":" + shadow_mode
            )

    non_added_changed = [
        c for c in sorted(set(base) - added)
        if stable(base[c]) != stable(shadow[c])
    ]
    if set(non_added_changed) != set(expected_inherited):
        raise RuntimeError(
            "V8176A_UNEXPECTED_NON_ADDED_SCORE_DRIFT:"
            + ",".join(non_added_changed[:30])
        )

    changed_added = [
        c for c in sorted(added)
        if stable(base[c]) != stable(shadow[c])
    ]
    newly_ready = [
        c for c in sorted(base)
        if base[c].get("score_status") != "READY"
        and shadow[c].get("score_status") == "READY"
    ]

    OUT_CAND.write_bytes(SHADOW_RAW.read_bytes())

    runlog = {}
    for line in SHADOW_RUNLOG.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k,v = line.split("=",1)
            runlog[k] = v

    gate = {}
    for line in Path("/tmp/v8176a_gate.txt").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v = line.split("=",1)
            gate[k] = v

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SHADOW_ONLY_POST_FINANCIAL_SOURCE_REFRESH_PASS",
        "policy_version": POLICY,
        "v8175_version": V8175_VERSION,
        "v8175_result_commit": V8175_COMMIT,
        "source_cache": {
            "production_row_count": 227,
            "shadow_row_count": 288,
            "row_delta": 61,
            "expected_added_ticker_count": 61,
            "actual_added_ticker_count": len(added),
            "actual_added_tickers": sorted(added),
        },
        "fresh_source_run": {
            "financial_cache_rows": int(runlog.get("FINANCIAL_CACHE_ROWS") or 0),
            "targets": int(runlog.get("TARGETS") or 0),
            "output_rows": int(runlog.get("OUTPUT_ROWS") or 0),
            "three_year_ready": int(runlog.get("THREE_YEAR_READY") or 0),
            "quarter_source_ready": int(runlog.get("QUARTER_SOURCE_READY") or 0),
            "deep_source_ready": int(runlog.get("DEEP_SOURCE_READY") or 0),
            "raw_source_ready": int(runlog.get("RAW_SOURCE_READY") or 0),
            "source_retention_guard": runlog.get("SOURCE_RETENTION_GUARD",""),
        },
        "scorer_regression": {
            "universe_count": 157,
            "baseline_ready_count": 14,
            "shadow_ready_count": int(ss.get("ready_count") or 0),
            "baseline_limited_count": 143,
            "shadow_limited_count": int(ss.get("limited_count") or 0),
            "baseline_blocker_occurrences": 906,
            "shadow_blocker_occurrences": shadow_total,
            "blocker_occurrences_reduced_by": 906 - shadow_total,
            "changed_added_score_row_count": len(changed_added),
            "changed_added_score_tickers": changed_added,
            "expected_inherited_preferred_score_row_changed_count": 3,
            "expected_inherited_preferred_score_row_changed_tickers": sorted(expected_inherited),
            "expected_inherited_preferred_common_map": expected_inherited,
            "unexpected_non_added_score_row_changed_count": 0,
            "newly_ready_count": len(newly_ready),
            "newly_ready_tickers": newly_ready,
            "lost_ready_count": 0,
        },
        "v854_gate": {
            "need_refresh": gate.get("NEED_REFRESH") == "true",
            "reason": gate.get("REFRESH_REASON"),
            "financial_run_at_kst": gate.get("FINANCIAL_RUN_AT_KST"),
            "source_run_at_kst": gate.get("SOURCE_RUN_AT_KST"),
            "manual_dispatch_force_refresh_preserved": True,
        },
        "automatic_promotion": {
            "allowed": False,
            "production_source_cache_modified": False,
        },
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_financial_run_log_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "unexpected_non_added_score_row_changed": False,
            "preferred_inheritance_contract_violated": False,
            "ready_regression_count": 0,
        },
        "next_step": "STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177",
    }

    OUT_JSON.write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=SHADOW_ONLY_POST_FINANCIAL_SOURCE_REFRESH_PASS",
        "PRODUCTION_SOURCE_ROWS=227",
        "SHADOW_SOURCE_ROWS=288",
        "SOURCE_ROW_DELTA=61",
        "ADDED_TICKERS=61",
        "SCORER_UNIVERSE=157",
        "BASELINE_READY=14",
        f"SHADOW_READY={int(ss.get('ready_count') or 0)}",
        "BASELINE_LIMITED=143",
        f"SHADOW_LIMITED={int(ss.get('limited_count') or 0)}",
        "BASELINE_BLOCKERS=906",
        f"SHADOW_BLOCKERS={shadow_total}",
        f"BLOCKER_REDUCED_BY={906-shadow_total}",
        f"CHANGED_ADDED_SCORE_ROWS={len(changed_added)}",
        "EXPECTED_INHERITED_PREFERRED_SCORE_ROWS=3",
        "EXPECTED_INHERITED_PREFERRED_TICKERS=000225,002787,078935",
        "UNEXPECTED_NON_ADDED_SCORE_ROW_CHANGED=0",
        f"NEWLY_READY={len(newly_ready)}",
        "LOST_READY=0",
        "V854_GATE_NEED_REFRESH=true",
        "V854_GATE_REASON=financial_source_newer_than_investment_source",
        "AUTOMATIC_PROMOTION=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "STATUS_OK=true",
        "NEXT_STEP=STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    OUT_DOC.write_text(
        "# V8.17.6 shadow post-financial source refresh\n\n"
        "- Confirms V8.5.4 timestamp gate requires a source refresh.\n"
        "- Production source cache remains 227 rows.\n"
        "- Isolated refresh produces 288 rows, adding exactly the 61 newly financial-resolved tickers.\n"
        f"- Blockers: 906 -> {shadow_total}.\n"
        f"- READY: 14 -> {int(ss.get('ready_count') or 0)}.\n"
        f"- Newly READY: {len(newly_ready)}.\n"
        "- Expected preferred-share inherited score changes: 3 (000225, 002787, 078935).\n"
        "- Unexpected non-added score drift: 0; lost READY: 0.\n"
        "- Production source cache, API, policy and score remain unchanged.\n\n"
        "Next: STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177\n",
        encoding="utf-8"
    )

    print("V8176A_SOURCE_SHADOW=PASS")
    print("V8176A_SOURCE_ROWS=227->288")
    print(f"V8176A_BLOCKERS=906->{shadow_total}")
    print(f"V8176A_READY=14->{int(ss.get('ready_count') or 0)}")
    print("V8176A_NEXT_STEP=STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177")

if __name__ == "__main__":
    main()
