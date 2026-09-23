#!/usr/bin/env python3
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-23-v8.17.0-controlled-narrow-production-price-elasticity-patch"
SOURCE_CONTRACT = "2026-09-12-v8.7.5-price-elasticity-20-session-source"
POLICY = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8169_VERSION = "2026-09-23-v8.16.9-stage-narrow-production-price-elasticity-patch"
V8169_COMMIT = "8b32b0bb480f4ea93e55d27b5541de45d4db04eb"
TARGET = "004990"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
META = ROOT / "latest/investment_score_price_elasticity_20d_latest.json"
RUNLOG = ROOT / "latest/investment_score_price_elasticity_20d_run_log_latest.txt"
CAND = ROOT / "latest/investment_score_price_elasticity_candidate_v8169.csv"
STAGE = ROOT / "latest/investment_score_price_elasticity_stage_v8169_summary_latest.json"

OUTJ = ROOT / "latest/investment_score_price_elasticity_production_v8170_summary_latest.json"
OUTL = ROOT / "latest/investment_score_price_elasticity_production_v8170_run_log_latest.txt"
OUTD = ROOT / "docs/investment_score_price_elasticity_production_v8170.md"

B_PROD = Path("/tmp/v8170_prod.backup.csv")
B_META = Path("/tmp/v8170_meta.backup.json")
B_LOG = Path("/tmp/v8170_log.backup.txt")

BASE_CSV = Path("/tmp/v8170_base.csv")
BASE_JSON = Path("/tmp/v8170_base.json")
BASE_LOG = Path("/tmp/v8170_base.log")
BASE_DOC = Path("/tmp/v8170_base.md")
CAND_CSV = Path("/tmp/v8170_cand.csv")
CAND_JSON = Path("/tmp/v8170_cand.json")
CAND_LOG = Path("/tmp/v8170_cand.log")
CAND_DOC = Path("/tmp/v8170_cand.md")
POST_CSV = Path("/tmp/v8170_post.csv")
POST_JSON = Path("/tmp/v8170_post.json")
POST_LOG = Path("/tmp/v8170_post.log")
POST_DOC = Path("/tmp/v8170_post.md")

