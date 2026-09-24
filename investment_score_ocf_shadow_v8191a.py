import csv, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.19.1A-freeze-recoverable-ocf-shadow-current-score"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
AUDIT_VERSION="2026-09-24-v8.19.0A-current-actionable-ocf-single-blocker-audit"
AUDIT_COMMIT="3134bf6cff5e8576d2de0628629726618b848028"
OCF_CONTRACT_VERSION="2026-09-12-v8.7.4-audited-operating-cash-flow-source"
IFRS_OCF_ID="ifrs-full_CashFlowsFromUsedInOperatingActivities"
MISSING_REASON="영업현금흐름:MISSING_OCF_MARGIN_INPUT"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

AUDIT_CSV=ROOT/"latest/investment_score_ocf_actionable_v8190a.csv"
AUDIT_JSON=ROOT/"latest/investment_score_ocf_actionable_v8190a_summary_latest.json"
PROD_OCF=ROOT/"latest/investment_score_ocf_source_latest.csv"
PROD_META=ROOT/"latest/investment_score_ocf_source_latest.json"

SOURCE_OUT=ROOT/"latest/investment_score_ocf_source_v8191a.csv"
CAND_OUT=ROOT/"latest/investment_score_ocf_candidate_v8191a.csv"
COMPARE_OUT=ROOT/"latest/investment_score_ocf_shadow_v8191a.csv"
SUMMARY_OUT=ROOT/"latest/investment_score_ocf_shadow_v8191a_summary_latest.json"
LOG_OUT=ROOT/"latest/investment_score_ocf_shadow_v8191a_run_log_latest.txt"
DOC_OUT=ROOT/"docs/investment_score_ocf_shadow_v8191a.md"

BASE_CSV=Path("/tmp/v8191a_base.csv")
BASE_JSON=Path("/tmp/v8191a_base.json")
BASE_LOG=Path("/tmp/v8191a_base.log")
BASE_DOC=Path("/tmp/v8191a_base.md")
SH_CSV=Path("/tmp/v8191a_shadow.csv")
SH_JSON=Path("/tmp/v8191a_shadow.json")
SH_LOG=Path("/tmp/v8191a_shadow.log")
SH_DOC=Path("/tmp/v8191a_shadow.md")

EXPECTED={
    "000100":"유한양행",
    "005850":"에스엘",
    "006110":"삼아알미늄",
    "013870":"지엠비코리아",
    "014710":"사조씨푸드",
    "120110":"코오롱인더",
    "271560":"오리온",
}

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

def wrows(p,rs,fields):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        w.writerows(rs)

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def missing(r):
    return [x for x in str(r.get("missing_components") or "").split(";") if x]

