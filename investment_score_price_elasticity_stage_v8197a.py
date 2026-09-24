import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.19.7A-stage-current-single-price-elasticity-patch"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8196A_VERSION="2026-09-24-v8.19.6A-freeze-current-actionable-price-elasticity-shadow"
V8196A_COMMIT="1db585c319ece8f2bf89b621b2878a6b967558d5"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")
TARGET="034730"
TARGET_NAME="SK"
TARGET_PCT=2.9064

PROD=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
PROD_META=ROOT/"latest/investment_score_price_elasticity_20d_latest.json"
CAND=ROOT/"latest/investment_score_price_elasticity_candidate_v8196a.csv"
SOURCE=ROOT/"latest/investment_score_price_elasticity_source_v8196a.csv"
SHADOW=ROOT/"latest/investment_score_price_elasticity_shadow_v8196a_summary_latest.json"

STAGED=ROOT/"latest/investment_score_price_elasticity_stage_v8197a.csv"
STAGED_SOURCE=ROOT/"latest/investment_score_price_elasticity_stage_source_v8197a.csv"
COMPARE=ROOT/"latest/investment_score_price_elasticity_stage_v8197a_compare.csv"
OUTJ=ROOT/"latest/investment_score_price_elasticity_stage_v8197a_summary_latest.json"
OUTL=ROOT/"latest/investment_score_price_elasticity_stage_v8197a_run_log_latest.txt"
OUTD=ROOT/"docs/investment_score_price_elasticity_stage_v8197a.md"

