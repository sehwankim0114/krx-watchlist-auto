import csv, json, shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.19.3A-controlled-current-ocf-apply"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
STAGE_VERSION="2026-09-24-v8.19.2A-stage-current-ocf-patch"
STAGE_COMMIT="b7f31d2ef8fef000d1d06834b9b5e528b144b60b"
OCF_CONTRACT_VERSION="2026-09-12-v8.7.4-audited-operating-cash-flow-source"
IFRS_OCF_ID="ifrs-full_CashFlowsFromUsedInOperatingActivities"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

STAGE=ROOT/"latest/investment_score_ocf_stage_v8192a.csv"
STAGE_SUM=ROOT/"latest/investment_score_ocf_stage_v8192a_summary_latest.json"

PROD=ROOT/"latest/investment_score_ocf_source_latest.csv"
META=ROOT/"latest/investment_score_ocf_source_latest.json"
RUNLOG=ROOT/"latest/investment_score_ocf_source_run_log_latest.txt"

OUT_JSON=ROOT/"latest/investment_score_ocf_production_v8193a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_ocf_production_v8193a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_ocf_production_v8193a.md"

BACKUP=Path("/tmp/v8193a_backup")

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
    oc=Path(f"/tmp/{tag}.csv"); oj=Path(f"/tmp/{tag}.json")
    ol=Path(f"/tmp/{tag}.log"); od=Path(f"/tmp/{tag}.md")
    old={k:getattr(scorer,k) for k in ("VERSION","OCF","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.OCF=Path(ocf_path)
        scorer.OUT_CSV=oc; scorer.OUT_JSON=oj
        scorer.OUT_LOG=ol; scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8193A_SCORER_FAILED:"+str(rc))
    return rmap(oc),rj(oj)

def backup():
    BACKUP.mkdir(parents=True,exist_ok=True)
    shutil.copy2(PROD,BACKUP/PROD.name)
    shutil.copy2(META,BACKUP/META.name)
    shutil.copy2(RUNLOG,BACKUP/RUNLOG.name)

def rollback():
    shutil.copy2(BACKUP/PROD.name,PROD)
    shutil.copy2(BACKUP/META.name,META)
    shutil.copy2(BACKUP/RUNLOG.name,RUNLOG)

stage_sum=rj(STAGE_SUM)
old_meta=rj(META)

assert stage_sum["version"]==STAGE_VERSION
assert stage_sum["status"]=="STAGED_CURRENT_OCF_PATCH_PASS"
assert stage_sum["policy_version"]==POLICY
assert stage_sum["v8191a_result_commit"]=="c03e0cb88c381916c5c0e1934bd26c2f9635a39a"
assert stage_sum["staged_ticker_count"]==7
assert stage_sum["production_ocf_row_count"]==149
assert stage_sum["staged_ocf_row_count"]==156
assert stage_sum["ocf_row_delta"]==7
assert stage_sum["existing_ocf_row_changed_count"]==0
assert stage_sum["scorer_universe_count"]==198
assert (stage_sum["baseline_ready_count"],stage_sum["staged_ready_count"])==(15,22)
assert (stage_sum["baseline_limited_count"],stage_sum["staged_limited_count"])==(183,176)
assert (stage_sum["baseline_blocker_occurrences"],stage_sum["staged_blocker_occurrences"])==(1625,1618)
assert stage_sum["blocker_occurrences_reduced_by"]==7
assert stage_sum["changed_score_row_count"]==7
assert stage_sum["newly_ready_count"]==7
assert stage_sum["lost_ready_count"]==0
assert stage_sum["non_target_score_row_changed_count"]==0
assert stage_sum["stage_equals_v8191a_candidate"] is True
assert stage_sum["next_step"]=="CONTROLLED_CURRENT_OCF_APPLY_V8193A"

targets=sorted(stage_sum["staged_tickers"])
assert len(targets)==7
assert targets==sorted(stage_sum["changed_score_tickers"])
assert targets==sorted(stage_sum["newly_ready_tickers"])
tset=set(targets)

assert old_meta["version"]==OCF_CONTRACT_VERSION
assert old_meta["refresh_version"]=="2026-09-21-v8.13.3a-controlled-production-ocf-refresh"
assert old_meta["status"]=="READY_SOURCE_ONLY"
assert old_meta["production_unique_tickers"]==149
assert old_meta["operating_cash_flow_ready"]==147
assert old_meta["operating_cash_flow_limited"]==2
assert old_meta["account_id_policy"]=="EXACT_ONLY:"+IFRS_OCF_ID
assert old_meta["strict_identity_unresolved_count"]==2
assert set(old_meta["strict_identity_unresolved_tickers"])=={"000480","002200"}

prod_map=rmap(PROD)
stage_map=rmap(STAGE)

assert len(prod_map)==149
assert len(stage_map)==156
assert set(stage_map)-set(prod_map)==tset
assert all(stable(stage_map[c])==stable(prod_map[c]) for c in prod_map)

for c in targets:
    r=stage_map[c]
    assert r["source_status"]=="READY"
    assert r["account_id"]==IFRS_OCF_ID
    assert r["source_fs_div"] in {"CFS","OFS"}
    assert str(r["operating_cash_flow_annual"]).strip()
    assert r["source_mode"]=="DIRECT_EXACT_IFRS_V8190A"

source_counts=Counter((r.get("source_mode") or "MISSING") for r in stage_map.values())
ready_rows=[r for r in stage_map.values() if r.get("source_status")=="READY"]
limited_rows=[r for r in stage_map.values() if r.get("source_status")!="READY"]
assert len(ready_rows)==154
assert len(limited_rows)==2
unresolved={tick(r.get("ticker")) for r in limited_rows if r.get("source_mode")=="UNRESOLVED_CURRENT_IDENTITY"}
assert unresolved=={"000480","002200"}

base,bs=run_score(PROD,"v8193a_base")
staged,ss=run_score(STAGE,"v8193a_stage")
assert len(base)==198 and set(base)==set(staged)
assert (int(bs["ready_count"]),int(bs["limited_count"]),blockers(base))==(15,183,1625)
assert (int(ss["ready_count"]),int(ss["limited_count"]),blockers(staged))==(22,176,1618)

changed=[c for c in sorted(base) if stable(base[c])!=stable(staged[c])]
assert changed==targets

backup()

try:
    shutil.copy2(STAGE,PROD)

    now=datetime.now(KST).isoformat(timespec="seconds")
    meta=dict(old_meta)
    meta.update({
        "refresh_version":VERSION,
        "generated_at_kst":now,
        "status":"READY_SOURCE_ONLY",
        "production_unique_tickers":156,
        "operating_cash_flow_ready":154,
        "operating_cash_flow_limited":2,
        "promoted_from_candidate_version":STAGE_VERSION,
        "promoted_from_candidate_commit":STAGE_COMMIT,
        "strict_identity_unresolved_count":2,
        "strict_identity_unresolved_tickers":["000480","002200"],
        "source_mode_counts":dict(source_counts),
        "scorer_validation":{
            "baseline_ready_count":15,
            "post_ready_count":22,
            "ready_delta":7,
            "baseline_blocker_occurrences":1625,
            "post_blocker_occurrences":1618,
            "blocker_occurrences_reduced_by":7,
        },
        "narrow_patch":{
            "version":VERSION,
            "ticker_count":7,
            "tickers":targets,
            "source":"V8.19.0A exact annual OpenDART OCF audit",
        },
        "hard_guards":{
            "investment_score_100_calculated":False,
            "score_thresholds_changed":False,
            "production_api_changed":False,
            "source_value_imputed":False,
            "alternate_ocf_account_id_used":False,
            "unresolved_identity_force_mapped":False,
        },
    })
    META.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    RUNLOG.write_text("\n".join([
        f"VERSION={OCF_CONTRACT_VERSION}",
        f"REFRESH_VERSION={VERSION}",
        "PRODUCTION_UNIQUE_TICKERS=156",
        "OPERATING_CASH_FLOW_READY=154",
        "OPERATING_CASH_FLOW_LIMITED=2",
        "SCORER_READY=22",
        "SCORER_LIMITED=176",
        "SCORER_BLOCKERS=1618",
        "READY_DELTA=7",
        "BLOCKER_REDUCED_BY=7",
        "STRICT_IDENTITY_UNRESOLVED_COUNT=2",
        "NARROW_PATCH_COUNT=7",
        "PRODUCTION_OCF_CACHE_MODIFIED=true",
        "PRODUCTION_SCORE_WRITTEN=false",
        "PRODUCTION_API_CHANGED=false",
        "SCORING_POLICY_CHANGED=false",
        "STATUS=OK",
    ])+"\n",encoding="utf-8")

    post,ps=run_score(PROD,"v8193a_post")
    assert len(post)==198
    assert (int(ps["ready_count"]),int(ps["limited_count"]),blockers(post))==(22,176,1618)
    assert all(stable(post[c])==stable(staged[c]) for c in post)

    post_changed=[c for c in sorted(base) if stable(base[c])!=stable(post[c])]
    assert post_changed==targets
    lost=sorted(c for c in base if base[c].get("score_status")=="READY" and post[c].get("score_status")!="READY")
    newly=sorted(c for c in base if base[c].get("score_status")!="READY" and post[c].get("score_status")=="READY")
    assert lost==[]
    assert newly==targets

    summary={
        "version":VERSION,
        "generated_at_kst":now,
        "status":"PRODUCTION_CURRENT_OCF_PATCH_APPLIED_POST_REGRESSION_PASS",
        "policy_version":POLICY,
        "ocf_contract_version":OCF_CONTRACT_VERSION,
        "stage_version":STAGE_VERSION,
        "stage_result_commit":STAGE_COMMIT,
        "applied_ticker_count":7,
        "applied_tickers":targets,
        "production_before":{
            "row_count":149,
            "source_ready_count":147,
            "source_limited_count":2,
            "scorer_ready_count":15,
            "scorer_limited_count":183,
            "blocker_occurrences":1625,
        },
        "production_after":{
            "row_count":156,
            "source_ready_count":154,
            "source_limited_count":2,
            "scorer_ready_count":22,
            "scorer_limited_count":176,
            "blocker_occurrences":1618,
        },
        "ready_delta":7,
        "blocker_occurrences_reduced_by":7,
        "changed_score_row_count":7,
        "newly_ready_count":7,
        "lost_ready_count":0,
        "non_target_score_row_changed_count":0,
        "existing_ocf_row_changed_count":0,
        "post_score_equals_staged":True,
        "strict_identity_unresolved_count":2,
        "strict_identity_unresolved_tickers":["000480","002200"],
        "rollback_guard":{
            "enabled":True,
            "restores_production_csv":True,
            "restores_metadata_json":True,
            "restores_run_log":True,
        },
        "hard_guards":{
            "production_ocf_cache_modified":True,
            "production_ocf_metadata_modified":True,
            "production_ocf_run_log_modified":True,
            "production_source_cache_modified":False,
            "production_financial_cache_modified":False,
            "production_price_elasticity_cache_modified":False,
            "production_api_modified":False,
            "production_score_written":False,
            "scoring_policy_modified":False,
            "source_value_imputed":False,
            "alternate_ocf_account_id_used":False,
            "unresolved_identity_force_mapped":False,
            "non_target_score_row_changed":False,
        },
        "next_step":"POST_OCF_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8194A",
    }

    OUT_JSON.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=PRODUCTION_CURRENT_OCF_PATCH_APPLIED_POST_REGRESSION_PASS",
        "PRODUCTION_BEFORE_ROWS=149",
        "PRODUCTION_AFTER_ROWS=156",
        "SOURCE_READY=154",
        "SOURCE_LIMITED=2",
        "BASELINE_READY=15",
        "POST_READY=22",
        "BASELINE_LIMITED=183",
        "POST_LIMITED=176",
        "BASELINE_BLOCKERS=1625",
        "POST_BLOCKERS=1618",
        "READY_DELTA=7",
        "BLOCKER_REDUCED_BY=7",
        "CHANGED_SCORE_ROWS=7",
        "NEWLY_READY=7",
        "LOST_READY=0",
        "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
        "EXISTING_OCF_ROW_CHANGED_COUNT=0",
        "POST_SCORE_EQUALS_STAGED=true",
        "ROLLBACK_ENABLED=true",
        "PRODUCTION_SCORE_WRITTEN=false",
        "PRODUCTION_API_CHANGED=false",
        "SCORING_POLICY_CHANGED=false",
        "STATUS_OK=true",
        "NEXT_STEP=POST_OCF_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8194A",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    OUT_DOC.write_text(
        "# V8.19.3A controlled current OCF apply\n\n"
        "- Applied exactly seven validated exact-OCF rows.\n"
        "- Production OCF: 149 -> 156 rows; READY/LIMITED source rows: 147/2 -> 154/2.\n"
        "- Scorer READY/LIMITED: 15/183 -> 22/176.\n"
        "- Blockers: 1625 -> 1618 (-7).\n"
        "- Existing 149 OCF rows unchanged; non-target score drift 0; lost READY 0.\n"
        "- Production API, score, source, financial, elasticity, and policy unchanged.\n"
        "- Rollback restores OCF CSV, metadata, and run log on failure.\n\n"
        "Next: POST_OCF_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8194A\n",
        encoding="utf-8"
    )

    print("V8193A_CONTROLLED_OCF_APPLY=PASS")
    print("V8193A_OCF_ROWS=149->156")
    print("V8193A_READY=15->22")
    print("V8193A_BLOCKERS=1625->1618")
    print("V8193A_ROLLBACK_GUARD=ENABLED")

except Exception:
    rollback()
    raise