def blockers(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_score(ocf_path,tag):
    oc=Path(f"/tmp/{tag}.csv"); oj=Path(f"/tmp/{tag}.json")
    ol=Path(f"/tmp/{tag}.log"); od=Path(f"/tmp/{tag}.md")
    old={k:getattr(scorer,k) for k in ("VERSION","OCF","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.OCF=Path(ocf_path)
        scorer.OUT_CSV=oc; scorer.OUT_JSON=oj; scorer.OUT_LOG=ol; scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8191A_SCORER_FAILED:"+str(rc))
    return rmap(oc), rj(oj)

audit=rj(AUDIT_JSON)
meta=rj(PROD_META)

assert audit["version"]==AUDIT_VERSION
assert audit["status"]=="AUDIT_ONLY_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS"
assert audit["policy_version"]==POLICY
assert audit["recoverable_count"]==7
assert set(audit["recoverable_tickers"])==set(EXPECTED)
assert audit["no_approved_exact_count"]==0
assert audit["official_query_incomplete_count"]==0
assert audit["conflict_count"]==0
assert audit["next_step"]=="FREEZE_RECOVERABLE_OCF_AND_SHADOW_CURRENT_SCORE_V8191A"

assert meta["version"]==OCF_CONTRACT_VERSION
assert meta["status"]=="READY_SOURCE_ONLY"
assert meta["production_unique_tickers"]==149
assert meta["account_id_policy"]=="EXACT_ONLY:"+IFRS_OCF_ID

audit_map=rmap(AUDIT_CSV)
prod_rows=rows(PROD_OCF)
prod_fields=list(prod_rows[0].keys())
prod_map=rmap(PROD_OCF)

assert len(prod_map)==149
assert not (set(EXPECTED)&set(prod_map))
assert set(audit_map)==set(EXPECTED)

frozen=[]
cand=dict(prod_map)

for code in sorted(EXPECTED):
    r=audit_map[code]
    assert r["name"]==EXPECTED[code]
    assert r["classification"]=="RECOVERABLE_EXACT_OCF_MARGIN_INPUT"
    assert r["source_status"]=="READY"
    assert r["account_id"]==IFRS_OCF_ID
    assert r["source_fs_div"] in {"CFS","OFS"}
    assert str(r["operating_cash_flow_annual"]).strip()

    names=json.loads(r.get("account_names_json") or "[]")
    account_nm=str(names[0]) if isinstance(names,list) and names else "영업활동현금흐름"

    fr={
        "ticker":code,
        "name":EXPECTED[code],
        "source_mode":"DIRECT_EXACT_IFRS_V8190A",
        "source_ticker":code,
        "source_corp_code":r.get("corp_code",""),
        "source_fs_div":r.get("source_fs_div",""),
        "account_id":IFRS_OCF_ID,
        "account_nm":account_nm,
        "operating_cash_flow_annual":r["operating_cash_flow_annual"],
        "source_status":"READY",
        "inheritance_evidence":"",
        "note":"V8.19.0A audited exact annual OCF",
    }
    frozen.append(fr)
    nr={f:"" for f in prod_fields}
    nr.update(fr)
    cand[code]=nr

wrows(SOURCE_OUT,frozen,prod_fields)
candidate=[cand[c] for c in sorted(cand)]
assert len(candidate)==156
wrows(CAND_OUT,candidate,prod_fields)

base,bs=run_score(PROD_OCF,"v8191a_base")
shadow,ss=run_score(CAND_OUT,"v8191a_shadow")

assert set(base)==set(shadow)
assert len(base)==198
assert set(EXPECTED)<=set(base)

changed=[c for c in sorted(base) if stable(base[c])!=stable(shadow[c])]
assert changed==sorted(EXPECTED)

non_target=sorted(set(changed)-set(EXPECTED))
assert non_target==[]

compare=[]
newly=[]
for code in sorted(EXPECTED):
    b=base[code]; s=shadow[code]
    bm=missing(b); sm=missing(s)
    assert b.get("score_status")=="LIMITED"
    assert bm==[MISSING_REASON]
    assert MISSING_REASON not in sm
    assert s.get("score_status")=="READY"
    newly.append(code)
    compare.append({
        "ticker":code,
        "name":EXPECTED[code],
        "operating_cash_flow_annual":audit_map[code]["operating_cash_flow_annual"],
        "ocf_margin_pct_if_promoted":audit_map[code]["ocf_margin_pct_if_promoted"],
        "source_fs_div":audit_map[code]["source_fs_div"],
        "baseline_status":b.get("score_status",""),
        "shadow_status":s.get("score_status",""),
        "baseline_missing_components":";".join(bm),
        "shadow_missing_components":";".join(sm),
        "baseline_score_total":b.get("score_total",""),
        "shadow_score_total":s.get("score_total",""),
    })

wrows(COMPARE_OUT,compare,list(compare[0].keys()))

br=int(bs["ready_count"]); bl=int(bs["limited_count"]); bb=blockers(base)
sr=int(ss["ready_count"]); sl=int(ss["limited_count"]); sb=blockers(shadow)

assert (br,bl,bb)==(15,183,1625), (br,bl,bb)
assert (sr,sl,sb)==(22,176,1618), (sr,sl,sb)
assert sr-br==7
assert bl-sl==7
assert bb-sb==7

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"SOURCE_ONLY_FROZEN_SHADOW_PASS",
    "policy_version":POLICY,
    "v8190a_version":AUDIT_VERSION,
    "v8190a_result_commit":AUDIT_COMMIT,
    "ocf_contract_version":OCF_CONTRACT_VERSION,
    "source_frozen_count":7,
    "source_frozen_tickers":sorted(EXPECTED),
    "current_scorer_universe_count":198,
    "production_ocf_row_count":149,
    "shadow_ocf_row_count":156,
    "baseline_ready_count":15,
    "baseline_limited_count":183,
    "shadow_ready_count":22,
    "shadow_limited_count":176,
    "ready_delta":7,
    "newly_ready_count":7,
    "newly_ready_tickers":sorted(newly),
    "baseline_blocker_occurrences":1625,
    "shadow_blocker_occurrences":1618,
    "blocker_occurrences_reduced_by":7,
    "ocf_reason_removed_count":7,
    "ocf_reason_removed_tickers":sorted(EXPECTED),
    "non_target_score_row_changed_count":0,
    "existing_ocf_row_changed_count":0,
    "hard_guards":{
        "production_ocf_cache_modified":False,
        "production_ocf_metadata_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_price_elasticity_cache_modified":False,
        "production_api_modified":False,
        "scoring_policy_modified":False,
        "source_value_imputed":False,
        "alternate_ocf_account_id_used":False,
        "production_score_written":False,
    },
    "automatic_promotion":False,
    "next_step":"STAGE_CURRENT_OCF_PATCH_V8192A",
}

SUMMARY_OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
LOG_OUT.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
    "SOURCE_FROZEN_COUNT=7",
    "CURRENT_SCORER_UNIVERSE=198",
    "PRODUCTION_OCF_ROWS=149",
    "SHADOW_OCF_ROWS=156",
    "BASELINE_READY=15",
    "BASELINE_LIMITED=183",
    "SHADOW_READY=22",
    "SHADOW_LIMITED=176",
    "READY_DELTA=7",
    "BASELINE_BLOCKERS=1625",
    "SHADOW_BLOCKERS=1618",
    "BLOCKER_REDUCED_BY=7",
    "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
    "EXISTING_OCF_ROW_CHANGED_COUNT=0",
    "PRODUCTION_OCF_CACHE_MODIFIED=false",
    "PRODUCTION_SCORE_WRITTEN=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    "NEXT_STEP=STAGE_CURRENT_OCF_PATCH_V8192A",
])+"\n",encoding="utf-8")

DOC_OUT.parent.mkdir(parents=True,exist_ok=True)
DOC_OUT.write_text(
    "# V8.19.1A recoverable OCF freeze and shadow\n\n"
    "- Seven exact annual OCF values audited in V8.19.0A are frozen as source-only candidates.\n"
    "- Production OCF cache remains 149 rows; shadow candidate is 156 rows.\n"
    "- READY / LIMITED: 15 / 183 -> 22 / 176.\n"
    "- Blockers: 1625 -> 1618 (-7).\n"
    "- Each target was a single OCF blocker and becomes READY in shadow.\n"
    "- Existing production OCF rows changed: 0.\n"
    "- Non-target score drift: 0.\n"
    "- Production cache, API, score, and policy remain unchanged.\n\n"
    "Next: STAGE_CURRENT_OCF_PATCH_V8192A\n",
    encoding="utf-8"
)

print("V8191A_OCF_FREEZE_SHADOW=PASS")
print("V8191A_READY=15->22")
print("V8191A_BLOCKERS=1625->1618")
