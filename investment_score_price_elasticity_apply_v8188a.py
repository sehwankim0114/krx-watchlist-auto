import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.18.8A-controlled-current-basis-bulk-price-elasticity-apply"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
STAGE_VERSION="2026-09-24-v8.18.7A-stage-current-basis-bulk-price-elasticity-patch"
STAGE_COMMIT="2f03b743d8e9f168cd786a635a59c5804c9c2e45"
PREV_REFRESH="2026-09-23-v8.18.3-controlled-narrow-production-price-elasticity-patch"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

STAGE=ROOT/"latest/investment_score_price_elasticity_stage_v8187a.csv"
STAGE_SOURCE=ROOT/"latest/investment_score_price_elasticity_stage_source_v8187a.csv"
STAGE_SUM=ROOT/"latest/investment_score_price_elasticity_stage_v8187a_summary_latest.json"

PROD=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
META=ROOT/"latest/investment_score_price_elasticity_20d_latest.json"
RUNLOG=ROOT/"latest/investment_score_price_elasticity_20d_run_log_latest.txt"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

OUT_JSON=ROOT/"latest/investment_score_price_elasticity_production_v8188a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_price_elasticity_production_v8188a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_price_elasticity_production_v8188a.md"

PRE_CSV=Path("/tmp/v8188a_pre.csv")
PRE_JSON=Path("/tmp/v8188a_pre.json")
PRE_LOG=Path("/tmp/v8188a_pre.log")
PRE_DOC=Path("/tmp/v8188a_pre.md")

POST_CSV=Path("/tmp/v8188a_post.csv")
POST_JSON=Path("/tmp/v8188a_post.json")
POST_LOG=Path("/tmp/v8188a_post.log")
POST_DOC=Path("/tmp/v8188a_post.md")

BACKUP_DIR=Path("/tmp/v8188a_backup")

