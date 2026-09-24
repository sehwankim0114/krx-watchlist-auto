#!/usr/bin/env python3
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
from investment_score_current_blocker_reaudit_v8148 import classify
from investment_score_current_blocker_reaudit_v8161 import (
    recovery_status, ticker, split_reasons
)

VERSION="2026-09-24-v8.18.9A-post-bulk-elasticity-dynamic-blocker-reaudit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8188A_VERSION="2026-09-24-v8.18.8A-controlled-current-basis-bulk-price-elasticity-apply"
V8188A_COMMIT="f38115426e64cbd7e9069c08d872404d26e63e7b"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

PRIOR=ROOT/"latest/investment_score_price_elasticity_production_v8188a_summary_latest.json"
EXHAUSTED=ROOT/"latest/investment_score_current_blockers_v8179_summary_latest.json"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"
ELASTIC_META=ROOT/"latest/investment_score_price_elasticity_20d_latest.json"

TMP_CSV=Path("/tmp/v8189a_score.csv")
TMP_JSON=Path("/tmp/v8189a_score.json")
TMP_LOG=Path("/tmp/v8189a_score.log")
TMP_DOC=Path("/tmp/v8189a_score.md")

OUT_CSV=ROOT/"latest/investment_score_current_blockers_v8189a.csv"
OUT_JSON=ROOT/"latest/investment_score_current_blockers_v8189a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_current_blockers_v8189a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_current_blockers_v8189a.md"

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def run_scorer():
    old={k:getattr(scorer,k) for k in ("VERSION","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.OUT_CSV=TMP_CSV
        scorer.OUT_JSON=TMP_JSON
        scorer.OUT_LOG=TMP_LOG
        scorer.OUT_DOC=TMP_DOC
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8189A_SCORER_FAILED:"+str(rc))

prior=read_json(PRIOR)
exhausted=read_json(EXHAUSTED)
mf=read_json(MANIFEST)
em=read_json(ELASTIC_META)

assert prior["version"]==V8188A_VERSION
assert prior["status"]=="PRODUCTION_CURRENT_BASIS_BULK_ELASTICITY_APPLIED_POST_REGRESSION_PASS"
assert prior["policy_version"]==POLICY
assert prior["stage_result_commit"]=="2f03b743d8e9f168cd786a635a59c5804c9c2e45"
assert prior["rollback_guard"]["enabled"] is True
assert prior["next_step"]=="POST_BULK_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8189A"

assert em["refresh_version"]==V8188A_VERSION
assert em["production_unique_tickers"]==217
assert em["ready_tickers"]==217
assert em["limited_tickers"]==0
assert em["latest_row_basis_date"]=="2026-09-23"
assert em["narrow_patch"]["ticker_count"]==6
assert em["bulk_patch"]["ticker_count"]==62

assert mf["release_stage"]=="PRODUCTION"
assert mf["safe_to_analyze_as_latest"] is True
current_universe=int((mf.get("sector_rs_source") or {}).get("unique_ticker_count") or 0)
if current_universe<=0:
    raise RuntimeError("V8189A_MANIFEST_UNIVERSE_MISSING")

ev=exhausted["known_exhausted_evidence"]
da=set(ev["exact_da_exhausted_union_tickers"])
q2=set(ev["score_cache_q2_exhausted_tickers"])
v8104=set(ev["v8104_exhausted_tickers"])
if len(da)!=67:
    raise RuntimeError("V8189A_DA_EXHAUSTED_EVIDENCE_DRIFT")
if q2!={"357430","365550"}:
    raise RuntimeError("V8189A_Q2_EXHAUSTED_EVIDENCE_DRIFT")
if v8104!={"001020","357250"}:
    raise RuntimeError("V8189A_V8104_EXHAUSTED_EVIDENCE_DRIFT")

run_scorer()

with TMP_CSV.open(encoding="utf-8-sig",newline="") as f:
    score_rows=list(csv.DictReader(f))
score_summary=read_json(TMP_JSON)

if len(score_rows)!=current_universe:
    raise RuntimeError(
        f"V8189A_SCORER_MANIFEST_UNIVERSE_MISMATCH:{len(score_rows)}:{current_universe}"
    )

ready=[r for r in score_rows if r.get("score_status")=="READY"]
limited=[r for r in score_rows if r.get("score_status")=="LIMITED"]
if len(ready)+len(limited)!=len(score_rows):
    raise RuntimeError("V8189A_UNKNOWN_SCORE_STATUS")

assert int(score_summary.get("ready_count") or -1)==len(ready)
assert int(score_summary.get("limited_count") or -1)==len(limited)

out=[]
cats=Counter()
groups=Counter()
group_tickers=defaultdict(set)
rec=Counter()

actionable_single_counts=Counter()
actionable_single_tickers=defaultdict(set)

actionable_multi_counts=Counter()
actionable_multi_tickers=defaultdict(set)

exhausted_counts=Counter()
policy_counts=Counter()

for row in limited:
    code=ticker(row.get("ticker"))
    reasons=split_reasons(row.get("missing_components"))
    if not reasons:
        raise RuntimeError("V8189A_LIMITED_WITHOUT_REASON:"+code)
    single=len(reasons)==1

    for reason in reasons:
        cat,group=classify(reason)
        if group=="UNKNOWN":
            raise RuntimeError("V8189A_UNCLASSIFIED:"+code+":"+reason)

        status=recovery_status(code,group,single,da,q2,v8104)

        cats[cat]+=1
        groups[group]+=1
        group_tickers[group].add(code)
        rec[status]+=1

        if status=="ACTIONABLE_SINGLE_BLOCKER_REAUDIT":
            actionable_single_counts[group]+=1
            actionable_single_tickers[group].add(code)

        if status=="MULTI_BLOCKER_SOURCE_LANE":
            actionable_multi_counts[group]+=1
            actionable_multi_tickers[group].add(code)

        if status.startswith("EXHAUSTED_"):
            exhausted_counts[status]+=1

        if status=="POLICY_SEMANTIC_DEFER":
            policy_counts[group]+=1

        out.append({
            "ticker":code,
            "name":row.get("name",""),
            "market":row.get("market",""),
            "missing_component_count":len(reasons),
            "blocker_reason":reason,
            "blocker_category":cat,
            "source_group":group,
            "single_blocker_ticker":"TRUE" if single else "FALSE",
            "recovery_status":status,
        })

blocker_count=len(out)

singles=sorted([
    {
        "source_group":g,
        "actionable_single_blocker_count":c,
        "actionable_single_blocker_tickers":sorted(actionable_single_tickers[g]),
        "total_group_blocker_occurrences":groups[g],
    }
    for g,c in actionable_single_counts.items() if c
], key=lambda x:(
    -x["actionable_single_blocker_count"],
    -x["total_group_blocker_occurrences"],
    x["source_group"]
))

multis=sorted([
    {
        "source_group":g,
        "actionable_multi_blocker_occurrences":c,
        "actionable_multi_blocker_ticker_count":len(actionable_multi_tickers[g]),
        "actionable_multi_blocker_tickers":sorted(actionable_multi_tickers[g]),
        "total_group_blocker_occurrences":groups[g],
    }
    for g,c in actionable_multi_counts.items()
    if c and g!="V880_SCORING_CONTRACT"
], key=lambda x:(
    -x["actionable_multi_blocker_occurrences"],
    -x["actionable_multi_blocker_ticker_count"],
    x["source_group"]
))

if singles:
    mode="ACTIONABLE_SINGLE_BLOCKER"
    selected_group=singles[0]["source_group"]
    selected=singles[0]["actionable_single_blocker_tickers"]
    next_step="AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8190A"
elif multis:
    mode="ACTIONABLE_MULTI_BLOCKER_GROUP"
    selected_group=multis[0]["source_group"]
    selected=multis[0]["actionable_multi_blocker_tickers"]
    next_step="AUDIT_TOP_ACTIONABLE_MULTI_BLOCKER_GROUP_V8190A"
else:
    mode="NO_ACTIONABLE_SOURCE_LANE"
    selected_group=""
    selected=[]
    next_step="REVIEW_REMAINING_POLICY_OR_EXHAUSTED_BLOCKERS_V8190A"

out.sort(key=lambda r:(
    int(r["missing_component_count"]),
    r["ticker"],
    r["blocker_reason"]
))

OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
fields=[
    "ticker","name","market","missing_component_count",
    "blocker_reason","blocker_category","source_group",
    "single_blocker_ticker","recovery_status"
]
with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
    w.writeheader()
    w.writerows(out)

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"AUDIT_ONLY_DYNAMIC_POST_BULK_ELASTICITY_BLOCKERS",
    "policy_version":POLICY,
    "v8188a_version":V8188A_VERSION,
    "v8188a_result_commit":V8188A_COMMIT,
    "reaudit_mode":"CURRENT_PRODUCTION_DYNAMIC_UNIVERSE",
    "production_manifest":{
        "basis_date":mf.get("basis_date"),
        "source_build_id":mf.get("source_build_id"),
        "source_commit":mf.get("source_commit"),
        "manifest_universe_count":mf.get("universe_count"),
        "scorer_target_universe_count":current_universe,
        "kospi_rows":mf["tables"]["kospi"]["row_count"],
        "decliners_rows":mf["tables"]["decliners"]["row_count"],
        "decliners24_rows":mf["tables"]["decliners24"]["row_count"],
    },
    "current_elasticity_state":{
        "refresh_version":em.get("refresh_version"),
        "production_unique_tickers":em.get("production_unique_tickers"),
        "ready_tickers":em.get("ready_tickers"),
        "latest_row_basis_date":em.get("latest_row_basis_date"),
        "narrow_patch_count":em.get("narrow_patch",{}).get("ticker_count"),
        "bulk_patch_count":em.get("bulk_patch",{}).get("ticker_count"),
    },
    "scorer_universe_count":len(score_rows),
    "ready_count":len(ready),
    "limited_count":len(limited),
    "limited_blocker_occurrences":blocker_count,
    "blocker_category_counts":dict(cats),
    "source_group_counts":dict(groups),
    "source_group_tickers":{g:sorted(v) for g,v in group_tickers.items()},
    "recovery_status_counts":dict(rec),
    "exhausted_status_counts":dict(exhausted_counts),
    "policy_defer_group_counts":dict(policy_counts),
    "known_exhausted_evidence":{
        "exact_da_exhausted_union_count":67,
        "exact_da_exhausted_union_tickers":sorted(da),
        "score_cache_q2_exhausted_count":2,
        "score_cache_q2_exhausted_tickers":sorted(q2),
        "v8104_exhausted_tickers":sorted(v8104),
    },
    "actionable_single_priority":singles,
    "actionable_multi_priority":multis,
    "selection_mode":mode,
    "selected_source_group":selected_group,
    "selected_ticker_count":len(selected),
    "selected_tickers":selected,
    "baseline_reference":{
        "v8188a_scorer_universe":prior["scorer_regression"]["universe_count"],
        "v8188a_ready":prior["scorer_regression"]["ready_after"],
        "v8188a_limited":prior["scorer_regression"]["limited_after"],
        "v8188a_blockers":prior["scorer_regression"]["blockers_after"],
        "current_state_may_be_newer_due_to_scheduled_refresh":True,
    },
    "hard_guards":{
        "production_data_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "source_value_imputed":False,
        "exhausted_lane_auto_requeried":False,
        "fixed_historical_universe_assumption_used":False,
    },
    "next_step":next_step,
}

OUT_JSON.write_text(
    json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
    encoding="utf-8"
)

OUT_LOG.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=AUDIT_ONLY_DYNAMIC_POST_BULK_ELASTICITY_BLOCKERS",
    f"PRODUCTION_BASIS_DATE={mf.get('basis_date')}",
    f"SCORER_UNIVERSE={len(score_rows)}",
    f"READY={len(ready)}",
    f"LIMITED={len(limited)}",
    f"BLOCKER_OCCURRENCES={blocker_count}",
    f"ACTIONABLE_SINGLE_BLOCKERS={sum(actionable_single_counts.values())}",
    f"ACTIONABLE_MULTI_BLOCKERS={sum(actionable_multi_counts.values())}",
    f"SELECTION_MODE={mode}",
    f"SELECTED_SOURCE_GROUP={selected_group}",
    f"SELECTED_TICKER_COUNT={len(selected)}",
    f"ELASTICITY_CACHE_ROWS={em.get('production_unique_tickers')}",
    f"ELASTICITY_BULK_PATCH_COUNT={em.get('bulk_patch',{}).get('ticker_count')}",
    "FIXED_HISTORICAL_UNIVERSE_ASSUMPTION_USED=false",
    "EXHAUSTED_LANE_AUTO_REQUERIED=false",
    "PRODUCTION_DATA_MODIFIED=false",
    "STATUS_OK=true",
    f"NEXT_STEP={next_step}",
])+"\n",encoding="utf-8")

OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
OUT_DOC.write_text(
    "# V8.18.9A dynamic post-bulk-elasticity blocker reaudit\n\n"
    f"- Current scorer universe: {len(score_rows)}.\n"
    f"- READY / LIMITED: {len(ready)} / {len(limited)}.\n"
    f"- Current blocker occurrences: {blocker_count}.\n"
    f"- Actionable single blocker occurrences: {sum(actionable_single_counts.values())}.\n"
    f"- Actionable multi blocker occurrences: {sum(actionable_multi_counts.values())}.\n"
    f"- Selection mode: {mode}.\n"
    f"- Selected source group: {selected_group}.\n"
    f"- Selected ticker count: {len(selected)}.\n"
    "- Exhausted evidence is retained and excluded from actionable selection.\n"
    "- Uses current production manifest; no fixed historical universe.\n"
    "- No production cache, API, score or policy is modified.\n\n"
    f"Next: {next_step}\n",
    encoding="utf-8"
)

print("V8189A_DYNAMIC_REAUDIT=PASS")
print(f"V8189A_SCORER_UNIVERSE={len(score_rows)}")
print(f"V8189A_READY={len(ready)}")
print(f"V8189A_LIMITED={len(limited)}")
print(f"V8189A_BLOCKERS={blocker_count}")
print(f"V8189A_SELECTION_MODE={mode}")
print(f"V8189A_SELECTED_SOURCE_GROUP={selected_group}")
print(f"V8189A_SELECTED_TICKER_COUNT={len(selected)}")
print(f"V8189A_NEXT_STEP={next_step}")
