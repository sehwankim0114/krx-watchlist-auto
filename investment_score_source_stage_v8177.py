import csv, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-23-v8.17.7-stage-post-financial-source-cache-refresh"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
PRIOR_VERSION="2026-09-23-v8.17.6A-shadow-post-financial-source-refresh-preferred-inheritance-aware"
PRIOR_COMMIT="95ec13e162cdaaf7a6d1e2971521cca7bfd2d40c"
NEXT="CONTROLLED_POST_FINANCIAL_SOURCE_CACHE_APPLY_V8178"
ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")
PROD=ROOT/"latest/investment_score_source_cache_latest.csv"
SRC=ROOT/"latest/investment_score_source_cache_candidate_v8176a.csv"
PRIOR=ROOT/"latest/investment_score_source_shadow_v8176a_summary_latest.json"
STAGED=ROOT/"latest/investment_score_source_cache_candidate_v8177.csv"
REG=ROOT/"latest/investment_score_source_stage_v8177_regression.csv"
SUMMARY=ROOT/"latest/investment_score_source_stage_v8177_summary_latest.json"
RUNLOG=ROOT/"latest/investment_score_source_stage_v8177_run_log_latest.txt"
DOC=ROOT/"docs/investment_score_source_stage_v8177.md"

EXPECTED_INHERITED={"000225":"000220","002787":"002780","078935":"078930"}