def tick(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def rj(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def rmap(p):
    return {tick(r.get("ticker")):r for r in rows(p) if tick(r.get("ticker"))}

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def blockers(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_score(elasticity,ocsv,ojson,olog,odoc):
    old={k:getattr(scorer,k) for k in ("VERSION","ELASTICITY","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.ELASTICITY=Path(elasticity)
        scorer.OUT_CSV=Path(ocsv)
        scorer.OUT_JSON=Path(ojson)
        scorer.OUT_LOG=Path(olog)
        scorer.OUT_DOC=Path(odoc)
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8188A_SCORER_FAILED:"+str(rc))

def backup():
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    shutil.copy2(PROD,BACKUP_DIR/PROD.name)
    shutil.copy2(META,BACKUP_DIR/META.name)
    shutil.copy2(RUNLOG,BACKUP_DIR/RUNLOG.name)

def rollback():
    shutil.copy2(BACKUP_DIR/PROD.name,PROD)
    shutil.copy2(BACKUP_DIR/META.name,META)
    shutil.copy2(BACKUP_DIR/RUNLOG.name,RUNLOG)

stage_sum=rj(STAGE_SUM)
mf=rj(MANIFEST)
old_meta=rj(META)

assert stage_sum["version"]==STAGE_VERSION
assert stage_sum["status"]=="STAGED_CURRENT_BASIS_BULK_ELASTICITY_PATCH_PASS"
assert stage_sum["policy_version"]==POLICY
assert stage_sum["next_step"]=="CONTROLLED_CURRENT_BASIS_BULK_PRICE_ELASTICITY_APPLY_V8188A"

assert stage_sum["basis_date"]=="2026-09-23"
assert stage_sum["production_cache_row_count"]==155
assert stage_sum["staged_cache_row_count"]==217
assert stage_sum["cache_row_delta"]==62
assert stage_sum["staged_added_ticker_count"]==62
assert stage_sum["inactive_old_audited_targets_not_staged_count"]==38
assert stage_sum["existing_elasticity_row_changed_count"]==0
assert stage_sum["scorer_universe_count"]==198
assert stage_sum["baseline_ready_count"]==15
assert stage_sum["staged_ready_count"]==15
assert stage_sum["baseline_limited_count"]==183
assert stage_sum["staged_limited_count"]==183
assert stage_sum["baseline_blocker_occurrences"]==1687
assert stage_sum["staged_blocker_occurrences"]==1625
assert stage_sum["blocker_occurrences_reduced_by"]==62
assert stage_sum["changed_score_row_count"]==62
assert stage_sum["newly_ready_count"]==0
assert stage_sum["lost_ready_count"]==0
assert stage_sum["non_target_score_row_changed_count"]==0

targets=sorted(stage_sum["staged_added_tickers"])
target_set=set(targets)
assert len(targets)==62 and len(target_set)==62
assert targets==sorted(stage_sum["changed_score_tickers"])

assert mf["release_stage"]=="PRODUCTION"
assert mf["safe_to_analyze_as_latest"] is True
assert mf["basis_date"]=="2026-09-23"
assert int((mf.get("sector_rs_source") or {}).get("unique_ticker_count") or 0)==198

assert old_meta["refresh_version"]==PREV_REFRESH
assert old_meta["production_unique_tickers"]==155
assert old_meta["ready_tickers"]==155
assert old_meta["limited_tickers"]==0
assert old_meta["latest_row_basis_date"]=="2026-09-22"
assert old_meta["narrow_patch"]["ticker_count"]==6

prod_map=rmap(PROD)
stage_map=rmap(STAGE)
source_map=rmap(STAGE_SOURCE)

assert len(prod_map)==155
assert len(stage_map)==217
assert len(source_map)==62
assert set(stage_map)-set(prod_map)==target_set
assert set(source_map)==target_set
assert all(stable(stage_map[c])==stable(prod_map[c]) for c in prod_map)

for c in targets:
    r=stage_map[c]
    assert r["basis_date"]=="2026-09-23"
    assert r["close_observation_count"]=="21"
    assert r["daily_return_observation_count"]=="20"
    assert r["source_status"]=="READY"

run_score(PROD,PRE_CSV,PRE_JSON,PRE_LOG,PRE_DOC)
pre=rmap(PRE_CSV)
pre_sum=rj(PRE_JSON)
assert len(pre)==198
assert (int(pre_sum["ready_count"]),int(pre_sum["limited_count"]),blockers(pre))==(15,183,1687)

run_score(STAGE,POST_CSV,POST_JSON,POST_LOG,POST_DOC)
staged_score=rmap(POST_CSV)
staged_sum=rj(POST_JSON)
assert len(staged_score)==198
assert (int(staged_sum["ready_count"]),int(staged_sum["limited_count"]),blockers(staged_score))==(15,183,1625)

changed=[c for c in sorted(pre) if stable(pre[c])!=stable(staged_score[c])]
assert changed==targets

backup()

try:
    shutil.copy2(STAGE,PROD)

    values={c:float(stage_map[c]["avg_daily_move_pct"]) for c in targets}
    now=datetime.now(KST).isoformat(timespec="seconds")

    new_meta=dict(old_meta)
    new_meta["refresh_version"]=VERSION
    new_meta["generated_at_kst"]=now
    new_meta["production_unique_tickers"]=217
    new_meta["ready_tickers"]=217
    new_meta["limited_tickers"]=0
    new_meta["latest_row_basis_date"]="2026-09-23"
    new_meta["source"]="official KRX STK_BYDD_TRD; validated current-basis narrow and bulk additions"
    new_meta["bulk_patch"]={
        "version":VERSION,
        "promoted_from_version":STAGE_VERSION,
        "promoted_from_commit":STAGE_COMMIT,
        "ticker_count":62,
        "tickers":targets,
        "basis_date":"2026-09-23",
        "values":values,
        "latest_added_tickers":targets,
    }
    META.write_text(
        json.dumps(new_meta,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    RUNLOG.write_text("\n".join([
        "VERSION=2026-09-12-v8.7.5-price-elasticity-20-session-source",
        f"REFRESH_VERSION={VERSION}",
        "FULL_REFRESH_BASIS_DATE=2026-09-18",
        "LATEST_ROW_BASIS_DATE=2026-09-23",
        "PRODUCTION_UNIQUE_TICKERS=217",
        "PRICE_ELASTICITY_20D_READY=217",
        "PRICE_ELASTICITY_20D_LIMITED=0",
        "NARROW_PATCH_COUNT=6",
        "NARROW_PATCH_TICKERS=004990,006040,006260,012630,078930,267250",
        "BULK_PATCH_COUNT=62",
        "BULK_PATCH_TICKERS="+",".join(targets),
        "VALIDATED_PATCH_TOTAL_COUNT=68",
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
    ])+"\n",encoding="utf-8")

    post_prod=rmap(PROD)
    assert len(post_prod)==217
    assert set(post_prod)==set(stage_map)
    assert all(stable(post_prod[c])==stable(stage_map[c]) for c in stage_map)

    post_meta=rj(META)
    assert post_meta["refresh_version"]==VERSION
    assert post_meta["production_unique_tickers"]==217
    assert post_meta["ready_tickers"]==217
    assert post_meta["limited_tickers"]==0
    assert post_meta["latest_row_basis_date"]=="2026-09-23"
    assert post_meta["narrow_patch"]==old_meta["narrow_patch"]
    assert post_meta["bulk_patch"]["ticker_count"]==62
    assert post_meta["bulk_patch"]["tickers"]==targets

    run_score(PROD,POST_CSV,POST_JSON,POST_LOG,POST_DOC)
    post=rmap(POST_CSV)
    post_sum=rj(POST_JSON)

    assert len(post)==198
    assert (int(post_sum["ready_count"]),int(post_sum["limited_count"]),blockers(post))==(15,183,1625)
    assert all(stable(post[c])==stable(staged_score[c]) for c in post)

    changed_post=[c for c in sorted(pre) if stable(pre[c])!=stable(post[c])]
    assert changed_post==targets

    newly=sorted(c for c in pre if pre[c].get("score_status")!="READY" and post[c].get("score_status")=="READY")
    lost=sorted(c for c in pre if pre[c].get("score_status")=="READY" and post[c].get("score_status")!="READY")
    assert newly==[]
    assert lost==[]

    summary={
        "version":VERSION,
        "generated_at_kst":now,
        "status":"PRODUCTION_CURRENT_BASIS_BULK_ELASTICITY_APPLIED_POST_REGRESSION_PASS",
        "policy_version":POLICY,
        "stage_version":STAGE_VERSION,
        "stage_result_commit":STAGE_COMMIT,
        "basis_date":"2026-09-23",
        "production_cache_rows_before":155,
        "production_cache_rows_after":217,
        "production_cache_row_delta":62,
        "applied_ticker_count":62,
        "applied_tickers":targets,
        "inactive_old_audited_targets_not_applied_count":38,
        "existing_elasticity_row_changed_count":0,
        "scorer_regression":{
            "universe_count":198,
            "ready_before":15,
            "ready_after":15,
            "limited_before":183,
            "limited_after":183,
            "blockers_before":1687,
            "blockers_after":1625,
            "blockers_reduced_by":62,
            "changed_score_row_count":62,
            "changed_score_tickers":targets,
            "newly_ready_count":0,
            "lost_ready_count":0,
            "non_target_score_row_changed_count":0,
            "post_score_equals_staged":True,
        },
        "metadata":{
            "previous_refresh_version":PREV_REFRESH,
            "refresh_version":VERSION,
            "production_unique_tickers":217,
            "narrow_patch_count_preserved":6,
            "bulk_patch_count":62,
            "validated_patch_total_count":68,
            "latest_row_basis_date":"2026-09-23",
        },
        "rollback_guard":{
            "enabled":True,
            "restores_production_csv":True,
            "restores_metadata_json":True,
            "restores_run_log":True,
        },
        "hard_guards":{
            "production_source_cache_modified":False,
            "production_financial_cache_modified":False,
            "production_ocf_cache_modified":False,
            "production_supply_source_modified":False,
            "production_api_modified":False,
            "production_score_written":False,
            "scoring_policy_modified":False,
            "inactive_old_target_applied":False,
            "atr_used_as_elasticity_substitute":False,
            "nonofficial_price_source_used":False,
            "non_target_score_row_changed":False,
        },
        "next_step":"POST_BULK_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8189A",
    }

    OUT_JSON.write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=PRODUCTION_CURRENT_BASIS_BULK_ELASTICITY_APPLIED_POST_REGRESSION_PASS",
        "BASIS_DATE=2026-09-23",
        "PRODUCTION_CACHE_ROWS_BEFORE=155",
        "PRODUCTION_CACHE_ROWS_AFTER=217",
        "APPLIED_TICKERS=62",
        "INACTIVE_OLD_TARGETS_NOT_APPLIED=38",
        "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
        "SCORER_UNIVERSE=198",
        "READY_BEFORE=15",
        "READY_AFTER=15",
        "LIMITED_BEFORE=183",
        "LIMITED_AFTER=183",
        "BLOCKERS_BEFORE=1687",
        "BLOCKERS_AFTER=1625",
        "BLOCKERS_REDUCED_BY=62",
        "CHANGED_SCORE_ROWS=62",
        "NEWLY_READY=0",
        "LOST_READY=0",
        "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
        "POST_SCORE_EQUALS_STAGED=true",
        "ROLLBACK_ENABLED=true",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_SCORE_WRITTEN=false",
        "STATUS_OK=true",
        "NEXT_STEP=POST_BULK_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8189A",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    OUT_DOC.write_text(
        "# V8.18.8A controlled current-basis bulk elasticity apply\n\n"
        "- Applied the staged 62 current active PRICE_ELASTICITY_20D rows.\n"
        "- Production elasticity cache: 155 -> 217 rows.\n"
        "- 38 inactive old audited tickers were not applied.\n"
        "- READY / LIMITED remains 15 / 183.\n"
        "- Blockers: 1687 -> 1625 (-62).\n"
        "- Existing 155 production elasticity rows unchanged.\n"
        "- Post-production scorer equals staged scorer.\n"
        "- Non-target score drift: 0; lost READY: 0.\n"
        "- Production API, score, source, financial cache, and policy unchanged.\n"
        "- Rollback guard restores production CSV, metadata, and run log on failure.\n\n"
        "Next: POST_BULK_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8189A\n",
        encoding="utf-8"
    )

    print("V8188A_CONTROLLED_APPLY=PASS")
    print("V8188A_CACHE_ROWS=155->217")
    print("V8188A_READY=15->15")
    print("V8188A_BLOCKERS=1687->1625")
    print("V8188A_CHANGED_SCORE_ROWS=62")
    print("V8188A_ROLLBACK_GUARD=ENABLED")

except Exception:
    rollback()
    raise
