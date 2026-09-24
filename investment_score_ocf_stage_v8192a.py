import csv, json, shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.19.2A-stage-current-ocf-patch"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8191A_VERSION="2026-09-24-v8.19.1A-freeze-recoverable-ocf-shadow-current-score"
V8191A_COMMIT="c03e0cb88c381916c5c0e1934bd26c2f9635a39a"
OCF_CONTRACT_VERSION="2026-09-12-v8.7.4-audited-operating-cash-flow-source"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

SHADOW_JSON=ROOT/"latest/investment_score_ocf_shadow_v8191a_summary_latest.json"
SHADOW_COMPARE=ROOT/"latest/investment_score_ocf_shadow_v8191a.csv"
FROZEN=ROOT/"latest/investment_score_ocf_source_v8191a.csv"
CANDIDATE=ROOT/"latest/investment_score_ocf_candidate_v8191a.csv"

PROD=ROOT/"latest/investment_score_ocf_source_latest.csv"
PROD_META=ROOT/"latest/investment_score_ocf_source_latest.json"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

STAGE=ROOT/"latest/investment_score_ocf_stage_v8192a.csv"
STAGE_SOURCE=ROOT/"latest/investment_score_ocf_stage_source_v8192a.csv"
STAGE_COMPARE=ROOT/"latest/investment_score_ocf_stage_v8192a_compare.csv"
OUT_JSON=ROOT/"latest/investment_score_ocf_stage_v8192a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_ocf_stage_v8192a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_ocf_stage_v8192a.md"