def tick(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def read_json(p):
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

def run_score(elasticity,tag):
    oc=Path(f"/tmp/{tag}.csv")
    oj=Path(f"/tmp/{tag}.json")
    ol=Path(f"/tmp/{tag}.log")
    od=Path(f"/tmp/{tag}.md")
    old={k:getattr(scorer,k) for k in ("VERSION","ELASTICITY","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.ELASTICITY=Path(elasticity)
        scorer.OUT_CSV=oc
        scorer.OUT_JSON=oj
        scorer.OUT_LOG=ol
        scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8197A_SCORER_FAILED:"+str(rc))
    return rmap(oc),read_json(oj)

s=read_json(SHADOW)
meta=read_json(PROD_META)

assert s["version"]==V8196A_VERSION
assert s["status"]=="SOURCE_ONLY_FROZEN_SHADOW_PASS"
assert s["policy_version"]==POLICY
assert s["v8195a_result_commit"]=="276ef141fee759234525f8fe97ada1dffbdc6089"
assert s["source_frozen_count"]==1
assert s["source_frozen_tickers"]==[TARGET]
assert s["frozen_avg_daily_move_pct"]=={TARGET:TARGET_PCT}
assert s["basis_date"]=="2026-09-23"
assert s["production_cache_row_count"]==217
assert s["shadow_candidate_row_count"]==218
assert s["cache_row_delta"]==1
assert s["existing_elasticity_row_changed_count"]==0
assert s["current_scorer_universe_count"]==198
assert (s["baseline_ready_count"],s["shadow_ready_count"])==(22,23)
assert (s["baseline_limited_count"],s["shadow_limited_count"])==(176,175)
assert (s["baseline_blocker_occurrences"],s["shadow_blocker_occurrences"])==(1618,1617)
assert s["blocker_occurrences_reduced_by"]==1
assert s["newly_ready_tickers"]==[TARGET]
assert s["non_target_score_row_changed_count"]==0
assert s["next_step"]=="STAGE_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_V8197A"

assert meta["refresh_version"]=="2026-09-24-v8.18.8A-controlled-current-basis-bulk-price-elasticity-apply"
assert meta["production_unique_tickers"]==217
assert meta["ready_tickers"]==217
assert meta["limited_tickers"]==0
assert meta["latest_row_basis_date"]=="2026-09-23"

pr=rows(PROD)
cr=rows(CAND)
sr=rows(SOURCE)
if len(pr)!=217 or len(cr)!=218 or len(sr)!=1:
    raise RuntimeError(f"V8197A_CACHE_ROW_DRIFT:{len(pr)}:{len(cr)}:{len(sr)}")
if list(pr[0])!=list(cr[0]):
    raise RuntimeError("V8197A_SCHEMA_DRIFT")

pm=rmap(PROD)
cm=rmap(CAND)
if len(pm)!=217 or len(cm)!=218:
    raise RuntimeError("V8197A_CACHE_DUPLICATE_OR_COUNT_BAD")

added=set(cm)-set(pm)
if added!={TARGET}:
    raise RuntimeError("V8197A_ADDED_SET_CHANGED:"+",".join(sorted(added)))

changed_existing=[c for c in sorted(pm) if stable(pm[c])!=stable(cm[c])]
if changed_existing:
    raise RuntimeError(
        "V8197A_EXISTING_CACHE_ROW_CHANGED:"+",".join(changed_existing[:30])
    )

r=cm[TARGET]
assert r["name"]==TARGET_NAME
assert r["source_status"]=="READY"
assert r["basis_date"]=="2026-09-23"
assert int(r["close_observation_count"])==21
assert int(r["daily_return_observation_count"])==20
assert abs(float(r["avg_daily_move_pct"])-TARGET_PCT)<1e-8

shutil.copy2(CAND,STAGED)
shutil.copy2(SOURCE,STAGED_SOURCE)

b,bs=run_score(PROD,"v8197a_base")
t,ts=run_score(STAGED,"v8197a_stage")

if set(b)!=set(t) or len(b)!=198:
    raise RuntimeError("V8197A_SCORER_UNIVERSE_DRIFT")

if (int(bs["ready_count"]),int(bs["limited_count"]),blockers(b))!=(22,176,1618):
    raise RuntimeError(
        f"V8197A_BASELINE_DRIFT:{bs['ready_count']}:{bs['limited_count']}:{blockers(b)}"
    )
if (int(ts["ready_count"]),int(ts["limited_count"]),blockers(t))!=(23,175,1617):
    raise RuntimeError(
        f"V8197A_STAGE_RESULT_BAD:{ts['ready_count']}:{ts['limited_count']}:{blockers(t)}"
    )

changed=[c for c in sorted(b) if stable(b[c])!=stable(t[c])]
if changed!=[TARGET]:
    raise RuntimeError("V8197A_CHANGED_SCORE_SET_BAD:"+",".join(changed))

assert b[TARGET]["score_status"]=="LIMITED"
assert t[TARGET]["score_status"]=="READY"

compare=[{
    "ticker":TARGET,
    "name":TARGET_NAME,
    "avg_daily_move_pct":f"{TARGET_PCT:.4f}",
    "baseline_status":b[TARGET].get("score_status",""),
    "staged_status":t[TARGET].get("score_status",""),
    "baseline_missing_components":b[TARGET].get("missing_components",""),
    "staged_missing_components":t[TARGET].get("missing_components",""),
    "baseline_score_total":b[TARGET].get("score_total",""),
    "staged_score_total":t[TARGET].get("score_total",""),
}]
with COMPARE.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(compare[0].keys()),lineterminator="\n")
    w.writeheader()
    w.writerows(compare)

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"STAGED_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_PASS",
    "policy_version":POLICY,
    "v8196a_version":V8196A_VERSION,
    "v8196a_result_commit":V8196A_COMMIT,
    "staged_cache":{
        "production_row_count":217,
        "staged_row_count":218,
        "row_delta":1,
        "added_tickers":[TARGET],
        "existing_row_changed_count":0,
        "target_values":{TARGET:TARGET_PCT},
        "basis_date":"2026-09-23",
    },
    "scorer_regression":{
        "universe_count":198,
        "baseline_ready_count":22,
        "staged_ready_count":23,
        "baseline_limited_count":176,
        "staged_limited_count":175,
        "baseline_blocker_occurrences":1618,
        "staged_blocker_occurrences":1617,
        "blocker_occurrences_reduced_by":1,
        "changed_score_row_count":1,
        "changed_score_tickers":[TARGET],
        "non_target_score_row_changed_count":0,
        "newly_ready_count":1,
        "newly_ready_tickers":[TARGET],
        "lost_ready_count":0,
    },
    "automatic_promotion":False,
    "hard_guards":{
        "production_price_elasticity_cache_modified":False,
        "production_price_elasticity_metadata_modified":False,
        "production_price_elasticity_run_log_modified":False,
        "production_ocf_cache_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "atr_substituted":False,
        "nonofficial_price_source_used":False,
        "non_target_score_row_changed":False,
    },
    "next_step":"CONTROLLED_CURRENT_SINGLE_PRICE_ELASTICITY_APPLY_V8198A",
}

OUTJ.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
OUTL.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=STAGED_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_PASS",
    "PRODUCTION_CACHE_ROWS=217",
    "STAGED_CACHE_ROWS=218",
    "CACHE_ROW_DELTA=1",
    "ADDED_TICKERS=034730",
    "EXISTING_CACHE_ROW_CHANGED_COUNT=0",
    "SCORER_UNIVERSE=198",
    "BASELINE_READY=22",
    "STAGED_READY=23",
    "BASELINE_LIMITED=176",
    "STAGED_LIMITED=175",
    "BASELINE_BLOCKERS=1618",
    "STAGED_BLOCKERS=1617",
    "BLOCKER_REDUCED_BY=1",
    "CHANGED_SCORE_ROWS=1",
    "NON_TARGET_SCORE_ROW_CHANGED=0",
    "NEWLY_READY=1",
    "LOST_READY=0",
    "AUTOMATIC_PROMOTION=false",
    "PRODUCTION_DATA_MODIFIED=false",
    "STATUS_OK=true",
    "NEXT_STEP=CONTROLLED_CURRENT_SINGLE_PRICE_ELASTICITY_APPLY_V8198A",
])+"\n",encoding="utf-8")

OUTD.parent.mkdir(parents=True,exist_ok=True)
OUTD.write_text(
    "# V8.19.7A current single price-elasticity patch stage\n\n"
    "- Staged only SK (034730) = 2.9064%.\n"
    "- Production elasticity cache remains 217 rows; staged cache is 218 rows.\n"
    "- READY / LIMITED: 22/176 -> 23/175.\n"
    "- Blockers: 1618 -> 1617 (-1).\n"
    "- Existing 217 cache rows and all non-target score rows remain unchanged.\n"
    "- Production data, API, policy and production score are unchanged.\n\n"
    "Next: CONTROLLED_CURRENT_SINGLE_PRICE_ELASTICITY_APPLY_V8198A\n",
    encoding="utf-8"
)

print("V8197A_STAGE=PASS")
print("V8197A_CACHE_ROWS=217->218")
print("V8197A_READY=22->23")
print("V8197A_BLOCKERS=1618->1617")
