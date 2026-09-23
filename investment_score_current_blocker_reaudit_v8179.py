#!/usr/bin/env python3
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
from investment_score_current_blocker_reaudit_v8148 import classify
from investment_score_current_blocker_reaudit_v8161 import recovery_status, ticker, split_reasons

VERSION="2026-09-23-v8.17.9-dynamic-post-source-apply-blocker-reaudit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8178_VERSION="2026-09-23-v8.17.8-controlled-post-financial-source-cache-apply"
V8178_COMMIT="6a60a7b12909a0cd88dd8680388c7ee7763b4e21"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")
PRIOR=ROOT/"latest/investment_score_source_production_v8178_summary_latest.json"
EXHAUSTED_PRIOR=ROOT/"latest/investment_score_current_blockers_v8171a_summary_latest.json"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"
SOURCE_LOG=ROOT/"latest/investment_score_source_run_log_latest.txt"
FIN_LOG=ROOT/"latest/financial_valuation_run_log_latest.txt"

TMP_CSV=Path("/tmp/v8179_score.csv")
TMP_JSON=Path("/tmp/v8179_score.json")
TMP_LOG=Path("/tmp/v8179_score.log")
TMP_DOC=Path("/tmp/v8179_score.md")

OUT_CSV=ROOT/"latest/investment_score_current_blockers_v8179.csv"
OUT_JSON=ROOT/"latest/investment_score_current_blockers_v8179_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_current_blockers_v8179_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_current_blockers_v8179.md"

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def read_kv(p):
    out={}
    for line in Path(p).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k,v=line.split("=",1)
            out[k.strip()]=v.strip()
    return out

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
        raise RuntimeError("V8179_SCORER_FAILED:"+str(rc))