def tick(v):
    s = "".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def rows(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def rmap(p):
    return {tick(r.get("ticker")): r for r in rows(p) if tick(r.get("ticker"))}

def stable(r):
    return json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def blocker_count(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_score(elasticity, ocsv, ojson, olog, odoc):
    old = {k:getattr(scorer,k) for k in ("VERSION","ELASTICITY","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION = VERSION
        scorer.ELASTICITY = Path(elasticity)
        scorer.OUT_CSV = Path(ocsv)
        scorer.OUT_JSON = Path(ojson)
        scorer.OUT_LOG = Path(olog)
        scorer.OUT_DOC = Path(odoc)
        rc = scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8170_SCORER_FAILED")

def main():
    stage = read_json(STAGE)
    meta = read_json(META)

    assert stage["version"] == V8169_VERSION
    assert stage["status"] == "STAGED_NARROW_PRICE_ELASTICITY_PATCH_PASS"
    assert stage["policy_version"] == POLICY
    assert stage["v8168_result_commit"] == "a2db42cd94b2af57b438101d086f9025d3939880"
    assert stage["next_step"] == "CONTROLLED_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8170"
    assert stage["staged_cache"]["production_row_count"] == 151
    assert stage["staged_cache"]["staged_row_count"] == 152
    assert stage["staged_cache"]["added_tickers"] == [TARGET]
    assert stage["staged_cache"]["existing_row_changed_count"] == 0
    assert abs(stage["staged_cache"]["target_value"] - 1.3594) < 1e-8
    assert stage["scorer_regression"]["baseline_ready_count"] == 21
    assert stage["scorer_regression"]["staged_ready_count"] == 22
    assert stage["scorer_regression"]["baseline_limited_count"] == 99
    assert stage["scorer_regression"]["staged_limited_count"] == 98
    assert stage["scorer_regression"]["baseline_blocker_occurrences"] == 322
    assert stage["scorer_regression"]["staged_blocker_occurrences"] == 321
    assert stage["scorer_regression"]["changed_score_tickers"] == [TARGET]
    assert stage["scorer_regression"]["lost_ready_count"] == 0
    assert all(v is False for v in stage["hard_guards"].values())

    assert meta["version"] == SOURCE_CONTRACT
    assert meta["status"] == "READY_SOURCE_ONLY"
    assert meta["production_unique_tickers"] == 151
    assert meta["ready_tickers"] == 151
    assert meta["limited_tickers"] == 0
    assert meta["basis_date"] == "2026-09-18"
    assert meta["latest_row_basis_date"] == "2026-09-21"

    prod_rows = rows(PROD)
    cand_rows = rows(CAND)
    assert len(prod_rows) == 151
    assert len(cand_rows) == 152
    assert list(prod_rows[0]) == list(cand_rows[0])

    prod_map = rmap(PROD)
    cand_map = rmap(CAND)
    assert len(prod_map) == 151 and len(cand_map) == 152
    assert set(cand_map) - set(prod_map) == {TARGET}
    assert all(stable(prod_map[c]) == stable(cand_map[c]) for c in prod_map)

    tr = cand_map[TARGET]
    assert tr["name"] == "롯데지주"
    assert tr["source_status"] == "READY"
    assert tr["basis_date"] == "2026-09-21"
    assert int(tr["close_observation_count"]) == 21
    assert int(tr["daily_return_observation_count"]) == 20
    assert abs(float(tr["avg_daily_move_pct"]) - 1.3594) < 1e-8

    run_score(PROD, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC)
    run_score(CAND, CAND_CSV, CAND_JSON, CAND_LOG, CAND_DOC)

    base = rmap(BASE_CSV)
    cand_score = rmap(CAND_CSV)
    bs = read_json(BASE_JSON)
    cs = read_json(CAND_JSON)

    assert set(base) == set(cand_score) and len(base) == 120
    assert (int(bs["ready_count"]), int(bs["limited_count"]), blocker_count(base)) == (21,99,322)
    assert (int(cs["ready_count"]), int(cs["limited_count"]), blocker_count(cand_score)) == (22,98,321)
    changed = [c for c in sorted(base) if stable(base[c]) != stable(cand_score[c])]
    assert changed == [TARGET]

    shutil.copyfile(PROD, B_PROD)
    shutil.copyfile(META, B_META)
    shutil.copyfile(RUNLOG, B_LOG)

    try:
        shutil.copyfile(CAND, PROD)
        if PROD.read_bytes() != CAND.read_bytes():
            raise RuntimeError("V8170_APPLIED_BYTES_NOT_CANDIDATE")

        now = datetime.now(KST).isoformat(timespec="seconds")

        cumulative = {
            "004990": 1.3594,
            "006260": 2.70,
            "267250": 2.91,
        }
        new_meta = dict(meta)
        new_meta.update({
            "version": SOURCE_CONTRACT,
            "refresh_version": VERSION,
            "generated_at_kst": now,
            "status": "READY_SOURCE_ONLY",
            "basis_date": "2026-09-18",
            "basis_date_semantics": (
                "full_refresh_basis; per-row basis_date is authoritative "
                "for narrow-patched rows"
            ),
            "latest_row_basis_date": "2026-09-21",
            "production_unique_tickers": 152,
            "ready_tickers": 152,
            "limited_tickers": 0,
            "source": (
                "official KRX STK_BYDD_TRD; v8.12.7 full refresh "
                "plus validated narrow additions"
            ),
            "narrow_patch": {
                "version": VERSION,
                "promoted_from_version": V8169_VERSION,
                "promoted_from_commit": V8169_COMMIT,
                "ticker_count": 3,
                "tickers": sorted(cumulative),
                "basis_date": "2026-09-21",
                "values": cumulative,
                "latest_added_tickers": [TARGET],
            },
        })
        new_meta["hard_guards"] = {
            "investment_score_100_calculated": False,
            "score_thresholds_defined": False,
            "avg_daily_range_20_pct_substituted": False,
            "production_api_changed": False,
            "non_target_elasticity_rows_modified": False,
        }
        META.write_text(
            json.dumps(new_meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        RUNLOG.write_text("\n".join([
            f"VERSION={SOURCE_CONTRACT}",
            f"REFRESH_VERSION={VERSION}",
            "FULL_REFRESH_BASIS_DATE=2026-09-18",
            "LATEST_ROW_BASIS_DATE=2026-09-21",
            "PRODUCTION_UNIQUE_TICKERS=152",
            "PRICE_ELASTICITY_20D_READY=152",
            "PRICE_ELASTICITY_20D_LIMITED=0",
            "NARROW_PATCH_COUNT=3",
            "NARROW_PATCH_TICKERS=004990,006260,267250",
            "LATEST_NARROW_PATCH_TICKERS=004990",
            "CLOSE_OBSERVATIONS_REQUIRED=21",
            "DAILY_RETURN_OBSERVATIONS_REQUIRED=20",
            "AVG_DAILY_RANGE_20_PCT_SUBSTITUTED=false",
            "INVESTMENT_SCORE_100_CALCULATED=false",
            "SCORE_THRESHOLDS_DEFINED=false",
            "NON_TARGET_ELASTICITY_ROWS_MODIFIED=false",
            "PRODUCTION_DATA_CHANGED=true",
            "PRODUCTION_API_CHANGED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "STATUS=OK",
        ]) + "\n", encoding="utf-8")

        post_map = rmap(PROD)
        assert len(post_map) == 152
        assert all(stable(prod_map[c]) == stable(post_map[c]) for c in prod_map)
        assert stable(post_map[TARGET]) == stable(cand_map[TARGET])

        run_score(PROD, POST_CSV, POST_JSON, POST_LOG, POST_DOC)
        post = rmap(POST_CSV)
        ps = read_json(POST_JSON)

        assert set(post) == set(cand_score)
        mismatch = [c for c in sorted(post) if stable(post[c]) != stable(cand_score[c])]
        if mismatch:
            raise RuntimeError("V8170_POST_SCORE_NOT_STAGE:" + ",".join(mismatch[:20]))

        assert (int(ps["ready_count"]), int(ps["limited_count"]), blocker_count(post)) == (22,98,321)
        newly_ready = [
            c for c in sorted(base)
            if base[c].get("score_status") != "READY"
            and post[c].get("score_status") == "READY"
        ]
        assert newly_ready == [TARGET]

        summary = {
            "version": VERSION,
            "generated_at_kst": now,
            "status": "PRODUCTION_NARROW_ELASTICITY_PATCH_APPLIED_POST_REGRESSION_PASS",
            "policy_version": POLICY,
            "source_contract_version": SOURCE_CONTRACT,
            "v8169_version": V8169_VERSION,
            "v8169_result_commit": V8169_COMMIT,
            "production_cache": {
                "row_count_before": 151,
                "row_count_after": 152,
                "row_delta": 1,
                "latest_added_tickers": [TARGET],
                "cumulative_narrow_patch_tickers": sorted(cumulative),
                "existing_row_changed_count": 0,
                "post_apply_exact_stage_bytes": True,
            },
            "scorer_regression": {
                "universe_count": 120,
                "ready_before": 21,
                "ready_after": 22,
                "limited_before": 99,
                "limited_after": 98,
                "blockers_before": 322,
                "blockers_after": 321,
                "blockers_reduced_by": 1,
                "changed_score_row_count": 1,
                "changed_score_tickers": [TARGET],
                "non_target_score_row_changed_count": 0,
                "newly_ready_count": 1,
                "newly_ready_tickers": [TARGET],
                "lost_ready_count": 0,
                "post_score_equals_staged_score": True,
            },
            "rollback_guard": {
                "enabled": True,
                "restores_cache": True,
                "restores_metadata": True,
                "restores_run_log": True,
            },
            "hard_guards": {
                "production_price_elasticity_cache_modified": True,
                "production_price_elasticity_metadata_modified": True,
                "production_price_elasticity_run_log_modified": True,
                "production_source_cache_modified": False,
                "production_financial_cache_modified": False,
                "production_ocf_cache_modified": False,
                "production_supply_source_modified": False,
                "production_api_modified": False,
                "production_score_written": False,
                "scoring_policy_modified": False,
                "atr_substituted": False,
                "nonofficial_price_source_used": False,
                "non_target_elasticity_rows_modified": False,
                "ready_regression_count": 0,
            },
            "next_step": "POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8171",
        }
        OUTJ.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        OUTL.write_text("\n".join([
            f"VERSION={VERSION}",
            "STATUS=PRODUCTION_NARROW_ELASTICITY_PATCH_APPLIED_POST_REGRESSION_PASS",
            "PRODUCTION_ROWS_BEFORE=151",
            "PRODUCTION_ROWS_AFTER=152",
            "LATEST_NARROW_PATCH_COUNT=1",
            "LATEST_NARROW_PATCH_TICKERS=004990",
            "CUMULATIVE_NARROW_PATCH_COUNT=3",
            "SCORER_UNIVERSE=120",
            "READY_BEFORE=21",
            "READY_AFTER=22",
            "LIMITED_BEFORE=99",
            "LIMITED_AFTER=98",
            "BLOCKERS_BEFORE=322",
            "BLOCKERS_AFTER=321",
            "BLOCKER_REDUCED_BY=1",
            "CHANGED_SCORE_ROWS=1",
            "NON_TARGET_SCORE_ROW_CHANGED=0",
            "NEWLY_READY=1",
            "LOST_READY=0",
            "POST_SCORE_EQUALS_STAGED=true",
            "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
            "ROLLBACK_GUARD=true",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8171",
        ]) + "\n", encoding="utf-8")
        OUTD.parent.mkdir(parents=True, exist_ok=True)
        OUTD.write_text(
            "# V8.17.0 controlled narrow production price-elasticity patch\n\n"
            "- Added only 롯데지주 (004990) to production elasticity cache.\n"
            "- Cache rows: 151 -> 152.\n"
            "- Existing 151 rows are preserved field-for-field.\n"
            "- READY / LIMITED: 21/99 -> 22/98.\n"
            "- Blockers: 322 -> 321.\n"
            "- Post-apply score equals the tested V8.16.9 staged state.\n"
            "- API, scoring policy, and production score are not modified.\n"
            "- Rollback guard covers cache, metadata, and run log.\n\n"
            "Next: POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8171\n",
            encoding="utf-8",
        )

    except Exception:
        shutil.copyfile(B_PROD, PROD)
        shutil.copyfile(B_META, META)
        shutil.copyfile(B_LOG, RUNLOG)
        raise

    print("V8170_CONTROLLED_APPLY=PASS")

if __name__ == "__main__":
    main()