def ticker(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        r=csv.DictReader(f); return list(r), list(r.fieldnames or [])

def rmap(p):
    rs,_=rows(p); return {ticker(r.get("ticker")):r for r in rs if ticker(r.get("ticker"))}

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def blockers(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def active_codes():
    out=set()
    for table in ("kospi","decliners","decliners24"):
        j=read_json(ROOT/f"api/two_table_v1/{table}.json")
        for r in j.get("rows") or []:
            c=ticker(r.get("ticker"))
            if c: out.add(c)
    return out

def run(raw,ocsv,ojson,olog,odoc):
    old={k:getattr(scorer,k) for k in ("VERSION","RAW","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION; scorer.RAW=Path(raw)
        scorer.OUT_CSV=Path(ocsv); scorer.OUT_JSON=Path(ojson)
        scorer.OUT_LOG=Path(olog); scorer.OUT_DOC=Path(odoc)
        rc=scorer.main()
    finally:
        for k,v in old.items(): setattr(scorer,k,v)
    if rc not in (None,0): raise RuntimeError("V8177_SCORER_FAILED")

def main():
    p=read_json(PRIOR)
    assert p["version"]==PRIOR_VERSION
    assert p["status"]=="SHADOW_ONLY_POST_FINANCIAL_SOURCE_REFRESH_PASS"
    assert p["policy_version"]==POLICY
    assert p["next_step"]=="STAGE_POST_FINANCIAL_SOURCE_CACHE_REFRESH_V8177"

    sc=p["source_cache"]; rg=p["scorer_regression"]; gate=p["v854_gate"]
    assert (sc["production_row_count"],sc["shadow_row_count"],sc["row_delta"],sc["actual_added_ticker_count"])==(227,288,61,61)
    assert (rg["baseline_ready_count"],rg["shadow_ready_count"],rg["baseline_limited_count"],rg["shadow_limited_count"])==(14,14,143,143)
    assert (rg["baseline_blocker_occurrences"],rg["shadow_blocker_occurrences"],rg["blocker_occurrences_reduced_by"])==(906,543,363)
    assert rg["changed_added_score_row_count"]==61
    assert rg["expected_inherited_preferred_score_row_changed_count"]==3
    assert rg["expected_inherited_preferred_common_map"]==EXPECTED_INHERITED
    assert rg["unexpected_non_added_score_row_changed_count"]==0
    assert rg["newly_ready_count"]==0 and rg["lost_ready_count"]==0
    assert gate["need_refresh"] is True
    assert gate["reason"]=="financial_source_newer_than_investment_source"

    prod,pfields=rows(PROD); cand,cfields=rows(SRC)
    assert pfields==cfields
    assert len(prod)==227 and len(cand)==288
    pm={ticker(r["ticker"]):r for r in prod}
    cm={ticker(r["ticker"]):r for r in cand}
    assert len(pm)==227 and len(cm)==288
    assert set(pm)<set(cm)
    added=set(cm)-set(pm)
    assert added==set(sc["actual_added_tickers"]) and len(added)==61

    STAGED.write_bytes(SRC.read_bytes())

    base_csv=Path("/tmp/v8177_base.csv"); base_json=Path("/tmp/v8177_base.json")
    stage_csv=Path("/tmp/v8177_stage.csv"); stage_json=Path("/tmp/v8177_stage.json")
    run(PROD,base_csv,base_json,Path("/tmp/v8177_base.log"),Path("/tmp/v8177_base.md"))
    run(STAGED,stage_csv,stage_json,Path("/tmp/v8177_stage.log"),Path("/tmp/v8177_stage.md"))

    base=rmap(base_csv); staged=rmap(stage_csv)
    bs=read_json(base_json); ss=read_json(stage_json)
    active=active_codes()
    assert len(active)==157 and set(base)==set(staged)==active
    assert (int(bs.get("ready_count") or 0),int(ss.get("ready_count") or 0),int(bs.get("limited_count") or 0),int(ss.get("limited_count") or 0),blockers(base),blockers(staged))==(14,14,143,143,906,543)

    changed_added={c for c in added if stable(base[c])!=stable(staged[c])}
    changed_other={c for c in active-added if stable(base[c])!=stable(staged[c])}
    assert changed_added==set(rg["changed_added_score_tickers"])
    assert len(changed_added)==61
    assert changed_other==set(EXPECTED_INHERITED)

    for pref,common in EXPECTED_INHERITED.items():
        assert str(staged[pref].get("raw_source_mode") or "").startswith("PREFERRED_COMMON:"+common)

    lost=[c for c in active if base[c].get("score_status")=="READY" and staged[c].get("score_status")!="READY"]
    new=[c for c in active if base[c].get("score_status")!="READY" and staged[c].get("score_status")=="READY"]
    assert not lost and not new

    reg=[]
    for c in sorted(changed_added|changed_other):
        reg.append({
            "ticker":c,
            "change_type":"DIRECT_ADDED_SOURCE" if c in added else "PREFERRED_COMMON_INHERITANCE",
            "baseline_raw_source_mode":base[c].get("raw_source_mode",""),
            "staged_raw_source_mode":staged[c].get("raw_source_mode",""),
            "baseline_missing_component_count":base[c].get("missing_component_count",""),
            "staged_missing_component_count":staged[c].get("missing_component_count",""),
        })
    with REG.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(reg[0].keys()),lineterminator="\n"); w.writeheader(); w.writerows(reg)

    summary={
        "version":VERSION,
        "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
        "status":"STAGED_POST_FINANCIAL_SOURCE_CACHE_REGRESSION_PASS",
        "policy_version":POLICY,
        "v8176a_version":PRIOR_VERSION,
        "v8176a_result_commit":PRIOR_COMMIT,
        "staged_source_cache":{
            "production_row_count":227,"staged_row_count":288,"row_delta":61,
            "added_ticker_count":61,"added_tickers":sorted(added)
        },
        "scorer_regression":{
            "universe_count":157,
            "baseline_ready_count":14,"staged_ready_count":14,
            "baseline_limited_count":143,"staged_limited_count":143,
            "baseline_blocker_occurrences":906,"staged_blocker_occurrences":543,
            "blocker_occurrences_reduced_by":363,
            "direct_added_score_row_changed_count":61,
            "direct_added_score_row_changed_tickers":sorted(changed_added),
            "expected_inherited_preferred_score_row_changed_count":3,
            "expected_inherited_preferred_score_row_changed_tickers":sorted(EXPECTED_INHERITED),
            "expected_inherited_preferred_common_map":EXPECTED_INHERITED,
            "unexpected_score_row_changed_count":0,
            "newly_ready_count":0,"lost_ready_count":0
        },
        "gate_stage":{
            "need_refresh_before_apply":True,
            "reason":"financial_source_newer_than_investment_source",
            "financial_run_at_kst":gate["financial_run_at_kst"],
            "source_run_at_kst":gate["source_run_at_kst"],
            "manual_dispatch_force_refresh_preserved":True,
            "production_workflow_modified":False
        },
        "automatic_promotion":{"allowed":False,"production_source_cache_modified":False},
        "hard_guards":{
            "production_source_cache_modified":False,
            "production_source_run_log_modified":False,
            "production_financial_cache_modified":False,
            "production_financial_run_log_modified":False,
            "production_api_modified":False,
            "production_score_written":False,
            "scoring_policy_modified":False,
            "source_value_imputed":False,
            "unexpected_score_row_changed":False,
            "preferred_inheritance_contract_violated":False,
            "ready_regression_count":0
        },
        "next_step":NEXT
    }
    SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    RUNLOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=STAGED_POST_FINANCIAL_SOURCE_CACHE_REGRESSION_PASS",
        "PRODUCTION_SOURCE_ROWS=227","STAGED_SOURCE_ROWS=288","SOURCE_ROW_DELTA=61","ADDED_TICKERS=61",
        "SCORER_UNIVERSE=157","BASELINE_READY=14","STAGED_READY=14","BASELINE_LIMITED=143","STAGED_LIMITED=143",
        "BASELINE_BLOCKERS=906","STAGED_BLOCKERS=543","BLOCKER_REDUCED_BY=363",
        "DIRECT_ADDED_SCORE_ROWS_CHANGED=61","EXPECTED_INHERITED_PREFERRED_SCORE_ROWS=3",
        "EXPECTED_INHERITED_PREFERRED_TICKERS=000225,002787,078935",
        "UNEXPECTED_SCORE_ROW_CHANGED=0","NEWLY_READY=0","LOST_READY=0",
        "GATE_NEED_REFRESH=true","GATE_REASON=financial_source_newer_than_investment_source",
        "PRODUCTION_DATA_MODIFIED=false","AUTOMATIC_PROMOTION=false","STATUS_OK=true",
        f"NEXT_STEP={NEXT}"
    ])+"\n",encoding="utf-8")
    DOC.parent.mkdir(parents=True,exist_ok=True)
    DOC.write_text(
        "# V8.17.7 staged post-financial source-cache refresh\n\n"
        "- Exact V8.17.6A 288-row source candidate staged.\n"
        "- Production source cache remains 227 rows.\n"
        "- Blockers reproduce 906 -> 543 (-363).\n"
        "- READY/LIMITED remains 14/143.\n"
        "- 61 direct rows plus exactly 3 preferred-share inheritance rows change.\n"
        "- Unexpected drift 0; lost READY 0.\n"
        "- Production files remain unchanged.\n\n"
        "Next: CONTROLLED_POST_FINANCIAL_SOURCE_CACHE_APPLY_V8178\n",
        encoding="utf-8"
    )
    print("V8177_STAGE=PASS")

if __name__=="__main__":
    main()