def tick(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def rmap(p):
    return {tick(r.get("ticker")):r for r in rows(p) if tick(r.get("ticker"))}

def rj(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def blockers(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_score(ocf_path,tag):
    oc=Path(f"/tmp/{tag}.csv")
    oj=Path(f"/tmp/{tag}.json")
    ol=Path(f"/tmp/{tag}.log")
    od=Path(f"/tmp/{tag}.md")
    old={k:getattr(scorer,k) for k in ("VERSION","OCF","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.OCF=Path(ocf_path)
        scorer.OUT_CSV=oc
        scorer.OUT_JSON=oj
        scorer.OUT_LOG=ol
        scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8192A_SCORER_FAILED:"+str(rc))
    return rmap(oc),rj(oj)

sh=rj(SHADOW_JSON)
meta=rj(PROD_META)
mf=rj(MANIFEST)

assert sh["version"]==V8191A_VERSION
assert sh["status"]=="SOURCE_ONLY_FROZEN_SHADOW_PASS"
assert sh["policy_version"]==POLICY
assert sh["v8190a_result_commit"]=="3134bf6cff5e8576d2de0628629726618b848028"
assert sh["source_frozen_count"]==7
assert sh["current_scorer_universe_count"]==198
assert sh["production_ocf_row_count"]==149
assert sh["shadow_ocf_row_count"]==156
assert sh["baseline_ready_count"]==15
assert sh["shadow_ready_count"]==22
assert sh["baseline_limited_count"]==183
assert sh["shadow_limited_count"]==176
assert sh["baseline_blocker_occurrences"]==1625
assert sh["shadow_blocker_occurrences"]==1618
assert sh["ready_delta"]==7
assert sh["blocker_occurrences_reduced_by"]==7
assert sh["non_target_score_row_changed_count"]==0
assert sh["existing_ocf_row_changed_count"]==0
assert sh["next_step"]=="STAGE_CURRENT_OCF_PATCH_V8192A"

targets=sorted(sh["source_frozen_tickers"])
target_set=set(targets)
assert len(targets)==7
assert targets==sorted(sh["newly_ready_tickers"])

assert meta["version"]==OCF_CONTRACT_VERSION
assert meta["production_unique_tickers"]==149
assert meta["account_id_policy"]=="EXACT_ONLY:ifrs-full_CashFlowsFromUsedInOperatingActivities"

assert mf["release_stage"]=="PRODUCTION"
assert mf["safe_to_analyze_as_latest"] is True
assert int((mf.get("sector_rs_source") or {}).get("unique_ticker_count") or 0)==198

prod_map=rmap(PROD)
cand_map=rmap(CANDIDATE)
frozen_map=rmap(FROZEN)

assert len(prod_map)==149
assert len(cand_map)==156
assert len(frozen_map)==7
assert set(cand_map)-set(prod_map)==target_set
assert set(frozen_map)==target_set
assert all(stable(cand_map[c])==stable(prod_map[c]) for c in prod_map)

frozen_fields=list(rows(FROZEN)[0].keys())
candidate_fields=list(rows(CANDIDATE)[0].keys())

shutil.copy2(CANDIDATE,STAGE)
shutil.copy2(FROZEN,STAGE_SOURCE)

stage_map=rmap(STAGE)
assert len(stage_map)==156
assert set(stage_map)==set(cand_map)
assert all(stable(stage_map[c])==stable(cand_map[c]) for c in cand_map)

base,bs=run_score(PROD,"v8192a_base")
staged,ss=run_score(STAGE,"v8192a_stage")

assert set(base)==set(staged)
assert len(base)==198

br=int(bs["ready_count"])
bl=int(bs["limited_count"])
bb=blockers(base)
sr=int(ss["ready_count"])
sl=int(ss["limited_count"])
sb=blockers(staged)

assert (br,bl,bb)==(15,183,1625), (br,bl,bb)
assert (sr,sl,sb)==(22,176,1618), (sr,sl,sb)

changed=[c for c in sorted(base) if stable(base[c])!=stable(staged[c])]
assert changed==targets

newly=sorted(c for c in base if base[c].get("score_status")!="READY" and staged[c].get("score_status")=="READY")
lost=sorted(c for c in base if base[c].get("score_status")=="READY" and staged[c].get("score_status")!="READY")
assert newly==targets
assert lost==[]

shadow_compare=rmap(SHADOW_COMPARE)
assert set(shadow_compare)==target_set

compare=[]
for c in targets:
    compare.append({
        "ticker":c,
        "name":staged[c].get("name",""),
        "operating_cash_flow_annual":frozen_map[c].get("operating_cash_flow_annual",""),
        "source_fs_div":frozen_map[c].get("source_fs_div",""),
        "baseline_status":base[c].get("score_status",""),
        "staged_status":staged[c].get("score_status",""),
        "baseline_missing_components":base[c].get("missing_components",""),
        "staged_missing_components":staged[c].get("missing_components",""),
        "baseline_score_total":base[c].get("score_total",""),
        "staged_score_total":staged[c].get("score_total",""),
    })

with STAGE_COMPARE.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(compare[0].keys()),lineterminator="\n")
    w.writeheader()
    w.writerows(compare)

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"STAGED_CURRENT_OCF_PATCH_PASS",
    "policy_version":POLICY,
    "v8191a_version":V8191A_VERSION,
    "v8191a_result_commit":V8191A_COMMIT,
    "ocf_contract_version":OCF_CONTRACT_VERSION,
    "staged_ticker_count":7,
    "staged_tickers":targets,
    "production_ocf_row_count":149,
    "staged_ocf_row_count":156,
    "ocf_row_delta":7,
    "existing_ocf_row_changed_count":0,
    "scorer_universe_count":198,
    "baseline_ready_count":15,
    "staged_ready_count":22,
    "ready_delta":7,
    "baseline_limited_count":183,
    "staged_limited_count":176,
    "baseline_blocker_occurrences":1625,
    "staged_blocker_occurrences":1618,
    "blocker_occurrences_reduced_by":7,
    "changed_score_row_count":7,
    "changed_score_tickers":targets,
    "newly_ready_count":7,
    "newly_ready_tickers":targets,
    "lost_ready_count":0,
    "non_target_score_row_changed_count":0,
    "stage_equals_v8191a_candidate":True,
    "hard_guards":{
        "production_ocf_cache_modified":False,
        "production_ocf_metadata_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_price_elasticity_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "source_value_imputed":False,
        "alternate_ocf_account_id_used":False,
        "non_target_score_row_changed":False,
    },
    "automatic_promotion":False,
    "next_step":"CONTROLLED_CURRENT_OCF_APPLY_V8193A",
}

OUT_JSON.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
OUT_LOG.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=STAGED_CURRENT_OCF_PATCH_PASS",
    "STAGED_TICKER_COUNT=7",
    "PRODUCTION_OCF_ROWS=149",
    "STAGED_OCF_ROWS=156",
    "OCF_ROW_DELTA=7",
    "EXISTING_OCF_ROW_CHANGED_COUNT=0",
    "SCORER_UNIVERSE=198",
    "BASELINE_READY=15",
    "STAGED_READY=22",
    "BASELINE_LIMITED=183",
    "STAGED_LIMITED=176",
    "BASELINE_BLOCKERS=1625",
    "STAGED_BLOCKERS=1618",
    "BLOCKER_REDUCED_BY=7",
    "CHANGED_SCORE_ROWS=7",
    "NEWLY_READY=7",
    "LOST_READY=0",
    "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
    "STAGE_EQUALS_V8191A_CANDIDATE=true",
    "PRODUCTION_DATA_MODIFIED=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    "NEXT_STEP=CONTROLLED_CURRENT_OCF_APPLY_V8193A",
])+"\n",encoding="utf-8")

OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
OUT_DOC.write_text(
    "# V8.19.2A current OCF patch stage\n\n"
    "- Staged only the seven V8.19.1A exact OCF rows.\n"
    "- Production OCF remains 149 rows; stage is 156 rows.\n"
    "- READY / LIMITED: 15 / 183 -> 22 / 176.\n"
    "- Blockers: 1625 -> 1618 (-7).\n"
    "- Existing production OCF rows changed: 0.\n"
    "- Non-target score drift: 0; lost READY: 0.\n"
    "- Stage bytes are copied from the validated V8.19.1A candidate.\n"
    "- Production API, score, source, financial, elasticity, and policy remain unchanged.\n\n"
    "Next: CONTROLLED_CURRENT_OCF_APPLY_V8193A\n",
    encoding="utf-8"
)

print("V8192A_OCF_STAGE=PASS")
print("V8192A_OCF_ROWS=149->156")
print("V8192A_READY=15->22")
print("V8192A_BLOCKERS=1625->1618")
