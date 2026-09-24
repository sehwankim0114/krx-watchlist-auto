import csv, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.18.7A-stage-current-basis-bulk-price-elasticity-patch"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8186A_VERSION="2026-09-24-v8.18.6A-current-basis-rebase-multi-elasticity-shadow"
V8186A_COMMIT="9b961bf48bb14c34189d8d1f43ca188cfb48a547"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")
SHADOW_JSON=ROOT/"latest/investment_score_price_elasticity_multi_shadow_v8186a_summary_latest.json"
SHADOW_CMP=ROOT/"latest/investment_score_price_elasticity_multi_shadow_v8186a.csv"
SOURCE100=ROOT/"latest/investment_score_price_elasticity_multi_source_v8186a.csv"
PROD=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

STAGE=ROOT/"latest/investment_score_price_elasticity_stage_v8187a.csv"
STAGE_SOURCE=ROOT/"latest/investment_score_price_elasticity_stage_source_v8187a.csv"
STAGE_COMPARE=ROOT/"latest/investment_score_price_elasticity_stage_v8187a_compare.csv"
OUT_JSON=ROOT/"latest/investment_score_price_elasticity_stage_v8187a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_price_elasticity_stage_v8187a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_price_elasticity_stage_v8187a.md"

def tick(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def rj(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def wrows(p,rs,fields):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        w.writerows(rs)

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
        raise RuntimeError("V8187A_SCORER_FAILED:"+str(rc))
    return rmap(oc), rj(oj)

s=rj(SHADOW_JSON)
mf=rj(MANIFEST)
reg=s["scorer_regression"]

assert s["version"]==V8186A_VERSION
assert s["status"]=="CURRENT_BASIS_REBASE_SHADOW_PASS"
assert s["policy_version"]==POLICY
assert s["next_step"]=="STAGE_CURRENT_BASIS_BULK_PRICE_ELASTICITY_PATCH_V8187A"
assert s["current_production"]["basis_date"]=="2026-09-23"
assert s["current_production"]["scorer_universe_count"]==198
assert s["current_production"]["production_elasticity_rows"]==155

assert reg["baseline_ready_count"]==15
assert reg["baseline_limited_count"]==183
assert reg["baseline_blocker_occurrences"]==1687
assert reg["shadow_ready_count"]==15
assert reg["shadow_limited_count"]==183
assert reg["shadow_blocker_occurrences"]==1625
assert reg["blocker_occurrences_reduced_by"]==62
assert reg["currently_elasticity_blocked_old_target_count"]==62
assert reg["currently_single_elasticity_old_target_count"]==0
assert reg["currently_multi_elasticity_old_target_count"]==62
assert reg["changed_score_row_count"]==62
assert reg["newly_ready_count"]==0
assert reg["lost_ready_count"]==0
assert reg["non_target_score_row_changed_count"]==0

targets=sorted(reg["changed_score_tickers"])
target_set=set(targets)
assert len(targets)==62 and len(target_set)==62

assert mf["release_stage"]=="PRODUCTION"
assert mf["safe_to_analyze_as_latest"] is True
assert mf["basis_date"]=="2026-09-23"
assert int((mf.get("sector_rs_source") or {}).get("unique_ticker_count") or 0)==198

prod_rows=rows(PROD)
assert len(prod_rows)==155
fields=list(prod_rows[0].keys())
prod_map={tick(r["ticker"]):r for r in prod_rows}
assert len(prod_map)==155
assert not (set(prod_map)&target_set)

source100=rmap(SOURCE100)
compare=rmap(SHADOW_CMP)
assert target_set <= set(source100)
assert set(compare)==target_set

stage_source=[source100[c] for c in targets]
for r in stage_source:
    assert r["basis_date"]=="2026-09-23"
    assert r["basis_source"]=="CURRENT_PRODUCTION_MANIFEST_BASIS_DATE"
    assert r["close_observation_count"]=="21"
    assert r["daily_return_observation_count"]=="20"
    assert r["classification"]=="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE_CURRENT_BASIS"
    assert r["source"]=="KRX_OFFICIAL_STK_BYDD_TRD"

wrows(STAGE_SOURCE,stage_source,list(stage_source[0].keys()))

stage_map=dict(prod_map)
for c in targets:
    src=source100[c]
    nr={f:"" for f in fields}
    nr.update({
        "ticker":c,
        "name":src.get("name",""),
        "basis_date":src["basis_date"],
        "window_start_date":src["window_start_date"],
        "window_end_date":src["window_end_date"],
        "close_observation_count":"21",
        "daily_return_observation_count":"20",
        "avg_daily_move_abs":"",
        "avg_daily_move_pct":src["avg_daily_move_pct"],
        "source_status":"READY",
    })
    stage_map[c]=nr

staged_rows=[stage_map[c] for c in sorted(stage_map)]
assert len(staged_rows)==217
wrows(STAGE,staged_rows,fields)

staged_cache=rmap(STAGE)
assert set(staged_cache)-set(prod_map)==target_set
assert all(stable(staged_cache[c])==stable(prod_map[c]) for c in prod_map)

base,bs=run_score(PROD,"v8187a_base")
staged,ss=run_score(STAGE,"v8187a_stage")
assert set(base)==set(staged)
assert len(base)==198

base_tuple=(int(bs["ready_count"]),int(bs["limited_count"]),blockers(base))
stage_tuple=(int(ss["ready_count"]),int(ss["limited_count"]),blockers(staged))
assert base_tuple==(15,183,1687), base_tuple
assert stage_tuple==(15,183,1625), stage_tuple

changed=[c for c in sorted(base) if stable(base[c])!=stable(staged[c])]
assert changed==targets

newly=sorted(c for c in base if base[c].get("score_status")!="READY" and staged[c].get("score_status")=="READY")
lost=sorted(c for c in base if base[c].get("score_status")=="READY" and staged[c].get("score_status")!="READY")
assert newly==[]
assert lost==[]

cmp=[]
for c in targets:
    cmp.append({
        "ticker":c,
        "name":staged[c].get("name",""),
        "avg_daily_move_pct":source100[c]["avg_daily_move_pct"],
        "baseline_status":base[c].get("score_status",""),
        "staged_status":staged[c].get("score_status",""),
        "baseline_missing_component_count":base[c].get("missing_component_count",""),
        "staged_missing_component_count":staged[c].get("missing_component_count",""),
        "baseline_missing_components":base[c].get("missing_components",""),
        "staged_missing_components":staged[c].get("missing_components",""),
    })
wrows(STAGE_COMPARE,cmp,list(cmp[0].keys()))

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"STAGED_CURRENT_BASIS_BULK_ELASTICITY_PATCH_PASS",
    "policy_version":POLICY,
    "v8186a_version":V8186A_VERSION,
    "v8186a_result_commit":V8186A_COMMIT,
    "basis_date":"2026-09-23",
    "production_cache_row_count":155,
    "staged_cache_row_count":217,
    "cache_row_delta":62,
    "staged_added_ticker_count":62,
    "staged_added_tickers":targets,
    "inactive_old_audited_targets_not_staged_count":38,
    "existing_elasticity_row_changed_count":0,
    "scorer_universe_count":198,
    "baseline_ready_count":15,
    "staged_ready_count":15,
    "baseline_limited_count":183,
    "staged_limited_count":183,
    "baseline_blocker_occurrences":1687,
    "staged_blocker_occurrences":1625,
    "blocker_occurrences_reduced_by":62,
    "changed_score_row_count":62,
    "changed_score_tickers":targets,
    "newly_ready_count":0,
    "lost_ready_count":0,
    "non_target_score_row_changed_count":0,
    "hard_guards":{
        "production_price_elasticity_cache_modified":False,
        "production_price_elasticity_metadata_modified":False,
        "production_price_elasticity_run_log_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "inactive_old_target_added_to_stage":False,
        "atr_used_as_elasticity_substitute":False,
        "nonofficial_price_source_used":False,
        "non_target_score_row_changed":False,
    },
    "automatic_promotion":False,
    "next_step":"CONTROLLED_CURRENT_BASIS_BULK_PRICE_ELASTICITY_APPLY_V8188A",
}

OUT_JSON.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
OUT_LOG.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=STAGED_CURRENT_BASIS_BULK_ELASTICITY_PATCH_PASS",
    "BASIS_DATE=2026-09-23",
    "PRODUCTION_CACHE_ROWS=155",
    "STAGED_CACHE_ROWS=217",
    "CACHE_ROW_DELTA=62",
    "STAGED_ADDED_TICKERS=62",
    "INACTIVE_OLD_TARGETS_NOT_STAGED=38",
    "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
    "SCORER_UNIVERSE=198",
    "BASELINE_READY=15",
    "STAGED_READY=15",
    "BASELINE_LIMITED=183",
    "STAGED_LIMITED=183",
    "BASELINE_BLOCKERS=1687",
    "STAGED_BLOCKERS=1625",
    "BLOCKER_REDUCED_BY=62",
    "CHANGED_SCORE_ROWS=62",
    "NEWLY_READY=0",
    "LOST_READY=0",
    "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
    "PRODUCTION_DATA_MODIFIED=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    "NEXT_STEP=CONTROLLED_CURRENT_BASIS_BULK_PRICE_ELASTICITY_APPLY_V8188A",
])+"\n",encoding="utf-8")

OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
OUT_DOC.write_text(
    "# V8.18.7A current-basis bulk elasticity stage\n\n"
    "- Stage includes only 62 currently active elasticity-blocked targets.\n"
    "- 38 previously audited but currently inactive tickers are excluded.\n"
    "- Production elasticity cache remains 155 rows; staged cache is 217 rows.\n"
    "- READY / LIMITED remains 15 / 183.\n"
    "- Blockers: 1687 -> 1625 (-62).\n"
    "- Existing production elasticity rows changed: 0.\n"
    "- Non-target score drift: 0; lost READY: 0.\n"
    "- Production API, score, source, financial cache, and policy unchanged.\n\n"
    "Next: CONTROLLED_CURRENT_BASIS_BULK_PRICE_ELASTICITY_APPLY_V8188A\n",
    encoding="utf-8"
)

print("V8187A_STAGE=PASS")
print("V8187A_CACHE_ROWS=155->217")
print("V8187A_READY=15->15")
print("V8187A_BLOCKERS=1687->1625")
print("V8187A_CHANGED_SCORE_ROWS=62")