def main():
    prior=read_json(PRIOR)
    exhausted=read_json(EXHAUSTED_PRIOR)
    mf=read_json(MANIFEST)
    src=read_kv(SOURCE_LOG)
    fin=read_kv(FIN_LOG)

    assert prior["version"]==V8178_VERSION
    assert prior["status"]=="PRODUCTION_SOURCE_CACHE_APPLIED_GATE_SYNCHRONIZED"
    assert prior["policy_version"]==POLICY
    assert prior["rollback_guard"]["enabled"] is True
    assert prior["next_step"]=="POST_SOURCE_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8179"

    assert mf["release_stage"]=="PRODUCTION"
    assert mf["safe_to_analyze_as_latest"] is True

    current_universe=int((mf.get("sector_rs_source") or {}).get("unique_ticker_count") or 0)
    if current_universe<=0:
        raise RuntimeError("V8179_MANIFEST_UNIVERSE_MISSING")

    # Accept either the controlled synchronized state or a newer scheduled refresh,
    # but require valid current source retention.
    if src.get("SOURCE_RETENTION_GUARD")!="PASS":
        raise RuntimeError("V8179_SOURCE_RETENTION_GUARD_NOT_PASS")
    if src.get("STATUS_OK") not in {"true","TRUE"}:
        raise RuntimeError("V8179_SOURCE_STATUS_NOT_OK")

    ev=exhausted["known_exhausted_evidence"]
    da=set(ev["exact_da_exhausted_union_tickers"])
    q2=set(ev["score_cache_q2_exhausted_tickers"])
    v8104=set(ev["v8104_exhausted_tickers"])
    assert len(da)==67
    assert q2=={"357430","365550"}
    assert v8104=={"001020","357250"}

    run_scorer()

    with TMP_CSV.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    score_summary=read_json(TMP_JSON)

    if len(rows)!=current_universe:
        raise RuntimeError(
            f"V8179_SCORER_MANIFEST_UNIVERSE_MISMATCH:{len(rows)}:{current_universe}"
        )

    ready=[r for r in rows if r.get("score_status")=="READY"]
    limited=[r for r in rows if r.get("score_status")=="LIMITED"]
    if len(ready)+len(limited)!=len(rows):
        raise RuntimeError("V8179_UNKNOWN_SCORE_STATUS")

    assert int(score_summary.get("ready_count") or -1)==len(ready)
    assert int(score_summary.get("limited_count") or -1)==len(limited)

    out=[]
    cats=Counter()
    groups=Counter()
    group_tickers=defaultdict(set)
    rec=Counter()
    single_counts=Counter()
    single_tickers=defaultdict(set)
    multi_counts=Counter()
    multi_tickers=defaultdict(set)

    for row in limited:
        code=ticker(row.get("ticker"))
        reasons=split_reasons(row.get("missing_components"))
        if not reasons:
            raise RuntimeError("V8179_LIMITED_WITHOUT_REASON:"+code)
        single=len(reasons)==1

        for reason in reasons:
            cat,group=classify(reason)
            if group=="UNKNOWN":
                raise RuntimeError("V8179_UNCLASSIFIED:"+code+":"+reason)

            status=recovery_status(code,group,single,da,q2,v8104)
            cats[cat]+=1
            groups[group]+=1
            group_tickers[group].add(code)
            rec[status]+=1

            if single and status=="ACTIONABLE_SINGLE_BLOCKER_REAUDIT":
                single_counts[group]+=1
                single_tickers[group].add(code)

            if not single:
                multi_counts[group]+=1
                multi_tickers[group].add(code)

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
            "actionable_single_blocker_tickers":sorted(single_tickers[g]),
            "total_group_blocker_occurrences":groups[g],
        }
        for g,c in single_counts.items() if c
    ],key=lambda x:(-x["actionable_single_blocker_count"],-x["total_group_blocker_occurrences"],x["source_group"]))

    multis=sorted([
        {
            "source_group":g,
            "multi_blocker_occurrences":c,
            "multi_blocker_ticker_count":len(multi_tickers[g]),
            "multi_blocker_tickers":sorted(multi_tickers[g]),
            "total_group_blocker_occurrences":groups[g],
        }
        for g,c in multi_counts.items()
        if c and g!="V880_SCORING_CONTRACT"
    ],key=lambda x:(-x["multi_blocker_occurrences"],-x["multi_blocker_ticker_count"],x["source_group"]))

    if singles:
        mode="ACTIONABLE_SINGLE_BLOCKER"
        selected_group=singles[0]["source_group"]
        selected=singles[0]["actionable_single_blocker_tickers"]
        next_step="AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8180"
    elif multis:
        mode="MULTI_BLOCKER_GROUP"
        selected_group=multis[0]["source_group"]
        selected=multis[0]["multi_blocker_tickers"]
        next_step="AUDIT_TOP_MULTI_BLOCKER_GROUP_V8180"
    else:
        mode="NO_SOURCE_LANE"
        selected_group=""
        selected=[]
        next_step="REVIEW_REMAINING_POLICY_OR_EXHAUSTED_BLOCKERS_V8180"

    out.sort(key=lambda r:(int(r["missing_component_count"]),r["ticker"],r["blocker_reason"]))

    OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
    fields=[
        "ticker","name","market","missing_component_count","blocker_reason",
        "blocker_category","source_group","single_blocker_ticker","recovery_status"
    ]
    with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        w.writerows(out)

    summary={
        "version":VERSION,
        "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
        "status":"AUDIT_ONLY_DYNAMIC_CURRENT_PRODUCTION_BLOCKERS",
        "policy_version":POLICY,
        "v8178_version":V8178_VERSION,
        "v8178_result_commit":V8178_COMMIT,
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
        "current_refresh_state":{
            "financial_version":fin.get("VERSION"),
            "financial_status":fin.get("STATUS"),
            "financial_run_at_kst":fin.get("RUN_AT_KST"),
            "financial_cache_rows":int(fin.get("PRODUCTION_ROWS_AFTER") or fin.get("CACHE_OUTPUT_ROWS") or 0),
            "financial_source_refresh_required":fin.get("SOURCE_REFRESH_REQUIRED"),
            "source_version":src.get("CONTROLLED_PROMOTION_VERSION") or src.get("SCRIPT_VERSION"),
            "source_run_at_kst":src.get("RUN_AT_KST"),
            "source_cache_rows":int(src.get("OUTPUT_ROWS") or 0),
            "source_targets":int(src.get("TARGETS") or 0),
            "source_retention_guard":src.get("SOURCE_RETENTION_GUARD"),
        },
        "scorer_universe_count":len(rows),
        "ready_count":len(ready),
        "limited_count":len(limited),
        "limited_blocker_occurrences":blocker_count,
        "blocker_category_counts":dict(cats),
        "source_group_counts":dict(groups),
        "source_group_tickers":{g:sorted(v) for g,v in group_tickers.items()},
        "recovery_status_counts":dict(rec),
        "known_exhausted_evidence":{
            "exact_da_exhausted_union_count":67,
            "exact_da_exhausted_union_tickers":sorted(da),
            "score_cache_q2_exhausted_count":2,
            "score_cache_q2_exhausted_tickers":sorted(q2),
            "v8104_exhausted_tickers":sorted(v8104),
        },
        "actionable_single_priority":singles,
        "multi_blocker_priority":multis,
        "selection_mode":mode,
        "selected_source_group":selected_group,
        "selected_ticker_count":len(selected),
        "selected_tickers":selected,
        "baseline_reference":{
            "v8178_scorer_universe":prior["scorer_regression"]["universe_count"],
            "v8178_ready":prior["scorer_regression"]["ready_after"],
            "v8178_limited":prior["scorer_regression"]["limited_after"],
            "v8178_blockers":prior["scorer_regression"]["blockers_after"],
            "current_state_may_be_newer_due_to_scheduled_refresh":True,
        },
        "separate_operational_issue":{
            "us_sp500_run_id":35803064524,
            "status":"FAILED",
            "cause":"MISSING_PYKRX_DEPENDENCY_IN_ISOLATED_BUILD",
            "separate_from_score_blocker_lane":True,
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

    OUT_JSON.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY_DYNAMIC_CURRENT_PRODUCTION_BLOCKERS",
        f"PRODUCTION_BASIS_DATE={mf.get('basis_date')}",
        f"SCORER_UNIVERSE={len(rows)}",
        f"READY={len(ready)}",
        f"LIMITED={len(limited)}",
        f"BLOCKER_OCCURRENCES={blocker_count}",
        f"ACTIONABLE_SINGLE_BLOCKERS={sum(single_counts.values())}",
        f"SELECTION_MODE={mode}",
        f"SELECTED_SOURCE_GROUP={selected_group}",
        f"SELECTED_TICKER_COUNT={len(selected)}",
        f"SOURCE_CACHE_ROWS={src.get('OUTPUT_ROWS','')}",
        "FIXED_HISTORICAL_UNIVERSE_ASSUMPTION_USED=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={next_step}",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    OUT_DOC.write_text(
        "# V8.17.9 dynamic post-source-apply blocker reaudit\n\n"
        f"- Current scorer universe: {len(rows)}.\n"
        f"- READY / LIMITED: {len(ready)} / {len(limited)}.\n"
        f"- Current blocker occurrences: {blocker_count}.\n"
        "- Uses the current production manifest rather than a fixed historical universe.\n"
        f"- Selection mode: {mode}.\n"
        f"- Selected source group: {selected_group}.\n"
        f"- Selected ticker count: {len(selected)}.\n"
        "- Known exhausted evidence is retained and not auto-requeried.\n"
        "- No production cache, API, score or policy is modified.\n\n"
        f"Next: {next_step}\n",
        encoding="utf-8"
    )

    print("V8179_DYNAMIC_REAUDIT=PASS")
    print(f"V8179_SCORER_UNIVERSE={len(rows)}")
    print(f"V8179_READY={len(ready)}")
    print(f"V8179_LIMITED={len(limited)}")
    print(f"V8179_BLOCKERS={blocker_count}")
    print(f"V8179_SELECTION_MODE={mode}")
    print(f"V8179_SELECTED_SOURCE_GROUP={selected_group}")
    print(f"V8179_SELECTED_TICKER_COUNT={len(selected)}")
    print(f"V8179_NEXT_STEP={next_step}")

if __name__=="__main__":
    main()
